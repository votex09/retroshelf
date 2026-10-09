"""itch.io homebrew: free games tagged for retro consoles, from itch.io's official RSS feeds of its browse pages.

itch.io has no public API for other people's games, so everything is downloaded the normal way: "Open on itch.io"
shows the game's page in the user's browser (where the author can ask for a donation), the user downloads it there,
and lib/downloads.py files the ROM from the Downloads folder. "Browse on itch.io" does the same for the whole browse
page: any ROM for the chosen system that the user downloads is filed.

The feeds are browse pages with ".xml" added (https://itch.io/docs/api/overview#rss-feeds). itch.io's Cloudflare
protection sometimes turns feed readers away; then the list stays empty and browsing in the browser still works.
"""
import html, json, os, re, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import downloads
from fsutil import write_json

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(APP_DIR, "cache", "itch")
BROWSE = "https://itch.io/games/price-free"
USER_AGENT = "RetroShelf/1.0 (+https://github.com/votex09/retroshelf)"
PAGES = 3  # feed pages per browse page (about 30 games each)
CACHE_DAYS = 1

# ES-DE system, label, itch.io browse filters (tags, or the engine a game was made with)
SYSTEMS = [
    ("gb", "Game Boy", ["tag-game-boy", "made-with-gb-studio"]),
    ("gbc", "Game Boy Color", ["tag-game-boy-color"]),
    ("gba", "Game Boy Advance", ["tag-game-boy-advance", "tag-gba"]),
    ("nes", "NES", ["tag-nes", "made-with-nesmaker"]),
    ("snes", "SNES", ["tag-snes"]),
    ("megadrive", "Mega Drive / Genesis", ["tag-sega-genesis", "tag-mega-drive"]),
    ("mastersystem", "Master System", ["tag-sega-master-system"]),
    ("pcengine", "PC Engine", ["tag-pc-engine"]),
    ("atari2600", "Atari 2600", ["tag-atari-2600"]),
    ("pico8", "PICO-8", ["made-with-pico-8"]),
]
LABELS = {s: label for s, label, _ in SYSTEMS}
FILTERS = {s: f for s, _, f in SYSTEMS}


class Blocked(Exception):
    """itch.io refused the feed (Cloudflare's bot protection answers 403)."""


# ---------- feeds ----------
def feed_url(path, page=1):
    return f"{BROWSE}/{path}.xml" + (f"?page={page}" if page > 1 else "")


def browse_url(system):
    return f"{BROWSE}/{FILTERS[system][0]}"


def _fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _text(html_text):
    s = re.sub(r"<br\s*/?>|</p>", "\n", html_text or "", flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def parse_feed(data):
    """RSS -> [game]. Field names vary a little between itch.io's feeds, so this reads what's there."""
    root = ET.fromstring(data)
    games = []
    for item in root.iter("item"):
        f = {child.tag.split("}")[-1].lower(): (child.text or "").strip() for child in item}
        link = f.get("link") or f.get("guid") or ""
        if not link.startswith("http"):
            continue
        desc_html = f.get("description", "")
        img = f.get("imageurl") or next(iter(re.findall(r'<img[^>]+src="([^"]+)"', desc_html)), "")
        host = urllib.parse.urlsplit(link).hostname or ""
        author = host[:-len(".itch.io")] if host.endswith(".itch.io") else ""
        date = f.get("createdate") or f.get("pubdate") or ""
        try:
            year = str(parsedate_to_datetime(date).year)
        except (TypeError, ValueError, IndexError):
            year = (re.search(r"(19|20)\d\d", date) or [""])[0]
        price = f.get("price") or ""
        games.append({
            "url": link, "title": html.unescape(f.get("plaintitle") or f.get("title") or link),
            "author": author, "image": html.unescape(img), "description": _text(desc_html),
            "year": year, "price": price,
        })
    return games


def is_free(game):
    p = (game.get("price") or "").strip().lower()
    return p in ("", "free", "0", "0.00", "$0.00") or re.fullmatch(r"[^\d]*0+(?:[.,]0+)?[^\d]*", p) is not None


def cache_path(system):
    return os.path.join(CACHE, f"{system}.json")


def cached_age(system):
    try:
        with open(cache_path(system), encoding="utf-8") as f:
            return (time.time() - json.load(f)["time"]) / 86400
    except (OSError, ValueError, KeyError):
        return None


def load_catalog(system, refresh=False, pages=PAGES):
    """-> [game] for an ES-DE system, from the cache unless it's missing, old or refresh is set.
    Raises Blocked when itch.io turned every request away."""
    path = cache_path(system)
    if not refresh:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if time.time() - data["time"] < CACHE_DAYS * 86400:
                return data["games"]
        except (OSError, ValueError, KeyError):
            pass
    games, blocked, errors = {}, 0, []
    for flt in FILTERS[system]:
        for page in range(1, pages + 1):
            try:
                found = parse_feed(_fetch(feed_url(flt, page)))
            except urllib.error.HTTPError as e:
                blocked += e.code in (403, 429, 503)
                errors.append(e)
                break
            except (urllib.error.URLError, OSError, ET.ParseError) as e:
                errors.append(e)
                break
            for g in found:
                if is_free(g):
                    games.setdefault(g["url"], dict(g, system=system))
            if len(found) < 10:
                break  # last page
    if not games and errors:
        if blocked:
            raise Blocked("itch.io turned the request away (its Cloudflare protection blocks some apps)")
        raise errors[0]
    out = sorted(games.values(), key=lambda g: g["title"].lower())
    os.makedirs(CACHE, exist_ok=True)
    write_json(path, {"time": time.time(), "games": out}, ensure_ascii=False)
    return out


# ---------- games ----------
def installed_path(game, roms_root):
    return downloads.find_installed(os.path.join(roms_root, game["system"]), game["title"])


def want(game):
    return {"id": game["url"], "title": game["title"], "system": game["system"], "stem": game["title"],
            "item": game}


def browse_want(system):
    return {"id": f"any:{system}", "title": f"any {LABELS[system]} ROM", "system": system, "any": True}


def es_de_fields(game):
    return {"name": game["title"], "desc": game.get("description") or "", "developer": game.get("author") or "",
            "publisher": "Homebrew (itch.io)",
            "releasedate": f"{game['year']}0101T000000" if game.get("year") else ""}
