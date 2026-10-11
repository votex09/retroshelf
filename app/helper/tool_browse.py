"""Picking a folder or files inside the window: the desktop's own dialog can't be worked with a gamepad, so while one
is in use the window lists folders itself (app/renderer/pad.js: browseBox)."""
import os

import frontend
from rpc import method

MAX_ENTRIES = 3000


def places():
    """[{"label", "path"}]: the home folder, Downloads, then drives and SD cards."""
    home = os.path.expanduser("~")
    out = [{"label": "Home", "path": home}]
    downloads = os.path.join(home, "Downloads")
    if os.path.isdir(downloads):
        out.append({"label": "Downloads", "path": downloads})
    for kind, label, folder in frontend.storage_choices():
        if kind == "drive":
            out.append({"label": label, "path": folder})
    return out


@method
def browse(path=None, files=False):
    """What's in a folder. -> {"path", "parent", "sep", "entries": [{"name", "dir"}], "places", "error", "more"}.
    path: where to look (a missing one: its nearest folder that exists; none: home). files: list files too.
    Hidden entries (a leading dot) are left out; folders come first."""
    path = os.path.abspath(os.path.expanduser(path or "~"))
    while not os.path.isdir(path) and os.path.dirname(path) != path:
        path = os.path.dirname(path)
    entries, error = [], ""
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    is_dir = e.is_dir()
                except OSError:
                    continue
                if is_dir or files:
                    entries.append({"name": e.name, "dir": is_dir})
    except OSError as e:
        error = e.strerror or str(e)
    entries.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    parent = os.path.dirname(path)
    return {"path": path, "parent": parent if parent != path else None, "sep": os.sep, "entries": entries[:MAX_ENTRIES],
            "more": max(0, len(entries) - MAX_ENTRIES), "places": places(), "error": error}
