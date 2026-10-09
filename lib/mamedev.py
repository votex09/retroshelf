"""MAMEDEV's free arcade ROMs (https://www.mamedev.org/roms/): classic arcade games whose owners let the MAME team
give them away "for free, non-commercial use".

Each game's page asks the visitor to confirm "I understand that these ROM images are for non-commercial use only"
before downloading, and says the ROMs may only be handed out from that site. So RetroShelf downloads each game
straight from mamedev.org, and only after the user confirms the same thing in the window.

Arcade ROMs are sets that MAME finds by file name (gridlee.zip), so they keep the name MAMEDEV gives them and go in
roms/mame. ES-DE shows their proper titles on its own.
"""
import html, json, os, re, time, urllib.request

from fsutil import write_json

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(APP_DIR, "cache", "mamedev")
SITE = "https://www.mamedev.org/roms/"
USER_AGENT = "RetroShelf/1.0 (+https://github.com/votex09/retroshelf)"
SYSTEM = "mame"
CACHE_DAYS = 30
PAUSE = 0.2
ACKNOWLEDGE = "I understand that these ROM images are for non-commercial use only."

CELL_RE = re.compile(r'<a href="([\w-]+)/?"><img src="([^"]+)"[^>]*alt="([^"]*)"[^>]*/?></a><br\s*/?>\s*'
                     r'<a href="[\w-]+/?">[^<]*</a><br\s*/?>\s*&copy;\s*(\d{4})\s*([^<]+?)\s*</td>', re.S)
SKIP_IMG_RE = re.compile(r"thumb|cabinet|flyer|marquee|logo|forkme|/_include/", re.I)


def _fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _text(fragment):
    s = re.sub(r"<br\s*/?>|</p>|</h\d>|</li>|</tr>", "\n", fragment or "", flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    lines = (" ".join(line.split()) for line in s.splitlines())
    return "\n".join(line for line in lines if line).strip()


def parse_index(text):
    """The ROMs page -> [{id, title, year, company, thumb, page}] in the site's order."""
    games = []
    for gid, thumb, title, year, company in CELL_RE.findall(text):
        page = SITE + gid + "/"
        games.append({"id": gid, "title": html.unescape(title), "year": year, "company": html.unescape(company),
                      "thumb": page + thumb.split("/", 1)[-1] if "/" in thumb else page + thumb, "page": page})
    return games


def parse_game_page(text, page):
    """A game's page -> {zips, notice, description, image}."""
    body = re.sub(r"<script.*?</script>|<style.*?</style>|<nav.*?</nav>|<table.*?</table>", "", text,
                  flags=re.S | re.I)  # (tables are scoring charts)
    zips = []
    for z in re.findall(r'href="([^"]+\.zip)"', body):
        if z not in zips:
            zips.append(z)
    out = {"zips": [z if z.startswith("http") else page + z for z in zips]}
    paras = [" ".join(_text(p).split()) for p in re.findall(r"<p[^>]*>(.*?)</p>", body, re.S)]
    out["notice"] = next((p for p in paras if "non-commercial" in p and "generosity" in p), "")
    m = re.search(r"<h2>\s*Description\s*</h2>(.*?)(?:<h2|$)", body, re.S)
    desc = re.findall(r"<p[^>]*>(.*?)</p>", m.group(1), re.S) if m else []
    out["description"] = "\n\n".join(" ".join(_text(p).split()) for p in desc)
    img = next((s for s in re.findall(r'<img [^>]*src="([^"]+)"', body) if not SKIP_IMG_RE.search(s)), "")
    out["image"] = img if not img or img.startswith("http") else page + img.lstrip("./")
    return out


def cache_path():
    return os.path.join(CACHE, "games.json")


def cached_age():
    try:
        with open(cache_path(), encoding="utf-8") as f:
            return (time.time() - json.load(f)["time"]) / 86400
    except (OSError, ValueError, KeyError):
        return None


def load_catalog(refresh=False, pause=PAUSE):
    """-> [game], each with its download links, from the cache unless it's missing, old or refresh is set."""
    path = cache_path()
    if not refresh:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if time.time() - data["time"] < CACHE_DAYS * 86400:
                return data["games"]
        except (OSError, ValueError, KeyError):
            pass
    games = parse_index(_fetch(SITE).decode("utf-8", "replace"))
    if not games:
        raise ValueError("the MAMEDEV ROMs page has changed, so RetroShelf can't read it")
    for i, g in enumerate(games):
        if i:
            time.sleep(pause)
        g.update(parse_game_page(_fetch(g["page"]).decode("utf-8", "replace"), g["page"]))
    games = [g for g in games if g["zips"]]
    os.makedirs(CACHE, exist_ok=True)
    write_json(path, {"time": time.time(), "games": games}, ensure_ascii=False)
    return games


def rom_name(game):
    """The set's file name, which MAME needs as is (the first download; others are older versions)."""
    return game["zips"][0].rsplit("/", 1)[-1]


def installed_path(game, roms_root):
    p = os.path.join(roms_root, SYSTEM, rom_name(game))
    return p if os.path.exists(p) else None


def install(game, roms_root):
    """Download the game's ROM set into roms/mame. -> path."""
    dest = os.path.join(roms_root, SYSTEM, rom_name(game))
    if os.path.exists(dest):
        raise FileExistsError(f"{os.path.basename(dest)} is already in roms/{SYSTEM}")
    data = _fetch(game["zips"][0], timeout=120)
    if not data.startswith(b"PK"):
        raise ValueError("MAMEDEV sent something that isn't a zip")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest + ".part", "wb") as f:
        f.write(data)
    os.replace(dest + ".part", dest)
    return dest


def want(game):
    return {"id": game["id"], "title": game["title"], "system": SYSTEM, "item": game}


def es_de_fields(game):
    return {"name": game["title"], "desc": game.get("description") or "", "developer": game.get("company") or "",
            "publisher": game.get("company") or "",
            "releasedate": f"{game['year']}0101T000000" if game.get("year") else ""}
