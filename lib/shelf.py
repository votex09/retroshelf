"""One system's games and what to do with them, without any windows: scan the folder, match LaunchBox, decide which
games move (presets, patterns, ratings, genres, regions, hand flips, played / hidden protection), and move them.

Used by retroshelf.py (Tk) and app/helper/helper.py (Electron), so both apps decide the same way.

    sc = scan(roms_root, "snes", folder, exts, platform)
    d = decide(sc, state, priority)      # state: what the filters say; see decide()
    d.to_move, d.kept, d.why[key]"""
import datetime, json, os, shutil
import xml.etree.ElementTree as ET
from collections import Counter

import hiding
import launchbox as lb
import nps
import scraper
from fsutil import held_rel, write_json
from library import PARTIAL_EXT, list_entries
from rules import DUPES, PREFIX_RE, PRESETS, REGION_MODES, dir_size, dupes_priority, region_dupes, regions_of, \
    title_of, unit_key, wildcard_re

DEFAULT_STATE = {"patterns": "", "icase": True, "presets": [], "protect_played": True, "use_rating": False,
                 "rating_max": 2.5, "min_votes": 3, "use_unrated": False, "genres": [], "regions": [],
                 "region_mode": REGION_MODES[0], "flips": {}}


class Scan:
    """What's in one system's folder: games (units of files), and what's known about each."""

    def __init__(self, roms_root, system, folder, exts, platform):
        self.roms_root, self.system, self.folder, self.exts, self.platform = roms_root, system, folder, exts, platform
        self.units = {}          # key -> {"paths": [abs path], "size": int, "extra": [installed RPCS3 / Vita3K data]}
        self.file_to_unit = {}
        self.preset_hits = {}    # preset -> {keys} (region dupes: {key: the copy kept instead})
        self.dupes_key = None    # the priority region dupes were last worked out with
        self.played, self.hidden = set(), set()
        self.ratings, self.lb_kind, self.lb_ids, self.lb_links = {}, {}, {}, {}
        self.regions = {}        # key -> region tags, ("(none)",) when it has none
        self.genre_counts, self.region_counts = Counter(), Counter()
        self.matched = self.rated = 0

    @property
    def region_names(self):
        return [r for r, _ in self.region_counts.most_common()]

    @property
    def genre_names(self):
        return [g for g, _ in self.genre_counts.most_common()]


def scan(roms_root, system, folder, exts, platform):
    sc = Scan(roms_root, system, folder, exts, platform)
    for e in list_entries(folder, exts):
        key = e.name if e.name.lower().endswith(PARTIAL_EXT) else unit_key(e.name)
        u = sc.units.setdefault(key, {"paths": [], "size": 0, "extra": []})
        u["paths"].append(e.path)
        u["size"] += dir_size(e.path) if e.is_dir() else e.stat().st_size
        for x in nps.linked_data(system, e.path, roms_root):  # installed PS3 / Vita data
            u["extra"].append(x)
            u["size"] += dir_size(x) if os.path.isdir(x) else os.path.getsize(x)
        sc.file_to_unit[e.name] = key
    keys = list(sc.units)
    sc.preset_hits = {p: fn(keys) for p, fn in PRESETS.items() if p != DUPES}
    sc.preset_hits["Partial downloads (.part)"] = {k for k in keys if k.lower().endswith(PARTIAL_EXT)}

    gl = scraper.find_gamelist(roms_root, system)
    if gl:
        try:
            for g in scraper.read_gamelist(gl)[1].iter("game"):
                if int(g.findtext("playcount") or 0) > 0:
                    fn = os.path.basename((g.findtext("path") or "").rstrip("/"))
                    sc.played.add(sc.file_to_unit.get(fn, unit_key(fn)))
        except (OSError, ET.ParseError, ValueError):
            pass
    sc.played &= sc.units.keys()
    names = hiding.hidden(gl)  # a game is hidden when the file ES-DE lists for it is (not just a disc of it)
    sc.hidden = {k for k, u in sc.units.items() if os.path.basename(scraper.primary_file(u["paths"])) in names}

    if platform:
        m = lb.Matcher(platform)
        if m.ok:
            for k in keys:
                gid, g, kind = m.match(title_of(k))
                if kind:
                    sc.lb_kind[k] = kind
                if g:
                    sc.ratings[k] = g
                    sc.lb_ids[k] = gid
                    if kind in ("exact", "manual"):  # (groups region dupes, drives scraping)
                        sc.lb_links[k] = gid
                    sc.matched += 1
                    sc.rated += g["r"] is not None
            m.save()
    sc.genre_counts = Counter(x for g in sc.ratings.values() for x in g["g"])
    sc.regions = {k: regions_of(k) or ("(none)",) for k in keys}
    sc.region_counts = Counter(r for rs in sc.regions.values() for r in rs)
    return sc


class Decision:
    def __init__(self):
        self.to_move, self.kept, self.why = [], [], {}
        self.active, self.moves, self.keeps = [], [], []  # presets on, move patterns, ! keep patterns
        self.use_rating = self.use_unrated = False
        self.genres, self.regions = set(), set()

    def tab_counts(self):
        """How many filters are on in each tab: presets & ratings, genres, regions, patterns."""
        return [len(self.active) + self.use_rating + self.use_unrated, len(self.genres), len(self.regions),
                len(self.moves) + len(self.keeps)]


def decide(sc, state, priority):
    """Sort sc's games into Keeping and Moving. state: DEFAULT_STATE's keys (missing ones take its values);
    priority: region names, best first, for which copy of a region dupe stays."""
    st = {**DEFAULT_STATE, **state}
    d = Decision()
    icase = st["icase"]
    for raw in (st["patterns"] or "").splitlines():
        p = raw.strip()
        if not p or p.startswith("#"):
            continue
        if p.startswith("!"):
            d.keeps.append((p, wildcard_re(p[1:], icase)))
        else:
            d.moves.append((p, wildcard_re(p, icase)))
    d.active = [p for p in st["presets"] if p in PRESETS or p in sc.preset_hits]
    try:
        rating_max, min_votes = float(st["rating_max"]), int(st["min_votes"])
    except (TypeError, ValueError):  # half-typed: no game passes
        rating_max, min_votes = -1.0, 1 << 30
    d.use_rating, d.use_unrated = bool(st["use_rating"]), bool(st["use_unrated"])
    d.genres = set(st["genres"]) & set(sc.genre_counts)
    d.regions = set(st["regions"]) & set(sc.region_counts)
    keep_only = st["region_mode"] == REGION_MODES[1]
    prio = dupes_priority(priority, d.regions, keep_only, sc.region_names)
    if prio != sc.dupes_key:
        sc.preset_hits[DUPES] = region_dupes(list(sc.units), prio, sc.lb_links)
        sc.dupes_key = prio
    protect = st["protect_played"]
    flips = st["flips"] or {}

    for key in sorted(sc.units):
        if key in flips:
            hit, why = flips[key], "manual"
        else:
            names = [key] + [os.path.basename(p) for p in sc.units[key]["paths"]]
            reasons = [
                f"dupe of {PREFIX_RE.sub('', sc.preset_hits[p][key])}" if p == DUPES else p.split(" (")[0]
                for p in d.active if key in sc.preset_hits.get(p, ())
            ]
            reasons += [p for p, rx in d.moves if any(rx.match(n) for n in names)]
            g = sc.ratings.get(key)
            if d.use_rating and g and g["r"] is not None and g["v"] >= min_votes and g["r"] < rating_max:
                reasons.append(f"rating < {rating_max:g}")
            if d.use_unrated and (not g or g["r"] is None):
                reasons.append("unrated")
            if d.genres and g and d.genres.intersection(g["g"]):
                reasons.append("genre")
            if d.regions:
                rs = set(sc.regions[key])
                if (keep_only and not rs & d.regions) or (not keep_only and rs <= d.regions):
                    reasons.append("region")
            keeper = "played" if protect and key in sc.played else None
            keeper = keeper or ("hidden in ES-DE" if key in sc.hidden else None)
            keeper = keeper or next((p for p, rx in d.keeps if any(rx.match(n) for n in names)), None)
            hit = bool(reasons) and keeper is None
            why = keeper if (reasons and keeper) else ", ".join(reasons)
        d.why[key] = why
        (d.to_move if hit else d.kept).append(key)
    return d


# ---------- moving ----------
def holding_root(cfg):
    return cfg.get("holding_root") or os.path.join(os.path.dirname(os.path.normpath(cfg["roms_root"])), "pruned")


def on_same_drive(holding, roms_root):
    """True when the holding folder (or where it will be created) shares a filesystem with roms."""
    p = holding
    while not os.path.exists(p) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    try:
        return os.stat(p).st_dev == os.stat(roms_root).st_dev
    except OSError:
        return False


def move_games(sc, keys, dest_dir):
    """Move these games (with any installed RPCS3 / Vita3K data) into dest_dir.
    -> (files moved, ["name: error"], [[from, to]] done)"""
    os.makedirs(dest_dir, exist_ok=True)
    base = os.path.dirname(os.path.realpath(sc.roms_root))
    moved, failed, done = 0, [], []
    for k in keys:
        u = sc.units[k]
        for p in u["paths"] + u["extra"]:
            if p in u["extra"]:  # keep the path under retrodeck/ so it can be moved back by hand
                target = os.path.join(dest_dir, "installed", held_rel(os.path.realpath(p), base))
                os.makedirs(os.path.dirname(target), exist_ok=True)
            else:
                target = os.path.join(dest_dir, os.path.basename(p))
            try:
                if os.path.exists(target):
                    raise OSError("already exists in holding folder")
                shutil.move(p, target)
                done.append([p, target])
                moved += 1
            except OSError as e:
                failed.append(f"{os.path.basename(p)}: {e}")
    return moved, failed, done


def move_batch(system, dest, games, size, done):
    """One entry of the move log (moves.json)."""
    return {"time": datetime.datetime.now().isoformat(timespec="seconds"), "system": system, "dest": dest,
            "games": games, "size": size, "moves": done}


def read_moves(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def write_moves(path, batches):
    write_json(path, batches, indent=1)
