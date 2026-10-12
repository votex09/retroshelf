"""Import ROMs → Sources: folders to copy games from, such as a home server's share, or a web server's folder
listing (lib/sources.py, lib/websource.py). The window lists a source like a store and copies the games the user
queues into the ROMs folder as a job ("progress" events carry each game's state by its key).

A web source's login is kept in the settings as cfg["source_logins"][address] = {"user", "secret"}: the password is
encrypted by the window (Electron's safeStorage) and only ever reaches here as plain text for the open source, kept
in memory."""
import os, re

import artwork
import launchbox as lb
import romimport
import sources
import tool_files
import websource
from rpc import ctx, event, method, stopped

sources.CACHE = os.path.join(ctx["data_dir"], "cache", "sources")
_src = {"path": None, "games": [], "titles": {}, "login": None}  # the open source: its games, what the library
# has, and its (user, password) for a web source


def _roms():
    root = ctx["cfg"]["roms_root"]
    if not root or not os.path.isdir(root):
        raise FileNotFoundError("Pick your ROMs folder first")
    return root


def _saved():
    logins = ctx["cfg"].get("source_logins", {})
    return [{"path": p, "label": sources.label(p), "web": websource.is_url(p),
             "here": websource.is_url(p) or os.path.isdir(p), "login": logins.get(p)}
            for p in ctx["cfg"].get("sources", [])]


@method
def source_list():
    """The saved sources, the last one opened first."""
    return {"sources": _saved(), "last": ctx["cfg"].get("source_last"), "home": os.path.expanduser("~")}


@method
def source_add(path, user="", password="", secret=None):
    """Save a folder, or a web address (with a login: password to check it now, secret to keep)."""
    web = websource.is_url(path)
    path = websource.normalize(path) if web else path
    problem = sources.problem(path, _roms(), (user, password) if web and user else None)
    if problem:
        raise ValueError(problem)
    if web:
        logins = ctx["cfg"].setdefault("source_logins", {})
        if user:
            logins[path] = {"user": user, "secret": secret}
            _src.update(path=None)  # (opened again with the new login)
        else:
            logins.pop(path, None)
    else:
        path = os.path.normpath(path)
    saved = ctx["cfg"].setdefault("sources", [])
    if path not in saved:
        saved.append(path)
    ctx["cfg"]["source_last"] = path
    ctx["save_cfg"]()
    return source_list()


@method
def source_remove(path):
    """Forget a source (its files are untouched)."""
    ctx["cfg"]["sources"] = [p for p in ctx["cfg"].get("sources", []) if p != path]
    ctx["cfg"].get("source_logins", {}).pop(path, None)
    if ctx["cfg"].get("source_last") == path:
        ctx["cfg"]["source_last"] = None
    ctx["save_cfg"]()
    return source_list()


def _mark():
    systems = {g["system"] for g in _src["games"] if g["system"]}
    _src["titles"] = sources.library_titles(_roms(), systems)


@method
def source_open(job, path, refresh=False, password=None):
    """Open a source: its saved list, or a fresh look through it (the first time, or refresh) -> {systems, total}.
    password: a web source's, decrypted by the window."""
    web = websource.is_url(path)
    if not web and not os.path.isdir(path):
        raise FileNotFoundError(f"Can't reach {path}: is the share mounted?")
    user = (ctx["cfg"].get("source_logins", {}).get(path) or {}).get("user") if web else None
    login = (user, password or "") if user else None
    listing = None if refresh else sources.cached(path)
    if listing is None:
        stop = stopped(job)
        listing = sources.scan(path, _roms(), lambda m: event("progress", {"job": job, "message": m, "done": 0, "total": 0}),
                               stop, login)
    _src.update(path=path, games=listing["games"], login=login)
    _mark()
    if ctx["cfg"].get("source_last") != path:
        ctx["cfg"]["source_last"] = path
        ctx["save_cfg"]()
    systems = sorted({g["system"] for g in listing["games"] if g["system"]}, key=lambda s: romimport.label(s).lower())
    return {"systems": [[s, romimport.label(s)] for s in systems], "total": len(listing["games"])}


@method
def source_rows(system="", query="", hide_have=False, queued=None, limit=3000):
    """The open source's games as the filters show them. queued: {key: state} of games in the window's queue."""
    queued, words = queued or {}, query.lower().split()
    rows = []
    for g in _src["games"]:
        if system and g["system"] != system:
            continue
        if words and not all(w in g["name"].lower() for w in words):
            continue
        have = sources.have(g, _src["titles"])
        if hide_have and have:
            continue
        rows.append({**g, "label": romimport.label(g["system"]) if g["system"] else "found when copied",
                     "status": queued.get(g["key"]) or ("In library" if have else "")})
    return {"rows": rows[:limit], "shown": len(rows), "total": len(_src["games"])}


@method
def source_art(key):
    """A source game's box art and screenshot (lib/artwork.py) -> {"art", "problem", "console"}."""
    g = next((g for g in _src["games"] if g["key"] == key), None)
    if not g or not g["system"]:
        return {"art": [], "problem": "No artwork: the system shows once it's copied", "console": ""}
    console = romimport.label(g["system"])
    platform = lb.resolve_platform(g["system"], console, ctx["cfg"]["platform_overrides"])
    regions = [r.strip() for tag in re.findall(r"\(([^)]*)\)", g["name"]) for r in tag.split(",")]
    return {**artwork.find(platform, g["name"], regions), "console": console}


@method
def source_copy(job, keys):
    """Copy the queued games (keys) into the ROMs folder, one at a time -> {"states", "copied", "systems",
    "stopped"}."""
    roms, path, login, stop = _roms(), _src["path"], _src["login"], stopped(job)
    games = {g["key"]: g for g in _src["games"]}
    states, done = {}, []
    for k, key in enumerate(keys):
        if stop():
            break

        def step(text=None, fraction=None, k=k, key=key):
            event("progress", {"job": job, "key": key, "state": "Copying", "message": text,
                               "done": round((k + (fraction or 0)) * 1000), "total": len(keys) * 1000})
        step(f"Copying {games.get(key, {}).get('name', key)} …")
        try:
            row = sources.copy(path, key, roms, (games.get(key) or {}).get("system"), step, stop, games.get(key),
                               login)
            st = row.status
        except Exception as e:  # shown in the queue
            st = str(e)[:200] or type(e).__name__
        if st.startswith("Imported"):
            states[key] = "Done"
            done.append(row)
        elif st.startswith("Already"):
            states[key] = "In library"
        elif st == "Stopped":
            states[key] = "Queued"
        else:
            states[key] = f"Failed: {st}"
        event("progress", {"job": job, "key": key, "state": states[key], "done": (k + 1) * 1000,
                           "total": len(keys) * 1000})
    _mark()
    systems = romimport.imported_systems(done)
    return {"states": states, "copied": len(done), "systems": systems, "stopped": stop(),
            "scraped": tool_files.scrape_imported(job, done, stop)}
