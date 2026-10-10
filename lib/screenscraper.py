"""Gameplay videos from ScreenScraper (https://www.screenscraper.fr), the community database ES-DE scrapes from.
LaunchBox's free data has no videos, so this fills ES-DE's videos folder: downloaded_media/<system>/videos/<rom>.mp4,
where ES-DE itself plays them and RetroShelf's details panel does too.

ScreenScraper needs two logins:
  - the app's developer ID (devid / devpassword), which ScreenScraper issues to each program. Release builds carry
    RetroShelf's in screenscraper_dev.json (added by the release workflow from repository secrets, so it's never
    in the source); a git checkout can set RETROSHELF_SS_DEVID / RETROSHELF_SS_DEVPASSWORD or enter one in the window;
  - the user's own free ScreenScraper account (ssid / sspassword), which is what their daily allowance is counted on.

Games are found the way ES-DE's scraper finds them (jeuInfos.php): by ROM file name and ScreenScraper system ID, plus
the file's MD5 and size when it's small enough to hash quickly. The system IDs come from ES-DE's own table (MIT)."""
import base64, hashlib, json, os, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEV_FILE = os.path.join(APP_DIR, "screenscraper_dev.json")  # next to retroshelf.py: updates leave it alone
API = "https://api.screenscraper.fr/api2"
SOFTNAME = "RetroShelf"
SIGNUP = "https://www.screenscraper.fr/membreinscription.php"
USER_AGENT = "RetroShelf/1.0 (+https://github.com/votex09/retroshelf)"
HASH_LIMIT = 128 << 20     # MD5 only files up to this size (hashing a 4 GB disc image takes too long)
PAUSE = 1.2                # seconds between lookups: free accounts get one request at a time
VIDEO_TYPES = ("video-normalized", "video")  # the normalized clip is shorter and smaller; else the full one
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".avi", ".mov")

# ES-DE system folder -> ScreenScraper system ID
SYSTEM_IDS = {
    "3do": 29, "adam": 89, "ags": 138, "amiga": 64, "amiga1200": 64, "amiga600": 64, "amigacd32": 130,
    "amstradcpc": 65, "android": 63, "androidapps": 63, "androidgames": 63, "apple2": 86, "apple2gs": 217,
    "arcade": 75, "arcadia": 94, "archimedes": 84, "arduboy": 263, "astrocde": 44, "atari2600": 26, "atari5200": 40,
    "atari7800": 41, "atari800": 43, "atarijaguar": 27, "atarijaguarcd": 171, "atarilynx": 28, "atarist": 42,
    "atarixe": 43, "atomiswave": 75, "bbcmicro": 37, "c64": 66, "cdimono1": 133, "cdtv": 129, "channelf": 80,
    "coco": 144, "colecovision": 48, "consolearcade": 75, "cps": 75, "cps1": 75, "cps2": 75, "cps3": 75,
    "crvision": 241, "daphne": 49, "desktop": 138, "doom": 135, "dos": 135, "dragon32": 91, "dreamcast": 23,
    "easyrpg": 231, "electron": 85, "emulators": 138, "epic": 138, "famicom": 3, "fba": 75, "fbneo": 75, "fds": 106,
    "fm7": 97, "fmtowns": 253, "fpinball": 199, "gamate": 266, "gameandwatch": 52, "gamecom": 121, "gamegear": 21,
    "gb": 9, "gba": 12, "gbc": 10, "gc": 13, "genesis": 1, "gmaster": 103, "gx4000": 87, "intellivision": 115,
    "j2me": 302, "kodi": 138, "laserdisc": 49, "lcdgames": 75, "lowresnx": 244, "lutris": 135, "lutro": 206,
    "macintosh": 146, "mame": 75, "mame-advmame": 75, "mark3": 2, "mastersystem": 2, "megacd": 20, "megacdjp": 20,
    "megadrive": 1, "megadrivejp": 1, "megaduck": 90, "model2": 75, "model3": 75, "moto": 141, "msx": 113,
    "msx1": 113, "msx2": 116, "msxturbor": 118, "multivision": 109, "n3ds": 17, "n64": 14, "n64dd": 14, "naomi": 75,
    "naomi2": 75, "naomigd": 75, "nds": 15, "neogeo": 142, "neogeocd": 70, "neogeocdjp": 70, "nes": 3, "ngage": 30,
    "ngp": 25, "ngpc": 82, "odyssey2": 104, "openbor": 214, "oric": 131, "palm": 219, "pc": 135, "pc88": 221,
    "pc98": 208, "pcarcade": 75, "pcengine": 31, "pcenginecd": 114, "pcfx": 72, "pico8": 234, "plus4": 99,
    "pokemini": 211, "ports": 135, "ps2": 58, "ps3": 59, "ps4": 60, "psp": 61, "psvita": 62, "psx": 57, "pv1000": 74,
    "quake": 135, "samcoupe": 213, "satellaview": 107, "saturn": 22, "saturnjp": 22, "scummvm": 123, "scv": 67,
    "sega32x": 19, "sega32xjp": 19, "sega32xna": 19, "segacd": 20, "sfc": 4, "sg-1000": 109, "sgb": 127, "snes": 4,
    "snesna": 4, "solarus": 223, "spectravideo": 218, "steam": 138, "stv": 75, "sufami": 108, "supergrafx": 105,
    "supervision": 207, "supracan": 100, "switch": 225, "symbian": 30, "tanodragon": 91, "tg-cd": 114, "tg16": 31,
    "ti99": 205, "tic80": 222, "to8": 141, "triforce": 75, "trs-80": 144, "type-x": 75, "uzebox": 216, "vectrex": 102,
    "vic20": 73, "videopac": 104, "vircon32": 272, "virtualboy": 11, "vpinball": 198, "vsmile": 120, "wasm4": 262,
    "wii": 16, "wiiu": 18, "windows": 138, "windows3x": 136, "windows9x": 138, "wonderswan": 45,
    "wonderswancolor": 46, "x1": 220, "x68000": 79, "xbox": 32, "xbox360": 33, "xboxone": 34, "zmachine": 215,
    "zx81": 77, "zxspectrum": 76,
}


class SSError(Exception):
    """ScreenScraper said no: the message is fit to show."""


class StopScraping(SSError):
    """Nothing more will work this session: bad login, no developer ID, daily allowance used up, API closed."""


def dev_credentials(cfg=None):
    """(devid, devpassword) or None: config.json, then the environment, then the release build's file."""
    cfg = cfg or {}
    if cfg.get("ss_devid") and cfg.get("ss_devpassword"):
        return cfg["ss_devid"], cfg["ss_devpassword"]
    env = os.environ.get("RETROSHELF_SS_DEVID"), os.environ.get("RETROSHELF_SS_DEVPASSWORD")
    if all(env):
        return env
    try:
        with open(DEV_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return _unscramble(data["id"]), _unscramble(data["password"])
    except (OSError, ValueError, KeyError):
        return None


def scramble(text):
    """Not secret (it ships with every copy), just not readable at a glance; release.sh writes it this way."""
    return base64.b64encode(bytes(b ^ 0x5A for b in text.encode())).decode()


def _unscramble(text):
    return bytes(b ^ 0x5A for b in base64.b64decode(text)).decode()


def md5_of(path, limit=HASH_LIMIT, cancelled=lambda: False):
    if os.path.getsize(path) > limit:
        return None
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            if cancelled():
                raise InterruptedError("cancelled")
            h.update(chunk)
    return h.hexdigest()


def lookup_url(path, system, dev, user=None, password=None, md5=None):
    q = {"devid": dev[0], "devpassword": dev[1], "softname": SOFTNAME, "output": "xml", "romtype": "rom",
         "romnom": os.path.basename(path), "romtaille": str(os.path.getsize(path))}
    if system in SYSTEM_IDS:
        q["systemeid"] = str(SYSTEM_IDS[system])
    if md5:
        q["md5"] = md5
    if user and password:
        q["ssid"], q["sspassword"] = user, password
    return f"{API}/jeuInfos.php?" + urllib.parse.urlencode(q)


def _fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300].strip()
        return f"HTTP {e.code}: {body}"


CODES = {  # ScreenScraper's HTTP status codes
    401: "ScreenScraper's API is closed to apps without members for now (its servers are busy). Try later.",
    403: "ScreenScraper didn't accept the login: check your username and password.",
    423: "ScreenScraper's API is closed for now. Try again later.",
    426: "ScreenScraper doesn't accept this version of RetroShelf any more: update it (Help → Check for updates).",
    430: "Your ScreenScraper allowance for today is used up. It resets every day; signing in raises it.",
    431: "ScreenScraper has had too many lookups for games it doesn't know today. Try again tomorrow.",
}


def _say(text):
    """ScreenScraper's plain-text answers -> None (game not found), or an error to show."""
    code = int(text[5:8]) if text.startswith("HTTP ") and text[5:8].isdigit() else None
    low = text.lower()
    if code == 404 or "erreur : rom" in low or "non trouv" in low:
        return None  # not in the database: not an error
    if "veloppeur" in low:  # "Erreur de login : Vérifier vos identifiants développeur !" (HTTP 403)
        raise StopScraping("ScreenScraper doesn't accept this copy's developer ID.")
    if code in CODES:
        raise StopScraping(CODES[code])
    if code == 429 or "trop de" in low:
        raise SSError("too many requests at once")
    if "identifiant" in low or "login" in low:
        raise StopScraping(CODES[403])
    if "quota" in low:
        raise StopScraping(CODES[430])
    raise SSError(text[:200])


def parse(text):
    """jeuInfos.php's answer -> {id, name, video: (url, ext) or None, user: {...}} or None when not found."""
    stripped = text.lstrip()
    if not stripped.startswith("<"):
        return _say(stripped)
    try:
        root = ET.fromstring(stripped)
    except ET.ParseError:
        raise SSError("ScreenScraper sent something unreadable")
    user = root.find("ssuser")
    info = {}
    if user is not None:
        info = {k: (user.findtext(k) or "") for k in ("id", "niveau", "requeststoday", "maxrequestsperday",
                                                      "requestskotoday", "maxrequestskoperday")}
        if info.get("niveau") == "0" and info.get("id"):
            raise StopScraping("ScreenScraper didn't accept your username and password.")
    game = root.find("jeu")
    if game is None:
        game = root.find("jeux/jeu")
    if game is None:
        return None
    names = {n.get("region"): (n.text or "").strip() for n in game.findall("noms/nom")}
    name = next((names[r] for r in ("wor", "us", "ss", "eu", "jp") if names.get(r)), next(iter(names.values()), ""))
    if name.upper().startswith("ZZZ(NOTGAME)"):
        return None
    video = None
    for kind in VIDEO_TYPES:
        m = game.find(f"medias/media[@type='{kind}']")
        if m is not None and (m.text or "").strip():
            video = (m.text.strip().replace(" ", "%20"), "." + (m.get("format") or "mp4").lower().lstrip("."))
            break
    return {"id": game.get("id"), "name": name, "video": video, "user": info}


def videos_dir(media_root, system):
    return os.path.join(media_root, system, "videos")


def has_video(folder, stem):
    try:
        return any(os.path.splitext(f)[0] == stem and f.lower().endswith(VIDEO_EXTS) for f in os.listdir(folder))
    except OSError:
        return False


def download(url, dest, cancelled=lambda: False, fetch_timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest + ".part"
    try:
        try:
            r = urllib.request.urlopen(req, timeout=fetch_timeout)
        except urllib.error.HTTPError as e:
            _say(f"HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace')}")
            return None  # 404: no such video after all
        with r:
            kind = r.headers.get("Content-Type", "")
            first = r.read(1 << 16)
            if "text" in kind or "xml" in kind or first[:1] in (b"<", b"E", b"N"):  # an error / "NOMEDIA", no video
                text = first.decode("utf-8", "replace")
                if text.strip().upper().startswith("NOMEDIA"):
                    return None
                _say(text)
            with open(tmp, "wb") as f:
                f.write(first)
                while True:
                    if cancelled():
                        raise InterruptedError("cancelled")
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
        os.replace(tmp, dest)
        return dest
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run(jobs, system, media_root, dev, user=None, password=None, progress=lambda text, done, total: None,
        cancelled=lambda: False, fetch=_fetch, pause=PAUSE):
    """jobs: [(rom file, stem the media is named after)]. Downloads each game's clip unless it already has one.
    -> stats {videos, had, no_video, not_found, failed, stopped (message or "")}."""
    folder = videos_dir(media_root, system)
    stats = {"videos": 0, "had": 0, "no_video": 0, "not_found": 0, "failed": 0, "stopped": "", "allowance": ""}
    total = len(jobs)
    asked = False
    for i, (path, stem) in enumerate(jobs):
        if cancelled():
            break
        if has_video(folder, stem):
            stats["had"] += 1
            continue
        progress(f"Looking up {os.path.basename(path)} …", i, total)
        if asked and pause:
            time.sleep(pause)
        asked = True
        try:
            url = lookup_url(path, system, dev, user, password, md5_of(path, cancelled=cancelled))
            try:
                game = parse(fetch(url))
            except StopScraping:
                raise
            except SSError as e:
                if "too many" not in str(e):
                    raise
                time.sleep(pause * 5)  # one request at a time for free accounts: wait, then once more
                game = parse(fetch(url))
            if game and game["user"].get("maxrequestsperday"):
                stats["allowance"] = f"{game['user']['requeststoday']} / {game['user']['maxrequestsperday']} today"
            if not game:
                stats["not_found"] += 1
                continue
            if not game["video"]:
                stats["no_video"] += 1
                continue
            url, ext = game["video"]
            os.makedirs(folder, exist_ok=True)
            progress(f"Downloading the video for {game['name'] or stem} …", i, total)
            if download(url, os.path.join(folder, stem + ext), cancelled):
                stats["videos"] += 1
            else:
                stats["no_video"] += 1
        except StopScraping as e:
            stats["stopped"] = str(e)
            break
        except InterruptedError:
            break
        except (SSError, OSError, urllib.error.URLError) as e:
            stats["failed"] += 1
            stats["last_error"] = str(e)
    progress("Done", total, total)
    return stats
