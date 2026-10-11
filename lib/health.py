"""Library health check: what stops games starting, and what takes space for nothing.

    scan(roms_root, systems=None)  -> [Problem]
    fix(problem, roms_root)        -> what was done (raises OSError / RuntimeError when it can't be)

What it looks for, in every system folder (or the ones asked for):
  - sheet     a .cue / .gdi naming track files that aren't there (fixable when only the name's case differs, or a
              one-file sheet whose file was renamed)
  - playlist  an .m3u naming discs that aren't there (fixable when the disc is there by another name: other case,
              or compressed to .chd / .rvz / …)
  - lonebin   a raw CD image (.bin / .img) with no .cue, which the emulators can't open: one is written
  - multidisc a game's discs side by side with no .m3u: ES-DE lists each disc, and changing discs mid-game needs
              the playlist. One is written, and the separate discs are hidden in ES-DE so the game shows once
  - empty     an empty game file (a failed copy or download)
  - leftover  partial downloads and RetroShelf's own temporary files left behind
  - media     ES-DE artwork, videos and manuals for games that aren't there any more
  - gamelist  ES-DE gamelist entries for games that aren't there any more
Nothing is changed by scan(); fix() changes one problem's files, and only what it says."""
import os, re, shutil, time

import romimport
import scraper

KINDS = [  # (kind, heading) in the order they're shown
    ("sheet", "Disc sheets naming files that aren't there"),
    ("playlist", "Playlists naming discs that aren't there"),
    ("lonebin", "Disc images without the .cue they need"),
    ("multidisc", "Games on several discs without a playlist"),
    ("empty", "Empty game files"),
    ("leftover", "Unfinished downloads and temporary files"),
    ("media", "Artwork and videos for games that aren't there"),
    ("gamelist", "Gamelist entries for games that aren't there"),
]
HEADINGS = dict(KINDS)

NOT_GAMES = {".txt", ".nfo", ".md", ".pdf", ".htm", ".html", ".xml", ".json", ".dat", ".jpg", ".jpeg", ".png", ".gif",
             ".bmp", ".webp", ".mp4", ".py", ".sh", ".log", ".ini", ".cfg", ".directory", ".keep", ".sav", ".srm"}
PARTIAL = (".part", ".crdownload", ".tmp")
OURS = re.compile(r"^\.(.+\.retroshelf-tmp|retroshelf-rename-\d+-\d+)$")  # compress.temp_path, apply_renames
QUIET_S = 600  # a partial download changed in the last ten minutes may still be downloading
DISC_EXTS = (".cue", ".gdi", ".chd", ".iso", ".cso", ".rvz", ".gcz", ".wia", ".wbfs", ".pbp", ".ccd", ".mds", ".cdi",
             ".bin", ".img", ".zso", ".m3u")
MAX_DEPTH = 4


class Problem:
    def __init__(self, kind, system, paths, detail, fix=None, size=0, data=None, title=None):
        self.kind, self.system, self.paths, self.detail = kind, system, list(paths), detail
        self.fix, self.size, self.data = fix, size, data  # fix: what fixing does ("Make a .cue"), or None
        self.title = title  # for problems about many files: what to call them

    @property
    def name(self):
        if self.title:
            return self.title
        return os.path.basename(self.paths[0]) if self.paths else self.system

    def __repr__(self):
        return f"Problem({self.kind}, {self.system}, {self.name}, fix={self.fix!r})"


def _exts(folder):
    """The extensions ES-DE reads in a system folder (systeminfo.txt), or None."""
    try:
        with open(os.path.join(folder, "systeminfo.txt"), encoding="utf-8") as f:
            m = re.search(r"Supported file extensions:\s*\n(.*)", f.read())
    except OSError:
        return None
    return {e.lower() for e in m.group(1).split()} if m else None


def _read(path, limit=1 << 20):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read(limit)


def systems(roms_root):
    try:
        return sorted(n for n in os.listdir(roms_root) if not n.startswith((".", "_"))
                      and os.path.isdir(os.path.join(roms_root, n)))
    except OSError:
        return []


def _walk(folder):
    """-> ([(path, rel '/'-separated, is_dir)], rel folders not looked inside). Folders whose name has an extension
    (Game.ps3, Game.psvita …) are games ES-DE doesn't look inside either."""
    out, closed = [], set()

    def go(d, rel, depth):
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name.lower())
        except OSError:
            return
        for e in entries:
            if e.name.startswith(".") and not OURS.match(e.name):
                continue
            r = f"{rel}{e.name}"
            is_dir = e.is_dir(follow_symlinks=False)
            out.append((e.path, r, is_dir))
            if is_dir:
                if os.path.splitext(e.name)[1] or depth >= MAX_DEPTH:
                    closed.add(r)
                else:
                    go(e.path, r + "/", depth + 1)
    go(folder, "", 1)
    return out, closed


def _key(p):
    return os.path.normcase(os.path.normpath(p)).lower()


def _resolve(here, ref, names_by_lower):
    """A sheet / playlist entry -> (path if it's there, path in other case if only that is)."""
    p = os.path.normpath(os.path.join(here, ref.replace("\\", "/")))
    if os.path.exists(p):
        return p, None
    return None, names_by_lower.get(_key(p))


def _sheet_refs(path):
    text = _read(path)
    if path.lower().endswith(".cue"):
        return [t[0] for t in romimport.parse_cue(text)] or [
            m.group(1) or m.group(2) for m in re.finditer(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))', text, re.M | re.I)]
    return romimport.parse_gdi(text)


def scan_system(roms_root, system, now=None):
    now = time.time() if now is None else now
    folder = os.path.join(roms_root, system)
    exts = _exts(folder)
    found, closed = _walk(folder)
    by_lower = {_key(p): p for p, _, _ in found}
    problems, referenced = [], set()
    files = [(p, r) for p, r, d in found if not d]

    def is_game(p):
        ext = os.path.splitext(p)[1].lower()
        if ext in NOT_GAMES or os.path.basename(p) == "systeminfo.txt":
            return False
        return exts is None or ext in exts

    for p, rel in files:
        name, low = os.path.basename(p), p.lower()
        if OURS.match(name):
            problems.append(Problem("leftover", system, [p], "left by RetroShelf when it was stopped part-way",
                                    "Delete it", _size(p)))
            continue
        if low.endswith(PARTIAL):
            age = now - _mtime(p)
            if age >= QUIET_S:
                problems.append(Problem("leftover", system, [p], f"unfinished download, last changed {_ago(age)}",
                                        "Delete it", _size(p)))
            continue
        if low.endswith((".cue", ".gdi")):
            try:
                refs = _sheet_refs(p)
            except OSError as e:
                problems.append(Problem("sheet", system, [p], f"can't be read: {e}"))
                continue
            missing, swaps = [], {}
            here = os.path.dirname(p)
            for r in refs:
                there, alt = _resolve(here, r, by_lower)
                if there:
                    referenced.add(_key(there))
                elif alt:
                    swaps[r] = os.path.relpath(alt, here).replace(os.sep, "/") if "/" in r else os.path.basename(alt)
                    referenced.add(_key(alt))
                else:
                    missing.append(r)
            if missing and len(refs) == 1 and len(missing) == 1:
                # a one-file sheet whose file was renamed: the one image of that stem next to it
                stem = os.path.splitext(name)[0].lower()
                cands = [q for q, _ in files if os.path.dirname(q) == here and os.path.splitext(q)[1].lower()
                         in (".bin", ".img", ".iso") and os.path.splitext(os.path.basename(q))[0].lower() == stem]
                if len(cands) == 1:
                    swaps[missing[0]] = os.path.basename(cands[0])
                    referenced.add(_key(cands[0]))
                    missing = []
            if missing:
                problems.append(Problem("sheet", system, [p], "names " + ", ".join(missing[:3])
                                        + (f" and {len(missing) - 3} more" if len(missing) > 3 else "")))
            elif swaps:
                problems.append(Problem("sheet", system, [p], "names " + ", ".join(
                    f"{a} (it's {b})" for a, b in list(swaps.items())[:3]), "Fix the names", data=swaps))
            continue
        if low.endswith(".m3u"):
            try:
                refs = romimport.parse_m3u(_read(p))
            except OSError as e:
                problems.append(Problem("playlist", system, [p], f"can't be read: {e}"))
                continue
            here = os.path.dirname(p)
            missing, swaps = [], {}
            for r in refs:
                there, alt = _resolve(here, r, by_lower)
                if there:
                    continue
                if not alt:  # compressed or converted since: the same name with another disc format
                    base = os.path.splitext(_key(os.path.join(here, r.replace("\\", "/"))))[0]
                    alts = [q for k, q in by_lower.items() if os.path.splitext(k)[0] == base
                            and os.path.splitext(k)[1] in DISC_EXTS and not k.endswith(".m3u")]
                    alts.sort(key=lambda q: DISC_EXTS.index(os.path.splitext(q)[1].lower()))
                    alt = alts[0] if alts else None
                if alt:
                    swaps[r] = os.path.relpath(alt, here).replace(os.sep, "/")
                else:
                    missing.append(r)
            if missing:
                problems.append(Problem("playlist", system, [p], "names " + ", ".join(missing[:3])
                                        + (f" and {len(missing) - 3} more" if len(missing) > 3 else "")
                                        + (" (the rest can be fixed)" if swaps else ""), data=swaps))
            elif swaps:
                problems.append(Problem("playlist", system, [p], "names " + ", ".join(
                    f"{a} (it's {b})" for a, b in list(swaps.items())[:3]), "Fix the names", data=swaps))
            continue
    for p, rel in files:
        name, low = os.path.basename(p), p.lower()
        if OURS.match(name) or low.endswith(PARTIAL) or not is_game(p):
            continue
        size = _size(p)
        if size == 0 and not low.endswith(".m3u"):
            problems.append(Problem("empty", system, [p], "0 bytes: a copy or download that didn't finish",
                                    "Delete it"))
            continue
        if system in romimport.CUE_SYSTEMS and low.endswith((".bin", ".img")) and \
                _key(p) not in referenced:
            cue = os.path.splitext(p)[0] + ".cue"
            if _key(cue) in by_lower:
                continue  # its .cue is there (and named something else inside: that's the sheet check's)
            try:
                with open(p, "rb") as f:
                    text = romimport.cue_for(name, f.read(16))
            except OSError:
                continue
            if text and not re.search(r"\((?:Track|Disc) \d+\)", name, re.I):
                problems.append(Problem("lonebin", system, [p], "a raw CD image: emulators open it through a .cue",
                                        "Make a .cue", data=text))
    problems += _multidisc(system, folder, files, by_lower, exts)
    problems += _orphans(roms_root, system, folder, found, closed)
    return problems


DISC = re.compile(r"\s*\((?:Disc|Disk|CD)\s*(\d+)(?:\s*of\s*\d+)?\)", re.I)
DISC_ORDER = (".chd", ".cue", ".gdi", ".ccd", ".iso", ".pbp", ".cso", ".zso", ".rvz", ".cdi", ".mds")


def _multidisc(system, folder, files, by_lower, exts):
    """Discs named "Game (Disc 1)", "Game (Disc 2)" … at the top of the folder with no Game.m3u."""
    if exts is not None and ".m3u" not in exts:
        return []
    sets = {}
    for p, rel in files:
        if "/" in rel:
            continue
        stem, ext = os.path.splitext(os.path.basename(p))
        if ext.lower() not in DISC_ORDER:
            continue
        m = DISC.search(stem)
        if not m:
            continue
        base = (stem[:m.start()] + stem[m.end():]).strip()
        disc = int(m.group(1))
        sets.setdefault(base, {}).setdefault(disc, []).append(p)
    out = []
    for base, discs in sorted(sets.items()):
        if len(discs) < 2 or _key(os.path.join(folder, base + ".m3u")) in by_lower:
            continue
        chosen = [min(discs[d], key=lambda q: DISC_ORDER.index(os.path.splitext(q)[1].lower())) for d in sorted(discs)]
        out.append(Problem("multidisc", system, chosen, f"{len(chosen)} discs, e.g. {os.path.basename(chosen[0])}",
                           "Make an .m3u", title=base + ".m3u", data=base))
    return out


def _orphans(roms_root, system, folder, found, closed):
    """ES-DE media and gamelist entries for games that aren't in the system folder."""
    out = []
    names = {r.lower() for _, r, _ in found}
    stems = names | {os.path.splitext(r)[0] for r in names}
    shut = {c.lower() for c in closed}

    def gone(rel_stem):
        r = rel_stem.lower()
        if r in stems:
            return False
        parts = r.split("/")
        return not any("/".join(parts[:i]) in shut for i in range(1, len(parts)))

    mdir = os.path.join(scraper.media_root(roms_root), system)
    if os.path.isdir(mdir) and os.path.isdir(folder):
        orphans = []
        for mtype in sorted(os.listdir(mdir)):
            tdir = os.path.join(mdir, mtype)
            if not os.path.isdir(tdir):
                continue
            for d, _, fs in os.walk(tdir):
                for f in fs:
                    p = os.path.join(d, f)
                    rel = os.path.relpath(p, tdir).replace(os.sep, "/")
                    if gone(os.path.splitext(rel)[0]):
                        orphans.append(p)
        if orphans:
            size = sum(_size(p) for p in orphans)
            out.append(Problem("media", system, orphans, f"{len(orphans):,} files ({_human(size)}), e.g. "
                               + ", ".join(os.path.basename(p) for p in orphans[:2]), "Delete them", size,
                               title=f"downloaded_media/{system}"))
    gl = scraper.find_gamelist(roms_root, system)
    if gl:
        try:
            _, root = scraper.read_gamelist(gl)
        except Exception as e:
            out.append(Problem("gamelist", system, [gl], f"gamelist.xml can't be read: {e}"))
            return out
        gone_paths = []
        for g in root.iter("game"):
            el = g.find("path")
            path = (el.text or "").strip() if el is not None else ""
            rel = path[2:] if path.startswith("./") else path
            if rel and not os.path.isabs(rel) and gone(rel.rstrip("/")) and gone(os.path.splitext(rel)[0]):
                gone_paths.append(rel)
        if gone_paths:
            out.append(Problem("gamelist", system, [gl], f"{len(gone_paths):,} entries, e.g. "
                                                         + ", ".join(gone_paths[:3]), "Remove them",
                               data=gone_paths, title=f"gamelists/{system}/gamelist.xml"))
    return out


def scan(roms_root, only=None, progress=lambda text, fraction: None, cancelled=lambda: False):
    names = [s for s in systems(roms_root) if only is None or s in only]
    out = []
    for i, system in enumerate(names):
        if cancelled():
            raise InterruptedError("cancelled")
        progress(f"Looking at {system} …", i / max(1, len(names)))
        out += scan_system(roms_root, system)
    order = {k: i for i, (k, _) in enumerate(KINDS)}
    out.sort(key=lambda p: (order[p.kind], p.system, p.name.lower()))
    return out


# ---------- fixing ----------
def fix(problem, roms_root, es_de_running=None):
    """-> a short line saying what was done."""
    k, p = problem.kind, problem.paths
    if not problem.fix:
        raise RuntimeError("RetroShelf can't fix this one: " + problem.detail)
    if k in ("leftover", "empty"):
        os.remove(p[0])
        return f"deleted {os.path.basename(p[0])}"
    if k in ("sheet", "playlist"):
        from compress import fix_refs  # (it lives with the code that renames files inside sheets)
        fix_refs(p[0], problem.data)
        return f"fixed {len(problem.data)} name{'s' if len(problem.data) != 1 else ''} in {os.path.basename(p[0])}"
    if k == "lonebin":
        cue = os.path.splitext(p[0])[0] + ".cue"
        if os.path.lexists(cue):
            raise RuntimeError(f"{os.path.basename(cue)} is already there")
        with open(cue, "w", encoding="utf-8", newline="\n") as f:
            f.write(problem.data)
        return f"wrote {os.path.basename(cue)}"
    if k == "media":
        n = 0
        for f in p:
            try:
                os.remove(f)
                n += 1
            except FileNotFoundError:
                pass
        mdir = os.path.join(scraper.media_root(roms_root), problem.system)
        for d, _, _ in sorted(os.walk(mdir), key=lambda t: -len(t[0])):  # folders left empty
            if d != mdir and not os.listdir(d) and os.path.relpath(d, mdir).count(os.sep) > 0:
                os.rmdir(d)
        return f"deleted {n:,} files"
    if k == "multidisc":
        folder = os.path.dirname(p[0])
        m3u = os.path.join(folder, problem.data + ".m3u")
        if os.path.lexists(m3u):
            raise RuntimeError(f"{os.path.basename(m3u)} is already there")
        running = scraper.es_de_running() if es_de_running is None else es_de_running
        if running:  # the discs are hidden in its gamelist, which it rewrites when it quits
            raise RuntimeError("ES-DE is running: close it first")
        import esde_collections, hiding  # (ES-DE's folder, and its hidden flag)
        with open(m3u, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(os.path.basename(d) + "\n" for d in p)
        hiding.set_hidden(scraper.gamelist_path(roms_root, problem.system), p)
        es_home = esde_collections.home(roms_root)
        if hiding.shows_hidden(es_home):
            hiding.stop_showing_hidden(es_home)
        return f"wrote {os.path.basename(m3u)} for {len(p)} discs, and hid the discs in ES-DE"
    if k == "gamelist":
        running = scraper.es_de_running() if es_de_running is None else es_de_running
        if running:
            raise RuntimeError("ES-DE is running, and rewrites gamelist.xml when it quits: close it first")
        gl = p[0]
        drop = {r.lower() for r in problem.data}
        tops, root = scraper.read_gamelist(gl)
        n = 0
        for g in list(root.findall("game")):
            el = g.find("path")
            path = (el.text or "").strip() if el is not None else ""
            rel = path[2:] if path.startswith("./") else path
            if rel.lower() in drop:
                root.remove(g)
                n += 1
        if n:
            shutil.copy2(gl, f"{gl}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
            scraper.save_gamelist(gl, tops)
        return f"removed {n:,} entries"
    raise RuntimeError(f"don't know how to fix {k}")


# ---------- small things ----------
def _size(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0


def _ago(s):
    for unit, n in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if s >= n:
            k = int(s // n)
            return f"{k} {unit}{'s' if k != 1 else ''} ago"
    return "just now"


def _human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
