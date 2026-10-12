"""The whole ROMs folder at once: Library → Storage overview (lib/storage.py), Tools → Library health check
(lib/health.py) and Tools → Find duplicates (lib/dupes.py). A check's findings stay here between requests, so the
window can fix or move them by their ids."""
import os

import dupes
import frontend
import health
import library
import nps
import scraper
import shelf
import storage
from rules import unit_key
from rpc import ctx, method, need_free, progress, stopped

found = {"problems": [], "sets": [], "done": set()}  # the last health check and duplicates search
LOW_SPACE = 0.05, 2 << 30  # the ROMs drive is nearly full: under 5% free, or under 2 GB


def _root():
    root = ctx["cfg"]["roms_root"]
    if not root or not os.path.isdir(root):
        raise FileNotFoundError("Pick your ROMs folder first")
    return root


def _label(root, code):
    """'psx — Sony PlayStation', as the Tk app's system_label."""
    name, full, _ = library.read_systeminfo(os.path.join(root, code))
    full = full if name == code and full else nps.FULL_NAMES.get(code)
    return f"{code} — {full}" if full else code


def _report(job):
    """lib's progress(text, fraction) -> "progress" events for job."""
    report = progress(job)
    return lambda text, fraction: report(text, round(fraction * 1000), 1000)


# ---------- Storage overview ----------
@method
def storage_scan(job):
    """-> {"systems": [...] biggest first, each with its biggest games, "drive": {free, total} or None}."""
    root = _root()
    try:
        systems = storage.scan(root, unit_key, _report(job), stopped(job))
    except InterruptedError:
        return {"stopped": True}
    d = storage.drive(root)
    out = []
    for s in systems:
        rows = s.biggest()
        out.append({"code": s.name, "label": _label(root, s.name), "games": len(s.games), "size": s.size,
                    "media": s.media, "total": s.total, "compressible": s.compressible,
                    "biggest": rows[:200], "more": max(0, len(rows) - 200)})
    return {"systems": out, "drive": {"free": d[0], "total": d[1]} if d else None}


# ---------- Library health check ----------
@method
def health_scan(job, system=None):
    """Look in every system folder, or just system. -> {"kinds": [[kind, heading]], "problems": [...]}"""
    root = _root()
    try:
        problems = health.scan(root, {system} if system else None, _report(job), stopped(job))
    except InterruptedError:
        return {"stopped": True}
    found["problems"] = problems
    return {"kinds": health.KINDS,
            "problems": [{"id": i, "kind": p.kind, "system": p.system, "name": p.name, "detail": p.detail,
                          "fix": p.fix, "frees": health.frees([p])} for i, p in enumerate(problems)]}


def _problems(ids):
    return [found["problems"][i] for i in ids if 0 <= i < len(found["problems"])]


@method
def health_fix_plan(ids):
    """What fixing these does, to ask first. -> {"lines", "deletes" (files deleted for good)}"""
    lines, deletes = health.fix_plan(_problems(ids))
    return {"lines": lines, "deletes": deletes}


@method
def health_fix(ids):
    """Fix these problems. -> {"done": {id: what was done}, "failed": {id: why}, "systems": systems changed}"""
    root = _root()
    done, failed, touched = {}, {}, set()
    with ctx["state_lock"]:
        need_free(*{found["problems"][i].system for i in ids if 0 <= i < len(found["problems"])})
        for i in ids:
            if not 0 <= i < len(found["problems"]):
                continue
            p = found["problems"][i]
            try:
                what = health.fix(p, root)
                done[i] = what[:1].upper() + what[1:]
                touched.add(p.system)
            except (OSError, RuntimeError) as e:
                failed[i] = f"{p.system}/{p.name}: {e}"
    return {"done": done, "failed": failed, "systems": sorted(touched)}


# ---------- Find duplicates ----------
@method
def dupes_scan(job):
    """-> {"sets": [{id, kind, title, keep, extra, copies: [{rel, system, fmt, size}]}], "holding", "same_drive"}"""
    root = _root()
    try:
        sets = dupes.find(root, unit_key, _report(job), stopped(job))
    except InterruptedError:
        return {"stopped": True}
    found["sets"], found["done"] = sets, set()
    holding = shelf.holding_root(ctx["cfg"])
    return {"sets": [{"id": i, "kind": s.kind, "title": s.title, "keep": s.keep, "extra": s.extra,
                      "copies": [{"rel": c.rel, "system": c.system, "fmt": c.fmt, "size": c.size} for c in s.copies]}
                     for i, s in enumerate(sets)],
            "holding": os.path.join(holding, "to_delete"), "same_drive": shelf.on_same_drive(holding, root)}


@method
def dupes_resolve(keep):
    """Move the copies not kept to the holding folder. keep: {set id: index of the copy that stays}
    -> {"moved": files, "sets": ids done, "systems": systems changed, "problems": [...]}"""
    root = _root()
    picked = {}
    for sid, k in keep.items():
        sid = int(sid)
        if 0 <= sid < len(found["sets"]) and sid not in found["done"] and 0 <= k < len(found["sets"][sid].copies):
            found["sets"][sid].keep = k
            picked[sid] = found["sets"][sid]
    with ctx["state_lock"]:
        need_free(*{c.system for s in picked.values() for c in s.copies})
        moves, problems = dupes.resolve(list(picked.values()), root, shelf.holding_root(ctx["cfg"]),
                                        scraper.es_de_running())
        found["done"].update(picked)
        if moves:
            log = os.path.join(ctx["data_dir"], "moves.json")
            try:
                shelf.write_moves(log, shelf.read_moves(log) + dupes.log_batches(moves))
            except OSError as e:
                problems.append(f"move log (Restore won't know about this move): {e}")
    return {"moved": sum(len(v) for v in moves.values()), "sets": sorted(picked), "systems": sorted(moves),
            "problems": problems}


# ---------- Things to fix ----------
@method
def issues_scan(job):
    """Everything the other checks would find, for the header's "things to fix". Looks quietly: a check that fails
    is left out. -> {"issues": [{"kind", "count", "text", "cmd": the menu command that fixes it}]}"""
    cfg, out, stop = ctx["cfg"], [], stopped(job)
    quiet = lambda text, fraction: None
    if not frontend.frontend_installed(cfg.get("esde_bases", ())):
        out.append({"kind": "frontend", "count": 1, "cmd": "setup",
                    "text": "ES-DE isn't installed" if frontend.is_windows() else "RetroDECK / ES-DE isn't installed"})
    root = cfg["roms_root"]
    if not root or not os.path.isdir(root):
        return {"issues": out}
    d = storage.drive(root)
    if d and d[1] and (d[0] < LOW_SPACE[0] * d[1] or d[0] < LOW_SPACE[1]):
        out.append({"kind": "storage", "count": 1, "cmd": "storage",
                    "text": f"The ROMs drive is nearly full: {frontend.human_size(d[0])} free"})
    try:
        n = len(health.scan(root, None, quiet, stop))
        if n:
            out.append({"kind": "health", "count": n, "cmd": "health",
                        "text": f"{n} library problem{'s' if n != 1 else ''}"})
        n = len(dupes.find(root, unit_key, quiet, stop))
        if n:
            out.append({"kind": "dupes", "count": n, "cmd": "dupes",
                        "text": f"{n} duplicate game{'s' if n != 1 else ''}"})
    except InterruptedError:
        return {"stopped": True}
    except OSError:
        pass
    return {"issues": out}
