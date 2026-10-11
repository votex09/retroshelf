"""Tools → Compress games (disc images into .chd / .rvz, originals to the holding folder) and Library → Import ROMs
(games thrown in the import folder, or added from anywhere, filed into the ROMs folder by system)."""
import os, shutil, threading

import compress
import romimport
import scraper
import shelf
from rpc import ctx, event, method, progress, stopped

FORMATS = {".chd": "CHD", ".rvz": "RVZ"}


# ---------- Compress games ----------
_tools = {}  # tool name -> Tool, once found (looked for again while it isn't installed)


def _compressing():
    """-> (the open system, the format its games become, the tool's name); an error when it has no disc images."""
    sc = ctx["need_system"]()
    ext = compress.supported(sc.system, sc.exts)
    if not ext:
        raise RuntimeError("This system's games can't be compressed")
    return sc, ext, compress.tool_name("rvz" if ext == ".rvz" else "cd")


def _plan(sc):
    """-> {game key: [Job]} for the games that can be compressed, and [(key, why)] for the others."""
    jobs, skipped = {}, []
    for key, js, why in compress.plan(sc.system, sc.units, sc.exts):
        if js:
            jobs[key] = js
        elif why != "nothing to compress":
            skipped.append((key, why))
    return jobs, skipped


@method
def compress_info():
    """What the window lists: each game that can be compressed (what it is now, its size), then the ones left alone
    and why. supported is False (and nothing else comes) for systems without disc images."""
    sc = ctx["need_system"]()
    ext = compress.supported(sc.system, sc.exts)
    if not ext:
        return {"supported": False, "listed": bool(compress.target_ext(sc.system))}
    cfg = ctx["cfg"]
    jobs, skipped = _plan(sc)
    rows = [{"key": k, "now": ", ".join(dict.fromkeys(compress.describe(j) for j in js)),
             "size": sum(j.size for j in js), "discs": len(js)} for k, js in jobs.items()]
    holding = os.path.join(shelf.holding_root(cfg), "to_delete", sc.system)
    return {"supported": True, "ext": ext, "format": FORMATS[ext], "rows": rows, "skipped": [{"key": k, "why": why} for k, why in skipped],
            "verify": cfg.get("compress_verify", True), "delete": cfg.get("compress_delete", False),
            "holding": holding, "same_drive": shelf.on_same_drive(shelf.holding_root(cfg), sc.roms_root)}


@method
def compress_tool():
    """Find chdman / dolphin-tool (asking Flatpak takes a moment). -> {name, where (None: not installed), hint}"""
    _, _, name = _compressing()
    tool = _tools[name] = _tools.get(name) or compress.find_tool(name)
    return {"name": name, "where": tool.where if tool else None, "hint": compress.INSTALL_HINT[name]}


@method
def compress_options(verify, delete):
    ctx["cfg"]["compress_verify"] = bool(verify)
    ctx["cfg"]["compress_delete"] = bool(delete)
    ctx["save_cfg"]()


@method
def compress_games(job, keys, verify=True, delete=False):
    """Compress these games, one at a time. Progress comes as "progress" events for job; one with a key says how
    that game went (result, tag "done" / "failed"). The originals' moves are logged, so Restore a move undoes them."""
    sc, _, name = _compressing()
    tool = _tools[name] = _tools.get(name) or compress.find_tool(name)
    if not tool:
        raise RuntimeError(f"{name} isn't installed. {compress.INSTALL_HINT[name]}")
    plan, _ = _plan(sc)
    keys = [k for k in keys if k in plan]
    holding = None if delete else os.path.join(shelf.holding_root(ctx["cfg"]), "to_delete", sc.system)
    report, stop = progress(job), stopped(job)
    res = compress.run([(k, j) for k in keys for j in plan[k]], tool, sc.folder,
                       {k: list(sc.units[k]["paths"]) for k in keys}, scraper.gamelist_path(sc.roms_root, sc.system),
                       os.path.join(scraper.media_root(sc.roms_root), sc.system), holding, verify,
                       lambda key, text, tag: event("progress", {"job": job, "key": key, "result": text, "tag": tag}),
                       lambda text, fraction: report(text, round(fraction * 1000), 1000), stop)
    games = len(dict.fromkeys(res["keys"]))
    if res["moves"]:
        moves = os.path.join(ctx["data_dir"], "moves.json")
        with ctx["state_lock"]:
            try:
                shelf.write_moves(moves, shelf.read_moves(moves) + [compress.log_entry(sc.system, games,
                                                                                       res["moves"])])
            except OSError as e:
                res["problems"].append(f"move log (Restore a move won't know about this run): {e}")
    return {"games": games, "saved": res["saved"], "problems": res["problems"], "held": bool(holding),
            "stopped": stop()}


# ---------- Import ROMs ----------
# The list lives here between calls: row id -> romimport.Row (the window shows romimport.shown() of each).
_imp = {"rows": {}, "next": 0, "inbox": "", "snapshot": None, "pending": False, "folder": [], "busy": False}
_imp_lock = threading.Lock()


def _roms():
    root = ctx["cfg"]["roms_root"]
    if not root or not os.path.isdir(root):
        raise FileNotFoundError("Pick your ROMs folder first (or set up RetroDECK / ES-DE).")
    return root


def _rows():
    return [{"id": i, "override": r.override, **romimport.shown(r)} for i, r in _imp["rows"].items()]


def _listed():
    """-> the list, and what the window says under it."""
    rows = _imp["rows"].values()
    return {"rows": _rows(), "ready": len(romimport.to_import(rows)),
            "unknown": sum(1 for r in rows if not r.status.startswith("Imported") and not r.ready())}


def _add(rows):
    """Put rows that aren't listed yet in the list, as Checking … (import_scan looks at them)."""
    with _imp_lock:
        for r in romimport.new_rows(rows, _imp["rows"].values()):
            r.status = "Checking …"
            _imp["rows"][_imp["next"]] = r
            _imp["next"] += 1


def _refresh():
    """Pick up what's in the import folder; forget rows whose files have gone."""
    with _imp_lock:
        for i, r in list(_imp["rows"].items()):
            if romimport.gone(r):
                del _imp["rows"][i]
    _add(romimport.collect(romimport.inbox_paths(_imp["inbox"]), _imp["inbox"]))


@method
def import_info():
    """Open the window: an empty list, then what's in the import folder (as Checking …: import_scan next)."""
    root = _roms()
    cfg = ctx["cfg"]
    inbox = romimport.inbox_dir(cfg)
    try:
        os.makedirs(inbox, exist_ok=True)
    except OSError:
        pass
    if not _imp["busy"]:  # a half-finished import (closed mid-way) left its staging folder behind
        shutil.rmtree(romimport.staging_dir(root), ignore_errors=True)
    _imp.update(rows={}, inbox=inbox, snapshot=None, pending=False, folder=[])
    _refresh()
    return {"inbox": inbox, "delete": bool(cfg.get("import_delete_originals")), "home": os.path.expanduser("~"),
            "systems": [{"code": c, "label": romimport.label(c)} for c in romimport.system_choices(root)],
            **_listed()}


@method
def import_scan():
    """Look at the rows still Checking … and guess their systems. -> the list."""
    for r in [r for r in _imp["rows"].values() if r.status == "Checking …"]:
        romimport.scan_row(r)
    return _listed()


@method
def import_list():
    return _listed()


@method
def import_watch():
    """Every couple of seconds while the window is open: new files in the import folder are listed once they've
    finished copying (two looks the same). -> the list when it changed, else None."""
    if _imp["busy"] or not _imp["inbox"]:
        return None
    state = romimport.inbox_state(_imp["inbox"])
    if state != _imp["snapshot"]:
        _imp.update(pending=True, snapshot=state)
    elif _imp["pending"]:
        _imp["pending"] = False
        _refresh()
        return _listed()
    return None


@method
def import_add(paths):
    """Add files from anywhere (they're copied, unless the delete option is on). -> the list."""
    _add(romimport.collect(paths, _imp["inbox"]))
    return _listed()


@method
def import_folder(path):
    """What Add a folder would add, for the window to confirm: -> {games, folders}; import_add_folder adds them."""
    rows = romimport.new_rows(romimport.collect([path], _imp["inbox"]), _imp["rows"].values())
    _imp["folder"] = rows
    return {"games": len(rows), "folders": len({os.path.dirname(r.path) for r in rows})}


@method
def import_add_folder():
    _add(_imp["folder"])
    _imp["folder"] = []
    return _listed()


@method
def import_remove(ids):
    with _imp_lock:
        for i in ids:
            _imp["rows"].pop(i, None)
    return _listed()


@method
def import_set_system(ids, system=None):
    """Pick the system for these rows (None: back to the one detected)."""
    for i in ids:
        if i in _imp["rows"]:
            romimport.set_system(_imp["rows"][i], system)
    return _listed()


@method
def import_set_inbox(path):
    problem = romimport.inbox_problem(path, _roms())
    if problem:
        raise ValueError(problem)
    path = os.path.normpath(path)
    ctx["cfg"]["import_dir"] = path
    ctx["save_cfg"]()
    with _imp_lock:
        for i, r in list(_imp["rows"].items()):
            if r.inbox and not r.status.startswith("Imported"):
                del _imp["rows"][i]
    _imp.update(inbox=path, snapshot=None)
    _refresh()
    return {"inbox": path, **_listed()}


@method
def import_options(delete):
    ctx["cfg"]["import_delete_originals"] = bool(delete)
    ctx["save_cfg"]()


@method
def import_run(job, delete=False):
    """Import every row that's ready, one at a time. Progress comes as "progress" events for job; one with a row
    is that row as it is now. -> the list, how many were imported and into which systems."""
    root = _roms()
    stop = stopped(job)
    ready = set(romimport.to_import(_imp["rows"].values()))
    items = [(i, r) for i, r in _imp["rows"].items() if r in ready]
    _imp["busy"] = True
    try:
        for k, (i, r) in enumerate(items):
            if stop():
                break

            def step(text=None, fraction=None, k=k):
                event("progress", {"job": job, "message": text, "done": round((k + (fraction or 0)) * 1000),
                                   "total": len(items) * 1000})
            step(f"Importing {r.name} …")
            romimport.import_one(r, root, _imp["inbox"], step, stop, delete)
            event("progress", {"job": job, "row": {"id": i, "override": r.override, **romimport.shown(r)}})
    finally:
        _imp["busy"] = False
    done = [r for _, r in items if r.status.startswith("Imported")]
    return {**_listed(), "imported": len(done), "systems": romimport.imported_systems(done), "stopped": stop()}
