"""Moving from the Tk app (a folder with retroshelf.py) to the standalone Electron app (app/): where the new app keeps
its data, and bringing the settings, logs, hand-picked matches and downloaded data over. The Tk app does it when you
get the new app; the new app does it by itself the first time it finds the old copy (from its app-menu entry), and
from ☰ → Settings for a folder you pick. Then it offers to remove the old copy."""
import json, os, re, shutil, sys

import desktop
from fsutil import is_windows, shortcut_text, write_json

JSON_FILES = ("config.json", "moves.json", "renames.json", "matches.json")
APP_NAME = "RetroShelf"  # Electron's userData folder is named after the app's productName


def app_data_dir():
    """Where the new app keeps config.json and the rest (Electron's userData folder)."""
    if is_windows():
        base = os.environ.get("APPDATA") or os.path.expanduser(os.path.join("~", "AppData", "Roaming"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_NAME)


def has_data(folder):
    return any(os.path.isfile(os.path.join(folder, f)) for f in JSON_FILES)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _merge(old, new, new_wins=False):
    """What to keep when both apps have the file: the old app's settings and matches win (bringing them over is
    the point) unless new_wins, and logs keep every entry from both."""
    if isinstance(old, dict) and isinstance(new, dict):
        return {**old, **new} if new_wins else {**new, **old}
    if isinstance(old, list) and isinstance(new, list):
        return new + [x for x in old if x not in new]
    return old


def copy_data(src, dst, new_wins=False):
    """Bring src's data into dst. Files dst doesn't have are copied; JSON files both have are merged (see _merge);
    downloaded data in cache/ is copied where dst doesn't have it yet. -> [names of what was brought over]."""
    if os.path.realpath(src) == os.path.realpath(dst):
        return []
    os.makedirs(dst, exist_ok=True)
    done = []
    for name in JSON_FILES:
        old = _read(os.path.join(src, name))
        if old is None:
            continue
        new = _read(os.path.join(dst, name))
        write_json(os.path.join(dst, name), old if new is None else _merge(old, new, new_wins), indent=1,
                   ensure_ascii=False)
        done.append(name)
    cache = os.path.join(src, "cache")
    copied = 0
    for root, _dirs, files in os.walk(cache):
        for f in files:
            target = os.path.join(dst, "cache", os.path.relpath(os.path.join(root, f), cache))
            if os.path.exists(target):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                shutil.copy2(os.path.join(root, f), target)
                copied += 1
            except OSError:
                pass
    if copied:
        done.append("cache")
    return done


# ---------- the old copy itself ----------
OLD_GUESSES = ("retroshelf", "RetroShelf", "retroshelf-main", os.path.join("Downloads", "retroshelf"),
               os.path.join("Downloads", "retroshelf-main"), os.path.join("Applications", "retroshelf"))
_SCRIPT = re.compile(r"""((?:[A-Za-z]:)?[\\/][^"'\n\x00]*?[\\/])retroshelf\.py""")  # in Exec= or the .lnk


def is_old_app(folder):
    return bool(folder) and os.path.isfile(os.path.join(folder, "retroshelf.py")) and \
        os.path.isdir(os.path.join(folder, "lib"))


def old_entry():
    """The folder the app-menu entry (Windows: Start menu shortcut) starts the old app from, or None when the entry
    is missing or already starts the new app."""
    path = desktop.entry_path()
    if is_windows():
        text = shortcut_text(path)
    else:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return None
    for m in _SCRIPT.finditer(text):
        folder = m.group(1).rstrip("\\/")
        if is_old_app(folder):
            return folder
    return None


def find_old(home=None):
    """-> the old app's folder (where its app-menu entry points, else the usual places), or None."""
    folder = old_entry()
    if folder:
        return folder
    home = home or os.path.expanduser("~")
    for rel in OLD_GUESSES:
        if is_old_app(os.path.join(home, rel)):
            return os.path.join(home, rel)
    return None


def remove_old(folder, keep=()):
    """Delete the old app's folder, and its app-menu entry if that still starts it. Only a folder that is the old
    app (retroshelf.py and lib/ in it), and never one holding any of keep (the new app, its data, the ROMs)."""
    if not is_old_app(folder):
        raise ValueError(f"{folder} isn't the old RetroShelf")
    real = os.path.realpath(folder)
    for k in keep:
        if k and (os.path.realpath(k) + os.sep).startswith(real + os.sep):
            raise ValueError(f"{folder} holds {k}: not removing it")
    if old_entry() == folder:
        try:
            os.remove(desktop.entry_path())
        except OSError:
            pass
    shutil.rmtree(folder)
