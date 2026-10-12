"""Library sources: folders to get games from, such as a home server's share mounted on this machine (or any local
folder). The window lists what a source holds like a store, with what's already in the library, and copies the
games picked into the ROMs folder through the importer (lib/romimport.py), so archives are unpacked and each game
lands in its system's folder. A source is only ever read: nothing in it is moved or deleted.

A source can also be a web server's folder listing (an http:// or https:// address, lib/websource.py): its games
are downloaded, then imported the same way.

A source's list is kept in cache/sources/ so opening it again is quick; Refresh walks the folder again."""
import hashlib, json, os, shutil, time, zipfile

import nps
import romimport
import websource
from fsutil import write_json

CACHE = os.path.join(os.environ.get("RETROSHELF_DATA") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "cache", "sources")


def problem(path, roms_root, login=None):
    """Why path can't be a source, or None. A web address is asked for its listing (login: (user, password))."""
    if websource.is_url(path):
        try:
            websource.Site(path, *(login or ())).listing()
        except (OSError, ValueError) as e:
            return str(e)
        return None
    if not os.path.isdir(path):
        return f"{path} isn't a folder (is the share mounted?)"
    p, root = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(roms_root))
    if p == root or p.startswith(root + os.sep) or root.startswith(p + os.sep):
        return "A source can't be your ROMs folder, inside it, or hold it."
    return None


def label(path):
    """What the source is called in the window: its folder's name, with the one above it (or the server's)."""
    if websource.is_url(path):
        return websource.label(path)
    path = os.path.normpath(path)
    parent = os.path.basename(os.path.dirname(path))
    return f"{os.path.basename(path)}  ({parent})" if parent else path


def quick_system(path, source, codes):
    """The system for a game in a source without opening it: a folder named for an ES-DE system (a copy of a ROMs
    folder), the file type, or a folder name like "Sony - PlayStation 2". A web source's path is relative to it.
    -> (system or None, how)"""
    web = websource.is_url(source)
    parts = (os.path.dirname(path) if web else os.path.relpath(os.path.dirname(path), source)).replace("\\", "/").split("/")
    for part in reversed(parts):
        if part.lower() in codes:
            return part.lower(), "folder"
    ext = romimport.ext_of(path)
    if ext in romimport.EXT_SYSTEMS:
        return romimport.EXT_SYSTEMS[ext], "file type"
    if ext == ".zip" and not web:  # a zip's list of files is quick to read, even over the network
        try:
            with zipfile.ZipFile(path) as z:
                inside = {romimport.EXT_SYSTEMS.get(romimport.ext_of(n)) for n in z.namelist()} - {None}
            if len(inside) == 1:
                return inside.pop(), "file type"
        except (OSError, zipfile.BadZipFile):
            pass
    h = romimport.hint(path)
    return (h, "folder name") if h else (None, "")


def _size(row):
    total = 0
    for p in row.sources():
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    return total


def _cache_file(path):
    key = path if websource.is_url(path) else os.path.normcase(os.path.abspath(path))
    return os.path.join(CACHE, hashlib.sha1(key.encode()).hexdigest()[:16] + ".json")


def cached(path):
    """The list saved by the last scan of this source, or None."""
    try:
        with open(_cache_file(path), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def scan(path, roms_root, progress=lambda message: None, cancelled=lambda: False, login=None):
    """Walk the source -> {"games": [{key, name, system, how, size}], "scanned"}; key is the game's main file (or
    archive), relative to the source (a web source's games also list their "files"). Saved for cached()."""
    codes = {c.lower() for c in romimport.system_choices(roms_root)}
    if websource.is_url(path):
        site = websource.Site(path, *(login or ()))
        games = websource.games(site, websource.walk(site, progress, cancelled),
                                lambda rel: quick_system(rel, path, codes))
        return _save(path, games)
    tops = sorted(os.listdir(path))
    games = []
    for i, top in enumerate(tops):
        if cancelled():
            raise InterruptedError
        if top.startswith(".") or top == romimport.STAGING:
            continue
        progress(f"Looking in {top} … ({i + 1} of {len(tops)})")
        for row in romimport.collect([os.path.join(path, top)]):
            system, how = quick_system(row.path, path, codes)
            games.append({"key": os.path.relpath(row.path, path).replace("\\", "/"),
                          "name": os.path.splitext(row.name)[0], "system": system,
                          "how": how, "size": _size(row)})
    return _save(path, games)


def _save(path, games):
    games.sort(key=lambda g: (g["name"].lower(), g["key"]))
    out = {"games": games, "scanned": time.time()}
    os.makedirs(CACHE, exist_ok=True)
    write_json(_cache_file(path), out)
    return out


def library_titles(roms_root, systems):
    """{system: {title key}} of the games already in those ROMs folders, to mark what's here."""
    out = {}
    for s in systems:
        try:
            names = os.listdir(os.path.join(roms_root, s))
        except OSError:
            names = []
        out[s] = {nps.title_key(os.path.splitext(n)[0]) for n in names if not n.startswith(".")}
    return out


def have(game, titles):
    """Whether the library already has a game like this one (same title, any version or region)."""
    return bool(game["system"]) and nps.title_key(game["name"]) in titles.get(game["system"], ())


def copy(source, key, roms_root, system=None, report=lambda text=None, fraction=None: None,
         cancelled=lambda: False, game=None, login=None):
    """Copy one game from the source into the ROMs folder (unpacked and filed as Import does; the source keeps it).
    system: the one the list showed, used when the game itself doesn't say. A web source's game (its listed
    "files") is downloaded into cache/downloads first. -> the importer's Row, its status saying how it went."""
    if websource.is_url(source):
        site = websource.Site(source, *(login or ()))
        dest = os.path.join(os.path.dirname(CACHE), "downloads")
        try:
            try:
                local = websource.download(site, (game or {}).get("files") or [key], dest, report, cancelled,
                                           (game or {}).get("size") or 0)
            except InterruptedError:
                row = romimport.Row(key)
                row.status = "Stopped"
                return row
            codes = {c.lower() for c in romimport.system_choices(roms_root)}
            folder_system, how = quick_system(key, source, codes)
            rows = [r for r in romimport.collect([local]) if os.path.normcase(r.path) == os.path.normcase(local)]
            if not rows:
                raise FileNotFoundError(f"{key} didn't download as a game")
            row = romimport.scan_row(rows[0])
            if how == "folder" or (not row.system() and (system or folder_system)):
                romimport.set_system(row, folder_system if how == "folder" else system or folder_system)
            row.inbox = False
            return romimport.import_one(row, roms_root, "", lambda text=None, fraction=None: report(
                text, None if fraction is None else 0.8 + 0.2 * fraction), cancelled, delete_originals=True)
        finally:
            shutil.rmtree(dest, ignore_errors=True)
    path = os.path.join(source, *key.split("/"))
    rows = [r for r in romimport.collect([path]) if os.path.normcase(r.path) == os.path.normcase(path)]
    if not rows:
        raise FileNotFoundError(f"{key} isn't in the source any more")
    row = romimport.scan_row(rows[0])
    codes = {c.lower() for c in romimport.system_choices(roms_root)}
    folder_system, how = quick_system(path, source, codes)
    if how == "folder" or (not row.system() and (system or folder_system)):
        romimport.set_system(row, folder_system if how == "folder" else system or folder_system)
    row.inbox = False  # never moved out of the source
    return romimport.import_one(row, roms_root, "", report, cancelled, delete_originals=False)
