"""Duplicates the main window's presets can't see:

  - formats  one game kept twice in its folder in different forms: .cue/.bin and .chd, .iso and .chd, a .zip and the
             ROM it holds … (the main window shows these as one row, since the name is the same)
  - copies   the same file in two places: two system folders (snes and sfc, genesis and megadrive …) or one folder
             under two names. Compared by content, so it doesn't matter what they're called.

    find(roms_root, unit_key) -> [Set]; each Set has .copies and .keep (the one to keep: chosen sensibly, changeable)
    resolve(sets, roms_root, holding_root) -> ({system: [[moved from, to]]}, [problems])

The copies not kept go to the holding folder, so Restore a move can put them back."""
import hashlib, os, re, shutil

import compress
import health
import scraper

SKIP_SYSTEMS = {"ps3", "psvita"}  # installed games (folders with data elsewhere): not compared
# when one game is there in several forms, keep the first of these that's there
PREFER = [".chd", ".rvz", ".cso", ".zso", ".pbp", ".cue", ".gdi", ".iso", ".gcz", ".wia", ".wbfs", ".7z", ".zip"]
DISC = re.compile(r"\((?:Disc|Disk|CD) \d", re.I)
PARTIAL_HASH = 64 << 20  # files bigger than this are compared by three 1 MB samples first


class Copy:
    """One form of a game: its files (a .cue and its tracks count as one), the one ES-DE lists, and their size."""

    def __init__(self, system, folder, paths, primary):
        self.system, self.folder, self.paths, self.primary = system, folder, list(paths), primary
        self.size = sum(_size(p) for p in self.paths)

    @property
    def fmt(self):
        if os.path.isdir(self.primary):
            return "folder"
        ext = os.path.splitext(self.primary)[1].lower()[1:]
        rest = len(self.paths) - 1
        return f"{ext} + {rest} file{'s' if rest != 1 else ''}" if rest else ext

    @property
    def rel(self):
        return os.path.relpath(self.primary, self.folder).replace(os.sep, "/")

    def __repr__(self):
        return f"Copy({self.system}/{self.rel})"


class Set:
    def __init__(self, kind, title, copies, keep=0):
        self.kind, self.title, self.copies, self.keep = kind, title, copies, keep

    @property
    def extra(self):
        """Space the copies not kept take."""
        return sum(c.size for i, c in enumerate(self.copies) if i != self.keep)


def _size(p):
    return compress._size(p)


def _forms(system, folder, paths):
    """A game's files -> [Copy], one per form it's kept in."""
    left = [p for p in paths if not p.lower().endswith(health.PARTIAL)]
    forms = []
    for sheet in [p for p in left if p.lower().endswith((".cue", ".gdi"))]:
        job = compress._sheet_job("cd", sheet, sheet)
        parts = job.parts if isinstance(job, compress.Job) else [sheet]
        parts = [p for p in parts if p in left]
        forms.append(Copy(system, folder, parts, sheet))
        left = [p for p in left if p not in parts]
    for p in left:
        forms.append(Copy(system, folder, [p], p))
    return forms


def _preferred(copies, listed=()):
    """Index of the copy to keep: the one ES-DE's gamelist knows (its play count, favorite, metadata), else the
    best format, else the smallest."""
    for i, c in enumerate(copies):
        if (c.system, c.rel.lower()) in listed:
            return i

    def rank(c):
        ext = os.path.splitext(c.primary)[1].lower()
        return (PREFER.index(ext) if ext in PREFER else len(PREFER), c.size, c.rel.lower())
    return min(range(len(copies)), key=lambda i: rank(copies[i]))


def _listed(roms_root, system):
    """{(system, path relative to the system folder, lowercase)} ES-DE's gamelist has entries for."""
    gl = scraper.find_gamelist(roms_root, system)
    if not gl:
        return set()
    try:
        _, root = scraper.read_gamelist(gl)
    except Exception:
        return set()
    out = set()
    for g in root.iter("game"):
        el = g.find("path")
        path = (el.text or "").strip() if el is not None else ""
        out.add((system, (path[2:] if path.startswith("./") else path).rstrip("/").lower()))
    return out


def _digest(path, size):
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            if size > PARTIAL_HASH:
                for at in (0, size // 2, size - (1 << 20)):
                    f.seek(at)
                    h.update(f.read(1 << 20))
            else:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _full_digest(path):
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _signature_file(c):
    """The file that tells copies apart: the biggest one (a disc's data track)."""
    files = [p for p in c.paths if os.path.isfile(p)]
    return max(files, key=_size) if files else None


def find(roms_root, unit_key, progress=lambda text, fraction: None, cancelled=lambda: False):
    systems = [s for s in health.systems(roms_root) if s not in SKIP_SYSTEMS]
    sets, everything = [], []
    for n, system in enumerate(systems):
        if cancelled():
            raise InterruptedError("cancelled")
        progress(f"Looking at {system} …", 0.5 * n / max(1, len(systems)))
        folder = os.path.join(roms_root, system)
        exts = health._exts(folder)
        games = {}
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
        except OSError:
            continue
        for e in entries:
            if e.name.startswith((".", "_")) or e.name == "systeminfo.txt":
                continue
            ext = os.path.splitext(e.name)[1].lower()
            if not e.is_dir() and (ext in health.NOT_GAMES or (exts is not None and ext not in exts)):
                continue
            games.setdefault(unit_key(e.name), []).append(e.path)
        listed = None
        for key, paths in games.items():
            forms = _forms(system, folder, paths)
            everything += [(key, c) for c in forms]
            # several forms of one game; not multi-disc sets (their discs share the key but are different discs)
            if len(forms) > 1 and not any(p.lower().endswith(".m3u") for p in paths) and \
                    not any(DISC.search(os.path.basename(p)) for p in paths):
                if listed is None:
                    listed = _listed(roms_root, system)
                sets.append(Set("formats", key, forms, _preferred(forms, listed)))
    # the same content in more than one place
    by_size = {}
    for key, c in everything:
        f = _signature_file(c)
        if f and c.size:
            by_size.setdefault(c.size, []).append((key, c, f))
    groups = [g for g in by_size.values() if len(g) > 1]
    listed_by = {}
    counts = {}  # games per folder: of copies in two folders, the one in the fuller folder is kept
    for _, c in everything:
        counts[c.system] = counts.get(c.system, 0) + 1
    for n, group in enumerate(groups):
        if cancelled():
            raise InterruptedError("cancelled")
        progress("Comparing files of the same size …", 0.5 + 0.5 * n / max(1, len(groups)))
        by_hash = {}
        for key, c, f in group:
            d = _digest(f, _size(f))
            if d:
                by_hash.setdefault(d, []).append((key, c, f))
        for same in by_hash.values():
            if len(same) < 2:
                continue
            if _size(same[0][2]) > PARTIAL_HASH:  # the samples matched: make sure
                full = {}
                for item in same:
                    full.setdefault(_full_digest(item[2]), []).append(item)
                same = max(full.values(), key=len)
                if len(same) < 2:
                    continue
            places = {(c.system, key) for key, c, _ in same}
            if len(places) < 2:
                continue  # one game's own forms (already a "formats" set)
            copies = [c for _, c, _ in same]
            for c in copies:
                if c.system not in listed_by:
                    listed_by[c.system] = _listed(roms_root, c.system)
            # keep the copy ES-DE knows, else the one in the fuller folder, else the cleaner name (no GoodTools [!])
            keep = min(range(len(copies)), key=lambda i: (
                (copies[i].system, copies[i].rel.lower()) not in listed_by[copies[i].system],
                -counts.get(copies[i].system, 0), "[" in copies[i].rel, copies[i].rel.lower()))
            sets.append(Set("copies", same[keep][0], copies, keep))  # named after the copy that stays
    sets.sort(key=lambda s: (s.kind != "formats", -s.extra, s.title.lower()))
    return sets


def _free_name(path):
    return compress._free_name(path)


def resolve(sets, roms_root, holding_root, es_de_running=False):
    """Move every copy that isn't kept into <holding>/to_delete/<system>/. For a game kept in another form in the
    same folder, ES-DE's gamelist entry is pointed at the form that's kept (so play counts and favorites stay).
    -> ({system: [[from, to]]}, [problems])."""
    moves, problems = {}, []
    for s in sets:
        kept = s.copies[s.keep]
        for i, c in enumerate(s.copies):
            if i == s.keep:
                continue
            dest = os.path.join(holding_root, "to_delete", c.system)
            os.makedirs(dest, exist_ok=True)
            for p in c.paths:
                try:
                    target = _free_name(os.path.join(dest, os.path.basename(p)))
                    shutil.move(p, target)
                    moves.setdefault(c.system, []).append([p, target])
                except OSError as e:
                    problems.append(f"{c.system}/{os.path.basename(p)}: {e}")
            if s.kind == "formats" and kept.system == c.system:
                gl = scraper.find_gamelist(roms_root, c.system)
                if gl and not es_de_running and (kept.system, kept.rel.lower()) not in _listed(roms_root, c.system):
                    try:
                        compress.repath_gamelist(gl, {c.rel: kept.rel})
                    except Exception as e:
                        problems.append(f"{c.system} gamelist.xml: {e}")
    return moves, problems
