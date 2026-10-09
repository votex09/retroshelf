"""App-menu entry pointing at this copy of RetroShelf: on Linux ~/.local/share/applications/retroshelf.desktop,
on Windows a RetroShelf shortcut in the Start menu (made with PowerShell, which every Windows has)."""
import os, subprocess, sys

from fsutil import NO_WINDOW, is_windows

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WM_CLASS = "Retroshelf"  # what Tk reports for className="retroshelf"; lets the taskbar match window and entry
DESCRIPTION = "Prune, scrape, rename and install games for ES-DE / RetroDECK"
# the shortcut's settings travel as environment variables, so paths need no quoting inside the script
PS_SCRIPT = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:RS_LNK); "
             "$s.TargetPath = $env:RS_TARGET; $s.Arguments = $env:RS_ARGS; $s.WorkingDirectory = $env:RS_DIR; "
             "$s.IconLocation = $env:RS_ICON; $s.Description = $env:RS_DESC; $s.Save()")


def menu_label():
    return "Add to Start menu" if is_windows() else "Add to app menu"


def entry_path():
    if is_windows():
        base = os.environ.get("APPDATA") or os.path.expanduser(os.path.join("~", "AppData", "Roaming"))
        return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs", "RetroShelf.lnk")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "applications", "retroshelf.desktop")


def _quote(arg):
    return '"' + "".join("\\" + c if c in '"`$\\' else c for c in arg) + '"'


def _contents():
    exe = sys.executable or "python3"
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=RetroShelf",
        "GenericName=ROM library manager",
        f"Comment={DESCRIPTION}",
        f"Exec={_quote(exe)} {_quote(os.path.join(APP_DIR, 'retroshelf.py'))}",
        f"Path={APP_DIR}",
        f"Icon={os.path.join(APP_DIR, 'assets', 'icon-256.png')}",
        "Terminal=false",
        "Categories=Game;",
        "Keywords=ROM;ES-DE;RetroDECK;emulation;LaunchBox;NoPayStation;",
        f"StartupWMClass={WM_CLASS}",
        "",
    ])


def windowed_python():
    """pythonw.exe next to the running python.exe, so the shortcut opens no console window."""
    exe = sys.executable or "pythonw.exe"
    folder, name = os.path.split(exe)
    if name.lower() == "python.exe" and os.path.exists(os.path.join(folder, "pythonw.exe")):
        return os.path.join(folder, "pythonw.exe")
    return exe


def is_installed():
    """True only if the entry exists and points at this copy (a moved folder needs reinstalling)."""
    try:
        if is_windows():  # .lnk files are binary; the folder is stored in it as UTF-16
            with open(entry_path(), "rb") as f:
                return APP_DIR.encode("utf-16-le") in f.read()
        with open(entry_path(), encoding="utf-8") as f:
            return f.read() == _contents()
    except OSError:
        return False


def install():
    path = entry_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if is_windows():
        env = dict(os.environ, RS_LNK=path, RS_TARGET=windowed_python(),
                   RS_ARGS=f'"{os.path.join(APP_DIR, "retroshelf.py")}"', RS_DIR=APP_DIR,
                   RS_ICON=os.path.join(APP_DIR, "assets", "icon.ico"), RS_DESC=DESCRIPTION)
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                "-Command", PS_SCRIPT], env=env, capture_output=True, text=True, timeout=60,
                               creationflags=NO_WINDOW)
        except subprocess.SubprocessError as e:
            raise OSError(f"PowerShell didn't finish: {e}") from e
        if r.returncode or not os.path.exists(path):
            raise OSError(f"PowerShell couldn't make the shortcut: {(r.stderr or r.stdout).strip()[:300]}")
        return path
    with open(path, "w", encoding="utf-8") as f:
        f.write(_contents())
    os.chmod(path, 0o755)  # some desktops only trust executable entries
    return path
