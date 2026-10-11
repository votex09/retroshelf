"""Importing games: take whatever someone throws in (loose ROMs, disc images, zip / 7z / rar archives, folders of
them), work out which system each game is for, and file it into roms/<system> in a form the emulators read.

How a system is found, most certain first:
  1. the file type, when only one system uses it (.gba, .sfc, .nds, .gdi, ...);
  2. the disc or ROM itself: disc images (.iso, .bin/.cue, .cso, .rvz, ...) say what they are in their first
     sectors (PS2 and PS1 discs in SYSTEM.CNF, PSP's PSP_GAME folder, GameCube / Wii magic numbers, Sega's
     "SEGA SEGASATURN" header, ...), Mega Drive ROMs have "SEGA" at 0x100;
  3. the folder it came from ("PS2", "Sony - PlayStation 2", "gamecube", ...), for what the file can't tell.
The user can always pick the system by hand instead.

What happens to it: archives are unpacked (7z with lib/sevenzip.py, zip with zipfile, anything those can't do, and
rar, with 7-Zip / unrar / bsdtar when one is installed), except for arcade systems, whose emulators want the zip as
it is. A .bin disc image without a .cue gets one written, and full-size Xbox dumps are cut down to the game
partition xemu reads. Everything is unpacked into a hidden staging folder next to the system folders and only
moved into roms/<system> once it's complete, so ES-DE never lists half a game.
"""
import os, re, shutil, struct, subprocess, uuid, zipfile, zlib

import sevenzip
from fsutil import NO_WINDOW, is_windows

STAGING = ".retroshelf-import"
LIMIT = 64 << 20  # how far into an archived disc image the preview reads before giving up

LABELS = {
    "nes": "Nintendo Entertainment System", "fds": "Famicom Disk System", "snes": "Super Nintendo",
    "n64": "Nintendo 64", "gc": "Nintendo GameCube", "wii": "Nintendo Wii", "switch": "Nintendo Switch",
    "gb": "Game Boy", "gbc": "Game Boy Color", "gba": "Game Boy Advance", "nds": "Nintendo DS",
    "n3ds": "Nintendo 3DS", "virtualboy": "Virtual Boy", "pokemini": "Pokémon Mini",
    "psx": "PlayStation", "ps2": "PlayStation 2", "psp": "PlayStation Portable",
    "sg-1000": "Sega SG-1000", "mastersystem": "Sega Master System", "megadrive": "Sega Mega Drive / Genesis",
    "gamegear": "Sega Game Gear", "segacd": "Sega CD / Mega-CD", "sega32x": "Sega 32X", "saturn": "Sega Saturn",
    "dreamcast": "Sega Dreamcast", "pcengine": "PC Engine / TurboGrafx-16", "pcenginecd": "PC Engine CD",
    "supergrafx": "PC Engine SuperGrafx", "atari2600": "Atari 2600", "atari5200": "Atari 5200",
    "atari7800": "Atari 7800", "atarilynx": "Atari Lynx", "atarijaguar": "Atari Jaguar", "colecovision": "ColecoVision",
    "intellivision": "Intellivision", "vectrex": "Vectrex", "ngp": "Neo Geo Pocket", "ngpc": "Neo Geo Pocket Color",
    "neogeocd": "Neo Geo CD", "wonderswan": "WonderSwan", "wonderswancolor": "WonderSwan Color", "3do": "3DO",
    "xbox": "Xbox", "msx": "MSX", "pico8": "PICO-8", "tic80": "TIC-80",
    "mame": "Arcade (MAME)", "fbneo": "Arcade (FinalBurn Neo)", "neogeo": "Neo Geo (arcade)",
}
# arcade emulators find games by the zip's name and read it as it is: never unpack those
ARCADE = {"arcade", "mame", "mame-advmame", "mame-mame4all", "fba", "fbneo", "neogeo", "cps", "cps1", "cps2",
          "cps3", "naomi", "naomi2", "naomigd", "atomiswave", "model2", "model3", "hikaru", "triforce"}
# disc systems whose .bin images need a .cue next to them
CUE_SYSTEMS = {"psx", "saturn", "segacd", "pcenginecd", "neogeocd", "3do"}

EXT_SYSTEMS = {
    ".nes": "nes", ".unf": "nes", ".fds": "fds", ".sfc": "snes", ".smc": "snes", ".z64": "n64", ".n64": "n64",
    ".v64": "n64", ".gb": "gb", ".gbc": "gbc", ".gba": "gba", ".nds": "nds", ".3ds": "n3ds", ".cia": "n3ds",
    ".cci": "n3ds", ".cxi": "n3ds", ".3dsx": "n3ds", ".nsp": "switch", ".xci": "switch", ".wbfs": "wii",
    ".vb": "virtualboy", ".vboy": "virtualboy", ".min": "pokemini", ".sg": "sg-1000", ".sms": "mastersystem",
    ".gen": "megadrive", ".smd": "megadrive", ".gg": "gamegear", ".32x": "sega32x", ".gdi": "dreamcast",
    ".cdi": "dreamcast", ".pce": "pcengine", ".sgx": "supergrafx", ".a26": "atari2600", ".a52": "atari5200",
    ".a78": "atari7800", ".lnx": "atarilynx", ".j64": "atarijaguar", ".jag": "atarijaguar", ".col": "colecovision",
    ".int": "intellivision", ".vec": "vectrex", ".ngp": "ngp", ".ngc": "ngpc", ".ws": "wonderswan",
    ".wsc": "wonderswancolor", ".p8.png": "pico8", ".p8": "pico8", ".tic": "tic80", ".mx1": "msx", ".mx2": "msx",
}
# formats whose system comes from what's inside
SNIFF_EXTS = (".iso", ".bin", ".img", ".mdf", ".cue", ".chd", ".cso", ".pbp", ".rvz", ".wia", ".gcz", ".md")
ARCHIVE_EXTS = (".zip", ".7z", ".rar")
ROM_EXTS = tuple(EXT_SYSTEMS) + SNIFF_EXTS + (".m3u",)

# folder names that say what's in them (whole words, longest first)
HINTS = {
    "ps2": "ps2", "playstation 2": "ps2", "playstation2": "ps2", "psx": "psx", "ps1": "psx", "psone": "psx",
    "playstation": "psx", "psp": "psp", "playstation portable": "psp", "gamecube": "gc", "game cube": "gc",
    "ngc": "gc", "gc": "gc", "wii": "wii", "saturn": "saturn", "sega saturn": "saturn", "dreamcast": "dreamcast",
    "sega cd": "segacd", "segacd": "segacd", "mega cd": "segacd", "mega-cd": "segacd", "megacd": "segacd",
    "xbox": "xbox", "3do": "3do", "pc engine cd": "pcenginecd", "pcengine cd": "pcenginecd",
    "pcenginecd": "pcenginecd", "turbografx cd": "pcenginecd", "turbografx-cd": "pcenginecd",
    "neo geo cd": "neogeocd", "neogeocd": "neogeocd", "mame": "mame", "arcade": "mame", "fbneo": "fbneo",
    "finalburn neo": "fbneo", "neogeo": "neogeo", "neo geo": "neogeo", "genesis": "megadrive",
    "mega drive": "megadrive", "megadrive": "megadrive", "atari 2600": "atari2600", "atari2600": "atari2600",
    "msx": "msx", "jaguar": "atarijaguar", "lynx": "atarilynx", "nds": "nds", "3ds": "n3ds", "n64": "n64", "nintendo 64": "n64",
    "snes": "snes", "super nintendo": "snes", "nes": "nes", "gba": "gba", "game boy advance": "gba",
}
HINT_RE = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(k) for k in sorted(HINTS, key=len, reverse=True))
                     + r")(?![a-z0-9])")

SYNC = b"\x00" + b"\xff" * 10 + b"\x00"
XBOX_MAGIC = b"MICROSOFT*XBOX*MEDIA"
XBOX_REDUMP_OFFSET = 0x18300000  # full Xbox dumps: the game partition xemu reads starts here
SPLIT_RE = re.compile(r"\.(7z|zip)\.(\d{3})$", re.I)
RAR_PART_RE = re.compile(r"\.part(\d+)\.rar$", re.I)


def ext_of(name):
    low = name.lower()
    for e in (".p8.png",):
        if low.endswith(e):
            return e
    return os.path.splitext(low)[1]


def is_archive(name):
    low = name.lower()
    return low.endswith(ARCHIVE_EXTS) or bool(SPLIT_RE.search(low))


def wanted_member(name):
    """Worth unpacking: a ROM / disc file (readmes, pictures and .exe tools in an archive are left out)."""
    return ext_of(name) in ROM_EXTS or not os.path.splitext(name)[1]


def label(system):
    return LABELS.get(system, system) if system else "?"


def hint(path):
    """A system from the folder names in path ("…/Sony - PlayStation 2/x.7z" -> "ps2"), or None."""
    for part in reversed(os.path.normpath(os.path.dirname(path)).replace("\\", "/").split("/")):
        m = HINT_RE.findall(part.lower().replace("_", " "))
        if m:
            return HINTS[max(m, key=len)]
    return None


# ---------- looking inside discs and ROMs ----------
def _read(f, offset, n):
    try:
        f.seek(offset)
        return f.read(n)
    except (OSError, ValueError, EOFError, zlib.error):
        return b""


class Disc:
    """2048-byte data sectors of a disc image: plain ISO, raw 2352-byte sectors (.bin), or a CSO."""

    def __init__(self, f, base=0):
        self.f, self.base = f, base
        head = _read(f, base, 16)
        self.raw = head[:12] == SYNC
        self.mode = head[15] if self.raw and len(head) > 15 else 1
        self.cso = None
        if head[:4] == b"CISO":
            hdr = _read(f, 0, 24)
            total, block, _, align = struct.unpack("<QIBB", hdr[8:22]) if len(hdr) == 24 else (0, 0, 0, 0)
            if block:
                self.cso = (block, align, total)

    def sector(self, lba, n=1):
        if self.cso:
            return self._cso_read(lba * 2048, n * 2048)
        if not self.raw:
            return _read(self.f, self.base + lba * 2048, n * 2048)
        skip = 16 if self.mode == 1 else 24
        return b"".join(_read(self.f, self.base + (lba + i) * 2352 + skip, 2048) for i in range(n))

    def _cso_read(self, offset, n):
        block, align, total = self.cso
        out = b""
        while n > 0 and offset < total:
            i = offset // block
            idx = _read(self.f, 24 + i * 4, 8)
            if len(idx) < 8:
                break
            a, b = struct.unpack("<II", idx)
            start, end = (a & 0x7FFFFFFF) << align, (b & 0x7FFFFFFF) << align
            data = _read(self.f, start, end - start)
            if not a & 0x80000000:  # compressed (raw deflate)
                try:
                    data = zlib.decompress(data, -15)
                except zlib.error:
                    break
            piece = data[offset % block:offset % block + n]
            if not piece:
                break
            out += piece
            offset += len(piece)
            n -= len(piece)
        return out

    def root(self):
        """{NAME: (lba, size)} of the ISO 9660 root folder, or None when it isn't one."""
        pvd = self.sector(16)
        if pvd[1:6] != b"CD001":
            return None
        rec = pvd[156:190]
        lba, size = struct.unpack("<I", rec[2:6])[0], struct.unpack("<I", rec[10:14])[0]
        data = self.sector(lba, min(max(size // 2048, 1), 16))
        out, i = {}, 0
        while i < len(data):
            n = data[i]
            if n == 0:  # records don't cross sectors: jump to the next one
                i = (i // 2048 + 1) * 2048
                continue
            r = data[i:i + n]
            name = r[33:33 + r[32]].decode("latin-1").split(";")[0].upper()
            out[name] = (struct.unpack("<I", r[2:6])[0], struct.unpack("<I", r[10:14])[0])
            i += n
        return out

    def volume_bytes(self):
        pvd = self.sector(16)
        return struct.unpack("<I", pvd[80:84])[0] * 2048 if pvd[1:6] == b"CD001" else 0


def sniff_disc(f, base=0):
    """(system, how) for a disc image, or (None, note)."""
    head = _read(f, base, 0x60)
    if len(head) < 0x60:
        return None, "too small to be a disc"
    if head[0x1C:0x20] == b"\xc2\x33\x9f\x3d":
        return "gc", "GameCube disc"
    if head[0x18:0x1C] == b"\x5d\x1c\x9e\xa3":
        return "wii", "Wii disc"
    d = Disc(f, base)
    first = d.sector(0)
    if first.startswith(b"SEGA SEGASATURN"):
        return "saturn", "Saturn disc"
    if first.startswith((b"SEGADISCSYSTEM", b"SEGABOOTDISC")):
        return "segacd", "Sega CD disc"
    if first.startswith(b"SEGA SEGAKATANA"):
        return "dreamcast", "Dreamcast disc"
    if first[:7] == b"\x01\x5a\x5a\x5a\x5a\x5a\x01":
        return "3do", "3DO disc"
    if b"PC Engine CD-ROM SYSTEM" in d.sector(1)[:0x40]:
        return "pcenginecd", "PC Engine CD disc"
    if _read(f, base + 0x10000, 20) == XBOX_MAGIC:
        return "xbox", "Xbox disc"
    if _read(f, base + XBOX_REDUMP_OFFSET + 0x10000, 20) == XBOX_MAGIC:
        return "xbox", "Xbox disc (full dump)"
    root = d.root()
    if root is None:
        return None, "not a disc image RetroShelf knows"
    if "PSP_GAME" in root or "UMD_DATA.BIN" in root:
        return "psp", "PSP disc"
    if "PS3_GAME" in root or "PS3_DISC.SFB" in root:
        return None, "a PS3 disc (RetroShelf doesn't import those)"
    if "SYSTEM.CNF" in root:
        lba, size = root["SYSTEM.CNF"]
        cnf = d.sector(lba)[:min(size, 2048)]
        if b"BOOT2" in cnf:
            return "ps2", "PS2 disc"
        if b"BOOT" in cnf:
            return "psx", "PS1 disc"
        if not cnf and d.volume_bytes() > 900 << 20:  # couldn't read that far into an archive: size tells
            return "ps2", "PlayStation disc bigger than a CD"
    if "IPL.TXT" in root:
        return "neogeocd", "Neo Geo CD disc"
    return None, "a disc RetroShelf can't place"


def cue_for(name, head):
    """The .cue a lone raw CD image (.bin / .img) needs, from its first 16 bytes; None if it isn't one."""
    if head[:12] != SYNC:
        return None
    mode = "MODE1/2352" if head[15] == 1 else "MODE2/2352"
    return f'FILE "{name}" BINARY\n  TRACK 01 {mode}\n    INDEX 01 00:00:00\n'


def parse_cue(text):
    """-> [(file name, track mode, start in bytes)] for each track."""
    tracks, current = [], None
    for line in text.splitlines():
        m = re.match(r'\s*FILE\s+(?:"([^"]+)"|(\S+))', line, re.I)
        if m:
            current = m.group(1) or m.group(2)
            continue
        m = re.match(r"\s*TRACK\s+\d+\s+(\S+)", line, re.I)
        if m and current:
            tracks.append([current, m.group(1).upper(), 0])
            continue
        m = re.match(r"\s*INDEX\s+01\s+(\d+):(\d+):(\d+)", line, re.I)
        if m and tracks:
            mm, ss, ff = map(int, m.groups())
            size = 2048 if tracks[-1][1].endswith("/2048") else 2352
            tracks[-1][2] = ((mm * 60 + ss) * 75 + ff) * size
    return [tuple(t) for t in tracks]


def parse_gdi(text):
    names = []
    for line in text.splitlines()[1:]:
        m = re.match(r'\s*\d+\s+\d+\s+\d+\s+\d+\s+(?:"([^"]+)"|(\S+))', line)
        if m:
            names.append(m.group(1) or m.group(2))
    return names


def parse_m3u(text):
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def sniff_chd(f):
    head = _read(f, 0, 124)
    if head[:8] != b"MComprHD":
        return None, "not a CHD"
    version = struct.unpack(">I", head[12:16])[0]
    if version != 5:
        return None, "an old CHD"
    pos = struct.unpack(">Q", head[48:56])[0]
    tags = set()
    for _ in range(64):
        if not pos:
            break
        meta = _read(f, pos, 16)
        if len(meta) < 16:
            break
        tags.add(meta[:4])
        pos = struct.unpack(">Q", meta[8:16])[0]
    if b"CHGD" in tags:
        return "dreamcast", "Dreamcast disc"
    if b"DVD " in tags:
        return "ps2", "DVD image (most are PS2)"
    return None, "a CD image (its system isn't written outside the compressed data)"


def sniff_rom(name, f, size):
    """(system, how) for one file, from its type and contents. (None, note) when it can't tell."""
    ext = ext_of(name)
    if ext == ".md":  # Mega Drive, or a readme
        return ("megadrive", "Mega Drive ROM") if _read(f, 0x100, 4) == b"SEGA" else (None, "a text file")
    if ext in EXT_SYSTEMS:
        return EXT_SYSTEMS[ext], "file type"
    if ext == ".chd":
        return sniff_chd(f)
    if ext == ".pbp":
        head = _read(f, 0, 0x28)
        if head[:4] != b"\x00PBP":
            return None, "not a PBP"
        psar = _read(f, struct.unpack("<I", head[0x24:0x28])[0], 8)
        return ("psx", "PS1 game for PSP") if psar in (b"PSISOIMG", b"PSTITLEI") else ("psp", "PSP game")
    if ext in (".rvz", ".wia"):
        head = _read(f, 0, 0x4C)
        kind = struct.unpack(">I", head[0x48:0x4C])[0] if len(head) == 0x4C else 0
        return {1: ("gc", "GameCube disc"), 2: ("wii", "Wii disc")}.get(kind, (None, "unreadable RVZ"))
    if ext == ".gcz":
        head = _read(f, 0, 8)
        kind = struct.unpack("<I", head[4:8])[0] if len(head) == 8 else -1
        return {0: ("gc", "GameCube disc"), 1: ("wii", "Wii disc")}.get(kind, (None, "unreadable GCZ"))
    if ext == ".cso":
        system, how = sniff_disc(f)
        return (system, how) if system else ("psp", "CSO image (most are PSP)")
    if ext in (".iso", ".bin", ".img", ".mdf"):
        system, how = sniff_disc(f)
        if system or ext != ".bin":
            return system, how
        head = _read(f, 0x100, 16)
        if head.startswith(b"SEGA 32X"):
            return "sega32x", "32X ROM"
        if head.startswith(b"SEGA"):
            return "megadrive", "Mega Drive ROM"
        return None, "a .bin RetroShelf can't place"
    return None, "not a game file"


# ---------- games found in a set of files ----------
class Unit:
    """One game: its files (relative names inside the row's folder or archive), the main one first."""

    def __init__(self, files, size=0):
        self.files, self.size = files, size
        self.system, self.how = None, ""
        self.cue = None      # text of a .cue to write next to a lone .bin
        self.xbox_trim = False

    @property
    def main(self):
        return self.files[0]

    def __repr__(self):
        return f"Unit({self.files}, {self.system!r})"


def _norm(p):
    return p.replace("\\", "/")


def group(names, read_text):
    """Split file names (relative, '/'-separated) into games: a .cue / .gdi / .m3u takes the files it lists.
    read_text(name) -> its text. -> ([Unit], [names left over that aren't games])."""
    names = [_norm(n) for n in names]
    by_lower = {n.lower(): n for n in names}
    taken, units = set(), []

    def listed(sheet, refs):
        folder = os.path.dirname(sheet)
        out = []
        for r in refs:
            n = by_lower.get(_norm(os.path.join(folder, _norm(r))).lower())
            if n and n not in out:
                out.append(n)
        return out

    for n in sorted(names):
        ext = ext_of(n)
        if ext not in (".cue", ".gdi") or n in taken:
            continue
        try:
            text = read_text(n)
        except (OSError, UnicodeError, ValueError):
            text = ""
        refs = [t[0] for t in parse_cue(text)] if ext == ".cue" else parse_gdi(text)
        files = [n] + [f for f in listed(n, refs) if f not in taken]
        taken.update(files)
        units.append(Unit(files))
    for n in sorted(names):
        if n in taken or ext_of(n) not in ROM_EXTS or ext_of(n) in (".cue", ".gdi", ".m3u"):
            continue
        taken.add(n)
        units.append(Unit([n]))
    # playlists go with the discs they list
    for n in sorted(names):
        if ext_of(n) != ".m3u" or n in taken:
            continue
        try:
            refs = [_norm(os.path.join(os.path.dirname(n), r)).lower() for r in parse_m3u(read_text(n))]
        except (OSError, UnicodeError, ValueError):
            refs = []
        owner = next((u for u in units if any(f.lower() in refs for f in u.files)), None)
        if owner:
            owner.files.append(n)
            taken.add(n)
    leftover = [n for n in names if n not in taken]
    return units, leftover


def games(units):
    """Units that are games (a .md that turned out to be a readme isn't)."""
    return [u for u in units if not (ext_of(u.main) == ".md" and not u.system)]


def detect(unit, opener, sizes, fallback=None):
    """Work out the unit's system. opener(name) -> a binary file object (or None), sizes: {name: bytes}."""
    unit.size = sum(sizes.get(n, 0) for n in unit.files)
    main = unit.main
    ext = ext_of(main)
    system, how = None, ""
    if ext == ".cue":
        try:
            with opener(main) as f:
                tracks = parse_cue(f.read(1 << 16).decode("utf-8", "replace"))
        except (OSError, AttributeError, ValueError):
            tracks = []
        folder = os.path.dirname(main)
        lower = {n.lower(): n for n in unit.files}
        for name, mode, start in tracks:
            if mode == "AUDIO":
                continue
            n = lower.get(_norm(os.path.join(folder, name)).lower())
            if not n:
                continue
            f = opener(n)
            if f is None:
                continue
            with f:
                system, how = sniff_disc(f, start)
            if system:
                break
        if not tracks:
            how = "the .cue lists no tracks it came with"
        elif not system and not how:
            how = "the .cue's tracks are missing"
    else:
        f = opener(main)
        if f is None:
            how = "can't look inside"
        else:
            with f:
                system, how = sniff_rom(main, f, sizes.get(main, 0))
                if system in CUE_SYSTEMS and ext in (".bin", ".img") and len(unit.files) == 1:
                    unit.cue = cue_for(os.path.basename(main), _read(f, 0, 16))
                if system == "xbox" and how.endswith("(full dump)"):
                    unit.xbox_trim = True
    if not system and fallback and ext != ".md":
        system, how = fallback, "folder name"
    unit.system, unit.how = system, how
    return unit


# ---------- archives ----------
class JoinedFile:
    """Split archives (game.7z.001, .002, ...) read as one file."""

    def __init__(self, paths):
        self.parts = [(p, os.path.getsize(p)) for p in paths]
        self.size = sum(s for _, s in self.parts)
        self.pos, self.f, self.cur = 0, None, None

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def tell(self):
        return self.pos

    def seekable(self):
        return True

    def readable(self):
        return True

    def read(self, n=-1):
        n = self.size - self.pos if n is None or n < 0 else min(n, self.size - self.pos)
        out, start = [], 0
        for i, (p, s) in enumerate(self.parts):
            if n <= 0:
                break
            if self.pos < start + s:
                if self.cur != i:
                    if self.f:
                        self.f.close()
                    self.f, self.cur = open(p, "rb"), i
                self.f.seek(self.pos - start)
                data = self.f.read(min(n, start + s - self.pos))
                out.append(data)
                self.pos += len(data)
                n -= len(data)
            start += s
        return b"".join(out)

    def close(self):
        if self.f:
            self.f.close()
            self.f = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def split_parts(path):
    """All parts of a split archive, given its first (.001 / .part1.rar)."""
    m = SPLIT_RE.search(path)
    r = RAR_PART_RE.search(path)
    if r:
        stem, width = path[:r.start(1)], len(r.group(1))
        parts, i = [], 1
        while os.path.exists(f"{stem}{i:0{width}d}.rar"):
            parts.append(f"{stem}{i:0{width}d}.rar")
            i += 1
        return parts or [path]
    if not m:
        return [path]
    stem, parts = path[:m.start(2)], []
    i = 1
    while os.path.exists(f"{stem}{i:03d}"):
        parts.append(f"{stem}{i:03d}")
        i += 1
    return parts


def find_tool():
    """(kind, exe) of an installed unpacker that handles rar and 7z's rarer methods, or (None, None)."""
    names = [("7z", "7zz"), ("7z", "7z"), ("7z", "7za"), ("unrar", "unrar"), ("bsdtar", "bsdtar")]
    for kind, n in names:
        exe = shutil.which(n)
        if exe:
            return kind, exe
    if is_windows():
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            for kind, rel in (("7z", r"7-Zip\7z.exe"), ("unrar", r"WinRAR\UnRAR.exe")):
                exe = os.path.join(base, rel)
                if os.path.exists(exe):
                    return kind, exe
        tar = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
        if os.path.exists(tar):  # Windows 11's tar reads 7z and rar
            return "bsdtar", tar
    return None, None


def tool_extract(path, dest, cancelled=lambda: False):
    kind, exe = find_tool()
    if not exe:
        what = "rar" if path.lower().endswith(".rar") else "this kind of"
        raise RuntimeError(f"unpacking {what} archive needs 7-Zip: install it "
                           f"({'7-zip.org' if is_windows() else 'the 7zip or p7zip package'}) and try again")
    if kind == "7z":
        cmd = [exe, "x", "-y", "-bd", "-pnone", f"-o{dest}", path]  # a password given: fails instead of asking
    elif kind == "unrar":
        cmd = [exe, "x", "-o+", "-y", "-p-", path, dest + os.sep]
    else:
        cmd = [exe, "-xf", path, "-C", dest]
    os.makedirs(dest, exist_ok=True)
    with subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          creationflags=NO_WINDOW) as p:
        while True:
            try:
                out = p.communicate(timeout=0.5)[0]
                break
            except subprocess.TimeoutExpired:
                if cancelled():
                    p.kill()
                    raise InterruptedError("cancelled")
    if p.returncode:
        text = (out or b"").decode("utf-8", "replace").strip().splitlines()
        msg = next((t for t in reversed(text) if "rror" in t or "password" in t.lower()), text[-1] if text else "")
        if "password" in msg.lower() or "encrypted" in msg.lower():
            raise RuntimeError("the archive is password-protected")
        raise RuntimeError(f"{os.path.basename(exe)} couldn't unpack it: {msg[:200]}")
    # nothing may point outside the staging folder: drop links the archive carried
    for d, dirs, files in os.walk(dest):
        for n in dirs + files:
            p_ = os.path.join(d, n)
            if os.path.islink(p_):
                os.unlink(p_)


class Archive:
    """A zip / 7z (built in) or rar / anything else (an installed tool) — what's in it and how to unpack it."""

    def __init__(self, path):
        self.path = path
        self.parts = split_parts(path)
        self.f = JoinedFile(self.parts) if len(self.parts) > 1 else open(path, "rb")
        magic = self.f.read(6)
        self.f.seek(0)
        self.kind, self.z, self.members = "tool", None, None
        try:
            if magic[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
                self.z = zipfile.ZipFile(self.f)
                self.kind = "zip"
                self.members = {_norm(i.filename): i.file_size for i in self.z.infolist() if not i.is_dir()}
            elif magic == sevenzip.SIGNATURE:
                self.z = sevenzip.SevenZip(self.f)
                self.kind = "7z"
                self.members = {e.name: e.size for e in self.z.files()}
        except (zipfile.BadZipFile, ValueError, OSError):
            self.kind, self.z, self.members = "tool", None, None

    def close(self):
        if self.z and self.kind == "zip":
            self.z.close()
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def size(self):
        return sum(self.members.values()) if self.members else 0

    def open(self, name):
        """A seekable stream of one member, or None."""
        try:
            if self.kind == "zip":
                return _Limited(self.z.open(name), LIMIT)
            if self.kind == "7z":
                e = next(e for e in self.z.files() if e.name == name)
                return _Limited(self.z.open(e), LIMIT)
        except (KeyError, StopIteration, NotImplementedError, sevenzip.Unsupported, RuntimeError, OSError):
            return None
        return None

    def read_text(self, name):
        f = self.open(name)
        if f is None:
            return ""
        with f:
            return f.read(1 << 20).decode("utf-8", "replace")

    def extract(self, dest, progress=lambda done, total: None, cancelled=lambda: False):
        """Unpack the games (not readmes or tools) into dest."""
        root = os.path.realpath(dest)
        os.makedirs(root, exist_ok=True)
        try:
            if self.kind == "7z":
                self.z.extract_all(root, progress, cancelled, wanted=lambda e: wanted_member(e.name))
                return
            if self.kind == "zip":
                infos = [i for i in self.z.infolist() if not i.is_dir() and wanted_member(i.filename)]
                total, done = sum(i.file_size for i in infos), 0
                for i in infos:
                    target = os.path.realpath(os.path.join(root, *[p for p in _norm(i.filename).split("/")
                                                                   if p not in ("", ".")]))
                    if not target.startswith(root + os.sep):
                        raise ValueError(f"unsafe path in the archive: {i.filename}")
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with self.z.open(i) as src, open(target, "wb") as out:
                        while True:
                            if cancelled():
                                raise InterruptedError("cancelled")
                            chunk = src.read(1 << 20)
                            if not chunk:
                                break
                            out.write(chunk)
                            done += len(chunk)
                            progress(done, total)
                return
        except (sevenzip.Unsupported, NotImplementedError) as e:
            if isinstance(e, sevenzip.Encrypted):
                raise RuntimeError("the archive is password-protected") from e
            shutil.rmtree(root, ignore_errors=True)  # start over with a real unpacker
            os.makedirs(root, exist_ok=True)
        except RuntimeError as e:  # zipfile: encrypted member
            if "encrypted" in str(e).lower() or "password" in str(e).lower():
                raise RuntimeError("the archive is password-protected") from e
            raise
        tool_extract(self.parts[0], root, cancelled)


class _Limited:
    """Stops reading an archived file past a point (decoding gigabytes just to look would be slow)."""

    def __init__(self, f, limit):
        self.f, self.limit = f, limit

    def seek(self, offset, whence=0):
        if whence == 0 and offset > self.limit:
            raise ValueError("too far in")
        return self.f.seek(offset, whence)

    def read(self, n=-1):
        return self.f.read(n)

    def tell(self):
        return self.f.tell()

    def close(self):
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------- what's in the import list ----------
class Row:
    """One thing to import: an archive (path), or loose game files (a Unit of paths relative to folder)."""

    def __init__(self, path, folder=None, unit=None, inbox=False):
        self.path, self.folder, self.unit, self.inbox = path, folder, unit, inbox
        self.units = [unit] if unit else []
        self.archive = unit is None
        self.override = None
        self.status = ""
        self.size = 0
        self.leftover = []
        self.opaque = False  # an archive only an installed unpacker can list: what's in it shows once unpacked

    @property
    def name(self):
        return os.path.basename(self.path) if self.archive else self.unit.main.rsplit("/", 1)[-1]

    def sources(self):
        """The files this row takes away from where they are (archives: every part)."""
        if self.archive:
            return split_parts(self.path)
        return [os.path.join(self.folder, *f.split("/")) for f in self.unit.files]

    def systems(self):
        return sorted({u.system for u in self.units if u.system})

    def system(self):
        """The one system everything goes to, the user's pick first; None if unknown or mixed."""
        if self.override:
            return self.override
        s = self.systems()
        return s[0] if len(s) == 1 and all(u.system for u in self.units) else None

    def ready(self):
        """Whether Import can do something with it."""
        if self.override:
            return True
        if self.archive:
            return self.opaque or any(u.system for u in self.units)
        return bool(self.unit.system)

    def describe(self):
        if self.override:
            return label(self.override)
        s = self.systems()
        if not self.units:
            return "?"
        if len(s) > 1:
            return "Mixed: " + ", ".join(label(x) for x in s)
        if not s:
            return "?"
        missing = sum(1 for u in self.units if not u.system)
        return label(s[0]) + (f" (+{missing} unknown)" if missing else "")


def _skip_name(name):
    return name.startswith(".") or name.lower().endswith((".part", ".crdownload", ".tmp", ".download"))


def collect(paths, inbox=None):
    """Rows for files and folders (folders are walked). Loose files in one folder are grouped into games."""
    rows, loose = [], {}  # folder -> [names]
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            for d, dirs, files in os.walk(p):
                dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x != STAGING)
                for n in sorted(files):
                    if not _skip_name(n):
                        _add(os.path.join(d, n), rows, loose)
        elif os.path.isfile(p) and not _skip_name(os.path.basename(p)):
            _add(p, rows, loose)
            folder = os.path.dirname(p)
            sheets = [p] if ext_of(p) in (".cue", ".gdi", ".m3u") else []
            if ext_of(p) in (".bin", ".img", ".iso"):  # a track picked on its own: its .cue comes too
                try:
                    sheets = [os.path.join(folder, n) for n in os.listdir(folder) if ext_of(n) == ".cue"
                              and os.path.basename(p).lower() in _text_file(os.path.join(folder, n)).lower()]
                except OSError:
                    sheets = []
            for sheet in sheets:
                loose.setdefault(folder, set()).add(os.path.basename(sheet))
                text = _text_file(sheet)
                refs = [t[0] for t in parse_cue(text)] or parse_gdi(text) or parse_m3u(text)
                for r in refs:
                    q = os.path.normpath(os.path.join(folder, r))
                    if os.path.isfile(q) and os.path.dirname(q) == folder:
                        loose.setdefault(folder, set()).add(os.path.basename(q))
    for folder, names in loose.items():
        units, _ = group(sorted(names), lambda n: _text_file(os.path.join(folder, n)))
        for u in units:
            rows.append(Row(os.path.join(folder, u.main), folder, u))
    for r in rows:
        r.inbox = bool(inbox) and _inside(r.path, inbox)
    # one row per path, archives and loose games both
    seen, out = set(), []
    for r in rows:
        key = os.path.normcase(r.path)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _add(path, rows, loose):
    name = os.path.basename(path)
    low = name.lower()
    m = SPLIT_RE.search(low)
    if m and m.group(2) != "001":
        return  # a later part of a split archive: comes with the .001
    rp = RAR_PART_RE.search(low)
    if rp and int(rp.group(1)) != 1:
        return
    if is_archive(name):
        rows.append(Row(path))
    elif ext_of(name) in ROM_EXTS:
        loose.setdefault(os.path.dirname(path), set()).add(name)


def _text_file(path):
    try:
        with open(path, "rb") as f:
            return f.read(1 << 20).decode("utf-8", "replace")
    except OSError:
        return ""


def _inside(path, folder):
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(folder)]) == os.path.abspath(folder)
    except ValueError:
        return False


def scan(row):
    """Look at what the row holds and guess each game's system (archives: by peeking inside)."""
    fallback = hint(row.path)
    if not row.archive:
        sizes = {}
        for f in row.unit.files:
            try:
                sizes[f] = os.path.getsize(os.path.join(row.folder, *f.split("/")))
            except OSError:
                sizes[f] = 0

        def opener(n):
            try:
                return open(os.path.join(row.folder, *n.split("/")), "rb")
            except OSError:
                return None
        detect(row.unit, opener, sizes, fallback)
        row.size = row.unit.size
        return row
    row.size = sum(os.path.getsize(p) for p in split_parts(row.path) if os.path.exists(p))
    try:
        with Archive(row.path) as a:
            if a.members is None:
                row.units, row.opaque = [], bool(find_tool()[1])
                if not row.opaque:
                    row.status = "needs 7-Zip installed to unpack"
                if fallback:
                    u = Unit([os.path.basename(row.path)])
                    u.system, u.how = fallback, "folder name"
                    row.units = [u]
                return row
            units, leftover = group(list(a.members), a.read_text)
            for u in units:
                detect(u, a.open, a.members, fallback)
            row.units, row.leftover = games(units), leftover
            row.unpacked_size = a.size()
            if not row.units:
                if fallback in ARCADE:
                    u = Unit([os.path.basename(row.path)])
                    u.system, u.how = fallback, "folder name"
                    row.units = [u]
                else:
                    row.status = "an arcade set? pick its system" if a.kind == "zip" else "no games inside"
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        row.status = f"can't read it: {e}"
    return row


# ---------- importing ----------
def staging_dir(roms_root):
    return os.path.join(roms_root, STAGING)


def _move_or_copy(src, dest, move):
    if move:
        shutil.move(src, dest)
    else:
        shutil.copy2(src, dest)


def _copy_from(src, dest, offset, cancelled):
    with open(src, "rb") as a, open(dest + ".part", "wb") as b:
        a.seek(offset)
        while True:
            if cancelled():
                raise InterruptedError("cancelled")
            chunk = a.read(1 << 22)
            if not chunk:
                break
            b.write(chunk)
    os.replace(dest + ".part", dest)


def place(unit, folder, roms_root, system, move, cancelled=lambda: False):
    """Put a unit's files (in folder) into roms/<system>. -> [paths]. Raises FileExistsError if it's there."""
    dest_dir = os.path.join(roms_root, system)
    os.makedirs(dest_dir, exist_ok=True)
    pairs = [(os.path.join(folder, *f.split("/")), os.path.join(dest_dir, f.rsplit("/", 1)[-1])) for f in unit.files]
    cue = None
    if unit.cue and system in CUE_SYSTEMS:
        cue = os.path.join(dest_dir, os.path.splitext(os.path.basename(unit.main))[0] + ".cue")
    for _, d in pairs + ([(None, cue)] if cue else []):
        if os.path.exists(d):
            raise FileExistsError(f"{os.path.basename(d)} is already in roms/{system}")
    out = []
    for s, d in pairs:
        if unit.xbox_trim and s == pairs[0][0] and system == "xbox":
            _copy_from(s, d, XBOX_REDUMP_OFFSET, cancelled)
            if move:
                os.unlink(s)
        else:
            _move_or_copy(s, d, move)
        out.append(d)
    if cue:
        with open(cue, "w", encoding="utf-8", newline="\n") as f:
            f.write(unit.cue)
        out.append(cue)
    return out


def free_bytes(path):
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def import_row(row, roms_root, report=lambda text=None, fraction=None: None, cancelled=lambda: False,
               delete_originals=False):
    """Import one row. -> [(Unit, [paths] or Exception)]. Inbox rows (and others if delete_originals) have
    their source removed once everything in them was imported."""
    remove = row.inbox or delete_originals
    results = []
    if not row.archive:
        system = row.override or row.unit.system
        if not system:
            raise ValueError("RetroShelf can't tell which system this is for: pick one")
        results.append((row.unit, place(row.unit, row.folder, roms_root, system, remove, cancelled)))
        return results
    override = row.override
    target = row.system()
    if target in ARCADE:  # arcade sets stay zipped, named as they are
        if not row.path.lower().endswith(".zip"):
            raise ValueError("arcade games must be .zip files named after the game's set")
        u = Unit([os.path.basename(row.path)])
        results.append((u, place(u, os.path.dirname(row.path), roms_root, target, remove, cancelled)))
        return results
    need = getattr(row, "unpacked_size", 0)
    free = free_bytes(roms_root)
    if need and free is not None and need > free:
        raise OSError(f"not enough space: it needs {need / 2**30:.1f} GB and the drive has {free / 2**30:.1f} GB")
    stage = os.path.join(staging_dir(roms_root), uuid.uuid4().hex[:12])
    try:
        report(f"Unpacking {row.name} …")
        with Archive(row.path) as a:
            a.extract(stage, lambda d, t: report(None, d / t if t else None), cancelled)
        names = []
        for d, _, files in os.walk(stage):
            names += [_norm(os.path.relpath(os.path.join(d, n), stage)) for n in files]
        units, _ = group(names, lambda n: _text_file(os.path.join(stage, *n.split("/"))))
        fallback = hint(row.path)
        preview = {u.main: u.system for u in row.units}
        for u in units:
            def opener(n):
                try:
                    return open(os.path.join(stage, *n.split("/")), "rb")
                except OSError:
                    return None
            sizes = {n: os.path.getsize(os.path.join(stage, *n.split("/"))) for n in u.files}
            detect(u, opener, sizes, fallback)
            if u not in games([u]):
                continue
            system = override or u.system or preview.get(u.main)
            if not system:
                results.append((u, ValueError("RetroShelf can't tell which system this is for")))
                continue
            report(f"Filing {u.main.rsplit('/', 1)[-1]} into roms/{system} …")
            try:
                results.append((u, place(u, stage, roms_root, system, True, cancelled)))
            except (OSError, ValueError) as e:
                if isinstance(e, InterruptedError):
                    raise
                results.append((u, e))
        if not results:
            raise ValueError("there's no game in it")
        if remove and all(not isinstance(r, Exception) for _, r in results):
            for p in row.sources():
                os.unlink(p)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        try:
            os.rmdir(staging_dir(roms_root))
        except OSError:
            pass
    return results


def prune(folder, stop):
    """Remove empty folders from folder up to (not including) stop."""
    folder, stop = os.path.abspath(folder), os.path.abspath(stop)
    while folder != stop and _inside(folder, stop):
        try:
            os.rmdir(folder)
        except OSError:
            return
        folder = os.path.dirname(folder)
