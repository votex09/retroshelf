"""File and folder pickers. On Linux, Tk's own dialog is unlike every other app's: highlighting a folder and pressing
OK can hand back the folder you're *in* instead. So the desktop's own picker is used when there is one (KDE's
kdialog, which SteamOS has, or GNOME's zenity), and Tk's only without either. Windows' Tk dialogs are native already.

Each function returns what tkinter.filedialog would: "" (or () for several files) when cancelled."""
import os, shutil, subprocess
from tkinter import TclError, filedialog, messagebox

from fsutil import is_windows


def _tool():
    """("kdialog" | "zenity", exe) for the desktop's picker, or (None, None)."""
    if is_windows() or not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return None, None
    kde = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    for name in (("kdialog", "zenity") if kde else ("zenity", "kdialog")):
        exe = shutil.which(name)
        if exe:
            return name, exe
    return None, None


def _start(initialdir):
    d = initialdir or os.path.expanduser("~")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def _attach(parent):
    """kdialog --attach: keeps its window over ours."""
    try:
        return ["--attach", str(int(parent.winfo_toplevel().wm_frame(), 16))] if parent else []
    except (ValueError, TclError):  # no window id (not mapped yet): it just won't be attached
        return []


def _run(cmd, parent):
    """Run a picker, keeping our window drawn while it's open. -> its output lines, or None if cancelled."""
    if parent:
        parent.update_idletasks()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except OSError:
        return False  # the tool didn't start: fall back to Tk
    if p.returncode != 0:
        return None
    return [line for line in p.stdout.splitlines() if line.strip()]


def _local(paths, parent):
    """Only real paths are usable: a network location the desktop hasn't mounted comes back as a URL."""
    bad = [p for p in paths if "://" in p or not os.path.isabs(p)]
    if bad:
        messagebox.showerror("Not a folder RetroShelf can open",
                             f"{bad[0]}\n\nis a network location your desktop opens itself. Mount it as a folder "
                             "first (for example under /mnt) and pick it there.", parent=parent)
        return []
    return paths


def ask_directory(parent=None, title="Choose a folder", initialdir=None):
    kind, exe = _tool()
    start = _start(initialdir)
    if kind == "kdialog":
        out = _run([exe, "--title", title, *_attach(parent), "--getexistingdirectory", start], parent)
    elif kind == "zenity":
        out = _run([exe, "--file-selection", "--directory", "--title", title,
                    "--filename", os.path.join(start, "")], parent)
    else:
        out = False
    if out is False:
        return filedialog.askdirectory(parent=parent, title=title, initialdir=start)
    picked = _local(out or [], parent)
    return os.path.normpath(picked[0]) if picked else ""


def ask_open_files(parent=None, title="Choose files", initialdir=None):
    kind, exe = _tool()
    start = _start(initialdir)
    if kind == "kdialog":
        out = _run([exe, "--title", title, *_attach(parent), "--getopenfilename", start, "--multiple",
                    "--separate-output"], parent)
    elif kind == "zenity":
        out = _run([exe, "--file-selection", "--multiple", "--separator", "\n", "--title", title,
                    "--filename", os.path.join(start, "")], parent)
    else:
        out = False
    if out is False:
        return filedialog.askopenfilenames(parent=parent, title=title, initialdir=start)
    return tuple(os.path.normpath(p) for p in _local(out or [], parent))


def ask_save_file(parent=None, title="Save as", initialdir=None, initialfile="", **tk_options):
    kind, exe = _tool()
    start = os.path.join(_start(initialdir), initialfile)
    if kind == "kdialog":
        out = _run([exe, "--title", title, *_attach(parent), "--getsavefilename", start], parent)
    elif kind == "zenity":
        out = _run([exe, "--file-selection", "--save", "--confirm-overwrite", "--title", title,
                    "--filename", start], parent)
    else:
        out = False
    if out is False:
        return filedialog.asksaveasfilename(parent=parent, title=title, initialdir=_start(initialdir),
                                            initialfile=initialfile, **tk_options)
    picked = _local(out or [], parent)
    return os.path.normpath(picked[0]) if picked else ""
