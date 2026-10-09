"""Games the user downloads in their own browser, filed into roms/<system>/ by watching the Downloads folder.

Used by the Homebrew Hub and itch.io windows. A "want" says what to wait for:
    {"id": unique key, "title": shown to the user, "system": ES-DE system,
     "filename": the name the site serves (optional), "stem": the file name to use in roms (optional),
     "any": True to take every ROM for the system (browsing a site freely) instead of one game,
     "item": whatever the caller wants back}
"""
import os, re, shutil, zipfile

from fsutil import is_windows

PARTIAL_EXT = (".part", ".crdownload", ".tmp", ".download", ".opdownload")
# ES-DE system -> ROM extensions RetroShelf files for it (multi-part ones like .p8.png are matched whole)
SYSTEM_EXTS = {
    "gb": (".gb", ".gbc"), "gbc": (".gbc", ".gb", ".cgb"), "gba": (".gba",), "nes": (".nes",),
    "snes": (".sfc", ".smc"), "megadrive": (".md", ".gen", ".smd"), "genesis": (".md", ".gen", ".smd"),
    "mastersystem": (".sms",),
    "gamegear": (".gg",), "pcengine": (".pce",), "atari2600": (".a26",), "pico8": (".p8.png", ".p8"),
    "n64": (".z64", ".n64", ".v64"), "nds": (".nds",), "lynx": (".lnx",), "ngp": (".ngp", ".ngc"),
    "wonderswan": (".ws", ".wsc"), "vectrex": (".vec",), "colecovision": (".col",), "msx": (".rom", ".mx2"),
    "atari5200": (".a52",), "virtualboy": (".vb", ".vboy"), "sega32x": (".32x",), "pokemini": (".min",),
    "intellivision": (".int",),
}
DUP_RE = re.compile(r" ?\(\d+\)(?=\.[^.]+$)")  # browsers save repeats as "game (1).gb"


def downloads_dir():
    """The user's Downloads folder (XDG's on Linux, %USERPROFILE%\\Downloads on Windows)."""
    home = os.path.expanduser("~")
    if not is_windows():
        try:
            with open(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"),
                                   "user-dirs.dirs"), encoding="utf-8") as f:
                m = re.search(r'^XDG_DOWNLOAD_DIR="(.+)"', f.read(), re.M)
            if m:
                return os.path.normpath(os.path.expandvars(m.group(1).replace("$HOME", home)))
        except OSError:
            pass
    return os.path.join(home, "Downloads")


def safe_title(title):
    s = re.sub(r"\s*:\s*", " - ", title.strip()).replace("/", "-").replace("\\", "-")
    s = re.sub(r'[<>"|?*\x00-\x1f]', "", s)
    return re.sub(r"[\s.]+$", "", " ".join(s.split())) or "Homebrew"


def rom_ext(name, exts):
    """The extension of name from exts (longest match, any case), or None."""
    low = name.lower()
    return next((e for e in sorted(exts, key=len, reverse=True) if low.endswith(e)), None)


def homebrew_name(title, ext):
    """File name in roms/<system>: the title, tagged so it's clearly homebrew (No-Intro style)."""
    return f"{safe_title(title)} (Homebrew){ext.lower()}"


def stem_from_download(name, exts):
    """A title from a downloaded file name: 'my_cool-game_v1.2 (1).gb' -> 'my cool-game v1.2'."""
    name = DUP_RE.sub("", name)
    ext = rom_ext(name, exts) or os.path.splitext(name)[1]
    stem = name[:-len(ext)] if ext else name
    return " ".join(stem.replace("_", " ").split()) or "Homebrew"


def find_installed(folder, title):
    """The file filed for this title in folder, if there is one."""
    stem = safe_title(title) + " (Homebrew)"
    try:
        return next((os.path.join(folder, n) for n in sorted(os.listdir(folder)) if n.startswith(stem + ".")), None)
    except OSError:
        return None


def zip_rom(zpath, exts, want=None):
    """(member name, data) of the ROM in a zip: the expected file name if given, else the largest ROM. None if
    the zip holds no ROM for these extensions."""
    with zipfile.ZipFile(zpath) as z:
        roms = [i for i in z.infolist() if not i.is_dir() and rom_ext(i.filename, exts)]
        if want:
            roms = [i for i in roms if os.path.basename(i.filename) == os.path.basename(want)] or roms
        if not roms:
            return None
        best = max(roms, key=lambda i: i.file_size)
        return best.filename, z.read(best)


def file_rom(src, folder, title, exts, want_name=None, keep_source=False):
    """Put a downloaded ROM, or the ROM inside a downloaded zip, into folder as 'Title (Homebrew).ext'. -> path.
    Raises FileExistsError if it's already there and ValueError for a zip without a ROM."""
    os.makedirs(folder, exist_ok=True)
    if src.lower().endswith(".zip") and not (want_name or "").lower().endswith(".zip"):
        found = zip_rom(src, exts, want_name)
        if not found:
            raise ValueError("no ROM inside the zip")
        member, data = found
        dest = os.path.join(folder, homebrew_name(title, rom_ext(member, exts)))
        if os.path.exists(dest):
            raise FileExistsError(f"{os.path.basename(dest)} is already in roms/{os.path.basename(folder)}")
        with open(dest + ".part", "wb") as f:
            f.write(data)
        os.replace(dest + ".part", dest)
        if not keep_source:
            os.unlink(src)
        return dest
    dest = os.path.join(folder, homebrew_name(title, rom_ext(src, exts) or os.path.splitext(src)[1]))
    if os.path.exists(dest):
        raise FileExistsError(f"{os.path.basename(dest)} is already in roms/{os.path.basename(folder)}")
    (shutil.copy2 if keep_source else shutil.move)(src, dest)
    return dest


class DownloadWatcher:
    """Waits for what the user downloads and files it. Call poll() now and then (the windows do it on a timer);
    it returns [(want, path or Exception)] for what it handled.

    A new file counts once its size stops changing. It goes to the waiting game whose site file name it has; else,
    when exactly one waiting game takes that kind of ROM, to that game; else, when one "any ROM" want covers it,
    there. Anything ambiguous or unrelated is left alone, and files already in the folder are never touched."""

    def __init__(self, folder, roms_root):
        self.folder, self.roms_root = folder, roms_root
        self.waiting = []  # wants, oldest first
        self.seen = self._listing()
        self.sizes = {}

    def _listing(self):
        try:
            return {n: os.path.getmtime(os.path.join(self.folder, n)) for n in os.listdir(self.folder)}
        except OSError:
            return {}

    def expect(self, want):
        want.setdefault("exts", SYSTEM_EXTS.get(want["system"], ()))
        if all(w["id"] != want["id"] for w in self.waiting):
            self.waiting.append(want)

    def cancel(self, want_id=None):
        self.waiting = [w for w in self.waiting if want_id and w["id"] != want_id]

    def _takes(self, want, name):
        return name.endswith(".zip") or bool(rom_ext(name, want["exts"]))

    def _match(self, name):
        low = DUP_RE.sub("", name.lower())
        games = [w for w in self.waiting if not w.get("any")]
        named = [w for w in games if w.get("filename") and os.path.basename(w["filename"]).lower() == low]
        if named:
            return named[0]
        fits = [w for w in games if self._takes(w, low)]
        if len(fits) == 1:
            return fits[0]
        if fits:
            return None  # two games could own this file: don't guess
        anys = [w for w in self.waiting if w.get("any") and self._takes(w, low)]
        return anys[0] if len(anys) == 1 else None

    def _could_be_rom(self, low):
        return low.endswith(".zip") or any(rom_ext(low, w["exts"]) for w in self.waiting)

    def poll(self):
        if not self.waiting:
            self.seen = self._listing()
            return []
        done = []
        for name, mtime in self._listing().items():
            low = name.lower()
            if self.seen.get(name) == mtime or low.endswith(PARTIAL_EXT) or name.startswith("."):
                continue
            if not self._could_be_rom(low):
                self.seen[name] = mtime  # not a ROM for anything waiting: ignore it from now on
                continue
            path = os.path.join(self.folder, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if self.sizes.get(name) != size:  # still being written: look again next time
                self.sizes[name] = size
                continue
            want = self._match(name)
            self.seen[name] = mtime
            self.sizes.pop(name, None)
            if not want:
                continue
            title = want.get("stem") or stem_from_download(name, want["exts"])
            folder = os.path.join(self.roms_root, want["system"])
            try:
                done.append((want, file_rom(path, folder, title, want["exts"], want.get("filename"))))
            except (ValueError, zipfile.BadZipFile) as e:  # a zip with no ROM in it, or not a zip at all
                if not want.get("any"):
                    done.append((want, e))
                continue  # browsing freely: it was some other download, leave it be
            except OSError as e:
                done.append((want, e))
            if not want.get("any"):
                self.waiting.remove(want)
        return done
