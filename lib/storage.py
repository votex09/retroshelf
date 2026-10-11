"""Where the space goes: each system's games, their ES-DE media, and what could still be compressed.

    scan(roms_root, unit_key) -> [System], biggest first
    drive(roms_root)          -> (free, total) of the drive the ROMs are on, or None

unit_key groups a system's files into games the way the main window does (retroshelf.unit_key), so a game's
size here is the size of the row it has there."""
import os, shutil

import compress
import health
import scraper


class System:
    def __init__(self, name):
        self.name = name
        self.games = {}       # key -> {"paths": [...], "size": bytes}
        self.media = 0        # bytes in downloaded_media/<system>
        self.compressible = 0  # bytes of disc images Tools → Compress games would turn into .chd / .rvz

    @property
    def size(self):
        return sum(g["size"] for g in self.games.values())

    @property
    def total(self):
        return self.size + self.media

    def biggest(self, n=None):
        """[(key, size)], biggest first."""
        rows = sorted(((k, g["size"]) for k, g in self.games.items()), key=lambda r: (-r[1], r[0].lower()))
        return rows[:n] if n else rows


def tree_size(path):
    if not os.path.isdir(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for d, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return total


def scan_system(roms_root, name, unit_key):
    s = System(name)
    folder = os.path.join(roms_root, name)
    exts = health._exts(folder)
    try:
        entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
    except OSError:
        entries = []
    for e in entries:
        if e.name.startswith((".", "_")) or e.name == "systeminfo.txt":
            continue
        is_dir = e.is_dir()
        if not is_dir:
            ext = os.path.splitext(e.name)[1].lower()
            if ext in health.NOT_GAMES or (exts is not None and ext not in exts and not ext.endswith(health.PARTIAL)):
                continue
        key = e.name if e.name.lower().endswith(health.PARTIAL) else unit_key(e.name)
        g = s.games.setdefault(key, {"paths": [], "size": 0})
        g["paths"].append(e.path)
        g["size"] += tree_size(e.path)
    s.media = tree_size(os.path.join(scraper.media_root(roms_root), name))
    if compress.supported(name, exts):
        try:
            s.compressible = sum(j.size for _, jobs, _ in compress.plan(name, s.games, exts) for j in jobs)
        except OSError:
            pass
    return s


def scan(roms_root, unit_key, progress=lambda text, fraction: None, cancelled=lambda: False):
    names = health.systems(roms_root)
    out = []
    for i, name in enumerate(names):
        if cancelled():
            raise InterruptedError("cancelled")
        progress(f"Adding up {name} …", i / max(1, len(names)))
        s = scan_system(roms_root, name, unit_key)
        if s.games or s.media:
            out.append(s)
    out.sort(key=lambda s: (-s.total, s.name))
    return out


def drive(roms_root):
    try:
        du = shutil.disk_usage(roms_root)
    except OSError:
        return None
    return du.free, du.total
