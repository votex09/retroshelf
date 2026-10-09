"""PDRoms (https://pdroms.de): homebrew for old consoles and handhelds, free to download since 1998.

PDRoms only lists software that is "freeware, donationware, open-source, public-domain, or has been legally cleared
for free distribution by the respective copyright owners" (its masthead). Fan games made without the original
owner's permission are marked "copyright-restricted" there and hidden unless asked for; RetroShelf never asks for them.

Its download buttons are one-time links made for each page view, and every download is counted, so nothing is
downloaded behind the user's back: "Open on PDRoms" shows the game's page in the browser and lib/downloads.py files
what lands in the Downloads folder, as with itch.io. The list itself comes from PDRoms' per-system games pages
(robots.txt allows /files/ and /system/ is where they live), read slowly and cached for a week.
"""
import html, json, math, os, re, time, urllib.error, urllib.request

import downloads
from fsutil import write_json

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(APP_DIR, "cache", "pdroms")
SITE = "https://pdroms.de"
USER_AGENT = "RetroShelf/1.0 (+https://github.com/votex09/retroshelf)"
CACHE_DAYS = 7
PER_PAGE = 10
MAX_PAGES = 120
PAUSE = 0.3  # seconds between pages: be gentle with a one-person site

# ES-DE system, label, PDRoms platform (systems whose PDRoms files hold games; its Game Gear, Atari 7800, Vectrex,
# MSX, PICO-8 and TIC-80 sections are news only)
SYSTEMS = [
    ("gb", "Game Boy / Color", "nintendo-game-boy-gb-gbc"),
    ("gba", "Game Boy Advance", "nintendo-game-boy-advance-gba"),
    ("nes", "NES", "nintendo-entertainment-system-nes-famicom"),
    ("snes", "SNES", "super-nintendo-snes-super-famicom"),
    ("n64", "Nintendo 64", "nintendo-64-n64"),
    ("nds", "Nintendo DS", "nintendo-ds"),
    ("virtualboy", "Virtual Boy", "nintendo-virtual-boy"),
    ("pokemini", "Pokémon Mini", "pokemon-mini"),
    ("megadrive", "Mega Drive / Genesis", "sega-genesis-megadrive"),
    ("mastersystem", "Master System", "sega-master-system-sms"),
    ("sega32x", "Sega 32X", "sega-32x"),
    ("pcengine", "PC Engine", "nec-turbografx-16-pc-engine"),
    ("atari2600", "Atari 2600", "atari-2600"),
    ("atari5200", "Atari 5200", "atari-5200"),
    ("lynx", "Atari Lynx", "atari-lynx"),
    ("colecovision", "ColecoVision", "colecovision"),
    ("intellivision", "Intellivision", "mattel-intellivision"),
    ("ngp", "Neo Geo Pocket", "snk-neo-geo-pocket-ngp-ngpc"),
    ("wonderswan", "WonderSwan", "bandai-wonderswan-ws-wsc"),
]
LABELS = {s: label for s, label, _ in SYSTEMS}
PLATFORMS = {s: p for s, _, p in SYSTEMS}

ARTICLE_RE = re.compile(r'<article class="file_post">(.*?)</article>', re.S)
LINK_RE = re.compile(r'<a href="(https://pdroms\.de/files/[^"]+)" title="([^"]*)"')
COUNT_RE = re.compile(r'class="entry-count">\((\d+)\)')
ADDED_RE = re.compile(r"Added \w+ \d+, (\d{4})")
IMG_RE = re.compile(r'<img [^>]*src="([^"]+)"')
TAG_SUFFIX_RE = re.compile(r"\s*\((?:[^()]*\s)?(?:Game|Demo)\)\s*$")


# ---------- the list ----------
def games_url(system, page=1):
    base = f"{SITE}/system/{PLATFORMS[system]}/games/"
    return base if page == 1 else f"{base}page/{page}/"


def browse_url(system):
    return games_url(system)


def _fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _text(fragment):
    """HTML -> text: the source's own line breaks are spaces, <br> and paragraph ends are new lines."""
    s = re.sub(r"\s+", " ", fragment or "")
    s = re.sub(r"<br\s*/?>|</p>", "\n", s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return "\n".join(line for line in (" ".join(x.split()) for x in s.splitlines()) if line)


def clean_title(title):
    """'Robo-Ninja Climb (NES Game)' -> 'Robo-Ninja Climb'."""
    t = html.unescape(title).strip()
    return TAG_SUFFIX_RE.sub("", t) or t


def parse_page(text):
    """A games page -> ([game], total games on the site for this system or None)."""
    games = []
    for art in ARTICLE_RE.findall(text):
        m = LINK_RE.search(art)
        if not m:
            continue
        year = ADDED_RE.search(art)  # when PDRoms listed it, not when it came out
        img = IMG_RE.search(art)
        games.append({"url": m.group(1), "title": clean_title(m.group(2)), "added": year.group(1) if year else "",
                      "thumb": html.unescape(img.group(1)) if img else ""})
    count = COUNT_RE.search(text)
    return games, int(count.group(1)) if count else None


def cache_path(system):
    return os.path.join(CACHE, f"{system}.json")


def cached_age(system):
    try:
        with open(cache_path(system), encoding="utf-8") as f:
            return (time.time() - json.load(f)["time"]) / 86400
    except (OSError, ValueError, KeyError):
        return None


def load_catalog(system, refresh=False, pause=PAUSE):
    """-> [game] for an ES-DE system, from the cache unless it's missing, old or refresh is set."""
    path = cache_path(system)
    if not refresh:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if time.time() - data["time"] < CACHE_DAYS * 86400:
                return data["games"]
        except (OSError, ValueError, KeyError):
            pass
    games, pages, page = {}, 1, 1
    while page <= min(pages, MAX_PAGES):
        if page > 1:
            time.sleep(pause)
        try:
            found, total = parse_page(_fetch(games_url(system, page)))
        except urllib.error.HTTPError as e:
            if e.code == 404 and page > 1:
                break  # past the last page
            raise
        if page == 1 and total:
            pages = math.ceil(total / PER_PAGE)
        if not found:
            break
        for g in found:
            games.setdefault(g["url"], dict(g, system=system))
        page += 1
    out = sorted(games.values(), key=lambda g: g["title"].lower())
    os.makedirs(CACHE, exist_ok=True)
    write_json(path, {"time": time.time(), "games": out}, ensure_ascii=False)
    return out


# ---------- one game ----------
def parse_file_page(text):
    """A file's page -> {author, version, description, image} (whatever it has)."""
    out = {}
    for key, label in (("author", "Author"), ("version", "Version")):
        m = re.search(rf"<dt>{label}</dt>\s*<dd>(.*?)</dd>", text, re.S)
        if m:
            out[key] = _text(m.group(1))
    body = re.search(r'<div class="file-card-body">(.*?)</div><!--file-card-body-->', text, re.S)
    if body:
        img = re.search(r'class="file_thumb_single"><img [^>]*src="([^"]+)"', body.group(1))
        if img:
            out["image"] = html.unescape(img.group(1))
        out["description"] = _text(re.sub(r'<div class="file_thumb_single">.*?</div>', "", body.group(1),
                                          flags=re.S))
    return out


def load_details(game):
    return parse_file_page(_fetch(game["url"]))


def installed_path(game, roms_root):
    return downloads.find_installed(os.path.join(roms_root, game["system"]), game["title"])


def want(game):
    return {"id": game["url"], "title": game["title"], "system": game["system"], "stem": game["title"],
            "item": game}


def browse_want(system):
    return {"id": f"any:{system}", "title": f"any {LABELS[system]} ROM", "system": system, "any": True}


def es_de_fields(game):
    return {"name": game["title"], "desc": game.get("description") or "", "developer": game.get("author") or "",
            "publisher": "Homebrew (PDRoms)"}
