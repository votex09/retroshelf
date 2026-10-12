#!/usr/bin/env python3
"""RetroShelf's Python side for the Electron app: the window asks, this answers, over stdin / stdout.

Protocol: one JSON object per line.
    window -> helper   {"id": 1, "method": "systems", "params": {"roms": "/home/deck/retrodeck/roms"}}
    helper -> window   {"id": 1, "result": [...]}
                       {"id": 1, "error": {"type": "FileNotFoundError", "message": "..."}}
                       {"event": "name", "data": {...}}   (not tied to a request: progress, things that changed)
Each request runs on its own thread, so a slow one (a download, a scan) doesn't hold up the rest; answers can come
back in any order, matched by id. Anything else the helper prints goes to stderr, never stdout.

The work itself is RetroShelf's own lib/ modules, the same ones the Tk app uses. Settings, the move log and LaunchBox
data live in RETROSHELF_DATA (the Electron app sets it to its own data folder), in the Tk app's formats:
config.json, moves.json, cache/. Requests that change the open system run one at a time."""
import json, os, platform, shutil, sys, threading, traceback

if getattr(sys, "frozen", False):  # bundled by PyInstaller: lib/ modules are inside the bundle
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.path.join(APP_DIR, "lib"))

# Where Linux systems keep their trusted certificates: Debian / Ubuntu / Arch / SteamOS, Fedora, openSUSE, others
CA_BUNDLES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt",
              "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem", "/etc/ssl/ca-bundle.pem", "/etc/ssl/cert.pem")


def use_system_certificates():
    """The bundled helper's OpenSSL looks for trusted certificates where the machine that built it keeps them
    (Ubuntu's /usr/lib/ssl). SteamOS, Arch and Fedora have nothing there, so every https request (YouTube, LaunchBox,
    updates) would fail to verify: point it at this computer's own certificates instead."""
    if sys.platform != "linux" or os.environ.get("SSL_CERT_FILE"):
        return
    import ssl
    p = ssl.get_default_verify_paths()
    if (p.cafile and os.path.isfile(p.cafile)) or (p.capath and os.path.isdir(p.capath) and os.listdir(p.capath)):
        return
    for f in CA_BUNDLES:
        if os.path.isfile(f):
            os.environ["SSL_CERT_FILE"] = f
            return


use_system_certificates()


def use_system_libraries():
    """The bundled helper starts with LD_LIBRARY_PATH pointing at its own libraries (PyInstaller's doing), and every
    program it runs would inherit that: flatpak or chdman on SteamOS then loads Ubuntu's older libssl / libexpat and
    fails, so RetroDECK's tools look missing. This process has already loaded what it needs; give the programs it runs
    back the path it was started with."""
    if not getattr(sys, "frozen", False) or sys.platform != "linux":
        return
    orig = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig:
        os.environ["LD_LIBRARY_PATH"] = orig
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)


use_system_libraries()

import esde_collections  # noqa: E402
import hiding  # noqa: E402
import holding  # noqa: E402
import launchbox as lb  # noqa: E402
import library  # noqa: E402
import nps  # noqa: E402
import rules  # noqa: E402
import scraper  # noqa: E402
import shelf  # noqa: E402
from fsutil import write_json  # noqa: E402

import rpc  # noqa: E402
from rpc import METHODS, event, method, send  # noqa: E402

PROTOCOL = 1


# ---------- methods the window can call ----------
@method
def hello():
    return {"protocol": PROTOCOL, "python": platform.python_version(), "platform": sys.platform,
            "frozen": bool(getattr(sys, "frozen", False))}


@method
def roms_folder():
    """Where RetroDECK / ES-DE keeps its ROMs on this computer, or "" when it can't be found."""
    return library.guess_roms_root(APP_DIR)


@method
def systems(roms):
    if not roms or not os.path.isdir(roms):
        raise FileNotFoundError(f"No folder at {roms!r}")
    return [{"code": code, "name": name, "games": n} for code, name, n in library.systems(roms)]


@method
def disk(path):
    """-> {"free", "total"} bytes on the drive path is on, or None."""
    while path and not os.path.exists(path) and os.path.dirname(path) != path:
        path = os.path.dirname(path)
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {"free": usage.free, "total": usage.total}


# ---------- the main window: one system at a time ----------
DATA_DIR = os.environ.get("RETROSHELF_DATA") or APP_DIR
CONFIG = os.path.join(DATA_DIR, "config.json")
MOVES = os.path.join(DATA_DIR, "moves.json")
CFG_DEFAULTS = {"roms_root": "", "holding_root": "", "system": "", "platform_overrides": {},
                "region_priority": rules.DEFAULT_PRIORITY, "system_state": {}, "esde_bases": [],
                "setup_offered": False, "play_videos": True, "gamepad": True, "animations": True,
                "show_details": True, "check_updates": True, "theme": "dark",
                "stream_videos": False}
_state_lock = threading.Lock()  # one system-changing request at a time
cfg = {}
current = {"sc": None, "decision": None, "fullname": None}


def load_cfg():
    cfg.clear()
    cfg.update(json.loads(json.dumps(CFG_DEFAULTS)))
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except ValueError:  # unreadable: set it aside rather than overwrite it
        try:
            os.replace(CONFIG, CONFIG + ".bad")
        except OSError:
            pass
    except OSError:
        pass


def save_cfg():
    os.makedirs(DATA_DIR, exist_ok=True)
    write_json(CONFIG, cfg, indent=1)


def priority():
    return rules.parse_priority(cfg["region_priority"])


def _systems_list():
    root = cfg["roms_root"]
    if not root or not os.path.isdir(root):
        return []
    return [{"code": code, "name": name, "games": n} for code, name, n in library.systems(root)]


def _overview():
    root = cfg["roms_root"]
    return {"roms": root, "systems": _systems_list(), "system": cfg["system"],
            "holding": shelf.holding_root(cfg) if root else "", "launchbox": bool(lb.platforms())}


@method
def startup():
    """Where things stand when the window opens: the ROMs folder (found if it isn't set), its systems, and the
    system that was open last."""
    with _state_lock:
        load_cfg()
        if not cfg["roms_root"] or not os.path.isdir(cfg["roms_root"]):
            cfg["roms_root"] = library.guess_roms_root(APP_DIR, cfg["esde_bases"])
        return {**_overview(), "setup_offered": cfg["setup_offered"]}


@method
def set_roms(path):
    with _state_lock:
        if not os.path.isdir(path):
            raise FileNotFoundError(f"No folder at {path}")
        cfg["roms_root"] = path
        save_cfg()
        current["sc"] = None
        return _overview()


def _game_row(sc, key, d):
    u = sc.units[key]
    g = sc.ratings.get(key)
    paths = u["paths"]
    thumb = library.media_for(os.path.join(scraper.media_root(sc.roms_root), sc.system), library.stems_of(paths),
                              types=("covers", "3dboxes", "miximages"))
    return {
        "key": key,
        "label": os.path.basename(paths[0]) if len(paths) == 1 else f"{key}  [{len(paths)} files]",
        "size": u["size"], "regions": list(sc.regions[key]),
        "rating": g["r"] if g else None, "votes": g["v"] if g else 0, "genres": g["g"] if g else [],
        "played": key in sc.played, "hidden": key in sc.hidden, "manual_match": sc.lb_kind.get(key) == "manual",
        "move": key in d.to_move, "why": d.why[key],
        "thumb": thumb[0][1] if thumb else None,
    }


def _decision_out(sc, d):
    return {"move": d.to_move, "why": d.why, "tabs": d.tab_counts()}


@method
def open_system(system):
    """Scan a system and decide with its saved filters. -> everything the window shows for it."""
    with _state_lock:
        root = cfg["roms_root"]
        if not root or not os.path.isdir(root):
            raise FileNotFoundError("Pick your ROMs folder first")
        folder = os.path.join(root, system)
        name, fullname, exts = library.read_systeminfo(folder)
        fullname = fullname if name == system else nps.FULL_NAMES.get(system)
        exts = exts if name == system else None
        platform = lb.resolve_platform(system, fullname, cfg["platform_overrides"])
        sc = shelf.scan(root, system, folder, exts, platform)
        state = {**shelf.DEFAULT_STATE, **cfg["system_state"].get(system, {})}
        state["flips"] = {k: v for k, v in (state.get("flips") or {}).items() if k in sc.units}
        d = shelf.decide(sc, state, priority())
        current.update(sc=sc, decision=d, fullname=fullname)
        cfg["system"] = system
        save_cfg()
        return {
            "system": system, "fullname": fullname or system, "platform": platform,
            "warning": "" if name in (None, system) else
                       f"This folder's systeminfo.txt is for '{name}', so it's ignored.",
            "state": {k: state[k] for k in shelf.DEFAULT_STATE},
            "cursor": cfg["system_state"].get(system, {}).get("cursor_key"),
            "presets": [{"key": p, "label": rules.PRESET_LABELS.get(p, p)} for p in rules.PRESETS] +
                       [{"key": "Partial downloads (.part)", "label": "Partial downloads (.part)"}],
            "region_modes": rules.REGION_MODES,
            "genres": sc.genre_counts.most_common(), "regions": sc.region_counts.most_common(),
            "played": len(sc.played), "matched": sc.matched, "rated": sc.rated,
            "games": [_game_row(sc, k, d) for k in sorted(sc.units)],
            "decision": _decision_out(sc, d),
            "disk": disk(root),
        }


def _need_system():
    if not current["sc"]:
        raise RuntimeError("No system is open")
    return current["sc"]


@method
def decide(state, cursor_key=None):
    """The filters changed (or a game was flipped): decide again, and remember them for this system."""
    with _state_lock:
        sc = _need_system()
        state = {k: state.get(k, v) for k, v in shelf.DEFAULT_STATE.items()}
        d = shelf.decide(sc, state, priority())
        current["decision"] = d
        saved = {**state, "flips": {k: bool(v) for k, v in state["flips"].items()}}
        if cursor_key is not None:
            saved["cursor_key"] = cursor_key
        if cfg["system_state"].get(sc.system) != saved:
            cfg["system_state"][sc.system] = saved
            save_cfg()
        return _decision_out(sc, d)


@method
def remember_cursor(key):
    with _state_lock:
        sc = _need_system()
        st = cfg["system_state"].setdefault(sc.system, {})
        if st.get("cursor_key") != key:
            st["cursor_key"] = key
            save_cfg()


_details_cache = {}  # platform -> LaunchBox details


@method
def details(key):
    """What the details panel shows for one game: LaunchBox text, artwork and video on disk."""
    sc = _need_system()
    u = sc.units.get(key)
    if not u:
        raise KeyError(f"No game {key!r} here")
    g, gid = sc.ratings.get(key), sc.lb_ids.get(key)
    if sc.platform and sc.platform not in _details_cache:
        _details_cache[sc.platform] = lb.load_details(sc.platform)
    det = _details_cache.get(sc.platform, {}).get(gid, {}) if gid else {}
    media_dir = os.path.join(scraper.media_root(sc.roms_root), sc.system)
    stems = library.stems_of(u["paths"])
    names = [os.path.basename(p.rstrip("/\\")) for p in u["paths"]]
    kind = sc.lb_kind.get(key)
    return {
        "key": key, "title": g["n"] if g else rules.title_of(key),
        "console": nps.FULL_NAMES.get(sc.system) or current["fullname"] or sc.platform or sc.system,
        "year": (det.get("rd") or "")[:4], "developer": det.get("d"), "publisher": det.get("p"),
        "players": det.get("mp"), "description": (det.get("o") or "").strip(),
        "rating": g["r"] if g else None, "votes": g["v"] if g else 0, "genres": g["g"] if g else [],
        "match": (f"{g['n']} ({'picked by hand' if kind == 'manual' else kind})" if g else
                  "no match (set by hand)" if kind == "manual" else "no match"),
        "file": names[0] if len(names) == 1 else f"{key}  [{len(names)} files]", "size": u["size"],
        "images": [{"type": t, "path": p} for t, p in library.media_for(media_dir, stems)],
        "video": library.video_for(media_dir, stems),
        "installed": u["extra"],
    }


@method
def move_plan(dest="to_delete"):
    """What Move would do, for the window to confirm."""
    sc, d = _need_system(), current["decision"]
    rpc.need_free(sc.system)
    dest_dir = os.path.join(shelf.holding_root(cfg), dest, sc.system)
    return {"games": len(d.to_move), "files": sum(len(sc.units[k]["paths"]) for k in d.to_move),
            "size": sum(sc.units[k]["size"] for k in d.to_move), "dest_dir": dest_dir,
            "installed": sum(bool(sc.units[k]["extra"]) for k in d.to_move),
            "same_drive": shelf.on_same_drive(shelf.holding_root(cfg), sc.roms_root)}


@method
def move(dest="to_delete"):
    """Move the Moving list's games into the holding folder, log it, and open the system again."""
    if dest not in ("to_delete", "review_low_value"):
        raise ValueError(f"Unknown destination {dest!r}")
    with _state_lock:
        sc, d = _need_system(), current["decision"]
        rpc.need_free(sc.system)
        keys = list(d.to_move)
        dest_dir = os.path.join(shelf.holding_root(cfg), dest, sc.system)
        size = sum(sc.units[k]["size"] for k in keys)
        moved, failed, done = shelf.move_games(sc, keys, dest_dir)
        if done:
            shelf.write_moves(MOVES, shelf.read_moves(MOVES) + [shelf.move_batch(sc.system, dest, len(keys), size,
                                                                                 done)])
    result = open_system(sc.system)
    result["moved"] = {"files": moved, "failed": failed, "dest": dest}
    return result


@method
def download_launchbox(job=None):
    """Download LaunchBox's database (about 110 MB, once); progress arrives as "launchbox" events (and "progress" ones
    for job, which can be stopped: nothing changes then)."""
    report, stop = (rpc.progress(job), rpc.stopped(job)) if job else (lambda m: None, lambda: False)

    def say(msg):
        event("launchbox", {"message": msg})
        report(msg)
    if not lb.update(progress=say, stop=stop):
        return {"stopped": True}
    _details_cache.clear()
    return {"platforms": len(lb.platforms()), "stopped": False}


@method
def rescan():
    """Scan the open system again (files changed on disk, or a match / ES-DE setting changed)."""
    return open_system(_need_system().system)


@method
def export_moves(path):
    """Write the Moving list's file names to a text file, one per line."""
    sc, d = _need_system(), current["decision"]
    with open(path, "w", encoding="utf-8") as f:
        for k in d.to_move:
            f.writelines(os.path.basename(p) + "\n" for p in sc.units[k]["paths"])
    return {"games": len(d.to_move)}


# ---------- ES-DE: hiding games, picking LaunchBox matches ----------
@method
def hide_check(keys, hide=True):
    """What hiding (or showing) these games would do, for the window to confirm."""
    sc = _need_system()
    rpc.need_free(sc.system)
    keys = [k for k in keys if k in sc.units and (k in sc.hidden) != hide]
    return {"games": len(keys), "es_de_running": scraper.es_de_running(),
            "shows_hidden": bool(hiding.shows_hidden(esde_collections.home(sc.roms_root)))}


@method
def hide(keys, hide=True):
    """Mark games hidden in ES-DE's gamelist (or show them again). Hidden games stay in Keeping, like played ones,
    unless flipped by hand; a flip that sent one to Moving is dropped. -> the system opened again, with "hidden":
    how many changed."""
    with _state_lock:
        sc = _need_system()
        rpc.need_free(sc.system)
        keys = [k for k in keys if k in sc.units and (k in sc.hidden) != hide]
        if keys:
            if scraper.es_de_running():
                raise RuntimeError("Close RetroDECK / ES-DE first: it rewrites its gamelists when it quits, which "
                                   "would undo this.")
            es_home = esde_collections.home(sc.roms_root)
            hiding.set_hidden(scraper.gamelist_path(sc.roms_root, sc.system),
                              [scraper.primary_file(sc.units[k]["paths"]) for k in keys], hide)
            if hide and hiding.shows_hidden(es_home):
                hiding.stop_showing_hidden(es_home)
            flips = cfg["system_state"].get(sc.system, {}).get("flips", {})
            for k in keys:
                if flips.get(k):
                    flips.pop(k)
            save_cfg()
    result = open_system(sc.system)
    result["hidden"] = len(keys)
    return result


@method
def match_search(key, query):
    """LaunchBox games for the "which game is this?" picker."""
    sc = _need_system()
    if not sc.platform:
        raise RuntimeError("LaunchBox has no platform for this system")
    m = lb.Matcher(sc.platform)
    if not m.ok:
        raise RuntimeError("Download LaunchBox data first")
    out = []
    for gid in m.search(query):
        x = m.games[gid]
        alts = [a for a in m.alts.get(gid, []) if lb.norm(a) != lb.norm(x["n"])]
        out.append({"id": gid, "name": x["n"], "aka": alts[0] if alts else "", "rating": x["r"], "votes": x["v"],
                    "genres": x["g"]})
    title = rules.title_of(key)
    return {"results": out, "current": sc.lb_links.get(key), "kind": sc.lb_kind.get(key), "title": title,
            "same_title": sum(rules.title_of(k) == title for k in sc.units)}


@method
def set_match(key, gid=None, clear=False):
    """Pick the LaunchBox game for key (gid None: not in LaunchBox; clear: back to automatic), then rescan."""
    sc = _need_system()
    lb.set_manual(sc.platform, rules.title_of(key), gid, clear)
    return open_system(sc.system)


# ---------- ES-DE custom collections ----------
@method
def collections():
    """The user's ES-DE custom collections, with how many games each has, and the one last saved to."""
    home = esde_collections.home(cfg["roms_root"])
    return {"names": {n: len(esde_collections.games(p)) for n, p in esde_collections.names(home).items()},
            "last": cfg.get("last_collection", "")}


@method
def save_collection(keys, name, replace=False, show=True):
    """Put these games into an ES-DE custom collection, new or existing (replace: instead of what's in it);
    show: turn it on in ES-DE too."""
    sc = _need_system()
    home = esde_collections.home(cfg["roms_root"])
    name = esde_collections.clean_name(name)
    if not name:
        raise ValueError("Give the collection a name")
    existing = esde_collections.names(home)
    files = [scraper.primary_file(sc.units[k]["paths"]) for k in keys if k in sc.units]
    replace = bool(replace) and name in existing
    added = esde_collections.save(home, name, files, cfg["roms_root"], replace=replace)
    note = ""
    if show:
        if scraper.es_de_running():
            note = "Close ES-DE and save again to have it shown, or turn it on in ES-DE's Game collection settings."
        else:
            try:
                esde_collections.enable(home, name)
            except OSError as e:
                note = f"Couldn't turn it on in ES-DE: {e}"
    with _state_lock:
        cfg["last_collection"] = name
        save_cfg()
    return {"name": name, "added": added, "files": len(files), "replaced": replace, "new": name not in existing,
            "note": note}


# ---------- settings ----------
@method
def region_priority():
    """Regions in the order region dupes keeps them, the ones this system has first; with game counts here."""
    sc = _need_system()
    saved = [p.strip() for p in cfg["region_priority"].split(",") if p.strip()]
    low = [p.lower() for p in saved]
    present = [r for r in sc.region_names if r != "(none)"]
    order = [p for p in saved if p in present] + [r for r in present if r.lower() not in low]
    order += [p for p in saved if p not in order]
    return {"order": order, "counts": dict(sc.region_counts), "default": rules.DEFAULT_PRIORITY.split(", ")}


@method
def set_region_priority(order):
    with _state_lock:
        sc = _need_system()
        cfg["region_priority"] = ", ".join(order)
        save_cfg()
        sc.dupes_key = None
    return decide(_saved_state(sc))


def _saved_state(sc):
    return {**shelf.DEFAULT_STATE, **cfg["system_state"].get(sc.system, {})}


@method
def set_holding(path):
    with _state_lock:
        if not os.path.isdir(path):
            raise FileNotFoundError(f"No folder at {path}")
        cfg["holding_root"] = path
        save_cfg()
        return _overview()


# ---------- the holding folder and the move log ----------
def _holding_out():
    root = shelf.holding_root(cfg)
    games, origin = holding.holding_games(root, shelf.read_moves(MOVES))
    games.sort(key=lambda g: g["moved"], reverse=True)
    current["holding"] = (games, origin)
    return {"root": root, "same_drive": shelf.on_same_drive(root, cfg["roms_root"]) if cfg["roms_root"] else False,
            "games": [{"id": i, "dest": g["dest"], "system": g["system"], "key": g["key"], "size": g["size"],
                       "moved": g["moved"], "files": len(g["paths"]), "installed": len(g["extra"]),
                       "label": os.path.basename(g["paths"][0]) if len(g["paths"]) == 1 else
                       f"{g['key']}  [{len(g['paths'])} files]"} for i, g in enumerate(games)]}


@method
def holding_list():
    with _state_lock:
        return _holding_out()


def _picked(ids):
    games = current.get("holding", ([], {}))[0]
    return [games[i] for i in ids if 0 <= i < len(games)]


@method
def holding_restore(ids):
    """Put these games (ids from holding_list) back where they came from."""
    with _state_lock:
        root = shelf.holding_root(cfg)
        origin = current.get("holding", ([], {}))[1]
        rpc.need_free(*{g["system"] for g in _picked(ids)})
        back, failed, done = holding.restore_games(_picked(ids), origin, cfg["roms_root"], root)
        try:
            shelf.write_moves(MOVES, holding.drop_from_log(shelf.read_moves(MOVES), done))
        except OSError as e:
            failed.append(f"move log: {e}")
        return {"back": back, "failed": failed, "holding": _holding_out()}


@method
def holding_delete(ids, forget=True):
    """Delete these games for good; forget: also remove their ES-DE artwork and gamelist entries."""
    with _state_lock:
        root = shelf.holding_root(cfg)
        if forget:  # (their gamelist entries go)
            rpc.need_free(*{g["system"] for g in _picked(ids)})
        gone, failed, by_system = holding.delete_games(_picked(ids), root)
        try:
            shelf.write_moves(MOVES, holding.drop_from_log(shelf.read_moves(MOVES), gone))
        except OSError as e:
            failed.append(f"move log: {e}")
        if forget:
            for system, names in by_system.items():
                failed += scraper.forget_games(names, system, cfg["roms_root"],
                                               scraper.find_gamelist(cfg["roms_root"], system))[2]
        return {"deleted": len(gone), "failed": failed, "holding": _holding_out(), "disk": disk(cfg["roms_root"])}


@method
def moves():
    """Every Move run, newest first, with how much of it is still in the holding folder."""
    out = []
    for i, b in enumerate(shelf.read_moves(MOVES)):
        out.append({"id": i, "time": b["time"], "system": b["system"], "dest": b["dest"], "games": b["games"],
                    "size": b["size"], "files": len(b["moves"]), "left": sum(os.path.exists(t) for _, t in b["moves"])})
    return out[::-1]


@method
def restore_moves(ids):
    """Undo whole Move runs (ids from moves())."""
    with _state_lock:
        batches = shelf.read_moves(MOVES)
        rpc.need_free(*{batches[i].get("system") for i in ids if 0 <= i < len(batches)})
        back, failed, left = holding.restore_batches(batches, ids, shelf.holding_root(cfg))
        try:
            shelf.write_moves(MOVES, left)
        except OSError as e:
            failed.append(f"move log: {e}")
        return {"back": back, "failed": failed}


# ---------- the tool windows (app/helper/tool_*.py) ----------
rpc.ctx.update(cfg=cfg, save_cfg=save_cfg, need_system=_need_system, open_system=open_system, current=current,
               state_lock=_state_lock, data_dir=DATA_DIR, app_dir=APP_DIR, overview=_overview,
               reload_cfg=load_cfg)
import tool_browse  # noqa: E402,F401
import tool_files  # noqa: E402,F401
import tool_library  # noqa: E402,F401
import tool_rename  # noqa: E402,F401
import tool_scrape  # noqa: E402,F401
import tool_settings  # noqa: E402,F401
import tool_setup  # noqa: E402,F401
import tool_sources  # noqa: E402,F401
import tool_stores  # noqa: E402,F401
import tool_video  # noqa: E402,F401


# ---------- plumbing ----------
def handle(msg):
    rid = msg.get("id")
    try:
        fn = METHODS.get(msg.get("method"))
        if fn is None:
            raise LookupError(f"No method called {msg.get('method')!r}")
        result = fn(**(msg.get("params") or {}))
        send({"id": rid, "result": result})
    except Exception as e:  # the window shows it; the helper keeps going
        traceback.print_exc(file=sys.stderr)
        send({"id": rid, "error": {"type": type(e).__name__, "message": str(e)}})


def main():
    rpc.set_output(sys.stdout)
    sys.stdout = sys.stderr  # stray prints from lib/ code can't corrupt the protocol
    event("ready", hello())
    running = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            send({"id": None, "error": {"type": "ValueError", "message": f"Not JSON: {line[:200]}"}})
            continue
        t = threading.Thread(target=handle, args=(msg,), daemon=True)
        t.start()
        running = [x for x in running if x.is_alive()] + [t]
    for t in running:  # the window closed our stdin: finish what was asked, then stop
        t.join()


if __name__ == "__main__":
    main()
