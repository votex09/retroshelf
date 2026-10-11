"""Moving from the Tk app (a folder with retroshelf.py) to the standalone Electron app (app/): where the new app keeps
its data, and bringing the settings, logs, hand-picked matches and downloaded data over. The Tk app does it when you
get the new app; the new app can do it from ☰ → Settings for a folder you pick."""
import json, os, shutil, sys

from fsutil import is_windows, write_json

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


def _merge(old, new):
    """What to keep when both apps have the file: the old app's settings and matches win (bringing them over is
    the point), and logs keep every entry from both."""
    if isinstance(old, dict) and isinstance(new, dict):
        return {**new, **old}
    if isinstance(old, list) and isinstance(new, list):
        return new + [x for x in old if x not in new]
    return old


def copy_data(src, dst):
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
        write_json(os.path.join(dst, name), old if new is None else _merge(old, new), indent=1, ensure_ascii=False)
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
