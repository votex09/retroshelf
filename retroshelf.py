#!/usr/bin/env python3
"""RetroShelf: manage an ES-DE / RetroDECK library. Prune unwanted ROMs (any system), scrape metadata from
LaunchBox, and download + install PS3 / PS Vita / PSP games through NoPayStation.

Pick a roms folder and a system; the console comes from the folder name (ES-DE system name), checked against
its systeminfo.txt, and is mapped to a LaunchBox platform for ratings/genres (override it in the dropdown).

Patterns: one per line, case-insensitive by default. Only * and ? are wildcards, so [b] and (USA) match literally.
Plain text with no * or ? matches anywhere in the name; with wildcards the pattern must match the whole name.
  mario           -> move anything containing "mario"
  *(Demo)*        -> move matches
  !*Mario*        -> keep matches, even if a preset/pattern/rating hit them
  # comment       -> ignored
Double-click a game in either pane to flip it manually (beats everything, including played-game protection).
Right-click a game to pick its LaunchBox entry by hand when the automatic match is missing or wrong.
Rename… brings file names in line with a template (default: No-Intro order), with a preview and undo.
Multi-file games (cue/bin tracks, multi-disc + m3u) are handled as one unit and move together.
Moved files go to <holding folder>/<to_delete|review_low_value>/<system>/, outside roms so ES-DE won't list them.
Holding folder… lists moved games with artwork and details, and restores or permanently deletes them.
Import ROMs… takes games in any form (zip / 7z / rar archives, disc images, loose ROMs, folders of them), from an
import folder next to roms or from anywhere, works out each one's system, then unpacks and files it (see
lib/romimport.py; 7z needs no 7-Zip: lib/sevenzip.py).
The details panel plays a game's gameplay clip from ES-DE's videos folder, or (if switched on in the View menu) the
top YouTube result through mpv and yt-dlp (see lib/video.py).
Set up RetroDECK… (Windows: Set up ES-DE…) installs the frontend for people who don't have it yet, letting them pick
where games go (see lib/frontend.py); it opens by itself the first time no ROMs folder can be found.
For ps3, psvita and psp a NoPayStation… button downloads and installs PSN packages (see lib/nps.py).
Homebrew Hub… browses free GB / GBC / GBA / NES homebrew and files it into roms (see lib/homebrew.py); itch.io
homebrew… and PDRoms homebrew… do the same for free retro homebrew on itch.io and pdroms.de, downloaded in the
browser (see lib/itch.py, lib/pdroms.py). Free arcade games (MAMEDEV)… installs the arcade ROMs their owners released
for non-commercial use into roms/mame (see lib/mamedev.py). Rename… leaves arcade systems alone (set names matter).
Updates come from GitHub releases (git clones: the main branch): checked at startup (can be turned off) or with Check
for updates (see lib/updater.py).
Add to app menu (or --install-desktop) installs a .desktop entry (Windows: a Start menu shortcut); retroshelf.sh
(Windows: retroshelf.bat) is a launcher for Steam / file managers.
"""
import datetime, json, os, queue, re, shutil, sys, threading
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(APP_DIR, "vendor"))
sys.path.insert(0, os.path.join(APP_DIR, "lib"))
import sv_ttk  # noqa: E402  (vendored Sun Valley theme, MIT)

import launchbox as lb  # noqa: E402
import listkeys  # noqa: E402
import review  # noqa: E402
import nps  # noqa: E402
import nps_gui  # noqa: E402
import homebrew_gui  # noqa: E402
import import_gui  # noqa: E402
import romimport  # noqa: E402
import itch_gui  # noqa: E402
import mamedev_gui  # noqa: E402
import pdroms_gui  # noqa: E402
import setup_gui  # noqa: E402
import scraper  # noqa: E402
import desktop  # noqa: E402
import dialogs  # noqa: E402
import frontend  # noqa: E402
import details  # noqa: E402
from fsutil import held_rel, is_windows, write_json  # noqa: E402
import ui  # noqa: E402
import updater  # noqa: E402
import video  # noqa: E402

UI_FONTS = ["Inter", "Segoe UI", "Noto Sans", "Cantarell", "Ubuntu", "DejaVu Sans"]
MONO_FONTS = ["JetBrains Mono", "Fira Code", "Cascadia Mono", "Consolas", "Noto Sans Mono", "DejaVu Sans Mono",
              "monospace"]
PALETTE = {
    "dark": {"field": "#272727", "fg": "#fafafa", "border": "#3a3a3a", "accent": "#57c8ff", "sel": "#2f60d8",
             "muted": "#9a9a9a", "stripe": "#232323", "manual": "#ffb347", "keep": "#7fd17f", "move": "#ff8a80",
             "hover": "#30343c", "selrow": "#1f4f86"},
    "light": {"field": "#ffffff", "fg": "#1c1c1c", "border": "#d4d4d4", "accent": "#005fb8", "sel": "#2f60d8",
              "muted": "#6b6b6b", "stripe": "#f3f3f3", "manual": "#b05000", "keep": "#1e7b34", "move": "#c42b1c",
              "hover": "#e4ecf7", "selrow": "#bcd8f5"},
}
PATTERN_EXAMPLES = (
    "mario     contains\n"
    "*(Beta)*  * ? wildcards\n"
    "0002*     starts with\n"
    "!kart     always keep\n"
    "# note    ignored"
)
PATTERN_HELP = [
    ("mario", "Plain text: moves any game whose name contains it, anywhere."),
    ("(Japan)\n[b]", "Brackets and parentheses are ordinary characters, so tags like (Japan), (Demo) and [b] "
                     "match exactly as written."),
    ("*", "Wildcard for any run of characters (including none)."),
    ("?", "Wildcard for exactly one character."),
    ("0002*\n*.part\n*(USA)*(Rev ?)*", "As soon as a line has * or ?, it must match the whole name. "
                                        "0002* = starts with 0002, *.part = ends with .part."),
    ("!kart\n!*(USA)*", "Lines starting with ! are keep rules: matching games stay, even if a preset, pattern, "
                        "rating, genre or region would move them."),
    ("# comment", "Lines starting with # are ignored. Blank lines are ignored too."),
]
PATTERN_NOTES = (
    "Patterns are checked against the game name and each of its file names (with extension), so .nds, .zip "
    "or .cue work. Case is ignored unless you untick Ignore case.\n"
    "Priority, highest first: double-click flips  ›  Protect played games  ›  ! keep rules  ›  everything else "
    "that moves a game (presets, patterns, ratings, genres, regions)."
)
CONFIG = os.path.join(APP_DIR, "config.json")
DESTS = ["to_delete", "review_low_value"]
HEAD_PAD = 4  # px left/right inside column headings, matching the theme's cell text inset
NON_GAME_EXT = {".txt", ".nfo", ".md", ".pdf", ".htm", ".html", ".xml", ".json", ".dat", ".jpg", ".jpeg",
                ".png", ".gif", ".bmp", ".webp", ".mp4", ".py", ".sh", ".log", ".ini", ".cfg", ".directory"}

JUNK_TAGS = r"Proto|Beta|Demo|Sample|Kiosk|Unl|Promo|Not for Resale|Test Program|Alpha|Pirate|Aftermarket"

SPORTS_WORDS = (
    "Madden|FIFA|NBA|NFL|NHL|MLB|PGA|NASCAR|UFC|WWE|WWF|Tennis|Soccer|Football|Golf|Bowling|Cricket|"
    "Snowboard|Skate|Skateboarding|Surf|Rugby|Formula One|F1|MotoGP|Basketball|Baseball|Hockey|Boxing|"
    "Wrestling|Olympic|Volleyball|Dodgeball|Fishing|Hunting|Sports"
)
SPORTS_EXCEPT = ["Scotland Yard"]

KIDS_WORDS = (
    # kids' and casual brands (mostly DS / Wii era)
    "Dora|Barbie|Bratz|Hannah Montana|High School Musical|SpongeBob|Winx|Littlest Pet Shop|Monster High|"
    "Scooby-?Doo|Sesame Street|Shrek|Tinker ?Bell|Hello Kitty|My Little Pony|Strawberry Shortcake|Bakugan|"
    "Build-?A-?Bear|Imagine[: ]|Petz|Chihuahua|Cooking Mama|Diner Dash|Dress ?Up|Fashion|Horsez|Pony Friends|"
    "Care Bears|Go, ?Diego|Nickelodeon|Nicktoons|Nick Jr|Disney|Pixar|Fairly Odd ?Parents|Phineas|Hannah|iCarly|"
    "Trollz|Dreamworks|Cartoon Network|Garfield|Marmaduke|Alvin and the Chipmunks|Chipmunks|Cheetah Girls|"
    "WordWorld|Clifford|Curious George|Elmo|Thomas (?:and|&) Friends|Polly Pocket|Lalaloopsy|Moshi Monsters|"
    "Club Penguin|Webkinz|Zhu Zhu|Fisher-Price|LeapFrog|Jump ?Start|Reader Rabbit|Smurfs|Rainbow Magic|"
    # animated films (their games are named after the film, without the studio)
    "Finding (?:Nemo|Dory)|Toy Story|Incredibles|Monsters,? Inc|Monsters University|Ratatouille|WALL-?E|"
    "Lilo (?:&|and) Stitch|Ice Age|Kung Fu Panda|Madagascar|Bee Movie|Chicken Little|Chicken Run|Shark Tale|"
    "Over the Hedge|Monster House|Happy Feet|Flushed Away|Meet the Robinsons|Brother Bear|Treasure Planet|"
    "Open Season|Surf's Up|Ant Bully|Polar Express|Monsters vs\\.? Aliens|How to Train Your Dragon|Puss in Boots|"
    "Despicable Me|Minions|Hotel Transylvania|Cloudy with a Chance|Megamind|Rango|Wreck-It Ralph|Big Hero 6|"
    "Wallace (?:&|and) Gromit|Shaun the Sheep|Lion King|Little Mermaid|Jungle Book|Beauty and the Beast|"
    "Aladdin|Pocahontas|Mulan|Tarzan|Peter Pan|Pinocchio|Winnie the Pooh|Pooh|Mickey|Minnie|Donald Duck|"
    "Goofy|Cars (?:Race-O-Rama|Mater-National)|Atlantis - The Lost Empire|Cat in the Hat|Grinch|Horton|"
    "Charlie and the Chocolate Factory|Willy Wonka|Spy Kids|Agent Cody Banks|"
    # children's TV
    "Rugrats|Jimmy Neutron|Danny Phantom|Avatar - The Last Airbender|Teenage Mutant Ninja Turtles|TMNT|"
    "Power Rangers|Kim Possible|Lizzie McGuire|That's So Raven|Suite Life|Wizards of Waverly|Camp Rock|"
    "Zoey 101|Drake (?:&|and) Josh|Hey Arnold|Wild Thornberrys|CatDog|Powerpuff|Dexter's Laboratory|"
    "Kids Next Door|Ben 10|Wiggles|Teletubbies|Barney|Blue's Clues|Bob the Builder|Arthur's|Caillou|"
    "Little Einsteins|Handy Manny|Backyardigans|Paw Patrol|Peppa Pig|PJ Masks|Octonauts|Bubble Guppies|"
    "Wonder Pets|Tom (?:and|&) Jerry|Looney Tunes|Bugs Bunny|Tweety|Flintstones|Jetsons|Yogi Bear|"
    "American Dragon|Proud Family|Lazy ?Town|Rocket Power|Dragon Tales|Arthur!|Doug's|"
    # 80s / 90s cartoons and family films (NES, SNES, Mega Drive, Game Boy era)
    "DuckTales|Darkwing Duck|TaleSpin|Chip ?['’]?n['’]? ?Dale|Rescue Rangers|Goof Troop|Bonkers|Gargoyles|"
    "Tiny Toon|Animaniacs|Pinky and the Brain|Taz-?Mania|Road Runner|Wile E|Daffy Duck|Porky Pig|"
    "Speedy Gonzales|Simpsons|Bart (?:vs|Simpson)|Bart's|Itchy (?:&|and) Scratchy|Krusty|Rocko's Modern Life|"
    "Ren (?:&|and) Stimpy|Real Monsters|Captain Planet|Muppets?|Fraggle|Fievel|Land Before Time|Casper|"
    "Pagemaster|Home Alone|Addams Family|Bobby's World|We're Back|Stuart Little|Dalmatians|Bug's Life|"
    "Emperor's New Groove|Pink Panther|Popeye|Woody Woodpecker|Felix the Cat|Snoopy|Peanuts|Charlie Brown|"
    "Richie Rich|Dennis the Menace|Inspector Gadget|Huckleberry Hound|Top Cat|Wacky Races|Hanna-Barbera|"
    "Bucky O'Hare|Fido Dido|Tiny Toons|Baby Looney|Pocket Dragons"
)
# films whose name is an everyday word: only when it's the whole title ("Cars 2", "Up (USA)", not "Crazy Cars")
KIDS_TITLES = ("Cars|Up|Bolt|Brave|Planes|Rio|Turbo|Barnyard|Robots|Dinosaur|Frozen|Tangled|Zootopia|Coco|Moana|"
               "Inside Out|Arthur|Franklin|Recess|Hercules|Bambi|Valiant|Epic|Home on the Range|Hook|Doug|Widget")
KIDS_EXCEPT = ["Nintendogs"]

DEFAULT_PRIORITY = "USA, World, Europe, Australia, Japan, Korea"
KNOWN_REGIONS = {
    "World", "USA", "Europe", "Japan", "Korea", "China", "Taiwan", "Hong Kong", "Asia", "Australia", "New Zealand",
    "Canada", "Brazil", "Mexico", "Argentina", "Latin America", "France", "Germany", "Spain", "Italy", "Netherlands",
    "Belgium", "Austria", "Switzerland", "Sweden", "Denmark", "Norway", "Finland", "Scandinavia", "UK",
    "United Kingdom", "Ireland", "Portugal", "Greece", "Poland", "Russia", "Czech", "Hungary", "Croatia", "Turkey",
    "Israel", "India", "South Africa", "Export", "Unknown",
}
REGION_MODES = ["Move selected", "Keep only selected"]

JUNK_RE = re.compile(rf"\((?:{JUNK_TAGS})\b", re.I)
# whole words; "_" and "." count as spaces (scene names: Spongebob_Squarepants_USA)
SPORTS_RE = re.compile(rf"(?<![^\W_])(?:{SPORTS_WORDS})(?![^\W_])", re.I)
KIDS_RE = re.compile(rf"(?<![^\W_])(?:{KIDS_WORDS})(?![^\W_])", re.I)
KIDS_TITLE_RE = re.compile(rf"^(?:{KIDS_TITLES})(?:$|\s*[-:(]|\s+\d)", re.I)
PREFIX_RE = re.compile(r"^[a-z]?\d{3,4} - ", re.I)  # numbered sets like "0123 - " / "x045 - "
TAG_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
PART_RE = re.compile(r"\s*\((?:Track|Disc|Disk|CD)\s*\d+[^)]*\)", re.I)


def unit_key(name):
    return PART_RE.sub("", os.path.splitext(name)[0]).strip()


def title_of(key):
    return TAG_RE.sub("", PREFIX_RE.sub("", key)).strip()


def regions_of(key):
    """No-Intro/Redump region tag, e.g. '(USA, Europe)' -> ('USA', 'Europe'); () if none found."""
    for group in re.findall(r"\(([^)]*)\)", key):
        parts = tuple(p.strip() for p in group.split(","))
        if all(p in KNOWN_REGIONS for p in parts):
            return parts
    return ()


def keyword_preset(rx, exceptions, title_rx=None):
    """Games whose name has one of the words (or, with title_rx, whose whole title is one), minus exceptions."""
    def hit(k):
        text = " ".join(re.sub(r"[_.]+", " ", k).split())
        return bool(rx.search(text) or title_rx and title_rx.match(title_of(text)))

    def run(keys):
        return {k for k in keys if hit(k) and not any(x.lower() in k.lower() for x in exceptions)}
    return run


def junk(keys):
    return {k for k in keys if JUNK_RE.search(k)}


def parse_priority(text):
    return [p.strip().lower() for p in text.split(",") if p.strip()]


def keeper_rank(key, priority):
    """Lower sorts first = the copy to keep. A copy ranks by its best-priority region; unlisted regions go last."""
    regions = [r.lower() for r in regions_of(key)]
    region_rank = min((priority.index(r) for r in regions if r in priority), default=len(priority))
    rev = re.search(r"\(Rev (\d+)\)", key)
    langs = re.search(r"\(((?:[A-Z][a-z],)+[A-Z][a-z])\)", key)
    return (
        bool(JUNK_RE.search(key)),
        region_rank,
        "[b]" in key,
        -int(rev.group(1)) if rev else 0,
        -(langs.group(1).count(",") + 1 if langs else 1),
        key,
    )


def dupe_groups(keys, links=None):
    """Group copies of the same game: same title once tags are stripped, or same LaunchBox game (links: key -> id).
    Links chain, so 'Catch! Touch! Yoshi! (Japan)' joins 'Yoshi Touch & Go (USA)' and '(Europe)' via LaunchBox."""
    parent = {k: k for k in keys}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    first = {}
    for k in keys:
        for tag in (("t", title_of(k).lower()), ("lb", (links or {}).get(k))):
            if tag[1] is None:
                continue
            if tag in first:
                parent[find(k)] = find(first[tag])
            else:
                first[tag] = k
    groups = defaultdict(list)
    for k in keys:
        groups[find(k)].append(k)
    return groups


def region_dupes(keys, priority=None, links=None):
    """-> {extra copy: the copy kept instead}"""
    priority = priority or parse_priority(DEFAULT_PRIORITY)
    out = {}
    for ks in dupe_groups(keys, links).values():
        if len(ks) > 1:
            ranked = sorted(ks, key=lambda k: keeper_rank(k, priority))
            out.update({k: ranked[0] for k in ranked[1:]})
    return out


PRESETS = {
    "Junk (demo/kiosk/beta/proto/unl)": junk,
    "Sports": keyword_preset(SPORTS_RE, SPORTS_EXCEPT),
    "Kids / licensed tie-ins": keyword_preset(KIDS_RE, KIDS_EXCEPT, KIDS_TITLE_RE),
    "Region dupes (keep 1 per title)": region_dupes,
}
DUPES = "Region dupes (keep 1 per title)"
PRESET_LABELS = {  # shorter text for the checkboxes; the full names stay the keys (saved per system)
    "Junk (demo/kiosk/beta/proto/unl)": "Junk (demos, betas, protos …)",
    DUPES: "Region dupes (keep one)",
}
PARTIAL_EXT = (".part", ".crdownload", ".tmp")


# ---------- renaming ----------
DEFAULT_TEMPLATE = "{title} ({region}) ({lang}) ({rev}) {tags}"  # No-Intro order
RENAME_FIELDS = {
    "title": "name without tags or set number", "region": "USA, Europe …", "lang": "En,Fr,Es …",
    "rev": "Rev 1, v1.1 …", "tags": "every other tag, brackets kept", "lbname": "LaunchBox name (else title)",
}
ANY_TAG_RE = re.compile(r"[\(\[][^\)\]]*[\)\]]")
LANG_RE = re.compile(r"[A-Z][a-z](?:[+-][A-Z][a-z])*(?:,\s*[A-Z][a-z](?:[+-][A-Z][a-z])*)*")
REV_RE = re.compile(r"Rev\s*[\w.]+|v\d[\w.]*|Version\s*[\w.]+", re.I)
REF_EXT = (".cue", ".m3u", ".gdi")  # text files that name the game's other files
WIN_RESERVED_RE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", re.I)  # device names Windows won't use
WIN_MAX_PATH = 259  # longer paths fail unless long paths are switched on in Windows


def split_ext(name):
    """('Mr. Driller (USA)', '') rather than ('Mr', '. Driller (USA)') for folders and extensionless names."""
    stem, ext = os.path.splitext(name)
    return (stem, ext) if re.fullmatch(r"\.[A-Za-z0-9_+-]{1,10}", ext) else (name, "")


SCENE_REGIONS = {"USA": "USA", "US": "USA", "EUR": "Europe", "EU": "Europe", "JPN": "Japan", "JP": "Japan"}
SCENE_REGION_RE = re.compile(r"(?:^|(?<=[_\s.-]))(USA|US|EUR|EU|JPN|JP)(?=$|[_\s.-])"
                             r"|(?:(?<=[a-z])|(?<=[A-Z]{2}))(USA|US|EUR|JPN)$")


def name_fields(stem, lb_name=None, lb_title=False):
    """lb_title: the file name isn't a real title (scene name, or the game was matched by hand), so {title} comes
    from LaunchBox, and a region word like _USA_ or ...US becomes {region}."""
    s = PREFIX_RE.sub("", stem)
    f = {"title": TAG_RE.sub("", s).strip(), "region": "", "lang": "", "rev": ""}
    if lb_title and lb_name:
        f["title"] = lb_name
    other = []
    for tag in ANY_TAG_RE.findall(s):
        inner = tag[1:-1].strip()
        if tag[0] == "(" and not f["region"] and all(p.strip() in KNOWN_REGIONS for p in inner.split(",")):
            f["region"] = ", ".join(p.strip() for p in inner.split(","))
        elif tag[0] == "(" and not f["lang"] and LANG_RE.fullmatch(inner):
            f["lang"] = inner
        elif not f["rev"] and REV_RE.fullmatch(inner):
            f["rev"] = inner
        else:
            other.append(tag)
    if lb_title and not f["region"]:
        m = SCENE_REGION_RE.search(TAG_RE.sub("", s))
        if m:
            f["region"] = SCENE_REGIONS[m.group(1) or m.group(2)]
    f["tags"] = " ".join(other)
    f["lbname"] = lb_name or f["title"]
    return f


def render_name(template, fields):
    """Fill template; empty () / [] are dropped and characters other filesystems reject are cleaned out."""
    unknown = set(re.findall(r"\{(\w*)\}", template)) - fields.keys()
    if unknown:
        raise ValueError("unknown field " + ", ".join("{%s}" % u for u in sorted(unknown)))
    out = re.sub(r"\{(\w+)\}", lambda m: fields[m.group(1)], template)
    out = re.sub(r"\(\s*\)|\[\s*\]", "", out)
    out = re.sub(r"\s*:\s*", " - ", out).replace("/", "-")  # Fate/Unlimited Codes -> Fate-Unlimited Codes
    out = re.sub(r'[<>"\\|?*\x00-\x1f]', "", out)
    return re.sub(r"^[\s-]+|[\s-]+$", "", " ".join(out.split()))


# arcade systems whose emulators look games up by ROM set name, so their files must keep the names they have
ARCADE_SYSTEMS = romimport.ARCADE


def plan_renames(units, template):
    """units: [(key, [paths], LaunchBox name or None, use it as {title})] -> rows {key, old, new, status}; status
    is "rename", "same", or why it's skipped. A conflict anywhere in a multi-file game skips the whole game."""
    rows = []
    for key, paths, lb_name, lb_title in units:
        for p in paths:
            name = os.path.basename(p)
            row = {"key": key, "old": p, "new": p, "status": "same"}
            rows.append(row)
            if name.lower().endswith(PARTIAL_EXT):
                row["status"] = "partial download"
                continue
            stem, ext = split_ext(name)
            parts = "".join(" " + m.strip() for m in PART_RE.findall(stem))
            try:
                base = render_name(template, name_fields(PART_RE.sub("", stem).strip(), lb_name, lb_title))
            except ValueError as e:
                row["status"] = str(e)
                continue
            if not base:
                row["status"] = "empty name"
                continue
            if WIN_RESERVED_RE.fullmatch(base) or (not ext and base.endswith(".")):
                row["status"] = "name Windows can't use"  # also on Linux: the drive may be shared with Windows
                continue
            row["new"] = os.path.join(os.path.dirname(p), base + parts + ext)
            if is_windows() and len(os.path.abspath(row["new"])) > WIN_MAX_PATH:
                row["status"] = "path too long for Windows"
                continue
            if row["new"] != p:
                row["status"] = "rename"
    sources = {os.path.normcase(r["old"]) for r in rows if r["status"] == "rename"}
    seen = Counter(os.path.normcase(r["new"]).lower() for r in rows)
    for r in rows:
        if r["status"] != "rename":
            continue
        if seen[os.path.normcase(r["new"]).lower()] > 1:
            r["status"] = "two games get this name"
        elif os.path.lexists(r["new"]) and os.path.normcase(r["new"]) not in sources and \
                not os.path.samefile(r["new"], r["old"]):
            r["status"] = "name already taken"
    bad = {r["key"] for r in rows if r["status"] not in ("rename", "same")}
    for r in rows:
        if r["key"] in bad and r["status"] == "rename":
            r["status"] = "skipped with the rest of its game"
    return rows


def apply_renames(pairs):
    """Rename [(old, new)] in two steps through hidden temp names, so swaps and chains can't collide.
    -> (pairs done, error messages). Then fixes .cue/.m3u references to the renamed files."""
    staged, failed = [], []
    for i, (old, new) in enumerate(pairs):
        tmp = os.path.join(os.path.dirname(old), f".retroshelf-rename-{os.getpid()}-{i}")
        try:
            os.rename(old, tmp)
            staged.append((old, new, tmp))
        except OSError as e:
            failed.append(f"{os.path.basename(old)}: {e}")
    done = []
    for old, new, tmp in staged:
        try:
            if os.path.lexists(new):
                raise OSError("name already taken")
            os.rename(tmp, new)
            done.append([old, new])
        except OSError as e:
            failed.append(f"{os.path.basename(old)}: {e}")
            try:
                os.rename(tmp, old)
            except OSError as e2:
                failed.append(f"{os.path.basename(old)} is left as {tmp}: {e2}")
    by_name = {os.path.basename(o): os.path.basename(n) for o, n in done}
    for _, new in done:
        if new.lower().endswith(REF_EXT):
            try:
                fix_refs(new, by_name)
            except OSError as e:
                failed.append(f"{os.path.basename(new)} (updating file names inside): {e}")
    return done, failed


def fix_refs(path, by_name):
    """Swap old file names for new ones inside a .cue / .m3u / .gdi."""
    if not by_name:
        return
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
        text = f.read()
    rx = re.compile("|".join(re.escape(n) for n in sorted(by_name, key=len, reverse=True)))
    new = rx.sub(lambda m: by_name[m.group(0)], text)
    if new != text:
        with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
            f.write(new)


def wildcard_re(pat, icase):
    if "*" not in pat and "?" not in pat:
        pat = f"*{pat}*"  # plain text means "name contains this"
    rx = re.escape(pat).replace(r"\*", ".*").replace(r"\?", ".")
    return re.compile(rf"^{rx}$", re.IGNORECASE if icase else 0)


def human(n):
    if n >= 1 << 40:
        return f"{n / (1 << 40):.2f} TB"
    if n >= 1073741824:
        return f"{n / 1073741824:.2f} GB"
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, round(n / 1024)) if n else 0} KB"


def dir_size(path):
    total = 0
    for dp, _, fs in os.walk(path):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def read_systeminfo(folder):
    """-> (system name, full name, {game extensions}) from ES-DE's systeminfo.txt; missing parts are None."""
    try:
        with open(os.path.join(folder, "systeminfo.txt"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None, None, None
    name = re.search(r"System name:\s*\n(.*)", text)
    full = re.search(r"Full system name:\s*\n(.*)", text)
    exts = re.search(r"Supported file extensions:\s*\n(.*)", text)
    return (
        name.group(1).strip() if name else None,
        full.group(1).strip() if full else None,
        {e.lower() for e in exts.group(1).split()} if exts else None,
    )


def is_game(entry, exts):
    """Dirs count (ES-DE game folders); files must have a game extension (partial downloads judged by the inner one)."""
    if entry.name.startswith((".", "_")):
        return False
    if entry.is_dir():
        return True
    name = entry.name.lower()
    if name.endswith(PARTIAL_EXT):
        name = os.path.splitext(name)[0]
    ext = os.path.splitext(name)[1]
    return ext in exts if exts else ext not in NON_GAME_EXT


def list_entries(folder, exts=None):
    try:
        return [e for e in os.scandir(folder) if is_game(e, exts)]
    except OSError:
        return []


def valid_exts(folder, system):
    name, _, exts = read_systeminfo(folder)
    return exts if name == system else None


find_gamelist = scraper.find_gamelist


def guess_roms_root(esde_bases=()):
    """The ROMs folder of the RetroDECK / ES-DE on this computer (RetroDECK's config says where its folder went;
    ES-DE's settings, or the portable copies RetroShelf set up, say where its ROMs are), else a usual spot."""
    for p in ([frontend.retrodeck_roms()] + frontend.esde_installs(esde_bases) +
              [os.path.join(APP_DIR, "..", "retrodeck", "roms"), os.path.join(APP_DIR, "..", "roms"),
               os.path.join(APP_DIR, "..", "..", "roms"), os.path.expanduser("~/retrodeck/roms"),
               os.path.expanduser("~/ROMs")]):
        if p and os.path.isdir(p):
            return os.path.realpath(p)
    return ""


class App:
    def __init__(self, root):
        self.root = root
        root.title("RetroShelf")
        self.icons, self.big_icon = [], None
        try:  # default=True: dialogs and the NoPayStation window get it too
            self.icons = [tk.PhotoImage(file=os.path.join(APP_DIR, "assets", f"icon-{n}.png")) for n in (256, 64, 32)]
            root.iconphoto(True, *self.icons)
            self.big_icon = self.icons[0].subsample(2)  # 128 px, for the details panel's welcome
        except tk.TclError:
            pass
        # 1600x950 at 96 dpi, scaled for high-DPI screens and kept on screen (Steam Deck: 1280x800)
        scale = max(1.0, root.winfo_fpixels("1i") / 96)
        root.geometry(f"{min(round(1600 * scale), root.winfo_screenwidth())}x"
                      f"{min(round(950 * scale), root.winfo_screenheight() - round(60 * scale))}")

        self.cfg = {"roms_root": "", "holding_root": "", "system": "", "platform_overrides": {}, "theme": "dark",
                    "region_priority": DEFAULT_PRIORITY, "rename_templates": {}, "check_updates": True,
                    "system_state": {}, "show_details": True, "emulator_dirs": {}, "esde_bases": [],
                    "setup_offered": False, "import_dir": "", "import_delete_originals": False,
                    "play_videos": True, "stream_videos": False}
        try:
            with open(CONFIG, encoding="utf-8") as f:
                self.cfg.update(json.load(f))
        except ValueError:  # unreadable: set it aside instead of overwriting it with defaults on the next save
            try:
                os.replace(CONFIG, CONFIG + ".bad")
            except OSError:
                pass
        except OSError:
            pass
        if not self.cfg["roms_root"] or not os.path.isdir(self.cfg["roms_root"]):
            self.cfg["roms_root"] = guess_roms_root(self.cfg["esde_bases"])
        nps.emulator_dirs.update(self.cfg["emulator_dirs"])  # Windows: RPCS3 / Vita3K folders picked by hand
        details.PLAY_VIDEOS = bool(self.cfg["play_videos"])
        details.STREAM_VIDEOS = bool(self.cfg["stream_videos"])

        self.units = {}          # key -> {"paths": [abs path], "size": int}
        self.file_to_unit = {}
        self.ratings = {}        # key -> lb game dict
        self.lb_ids = {}         # key -> LaunchBox id for any match (fuzzy too), for the details panel
        self.detail_panels = []  # DetailsPanel widgets to restyle on theme changes
        self._lb_details = {}    # platform -> LaunchBox details (descriptions etc.), loaded on first use
        self.lb_kind = {}        # key -> "exact" | "fuzzy" | "manual" (manual may also mean "no match")
        self.played = set()
        self.preset_hits = {}
        self.manual = {}
        self.after_id = None
        self.sort_by = ("#0", False)
        self.to_move, self.kept, self.why = [], [], {}
        self.dupes_key = None

        sv_ttk.set_theme(self.cfg["theme"])
        self._fonts()
        self._build()
        self.apply_theme()
        self.toast = ui.Toaster(root, lambda: self.colors).show
        root.bind_class("Toplevel", "<Map>", self._center_dialog, add="+")
        self.load_roms_root(self.cfg["roms_root"])
        root.protocol("WM_DELETE_WINDOW", self._close)
        if not self.cfg["roms_root"] and not self.cfg["setup_offered"]:  # no library anywhere: offer to set one up
            root.after(600, lambda: setup_gui.open_window(self))
        if self.cfg["roms_root"] and import_gui.waiting(self):
            root.after(1200, lambda: self.toast(f"{import_gui.waiting(self)} waiting in the import folder: "
                                                "press Import ROMs to file them."))
        if self.cfg["check_updates"]:
            root.after(1500, lambda: self.check_updates(quiet=True))

    # ---------- look ----------
    def _fonts(self):
        fams = set(tkfont.families())
        ui = next((f for f in UI_FONTS if f in fams), None)
        self.mono = next((f for f in MONO_FONTS if f in fams), "monospace")
        if ui:
            for name in ("SunValleyCaptionFont", "SunValleyBodyFont", "SunValleyBodyLargeFont", "TkDefaultFont",
                         "TkTextFont", "TkMenuFont", "TkHeadingFont"):
                try:
                    tkfont.nametofont(name).configure(family=ui)
                except tk.TclError:
                    pass
            for name in ("SunValleyBodyStrongFont", "SunValleySubtitleFont", "SunValleyTitleFont"):
                try:
                    tkfont.nametofont(name).configure(family=ui, weight="bold")
                except tk.TclError:
                    pass

    def apply_theme(self):
        theme = self.cfg["theme"]
        sv_ttk.set_theme(theme)
        c = self.colors = PALETTE[theme]
        st = ttk.Style()
        st.configure("Treeview", rowheight=28, indent=0)
        # the theme's own selection colour is nearly the row colour in dark mode; use a clear accent tint
        st.map("Treeview", background=[("selected", c["selrow"])],
               foreground=[("selected", "#ffffff" if theme == "dark" else "#0b1a2b")])
        # flat lists only: drop the expand-arrow slot so first-column text lines up with its heading
        st.layout("Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
            ("Treeitem.image", {"side": "left", "sticky": ""}), ("Treeitem.text", {"sticky": "nswe"})]})])
        st.configure("Treeview.Heading", padding=(HEAD_PAD, 2))
        st.configure("Muted.TLabel", foreground=c["muted"])
        st.configure("Title.TLabel", font="SunValleySubtitleFont")
        st.configure("Section.TLabel", font="SunValleyBodyStrongFont")
        st.configure("Keep.TLabel", font="SunValleyBodyStrongFont", foreground=c["keep"])
        st.configure("Move.TLabel", font="SunValleyBodyStrongFont", foreground=c["move"])
        field = dict(bg=c["field"], fg=c["fg"], selectbackground=c["sel"], selectforeground="#ffffff",
                     relief="flat", borderwidth=0, highlightthickness=1, highlightbackground=c["border"],
                     highlightcolor=c["accent"])
        self.field_style = field
        self.pat_text.configure(insertbackground=c["fg"], padx=8, pady=6, **field)
        self.pat_hint.configure(bg=c["field"], fg=c["muted"])
        self.genre_lb.configure(activestyle="none", **field)
        self.keys.style(c)
        self.region_lb.configure(activestyle="none", **field)
        for tv in (self.keep_tv, self.move_tv):
            tv.tag_configure("odd", background=c["stripe"])
            tv.tag_configure("manual", foreground=c["manual"])
            tv.tag_configure("hover", background=c["hover"])  # configured last, so it wins over "odd"
        menu_colors = dict(background=c["field"], foreground=c["fg"], activebackground=c["sel"],
                           activeforeground="#ffffff", disabledforeground=c["muted"], selectcolor=c["fg"])
        for k, v in menu_colors.items():
            self.root.option_add(f"*Menu.{k}", v)  # right-click menus made later
        for m in self.menus:
            m.configure(relief="flat", borderwidth=0, activeborderwidth=0, **menu_colors)
        self.detail_panels = [p for p in self.detail_panels if p.winfo_exists()]
        for p in self.detail_panels:
            p.restyle(field)
        self.root.configure(bg=ttk.Style().lookup("TFrame", "background"))

    def toggle_theme(self):
        self.cfg["theme"] = "dark" if self.dark_var.get() else "light"
        self.save_cfg()
        self.apply_theme()

    def install_desktop(self):
        try:
            desktop.install()
        except OSError as e:
            messagebox.showerror(f"Couldn't {desktop.menu_label().lower()}", str(e))
            return
        self.help_menu.entryconfig(self._menu_item(self.help_menu, desktop.menu_label()), state="disabled")
        where = "the Start menu" if is_windows() else "your app menu"
        self.toast(f"Added to {where}. If you move the RetroShelf folder, add it again from Help.")

    # ---------- updates ----------
    def check_updates(self, quiet=False):
        """Ask GitHub off the UI thread. quiet (startup): stay silent unless there's an update."""
        if getattr(self, "_checking", False):
            return
        self._checking = True
        item = self._menu_item(self.help_menu, "Check")
        self.help_menu.entryconfig(item, label="Checking for updates…", state="disabled")
        box = queue.Queue()

        def work():
            try:
                box.put(updater.check())
            except Exception as e:
                box.put(e)

        def poll():
            try:
                res = box.get_nowait()
            except queue.Empty:
                self.root.after(200, poll)
                return
            self._checking = False
            self.help_menu.entryconfig(item, label="Check for updates", state="normal")
            if isinstance(res, Exception):
                if not quiet:
                    messagebox.showerror("Couldn't check for updates", str(res))
                return
            if res["behind"] == 0:
                if not quiet:
                    self.toast("You have the latest RetroShelf.")
                return
            # a menu-bar item stays as a reminder after "Later"
            label = "⬆ Update available"
            if self._menu_item(self.menubar, label) is None:
                self.menubar.add_command(label=label, command=lambda: self.update_dialog(res))
            else:
                self.menubar.entryconfig(self._menu_item(self.menubar, label), command=lambda: self.update_dialog(res))
            self.update_dialog(res)

        threading.Thread(target=work, daemon=True).start()
        poll()

    def update_dialog(self, res):
        win = tk.Toplevel(self.root)
        win.title("Update RetroShelf")
        win.transient(self.root)
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        body = ttk.Frame(win, padding=18)
        body.pack(fill="both", expand=True)
        n = res["behind"]
        ttk.Label(body, text=f"RetroShelf {res['tag']} is available" if res["tag"] else
                  "A new version of RetroShelf is available" if n is None else
                  f"{n} new change{'s' if n != 1 else ''} on GitHub", style="Section.TLabel").pack(anchor="w")
        if res["note"]:
            ttk.Label(body, text=res["note"], style="Muted.TLabel", wraplength=520, justify="left").pack(
                anchor="w", pady=(4, 0))
        if res["commits"]:
            box = tk.Text(body, height=min(12, len(res["commits"])), width=70, wrap="word", font=(self.mono, 10))
            box.insert("1.0", "\n".join(f"•  {c}" for c in res["commits"][:40]))
            box.config(state="disabled")
            box.pack(fill="both", expand=True, pady=(10, 0))
        ttk.Label(body, text="Your settings, logs and LaunchBox / NoPayStation data are kept. RetroShelf restarts "
                             "when the update is done.", style="Muted.TLabel", wraplength=520,
                  justify="left").pack(anchor="w", pady=(10, 0))
        auto = tk.BooleanVar(value=self.cfg["check_updates"])

        def set_auto():
            self.cfg["check_updates"] = auto.get()
            self.save_cfg()

        ttk.Checkbutton(body, text="Check for updates when RetroShelf starts", variable=auto,
                        command=set_auto).pack(anchor="w", pady=(10, 0))
        foot = ttk.Frame(body, padding=(0, 14, 0, 0))
        foot.pack(fill="x")
        status = ttk.Label(foot, style="Muted.TLabel")
        status.pack(side="left")
        go = ttk.Button(foot, text="Update and restart", style="Accent.TButton")
        go.pack(side="right")
        later = ttk.Button(foot, text="Later", command=win.destroy)
        later.pack(side="right", padx=(0, 6))

        def start():
            w = getattr(self, "nps_window", None)
            if w and w.running:
                messagebox.showinfo("Downloads running", "Wait for the NoPayStation queue to finish (or stop it) "
                                                         "before updating.", parent=win)
                return
            go.config(state="disabled", text="Updating…")
            later.config(state="disabled")
            box = queue.Queue()

            def work():
                try:
                    box.put(updater.apply(res["tag"]))
                except Exception as e:
                    box.put(e)

            def poll():
                try:
                    res2 = box.get_nowait()
                except queue.Empty:
                    win.after(200, poll)
                    return
                if isinstance(res2, Exception):
                    go.config(state="normal", text="Update and restart")
                    later.config(state="normal")
                    messagebox.showerror("Update failed", str(res2), parent=win)
                    return
                status.config(text="Restarting…")
                self.save_state()
                self.save_cfg()
                win.after(300, updater.restart)

            threading.Thread(target=work, daemon=True).start()
            poll()

        go.config(command=start)
        win.bind("<Escape>", lambda e: win.destroy() if str(later.cget("state")) == "normal" else None)

    # ---------- config ----------
    def save_cfg(self):
        try:
            write_json(CONFIG, self.cfg, indent=1)
        except OSError:
            pass

    def holding_root(self):
        return self.cfg["holding_root"] or os.path.join(os.path.dirname(os.path.normpath(self.cfg["roms_root"])),
                                                        "pruned")

    # ---------- UI ----------
    def _build(self):
        self._build_menu()
        outer = ttk.Frame(self.root, padding=(16, 10, 16, 8))
        outer.pack(fill="both", expand=True)

        # source bar: folder, system, LaunchBox platform; drive space on the right
        bar = ttk.Frame(outer)
        bar.pack(fill="x")
        bar.columnconfigure(1, weight=1)
        ttk.Label(bar, text="ROMs").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.roms_var = tk.StringVar()
        self.roms_entry = ttk.Entry(bar, textvariable=self.roms_var, state="readonly", width=12)
        self.roms_entry.grid(row=0, column=1, sticky="ew")
        self.roms_entry.bind("<Double-Button-1>", lambda e: self.browse_roms())
        pick = ttk.Button(bar, text="…", width=3, command=self.browse_roms)
        pick.grid(row=0, column=2, padx=(4, 16))
        ui.Tooltip(pick, "Choose your ROMs folder (the one with a folder per system)")
        ui.Tooltip(self.roms_entry, lambda: self.roms_var.get())
        ttk.Label(bar, text="System").grid(row=0, column=3, sticky="w", padx=(0, 8))
        self.system_var = tk.StringVar()
        self.system_cb = ttk.Combobox(bar, textvariable=self.system_var, state="readonly", width=26)
        self.system_cb.grid(row=0, column=4)
        self.system_cb.bind("<<ComboboxSelected>>", lambda e: self.load_system(self.system_codes[self.system_cb.current()]))
        self.sys_info = ttk.Label(bar, style="Move.TLabel", cursor="hand2")  # ⚠ when something's off; click it
        self.sys_info.grid(row=0, column=5, padx=(6, 0))
        self.sys_warning = ""
        self.sys_info.bind("<Button-1>", lambda e: self.sys_warning and messagebox.showinfo("System", self.sys_warning))
        ui.Tooltip(self.sys_info, lambda: self.sys_warning)
        ttk.Label(bar, text="LaunchBox").grid(row=0, column=6, sticky="w", padx=(16, 8))
        self.platform_var = tk.StringVar()
        self.platform_cb = ttk.Combobox(bar, textvariable=self.platform_var, state="readonly", width=20)
        self.platform_cb.grid(row=0, column=7)
        self.platform_cb.bind("<<ComboboxSelected>>", lambda e: self.set_platform())
        self.disk_lbl = ttk.Label(bar, style="Muted.TLabel")
        self.disk_lbl.grid(row=0, column=8, padx=(16, 8))
        self.disk_bar = ttk.Progressbar(bar, length=80, mode="determinate", maximum=100)
        self.disk_bar.grid(row=0, column=9)
        for w in (self.disk_lbl, self.disk_bar):
            ui.Tooltip(w, self._disk_tip)
        imp = ttk.Button(bar, text="Import ROMs…", command=lambda: import_gui.open_window(self))
        imp.grid(row=0, column=10, padx=(16, 0))
        ui.Tooltip(imp, "Add games: archives (zip, 7z, rar), disc images and ROMs are checked, unpacked and filed "
                        "into the right system folder")
        self.root.bind("<Control-i>", lambda e: None if isinstance(e.widget, tk.Text) else import_gui.open_window(self))

        # filter cards, with the details panel beside them
        top = ttk.Frame(outer, padding=(0, 10, 0, 0))
        top.pack(fill="x")

        # filters live in tabs (one group at a time fits even a Steam Deck screen next to the details panel);
        # tab names count what's switched on, so nothing active is hidden
        self.filter_tabs = nb = ttk.Notebook(top)
        nb.pack(side="right", fill="y")  # details takes the rest of the row on the left
        presets = ttk.Frame(nb, padding=(12, 8))
        pcol = ttk.Frame(presets)
        pcol.pack(side="left", fill="y", anchor="n")
        self.preset_vars = {}
        for name in list(PRESETS) + ["Partial downloads (.part)"]:
            v = tk.BooleanVar(value=False)
            ttk.Checkbutton(pcol, text=PRESET_LABELS.get(name, name), variable=v,
                            command=self.refresh).pack(anchor="w", pady=0)
            self.preset_vars[name] = v
            if name == DUPES:
                prow = ttk.Frame(pcol)
                prow.pack(fill="x", padx=(28, 0), pady=(0, 2))
                self.priority = [p.strip() for p in self.cfg["region_priority"].split(",") if p.strip()]
                self.prio_lbl = ttk.Label(prow, style="Muted.TLabel")
                self.prio_lbl.pack(side="left")
                ttk.Button(prow, text="Edit…", command=self.edit_priority).pack(side="right", padx=(6, 0))
                self._show_priority()
        ttk.Separator(presets, orient="vertical").pack(side="left", fill="y", padx=12)
        rat = ttk.Frame(presets)
        rat.pack(side="left", fill="y", anchor="n")
        row = ttk.Frame(rat)
        row.pack(anchor="w", pady=1)
        self.use_rating = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Rating below", variable=self.use_rating, command=self.refresh).pack(side="left")
        self.rating_max = tk.DoubleVar(value=2.5)
        ttk.Spinbox(row, from_=0, to=5, increment=0.25, width=3, textvariable=self.rating_max,
                    command=self.refresh).pack(side="left", padx=6)
        ttk.Label(row, text="/ 5").pack(side="left")
        row2 = ttk.Frame(rat)
        row2.pack(anchor="w", pady=1)
        ttk.Label(row2, text="if votes ≥", style="Muted.TLabel").pack(side="left", padx=(28, 0))
        self.min_votes = tk.IntVar(value=3)
        ttk.Spinbox(row2, from_=1, to=500, increment=1, width=3, textvariable=self.min_votes,
                    command=self.refresh).pack(side="left", padx=6)
        for var in (self.rating_max, self.min_votes):
            var.trace_add("write", lambda *_: self._debounce())
        self.use_unrated = tk.BooleanVar(value=False)
        ttk.Checkbutton(rat, text="Unrated or unmatched", variable=self.use_unrated,
                        command=self.refresh).pack(anchor="w", pady=1)
        self.rat_info = ttk.Label(rat, style="Muted.TLabel")
        self.rat_info.pack(anchor="w", pady=(2, 0))
        self.protect_played = tk.BooleanVar(value=True)
        self.played_cb = ttk.Checkbutton(rat, text="Protect played games", style="Switch.TCheckbutton",
                                         variable=self.protect_played, command=self.refresh)
        self.played_cb.pack(anchor="w", side="bottom", pady=(6, 2))
        nb.add(presets, text="Presets & ratings")

        gen = ttk.Frame(nb, padding=(12, 8))
        ttk.Label(gen, text="Games in the selected genres move. Ctrl / Shift-click for several.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        gf = ttk.Frame(gen)
        gf.pack(fill="both", expand=True)
        self.genre_lb = tk.Listbox(gf, selectmode="extended", height=6, exportselection=False, width=30,
                                   font="SunValleyBodyFont")
        gsb = ttk.Scrollbar(gf, orient="vertical", command=self.genre_lb.yview)
        self.genre_lb.configure(yscrollcommand=gsb.set)
        self.genre_lb.pack(side="left", fill="both", expand=True)
        gsb.pack(side="right", fill="y")
        self.genre_lb.bind("<<ListboxSelect>>", lambda e: self.refresh())
        self.genre_names = []
        nb.add(gen, text="Genres")

        reg = ttk.Frame(nb, padding=(12, 8))
        rtop = ttk.Frame(reg)
        rtop.pack(fill="x", pady=(0, 4))
        self.region_mode = tk.StringVar(value=REGION_MODES[0])
        mode_cb = ttk.Combobox(rtop, textvariable=self.region_mode, values=REGION_MODES, state="readonly",
                               width=17)
        mode_cb.pack(side="left")
        mode_cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Label(rtop, text="  the regions picked below", style="Muted.TLabel").pack(side="left")
        rf = ttk.Frame(reg)
        rf.pack(fill="both", expand=True)
        self.region_lb = tk.Listbox(rf, selectmode="extended", height=5, exportselection=False, width=30,
                                    font="SunValleyBodyFont")
        rsb = ttk.Scrollbar(rf, orient="vertical", command=self.region_lb.yview)
        self.region_lb.configure(yscrollcommand=rsb.set)
        self.region_lb.pack(side="left", fill="both", expand=True)
        rsb.pack(side="right", fill="y")
        self.region_lb.bind("<<ListboxSelect>>", lambda e: self.refresh())
        self.region_names = []
        nb.add(reg, text="Regions")

        pat = ttk.Frame(nb, padding=(12, 8))
        prow = ttk.Frame(pat)
        prow.pack(fill="x", pady=(0, 4))
        ttk.Label(prow, text="One rule per line", style="Muted.TLabel").pack(side="left")
        ttk.Button(prow, text="Help", command=self.pattern_help).pack(side="right")
        self.icase = tk.BooleanVar(value=True)
        ttk.Checkbutton(prow, text="Ignore case", variable=self.icase, command=self.refresh).pack(side="right",
                                                                                                padx=(0, 8))
        self.pat_text = tk.Text(pat, height=5, width=30, font=(self.mono, 10), undo=True)
        self.pat_text.pack(fill="both", expand=True)
        self.pat_text.bind("<<Modified>>", self._on_modified)
        self.pat_hint = tk.Label(self.pat_text, text=PATTERN_EXAMPLES, justify="left", anchor="nw",
                                 font=(self.mono, 10))
        self.pat_hint.bind("<Button-1>", lambda e: self.pat_text.focus_set())
        self._toggle_hint()
        nb.add(pat, text="Patterns")
        self.filter_pages = [presets, gen, reg, pat]

        self.details_card = ttk.LabelFrame(top, text="Details", padding=(10, 6))
        self.details = details.DetailsPanel(self.details_card, wide=True, padding=0)
        self.details.pack(fill="both", expand=True)
        self.detail_panels.append(self.details)
        if self.cfg["show_details"]:
            self.details_card.pack(side="left", fill="both", expand=True, padx=(0, 10))
        else:
            nb.pack_configure(side="left")

        # search
        flt = ttk.Frame(outer, padding=(0, 10, 0, 0))
        flt.pack(fill="x")
        ttk.Label(flt, text="Search").pack(side="left")
        self.view_filter = tk.StringVar()
        self.view_filter.trace_add("write", lambda *_: self.render())
        self.search_entry = ttk.Entry(flt, textvariable=self.view_filter)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(8, 16))
        reset = ttk.Button(flt, text="Reset flips", command=self.reset_manual)
        reset.pack(side="left")
        ui.Tooltip(reset, "Undo every double-click flip on this system")

        # footer: status left, move controls right (packed before the panes so it never gets squeezed out)
        foot = ttk.Frame(outer, padding=(0, 10, 0, 0))
        foot.pack(side="bottom", fill="x")
        self.move_btn = ttk.Button(foot, text="Move files", style="Accent.TButton", command=self.execute)
        self.move_btn.pack(side="right")
        ttk.Button(foot, text="Change…", command=self.browse_holding).pack(side="right", padx=(0, 16))
        self.hold_lbl = ttk.Label(foot, style="Muted.TLabel")
        self.hold_lbl.pack(side="right", padx=(0, 6))
        ui.Tooltip(self.hold_lbl, lambda: f"Holding folder: {self.holding_root()}\nMoved games wait here until you "
                                          "delete them (Library → Holding folder…)")
        self.dest = tk.StringVar(value=DESTS[0])
        ttk.Combobox(foot, textvariable=self.dest, values=DESTS, state="readonly", width=17).pack(side="right", padx=(0, 6))
        ttk.Label(foot, text="Move to").pack(side="right", padx=(0, 6))
        self.status = ttk.Label(foot, style="Muted.TLabel", anchor="w")
        self.status.pack(side="left", fill="x", expand=True)

        panes = ttk.PanedWindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=(10, 0))
        self.keep_lbl, self.keep_tv = self._pane(panes, "Keep.TLabel")
        self.keep_tv.configure(displaycolumns=("region", "rating", "genre", "size"))  # "why" only matters for moves
        self.move_lbl, self.move_tv = self._pane(panes, "Move.TLabel", pad=(8, 0))
        self.keep_tv.bind("<Double-Button-1>", lambda e: self.flip(self.keep_tv, True))
        self.move_tv.bind("<Double-Button-1>", lambda e: self.flip(self.move_tv, False))
        for tv in (self.keep_tv, self.move_tv):
            tv.bind("<<TreeviewSelect>>", lambda e, tv=tv: self._show_selected(tv))
            tv.bind("<Button-3>", lambda e, tv=tv: self._row_menu(tv, e))
        self.keys = listkeys.PaneKeys(self)  # arrows, Space marks, → / ← flip, Ctrl+Z, type to jump (see there)
        self.root.bind("<Control-z>", lambda e: None if isinstance(e.widget, (tk.Text, ttk.Entry)) else self.keys.undo())
        self.root.bind("<Control-r>", lambda e: self.review())
        self.root.bind("<F5>", lambda e: self.rescan())
        self.root.bind("<Control-f>", lambda e: (self.search_entry.focus_set(), "break")[1])

    def _build_menu(self):
        """Things you do now and then live in the menu bar, so the window can give its height to the tables."""
        mb = self.menubar = tk.Menu(self.root, tearoff=0)
        lib = tk.Menu(mb, tearoff=0)
        lib.add_command(label="Import ROMs…", accelerator="Ctrl+I", command=lambda: import_gui.open_window(self))
        lib.add_separator()
        lib.add_command(label="Change ROMs folder…", command=self.browse_roms)
        lib.add_command(label="Rescan", accelerator="F5", command=self.rescan)
        lib.add_separator()
        lib.add_command(label="Holding folder…", command=self.holding_dialog)
        lib.add_command(label="Restore a move…", command=self.restore_dialog)
        lib.add_command(label="Change holding folder…", command=self.browse_holding)
        lib.add_separator()
        lib.add_command(label="Export move list…", command=self.export)
        mb.add_cascade(label="Library", menu=lib)
        tools = self.tools_menu = tk.Menu(mb, tearoff=0)
        tools.add_command(label=setup_gui.title() + "…", command=lambda: setup_gui.open_window(self))
        tools.add_separator()
        tools.add_command(label="Scrape metadata…", command=self.scrape_dialog)
        tools.add_command(label="Rename files…", command=self.rename_dialog)
        tools.add_command(label="NoPayStation…", command=lambda: nps_gui.open_window(self))
        tools.add_command(label="Homebrew Hub…", command=lambda: homebrew_gui.open_window(self))
        tools.add_command(label="itch.io homebrew…", command=lambda: itch_gui.open_window(self))
        tools.add_command(label="PDRoms homebrew…", command=lambda: pdroms_gui.open_window(self))
        tools.add_command(label="Free arcade games (MAMEDEV)…", command=lambda: mamedev_gui.open_window(self))
        tools.add_separator()
        tools.add_command(label="Download LaunchBox data", command=self.update_lb)
        mb.add_cascade(label="Tools", menu=tools)
        view = tk.Menu(mb, tearoff=0)
        self.dark_var = tk.BooleanVar(value=self.cfg["theme"] == "dark")
        view.add_checkbutton(label="Dark mode", variable=self.dark_var, command=self.toggle_theme)
        self.details_var = tk.BooleanVar(value=self.cfg["show_details"])
        view.add_checkbutton(label="Details panel", variable=self.details_var, command=self.toggle_details)
        self.videos_var = tk.BooleanVar(value=self.cfg["play_videos"])
        view.add_checkbutton(label="Play gameplay videos", variable=self.videos_var, command=self.toggle_videos)
        self.stream_var = tk.BooleanVar(value=self.cfg["stream_videos"])
        view.add_checkbutton(label="   … and stream from YouTube when there's no clip", variable=self.stream_var,
                             command=self.toggle_streams)
        view.add_separator()
        view.add_command(label="Review one at a time…", accelerator="Ctrl+R", command=self.review)
        mb.add_cascade(label="View", menu=view)
        hlp = self.help_menu = tk.Menu(mb, tearoff=0)
        hlp.add_command(label="Keyboard shortcuts", command=self.keys_help)
        hlp.add_command(label="Name pattern help", command=self.pattern_help)
        hlp.add_separator()
        hlp.add_command(label="Check for updates", command=self.check_updates)
        hlp.add_command(label=desktop.menu_label(), command=self.install_desktop,
                        state="disabled" if desktop.is_installed() else "normal")
        mb.add_cascade(label="Help", menu=hlp)
        self.root.config(menu=mb)
        self.menus = [mb, lib, tools, view, hlp]

    def _menu_item(self, menu, label):
        """Index of a menu entry by its label (labels change, e.g. Download/Update LaunchBox data)."""
        for i in range(menu.index("end") + 1):
            if menu.type(i) != "separator" and menu.entrycget(i, "label").startswith(label):
                return i
        return None

    def _pane(self, panes, label_style, pad=(0, 8)):
        f = ttk.Frame(panes, padding=(pad[0], 0, pad[1], 0))
        lbl = ttk.Label(f, style=label_style)
        lbl.pack(anchor="w", pady=(0, 6))
        inner = ttk.Frame(f)
        inner.pack(fill="both", expand=True)
        tv = ttk.Treeview(inner, columns=("why", "region", "rating", "genre", "size"), selectmode="extended")
        anchors = {"#0": "w", "why": "w", "region": "w", "rating": "center", "genre": "w", "size": "e"}
        for col, text in (("#0", "Game"), ("why", "Why"), ("region", "Region"), ("rating", "Rating"),
                          ("genre", "Genre"), ("size", "Size")):
            tv.heading(col, text=text, anchor=anchors[col], command=lambda c=col: self.sort(c))
        tv.column("#0", width=210, minwidth=110, stretch=True)
        tv.column("why", width=150, minwidth=60, stretch=True)
        tv.column("region", width=95, minwidth=60, stretch=False)
        tv.column("rating", width=126, minwidth=110, stretch=False, anchor="center")
        tv.column("genre", width=112, minwidth=60, stretch=False)
        tv.column("size", width=80, minwidth=60, stretch=False, anchor="e")
        sb = ttk.Scrollbar(inner, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tv.empty = ttk.Label(inner, style="Muted.TLabel", justify="center", anchor="center")  # shown when no rows
        tv.hover = None
        tv.bind("<Motion>", lambda e: self._hover(tv, tv.identify_row(e.y)))
        tv.bind("<Leave>", lambda e: self._hover(tv, None))
        panes.add(f, weight=1)
        return lbl, tv

    def _hover(self, tv, row):
        if row == tv.hover:
            return
        for r, on in ((tv.hover, False), (row, True)):
            if r and tv.exists(r):
                tags = [t for t in tv.item(r, "tags") if t != "hover"] + (["hover"] if on else [])
                tv.item(r, tags=tags)
        tv.hover = row

    def _on_modified(self, _):
        self.pat_text.edit_modified(False)
        self._toggle_hint()
        self._debounce()

    def _toggle_hint(self):
        if self.pat_text.get("1.0", "end").strip():
            self.pat_hint.place_forget()
        else:
            self.pat_hint.place(x=8, y=6)

    def pattern_help(self):
        win = tk.Toplevel(self.root)
        win.title("Name pattern syntax")
        win.transient(self.root)
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        body = ttk.Frame(win, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Name patterns", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(body, text="Each line is one rule, checked against every game's file name.",
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 12))
        for i, (example, meaning) in enumerate(PATTERN_HELP):
            ttk.Label(body, text=example, font=(self.mono, 10)).grid(row=i + 2, column=0, sticky="nw", padx=(0, 18),
                                                                     pady=3)
            ttk.Label(body, text=meaning, wraplength=380, justify="left").grid(row=i + 2, column=1, sticky="nw",
                                                                              pady=3)
        notes = ttk.Label(body, text=PATTERN_NOTES, style="Muted.TLabel", wraplength=560, justify="left")
        notes.grid(row=len(PATTERN_HELP) + 2, column=0, columnspan=2, sticky="w", pady=(14, 0))
        ttk.Button(body, text="Close", style="Accent.TButton", command=win.destroy).grid(
            row=len(PATTERN_HELP) + 3, column=1, sticky="e", pady=(16, 0))
        win.bind("<Escape>", lambda e: win.destroy())

    def keys_help(self):
        win = tk.Toplevel(self.root)
        win.title("Keyboard shortcuts")
        win.transient(self.root)
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        body = ttk.Frame(win, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Keeping and Moving lists", style="Section.TLabel").grid(row=0, column=0, columnspan=2,
                                                                                    sticky="w", pady=(0, 10))
        for i, (keys, meaning) in enumerate(listkeys.HELP):
            ttk.Label(body, text=keys, font=(self.mono, 10)).grid(row=i + 1, column=0, sticky="nw", padx=(0, 18),
                                                                  pady=3)
            ttk.Label(body, text=meaning, wraplength=420, justify="left").grid(row=i + 1, column=1, sticky="nw",
                                                                              pady=3)
        ttk.Label(body, text="Review (Ctrl+R): K keep  ·  M move  ·  S or → skip  ·  ← back  ·  Backspace undo  ·  "
                             "Esc close", style="Muted.TLabel", wraplength=600, justify="left").grid(
            row=len(listkeys.HELP) + 1, column=0, columnspan=2, sticky="w", pady=(14, 0))
        ttk.Button(body, text="Close", style="Accent.TButton", command=win.destroy).grid(
            row=len(listkeys.HELP) + 2, column=1, sticky="e", pady=(16, 0))
        win.bind("<Escape>", lambda e: win.destroy())

    # ---------- region priority ----------
    def _show_priority(self):
        shown = " › ".join(self.priority[:2]) + (" …" if len(self.priority) > 2 else "")
        self.prio_lbl.config(text=f"Prefer {shown}")

    def set_priority(self, order):
        self.priority = list(order)
        self.cfg["region_priority"] = ", ".join(self.priority)
        self.save_cfg()
        self._show_priority()
        self.refresh()

    def dupes_priority(self, sel_regions, keep_only):
        """Priority for picking the copy to keep, adjusted so it never picks a copy the Regions filter will move."""
        base = [p.lower() for p in self.priority]
        if not sel_regions:
            return base
        sel = [r.lower() for r in sel_regions]
        present = [r.lower() for r in self.region_names]
        rest = [r for r in base if r not in sel] + [r for r in present if r not in base and r not in sel]
        chosen = [r for r in base if r in sel] + [r for r in sel if r not in base]
        return chosen + rest if keep_only else rest + chosen

    def edit_priority(self):
        present = [r for r in self.region_names if r != "(none)"]
        order = [p for p in self.priority if p in present] + [r for r in present if r not in self.priority]
        order += [p for p in self.priority if p not in order]  # keep saved regions this console lacks

        win = tk.Toplevel(self.root)
        win.title("Region priority")
        win.transient(self.root)
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        body = ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Keep the highest region a game has", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text="Drag to reorder, or use the buttons. Top = most preferred.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 10))
        mid = ttk.Frame(body)
        mid.pack(fill="both", expand=True)
        lb_ = tk.Listbox(mid, height=min(max(len(order), 6), 16), width=26, exportselection=False,
                         font="SunValleyBodyFont", activestyle="none", **self.field_style)
        lb_.pack(side="left", fill="both", expand=True)
        counts = {r: self.region_lb.get(i) for i, r in enumerate(self.region_names)}

        def fill(sel=None):
            lb_.delete(0, "end")
            for i, r in enumerate(order):
                lb_.insert("end", f"{i + 1}.  {counts.get(r, r + ' (0 here)')}")
            if sel is not None:
                lb_.selection_set(sel)
                lb_.see(sel)

        def move(delta=None, to=None):
            sel = lb_.curselection()
            if not sel:
                return
            i = sel[0]
            j = to if to is not None else max(0, min(len(order) - 1, i + delta))
            order.insert(j, order.pop(i))
            fill(j)

        drag = {"i": None}
        lb_.bind("<Button-1>", lambda e: drag.update(i=lb_.nearest(e.y)))

        def on_drag(e):
            j = lb_.nearest(e.y)
            if drag["i"] is not None and j != drag["i"]:
                order.insert(j, order.pop(drag["i"]))
                drag["i"] = j
                fill(j)
        lb_.bind("<B1-Motion>", on_drag)

        btns = ttk.Frame(mid, padding=(10, 0, 0, 0))
        btns.pack(side="left", fill="y")
        ttk.Button(btns, text="Top", width=8, command=lambda: move(to=0)).pack(pady=(0, 4))
        ttk.Button(btns, text="Up", width=8, command=lambda: move(-1)).pack(pady=(0, 4))
        ttk.Button(btns, text="Down", width=8, command=lambda: move(1)).pack(pady=(0, 4))
        ttk.Button(btns, text="Bottom", width=8, command=lambda: move(to=len(order) - 1)).pack(pady=(0, 4))

        def reset():
            default = [p.strip() for p in DEFAULT_PRIORITY.split(",")]
            order[:] = [p for p in default if p in order] + [r for r in order if r not in default]
            fill(0)

        def apply():
            self.set_priority(order)
            win.destroy()

        foot = ttk.Frame(body, padding=(0, 14, 0, 0))
        foot.pack(fill="x")
        ttk.Button(foot, text="Reset to default", command=reset).pack(side="left")
        ttk.Button(foot, text="Apply", style="Accent.TButton", command=apply).pack(side="right")
        ttk.Button(foot, text="Cancel", command=win.destroy).pack(side="right", padx=(0, 6))
        fill(0)
        win.grab_set()

    def _debounce(self):
        if self.after_id:
            self.root.after_cancel(self.after_id)
        self.after_id = self.root.after(300, self.refresh)

    # ---------- roms root / system ----------
    def browse_roms(self):
        path = dialogs.ask_directory(self.root, initialdir=self.cfg["roms_root"] or os.path.expanduser("~"),
                                     title="Pick the roms folder (the one containing nds/, snes/, …)")
        if path:
            self.load_roms_root(path)

    def browse_holding(self):
        path = dialogs.ask_directory(self.root, initialdir=self.holding_root(), title="Where moved files go")
        if path:
            self.cfg["holding_root"] = path
            self.save_cfg()
            self.show_holding()

    def load_roms_root(self, path):
        self.roms_var.set(path)
        self.roms_entry.xview_moveto(1)
        self.system_codes, labels = [], []
        if path and os.path.isdir(path):
            self.cfg["roms_root"] = path
            self.save_cfg()
            # NoPayStation systems are listed even when their folder is missing; installing creates it
            for d in sorted(set(os.listdir(path)) | set(nps.CONSOLES)):
                full = os.path.join(path, d)
                if d.startswith((".", "_")) or not (os.path.isdir(full) or d in nps.CONSOLES):
                    continue
                n = len(list_entries(full, valid_exts(full, d)))
                if n == 0 and d not in nps.CONSOLES:  # NoPayStation systems stay pickable so they can be filled
                    continue
                name, fullname, _ = read_systeminfo(full)
                self.system_codes.append(d)
                fullname = fullname if name == d and fullname else nps.FULL_NAMES.get(d, "?")
                labels.append(f"{d} — {fullname} ({n})")
        self.system_cb["values"] = labels
        self.show_holding()
        self.show_disk()
        self._merge_old_log()
        if not self.system_codes:
            self.sys_info.config(text="⚠ No games found — pick your ROMs folder")
            return
        sys_code = self.cfg["system"] if self.cfg["system"] in self.system_codes else self.system_codes[0]
        self.load_system(sys_code)

    def load_system(self, system):
        self.save_state()  # the system being left, including edits a pending refresh hasn't seen yet
        self.keys.undo_stack.clear()  # flips belong to the system they were made in
        self.system = system
        self.cfg["system"] = system
        self.save_cfg()
        self.system_cb.current(self.system_codes.index(system))
        self.folder = os.path.join(self.cfg["roms_root"], system)
        name, fullname, exts = read_systeminfo(self.folder)
        self.fullname = fullname if name == system else nps.FULL_NAMES.get(system)
        self.exts = exts if name == system else None
        self.sys_info.config(text="" if name in (None, system) else "⚠")
        self.sys_warning = "" if name in (None, system) else (
            f"This folder's systeminfo.txt is for '{name}', so it's ignored (ES-DE may have written it there).")
        self.root.title(f"RetroShelf — {self.fullname or system}")
        self.tools_menu.entryconfig(self._menu_item(self.tools_menu, "NoPayStation"),
                                    state="normal" if system in nps.CONSOLES else "disabled")
        self.restore_state()
        self._refresh_platform_choices()
        self.rescan()

    def _refresh_platform_choices(self):
        plats = lb.platforms()
        self.platform_cb["values"] = ["(none)"] + plats
        self.platform = lb.resolve_platform(self.system, self.fullname, self.cfg["platform_overrides"])
        self.platform_var.set(self.platform or "(none)")
        self.tools_menu.entryconfig(self._menu_item(self.tools_menu, ("Update", "Download")),
                                    label="Update LaunchBox data" if plats else "Download LaunchBox data")

    def set_platform(self):
        p = self.platform_var.get()
        self.cfg["platform_overrides"][self.system] = "" if p == "(none)" else p
        self.save_cfg()
        self.platform = p if p != "(none)" else None
        self.rescan()

    # ---------- LaunchBox ----------
    def update_lb(self):
        q = queue.Queue()

        def work():
            try:
                lb.update(progress=lambda m: q.put(("msg", m)))
                q.put(("done", None))
            except Exception as e:
                q.put(("done", e))

        def poll():
            try:
                while True:
                    kind, val = q.get_nowait()
                    if kind == "msg":
                        self.status.config(text=val)
                    else:
                        self.tools_menu.entryconfig(self._menu_item(self.tools_menu, ("Update", "Download")),
                                                    state="normal")
                        if val:
                            messagebox.showerror("LaunchBox update failed", str(val))
                        else:
                            self._refresh_platform_choices()
                            self.rescan()
                            self.toast("LaunchBox data is up to date: ratings, genres and scraping are ready.")
                        return
            except queue.Empty:
                self.root.after(200, poll)

        self.tools_menu.entryconfig(self._menu_item(self.tools_menu, ("Update", "Download")), state="disabled")
        threading.Thread(target=work, daemon=True).start()
        poll()

    # ---------- scraper ----------
    def gamelist_path(self):
        return scraper.gamelist_path(self.cfg["roms_root"], self.system)

    def scrape_dialog(self):
        if not self.platform:
            messagebox.showinfo("No LaunchBox platform", "Pick a LaunchBox platform for this system first.")
            return
        if not lb.has_details():
            messagebox.showinfo("Update needed", "Run Tools → Update LaunchBox data once first — the scraper needs "
                                                 "descriptions and image lists that older downloads don't include.")
            return
        selected = set(self.keep_tv.selection()) | set(self.move_tv.selection())
        scopes = [("Keeping list", list(self.kept)), ("All games", list(self.units)),
                  ("Selected rows", [k for k in self.units if k in selected])]

        win = tk.Toplevel(self.root)
        win.title(f"Scrape metadata — {self.system}")
        win.transient(self.root)
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        body = ttk.Frame(win, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"Scrape {self.fullname or self.system} from LaunchBox", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text="Fills gaps: existing images are never replaced, text only if you tick that below, and play counts, "
                             "favorites and hidden flags are left alone.", style="Muted.TLabel",
                  wraplength=520, justify="left").pack(anchor="w", pady=(2, 12))

        scope_box = ttk.LabelFrame(body, text="Games", padding=(12, 8))
        scope_box.pack(fill="x")
        scope = tk.IntVar(value=0)
        for i, (label, keys) in enumerate(scopes):
            linked = sum(k in self.lb_links for k in keys)
            close = sum(k in self.lb_ids and k not in self.lb_links for k in keys)
            ttk.Radiobutton(scope_box, text=f"{label}  —  {len(keys):,} games, {linked:,} matched in LaunchBox"
                                            + (f" (+{close:,} close matches)" if close else ""),
                            variable=scope, value=i, state="normal" if keys else "disabled").pack(anchor="w", pady=1)

        what = ttk.LabelFrame(body, text="What to fill", padding=(12, 8))
        what.pack(fill="x", pady=(10, 0))
        do_text = tk.BooleanVar(value=True)
        ttk.Checkbutton(what, text="Text — name, description, developer, publisher, release date, players, genre, "
                                   "rating", variable=do_text).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        media_vars = {}
        for i, (mtype, (label, _, default)) in enumerate(scraper.MEDIA.items()):
            v = tk.BooleanVar(value=default)
            ttk.Checkbutton(what, text=label, variable=v).grid(row=1 + i // 2, column=i % 2, sticky="w", pady=1,
                                                               padx=(0, 24))
            media_vars[mtype] = v
        rows = 1 + (len(scraper.MEDIA) + 1) // 2
        use_close = tk.BooleanVar(value=False)
        ttk.Checkbutton(what, text="Also scrape close (fuzzy) matches — check them in the details panel first",
                        variable=use_close).grid(row=rows, column=0, columnspan=2, sticky="w", pady=(8, 1))
        overwrite = tk.BooleanVar(value=False)
        ttk.Checkbutton(what, text="Replace existing text with LaunchBox's (dates, descriptions … from other "
                                   "scrapers)", variable=overwrite).grid(row=rows + 1, column=0, columnspan=2,
                                                                         sticky="w", pady=1)

        ttk.Label(body, text="Videos and miximages aren't in LaunchBox's free data. Afterwards, in ES-DE: "
                             "Scraper → Content to scrape → only Videos, and Scraper → Other settings → "
                             "Miximage settings → Offline generator.", style="Muted.TLabel",
                  wraplength=520, justify="left").pack(anchor="w", pady=(10, 0))
        if scraper.es_de_running():
            ttk.Label(body, text="⚠ RetroDECK / ES-DE is running. It rewrites gamelist.xml when it quits, so text "
                                 "can't be saved until you close it. Images are fine to download now.",
                      style="Move.TLabel", wraplength=520, justify="left").pack(anchor="w", pady=(10, 0))

        bar = ttk.Progressbar(body, mode="determinate")
        bar.pack(fill="x", pady=(14, 4))
        status = ttk.Label(body, text="", style="Muted.TLabel", wraplength=520, justify="left")
        status.pack(anchor="w")

        foot = ttk.Frame(body, padding=(0, 12, 0, 0))
        foot.pack(fill="x")
        state = {"cancel": False, "running": False}
        start_btn = ttk.Button(foot, text="Start", style="Accent.TButton")
        start_btn.pack(side="right")
        close_btn = ttk.Button(foot, text="Close", command=win.destroy)
        close_btn.pack(side="right", padx=(0, 6))

        def start():
            if state["running"]:
                state["cancel"] = True
                start_btn.config(state="disabled", text="Stopping…")
                return
            media = [m for m, v in media_vars.items() if v.get()]
            if not do_text.get() and not media:
                return
            if do_text.get() and scraper.es_de_running():
                messagebox.showwarning("Close RetroDECK first",
                                       "ES-DE is running and would overwrite gamelist.xml when it quits.\n\n"
                                       "Close it and press Start again, or untick Text to only download images.",
                                       parent=win)
                return
            keys = scopes[scope.get()][1]
            links = self.lb_ids if use_close.get() else self.lb_links
            jobs = [(scraper.primary_file(self.units[k]["paths"]), links[k], self.regions[k])
                    for k in keys if k in links]
            q = queue.Queue()
            args = (jobs, self.platform, self.system, self.cfg["roms_root"], self.gamelist_path(), do_text.get(),
                    media, lambda m, d, t: q.put(("p", m, d, t)), lambda: state["cancel"], overwrite.get())

            def work():
                try:
                    q.put(("done", scraper.scrape(*args), None, None))
                except Exception as e:
                    q.put(("err", str(e), None, None))

            def poll():
                try:
                    while True:
                        kind, a, d, t = q.get_nowait()
                        if kind == "p":
                            status.config(text=a)
                            bar.config(maximum=max(t, 1), value=d)
                        else:
                            state["running"] = False
                            start_btn.config(state="normal", text="Start")
                            close_btn.config(state="normal")
                            if kind == "err":
                                status.config(text=f"Failed: {a}")
                                return
                            s = a
                            stopped = "Stopped early. " if state["cancel"] else ""
                            status.config(text=(
                                f"{stopped}Filled {s['text']} text fields ({s.get('added', 0)} new gamelist entries), "
                                f"downloaded {s['images']} images. {s['skipped']} already had that image, "
                                f"{s['missing']} not available in LaunchBox, {s['failed']} failed. "
                                f"{len(keys) - len(jobs)} games had no {'' if use_close.get() else 'exact '}"
                                f"LaunchBox match "
                                f"(right-click a game to pick one)."))
                            state["cancel"] = False
                            return
                except queue.Empty:
                    win.after(150, poll)

            state.update(running=True, cancel=False)
            start_btn.config(text="Stop")
            close_btn.config(state="disabled")
            status.config(text=f"Preparing {len(jobs)} games …")
            threading.Thread(target=work, daemon=True).start()
            poll()

        start_btn.config(command=start)
        win.protocol("WM_DELETE_WINDOW", lambda: None if state["running"] else win.destroy())

    # ---------- scanning ----------
    def rescan(self):
        self.root.config(cursor="watch")
        self.root.update_idletasks()
        try:
            self._scan()
        finally:
            self.root.config(cursor="")
        self.show_disk()
        self.refresh()

    def show_disk(self):
        """Free space on the drive the roms folder is on; under 10% free turns the text orange."""
        try:
            du = shutil.disk_usage(self.cfg["roms_root"])
        except OSError:
            self.disk_lbl.config(text="")
            self.disk_bar.grid_remove()
            return
        used = 100 * (du.total - du.free) / du.total if du.total else 0
        self.disk_lbl.config(text=f"{human(du.free)} free",
                             style="Move.TLabel" if used > 90 else "Muted.TLabel")
        self.disk_bar.config(value=used)
        self.disk_bar.grid()

    def show_holding(self):
        """Footer shows the last two folders only, so a long path can't push the status text under the buttons."""
        parts = os.path.normpath(self.holding_root()).split(os.sep)
        self.hold_lbl.config(text=os.sep.join(parts[-2:] if len(parts) <= 3 else ["…"] + parts[-2:]))

    def _disk_tip(self):
        try:
            du = shutil.disk_usage(self.cfg["roms_root"])
        except OSError:
            return ""
        return (f"Drive with your ROMs: {human(du.free)} free of {human(du.total)} "
                f"({100 * (du.total - du.free) / du.total:.0f}% used)")

    def holding_on_same_drive(self):
        """True when the holding folder (or where it will be created) shares a filesystem with roms."""
        p = self.holding_root()
        while not os.path.exists(p) and os.path.dirname(p) != p:
            p = os.path.dirname(p)
        try:
            return os.stat(p).st_dev == os.stat(self.cfg["roms_root"]).st_dev
        except OSError:
            return False

    def _scan(self):
        self.units, self.file_to_unit = {}, {}
        for e in list_entries(self.folder, self.exts):
            key = e.name if e.name.lower().endswith(PARTIAL_EXT) else unit_key(e.name)
            u = self.units.setdefault(key, {"paths": [], "size": 0, "extra": []})
            u["paths"].append(e.path)
            u["size"] += dir_size(e.path) if e.is_dir() else e.stat().st_size
            for x in nps.linked_data(self.system, e.path, self.cfg["roms_root"]):  # installed PS3 / Vita data
                u["extra"].append(x)
                u["size"] += dir_size(x) if os.path.isdir(x) else os.path.getsize(x)
            self.file_to_unit[e.name] = key
        keys = list(self.units)
        self.manual = {k: v for k, v in self.manual.items() if k in self.units}
        self.preset_hits = {p: fn(keys) for p, fn in PRESETS.items() if p != DUPES}
        self.dupes_key = None  # region dupes are computed in refresh(), since they depend on the region filter
        self.preset_hits["Partial downloads (.part)"] = {k for k in keys if k.lower().endswith(PARTIAL_EXT)}

        self.played = set()
        gl = find_gamelist(self.cfg["roms_root"], self.system)
        if gl:
            try:
                for g in scraper.read_gamelist(gl)[1].iter("game"):
                    if int(g.findtext("playcount") or 0) > 0:
                        fn = os.path.basename((g.findtext("path") or "").rstrip("/"))
                        self.played.add(self.file_to_unit.get(fn, unit_key(fn)))
            except (OSError, ET.ParseError, ValueError):
                pass
        self.played &= self.units.keys()
        self.played_cb.config(text=f"Protect played games ({len(self.played)})")

        self.ratings, self.lb_kind, self.lb_ids = {}, {}, {}
        self.lb_links = {}  # key -> LaunchBox id, exact or hand-picked only (groups region dupes, drives scraping)
        matched = rated = 0
        if self.platform:
            m = lb.Matcher(self.platform)
            if m.ok:
                for k in keys:
                    gid, g, kind = m.match(title_of(k))
                    if kind:
                        self.lb_kind[k] = kind
                    if g:
                        self.ratings[k] = g
                        self.lb_ids[k] = gid
                        if kind in ("exact", "manual"):
                            self.lb_links[k] = gid
                        matched += 1
                        rated += g["r"] is not None
                m.save()
        if not lb.platforms():
            self.rat_info.config(text="No LaunchBox data — Tools → Download")
        elif not self.platform:
            self.rat_info.config(text="No LaunchBox platform for this system")
        else:
            picked = sum(kind == "manual" for kind in self.lb_kind.values())
            self.rat_info.config(text=f"{matched}/{len(keys)} matched · {rated} rated"
                                      + (f"\n{picked} matched by hand" if picked else ""))

        # keep genre / region picks across rescans; right after a system switch, use the ones saved for it
        pending = getattr(self, "_pending_sel", None)
        self._pending_sel = None
        keep_genres, keep_regions = pending or (
            [self.genre_names[i] for i in self.genre_lb.curselection()] if hasattr(self, "genre_names") else [],
            [self.region_names[i] for i in self.region_lb.curselection()] if hasattr(self, "region_names") else [])

        gcount = Counter(x for g in self.ratings.values() for x in g["g"])
        self.genre_names = [g for g, _ in gcount.most_common()]
        self.genre_lb.delete(0, "end")
        for i, g in enumerate(self.genre_names):
            self.genre_lb.insert("end", f"{g} ({gcount[g]})")
            if g in keep_genres:
                self.genre_lb.selection_set(i)

        self.regions = {k: regions_of(k) or ("(none)",) for k in keys}
        rcount = Counter(r for rs in self.regions.values() for r in rs)
        self.region_names = [r for r, _ in rcount.most_common()]
        self.region_lb.delete(0, "end")
        for i, r in enumerate(self.region_names):
            self.region_lb.insert("end", f"{r} ({rcount[r]})")
            if r in keep_regions:
                self.region_lb.selection_set(i)

    # ---------- per-system state ----------
    def _state(self):
        return {
            "patterns": self.pat_text.get("1.0", "end").rstrip("\n"), "icase": self.icase.get(),
            "presets": [p for p, v in self.preset_vars.items() if v.get()],
            "protect_played": self.protect_played.get(),
            "use_rating": self.use_rating.get(), "rating_max": self.rating_max.get(),
            "min_votes": self.min_votes.get(), "use_unrated": self.use_unrated.get(),
            "genres": [self.genre_names[i] for i in self.genre_lb.curselection()],
            "regions": [self.region_names[i] for i in self.region_lb.curselection()],
            "region_mode": self.region_mode.get(),
            "flips": self.manual,
        }

    def save_state(self):
        """Patterns, filters and flips are kept per system in config.json, so each one opens as it was left."""
        if not getattr(self, "system", None) or getattr(self, "_restoring", False):
            return
        try:
            state = self._state()
        except (tk.TclError, ValueError, IndexError):
            return  # a half-typed spinbox value: the next refresh saves
        if self.cfg["system_state"].get(self.system) != state:
            self.cfg["system_state"][self.system] = state
            self.save_cfg()

    def restore_state(self):
        st = self.cfg["system_state"].get(self.system, {})
        self._restoring = True
        try:
            self.pat_text.delete("1.0", "end")
            self.pat_text.insert("1.0", st.get("patterns", ""))
            self.pat_text.edit_reset()
            self._toggle_hint()
            self.icase.set(st.get("icase", True))
            for p, v in self.preset_vars.items():
                v.set(p in st.get("presets", []))
            self.protect_played.set(st.get("protect_played", True))
            self.use_rating.set(st.get("use_rating", False))
            self.rating_max.set(st.get("rating_max", 2.5))
            self.min_votes.set(st.get("min_votes", 3))
            self.use_unrated.set(st.get("use_unrated", False))
            self.region_mode.set(st.get("region_mode", REGION_MODES[0]))
            self.manual = dict(st.get("flips", {}))
            self._pending_sel = (st.get("genres", []), st.get("regions", []))  # applied once _scan lists them
        finally:
            self._restoring = False

    def _center_dialog(self, e):
        """Every dialog opens in the middle of the main window (once; moving it afterwards sticks)."""
        w = e.widget
        if isinstance(w, tk.Toplevel) and not getattr(w, "_centered", False) and not w.wm_overrideredirect():
            w._centered = True
            ui.center(w, self.root)

    def _close(self):
        self.save_state()
        self.root.destroy()

    def reset_manual(self):
        self.manual = {}
        self.refresh()

    def flip(self, tv, to_move):
        self.keys.flip(tv, to_move)

    def review(self):
        """Go through the list that has the keyboard (else Keeping) one game at a time, from the cursor."""
        focus = self.root.focus_get()
        tv = self.move_tv if focus is self.move_tv else self.keep_tv
        rows = tv.get_children()
        review.open_window(self, rows, self.keys.cursor(tv) or 0)

    # ---------- decide ----------
    def refresh(self):
        self.after_id = None
        icase = self.icase.get()
        moves, keeps = [], []
        for raw in self.pat_text.get("1.0", "end").splitlines():
            p = raw.strip()
            if not p or p.startswith("#"):
                continue
            if p.startswith("!"):
                keeps.append((p, wildcard_re(p[1:], icase)))
            else:
                moves.append((p, wildcard_re(p, icase)))
        active = [p for p, v in self.preset_vars.items() if v.get()]
        try:
            rating_max, min_votes = float(self.rating_max.get()), int(self.min_votes.get())
        except (tk.TclError, ValueError):
            rating_max, min_votes = -1.0, 1 << 30
        use_rating, use_unrated = self.use_rating.get(), self.use_unrated.get()
        genres = {self.genre_names[i] for i in self.genre_lb.curselection()}
        sel_regions = {self.region_names[i] for i in self.region_lb.curselection()}
        keep_only = self.region_mode.get() == REGION_MODES[1]
        prio = self.dupes_priority(sel_regions, keep_only)
        if prio != self.dupes_key:
            self.preset_hits[DUPES] = region_dupes(list(self.units), prio, self.lb_links)
            self.dupes_key = prio
        protect = self.protect_played.get()

        self.to_move, self.kept, self.why = [], [], {}
        for key in sorted(self.units):
            if key in self.manual:
                hit, why = self.manual[key], "manual"
            else:
                names = [key] + [os.path.basename(p) for p in self.units[key]["paths"]]
                reasons = [
                    f"dupe of {PREFIX_RE.sub('', self.preset_hits[p][key])}" if p == DUPES else p.split(" (")[0]
                    for p in active if key in self.preset_hits[p]
                ]
                reasons += [p for p, rx in moves if any(rx.match(n) for n in names)]
                g = self.ratings.get(key)
                if use_rating and g and g["r"] is not None and g["v"] >= min_votes and g["r"] < rating_max:
                    reasons.append(f"rating < {rating_max:g}")
                if use_unrated and (not g or g["r"] is None):
                    reasons.append("unrated")
                if genres and g and genres.intersection(g["g"]):
                    reasons.append("genre")
                if sel_regions:
                    rs = set(self.regions[key])
                    if (keep_only and not rs & sel_regions) or (not keep_only and rs <= sel_regions):
                        reasons.append("region")
                keeper = "played" if protect and key in self.played else None
                keeper = keeper or next((p for p, rx in keeps if any(rx.match(n) for n in names)), None)
                hit = bool(reasons) and keeper is None
                why = keeper if (reasons and keeper) else ", ".join(reasons)
            self.why[key] = why
            (self.to_move if hit else self.kept).append(key)
        self.render()
        self._tab_counts(active, moves, keeps, use_rating, use_unrated, genres, sel_regions)
        self.save_state()

    def _tab_counts(self, active, moves, keeps, use_rating, use_unrated, genres, regions):
        counts = [len(active) + use_rating + use_unrated, len(genres), len(regions), len(moves) + len(keeps)]
        for page, base, n in zip(self.filter_pages, ("Presets & ratings", "Genres", "Regions", "Patterns"), counts):
            self.filter_tabs.tab(page, text=f"{base} ({n})" if n else base)

    # ---------- display ----------
    def _label(self, key):
        paths = self.units[key]["paths"]
        return os.path.basename(paths[0]) if len(paths) == 1 else f"{key}  [{len(paths)} files]"

    def _sort_key(self, key, col):
        g = self.ratings.get(key) or {}
        if col == "rating":
            return g["r"] if g.get("r") is not None else -1.0
        if col == "genre":
            return ", ".join(g.get("g", []))
        if col == "region":
            return ", ".join(self.regions[key])
        if col == "size":
            return self.units[key]["size"]
        return self.why[key]

    def sort(self, col):
        c, desc = self.sort_by
        self.sort_by = (col, not desc if c == col else col in ("rating", "size"))
        self.render()

    def render(self):
        q = self.view_filter.get().lower()
        for tv, keys, lbl, title in (
            (self.keep_tv, self.kept, self.keep_lbl, "●  Keeping"),
            (self.move_tv, self.to_move, self.move_lbl, "●  Moving"),
        ):
            shown = [k for k in keys if q in k.lower()] if q else keys
            col, desc = self.sort_by
            if col != "#0":
                shown = sorted(shown, key=lambda k: self._sort_key(k, col), reverse=desc)
            elif desc:
                shown = shown[::-1]
            keep_sel = tv.selection()  # survive the rebuild (flips, filter changes) where the game is still listed
            tv.delete(*tv.get_children())
            tv.hover = None
            for i, k in enumerate(shown):
                g = self.ratings.get(k)
                rating = "—" if not g or g["r"] is None else f"{ui.stars(g['r'])}  {g['r']:.1f}"
                tags = (("odd",) if i % 2 else ()) + (("manual",) if k in self.manual else ())
                tv.insert("", "end", iid=k, text=self._label(k),
                          values=(self.why[k], ", ".join(self.regions[k]), rating, ", ".join(g["g"]) if g else "",
                                  human(self.units[k]["size"])),
                          tags=tags)
            again = [k for k in keep_sel if tv.exists(k)]
            if again:
                tv.selection_set(again)
            self.keys.after_render()
            size = sum(self.units[k]["size"] for k in keys)
            extra = f"  ·  {len(shown)} shown" if q else ""
            lbl.config(text=f"{title}   {len(keys):,} games  ·  {human(size)}{extra}")
            if shown:
                tv.empty.place_forget()
            else:
                tv.empty.config(text=f"No games match “{self.view_filter.get()}”" if q and keys else
                                "Nothing to move yet\n\nTick a preset, pick genres or regions, add a name pattern,\n"
                                "or double-click a game on the left." if tv is self.move_tv else
                                "Nothing left to keep\n\nEvery game here is set to move." if self.units else
                                "No games in this folder")
                tv.empty.place(relx=0.5, rely=0.45, anchor="center")
        n, size = len(self.to_move), sum(self.units[k]["size"] for k in self.to_move)
        self.move_btn.config(text=f"Move {n:,} game{'s' if n != 1 else ''}  ·  {human(size)}" if n else "Move files",
                             state="normal" if n else "disabled")
        self.render_status()
        if not self.keep_tv.selection() and not self.move_tv.selection():
            self._details_idle()

    def render_status(self):
        nfiles = sum(len(u["paths"]) for u in self.units.values())
        flips = f"{len(self.manual)} flipped (orange)  ·  " if self.manual else ""
        self.status.config(text=f"{len(self.units):,} games ({nfiles:,} files)  ·  {flips}double-click or → / ← flips "
                                f"a game, Space marks  ·  Ctrl+R reviews one by one  ·  right-click for more")

    # ---------- output ----------
    def export(self):
        path = dialogs.ask_save_file(self.root, "Export move list", initialdir=APP_DIR,
                                     initialfile=f"{self.system}_move.txt", defaultextension=".txt")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                for k in self.to_move:
                    f.writelines(os.path.basename(p) + "\n" for p in self.units[k]["paths"])

    def execute(self):
        if not self.to_move:
            messagebox.showinfo("Nothing to move", "Move list is empty.")
            return
        dest_dir = os.path.join(self.holding_root(), self.dest.get(), self.system)
        size = sum(self.units[k]["size"] for k in self.to_move)
        nfiles = sum(len(self.units[k]["paths"]) for k in self.to_move)
        installed = [k for k in self.to_move if self.units[k]["extra"]]
        extra_note = (f"\n\n{len(installed)} of them are installed in RPCS3 / Vita3K: their game data and licenses "
                      f"move too, into {dest_dir}/installed/ (saves stay put).") if installed else ""
        space_note = ("\n\nThe holding folder is on the same drive as your ROMs, so this frees no disk space "
                      "until you delete the files from there.") if self.holding_on_same_drive() else ""
        if not messagebox.askyesno("Confirm move", f"Move {len(self.to_move)} games ({nfiles} files, {human(size)}) "
                                                   f"into\n{dest_dir}/ ?{extra_note}{space_note}"):
            return
        os.makedirs(dest_dir, exist_ok=True)
        base = os.path.dirname(os.path.realpath(self.cfg["roms_root"]))
        moved, failed, done = 0, [], []
        for k in self.to_move:
            for p in self.units[k]["paths"] + self.units[k]["extra"]:
                if p in self.units[k]["extra"]:  # keep the path under retrodeck/ so it can be moved back by hand
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
        if done:
            self._log_moves({"time": datetime.datetime.now().isoformat(timespec="seconds"), "system": self.system,
                             "dest": self.dest.get(), "games": len(self.to_move), "size": size, "moves": done})
        self.rescan()  # drops the moved games' flips; "keep" flips on games that stayed are kept
        if failed:
            messagebox.showerror(f"Moved {moved} files, {len(failed)} failed", "\n".join(failed[:30]))
        else:
            self.toast(f"Moved {moved:,} files to {self.dest.get()}. Library → Holding folder… to review "
                       "or delete them.")

    # ---------- move log / restore ----------
    def moves_log(self):
        """Kept with the app (entries hold absolute paths), so changing the holding folder doesn't lose history."""
        return os.path.join(APP_DIR, "moves.json")

    def _read_moves(self):
        try:
            with open(self.moves_log(), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def _write_moves(self, batches):
        write_json(self.moves_log(), batches, indent=1)

    def _merge_old_log(self):
        """Older versions logged moves in <holding>/moves.json; fold that into the current log once, so Restore and
        the holding folder window know where those games came from. The old file is kept as moves.json.merged."""
        old = os.path.join(self.holding_root(), "moves.json")
        if not os.path.isfile(old) or os.path.realpath(old) == os.path.realpath(self.moves_log()):
            return
        try:
            with open(old, encoding="utf-8") as f:
                legacy = json.load(f)
            batches = self._read_moves()
            seen = {(b["time"], b["system"], b["dest"]) for b in batches}
            batches += [b for b in legacy if (b["time"], b["system"], b["dest"]) not in seen]
            self._write_moves(sorted(batches, key=lambda b: b["time"]))
            os.replace(old, old + ".merged")
        except (OSError, ValueError, KeyError, TypeError):
            pass  # leave both files alone; nothing is lost

    def _log_moves(self, batch):
        try:
            self._write_moves(self._read_moves() + [batch])
        except OSError as e:
            messagebox.showwarning("Move log not saved", f"Restore won't know about this move:\n{e}")

    def restore_dialog(self):
        batches = self._read_moves()
        win = tk.Toplevel(self.root)
        win.title("Restore moved games")
        win.transient(self.root)
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        body = ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Put moved games back", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text=f"Every Move files run is logged in {self.moves_log()}. Restoring moves the files "
                             "(and any RPCS3 / Vita3K data that went with them) back where they came from.",
                  style="Muted.TLabel", wraplength=640, justify="left").pack(anchor="w", pady=(2, 10))
        foot = ttk.Frame(body, padding=(0, 12, 0, 0))
        foot.pack(side="bottom", fill="x")
        tv = ttk.Treeview(body, columns=("system", "dest", "games", "left"), selectmode="extended", height=10)
        for col, text, width, anchor in (("#0", "When", 170, "w"), ("system", "System", 90, "w"),
                                         ("dest", "Moved to", 140, "w"), ("games", "Games", 110, "e"),
                                         ("left", "Still in holding", 130, "e")):
            tv.heading(col, text=text, anchor=anchor)
            tv.column(col, width=width, anchor=anchor, stretch=col == "#0")
        tv.pack(fill="both", expand=True)

        def fill():
            tv.delete(*tv.get_children())
            for i in range(len(batches) - 1, -1, -1):
                b = batches[i]
                left = sum(os.path.exists(t) for _, t in b["moves"])
                tv.insert("", "end", iid=str(i), text=b["time"].replace("T", "  "),
                          values=(b["system"], b["dest"], f"{b['games']}  ({human(b['size'])})",
                                  f"{left} / {len(b['moves'])} files"))
        fill()

        def restore():
            sel = sorted((int(i) for i in tv.selection()), reverse=True)  # newest first undoes in order
            if not sel:
                return
            back, failed = 0, []
            for i in sel:
                remaining = []
                for src, target in reversed(batches[i]["moves"]):
                    if not os.path.exists(target):
                        continue  # deleted from the holding folder since; nothing to bring back
                    try:
                        if os.path.exists(src):
                            raise OSError("something is already at the original path")
                        os.makedirs(os.path.dirname(src), exist_ok=True)
                        shutil.move(target, src)
                        back += 1
                        prune_empty(os.path.dirname(target), self.holding_root())
                    except OSError as e:
                        failed.append(f"{os.path.basename(src)}: {e}")
                        remaining.append([src, target])
                if remaining:
                    batches[i]["moves"] = remaining[::-1]
                else:
                    del batches[i]
            try:
                self._write_moves(batches)
            except OSError as e:
                failed.append(f"move log: {e}")
            fill()
            self.rescan()
            if failed:
                messagebox.showerror(f"Restored {back} files, {len(failed)} failed", "\n".join(failed[:30]),
                                     parent=win)
            else:
                self.toast(f"Put {back:,} files back.")

        ttk.Button(foot, text="Restore selected", style="Accent.TButton", command=restore).pack(side="right")
        ttk.Button(foot, text="Close", command=win.destroy).pack(side="right", padx=(0, 6))
        if not batches:
            ttk.Label(foot, text="Nothing logged yet.", style="Muted.TLabel").pack(side="left")
        win.bind("<Escape>", lambda e: win.destroy())

    def _show_selected(self, tv):
        """Status line: the LaunchBox match, and where a launcher entry's installed data lives (PS3 shortcuts,
        .psvita files)."""
        sel = tv.selection()
        key = sel[0] if len(sel) == 1 else None
        if key not in self.units:
            self.render_status()
            self._details_idle(sel)
            return
        self.details.show(self.game_info(self.system, key, self.units[key]["paths"], self.units[key]["size"],
                                         self.ratings.get(key), self.lb_ids.get(key), self.platform))
        g, kind = self.ratings.get(key), self.lb_kind.get(key)
        parts = [f"LaunchBox: {g['n']} ({'picked by hand' if kind == 'manual' else kind})" if g else
                 "LaunchBox: no match (set by hand)" if kind == "manual" else
                 "LaunchBox: no match  ·  right-click to pick one"]
        if self.units[key]["extra"]:
            parts.append("Installed data:  " + "  ·  ".join(self.units[key]["extra"]))
        self.status.config(text="  ·  ".join(parts))

    # ---------- details ----------
    def _details_idle(self, sel=()):
        """What the details panel shows with no single game selected."""
        if len(sel) > 1:
            size = sum(self.units[k]["size"] for k in sel if k in self.units)
            self.status.config(text=f"{len(sel):,} selected  ·  {human(size)}  ·  → / ← or Enter flips them, Space marks")
            self.details.placeholder(f"{len(sel):,} games selected", f"{human(size)} in total.\n\nSpace or "
                                     "double-click flips them between Keeping and Moving. Right-click for more.",
                                     image=self.big_icon)
            return
        tips = ("Pick a game to see its artwork, LaunchBox info and description.\n\n"
                "•  Presets, ratings, genres, regions and name patterns decide what moves.\n"
                "•  Double-click or Space flips a game by hand; right-click to fix its LaunchBox match.\n"
                "•  Moved games wait in the holding folder until you delete them (Library → Holding folder…).")
        action = None
        if not lb.platforms():
            tips = ("Download the LaunchBox database (about 110 MB, once) to get ratings, genres, artwork and "
                    "descriptions for your games.\n\n" + tips)
            action = ("Download LaunchBox data", self.update_lb)
        self.details.placeholder("Welcome to RetroShelf", tips, image=self.big_icon,
                                 action=action)


    def _replay(self):
        """Settings changed: restart (or stop) the video in every details panel."""
        for p in self.detail_panels:
            if p.winfo_exists():
                if details.PLAY_VIDEOS and p.info:
                    p.show(p.info)
                elif not details.PLAY_VIDEOS:
                    p.spot.stop()

    def toggle_videos(self):
        self.cfg["play_videos"] = details.PLAY_VIDEOS = self.videos_var.get()
        self.save_cfg()
        self._replay()
        if details.PLAY_VIDEOS and not video.backend()[0]:
            messagebox.showinfo("Gameplay videos", "To play videos here, install mpv (or ffmpeg, for clips only). "
                                                   "On Steam Deck: mpv from Discover.")

    def toggle_streams(self):
        on = self.stream_var.get()
        missing = video.missing_for_streams() if on else ""
        if missing:
            messagebox.showinfo("Stream gameplay videos", f"Streaming from YouTube needs {missing}. Install it, then "
                                                          "switch this on again.")
            self.stream_var.set(False)
            return
        self.cfg["stream_videos"] = details.STREAM_VIDEOS = on
        if on and not self.cfg["play_videos"]:  # streaming implies playing
            self.cfg["play_videos"] = details.PLAY_VIDEOS = True
            self.videos_var.set(True)
        self.save_cfg()
        self._replay()

    def toggle_details(self):
        self.cfg["show_details"] = self.details_var.get()
        self.save_cfg()
        if self.cfg["show_details"]:
            self.filter_tabs.pack_configure(side="right")
            self.details_card.pack(side="left", fill="both", expand=True, padx=(0, 10))
        else:
            self.details_card.pack_forget()
            self.filter_tabs.pack_configure(side="left")  # no empty gap where the details were

    def lb_details(self, platform):
        if platform and platform not in self._lb_details:
            self._lb_details[platform] = lb.load_details(platform)
        return self._lb_details.get(platform, {})

    def game_info(self, system, key, paths, size, game, gid, platform):
        """What a DetailsPanel shows for one game (in roms or in the holding folder)."""
        names = [os.path.basename(p.rstrip("/")) for p in paths]
        return {
            "title": game["n"] if game else title_of(key),
            "console": nps.FULL_NAMES.get(system) or (self.fullname if system == self.system else None)
                       or platform or system,
            "lb": game, "det": self.lb_details(platform).get(gid, {}) if gid else {},
            "media_dir": os.path.join(scraper.media_root(self.cfg["roms_root"]), system),
            "stems": list(dict.fromkeys([os.path.splitext(n)[0] for n in names] + names)),
            "file": names[0] if len(names) == 1 else f"{key}  [{len(names)} files]",
            "size": human(size),
        }

    # ---------- holding folder ----------
    def _holding_games(self):
        """Games sitting in <holding>/<to_delete|review_low_value>/<system>/, joined with the move log so each
        knows where it came from, when it moved, and which RPCS3 / Vita3K data went with it."""
        origin, moved_at, extras_of = {}, {}, {}
        for b in self._read_moves():
            owner = None
            for src, target in b["moves"]:
                origin[target], moved_at[target] = src, b["time"]
                if os.sep + "installed" + os.sep in target and owner:
                    extras_of.setdefault(owner, []).append(target)
                else:
                    owner = target
        games = {}
        root = self.holding_root()
        for dest in DESTS:
            base = os.path.join(root, dest)
            for system in sorted(os.listdir(base)) if os.path.isdir(base) else []:
                folder = os.path.join(base, system)
                if not os.path.isdir(folder):
                    continue
                for e in os.scandir(folder):
                    if e.name.startswith(".") or (e.is_dir() and e.name == "installed"):
                        continue
                    key = e.name if e.name.lower().endswith(PARTIAL_EXT) else unit_key(e.name)
                    g = games.setdefault((dest, system, key), {"dest": dest, "system": system, "key": key,
                                                               "paths": [], "extra": [], "size": 0, "moved": ""})
                    g["paths"].append(e.path)
                    g["size"] += dir_size(e.path) if e.is_dir() else e.stat().st_size
                    g["moved"] = max(g["moved"], moved_at.get(e.path, ""))
                    for x in extras_of.get(e.path, []):
                        if os.path.lexists(x):
                            g["extra"].append(x)
                            g["size"] += dir_size(x) if os.path.isdir(x) else os.path.getsize(x)
        return list(games.values()), origin

    def _drop_from_log(self, targets):
        batches = []
        for b in self._read_moves():
            b["moves"] = [m for m in b["moves"] if m[1] not in targets]
            if b["moves"]:
                batches.append(b)
        self._write_moves(batches)

    def holding_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("Holding folder")
        win.transient(self.root)
        win.geometry("1300x780")
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        body = ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Games in the holding folder", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text=f"{self.holding_root()}  ·  Look through what you moved out, put games back, or "
                             "delete them for good to free the space.", style="Muted.TLabel", wraplength=1200,
                  justify="left").pack(anchor="w", pady=(2, 10))

        row = ttk.Frame(body)
        row.pack(fill="x")
        ttk.Label(row, text="Folder").pack(side="left", padx=(0, 6))
        dest_var = tk.StringVar(value="All")
        ttk.Combobox(row, textvariable=dest_var, values=["All"] + DESTS, state="readonly", width=18).pack(side="left")
        ttk.Label(row, text="System").pack(side="left", padx=(16, 6))
        sys_var = tk.StringVar(value="All")
        sys_cb = ttk.Combobox(row, textvariable=sys_var, state="readonly", width=12)
        sys_cb.pack(side="left")
        ttk.Label(row, text="Search").pack(side="left", padx=(16, 6))
        q_var = tk.StringVar()
        ttk.Entry(row, textvariable=q_var).pack(side="left", fill="x", expand=True)

        foot = ttk.Frame(body, padding=(0, 12, 0, 0))
        foot.pack(side="bottom", fill="x")
        summary = ttk.Label(foot, style="Muted.TLabel")
        summary.pack(side="left")
        forget = tk.BooleanVar(value=True)

        panes = ttk.PanedWindow(body, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=(10, 0))
        left = ttk.Frame(panes)
        tv = ttk.Treeview(left, columns=("system", "dest", "size", "moved"), selectmode="extended")
        for col, text, width, anchor in (("#0", "Game", 420, "w"), ("system", "System", 90, "w"),
                                         ("dest", "Folder", 140, "w"), ("size", "Size", 90, "e"),
                                         ("moved", "Moved", 170, "w")):
            tv.heading(col, text=text, anchor=anchor, command=lambda c=col: sort(c))
            tv.column(col, width=width, anchor=anchor, stretch=col == "#0")
        sb = ttk.Scrollbar(left, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tv.tag_configure("odd", background=self.colors["stripe"])
        panes.add(left, weight=1)
        panel = details.DetailsPanel(panes, self.field_style)
        self.detail_panels.append(panel)
        panes.add(panel, weight=0)

        state = {"games": [], "origin": {}, "shown": [], "sort": ("#0", False), "matchers": {}}

        def platform_of(system):
            folder = os.path.join(self.cfg["roms_root"], system)
            name, full, _ = read_systeminfo(folder)
            return lb.resolve_platform(system, full if name == system else nps.FULL_NAMES.get(system),
                                       self.cfg["platform_overrides"])

        def lb_match(g):
            plat = platform_of(g["system"])
            if not plat:
                return None, None, None
            m = state["matchers"].get(plat) or state["matchers"].setdefault(plat, lb.Matcher(plat))
            gid, game, _ = m.match(title_of(g["key"]))
            return game, gid, plat

        def load():
            state["games"], state["origin"] = self._holding_games()
            systems = sorted({g["system"] for g in state["games"]})
            sys_cb["values"] = ["All"] + systems
            if sys_var.get() not in sys_cb["values"]:
                sys_var.set("All")
            fill()

        def sort(col):
            c, desc = state["sort"]
            state["sort"] = (col, not desc if c == col else col in ("size", "moved"))
            fill()

        def fill():
            q = q_var.get().lower()
            shown = [g for g in state["games"]
                     if dest_var.get() in ("All", g["dest"]) and sys_var.get() in ("All", g["system"])
                     and (not q or q in g["key"].lower())]
            col, desc = state["sort"]
            keyf = {"#0": lambda g: g["key"].lower(), "system": lambda g: g["system"], "dest": lambda g: g["dest"],
                    "size": lambda g: g["size"], "moved": lambda g: g["moved"]}[col]
            shown.sort(key=keyf, reverse=desc)
            state["shown"] = shown
            tv.delete(*tv.get_children())
            for i, g in enumerate(shown):
                label = os.path.basename(g["paths"][0]) if len(g["paths"]) == 1 else \
                    f"{g['key']}  [{len(g['paths'])} files]"
                tv.insert("", "end", iid=str(i), text=label, tags=("odd",) if i % 2 else (),
                          values=(g["system"], g["dest"], human(g["size"]), g["moved"].replace("T", "  ")))
            in_del = [g for g in shown if g["dest"] == "to_delete"]
            summary.config(text=f"{len(shown):,} games · {human(sum(g['size'] for g in shown))}")
            empty_btn.config(text=f"Empty to_delete ({len(in_del):,} · {human(sum(g['size'] for g in in_del))})",
                             state="normal" if in_del else "disabled")
            on_select()

        def picked():
            return [state["shown"][int(i)] for i in tv.selection()]

        def on_select(_=None):
            sel = picked()
            if len(sel) != 1:
                panel.clear(f"{len(sel)} games selected." if sel else "Select a game to see its details.")
                return
            g = sel[0]
            game, gid, plat = lb_match(g)
            panel.show(self.game_info(g["system"], g["key"], g["paths"], g["size"], game, gid, plat))

        def restore(games):
            if not games:
                return
            back, failed, done = 0, [], set()
            for g in games:
                pairs = [(p, state["origin"].get(p) or os.path.join(self.cfg["roms_root"], g["system"],
                                                                     os.path.basename(p))) for p in g["paths"]]
                pairs += [(x, state["origin"][x]) for x in g["extra"] if x in state["origin"]]
                for target, src in pairs:
                    try:
                        if os.path.lexists(src):
                            raise OSError("something is already at the original path")
                        os.makedirs(os.path.dirname(src), exist_ok=True)
                        shutil.move(target, src)
                        done.add(target)
                        back += 1
                        prune_empty(os.path.dirname(target), self.holding_root())
                    except OSError as e:
                        failed.append(f"{os.path.basename(src)}: {e}")
            try:
                self._drop_from_log(done)
            except OSError as e:
                failed.append(f"move log: {e}")
            load()
            self.rescan()
            if failed:
                messagebox.showerror(f"Restored {back} files, {len(failed)} failed", "\n".join(failed[:30]),
                                     parent=win)

        def delete(games, what):
            if not games:
                return
            size = sum(g["size"] for g in games)
            extra = sum(bool(g["extra"]) for g in games)
            note = f"\n\n{extra} of them include RPCS3 / Vita3K game data, which is deleted too." if extra else ""
            esde = "\n\nTheir ES-DE artwork and gamelist entries are removed as well." if forget.get() else ""
            if not messagebox.askyesno("Delete for good", f"Permanently delete {what} ({len(games):,} games, "
                                                         f"{human(size)})?{note}{esde}\n\nThis can't be undone.",
                                       icon="warning", parent=win):
                return
            gone, failed, by_system = set(), [], {}
            for g in games:
                for p in g["paths"] + g["extra"]:
                    try:
                        if os.path.isdir(p) and not os.path.islink(p):
                            shutil.rmtree(p)
                        else:
                            os.unlink(p)
                        gone.add(p)
                        prune_empty(os.path.dirname(p), self.holding_root())
                    except OSError as e:
                        failed.append(f"{os.path.basename(p)}: {e}")
                if all(p in gone for p in g["paths"]):
                    by_system.setdefault(g["system"], []).extend(os.path.basename(p.rstrip("/")) for p in g["paths"])
            try:
                self._drop_from_log(gone)
            except OSError as e:
                failed.append(f"move log: {e}")
            if forget.get():
                for system, names in by_system.items():
                    failed += scraper.forget_games(names, system, self.cfg["roms_root"],
                                                   find_gamelist(self.cfg["roms_root"], system))[2]
            load()
            self.show_disk()
            if failed:
                messagebox.showerror("Some files weren't deleted", "\n".join(failed[:30]), parent=win)

        ttk.Button(foot, text="Close", command=win.destroy).pack(side="right")
        empty_btn = ttk.Button(foot, command=lambda: delete(
            [g for g in state["shown"] if g["dest"] == "to_delete"],
            "everything in to_delete" + ("" if sys_var.get() == "All" else f" for {sys_var.get()}")))
        empty_btn.pack(side="right", padx=(0, 16))
        ttk.Button(foot, text="Delete selected", command=lambda: delete(picked(), "the selected games")).pack(
            side="right", padx=(0, 6))
        ttk.Button(foot, text="Restore selected", style="Accent.TButton",
                   command=lambda: restore(picked())).pack(side="right", padx=(0, 6))
        ttk.Checkbutton(foot, text="Deleting also removes ES-DE artwork and gamelist entries",
                        variable=forget).pack(side="right", padx=(0, 16))

        for var in (dest_var, sys_var, q_var):
            var.trace_add("write", lambda *_: fill())
        tv.bind("<<TreeviewSelect>>", on_select)
        tv.bind("<Delete>", lambda e: delete(picked(), "the selected games"))
        win.bind("<Escape>", lambda e: win.destroy())
        load()

    # ---------- renaming ----------
    def renames_log(self):
        return os.path.join(APP_DIR, "renames.json")

    def _read_renames(self):
        try:
            with open(self.renames_log(), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def _write_renames(self, batches):
        write_json(self.renames_log(), batches, indent=1, ensure_ascii=False)

    def _carry_over(self, done, failed):
        """ES-DE media + gamelist follow the renamed files. -> short summary for the result message."""
        media, entries, problems = scraper.carry_over(done, self.system, self.cfg["roms_root"], self.gamelist_path())
        failed += problems
        return f"\n\nES-DE: renamed {media:,} media files and {entries:,} gamelist entries."

    def _carry_matches(self, done, system):
        """Hand-picked LaunchBox matches are stored by title; copy them to the renamed games' new titles."""
        plat = self.platform if system == self.system else lb.resolve_platform(
            system, nps.FULL_NAMES.get(system), self.cfg["platform_overrides"])
        titles = {title_of(unit_key(os.path.basename(o))): title_of(unit_key(os.path.basename(n))) for o, n in done}
        titles = {o: n for o, n in titles.items() if o != n}
        if plat and titles:
            try:
                lb.copy_manual(plat, titles)
            except OSError:
                pass

    def _after_rename(self, done):
        """Carry double-click flips over to the games' new names, then rescan."""
        new_key = {}
        for old, new in done:
            k = self.file_to_unit.get(os.path.basename(old))
            if k:
                new_key[k] = unit_key(os.path.basename(new))
        self.manual = {new_key.get(k, k): v for k, v in self.manual.items()}
        self.rescan()

    def rename_dialog(self):
        if not self.units:
            messagebox.showinfo("No games", "Pick a system with games first.")
            return
        if self.system in ARCADE_SYSTEMS:
            messagebox.showinfo("Arcade games keep their names",
                                "MAME and FinalBurn find arcade games by their ROM set's file name (like "
                                "gridlee.zip), so renaming them would stop them starting. ES-DE shows their full "
                                "titles anyway.")
            return
        selected = set(self.keep_tv.selection()) | set(self.move_tv.selection())
        scopes = [("All games", list(self.units)), ("Keeping list", list(self.kept)),
                  ("Selected rows", [k for k in self.units if k in selected])]
        win = tk.Toplevel(self.root)
        win.title(f"Rename files — {self.system}")
        win.transient(self.root)
        win.geometry("1100x720")
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        body = ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Rename files to a pattern", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text="ES-DE media and gamelist.xml entries are renamed along with each game, so play "
                             "counts, favorites, scraped text and images stay with it. File names inside .cue / .m3u "
                             "files are updated too, so multi-disc games keep working.",
                  style="Muted.TLabel", wraplength=1040, justify="left").pack(anchor="w", pady=(2, 10))

        row = ttk.Frame(body)
        row.pack(fill="x")
        ttk.Label(row, text="Pattern").pack(side="left", padx=(0, 8))
        template = tk.StringVar(value=self.cfg["rename_templates"].get(self.system, DEFAULT_TEMPLATE))
        entry = ttk.Entry(row, textvariable=template, font=(self.mono, 10))
        entry.pack(side="left", fill="x", expand=True)
        scope = tk.IntVar(value=2 if scopes[2][1] else 0)
        for i, (label, keys) in enumerate(scopes):
            ttk.Radiobutton(row, text=f"{label} ({len(keys):,})", variable=scope, value=i,
                            state="normal" if keys else "disabled",
                            command=lambda: refresh()).pack(side="left", padx=(12, 0))
        ttk.Label(body, text="Fields:  " + "   ".join(f"{{{k}}} {v}" for k, v in RENAME_FIELDS.items())
                             + ".   Disc / Track parts and the extension are always kept.",
                  style="Muted.TLabel", wraplength=1040, justify="left").pack(anchor="w", pady=(6, 8))

        foot = ttk.Frame(body, padding=(0, 12, 0, 0))
        foot.pack(side="bottom", fill="x")
        inner = ttk.Frame(body)
        inner.pack(fill="both", expand=True)
        tv = ttk.Treeview(inner, columns=("new", "status"), selectmode="none")
        for col, text, width in (("#0", "Now", 420), ("new", "Becomes", 420), ("status", "", 190)):
            tv.heading(col, text=text, anchor="w")
            tv.column(col, width=width, anchor="w", stretch=col != "status")
        sb = ttk.Scrollbar(inner, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tv.tag_configure("bad", foreground="#e8a33d")

        summary = ttk.Label(foot, style="Muted.TLabel")
        summary.pack(side="left")
        show_same = tk.BooleanVar(value=False)
        fix_titles = tk.BooleanVar(value=True)
        ttk.Checkbutton(body, text="Use the LaunchBox name as {title} for games you matched by hand or whose file "
                                   "name isn't a proper title (e.g. Final_Fantasy_IV_US)", variable=fix_titles,
                        command=lambda: refresh()).pack(anchor="w", pady=(0, 8), before=inner)
        state = {"rows": [], "after": None}

        def refresh():
            state["after"] = None
            lb_names, fix = {}, set()
            if self.platform:
                m = lb.Matcher(self.platform)
                lb_names = {k: m.games[gid]["n"] for k, gid in self.lb_links.items() if gid in m.games}
                if fix_titles.get():  # hand-picked, or only matched after cleaning up a scene-style name
                    fix = {k for k in lb_names
                           if self.lb_kind.get(k) == "manual" or not m.matches_as_written(title_of(k))}
                    for k in fix:
                        if self.lb_kind.get(k) != "manual":
                            lb_names[k] = m.proper_name(title_of(k), self.lb_links[k]) or lb_names[k]
            keys = list(self.units) if scope.get() == 0 else [k for k in scopes[scope.get()][1] if k in self.units]
            state["rows"] = rows = plan_renames(
                [(k, self.units[k]["paths"], lb_names.get(k), k in fix) for k in keys], template.get())
            tv.delete(*tv.get_children())
            for i, r in enumerate(rows):
                if r["status"] == "same" and not show_same.get():
                    continue
                ok = r["status"] in ("rename", "same")
                tv.insert("", "end", iid=str(i), text=os.path.basename(r["old"]),
                          values=(os.path.basename(r["new"]) if ok else "", "" if ok else r["status"]),
                          tags=() if ok else ("bad",))
            n = Counter("rename" if r["status"] == "rename" else "same" if r["status"] == "same" else "skip"
                        for r in rows)
            summary.config(text=f"{n['rename']:,} files to rename  ·  {n['same']:,} already match  ·  "
                                f"{n['skip']:,} skipped")
            apply_btn.config(state="normal" if n["rename"] else "disabled")

        def on_type(*_):
            if state["after"]:
                win.after_cancel(state["after"])
            state["after"] = win.after(250, refresh)

        def apply():
            pairs = [(r["old"], r["new"]) for r in state["rows"] if r["status"] == "rename"]
            if not messagebox.askyesno("Rename files", f"Rename {len(pairs):,} files? You can undo this later "
                                                       "with Undo….", parent=win):
                return
            self.cfg["rename_templates"][self.system] = template.get()
            self.save_cfg()
            done, failed = apply_renames(pairs)
            esde = self._carry_over(done, failed) if done else ""
            self._carry_matches(done, self.system)
            if done:
                batches = self._read_renames()
                batches.append({"time": datetime.datetime.now().isoformat(timespec="seconds"),
                                "system": self.system, "template": template.get(), "renames": done})
                try:
                    self._write_renames(batches)
                except OSError as e:
                    failed.append(f"rename log (undo won't know about this run): {e}")
            self._after_rename(done)
            refresh()
            if failed:
                messagebox.showerror(f"Renamed {len(done)} files, {len(failed)} problems",
                                     "\n".join(failed[:30]) + esde, parent=win)
            else:
                self.toast(f"Renamed {len(done):,} files.{esde.replace(chr(10), ' ')}")

        apply_btn = ttk.Button(foot, text="Rename", style="Accent.TButton", command=apply)
        apply_btn.pack(side="right")
        ttk.Button(foot, text="Close", command=win.destroy).pack(side="right", padx=(0, 6))
        ttk.Button(foot, text="Undo…", command=lambda: self.undo_renames_dialog(win, refresh)).pack(side="right",
                                                                                                   padx=(0, 16))
        ttk.Checkbutton(foot, text="Show unchanged", variable=show_same, command=refresh).pack(side="right",
                                                                                                padx=(0, 16))
        template.trace_add("write", on_type)
        win.bind("<Escape>", lambda e: win.destroy())
        refresh()
        entry.focus_set()

    def undo_renames_dialog(self, parent, on_done):
        batches = self._read_renames()
        win = tk.Toplevel(parent)
        win.title("Undo renames")
        win.transient(parent)
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        body = ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Put old file names back", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text=f"Every rename run is logged in {self.renames_log()}. Undo newer runs first if the "
                             "same games were renamed more than once.", style="Muted.TLabel", wraplength=640,
                  justify="left").pack(anchor="w", pady=(2, 10))
        foot = ttk.Frame(body, padding=(0, 12, 0, 0))
        foot.pack(side="bottom", fill="x")
        tv = ttk.Treeview(body, columns=("system", "template", "left"), selectmode="extended", height=10)
        for col, text, width, anchor in (("#0", "When", 170, "w"), ("system", "System", 90, "w"),
                                         ("template", "Pattern", 220, "w"), ("left", "Still renamed", 130, "e")):
            tv.heading(col, text=text, anchor=anchor)
            tv.column(col, width=width, anchor=anchor, stretch=col == "template")
        tv.pack(fill="both", expand=True)

        def fill():
            tv.delete(*tv.get_children())
            for i in range(len(batches) - 1, -1, -1):
                b = batches[i]
                left = sum(os.path.lexists(n) for _, n in b["renames"])
                tv.insert("", "end", iid=str(i), text=b["time"].replace("T", "  "),
                          values=(b["system"], b["template"], f"{left} / {len(b['renames'])} files"))
        fill()

        def undo():
            sel = sorted((int(i) for i in tv.selection()), reverse=True)  # newest first undoes in order
            if not sel:
                return
            back, failed = [], []
            for i in sel:
                pairs = [(n, o) for o, n in batches[i]["renames"] if os.path.lexists(n)]
                done, errs = apply_renames(pairs)
                back += done
                failed += errs
                if done:  # ES-DE media + gamelist and hand-picked matches follow the names back
                    failed += scraper.carry_over(done, batches[i]["system"], self.cfg["roms_root"],
                                                 find_gamelist(self.cfg["roms_root"], batches[i]["system"]))[2]
                    self._carry_matches(done, batches[i]["system"])
                undone = {o for _, o in done}
                left = [[o, n] for o, n in batches[i]["renames"] if os.path.lexists(n) and o not in undone]
                if left:
                    batches[i]["renames"] = left
                else:
                    del batches[i]
            try:
                self._write_renames(batches)
            except OSError as e:
                failed.append(f"rename log: {e}")
            fill()
            self._after_rename(back)
            on_done()
            if failed:
                messagebox.showerror(f"Undid {len(back)} renames, {len(failed)} problems", "\n".join(failed[:30]),
                                     parent=win)
            else:
                self.toast(f"Put back {len(back):,} file names.")

        ttk.Button(foot, text="Undo selected", style="Accent.TButton", command=undo).pack(side="right")
        ttk.Button(foot, text="Close", command=win.destroy).pack(side="right", padx=(0, 6))
        if not batches:
            ttk.Label(foot, text="Nothing logged yet.", style="Muted.TLabel").pack(side="left")
        win.bind("<Escape>", lambda e: win.destroy())

    # ---------- manual LaunchBox match ----------
    def _row_menu(self, tv, e):
        row = tv.identify_row(e.y)
        if not row:
            return
        if row not in tv.selection():
            tv.selection_set(row)
        tv.focus(row)
        menu = tk.Menu(self.root, tearoff=0)
        state = "normal" if self.platform and lb.platforms() else "disabled"
        menu.add_command(label="Set LaunchBox match…", state=state, command=lambda: self.match_dialog(row))
        menu.add_command(label="Clear hand-picked match", command=lambda: self._set_match(row, None, clear=True),
                         state="normal" if self.lb_kind.get(row) == "manual" else "disabled")
        menu.tk_popup(e.x_root, e.y_root)

    def _set_match(self, key, gid, clear=False):
        try:
            lb.set_manual(self.platform, title_of(key), gid, clear)
        except OSError as e:
            messagebox.showerror("Couldn't save match", str(e))
            return
        self.rescan()

    def match_dialog(self, key):
        m = lb.Matcher(self.platform)
        if not m.ok:
            messagebox.showinfo("No LaunchBox data", "Download LaunchBox data for this platform first.")
            return
        title = title_of(key)
        same = sum(title_of(k) == title for k in self.units)
        win = tk.Toplevel(self.root)
        win.title("LaunchBox match")
        win.transient(self.root)
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        body = ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"Which {self.platform} game is this?", style="Section.TLabel").pack(anchor="w")
        g = self.ratings.get(key)
        now = f"Now: {g['n']} ({self.lb_kind.get(key)})" if g else "Now: no match"
        also = f"  ·  applies to all {same} versions titled “{title}”" if same > 1 else ""
        ttk.Label(body, text=f"{self._label(key)}\n{now}{also}", style="Muted.TLabel", wraplength=640,
                  justify="left").pack(anchor="w", pady=(2, 10))

        query = tk.StringVar(value=title)
        entry = ttk.Entry(body, textvariable=query)
        entry.pack(fill="x")
        foot = ttk.Frame(body, padding=(0, 12, 0, 0))
        foot.pack(side="bottom", fill="x")
        tv = ttk.Treeview(body, columns=("rating", "genre"), selectmode="browse", height=14)
        for col, text, width, anchor in (("#0", "LaunchBox game", 360, "w"), ("rating", "Rating", 110, "center"),
                                         ("genre", "Genre", 170, "w")):
            tv.heading(col, text=text, anchor=anchor)
            tv.column(col, width=width, anchor=anchor, stretch=col == "#0")
        tv.pack(fill="both", expand=True, pady=(8, 0))
        pending = {"id": None}

        def search():
            pending["id"] = None
            tv.delete(*tv.get_children())
            for gid in m.search(query.get()):
                x = m.games[gid]
                alts = [a for a in m.alts.get(gid, []) if lb.norm(a) != lb.norm(x["n"])]
                name = x["n"] + (f"   (aka {alts[0]})" if alts else "")
                rating = "—" if x["r"] is None else f"{ui.stars(x['r'])}  {x['r']:.1f}  ({x['v']})"
                tv.insert("", "end", iid=gid, text=name, values=(rating, ", ".join(x["g"])))
            kids = tv.get_children()
            if kids:
                tv.selection_set(self.lb_links.get(key) if self.lb_links.get(key) in kids else kids[0])

        def on_type(*_):
            if pending["id"]:
                win.after_cancel(pending["id"])
            pending["id"] = win.after(250, search)

        def use(gid):
            win.destroy()
            self._set_match(key, gid)

        def use_selected(*_):
            sel = tv.selection()
            if sel:
                use(sel[0])

        query.trace_add("write", on_type)
        tv.bind("<Double-Button-1>", use_selected)
        entry.bind("<Return>", use_selected)
        ttk.Button(foot, text="Use selected", style="Accent.TButton", command=use_selected).pack(side="right")
        ttk.Button(foot, text="Cancel", command=win.destroy).pack(side="right", padx=(0, 6))
        ttk.Button(foot, text="Not in LaunchBox", command=lambda: use(None)).pack(side="left")
        if self.lb_kind.get(key) == "manual":
            ttk.Button(foot, text="Back to automatic",
                       command=lambda: (win.destroy(), self._set_match(key, None, clear=True))).pack(side="left",
                                                                                                    padx=(6, 0))
        win.bind("<Escape>", lambda e: win.destroy())
        search()
        entry.focus_set()
        entry.select_range(0, "end")


def prune_empty(folder, stop):
    """Remove folder and its parents while they're empty, never going above stop."""
    stop = os.path.realpath(stop)
    folder = os.path.realpath(folder)
    while folder.startswith(stop + os.sep):
        try:
            os.rmdir(folder)
        except OSError:
            return
        folder = os.path.dirname(folder)


if __name__ == "__main__":
    if "--install-desktop" in sys.argv[1:]:
        print(f"Added RetroShelf to the {'Start' if is_windows() else 'app'} menu: {desktop.install()}")
        sys.exit()
    if is_windows():
        try:  # crisp text on high-DPI screens instead of a blurry bitmap-stretched window
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    App(tk.Tk(className="retroshelf")).root.mainloop()
