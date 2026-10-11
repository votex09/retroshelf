#!/usr/bin/env python3
"""RetroShelf's Python side for the Electron app: the window asks, this answers, over stdin / stdout.

Protocol: one JSON object per line.
    window -> helper   {"id": 1, "method": "systems", "params": {"roms": "/home/deck/retrodeck/roms"}}
    helper -> window   {"id": 1, "result": [...]}
                       {"id": 1, "error": {"type": "FileNotFoundError", "message": "..."}}
                       {"event": "name", "data": {...}}   (not tied to a request: progress, things that changed)
Each request runs on its own thread, so a slow one (a download, a scan) doesn't hold up the rest; answers can come
back in any order, matched by id. Anything else the helper prints goes to stderr, never stdout.

The work itself is RetroShelf's own lib/ modules, the same ones the Tk app uses."""
import json, os, platform, shutil, sys, threading, traceback

if getattr(sys, "frozen", False):  # bundled by PyInstaller: lib/ modules are inside the bundle
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.path.join(APP_DIR, "lib"))

import library  # noqa: E402

PROTOCOL = 1
_out = sys.stdout
_lock = threading.Lock()
METHODS = {}


def method(fn):
    METHODS[fn.__name__] = fn
    return fn


def send(obj):
    line = json.dumps(obj, ensure_ascii=False)
    with _lock:
        _out.write(line + "\n")
        _out.flush()


def event(name, data=None):
    send({"event": name, "data": data})


# ---------- methods the window can call ----------
@method
def hello():
    return {"protocol": PROTOCOL, "python": platform.python_version(), "platform": sys.platform,
            "frozen": bool(getattr(sys, "frozen", False))}


@method
def roms_folder():
    """Where RetroDECK / ES-DE keeps its ROMs on this computer, or "" when it can't be found."""
    return library.guess_roms_root(APP_DIR)


@method
def systems(roms):
    if not roms or not os.path.isdir(roms):
        raise FileNotFoundError(f"No folder at {roms!r}")
    return [{"code": code, "name": name, "games": n} for code, name, n in library.systems(roms)]


@method
def disk(path):
    """-> {"free", "total"} bytes on the drive path is on, or None."""
    while path and not os.path.exists(path) and os.path.dirname(path) != path:
        path = os.path.dirname(path)
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {"free": usage.free, "total": usage.total}


# ---------- plumbing ----------
def handle(msg):
    rid = msg.get("id")
    try:
        fn = METHODS.get(msg.get("method"))
        if fn is None:
            raise LookupError(f"No method called {msg.get('method')!r}")
        result = fn(**(msg.get("params") or {}))
        send({"id": rid, "result": result})
    except Exception as e:  # the window shows it; the helper keeps going
        traceback.print_exc(file=sys.stderr)
        send({"id": rid, "error": {"type": type(e).__name__, "message": str(e)}})


def main():
    global _out
    _out = sys.stdout
    sys.stdout = sys.stderr  # stray prints from lib/ code can't corrupt the protocol
    event("ready", hello())
    running = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            send({"id": None, "error": {"type": "ValueError", "message": f"Not JSON: {line[:200]}"}})
            continue
        t = threading.Thread(target=handle, args=(msg,), daemon=True)
        t.start()
        running = [x for x in running if x.is_alive()] + [t]
    for t in running:  # the window closed our stdin: finish what was asked, then stop
        t.join()


if __name__ == "__main__":
    main()
