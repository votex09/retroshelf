"""The helper's plumbing, shared by helper.py and the tool modules (app/helper/tool_*.py): the method table, sending
answers and events to the window, long jobs with progress and Stop, and what the tools need from the main window
(the settings, the open system).

    @method
    def name(**params): ...            # the window calls it as retroshelf.call("name", params)

    @method
    def scrape(job, ...):              # a long job: the window passes a job id it made up
        report = progress(job)         # report(message, done, total) -> a "progress" event {job, message, done, total}
        stop = stopped(job)            # stop() -> True once the window called cancel(job)"""
import json, sys, threading

# The window speaks UTF-8 whatever the system's own encoding is (Windows': cp1252), so names like "Pokémon" and
# messages with "→" get through even when the helper isn't started with PYTHONIOENCODING=utf-8.
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # not a text stream (tests may swap them)
        pass

METHODS = {}
ctx = {}  # filled by helper.py: cfg, save_cfg, need_system, open_system, state_lock, data_dir
_out = sys.stdout
_lock = threading.Lock()
_cancelled = set()


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


def progress(job):
    def report(message, done=0, total=0):
        event("progress", {"job": job, "message": message, "done": done, "total": total})
    return report


def stopped(job):
    return lambda: job in _cancelled


@method
def cancel(job):
    """Ask a running job to stop (it stops at its next check, then answers as usual)."""
    _cancelled.add(job)


def set_output(out):
    global _out
    _out = out
