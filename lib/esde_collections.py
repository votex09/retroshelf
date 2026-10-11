"""ES-DE custom collections: the game lists ES-DE shows as their own "system" (Best of SNES, Party games …).

Each one is <ES-DE>/collections/custom-<name>.cfg, one game per line, as ES-DE writes them: games under the ROMs
folder as %ROMPATH%/<system>/<file>, others by full path. ES-DE shows the ones listed in its es_settings.xml
CollectionSystemsCustom setting; enable() adds a name there (not while ES-DE runs: it rewrites the file on exit).

    home(roms_root)                     -> the ES-DE folder (next to the ROMs folder, else ~/ES-DE)
    names(home)                         -> {name: file}
    games(path)                         -> the lines of one collection
    save(home, name, files, roms_root, replace=False) -> how many games were added
    enable(home, name)                  -> True if es_settings.xml was changed"""
import os, re
from xml.sax.saxutils import escape, unescape

BAD = re.compile(r'[\\/:*?"<>|]')


def home(roms_root):
    for p in (os.path.join(roms_root or "", "..", "ES-DE"), os.path.expanduser("~/ES-DE")):
        if os.path.isdir(p):
            return os.path.realpath(p)
    return os.path.realpath(os.path.join(roms_root or os.path.expanduser("~"), "..", "ES-DE"))


def clean_name(name):
    """A name ES-DE can use as a file name."""
    return re.sub(r"\s+", " ", BAD.sub("", name or "")).strip().strip(".")


def path_of(home_dir, name):
    return os.path.join(home_dir, "collections", f"custom-{name}.cfg")


def names(home_dir):
    folder = os.path.join(home_dir, "collections")
    out = {}
    try:
        for f in sorted(os.listdir(folder), key=str.lower):
            if f.startswith("custom-") and f.endswith(".cfg"):
                out[f[7:-4]] = os.path.join(folder, f)
    except OSError:
        pass
    return out


def games(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except OSError:
        return []


def entry(path, roms_root):
    """How ES-DE writes a game's path in a collection."""
    full = os.path.normpath(os.path.abspath(path))
    root = os.path.normpath(os.path.abspath(roms_root)) if roms_root else None
    if root and os.path.normcase(full).startswith(os.path.normcase(root) + os.sep):
        return "%ROMPATH%/" + os.path.relpath(full, root).replace(os.sep, "/")
    return full.replace(os.sep, "/")


def save(home_dir, name, files, roms_root, replace=False):
    """Add games (their files: the one ES-DE lists for each) to a collection, creating it if need be.
    -> how many weren't in it already."""
    name = clean_name(name)
    if not name:
        raise ValueError("the collection needs a name")
    path = path_of(home_dir, name)
    have = [] if replace else games(path)
    seen = {h.lower() for h in have}
    added = []
    for f in files:
        e = entry(f, roms_root)
        if e.lower() not in seen:
            seen.add(e.lower())
            added.append(e)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(line + "\n" for line in have + added)
    os.replace(tmp, path)
    return len(added)


SETTING = re.compile(r'(<string\s+name="CollectionSystemsCustom"\s+value=")([^"]*)("\s*/>)')


def enabled(home_dir):
    try:
        with open(os.path.join(home_dir, "settings", "es_settings.xml"), encoding="utf-8") as f:
            m = SETTING.search(f.read())
    except OSError:
        return []
    return [n for n in unescape(m.group(2), {"&quot;": '"'}).split(",") if n] if m else []


def enable(home_dir, name):
    """Have ES-DE show the collection. -> True if es_settings.xml changed. (A missing es_settings.xml is left
    missing: ES-DE hasn't been started yet, and asks about collections itself.)"""
    settings = os.path.join(home_dir, "settings", "es_settings.xml")
    try:
        with open(settings, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return False
    on = enabled(home_dir)
    if name in on:
        return False
    value = escape(",".join(on + [name]), {'"': "&quot;"})
    if SETTING.search(text):
        new = SETTING.sub(lambda m: m.group(1) + value + m.group(3), text, count=1)
    else:
        new = text.rstrip("\n") + f'\n<string name="CollectionSystemsCustom" value="{value}" />\n'
    tmp = settings + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    os.replace(tmp, settings)
    return True
