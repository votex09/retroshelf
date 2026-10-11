"""Tools → NoPayStation, and the homebrew stores (Homebrew Hub, itch.io, PDRoms, MAMEDEV): get games into the ROMs
folder. They need a ROMs folder, not an open system.

NoPayStation: the lists and each row's status come from lib/nps_queue.py; the window keeps the queue and hands the
rows to nps_run, which downloads and installs them as a job ("progress" events carry each row's status by its key).
The stores: one window for all four, a "store" naming its source in lib/catalog.py. Games the user downloads in their
browser are filed by a Downloads watcher per store, which the window polls with store_watch."""
import base64, os, shutil, threading, time, urllib.request

import artwork
import catalog
import downloads
import homebrew as hb
import itch
import launchbox as lb
import library
import mamedev
import nps
import nps_queue
import pdroms
import scraper
import shelf
from fsutil import is_windows
from rpc import ctx, event, method, stopped

# their lists are kept in the data folder, like LaunchBox's
for _module, _name in ((nps, "nps"), (hb, "homebrew"), (itch, "itch"), (pdroms, "pdroms"), (mamedev, "mamedev")):
    _module.CACHE = os.path.join(ctx["data_dir"], "cache", _name)
nps.STATE = os.path.join(nps.CACHE, "state.json")


def _roms():
    root = ctx["cfg"]["roms_root"]
    if not root or not os.path.isdir(root):
        raise FileNotFoundError("Pick your ROMs folder first")
    return root


def _open_system():
    sc = ctx["current"]["sc"]
    return sc.system if sc else ctx["cfg"].get("system")


# ---------- NoPayStation ----------
_nps = {"rows": {}, "lib": None}  # (system, kind) -> rows; the Library of the system the window is on
_nps_lock = threading.RLock()


def _key(r):
    return f"{r['kind']}|{r['content_id'] or r['id']}|{r.get('version', '')}"


def _units(system, roms):
    """The system's games: the open system's scan, else a quick one (no LaunchBox)."""
    sc = ctx["current"]["sc"]
    if sc and sc.system == system and sc.roms_root == roms:
        return sc.units
    folder = os.path.join(roms, system)
    return shelf.scan(roms, system, folder, library.valid_exts(folder, system), None).units


def _lib(system, fresh=False):
    with _nps_lock:
        lib, roms = _nps["lib"], _roms()
        if fresh or not lib or lib.system != system or lib.roms_root != roms:
            lib = _nps["lib"] = nps_queue.Library(system, roms, _units(system, roms))
        return lib


def _nps_out(r, status, lib):
    return {"key": _key(r), "name": nps_queue.row_name(r), "label": f"{r['name']}  ({r['id']}, {r['kind']})",
            "id": r["id"], "region": nps.REGIONS.get(r["region"], r["region"]), "size": r["size"], "kind": r["kind"],
            "status": status, "have": lib.have(r)[:3]}


def _list_date(system):
    age = nps.list_age(system)
    return f"Lists from {time.strftime('%Y-%m-%d', time.localtime(age))}" if age else ""


@method
def nps_info(system=None):
    """What the NoPayStation window shows for a system (the open one when it's a PlayStation, else the last one)."""
    cfg = ctx["cfg"]
    nps.emulator_dirs.update(cfg.get("emulator_dirs", {}))
    system = system or next((s for s in (_open_system(), cfg.get("nps_system")) if s in nps.CONSOLES), "ps3")
    if cfg.get("nps_system") != system:
        cfg["nps_system"] = system
        ctx["save_cfg"]()
    roms = _roms()
    console, kinds = nps.CONSOLES[system]
    _lib(system, fresh=True)  # look at what's here afresh each time the window opens
    emulator = nps.SYSTEM_EMULATOR.get(system)
    return {"system": system, "console": console, "console_name": nps.FULL_NAMES[system], "kinds": list(kinds), "regions": nps_queue.REGION_CHOICES,
            "systems": [[s, nps.FULL_NAMES[s]] for s in nps.CONSOLES], "note": nps_queue.INSTALL_NOTES[console],
            "problem": nps.firmware_problem(system, roms), "age": _list_date(system), "mine": system in ("ps3", "psvita"),
            "dir": nps_queue.default_dir(cfg), "keep_pkg": cfg.get("nps_keep_pkg", False),
            "scrape": cfg.get("nps_scrape", True),
            "emulator": {"name": emulator, "label": nps.EMULATOR_NAMES[emulator], "exe": nps.EMULATOR_EXES[emulator],
                         "path": nps.find_emulator(emulator, roms) or "not found"} if is_windows() and emulator else None}


@method
def nps_load(job, system, kind):
    """Load one of the system's lists (downloading it the first time; Updates ask Sony's server) -> a status line."""
    roms, report = _roms(), lambda m: event("progress", {"job": job, "message": m, "done": 0, "total": 0})
    if nps.CONSOLES[system][1][kind] is None:
        rows = nps.load_updates(roms, report)
        message = f"{len(rows)} updates found for {len(_lib(system).owned_ids)} games"
    else:
        rows, message = nps.load_list(system, kind), ""
    _nps["rows"][(system, kind)] = rows
    return {"message": message, "age": _list_date(system)}


@method
def nps_refresh(system):
    """Download the system's NPS lists again."""
    for name in nps.CONSOLES[system][1].values():
        if name:
            nps.fetch_list(name)
    for k in [k for k in _nps["rows"] if k[0] == system]:
        del _nps["rows"][k]


@method
def nps_rows(system, kind, region="All regions", query="", mine=False, hide_have=False, sort="name", desc=False,
             queued=None, limit=3000):
    """The list as the filters show it. queued: {key: status} of rows in the window's queue (their status shows
    instead)."""
    rows = _nps["rows"].get((system, kind))
    if rows is None:
        return None
    lib, queued = _lib(system), queued or {}
    shown, status = nps_queue.shown_rows(rows, kind, lib.owned_ids, lambda r: queued.get(_key(r)) or lib.status(r),
                                         region, query, mine, hide_have, (sort, desc))
    return {"rows": [_nps_out(r, status[id(r)], lib) for r in shown[:limit]], "shown": len(shown), "total": len(rows)}


@method
def nps_art(system, name, region=""):
    """A NoPayStation game's box art and a screenshot (lib/artwork.py) -> {"art": [image urls, the window loads them
    with store_shot], "problem"}."""
    platform = lb.resolve_platform(system, nps.FULL_NAMES.get(system), ctx["cfg"]["platform_overrides"])
    return artwork.find(platform, name, (nps.REGIONS.get(region, region),) if region else ())


@method
def nps_enqueue(system, kind, keys):
    """Rows to add to the queue for these picks (an update brings the older ones the game is missing)."""
    rows, lib = _nps["rows"].get((system, kind)) or [], _lib(system)
    keys = set(keys)
    picked = [r for r in rows if _key(r) in keys]
    if kind == "Updates":
        picked = nps_queue.with_older_updates(picked, rows, _roms())
    return [_nps_out(r, "Queued", lib) for r in picked]


@method
def nps_space(system, keys):
    """-> {need, free, dir}: room for these packages and one extraction, and what the download folder has."""
    pending = _resolve(system, keys)
    folder = nps_queue.default_dir(ctx["cfg"])
    os.makedirs(folder, exist_ok=True)
    return {"need": nps_queue.space_needed(pending) if pending else 0, "free": shutil.disk_usage(folder).free,
            "dir": folder}


def _resolve(system, keys):
    by_key = {_key(r): r for (s, _), rows in _nps["rows"].items() if s == system for r in rows}
    return [by_key[k] for k in keys if k in by_key]


@method
def nps_run(job, system, keys, others=()):
    """Download and install these queued rows (keys, in queue order). others: the statuses of the rest of the queue,
    for the summary. "progress" events: {job, key, state, message, done, total} as rows move along."""
    cfg, roms = ctx["cfg"], _roms()
    pending = _resolve(system, keys)
    folder = nps_queue.default_dir(cfg)
    os.makedirs(folder, exist_ok=True)
    platform = lb.resolve_platform(system, nps.FULL_NAMES.get(system), cfg["platform_overrides"])
    scrape = nps_queue.scrape_plan(cfg.get("nps_scrape", True), platform, scraper.gamelist_path(roms, system))
    stop = stopped(job)
    states, got, sent = {}, {}, {}
    total = sum(r["size"] for r in pending) or 1
    out = {"scraped": None, "installed": False}

    def send(row=None, state=None, message=None):
        event("progress", {"job": job, "key": row and _key(row), "state": state, "message": message,
                           "done": sum(got.values()), "total": total})

    def say(m):
        if m[0] == "job":
            states[_key(m[1])] = m[2]
            send(m[1], m[2], f"{m[2]}: {m[1]['name']}")
        elif m[0] == "prog":
            _, row, what, d, t = m
            if what == "Downloading":
                got[_key(row)] = d
            now = time.monotonic()
            if t and (d >= t or now - sent.get(_key(row), 0) > 0.25):  # a few a second is plenty
                sent[_key(row)] = now
                send(row, f"{what}  {d * 100 // t}%  ({nps_queue.human(d)} / {nps_queue.human(t)})")
        elif m[0] == "log":
            send(message=m[1])
        elif m[0] == "scraped":
            out["scraped"] = m[1]
        elif m[0] == "installed":
            out["installed"] = True
    nps_queue.run_queue(pending, folder, roms, cfg.get("nps_keep_pkg", False), scrape, say, stop)
    _lib(system).owned_ids = nps.owned_ids(system, roms)
    return {"states": states, "installed": out["installed"], "stopped": stop(),
            "summary": nps_queue.summary(list(states.values()) + list(others), stop(), out["scraped"])}


@method
def nps_options(keep_pkg=None, scrape=None, folder=None):
    cfg = ctx["cfg"]
    for k, v in (("nps_keep_pkg", keep_pkg), ("nps_scrape", scrape), ("nps_dir", folder)):
        if v is not None:
            cfg[k] = v
    ctx["save_cfg"]()


@method
def nps_set_emulator(system, path):
    """Windows: the folder with rpcs3.exe / Vita3K.exe, kept in config.json. -> the window's info again."""
    name = nps.SYSTEM_EMULATOR[system]
    exe = nps.EMULATOR_EXES[name]
    if not os.path.isfile(os.path.join(path, exe)):
        raise FileNotFoundError(f"There's no {exe} in {path}")
    ctx["cfg"].setdefault("emulator_dirs", {})[name] = nps.emulator_dirs[name] = os.path.normpath(path)
    ctx["save_cfg"]()
    return nps_info(system)


# ---------- the homebrew stores ----------
_stores = {}  # store -> {"src", "entries": {code: [entry]}, "watcher"}
_store_lock = threading.Lock()
_shots = {}  # screenshot url -> data: URL (or None when it couldn't load)
SHOT_BYTES = 4 << 20


def _store(store):
    """The store's source, lists and Downloads watcher (made again, still waiting, if a folder changed)."""
    if store not in catalog.SOURCES:
        raise ValueError(f"No store {store!r}")
    s = _stores.setdefault(store, {"src": catalog.SOURCES[store](), "entries": {}, "watcher": None})
    folder, roms = catalog.downloads_folder(ctx["cfg"]), _roms()
    w = s["watcher"]
    if not w or w.folder != folder or w.roms_root != roms:
        s["watcher"] = downloads.DownloadWatcher(folder, roms)
        for want in (w.waiting if w else []):
            s["watcher"].expect(want)
    return s


def _entry(s, code, key):
    e = next((e for e in s["entries"].get(code, []) if s["src"].key(e) == key), None)
    if e is None:
        raise KeyError(f"No game {key!r} in this list")
    return e


def _waiting(s):
    w = s["watcher"]
    return {"text": catalog.waiting_text(w.waiting, w.folder), "count": len(w.waiting)}


@method
def store_info(store):
    """What the store window shows before its list loads."""
    with _store_lock:
        s = _store(store)
    src, cfg = s["src"], ctx["cfg"]
    folder = catalog.downloads_folder(cfg)
    return {"name": src.name, "heading": src.heading, "note": src.note, "open_label": src.open_label,
            "browse_label": src.browse_label, "license_header": src.license_header, "one_click": src.one_click,
            "one_click_filter": catalog.one_click_filter(src), "browser_downloads": catalog.watches_downloads(src),
            "systems": [list(x) for x in src.systems], "kinds": src.kinds, "default_kind": src.default_kind,
            "code": src.default_code(_open_system()), "downloads": folder, "downloads_short": catalog.short_path(folder),
            "waiting": _waiting(s)}


@method
def store_load(store, code, refresh=False):
    """Load a system's list (from the cache unless it's old or refresh is set) -> {age, error}. A list that can't
    load comes back empty with error saying why (the site's page may still work)."""
    s = _store(store)
    src = s["src"]
    try:
        entries = src.load(code, refresh)
    except Exception as e:
        s["entries"][code] = []
        return {"age": "", "error": src.load_error(e, code)}
    s["entries"][code] = entries
    return {"age": catalog.age_text(src.cached_age(code)), "error": ""}


@method
def store_rows(store, code, query="", kind="all", one_click=False, hide_have=False):
    """The list as the filters show it, sorted by title."""
    s = _store(store)
    src, roms, waiting = s["src"], _roms(), s["watcher"].waiting
    shown = catalog.shown(src, s["entries"].get(code, []), roms, query, kind, one_click, hide_have)
    return {"rows": [{"key": src.key(e), "title": src.title(e), "developer": src.developer(e), "kind": src.kind(e),
                      "license": src.license(e), "status": catalog.status_of(src, e, roms, waiting)} for e in shown],
            "results": catalog.results_text(src, shown)}


@method
def store_game(store, code, key):
    """One game's details, fetching what the list left out the first time it's picked."""
    s = _store(store)
    src, roms = s["src"], _roms()
    e = _entry(s, code, key)
    if hasattr(src, "fill") and "_filled" not in e:
        try:
            e.update({k: v for k, v in src.fill(e).items() if v})
            e["_filled"] = True
        except Exception:
            e["_filled"] = False
    return {"key": key, "title": src.title(e), "meta": "  ·  ".join(b for b in (src.developer(e), src.year(e),
                                                                                src.license(e)) if b),
            "description": src.description(e) or "No description.", "note": catalog.website_only_note(src, e),
            "shot": src.screenshot_url(e), "can_install": catalog.can_install(src, e, roms),
            "confirm": src.confirm(e) if hasattr(src, "confirm") else None}


@method
def store_shot(url):
    """A screenshot as a data: URL the window can show, or None when it couldn't load."""
    if url not in _shots:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": catalog.USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as r:
                data, kind = r.read(SHOT_BYTES), r.headers.get("Content-Type") or ""
            kind = kind.split(";")[0].strip() if kind.startswith("image/") else _image_type(data)
            _shots[url] = f"data:{kind};base64,{base64.b64encode(data).decode('ascii')}" if kind else None
        except Exception:
            _shots[url] = None
    return _shots[url]


def _image_type(data):
    for magic, kind in ((b"\x89PNG", "image/png"), (b"GIF8", "image/gif"), (b"\xff\xd8", "image/jpeg"),
                        (b"RIFF", "image/webp")):
        if data.startswith(magic):
            return kind
    return None


class _Stopped(Exception):
    pass


def _filed(s, want, res):
    """A ROM landed in roms/<system> (or failed to): add ES-DE metadata, and say so -> {title, message, error} or
    {title, message, toast, system}."""
    if isinstance(res, Exception):
        return {"title": want["title"], "message": f"{want['title']}: {res}", "error": str(res)}
    system, item = want["system"], want.get("item")
    note = catalog.add_metadata(s["src"], item, res, system, _roms()) if item else ""
    name = os.path.basename(res)
    return {"title": want["title"], "system": system, "message": f"Added {name} to roms/{system}{note}",
            "toast": f"Added {os.path.splitext(name)[0]} to roms/{system}."}


@method
def store_install(job, store, code, key):
    """Download a game the store may fetch itself and file it (progress as "progress" events) -> what _filed says,
    or {stopped: True}."""
    s = _store(store)
    src, roms = s["src"], _roms()
    e = _entry(s, code, key)
    if not catalog.can_install(src, e, roms):
        raise PermissionError(f"{src.title(e)} can't be installed from here")
    title, stop = src.title(e), stopped(job)

    def report(done, total):
        if stop():
            raise _Stopped()
        event("progress", {"job": job, "message": f"Downloading {title} …", "done": done, "total": total})
    try:
        report(0, 0)
        res = src.install(e, roms, report)
    except _Stopped:
        return {"stopped": True}
    except Exception as ex:
        res = ex
    return _filed(s, src.want(e), res)


@method
def store_open(store, code, key):
    """The game's page to open in the browser; what the user downloads there gets filed (see store_watch)."""
    with _store_lock:
        s = _store(store)
        src = s["src"]
        e = _entry(s, code, key)
        if not src.installed_path(e, _roms()) and catalog.watches_downloads(src):
            s["watcher"].expect(src.want(e))
        return {"url": src.page_url(e), "waiting": _waiting(s)}


@method
def store_browse(store, code):
    """Browse the site freely: any ROM for this system that lands in Downloads is filed."""
    with _store_lock:
        s = _store(store)
        s["watcher"].expect(s["src"].browse_want(code))
        return {"url": s["src"].browse_url(code), "waiting": _waiting(s)}


@method
def store_watch(store):
    """Look in the Downloads folder (the window asks every second or two) -> {filed: [what _filed says], waiting}."""
    with _store_lock:
        s = _store(store)
        filed = [_filed(s, want, res) for want, res in s["watcher"].poll()]
        return {"filed": filed, "waiting": _waiting(s)}


@method
def store_stop_waiting(store):
    with _store_lock:
        s = _store(store)
        s["watcher"].cancel()
        return {"waiting": _waiting(s)}


@method
def store_set_downloads(path):
    """Where the browser saves downloads (all the stores share it) -> how the window shows it."""
    ctx["cfg"]["homebrew_downloads"] = path
    ctx["save_cfg"]()
    return catalog.short_path(path)
