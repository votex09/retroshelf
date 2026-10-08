#!/usr/bin/env python3
"""LaunchBox Games DB: download once, split per platform into cache/launchbox/, match ROM titles to games.

CLI:
  ./launchbox.py              # download + rebuild cache (~110 MB download, not kept)
  ./launchbox.py --zip PATH   # rebuild from an already-downloaded Metadata.zip
"""
import argparse, datetime, difflib, gzip, json, os, re, tempfile, unicodedata, urllib.request, zipfile
import xml.etree.ElementTree as ET

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(APP_DIR, "cache", "launchbox")
META = os.path.join(CACHE, "_meta.json")
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
    try:
        with gzip.open(os.path.join(CACHE, safe(platform) + ".details.json.gz"), "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, EOFError):
        return {}


class Matcher:
    """Maps ROM titles (tags already stripped) to LaunchBox games for one platform. Memoises to cache/matches/."""

    def __init__(self, platform):
        meta = load_meta()
        path = os.path.join(CACHE, safe(platform) + ".json")
        self.ok = bool(meta) and os.path.exists(path)
        self.games, self.index, self.memo = {}, {}, {}
        if not self.ok:
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.games = data["games"]
        for gid, g in self.games.items():
            self.index.setdefault(norm(g["n"]), gid)
        for gid, name in data["alts"]:
            self.index.setdefault(norm(name), gid)
        self.keys = list(self.index)
        self.stamp = meta["updated"]
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
        """-> (LaunchBox id, game dict with n/r/v/g, "exact"|"fuzzy") or (None, None, None)"""
        if not self.ok:
            return None, None, None
        if title not in self.memo:
            n = norm(title)
            gid, kind = self.index.get(n), "exact"
            if not gid:
                m = difflib.get_close_matches(n, self.keys, n=1, cutoff=0.9)
                ok = m and set(re.findall(r"\d+", m[0])) == set(re.findall(r"\d+", n))
                gid, kind = (self.index[m[0]], "fuzzy") if ok else (None, None)
            self.memo[title] = [gid, kind]
            self.dirty = True
        gid, kind = self.memo[title]
        return (gid, self.games[gid], kind) if gid else (None, None, None)

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
