"""Tools → Rename files: rename the open system's games to a pattern, with ES-DE's media and gamelist following,
and undo earlier runs (logged in renames.json in the data folder)."""
import os
from collections import Counter

import launchbox as lb
import nps
import renaming
import scraper
from rules import unit_key
from rpc import ctx, method, need_free


def _log():
    return os.path.join(ctx["data_dir"], "renames.json")


def _plan(keys, template, fix_titles):
    sc = ctx["need_system"]()
    names, fix = renaming.lb_names(sc, fix_titles)
    keys = [k for k in keys if k in sc.units] if keys is not None else list(sc.units)
    return sc, renaming.plan_renames([(k, sc.units[k]["paths"], names.get(k), k in fix) for k in keys], template)


@method
def rename_info():
    sc = ctx["need_system"]()
    return {"arcade": sc.system in renaming.ARCADE_SYSTEMS, "fields": renaming.RENAME_FIELDS,
            "template": ctx["cfg"].get("rename_templates", {}).get(sc.system, renaming.DEFAULT_TEMPLATE),
            "default": renaming.DEFAULT_TEMPLATE}


@method
def rename_plan(template, keys=None, fix_titles=True):
    """-> rows {key, old, new (file names), status} and how many of each."""
    _, rows = _plan(keys, template, fix_titles)
    n = Counter("rename" if r["status"] == "rename" else "same" if r["status"] == "same" else "skip" for r in rows)
    return {"rows": [{"key": r["key"], "old": os.path.basename(r["old"]), "new": os.path.basename(r["new"]),
                      "status": r["status"]} for r in rows],
            "rename": n["rename"], "same": n["same"], "skip": n["skip"]}


def _platform_of(system):
    sc = ctx["current"]["sc"]
    if sc and system == sc.system:
        return sc.platform
    return lb.resolve_platform(system, nps.FULL_NAMES.get(system), ctx["cfg"]["platform_overrides"])


def _follow(done, system):
    """Hand flips follow the games to their new names; then the system is opened again."""
    cfg = ctx["cfg"]
    sc = ctx["current"]["sc"]
    new_key = {}
    for old, new in done:
        k = sc.file_to_unit.get(os.path.basename(old)) if sc and sc.system == system else None
        if k:
            new_key[k] = unit_key(os.path.basename(new))
    st = cfg["system_state"].get(system)
    if st and st.get("flips") and new_key:
        st["flips"] = {new_key.get(k, k): v for k, v in st["flips"].items()}
        ctx["save_cfg"]()


@method
def rename_apply(template, keys=None, fix_titles=True):
    cfg = ctx["cfg"]
    with ctx["state_lock"]:
        sc, rows = _plan(keys, template, fix_titles)
        need_free(sc.system)
        pairs = [(r["old"], r["new"]) for r in rows if r["status"] == "rename"]
        cfg.setdefault("rename_templates", {})[sc.system] = template
        ctx["save_cfg"]()
        done, failed = renaming.apply_renames(pairs)
        media = entries = 0
        if done:
            media, entries, problems = scraper.carry_over(done, sc.system, sc.roms_root,
                                                          scraper.gamelist_path(sc.roms_root, sc.system))
            failed += problems
            renaming.carry_matches(done, sc.platform)
            try:
                renaming.write_log(_log(), renaming.read_log(_log()) + [renaming.log_entry(sc.system, template, done)])
            except OSError as e:
                failed.append(f"rename log (undo won't know about this run): {e}")
        _follow(done, sc.system)
    result = ctx["open_system"](sc.system)
    result["renamed"] = {"files": len(done), "failed": failed, "media": media, "entries": entries}
    return result


@method
def rename_runs():
    out = []
    for i, b in enumerate(renaming.read_log(_log())):
        out.append({"id": i, "time": b["time"], "system": b["system"], "template": b["template"],
                    "files": len(b["renames"]), "left": sum(os.path.lexists(n) for _, n in b["renames"])})
    return out[::-1]


@method
def rename_undo(ids):
    """Put old names back for these runs (ids from rename_runs); the renderer rescans afterwards."""
    cfg = ctx["cfg"]
    with ctx["state_lock"]:
        batches = renaming.read_log(_log())
        need_free(*{batches[i]["system"] for i in ids if 0 <= i < len(batches)})
        back, failed, left = renaming.undo_batches(batches, ids, cfg["roms_root"], _platform_of)
        try:
            renaming.write_log(_log(), left)
        except OSError as e:
            failed.append(f"rename log: {e}")
        if ctx["current"]["sc"]:
            _follow(back, ctx["current"]["sc"].system)
    return {"back": len(back), "failed": failed}
