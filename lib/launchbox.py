#!/usr/bin/env python3
"""LaunchBox Games DB: download once, split per platform into cache/launchbox/, match ROM titles to games.

CLI:
  ./lib/launchbox.py              # download + rebuild cache (~110 MB download, not kept)
  ./lib/launchbox.py --zip PATH   # rebuild from an already-downloaded Metadata.zip
"""
import argparse, datetime, difflib, gzip, json, os, re, tempfile, unicodedata, urllib.request, zipfile
import xml.etree.ElementTree as ET

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(APP_DIR, "cache", "launchbox")
META = os.path.join(CACHE, "_meta.json")
MANUAL = os.path.join(APP_DIR, "matches.json")  # hand-picked matches; outside cache/ so updates never touch it
URL = "https://gamesdb.launchbox-app.com/Metadata.zip"
IMAGE_URL = "https://images.launchbox-app.com/"
USER_AGENT = "RetroShelf/1.0"
# image types kept in the cache (the ones ES-DE has a media folder for)
IMAGE_TYPES = {
    "Box - Front", "Box - Front - Reconstructed", "Fanart - Box - Front", "Box - Back", "Box - 3D",
    "Cart - Front", "Disc", "Fanart - Cart - Front", "Fanart - Disc", "Screenshot - Gameplay",
    "Screenshot - Game Title", "Clear Logo", "Fanart - Background",
}

# ES-DE system name -> LaunchBox platform, for systems whose ES-DE full name doesn't match LaunchBox's.
ESDE_TO_LB = {
    "amiga600": "Commodore Amiga", "amiga1200": "Commodore Amiga", "arduboy": "Arduboy",
    "atarixe": "Atari XEGS", "atomiswave": "Sammy Atomiswave", "bbcmicro": "BBC Microcomputer System",
    "coco": "TRS-80 Color Computer", "colecovision": "ColecoVision",
    "arcade": "Arcade", "mame": "Arcade", "fba": "Arcade", "fbneo": "Arcade",
    "cps": "Arcade", "cps1": "Arcade", "cps2": "Arcade", "cps3": "Arcade",
    "dos": "MS-DOS", "pc": "MS-DOS", "dragon32": "Dragon 32/64", "tanodragon": "Dragon 32/64",
    "famicom": "Nintendo Entertainment System", "gamecom": "Tiger Game.com",
    "intellivision": "Mattel Intellivision", "macintosh": "Apple Mac OS", "mark3": "Sega Master System",
    "megacd": "Sega CD", "megacdjp": "Sega CD", "msx1": "Microsoft MSX", "msx2": "Microsoft MSX2",
    "msxturbor": "Microsoft MSX2+", "psp": "Sony PSP", "ps3": "Sony Playstation 3", "ps4": "Sony Playstation 4",
    "mugen": "MUGEN", "naomigd": "Sega Naomi", "openbor": "OpenBOR", "oric": "Oric Atmos",
    "pc88": "NEC PC-8801", "pc98": "NEC PC-9801", "pico8": "PICO-8", "pokemini": "Nintendo Pokemon Mini",
    "scummvm": "ScummVM", "sega32x": "Sega 32X", "sega32xjp": "Sega 32X", "sega32xna": "Sega 32X",
    "sfc": "Super Nintendo Entertainment System", "snes": "Super Nintendo Entertainment System",
    "snesna": "Super Nintendo Entertainment System", "stv": "Sega ST-V",
    "ti99": "Texas Instruments TI 99/4A", "triforce": "Sega Triforce", "uzebox": "Uzebox",
    "videopac": "Magnavox Odyssey 2", "wasm4": "WASM-4", "windows3x": "Windows 3.X", "windows9x": "Windows",
}


# LaunchBox splits some consoles' games over extra platforms; matching and scraping look there too
PLATFORM_EXTRAS = {"Sony PSP": ["Sony PSP Minis"]}
MATCH_VERSION = 2  # bump when matching rules change, so memoised matches are redone
SCENE_JUNK = {"us", "usa", "eur", "eu", "europe", "jpn", "jp", "japan", "uk", "pal", "ntsc", "patched", "final",
              "fixed", "undub", "translated", "eng", "english", "psp", "iso", "cso"}


def scene_variants(title):
    """Cleaner spellings of scene-style names ('Fate_Unlimited_Codes_USA', 'NarutoShippudenKizunaDriveUS',
    'Disgaea_Infinite_USA_PSP-BAHAMUT'), tried only when the name as written has no exact match."""
    s = re.sub(r"[ _]PSP-\w+$", "", title).replace("_", " ")
    out = []
    for v in (s, re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)):  # second one also splits CamelCase
        v = re.sub(r"(?<=[A-Z]{2})(?:USA|US|EUR|JPN)$|(?<=[a-z])(?:USA|US|EUR|JPN)$", "", v)
        words = v.split()
        while len(words) > 1 and words[-1].lower().strip("[]()") in SCENE_JUNK:
            words.pop()
        v = " ".join(words)
        if v and v != title and v not in out:
            out.append(v)
    return out


def pnorm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^(.*), (the|a|an|le|la|les|der|die|das|el|il)\b", r"\2 \1", s)
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(the|a|an)\b", " ", s)
    return " ".join(s.split())


def safe(platform):
    return re.sub(r"[^A-Za-z0-9]+", "_", platform).strip("_")


def load_meta():
    try:
        with open(META, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def platforms():
    meta = load_meta()
    return meta["platforms"] if meta else []


def resolve_platform(system, fullname, overrides=None):
    """Best LaunchBox platform for an ES-DE system, or None."""
    if overrides and system in overrides:
        return overrides[system] or None
    if system in ESDE_TO_LB:
        return ESDE_TO_LB[system]
    meta = load_meta()
    if not meta or not fullname:
        return None
    idx = {pnorm(p): p for p in meta["platforms"]}
    for alt, p in meta["platform_alts"].items():
        idx.setdefault(pnorm(alt), p)
    return idx.get(pnorm(fullname))


def update(zip_path=None, progress=print):
    os.makedirs(CACHE, exist_ok=True)
    tmp = None
    if not zip_path:
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        progress(f"Downloading {URL} …")
        # The server 403s Python's default "Python-urllib" user agent.
        req = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            total, done, step = int(r.headers.get("Content-Length") or 0), 0, 0
            while chunk := r.read(1 << 20):
                tmp.write(chunk)
                done += len(chunk)
                if done >> 24 > step:
                    step = done >> 24
                    progress(f"Downloading … {done >> 20} / {total >> 20} MB" if total else f"Downloading … {done >> 20} MB")
        tmp.close()
        zip_path = tmp.name

    try:
        progress("Parsing LaunchBox metadata …")
        by_plat, game_plat, alts, plat_alts = {}, {}, [], {}
        details, images = {}, {}
        depth = 0
        with zipfile.ZipFile(zip_path) as z:
            for ev, el in ET.iterparse(z.open("Metadata.xml"), events=("start", "end")):
                if ev == "start":
                    depth += 1
                    continue
                depth -= 1
                if depth != 1:
                    continue
                if el.tag == "Game":
                    gid, plat = el.findtext("DatabaseID"), el.findtext("Platform")
                    if gid and plat:
                        rating = el.findtext("CommunityRating")
                        by_plat.setdefault(plat, {})[gid] = {
                            "n": el.findtext("Name") or "",
                            "r": round(float(rating), 3) if rating else None,
                            "v": int(el.findtext("CommunityRatingCount") or 0),
                            "g": [x.strip() for x in (el.findtext("Genres") or "").split(";") if x.strip()],
                        }
                        game_plat[gid] = plat
                        details[gid] = {
                            "o": el.findtext("Overview") or "",
                            "d": el.findtext("Developer") or "",
                            "p": el.findtext("Publisher") or "",
                            "rd": (el.findtext("ReleaseDate") or el.findtext("ReleaseYear") or "")[:10],
                            "mp": int(el.findtext("MaxPlayers") or 0),
                        }
                elif el.tag == "GameImage":
                    itype = el.findtext("Type")
                    if itype in IMAGE_TYPES:
                        images.setdefault(el.findtext("DatabaseID"), []).append(
                            [itype, el.findtext("FileName"), el.findtext("Region") or ""])
                elif el.tag == "GameAlternateName":
                    alts.append((el.findtext("DatabaseID"), el.findtext("AlternateName") or ""))
                elif el.tag == "PlatformAlternateName":
                    plat_alts[el.findtext("Alternate") or ""] = el.findtext("Name")
                el.clear()
    finally:
        if tmp:
            os.unlink(tmp.name)

    alts_by_plat = {}
    for gid, name in alts:
        if gid in game_plat and name:
            alts_by_plat.setdefault(game_plat[gid], []).append([gid, name])

    for plat, games in by_plat.items():
        with open(os.path.join(CACHE, safe(plat) + ".json"), "w", encoding="utf-8") as f:
            json.dump({"games": games, "alts": alts_by_plat.get(plat, [])}, f, ensure_ascii=False)
        extra = {gid: dict(details[gid], img=images.get(gid, [])) for gid in games}
        with gzip.open(os.path.join(CACHE, safe(plat) + ".details.json.gz"), "wt", encoding="utf-8") as f:
            json.dump(extra, f, ensure_ascii=False)
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    with open(META, "w", encoding="utf-8") as f:
        json.dump({"updated": stamp, "platforms": sorted(by_plat), "platform_alts": plat_alts, "details": True},
                  f, indent=0)
    progress(f"LaunchBox data updated: {len(by_plat)} platforms, {len(game_plat)} games")


def has_details():
    meta = load_meta()
    return bool(meta and meta.get("details"))


def load_details(platform):
    out = {}
    for plat in [platform] + PLATFORM_EXTRAS.get(platform, []):
        try:
            with gzip.open(os.path.join(CACHE, safe(plat) + ".details.json.gz"), "rt", encoding="utf-8") as f:
                out = {**json.load(f), **out}  # the main platform wins if an id were ever in both
        except (OSError, ValueError, EOFError):
            pass
    return out


def load_manual():
    """-> {platform: {title: LaunchBox id, or None for "no match"}}"""
    try:
        with open(MANUAL, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def set_manual(platform, title, gid, clear=False):
    """Pin title to gid (None = never match). clear=True drops the pin so automatic matching applies again."""
    data = load_manual()
    plat = data.setdefault(platform, {})
    if clear:
        plat.pop(title, None)
    else:
        plat[title] = gid
    if not plat:
        del data[platform]
    with open(MANUAL, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)


def copy_manual(platform, titles):
    """titles: {old title: new title} after files are renamed, so hand-picked matches follow the games. The old
    title keeps its pick too (other versions of the game may still use it)."""
    data = load_manual()
    plat = data.get(platform, {})
    changed = False
    for old, new in titles.items():
        if old in plat and new not in plat:
            plat[new] = plat[old]
            changed = True
    if changed:
        with open(MANUAL, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)


class Matcher:
    """Maps ROM titles (tags already stripped) to LaunchBox games for one platform. Memoises to cache/matches/.
    Manual picks from matches.json win over automatic matching."""

    def __init__(self, platform):
        meta = load_meta()
        path = os.path.join(CACHE, safe(platform) + ".json")
        self.ok = bool(meta) and os.path.exists(path)
        self.games, self.index, self.memo, self.alts = {}, {}, {}, {}
        self.spelling = {}  # normalised key -> the LaunchBox name (main or alternate) it came from
        self.manual = load_manual().get(platform, {})
        if not self.ok:
            return
        for plat in [platform] + PLATFORM_EXTRAS.get(platform, []):  # main platform first: its names win
            try:
                with open(os.path.join(CACHE, safe(plat) + ".json"), encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            for gid, g in data["games"].items():
                self.games.setdefault(gid, g)
                self.index.setdefault(norm(g["n"]), gid)
                self.spelling.setdefault(norm(g["n"]), g["n"])
            for gid, name in data["alts"]:
                self.index.setdefault(norm(name), gid)
                self.spelling.setdefault(norm(name), name)
                self.alts.setdefault(gid, []).append(name)
        self.keys = list(self.index)
        self.stamp = f"{meta['updated']}|v{MATCH_VERSION}"
        self.memo_path = os.path.join(APP_DIR, "cache", "matches", safe(platform) + ".json")
        try:
            with open(self.memo_path, encoding="utf-8") as f:
                m = json.load(f)
            if m.get("stamp") == self.stamp:
                self.memo = m["titles"]
        except (OSError, ValueError):
            pass
        self.dirty = False

    def match(self, title):
        """-> (LaunchBox id, game dict with n/r/v/g, "exact"|"fuzzy"|"manual") or (None, None, None|"manual")"""
        if not self.ok:
            return None, None, None
        if title in self.manual:
            gid = self.manual[title]
            if gid is None:
                return None, None, "manual"
            if gid in self.games:  # else the pick left the LaunchBox DB; fall back to automatic matching
                return gid, self.games[gid], "manual"
        if title not in self.memo:
            tries = [title] + scene_variants(title)
            gid = next((self.index[norm(t)] for t in tries if norm(t) in self.index), None)
            kind = "exact" if gid else None
            for t in tries if not gid else []:
                n = norm(t)
                m = difflib.get_close_matches(n, self.keys, n=1, cutoff=0.9)
                if m and set(re.findall(r"\d+", m[0])) == set(re.findall(r"\d+", n)):
                    gid, kind = self.index[m[0]], "fuzzy"
                    break
            self.memo[title] = [gid, kind]
            self.dirty = True
        gid, kind = self.memo[title]
        return (gid, self.games[gid], kind) if gid else (None, None, None)

    def proper_name(self, title, gid):
        """How LaunchBox spells this game for this file: the main or alternate name the (cleaned-up) title matched,
        so 'GTI_Club_-_World_City_Race_US' keeps its US title instead of the Japanese main one."""
        for t in [title] + scene_variants(title):
            n = norm(t)
            if self.index.get(n) == gid:
                return self.spelling[n]
        return self.games[gid]["n"] if gid in self.games else None

    def matches_as_written(self, title):
        """True when the title, exactly as written, is a LaunchBox name (not just after scene clean-up)."""
        return norm(title) in self.index

    def search(self, query, limit=200):
        """LaunchBox ids whose name or an alternate name fits query, best first."""
        q = norm(query)
        if not self.ok or not q:
            return []
        words = q.split()
        scored = []
        for gid, g in self.games.items():
            best = None
            for name in [g["n"]] + self.alts.get(gid, []):
                n = norm(name)
                if n == q:
                    score = 0
                elif n.startswith(q):
                    score = 1
                elif all(w in n for w in words):
                    score = 2
                else:
                    r = difflib.SequenceMatcher(None, q, n).quick_ratio()
                    if r < 0.75 or difflib.SequenceMatcher(None, q, n).ratio() < 0.75:
                        continue
                    score = 3 - r
                best = score if best is None else min(best, score)
            if best is not None:
                scored.append((best, g["n"].lower(), gid))
        return [gid for _, _, gid in sorted(scored)[:limit]]

    def save(self):
        if self.ok and self.dirty:
            os.makedirs(os.path.dirname(self.memo_path), exist_ok=True)
            with open(self.memo_path, "w", encoding="utf-8") as f:
                json.dump({"stamp": self.stamp, "titles": self.memo}, f, ensure_ascii=False)
            self.dirty = False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", help="existing Metadata.zip")
    update(ap.parse_args().zip)
