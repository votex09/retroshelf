"""The ROMs folder itself, without any windows: where it is, which systems it has, which files are games.

Shared by the Tk app (retroshelf.py) and the helper process behind the Electron app (app/helper/helper.py)."""
import os, re

import frontend
import nps

PARTIAL_EXT = (".part", ".crdownload", ".tmp")
NON_GAME_EXT = {".txt", ".nfo", ".md", ".pdf", ".htm", ".html", ".xml", ".json", ".dat", ".jpg", ".jpeg",
                ".png", ".gif", ".bmp", ".webp", ".mp4", ".py", ".sh", ".log", ".ini", ".cfg", ".directory"}


def read_systeminfo(folder):
    """-> (system name, full name, {game extensions}) from ES-DE's systeminfo.txt; missing parts are None."""
    try:
        with open(os.path.join(folder, "systeminfo.txt"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None, None, None
    name = re.search(r"System name:\s*\n(.*)", text)
    full = re.search(r"Full system name:\s*\n(.*)", text)
    exts = re.search(r"Supported file extensions:\s*\n(.*)", text)
    return (
        name.group(1).strip() if name else None,
        full.group(1).strip() if full else None,
        {e.lower() for e in exts.group(1).split()} if exts else None,
    )


def is_game(entry, exts):
    """Dirs count (ES-DE game folders); files must have a game extension (partial downloads judged by the inner one)."""
    if entry.name.startswith((".", "_")):
        return False
    if entry.is_dir():
        return True
    name = entry.name.lower()
    if name.endswith(PARTIAL_EXT):
        name = os.path.splitext(name)[0]
    ext = os.path.splitext(name)[1]
    return ext in exts if exts else ext not in NON_GAME_EXT


def list_entries(folder, exts=None):
    try:
        return [e for e in os.scandir(folder) if is_game(e, exts)]
    except OSError:
        return []


def valid_exts(folder, system):
    name, _, exts = read_systeminfo(folder)
    return exts if name == system else None


def guess_roms_root(app_dir, esde_bases=()):
    """The ROMs folder of the RetroDECK / ES-DE on this computer (RetroDECK's config says where its folder went;
    ES-DE's settings, or the portable copies RetroShelf set up, say where its ROMs are), else a usual spot.
    app_dir: RetroShelf's own folder, since a portable setup keeps its ROMs next to it."""
    for p in ([frontend.retrodeck_roms()] + frontend.esde_installs(esde_bases) +
              [os.path.join(app_dir, "..", "retrodeck", "roms"), os.path.join(app_dir, "..", "roms"),
               os.path.join(app_dir, "..", "..", "roms"), os.path.expanduser("~/retrodeck/roms"),
               os.path.expanduser("~/ROMs")]):
        if p and os.path.isdir(p):
            return os.path.realpath(p)
    return ""


def systems(roms_root):
    """-> [(folder name, full name, number of games)] for the systems in roms_root that have games, plus the
    NoPayStation ones (listed even when empty or missing, since installing fills them)."""
    out = []
    for d in sorted(set(os.listdir(roms_root)) | set(nps.CONSOLES)):
        full = os.path.join(roms_root, d)
        if d.startswith((".", "_")) or not (os.path.isdir(full) or d in nps.CONSOLES):
            continue
        n = len(list_entries(full, valid_exts(full, d)))
        if n == 0 and d not in nps.CONSOLES:
            continue
        name, fullname, _ = read_systeminfo(full)
        out.append((d, fullname if name == d and fullname else nps.FULL_NAMES.get(d, "?"), n))
    return out


# ---------- a game's artwork and video (ES-DE's downloaded_media/<system>/<type>/<rom name>.*) ----------
MEDIA_ORDER = ["covers", "3dboxes", "miximages", "screenshots", "titlescreens", "physicalmedia", "marquees"]
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".avi", ".mov")
_listings = {}  # folder -> (mtime, {stem: [file names]})


def _by_stem(folder):
    try:
        mtime = os.stat(folder).st_mtime
    except OSError:
        return None
    cached = _listings.get(folder)
    if not cached or cached[0] != mtime:
        by_stem = {}
        for f in sorted(os.listdir(folder)):
            by_stem.setdefault(os.path.splitext(f)[0], []).append(f)
        cached = _listings[folder] = (mtime, by_stem)
    return cached[1]


def media_for(media_dir, stems, types=MEDIA_ORDER):
    """[(media type, image path)] for a game, in MEDIA_ORDER. stems: the names its files go by, without extension."""
    out = []
    for mtype in types:
        folder = os.path.join(media_dir, mtype)
        by_stem = _by_stem(folder)
        for stem in stems if by_stem else ():
            out += [(mtype, os.path.join(folder, f)) for f in by_stem.get(stem, [])
                    if not f.lower().endswith(VIDEO_EXTS)]
    return out


def video_for(media_dir, stems):
    """The game's clip in <media_dir>/videos, or None."""
    folder = os.path.join(media_dir or "", "videos")
    by_stem = _by_stem(folder)
    for stem in stems if by_stem else ():
        for f in by_stem.get(stem, []):
            if f.lower().endswith(VIDEO_EXTS):
                return os.path.join(folder, f)
    return None


def stems_of(paths):
    """The names ES-DE files a game's media under: each file's name with and without its extension."""
    names = [os.path.basename(p.rstrip("/\\")) for p in paths]
    return list(dict.fromkeys([os.path.splitext(n)[0] for n in names] + names))
