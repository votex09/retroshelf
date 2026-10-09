"""App-menu entry pointing at this copy of RetroShelf: on Linux ~/.local/share/applications/retroshelf.desktop,
on Windows a RetroShelf shortcut in the Start menu (made with PowerShell, which every Windows has)."""
import os, sys

from fsutil import is_windows, make_shortcut, shortcut_text

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WM_CLASS = "Retroshelf"  # what Tk reports for className="retroshelf"; lets the taskbar match window and entry
DESCRIPTION = "Prune, scrape, rename and install games for ES-DE / RetroDECK"


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
        if is_windows():  # .lnk files are binary
            return APP_DIR in shortcut_text(entry_path())
        with open(entry_path(), encoding="utf-8") as f:
            return f.read() == _contents()
    except OSError:
        return False


def install():
    path = entry_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if is_windows():
        make_shortcut(path, windowed_python(), f'"{os.path.join(APP_DIR, "retroshelf.py")}"', APP_DIR,
                      os.path.join(APP_DIR, "assets", "icon.ico"), DESCRIPTION)
        return path
    with open(path, "w", encoding="utf-8") as f:
        f.write(_contents())
    os.chmod(path, 0o755)  # some desktops only trust executable entries
    return path
