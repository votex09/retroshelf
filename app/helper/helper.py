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

import launchbox as lb  # noqa: E402
import library  # noqa: E402
import nps  # noqa: E402
import rules  # noqa: E402
import scraper  # noqa: E402
import shelf  # noqa: E402
from fsutil import write_json  # noqa: E402

PROTOCOL = 1
_out = sys.stdout
_lock = threading.Lock()
METHODS = {}


def method(fn):
    METHODS[fn.__name__] = fn
    return fn


def send(obj):
    line = json.dumps(obj, ensure_ascii=False)
    with _lock:
        _out.write(line + "\n")
        _out.flush()


def event(name, data=None):
    send({"event": name, "data": data})


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
                "region_priority": rules.DEFAULT_PRIORITY, "system_state": {}}
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
            cfg["roms_root"] = library.guess_roms_root(APP_DIR)
        return _overview()


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
        "played": key in sc.played, "hidden": key in sc.hidden,
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
def download_launchbox():
    """Download LaunchBox's database (about 110 MB, once); progress arrives as "launchbox" events."""
    lb.update(progress=lambda msg: event("launchbox", {"message": msg}))
    _details_cache.clear()
    return {"platforms": len(lb.platforms())}


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
    global _out
    _out = sys.stdout
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
