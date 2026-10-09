"""Homebrew Hub (https://hh.gbdev.io): free Game Boy / Game Boy Color / Game Boy Advance / NES homebrew.

The catalogue comes from Homebrew Hub's public API and is cached in cache/homebrew/. Homebrew Hub lets authors
choose which apps may download their games into a user's library, so RetroShelf only downloads directly when an
entry is open source (an open licence or the "Open Source" tag) or names RetroShelf in "third-party". For every
other entry, "Open on Homebrew Hub" opens the game's page in the user's browser, the user downloads it there, and
lib/downloads.py picks the file up from the Downloads folder and files it into the right roms/<system> folder.
"""
import json, os, re, shutil, tempfile, time, urllib.parse, urllib.request

import downloads
from fsutil import write_json

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


def entry_title(entry):
    return entry.get("title") or entry["slug"]


def rom_name(entry, ext):
    return downloads.homebrew_name(entry_title(entry), ext)


def installed_path(entry, roms_root):
    """The ROM RetroShelf filed for this entry, if it's still there."""
    return downloads.find_installed(os.path.join(roms_root, PLATFORMS[entry_platform(entry)]), entry_title(entry))


def entry_platform(entry, default="GB"):
    p = entry.get("platform")
    return p if p in PLATFORMS else default


# ---------- filing a ROM ----------
def want(entry):
    """What the Downloads watcher waits for when the user downloads this entry from its page."""
    platform = entry_platform(entry)
    return {"id": entry["slug"], "title": entry_title(entry), "system": PLATFORMS[platform],
            "exts": ROM_EXTS[platform], "filename": (rom_file(entry) or {}).get("filename"),
            "stem": entry_title(entry), "item": entry}


def file_rom(src, entry, roms_root, keep_source=False):
    """Put a downloaded ROM (or a zip holding one) into roms/<system>/ under the entry's name. -> path."""
    w = want(entry)
    return downloads.file_rom(src, os.path.join(roms_root, w["system"]), w["stem"], w["exts"], w["filename"],
                              keep_source)


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
