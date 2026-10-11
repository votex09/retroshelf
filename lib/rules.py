"""What RetroShelf decides about game names, without any windows: grouping files into games, region tags, the
presets (junk, sports, kids / licensed tie-ins, region duplicates), name patterns, and a few number formats.
Used by retroshelf.py (Tk) and lib/shelf.py (the Electron app's helper)."""
import os, re
from collections import defaultdict

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


def dupes_priority(priority, sel_regions, keep_only, present):
    """Priority for picking the copy to keep, adjusted so it never picks a copy the Regions filter will move.
    priority: region names, best first; present: the regions this system's games have."""
    base = [p.lower() for p in priority]
    if not sel_regions:
        return base
    sel = [r.lower() for r in sel_regions]
    present = [r.lower() for r in present]
    rest = [r for r in base if r not in sel] + [r for r in present if r not in base and r not in sel]
    chosen = [r for r in base if r in sel] + [r for r in sel if r not in base]
    return chosen + rest if keep_only else rest + chosen
