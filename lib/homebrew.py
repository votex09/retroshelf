"""Homebrew Hub (https://hh.gbdev.io): free Game Boy / Game Boy Color / Game Boy Advance / NES homebrew.

The catalogue comes from Homebrew Hub's public API and is cached in cache/homebrew/. Homebrew Hub lets authors
choose which apps may download their games into a user's library, so RetroShelf only downloads directly when an
entry is open source (an open licence or the "Open Source" tag) or names RetroShelf in "third-party". For every
other entry, "Open on Homebrew Hub" opens the game's page in the user's browser, the user downloads it there, and
DownloadWatcher picks the file up from the Downloads folder and files it into the right roms/<system> folder.
"""
import json, os, re, shutil, tempfile, time, urllib.parse, urllib.request, zipfile

from fsutil import is_windows, write_json

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(APP_DIR, "cache", "homebrew")
API = "https://hh3.gbdev.io"
SITE = "https://hh.gbdev.io"
USER_AGENT = "RetroShelf/1.0"
CLIENT = "retroshelf"  # the name an entry's "third-party" list would use to allow RetroShelf downloads

# Homebrew Hub platform -> ES-DE system, and the ROM extensions that system takes
PLATFORMS = {"GB": "gb", "GBC": "gbc", "GBA": "gba", "NES": "nes"}
PLATFORM_NAMES = {"GB": "Game Boy", "GBC": "Game Boy Color", "GBA": "Game Boy Advance", "NES": "NES"}
ROM_EXTS = {"GB": (".gb", ".gbc"), "GBC": (".gbc", ".gb", ".cgb"), "GBA": (".gba",), "NES": (".nes",)}
TYPES = ["game", "demo", "tool", "music", "hackrom"]
PARTIAL_EXT = (".part", ".crdownload", ".tmp", ".download", ".opdownload")
# licence families whose terms let the game be passed on (any version; "-only" / "-or-later" variants included)
OPEN_LICENSE_RE = re.compile(
    r"(?:MIT(?:-0)?|0?BSD(?:-[234]-CLAUSE)?|ISC|ZLIB|UNLICENSE|WTFPL|CC0|APACHE|MPL|(?:A|L)?GPL"
    r"|CC-BY(?:-NC)?(?:-SA|-ND)?)(?:-?V?[\d.]+)?(?:-ONLY|-OR-LATER|\+)?")
CACHE_DAYS = 7


# ---------- catalogue ----------
def _get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def cache_path(platform):
    return os.path.join(CACHE, f"{platform}.json")


def cached_age(platform):
    """Days since the platform's list was downloaded, or None."""
    try:
        with open(cache_path(platform), encoding="utf-8") as f:
            return (time.time() - json.load(f)["time"]) / 86400
    except (OSError, ValueError, KeyError):
        return None


def load_catalog(platform, refresh=False):
    """-> [entry] for a Homebrew Hub platform, from the cache unless it's missing, old or refresh is set."""
    path = cache_path(platform)
    if not refresh:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if time.time() - data["time"] < CACHE_DAYS * 86400:
                return data["entries"]
        except (OSError, ValueError, KeyError):
            pass
    query = urllib.parse.urlencode({"platform": platform, "results": 10000})
    entries = _get_json(f"{API}/api/search?{query}").get("entries") or []
    entries = [dict(e, platform=e.get("platform") or platform) for e in entries if e.get("slug")]
    entries = [e for e in entries if e["platform"] == platform]  # entries without one belong to the list asked for
    os.makedirs(CACHE, exist_ok=True)
    write_json(path, {"time": time.time(), "entries": entries}, ensure_ascii=False)
    return entries


def load_entry(slug):
    """The full manifest of one entry (files, screenshots, licenses …)."""
    return _get_json(f"{API}/api/entry/{urllib.parse.quote(slug)}.json")


# ---------- entry helpers ----------
def developer_text(dev):
    """Developer field: a string, an author object ({"name": …}), or a list of either."""
    if not dev:
        return ""
    items = dev if isinstance(dev, list) else [dev]
    return ", ".join(d.get("name", "") if isinstance(d, dict) else str(d) for d in items if d)


def game_license(entry):
    """The game's license as a string ("" if none). The API calls it "license"; the database schema "gameLicense"."""
    lic = entry.get("license") or entry.get("gameLicense")
    if isinstance(lic, dict):
        lic = lic.get("spdx") or lic.get("id") or lic.get("name")
    return str(lic).strip() if lic else ""


def license_text(entry):
    return game_license(entry) or ("Open source" if "Open Source" in (entry.get("tags") or []) else "")


def downloads_disabled(entry):
    return bool((entry.get("use-requirements") or {}).get("disable-downloads"))


def can_download(entry):
    """True when RetroShelf may download this entry itself: the author allows downloads, and the game is open
    source or names RetroShelf among the apps allowed to fetch it. Everything else goes through the website."""
    if downloads_disabled(entry):
        return False
    return (open_license(game_license(entry)) or "Open Source" in (entry.get("tags") or [])
            or CLIENT in (entry.get("third-party") or []))


def open_license(text):
    """True when every licence named is an open one: "MIT", "GPL-3.0", "CC-BY-SA 4.0", "MIT / CC-BY-4.0 (Assets)".
    Anything vague ("CC-BY ish", "free to share") or unknown is False, so it goes through the website instead."""
    text = re.sub(r"\([^)]*\)", "", text.upper())  # "(Assets)", "(code)"
    parts = [p.strip().replace(" ", "-") for p in re.split(r"/|,|;|\bAND\b|&", text)]
    parts = [p for p in parts if p]
    return bool(parts) and all(OPEN_LICENSE_RE.fullmatch(p) for p in parts)


def rom_file(entry):
    """The file to install: the playable one marked default, else the first playable, else the first (the same
    choice Homebrew Hub's own player makes). None if the manifest lists no files."""
    files = entry.get("files") or []
    playable = [f for f in files if f.get("playable")] or files
    return next((f for f in playable if f.get("default")), playable[0] if playable else None)


def file_url(entry, filename):
    return f"{API}/static/{entry.get('basepath') or 'database'}/entries/{entry['slug']}/{urllib.parse.quote(filename)}"


def screenshot_url(entry):
    shots = entry.get("screenshots") or []
    return file_url(entry, shots[0]) if shots else None


def page_url(entry):
    return f"{SITE}/game/{urllib.parse.quote(entry['slug'])}"


def safe_title(title):
    s = re.sub(r"\s*:\s*", " - ", title.strip()).replace("/", "-").replace("\\", "-")
    s = re.sub(r'[<>"|?*\x00-\x1f]', "", s)
    return re.sub(r"[\s.]+$", "", " ".join(s.split())) or "Homebrew"


def rom_name(entry, ext):
    """File name in roms/<system>: the Homebrew Hub title, tagged so it's clearly homebrew (No-Intro style)."""
    return f"{safe_title(entry.get('title') or entry['slug'])} (Homebrew){ext.lower()}"


def installed_path(entry, roms_root):
    """The ROM RetroShelf filed for this entry, if it's still there."""
    folder = os.path.join(roms_root, PLATFORMS[entry_platform(entry)])
    stem = os.path.splitext(rom_name(entry, ".x"))[0]
    try:
        for n in os.listdir(folder):
            if os.path.splitext(n)[0] == stem:
                return os.path.join(folder, n)
    except OSError:
        pass
    return None


def entry_platform(entry, default="GB"):
    p = entry.get("platform")
    return p if p in PLATFORMS else default


# ---------- filing a ROM ----------
def _pick_from_zip(zpath, platform, want=None):
    """(member name, data) of the ROM inside a zip: the expected file name if given, else the only/largest ROM."""
    with zipfile.ZipFile(zpath) as z:
        roms = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith(ROM_EXTS[platform])]
        if want:
            named = [i for i in roms if os.path.basename(i.filename) == os.path.basename(want)]
            roms = named or roms
        if not roms:
            raise ValueError("no ROM inside the zip")
        best = max(roms, key=lambda i: i.file_size)
        return best.filename, z.read(best)


def file_rom(src, entry, roms_root, keep_source=False):
    """Put a downloaded ROM (or a zip holding one) into roms/<system>/ under the entry's name. -> path."""
    platform = entry_platform(entry)
    folder = os.path.join(roms_root, PLATFORMS[platform])
    os.makedirs(folder, exist_ok=True)
    want = (rom_file(entry) or {}).get("filename")
    if src.lower().endswith(".zip") and not (want or "").lower().endswith(".zip"):
        member, data = _pick_from_zip(src, platform, want)
        ext = os.path.splitext(member)[1]
        dest = os.path.join(folder, rom_name(entry, ext))
        if os.path.exists(dest):
            raise FileExistsError(f"{os.path.basename(dest)} is already in roms/{PLATFORMS[platform]}")
        with open(dest + ".part", "wb") as f:
            f.write(data)
        os.replace(dest + ".part", dest)
        if not keep_source:
            os.unlink(src)
        return dest
    ext = os.path.splitext(src)[1]
    dest = os.path.join(folder, rom_name(entry, ext))
    if os.path.exists(dest):
        raise FileExistsError(f"{os.path.basename(dest)} is already in roms/{PLATFORMS[platform]}")
    (shutil.copy2 if keep_source else shutil.move)(src, dest)
    return dest


def install(entry, roms_root, progress=lambda done, total: None):
    """Download an entry RetroShelf may fetch itself (can_download) and file it. -> path."""
    if not can_download(entry):
        raise PermissionError("this game's author hasn't allowed apps to download it; use Open on Homebrew Hub")
    f = rom_file(entry)
    if not f:
        raise ValueError("Homebrew Hub lists no file for this entry")
    tmpdir = tempfile.mkdtemp(prefix="retroshelf-hh-")
    try:
        tmp = os.path.join(tmpdir, os.path.basename(f["filename"]))
        req = urllib.request.Request(file_url(entry, f["filename"]), headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as out:
            total, done = int(r.headers.get("Content-Length") or 0), 0
            while chunk := r.read(1 << 16):
                out.write(chunk)
                done += len(chunk)
                progress(done, total)
        return file_rom(tmp, entry, roms_root)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def es_de_fields(entry):
    """gamelist.xml fields from a Homebrew Hub entry."""
    date = str(entry.get("date") or "")
    m = re.match(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", date)
    release = f"{m.group(1)}{int(m.group(2) or 1):02}{int(m.group(3) or 1):02}T000000" if m else ""
    return {"name": entry.get("title") or "", "desc": (entry.get("description") or "").strip(),
            "developer": developer_text(entry.get("developer")), "publisher": "Homebrew",
            "releasedate": release, "genre": (entry.get("typetag") or "").capitalize()}


# ---------- watching the Downloads folder ----------
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


class DownloadWatcher:
    """Waits for ROMs the user downloads from Homebrew Hub pages and files them. Call poll() now and then (the
    window does it on a timer); it returns [(entry, path or Exception)] for what it handled.

    A new file counts once its size stops changing. It's matched to a waiting entry by the file name Homebrew Hub
    serves (from the entry's manifest), or, when that name is generic or unknown, by extension to the single entry
    waiting for that kind of ROM."""

    def __init__(self, folder, roms_root):
        self.folder, self.roms_root = folder, roms_root
        self.waiting = []  # entries, oldest first
        self.seen = self._listing()
        self.sizes = {}

    def _listing(self):
        try:
            return {n: os.path.getmtime(os.path.join(self.folder, n)) for n in os.listdir(self.folder)}
        except OSError:
            return {}

    def expect(self, entry):
        if all(e["slug"] != entry["slug"] for e in self.waiting):
            self.waiting.append(entry)

    def cancel(self, slug=None):
        self.waiting = [e for e in self.waiting if slug and e["slug"] != slug]

    def _match(self, name):
        low = re.sub(r" ?\(\d+\)(?=\.[^.]+$)", "", name.lower())  # browsers save repeats as "game (1).gb"
        for e in self.waiting:
            f = rom_file(e)
            if f and os.path.basename(f["filename"]).lower() == low:
                return e
        exts = [e for e in self.waiting
                if low.endswith(".zip") or low.endswith(ROM_EXTS[entry_platform(e)])]
        return exts[0] if len(exts) == 1 else None

    def poll(self):
        if not self.waiting:
            self.seen = self._listing()
            return []
        now, done = self._listing(), []
        for name, mtime in now.items():
            if self.seen.get(name) == mtime or name.lower().endswith(PARTIAL_EXT) or name.startswith("."):
                continue
            low = name.lower()
            if not (low.endswith(".zip") or any(low.endswith(ROM_EXTS[p]) for p in ROM_EXTS)):
                self.seen[name] = mtime  # not a ROM: ignore it from now on
                continue
            path = os.path.join(self.folder, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if self.sizes.get(name) != size:  # still being written: look again next time
                self.sizes[name] = size
                continue
            entry = self._match(name)
            self.seen[name] = mtime
            self.sizes.pop(name, None)
            if not entry:
                continue
            try:
                done.append((entry, file_rom(path, entry, self.roms_root)))
            except (OSError, ValueError, zipfile.BadZipFile) as e:
                done.append((entry, e))
            self.waiting.remove(entry)
        return done
