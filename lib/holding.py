"""The holding folder: where Move puts games (<holding>/<to_delete|review_low_value>/<system>/), and the move log
(moves.json) that remembers where each file came from. Look through what's there, put games back, or delete them
for good. No windows here; retroshelf.py (Tk) and app/helper/helper.py (Electron) both use it.

    games, origin = holding_games(root, batches)    # batches: shelf.read_moves(); origin: {held path: original}
    restore_games(games, origin, roms_root, root)   -> (files back, ["name: error"], {held paths moved})
    delete_games(games, root)                       -> ({paths deleted}, ["name: error"], {system: [file names]})
    restore_batches(batches, picks, root)           -> (files back, ["name: error"], batches left)
    drop_from_log(batches, targets)                 -> batches without those held paths"""
import os, shutil

from library import PARTIAL_EXT
from rules import dir_size, unit_key

DESTS = ["to_delete", "review_low_value"]


def prune_empty(folder, stop):
    """Remove folder and its parents while they're empty, never going above stop."""
    stop = os.path.realpath(stop)
    folder = os.path.realpath(folder)
    while folder.startswith(stop + os.sep):
        try:
            os.rmdir(folder)
        except OSError:
            return
        folder = os.path.dirname(folder)


def holding_games(root, batches):
    """Games sitting in <root>/<dest>/<system>/, joined with the move log so each knows where it came from, when it
    moved, and which RPCS3 / Vita3K data went with it. -> ([game], {held path: original path})
    game: {"dest", "system", "key", "paths", "extra", "size", "moved"}"""
    origin, moved_at, extras_of = {}, {}, {}
    for b in batches:
        owner = None
        for src, target in b["moves"]:
            origin[target], moved_at[target] = src, b["time"]
            if os.sep + "installed" + os.sep in target and owner:
                extras_of.setdefault(owner, []).append(target)
            else:
                owner = target
    games = {}
    for dest in DESTS:
        base = os.path.join(root, dest)
        for system in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            folder = os.path.join(base, system)
            if not os.path.isdir(folder):
                continue
            for e in os.scandir(folder):
                if e.name.startswith(".") or (e.is_dir() and e.name == "installed"):
                    continue
                key = e.name if e.name.lower().endswith(PARTIAL_EXT) else unit_key(e.name)
                g = games.setdefault((dest, system, key), {"dest": dest, "system": system, "key": key,
                                                           "paths": [], "extra": [], "size": 0, "moved": ""})
                g["paths"].append(e.path)
                g["size"] += dir_size(e.path) if e.is_dir() else e.stat().st_size
                g["moved"] = max(g["moved"], moved_at.get(e.path, ""))
                for x in extras_of.get(e.path, []):
                    if os.path.lexists(x):
                        g["extra"].append(x)
                        g["size"] += dir_size(x) if os.path.isdir(x) else os.path.getsize(x)
    return list(games.values()), origin


def drop_from_log(batches, targets):
    out = []
    for b in batches:
        b = {**b, "moves": [m for m in b["moves"] if m[1] not in targets]}
        if b["moves"]:
            out.append(b)
    return out


def _put_back(target, src, root):
    if os.path.lexists(src):
        raise OSError("something is already at the original path")
    os.makedirs(os.path.dirname(src), exist_ok=True)
    shutil.move(target, src)
    prune_empty(os.path.dirname(target), root)


def restore_games(games, origin, roms_root, root):
    """Put games from holding_games() back where they came from (or into their system's folder when the log
    doesn't know). -> (files back, failures, {held paths moved}); drop the last from the log."""
    back, failed, done = 0, [], set()
    for g in games:
        pairs = [(p, origin.get(p) or os.path.join(roms_root, g["system"], os.path.basename(p))) for p in g["paths"]]
        pairs += [(x, origin[x]) for x in g["extra"] if x in origin]
        for target, src in pairs:
            try:
                _put_back(target, src, root)
                done.add(target)
                back += 1
            except OSError as e:
                failed.append(f"{os.path.basename(src)}: {e}")
    return back, failed, done


def delete_games(games, root):
    """Delete games from holding_games() for good. -> ({paths deleted}, failures, {system: [file names of games
    deleted whole]}) — the last is what to forget in ES-DE (scraper.forget_games)."""
    gone, failed, by_system = set(), [], {}
    for g in games:
        for p in g["paths"] + g["extra"]:
            try:
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.rmtree(p)
                else:
                    os.unlink(p)
                gone.add(p)
                prune_empty(os.path.dirname(p), root)
            except OSError as e:
                failed.append(f"{os.path.basename(p)}: {e}")
        if all(p in gone for p in g["paths"]):
            by_system.setdefault(g["system"], []).extend(os.path.basename(p.rstrip("/\\")) for p in g["paths"])
    return gone, failed, by_system


def restore_batches(batches, picks, root):
    """Undo whole Move runs: picks are indexes into batches. Newest first, so later moves are undone before
    earlier ones. -> (files back, failures, the batches still logged)"""
    batches = [dict(b) for b in batches]
    back, failed = 0, []
    for i in sorted(set(picks), reverse=True):
        remaining = []
        for src, target in reversed(batches[i]["moves"]):
            if not os.path.exists(target):
                continue  # deleted from the holding folder since; nothing to bring back
            try:
                _put_back(target, src, root)
                back += 1
            except OSError as e:
                failed.append(f"{os.path.basename(src)}: {e}")
                remaining.append([src, target])
        batches[i]["moves"] = remaining[::-1]
    return back, failed, [b for b in batches if b["moves"]]
