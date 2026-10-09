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


# a shortcut's settings travel as environment variables, so paths need no quoting inside the script
_LNK_SCRIPT = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:RS_LNK); "
               "$s.TargetPath = $env:RS_TARGET; $s.Arguments = $env:RS_ARGS; $s.WorkingDirectory = $env:RS_DIR; "
               "$s.IconLocation = $env:RS_ICON; $s.Description = $env:RS_DESC; $s.Save()")


def make_shortcut(path, target, args="", workdir="", icon="", description=""):
    """Windows .lnk via PowerShell's WScript.Shell (every Windows has it). Raises OSError if it can't."""
    env = dict(os.environ, RS_LNK=path, RS_TARGET=target, RS_ARGS=args, RS_DIR=workdir, RS_ICON=icon,
               RS_DESC=description)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-Command", _LNK_SCRIPT], env=env, capture_output=True, text=True, timeout=60,
                           creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        raise OSError(f"PowerShell didn't run: {e}") from e
    if r.returncode or not os.path.exists(path):
        raise OSError(f"PowerShell couldn't make the shortcut: {(r.stderr or r.stdout).strip()[:300]}")


def shortcut_text(path):
    """The readable text of a .lnk (target, arguments, folders are UTF-16 inside it), for searching; "" if
    unreadable. Strings can start at an odd offset, so both alignments are decoded."""
    try:
        with open(path, "rb") as f:
            data = f.read(1 << 20)
    except OSError:
        return ""
    return data.decode("utf-16-le", "replace") + "\n" + data[1:].decode("utf-16-le", "replace")
