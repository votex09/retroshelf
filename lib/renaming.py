"""Renaming games' files to a pattern ("{title} ({region}) ({lang}) ({rev}) {tags}", No-Intro order), safely: plan
first (conflicts skip the whole game), rename through temp names, fix .cue / .m3u references, and keep a log so runs
can be undone. ES-DE media and gamelist entries follow along (scraper.carry_over). No windows; retroshelf.py (Tk)
and app/helper (Electron) both use it.

    rows = plan_renames([(key, paths, lb_name, use_lb_title)], template)
    done, failed = apply_renames([(old, new) for r in rows if r["status"] == "rename"])"""
import datetime, json, os, re
from collections import Counter

import compress
import launchbox as lb
import romimport
import scraper
from fsutil import is_windows, write_json
from library import PARTIAL_EXT
from rules import KNOWN_REGIONS, PART_RE, PREFIX_RE, TAG_RE, title_of, unit_key

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


fix_refs = compress.fix_refs  # swaps old file names for new ones inside a .cue / .m3u / .gdi


# ---------- for a whole system ----------
def lb_names(sc, fix_titles=True):
    """-> ({key: LaunchBox name}, {keys whose {title} comes from LaunchBox}) for a shelf.Scan: games matched by hand,
    or only matched once a scene-style name (Final_Fantasy_IV_US) was cleaned up."""
    names, fix = {}, set()
    if not sc.platform:
        return names, fix
    m = lb.Matcher(sc.platform)
    names = {k: m.games[gid]["n"] for k, gid in sc.lb_links.items() if gid in m.games}
    if fix_titles:
        fix = {k for k in names if sc.lb_kind.get(k) == "manual" or not m.matches_as_written(title_of(k))}
        for k in fix:
            if sc.lb_kind.get(k) != "manual":
                names[k] = m.proper_name(title_of(k), sc.lb_links[k]) or names[k]
    return names, fix


def carry_matches(done, platform):
    """Hand-picked LaunchBox matches are stored by title; copy them to the renamed games' new titles."""
    titles = {title_of(unit_key(os.path.basename(o))): title_of(unit_key(os.path.basename(n))) for o, n in done}
    titles = {o: n for o, n in titles.items() if o != n}
    if platform and titles:
        try:
            lb.copy_manual(platform, titles)
        except OSError:
            pass


def read_log(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def write_log(path, batches):
    write_json(path, batches, indent=1, ensure_ascii=False)


def log_entry(system, template, done):
    return {"time": datetime.datetime.now().isoformat(timespec="seconds"), "system": system, "template": template,
            "renames": done}


def undo_batches(batches, picks, roms_root, platform_of):
    """Put old names back for these runs (indexes into batches), newest first. platform_of(system) -> LaunchBox
    platform, for carrying hand-picked matches back. -> (pairs undone, failures, the batches still logged)"""
    batches = [dict(b) for b in batches]
    back, failed = [], []
    for i in sorted(set(picks), reverse=True):
        b = batches[i]
        pairs = [(n, o) for o, n in b["renames"] if os.path.lexists(n)]
        done, errs = apply_renames(pairs)
        back += done
        failed += errs
        if done:
            failed += scraper.carry_over(done, b["system"], roms_root, scraper.find_gamelist(roms_root, b["system"]))[2]
            carry_matches(done, platform_of(b["system"]))
        undone = {o for _, o in done}
        b["renames"] = [[o, n] for o, n in b["renames"] if os.path.lexists(n) and o not in undone]
    return back, failed, [b for b in batches if b["renames"]]
