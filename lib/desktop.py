"""App-menu entry: ~/.local/share/applications/retroshelf.desktop pointing at this copy of RetroShelf."""
import os, sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WM_CLASS = "Retroshelf"  # what Tk reports for className="retroshelf"; lets the taskbar match window and entry


def entry_path():
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
        "Comment=Prune, scrape, rename and install games for ES-DE / RetroDECK",
        f"Exec={_quote(exe)} {_quote(os.path.join(APP_DIR, 'retroshelf.py'))}",
        f"Path={APP_DIR}",
        f"Icon={os.path.join(APP_DIR, 'assets', 'icon-256.png')}",
        "Terminal=false",
        "Categories=Game;",
        "Keywords=ROM;ES-DE;RetroDECK;emulation;LaunchBox;NoPayStation;",
        f"StartupWMClass={WM_CLASS}",
        "",
    ])


def is_installed():
    """True only if the entry exists and points at this copy (a moved folder needs reinstalling)."""
    try:
        with open(entry_path(), encoding="utf-8") as f:
            return f.read() == _contents()
    except OSError:
        return False


def install():
    path = entry_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(_contents())
    os.chmod(path, 0o755)  # some desktops only trust executable entries
    return path
