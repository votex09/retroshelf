"""Fill ES-DE metadata and media from the cached LaunchBox data. Only fills gaps: never overwrites existing
gamelist fields or media files, and never touches play counts, favorites or other ES-DE-managed fields."""
import datetime, os, re, shutil, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

import launchbox as lb

# ES-DE media folder -> (label, LaunchBox image types in order of preference, on by default)
MEDIA = {
    "covers": ("Box covers", ["Box - Front", "Box - Front - Reconstructed", "Fanart - Box - Front"], True),
    "backcovers": ("Back covers", ["Box - Back"], False),
    "3dboxes": ("3D boxes", ["Box - 3D"], False),
    "physicalmedia": ("Cartridge / disc", ["Cart - Front", "Disc", "Fanart - Cart - Front", "Fanart - Disc"], True),
    "screenshots": ("Screenshots", ["Screenshot - Gameplay"], True),
    "titlescreens": ("Title screens", ["Screenshot - Game Title"], True),
    "marquees": ("Marquees (logos)", ["Clear Logo"], True),
    "fanart": ("Fan art", ["Fanart - Background"], False),
}

# ROM region tag -> LaunchBox image regions, best first
IMAGE_REGIONS = {
    "USA": ["North America", "United States", "Canada", "World"],
    "Canada": ["Canada", "North America", "World"],
    "Europe": ["Europe", "United Kingdom", "World"],
    "UK": ["United Kingdom", "Europe", "World"],
    "Australia": ["Australia", "Oceania", "Europe", "World"],
    "Japan": ["Japan", "Asia"],
    "Korea": ["Korea", "Asia"],
    "China": ["China", "Asia"],
    "World": ["World", "North America", "Europe"],
}
for _r in ("France", "Germany", "Spain", "Italy", "Netherlands", "Sweden", "Norway", "Denmark", "Finland"):
    IMAGE_REGIONS[_r] = [_r, "Europe", "World"]

PRIMARY_EXT = [".m3u", ".cue", ".gdi", ".ccd", ".chd", ".iso", ".cso", ".pbp"]


def es_de_running():
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                with open(f"/proc/{pid}/comm") as f:
                    if f.read().strip().lower() in ("es-de", "emulationstation", "retrodeck"):
                        return True
            except OSError:
                pass
    return False


def media_root(roms_root):
    for p in (os.path.join(roms_root, "..", "ES-DE", "downloaded_media"), os.path.expanduser("~/ES-DE/downloaded_media")):
        if os.path.isdir(p):
            return os.path.realpath(p)
    return os.path.realpath(os.path.join(roms_root, "..", "ES-DE", "downloaded_media"))


def primary_file(paths):
    """The file ES-DE lists for a multi-file game (m3u over cue over bin tracks, …)."""
    if len(paths) == 1:
        return paths[0]
    for ext in PRIMARY_EXT:
        for p in sorted(paths):
            if p.lower().endswith(ext):
                return p
    return sorted(paths)[0]


def pick_image(images, types, rom_regions):
    prefs = []
    for r in rom_regions:
        prefs += [x for x in IMAGE_REGIONS.get(r, [r]) if x not in prefs]
    for t in types:
        cands = [i for i in images if i[0] == t]
        if not cands:
            continue
        for region in prefs + [""]:
            for i in cands:
                if i[2] == region:
                    return i
        return cands[0]
    return None


def has_media(folder, stem):
    try:
        return any(os.path.splitext(f)[0] == stem for f in os.listdir(folder))
    except OSError:
        return False


def es_date(s):
    if len(s) >= 10:
        return s[:10].replace("-", "") + "T000000"
    if len(s) == 4 and s.isdigit():
        return s + "0101T000000"
    return ""


def text_fields(game, det):
    players = det.get("mp") or 0
    return {
        "name": game["n"],
        "desc": (det.get("o") or "").strip(),
        "rating": f"{game['r'] / 5:.2f}".rstrip("0").rstrip(".") if game.get("r") is not None and game.get("v") else "",
        "releasedate": es_date(det.get("rd") or ""),
        "developer": det.get("d") or "",
        "publisher": det.get("p") or "",
        "genre": ", ".join(game.get("g") or []),
        "players": "" if not players else ("1" if players == 1 else f"1-{players}"),
    }


def read_gamelist(path):
    """ES-DE gamelists can have several top-level elements (e.g. <alternativeEmulator> before <gameList>), which
    isn't valid XML on its own. -> (list of top-level elements, the <gameList> element)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    tops = list(ET.fromstring(f"<esde-root>{text}</esde-root>"))
    gl = next((e for e in tops if e.tag == "gameList"), None)
    if gl is None:
        gl = ET.Element("gameList")
        tops.append(gl)
    return tops, gl


def save_gamelist(path, tops):
    parts = []
    for e in tops:
        ET.indent(e, space="\t")
        e.tail = None
        parts.append(ET.tostring(e, encoding="unicode"))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0"?>\n' + "\n".join(parts) + "\n")
    os.replace(tmp, path)


def carry_over(pairs, system, roms_root, gamelist):
    """After ROM renames [(old path, new path)]: rename the game's ES-DE media and gamelist <path> to match, so
    play counts, favorites, metadata and images follow the game. Files named for the new name already are left
    alone. -> (media files renamed, gamelist entries updated, problems). The gamelist is skipped while ES-DE runs,
    since it rewrites gamelist.xml when it quits."""
    stems = {}
    for old, new in pairs:
        o, n = os.path.basename(old), os.path.basename(new)
        stems[o] = n  # folders-as-games keep their full name in media
        stems[os.path.splitext(o)[0]] = os.path.splitext(n)[0]
    problems, media = [], 0
    mdir = os.path.join(media_root(roms_root), system)
    for mtype in sorted(os.listdir(mdir)) if os.path.isdir(mdir) else []:
        folder = os.path.join(mdir, mtype)
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            stem, ext = os.path.splitext(f)
            if stem not in stems:
                continue
            src, dst = os.path.join(folder, f), os.path.join(folder, stems[stem] + ext)
            try:
                if os.path.lexists(dst):
                    raise OSError("the new name already has this image")
                os.rename(src, dst)
                media += 1
            except OSError as e:
                problems.append(f"{mtype}/{f}: {e}")

    entries = 0
    if gamelist and os.path.exists(gamelist):
        if es_de_running():
            return media, 0, problems + ["gamelist.xml not updated: close RetroDECK / ES-DE and undo + redo, or "
                                         "rescrape text"]
        rel = {os.path.basename(o): n for o, n in pairs}
        try:
            tops, root = read_gamelist(gamelist)
            for g in root.iter("game"):
                el = g.find("path")
                path = (el.text or "").strip() if el is not None else ""
                old = os.path.basename(path.rstrip("/"))
                if old not in rel:
                    continue
                new = os.path.basename(rel[old])
                el.text = path.rstrip("/")[:-len(old)] + new + path[len(path.rstrip("/")):]
                name = g.find("name")
                if name is not None and (name.text or "").strip() == os.path.splitext(old)[0]:
                    name.text = os.path.splitext(new)[0]  # ES-DE's placeholder name for unscraped games
                entries += 1
            if entries:
                shutil.copy2(gamelist, f"{gamelist}.bak-{datetime.datetime.now():%Y%m%d-%H%M%S}")
                save_gamelist(gamelist, tops)
        except (OSError, ET.ParseError) as e:
            problems.append(f"gamelist.xml: {e}")
            entries = 0
    return media, entries, problems


def forget_games(names, system, roms_root, gamelist):
    """After games are deleted: remove their ES-DE media and gamelist entries. names = the games' file / folder
    names. -> (media files removed, gamelist entries removed, problems). The gamelist is left alone while ES-DE runs."""
    stems = set(names) | {os.path.splitext(n)[0] for n in names}
    problems, media = [], 0
    mdir = os.path.join(media_root(roms_root), system)
    for mtype in sorted(os.listdir(mdir)) if os.path.isdir(mdir) else []:
        folder = os.path.join(mdir, mtype)
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if os.path.splitext(f)[0] in stems:
                try:
                    os.unlink(os.path.join(folder, f))
                    media += 1
                except OSError as e:
                    problems.append(f"{mtype}/{f}: {e}")

    entries = 0
    if gamelist and os.path.exists(gamelist):
        if es_de_running():
            return media, 0, problems + ["gamelist.xml not cleaned: RetroDECK / ES-DE is running"]
        try:
            tops, root = read_gamelist(gamelist)
            gone = [g for g in root.findall("game")
                    if os.path.basename((g.findtext("path") or "").strip().rstrip("/")) in names]
            if gone:
                shutil.copy2(gamelist, f"{gamelist}.bak-{datetime.datetime.now():%Y%m%d-%H%M%S}")
                for g in gone:
                    root.remove(g)
                save_gamelist(gamelist, tops)
                entries = len(gone)
        except (OSError, ET.ParseError) as e:
            problems.append(f"gamelist.xml: {e}")
    return media, entries, problems


def write_gamelist(path, entries, log, overwrite=False):
    """entries: {rom file name: {field: value}}. Adds missing <game>s and fills empty fields; overwrite=True also
    replaces fields that already have a different value (e.g. from ES-DE's own scraper)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        tops, root = read_gamelist(path)  # parse before backing up, so a bad file fails without side effects
        backup = f"{path}.bak-{datetime.datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(path, backup)
        log(f"Backed up gamelist to {os.path.basename(backup)}")
    else:
        root = ET.Element("gameList")
        tops = [root]
    by_file = {}
    for g in root.iter("game"):
        by_file[os.path.basename((g.findtext("path") or "").rstrip("/"))] = g
    added = filled = 0
    for fname, fields in entries.items():
        g = by_file.get(fname)
        if g is None:
            g = ET.SubElement(root, "game")
            ET.SubElement(g, "path").text = f"./{fname}"
            added += 1
        for tag, value in fields.items():
            if not value:
                continue
            el = g.find(tag)
            if el is None:
                ET.SubElement(g, tag).text = value
                filled += 1
            elif not (el.text or "").strip() or (tag == "name" and el.text.strip() == os.path.splitext(fname)[0]) \
                    or (overwrite and el.text.strip() != value):
                el.text = value  # ES-DE uses the file name as a placeholder name for unscraped games
                filled += 1
    save_gamelist(path, tops)
    return added, filled


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": lb.USER_AGENT})
    tmp = dest + ".part"
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(tmp, dest)


def scrape(jobs, platform, system, roms_root, gamelist, do_text, media_types, progress, cancelled, overwrite=False):
    """jobs: list of (rom file path, LaunchBox id, rom regions). progress(msg, done, total). overwrite: replace
    existing gamelist text too (images are never replaced)."""
    details = lb.load_details(platform)
    games = lb.Matcher(platform).games
    mroot = os.path.join(media_root(roms_root), system)
    stats = {"text": 0, "images": 0, "skipped": 0, "missing": 0, "failed": 0}

    entries, downloads = {}, []
    for path, gid, regions in jobs:
        fname, stem = os.path.basename(path), os.path.splitext(os.path.basename(path))[0]
        det, game = details.get(gid, {}), games.get(gid)
        if not game:
            continue
        if do_text:
            entries[fname] = text_fields(game, det)
        for mtype in media_types:
            folder = os.path.join(mroot, mtype)
            if has_media(folder, stem):
                stats["skipped"] += 1
                continue
            img = pick_image(det.get("img", []), MEDIA[mtype][1], regions)
            if not img:
                stats["missing"] += 1
                continue
            ext = os.path.splitext(img[1])[1].lower() or ".jpg"
            downloads.append((lb.IMAGE_URL + img[1], os.path.join(folder, stem + ext)))

    total = len(downloads)
    progress(f"Downloading {total} images …", 0, total)
    for mtype in media_types:
        os.makedirs(os.path.join(mroot, mtype), exist_ok=True)
    done = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(download, u, d): d for u, d in downloads}
        for fut in as_completed(futures):
            if cancelled():
                for f in futures:
                    f.cancel()
                break
            done += 1
            try:
                fut.result()
                stats["images"] += 1
            except Exception:
                stats["failed"] += 1
            if done % 5 == 0 or done == total:
                progress(f"Downloading images … {done} / {total}", done, total)

    if do_text and entries and not cancelled():
        added, filled = write_gamelist(gamelist, entries, lambda m: progress(m, done, total), overwrite)
        stats["text"] = filled
        stats["added"] = added
    return stats
