"""Small file and platform helpers shared by the app and lib modules."""
import json, os, subprocess


def is_windows():
    """A function rather than a constant, so tests can pretend to be on the other system."""
    return os.name == "nt"


# keeps a console window from flashing up when a windowed (pythonw) RetroShelf runs a command-line tool
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def write_json(path, data, **kw):
    """Write JSON through a temp file and a rename, so a crash or full disk mid-write never leaves a truncated
    file behind (config.json, matches.json and the logs would otherwise read back as empty and be overwritten)."""
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, **kw)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def outside_rel(path, pathmod=os.path):
    """An absolute path as a relative one, so it can be rebuilt under another folder:
    '/home/me/x' -> 'home/me/x', 'D:\\Emu\\x' -> 'D\\Emu\\x', '\\\\nas\\share\\x' -> 'nas\\share\\x'."""
    drive, rest = pathmod.splitdrive(path)
    parts = [p for p in drive.replace(":", "").replace("\\", "/").split("/") if p]
    parts += [p for p in rest.replace("\\", "/").split("/") if p]
    return pathmod.join(*parts) if parts else ""


def held_rel(path, base, pathmod=os.path):
    """Where a file outside roms (installed emulator data) goes under <holding>/installed/: its path relative to
    base (the folder holding roms, e.g. retrodeck/), or external/<its full path> when it isn't under base or is
    on another drive (Windows can't express a path from C: relative to D:)."""
    try:
        rel = pathmod.relpath(path, base)
    except ValueError:
        rel = pathmod.pardir
    if rel == pathmod.pardir or rel.startswith(pathmod.pardir + pathmod.sep):
        rel = pathmod.join("external", outside_rel(path, pathmod))
    return rel
