#!/usr/bin/env python3
"""ROM Pruner: preview and move unwanted ROMs out of an ES-DE / RetroDECK roms folder, for any system.

Pick a roms folder and a system; the console comes from the folder name (ES-DE system name), checked against
its systeminfo.txt, and is mapped to a LaunchBox platform for ratings/genres (override it in the dropdown).

Patterns: one per line, case-insensitive by default. Only * and ? are wildcards, so [b] and (USA) match literally.
Plain text with no * or ? matches anywhere in the name; with wildcards the pattern must match the whole name.
  mario           -> move anything containing "mario"
  *(Demo)*        -> move matches
  !*Mario*        -> keep matches, even if a preset/pattern/list/rating hit them
  # comment       -> ignored
Double-click a game in either pane to flip it manually (beats everything, including played-game protection).
Multi-file games (cue/bin tracks, multi-disc + m3u) are handled as one unit and move together.
Moved files go to <holding folder>/<to_delete|review_low_value>/<system>/, outside roms so ES-DE won't list them.
For ps3, psvita and psp a NoPayStation… button downloads and installs PSN packages (see nps.py).
"""
import json, os, queue, re, shutil, sys, threading
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(APP_DIR, "vendor"))
import sv_ttk  # noqa: E402  (vendored Sun Valley theme, MIT)

import launchbox as lb  # noqa: E402
import nps  # noqa: E402
import nps_gui  # noqa: E402
import scraper  # noqa: E402

UI_FONTS = ["Inter", "Segoe UI", "Noto Sans", "Cantarell", "Ubuntu", "DejaVu Sans"]
MONO_FONTS = ["JetBrains Mono", "Fira Code", "Noto Sans Mono", "DejaVu Sans Mono", "monospace"]
PALETTE = {
    "dark": {"field": "#272727", "fg": "#fafafa", "border": "#3a3a3a", "accent": "#57c8ff", "sel": "#2f60d8",
             "muted": "#9a9a9a", "stripe": "#232323", "manual": "#ffb347", "keep": "#7fd17f", "move": "#ff8a80"},
    "light": {"field": "#ffffff", "fg": "#1c1c1c", "border": "#d4d4d4", "accent": "#005fb8", "sel": "#2f60d8",
              "muted": "#6b6b6b", "stripe": "#f3f3f3", "manual": "#b05000", "keep": "#1e7b34", "move": "#c42b1c"},
}
PATTERN_EXAMPLES = (
    "mario         name contains \"mario\"\n"
    "(Japan)       name contains \"(Japan)\"\n"
    "*(Beta)*      * = any text, ? = one character\n"
    "0002*         name starts with 0002\n"
    "!kart         ! = always keep these\n"
    "# note        ignored"
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
                        "list, rating, genre or region would move them."),
    ("# comment", "Lines starting with # are ignored. Blank lines are ignored too."),
]
PATTERN_NOTES = (
    "Patterns are checked against the game name and each of its file names (with extension), so .nds, .zip "
    "or .cue work. Case is ignored unless you untick Ignore case.\n"
    "Priority, highest first: double-click flips  ›  Protect played games  ›  ! keep rules  ›  everything else "
    "that moves a game (presets, patterns, list, ratings, genres, regions)."
)
CONFIG = os.path.join(APP_DIR, "config.json")
DESTS = ["to_delete", "review_low_value"]
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
    "Dora|Barbie|Bratz|Hannah Montana|High School Musical|SpongeBob|Winx|Littlest Pet Shop|Monster High|"
    "Scooby-?Doo|Sesame Street|Shrek|Tinker ?Bell|Hello Kitty|My Little Pony|Strawberry Shortcake|Bakugan|"
    "Build-?A-?Bear|Imagine[: ]|Petz|Chihuahua|Cooking Mama|Diner Dash|Dress ?Up|Fashion|Horsez|Pony Friends|"
    "Care Bears|Go, ?Diego|Nickelodeon|Disney|Fairly Odd ?Parents|Phineas|Hannah|iCarly|Trollz|Dreamworks|"
    "Madagascar|Bee Movie|Chicken Little|Garfield|Marmaduke|Alvin and the Chipmunks|Cheetah Girls|WordWorld|"
    "Clifford|Curious George|Elmo|Thomas (?:and|&) Friends"
)
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
SPORTS_RE = re.compile(rf"\b(?:{SPORTS_WORDS})\b", re.I)
KIDS_RE = re.compile(rf"\b(?:{KIDS_WORDS})\b", re.I)
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


def keyword_preset(rx, exceptions):
    def run(keys):
        return {k for k in keys if rx.search(k) and not any(x.lower() in k.lower() for x in exceptions)}
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
    "Kids / licensed tie-ins": keyword_preset(KIDS_RE, KIDS_EXCEPT),
    "Region dupes (keep 1 per title)": region_dupes,
}
DUPES = "Region dupes (keep 1 per title)"
PARTIAL_EXT = (".part", ".crdownload", ".tmp")


def wildcard_re(pat, icase):
    if "*" not in pat and "?" not in pat:
        pat = f"*{pat}*"  # plain text means "name contains this"
    rx = re.escape(pat).replace(r"\*", ".*").replace(r"\?", ".")
    return re.compile(rf"^{rx}$", re.IGNORECASE if icase else 0)


def human(n):
    return f"{n / 1073741824:.2f} GB" if n >= 1073741824 else f"{n / 1048576:.1f} MB"


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


def find_gamelist(roms_root, system):
    for base in (os.path.join(roms_root, "..", "ES-DE"), os.path.expanduser("~/ES-DE"),
                 os.path.expanduser("~/.emulationstation")):
        p = os.path.join(base, "gamelists", system, "gamelist.xml")
        if os.path.exists(p):
            return p
    return None


def guess_roms_root():
    for p in (os.path.join(APP_DIR, "..", "retrodeck", "roms"), os.path.join(APP_DIR, "..", "roms"),
              os.path.join(APP_DIR, "..", "..", "roms"), os.path.expanduser("~/retrodeck/roms"),
              os.path.expanduser("~/ROMs")):
        if os.path.isdir(p):
            return os.path.realpath(p)
    return ""


class App:
    def __init__(self, root):
        self.root = root
        root.title("ROM Pruner")
        root.geometry("1600x950")

        self.cfg = {"roms_root": "", "holding_root": "", "system": "", "platform_overrides": {}, "theme": "dark",
                    "region_priority": DEFAULT_PRIORITY}
        try:
            with open(CONFIG, encoding="utf-8") as f:
                self.cfg.update(json.load(f))
        except (OSError, ValueError):
            pass
        if not self.cfg["roms_root"] or not os.path.isdir(self.cfg["roms_root"]):
            self.cfg["roms_root"] = guess_roms_root()

        self.units = {}          # key -> {"paths": [abs path], "size": int}
        self.file_to_unit = {}
        self.ratings = {}        # key -> lb game dict
        self.played = set()
        self.preset_hits = {}
        self.list_names = set()
        self.manual = {}
        self.after_id = None
        self.sort_by = ("#0", False)
        self.to_move, self.kept, self.why = [], [], {}
        self.dupes_key = None

        sv_ttk.set_theme(self.cfg["theme"])
        self._fonts()
        self._build()
        self.apply_theme()
        self.load_roms_root(self.cfg["roms_root"])

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
        st.configure("Treeview", rowheight=28)
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
        self.region_lb.configure(activestyle="none", **field)
        for tv in (self.keep_tv, self.move_tv):
            tv.tag_configure("odd", background=c["stripe"])
            tv.tag_configure("manual", foreground=c["manual"])
        self.root.configure(bg=ttk.Style().lookup("TFrame", "background"))

    def toggle_theme(self):
        self.cfg["theme"] = "dark" if self.dark_var.get() else "light"
        self.save_cfg()
        self.apply_theme()

    # ---------- config ----------
    def save_cfg(self):
        try:
            with open(CONFIG, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=1)
        except OSError:
            pass

    def holding_root(self):
        return self.cfg["holding_root"] or os.path.join(os.path.dirname(self.cfg["roms_root"].rstrip("/")), "pruned")

    # ---------- UI ----------
    def _build(self):
        outer = ttk.Frame(self.root, padding=(16, 12, 16, 8))
        outer.pack(fill="both", expand=True)

        # header: title + theme switch
        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Label(head, text="ROM Pruner", style="Title.TLabel").pack(side="left")
        self.dark_var = tk.BooleanVar(value=self.cfg["theme"] == "dark")
        ttk.Checkbutton(head, text="Dark mode", style="Switch.TCheckbutton", variable=self.dark_var,
                        command=self.toggle_theme).pack(side="right")

        # source bar
        bar = ttk.Frame(outer, padding=(0, 10, 0, 0))
        bar.pack(fill="x")
        bar.columnconfigure(1, weight=1)
        ttk.Label(bar, text="ROMs folder").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.roms_var = tk.StringVar()
        self.roms_entry = ttk.Entry(bar, textvariable=self.roms_var, state="readonly")
        self.roms_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(bar, text="Browse…", command=self.browse_roms).grid(row=0, column=2, padx=(6, 18))
        ttk.Label(bar, text="System").grid(row=0, column=3, sticky="w", padx=(0, 8))
        self.system_var = tk.StringVar()
        self.system_cb = ttk.Combobox(bar, textvariable=self.system_var, state="readonly", width=30)
        self.system_cb.grid(row=0, column=4)
        self.system_cb.bind("<<ComboboxSelected>>", lambda e: self.load_system(self.system_codes[self.system_cb.current()]))
        self.nps_btn = ttk.Button(bar, text="NoPayStation…", command=lambda: nps_gui.NpsWindow(self))
        self.nps_btn.grid(row=0, column=5, padx=(6, 0))
        ttk.Label(bar, text="LaunchBox").grid(row=0, column=6, sticky="w", padx=(18, 8))
        self.platform_var = tk.StringVar()
        self.platform_cb = ttk.Combobox(bar, textvariable=self.platform_var, state="readonly", width=24)
        self.platform_cb.grid(row=0, column=7)
        self.platform_cb.bind("<<ComboboxSelected>>", lambda e: self.set_platform())
        self.lb_btn = ttk.Button(bar, text="Download LaunchBox data", command=self.update_lb)
        self.lb_btn.grid(row=0, column=8, padx=(6, 0))
        ttk.Button(bar, text="Scrape metadata…", command=self.scrape_dialog).grid(row=0, column=9, padx=(6, 0))
        self.sys_info = ttk.Label(outer, style="Muted.TLabel", padding=(0, 6, 0, 0))
        self.sys_info.pack(fill="x")

        # filter cards
        top = ttk.Frame(outer, padding=(0, 10, 0, 0))
        top.pack(fill="x")

        presets = ttk.LabelFrame(top, text="Presets", padding=(12, 8))
        presets.pack(side="left", fill="y")
        self.preset_vars = {}
        for name in list(PRESETS) + ["Partial downloads (.part)"]:
            v = tk.BooleanVar(value=False)
            ttk.Checkbutton(presets, text=name, variable=v, command=self.refresh).pack(anchor="w", pady=1)
            self.preset_vars[name] = v
            if name == DUPES:
                prow = ttk.Frame(presets)
                prow.pack(fill="x", padx=(28, 0), pady=(0, 4))
                self.priority = [p.strip() for p in self.cfg["region_priority"].split(",") if p.strip()]
                self.prio_lbl = ttk.Label(prow, style="Muted.TLabel")
                self.prio_lbl.pack(side="left")
                ttk.Button(prow, text="Edit…", command=self.edit_priority).pack(side="right", padx=(6, 0))
                self._show_priority()
        ttk.Separator(presets).pack(fill="x", pady=8)
        self.protect_played = tk.BooleanVar(value=True)
        self.played_cb = ttk.Checkbutton(presets, text="Protect played games", style="Switch.TCheckbutton",
                                         variable=self.protect_played, command=self.refresh)
        self.played_cb.pack(anchor="w")

        rat = ttk.LabelFrame(top, text="LaunchBox ratings", padding=(12, 8))
        rat.pack(side="left", fill="y", padx=(10, 0))
        self.rat_info = ttk.Label(rat, style="Muted.TLabel")
        self.rat_info.pack(anchor="w", pady=(0, 4))
        row = ttk.Frame(rat)
        row.pack(anchor="w", pady=1)
        self.use_rating = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Rating below", variable=self.use_rating, command=self.refresh).pack(side="left")
        self.rating_max = tk.DoubleVar(value=2.5)
        ttk.Spinbox(row, from_=0, to=5, increment=0.25, width=5, textvariable=self.rating_max,
                    command=self.refresh).pack(side="left", padx=6)
        ttk.Label(row, text="/ 5").pack(side="left")
        row2 = ttk.Frame(rat)
        row2.pack(anchor="w", pady=1)
        ttk.Label(row2, text="only if votes ≥", style="Muted.TLabel").pack(side="left", padx=(28, 0))
        self.min_votes = tk.IntVar(value=3)
        ttk.Spinbox(row2, from_=1, to=500, increment=1, width=5, textvariable=self.min_votes,
                    command=self.refresh).pack(side="left", padx=6)
        for var in (self.rating_max, self.min_votes):
            var.trace_add("write", lambda *_: self._debounce())
        self.use_unrated = tk.BooleanVar(value=False)
        ttk.Checkbutton(rat, text="Unrated / no LaunchBox match", variable=self.use_unrated,
                        command=self.refresh).pack(anchor="w", pady=1)

        gen = ttk.LabelFrame(top, text="Move genres", padding=(12, 8))
        gen.pack(side="left", fill="y", padx=(10, 0))
        ttk.Label(gen, text="ctrl / shift-click for several", style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        gf = ttk.Frame(gen)
        gf.pack(fill="both", expand=True)
        self.genre_lb = tk.Listbox(gf, selectmode="extended", height=6, exportselection=False, width=22,
                                   font="SunValleyBodyFont")
        gsb = ttk.Scrollbar(gf, orient="vertical", command=self.genre_lb.yview)
        self.genre_lb.configure(yscrollcommand=gsb.set)
        self.genre_lb.pack(side="left", fill="both", expand=True)
        gsb.pack(side="right", fill="y")
        self.genre_lb.bind("<<ListboxSelect>>", lambda e: self.refresh())
        self.genre_names = []

        reg = ttk.LabelFrame(top, text="Regions", padding=(12, 8))
        reg.pack(side="left", fill="y", padx=(10, 0))
        self.region_mode = tk.StringVar(value=REGION_MODES[0])
        mode_cb = ttk.Combobox(reg, textvariable=self.region_mode, values=REGION_MODES, state="readonly", width=17)
        mode_cb.pack(fill="x", pady=(0, 4))
        mode_cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        rf = ttk.Frame(reg)
        rf.pack(fill="both", expand=True)
        self.region_lb = tk.Listbox(rf, selectmode="extended", height=6, exportselection=False, width=18,
                                    font="SunValleyBodyFont")
        rsb = ttk.Scrollbar(rf, orient="vertical", command=self.region_lb.yview)
        self.region_lb.configure(yscrollcommand=rsb.set)
        self.region_lb.pack(side="left", fill="both", expand=True)
        rsb.pack(side="right", fill="y")
        self.region_lb.bind("<<ListboxSelect>>", lambda e: self.refresh())
        self.region_names = []

        pat = ttk.LabelFrame(top, text="Name patterns", padding=(12, 8))
        pat.pack(side="left", fill="both", expand=True, padx=(10, 0))
        prow = ttk.Frame(pat)
        prow.pack(fill="x", pady=(0, 4))
        ttk.Label(prow, text="One rule per line", style="Muted.TLabel").pack(side="left")
        ttk.Button(prow, text="Help", command=self.pattern_help).pack(side="right")
        self.icase = tk.BooleanVar(value=True)
        ttk.Checkbutton(prow, text="Ignore case", variable=self.icase, command=self.refresh).pack(side="right",
                                                                                                padx=(0, 8))
        self.pat_text = tk.Text(pat, height=6, width=30, font=(self.mono, 10), undo=True)
        self.pat_text.pack(fill="both", expand=True)
        self.pat_text.bind("<<Modified>>", self._on_modified)
        self.pat_hint = tk.Label(self.pat_text, text=PATTERN_EXAMPLES, justify="left", anchor="nw",
                                 font=(self.mono, 10))
        self.pat_hint.bind("<Button-1>", lambda e: self.pat_text.focus_set())
        self._toggle_hint()

        # search + list tools
        flt = ttk.Frame(outer, padding=(0, 12, 0, 0))
        flt.pack(fill="x")
        ttk.Label(flt, text="Search").pack(side="left")
        self.view_filter = tk.StringVar()
        self.view_filter.trace_add("write", lambda *_: self.render())
        ttk.Entry(flt, textvariable=self.view_filter).pack(side="left", fill="x", expand=True, padx=(8, 16))
        self.list_lbl = ttk.Label(flt, text="List: none", style="Muted.TLabel")
        self.list_lbl.pack(side="left", padx=(0, 6))
        ttk.Button(flt, text="Load list…", command=self.load_list).pack(side="left")
        ttk.Button(flt, text="Clear list", command=self.clear_list).pack(side="left", padx=(4, 16))
        ttk.Button(flt, text="Reset flips", command=self.reset_manual).pack(side="left")
        ttk.Button(flt, text="Rescan", command=self.rescan).pack(side="left", padx=(4, 0))

        # footer: status left, move controls right (packed before the panes so it never gets squeezed out)
        foot = ttk.Frame(outer, padding=(0, 10, 0, 0))
        foot.pack(side="bottom", fill="x")
        ttk.Button(foot, text="Move files", style="Accent.TButton", command=self.execute).pack(side="right")
        ttk.Button(foot, text="Export list…", command=self.export).pack(side="right", padx=(0, 6))
        ttk.Button(foot, text="Change…", command=self.browse_holding).pack(side="right", padx=(0, 16))
        self.hold_lbl = ttk.Label(foot, style="Muted.TLabel")
        self.hold_lbl.pack(side="right", padx=(0, 6))
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
        tv.column("#0", width=210, minwidth=160, stretch=True)
        tv.column("why", width=150, minwidth=60, stretch=True)
        tv.column("region", width=95, minwidth=60, stretch=False)
        tv.column("rating", width=105, minwidth=80, stretch=False, anchor="center")
        tv.column("genre", width=120, minwidth=60, stretch=False)
        tv.column("size", width=80, minwidth=60, stretch=False, anchor="e")
        sb = ttk.Scrollbar(inner, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        panes.add(f, weight=1)
        return lbl, tv

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

    # ---------- region priority ----------
    def _show_priority(self):
        shown = " › ".join(self.priority[:3]) + (" …" if len(self.priority) > 3 else "")
        self.prio_lbl.config(text=f"Prefer  {shown}")

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
        path = filedialog.askdirectory(initialdir=self.cfg["roms_root"] or os.path.expanduser("~"),
                                       title="Pick the roms folder (the one containing nds/, snes/, …)")
        if path:
            self.load_roms_root(path)

    def browse_holding(self):
        path = filedialog.askdirectory(initialdir=self.holding_root(), title="Where moved files go")
        if path:
            self.cfg["holding_root"] = path
            self.save_cfg()
            self.hold_lbl.config(text=self.holding_root())

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
        self.hold_lbl.config(text=self.holding_root())
        if not self.system_codes:
            self.sys_info.config(text="No systems with ROMs found — pick your roms folder with Browse…")
            return
        sys_code = self.cfg["system"] if self.cfg["system"] in self.system_codes else self.system_codes[0]
        self.load_system(sys_code)

    def load_system(self, system):
        self.system = system
        self.cfg["system"] = system
        self.save_cfg()
        self.system_cb.current(self.system_codes.index(system))
        self.folder = os.path.join(self.cfg["roms_root"], system)
        name, fullname, exts = read_systeminfo(self.folder)
        self.fullname = fullname if name == system else nps.FULL_NAMES.get(system)
        self.exts = exts if name == system else None
        warn = "" if name in (None, system) else f"  ⚠ systeminfo.txt here is for '{name}' — ignored"
        self.sys_info.config(text=f"{self.folder}  ·  {self.fullname or 'unknown console'}{warn}")
        if system in nps.CONSOLES:
            self.nps_btn.grid()
        else:
            self.nps_btn.grid_remove()
        self.manual, self.list_names = {}, set()
        self.list_lbl.config(text="List: none")
        self._refresh_platform_choices()
        self.rescan()

    def _refresh_platform_choices(self):
        plats = lb.platforms()
        self.platform_cb["values"] = ["(none)"] + plats
        self.platform = lb.resolve_platform(self.system, self.fullname, self.cfg["platform_overrides"])
        self.platform_var.set(self.platform or "(none)")
        self.lb_btn.config(text="Update LaunchBox data" if plats else "Download LaunchBox data")

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
                        self.lb_btn.config(state="normal")
                        if val:
                            messagebox.showerror("LaunchBox update failed", str(val))
                        else:
                            self._refresh_platform_choices()
                            self.rescan()
                        return
            except queue.Empty:
                self.root.after(200, poll)

        self.lb_btn.config(state="disabled")
        threading.Thread(target=work, daemon=True).start()
        poll()

    # ---------- scraper ----------
    def gamelist_path(self):
        return find_gamelist(self.cfg["roms_root"], self.system) or os.path.realpath(
            os.path.join(self.cfg["roms_root"], "..", "ES-DE", "gamelists", self.system, "gamelist.xml"))

    def scrape_dialog(self):
        if not self.platform:
            messagebox.showinfo("No LaunchBox platform", "Pick a LaunchBox platform for this system first.")
            return
        if not lb.has_details():
            messagebox.showinfo("Update needed", "Click “Update LaunchBox data” once first — the scraper needs "
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
        ttk.Label(body, text="Fills gaps only: existing text and images are never replaced, and play counts, "
                             "favorites and hidden flags are left alone.", style="Muted.TLabel",
                  wraplength=520, justify="left").pack(anchor="w", pady=(2, 12))

        scope_box = ttk.LabelFrame(body, text="Games", padding=(12, 8))
        scope_box.pack(fill="x")
        scope = tk.IntVar(value=0)
        for i, (label, keys) in enumerate(scopes):
            linked = sum(k in self.lb_links for k in keys)
            ttk.Radiobutton(scope_box, text=f"{label}  —  {len(keys):,} games, {linked:,} matched in LaunchBox",
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
            jobs = [(scraper.primary_file(self.units[k]["paths"]), self.lb_links[k], self.regions[k])
                    for k in keys if k in self.lb_links]
            q = queue.Queue()
            args = (jobs, self.platform, self.system, self.cfg["roms_root"], self.gamelist_path(), do_text.get(),
                    media, lambda m, d, t: q.put(("p", m, d, t)), lambda: state["cancel"])

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
                                f"{len(keys) - len(jobs)} games had no exact LaunchBox match."))
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
        self.refresh()

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

        self.ratings = {}
        self.lb_links = {}  # key -> LaunchBox id, exact title matches only (used to group region dupes)
        matched = rated = 0
        if self.platform:
            m = lb.Matcher(self.platform)
            if m.ok:
                for k in keys:
                    gid, g, kind = m.match(title_of(k))
                    if g:
                        self.ratings[k] = g
                        if kind == "exact":
                            self.lb_links[k] = gid
                        matched += 1
                        rated += g["r"] is not None
                m.save()
        if not lb.platforms():
            self.rat_info.config(text="No LaunchBox data — click Download")
        elif not self.platform:
            self.rat_info.config(text="No LaunchBox platform for this system")
        else:
            self.rat_info.config(text=f"Matched {matched}/{len(keys)}, {rated} rated")

        gcount = Counter(x for g in self.ratings.values() for x in g["g"])
        self.genre_names = [g for g, _ in gcount.most_common()]
        self.genre_lb.delete(0, "end")
        for g in self.genre_names:
            self.genre_lb.insert("end", f"{g} ({gcount[g]})")

        self.regions = {k: regions_of(k) or ("(none)",) for k in keys}
        rcount = Counter(r for rs in self.regions.values() for r in rs)
        self.region_names = [r for r, _ in rcount.most_common()]
        self.region_lb.delete(0, "end")
        for r in self.region_names:
            self.region_lb.insert("end", f"{r} ({rcount[r]})")

    # ---------- lists / manual ----------
    def load_list(self):
        path = filedialog.askopenfilename(initialdir=APP_DIR, filetypes=[("Text", "*.txt"), ("All", "*")])
        if not path:
            return
        with open(path, encoding="utf-8") as f:
            names = {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}
        hits = {self.file_to_unit.get(n, n) for n in names}
        self.list_names |= hits & self.units.keys()
        missing = len(hits - self.units.keys())
        self.list_lbl.config(text=f"List: {len(self.list_names)} games ({missing} names not found)")
        self.refresh()

    def clear_list(self):
        self.list_names = set()
        self.list_lbl.config(text="List: none")
        self.refresh()

    def reset_manual(self):
        self.manual = {}
        self.refresh()

    def flip(self, tv, to_move):
        for iid in tv.selection():
            self.manual[iid] = to_move
        self.refresh()

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
                if key in self.list_names:
                    reasons.append("list")
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
            tv.delete(*tv.get_children())
            for i, k in enumerate(shown):
                g = self.ratings.get(k)
                rating = "—" if not g or g["r"] is None else f"★ {g['r']:.1f}  ({g['v']})"
                tags = (("odd",) if i % 2 else ()) + (("manual",) if k in self.manual else ())
                tv.insert("", "end", iid=k, text=self._label(k),
                          values=(self.why[k], ", ".join(self.regions[k]), rating, ", ".join(g["g"]) if g else "",
                                  human(self.units[k]["size"])),
                          tags=tags)
            size = sum(self.units[k]["size"] for k in keys)
            extra = f"  ·  {len(shown)} shown" if q else ""
            lbl.config(text=f"{title}   {len(keys):,} games  ·  {human(size)}{extra}")
        nfiles = sum(len(u["paths"]) for u in self.units.values())
        self.status.config(text=f"{len(self.units):,} games ({nfiles:,} files)  ·  {len(self.manual)} flipped (orange)"
                                f"  ·  double-click to flip  ·  click a column to sort")

    # ---------- output ----------
    def export(self):
        path = filedialog.asksaveasfilename(initialdir=APP_DIR, initialfile=f"{self.system}_move.txt",
                                            defaultextension=".txt")
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
        if not messagebox.askyesno("Confirm move", f"Move {len(self.to_move)} games ({nfiles} files, {human(size)}) "
                                                   f"into\n{dest_dir}/ ?{extra_note}"):
            return
        os.makedirs(dest_dir, exist_ok=True)
        base = os.path.dirname(os.path.realpath(self.cfg["roms_root"]).rstrip("/"))
        moved, failed = 0, []
        for k in self.to_move:
            for p in self.units[k]["paths"] + self.units[k]["extra"]:
                if p in self.units[k]["extra"]:  # keep the path under retrodeck/ so it can be moved back by hand
                    rel = os.path.relpath(os.path.realpath(p), base)
                    target = os.path.join(dest_dir, "installed", rel if not rel.startswith("..") else
                                          os.path.join("external", os.path.realpath(p).lstrip("/")))
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                else:
                    target = os.path.join(dest_dir, os.path.basename(p))
                try:
                    if os.path.exists(target):
                        raise OSError("already exists in holding folder")
                    shutil.move(p, target)
                    moved += 1
                except OSError as e:
                    failed.append(f"{os.path.basename(p)}: {e}")
        self.manual = {}
        self.rescan()
        if failed:
            messagebox.showerror(f"Moved {moved} files, {len(failed)} failed", "\n".join(failed[:30]))
        else:
            messagebox.showinfo("Done", f"Moved {moved} files to {dest_dir}/")


if __name__ == "__main__":
    App(tk.Tk()).root.mainloop()
