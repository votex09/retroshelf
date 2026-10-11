"""First-run setup: install RetroDECK (Linux) or ES-DE (Windows) for someone who doesn't have it yet, then point
RetroShelf at the new ROMs folder. lib/frontend.py does the installing; this is the window's side of it."""
import os

import frontend
from fsutil import is_windows
from rpc import ctx, method, progress, stopped


def _name():
    return "ES-DE" if is_windows() else "RetroDECK"


@method
def setup_info():
    """What the setup window shows first: an install that's already there, whether flatpak is missing (Linux),
    and the places games could go."""
    windows = is_windows()
    cfg = ctx["cfg"]
    found = (frontend.esde_installs(cfg.get("esde_bases", ())) if windows
             else [r for r in [frontend.retrodeck_roms()] if r])
    return {"windows": windows, "name": _name(), "found": found[0] if found else "",
            "flatpak": windows or bool(frontend.flatpak()), "flatpak_guide": frontend.FLATPAK_SETUP,
            "guide": frontend.ESDE_GUIDE, "home": os.path.expanduser("~"),
            "choices": [{"kind": kind, "label": label, "folder": folder, "free": frontend.free_bytes(folder),
                         "games": frontend.games_folder(kind, folder)}
                        for kind, label, folder in frontend.storage_choices()]}


@method
def setup_target(folder):
    """For a folder the user picked themselves: where the games would go, and the free space there."""
    folder = os.path.normpath(folder)
    return {"folder": folder, "free": frontend.free_bytes(folder), "games": frontend.games_folder("custom", folder)}


@method
def setup_install(job, kind, folder, shortcut=True):
    """Install into folder. Each line of output comes as a "progress" event for job (done/total out of 1000 when
    a download's size is known). -> {"roms", "notes"} on Windows, where it's finished; {"steps"} on Linux, where
    RetroDECK's own first-time setup comes next (setup_launch, then setup_poll until it's done)."""
    if kind == "home" and folder:
        try:
            os.makedirs(folder, exist_ok=True)  # Windows: ~\Games
        except OSError:
            pass
    if not folder or not os.path.isdir(folder) or not os.access(folder, os.W_OK):
        raise PermissionError(f"RetroShelf can't write to {folder}. Pick another place.")
    send, stop = progress(job), stopped(job)

    def report(line=None, fraction=None):
        send(line or "", int(fraction * 1000) if fraction is not None else 0, 1000 if fraction is not None else 0)
    try:
        if is_windows():
            return _install_esde(folder, shortcut, report, stop)
        if frontend.retrodeck_installed():
            report("RetroDECK is already installed.")
        else:
            frontend.install_retrodeck(report, stop)
    except InterruptedError:
        return {"stopped": True}
    return {"steps": frontend.retrodeck_steps(kind, folder), "expected": frontend.games_folder(kind, folder)}


def _install_esde(base, shortcut, report, stop):
    if os.path.exists(frontend.esde_exe(base)):
        report(f"ES-DE is already in {frontend.esde_dir(base)}: using it.")
    else:
        report("Finding ES-DE's latest version …")
        version, pkg = frontend.esde_release()
        report(f"Downloading ES-DE {version} ({pkg['filename']}) …")
        zpath = os.path.join(base, pkg["filename"])
        last = [-1]

        def got(done, total):
            if total and int(done * 100 / total) != last[0]:
                last[0] = int(done * 100 / total)
                report(None, done / total)
        frontend.download(pkg["url"], zpath, pkg.get("md5"), got, stop)
        report("Unpacking …")
        try:
            frontend.unpack_esde(zpath, base)
        finally:
            os.unlink(zpath)
    report("Creating a folder for each system …")
    roms = frontend.create_system_dirs(base)
    notes = []
    if shortcut:
        try:
            frontend.add_esde_shortcut(base)
            notes.append("ES-DE is in your Start menu.")
        except OSError as e:
            notes.append(f"Couldn't add ES-DE to the Start menu: {e}")
    cfg = ctx["cfg"]
    if base not in cfg["esde_bases"]:
        cfg["esde_bases"].append(base)
        ctx["save_cfg"]()
    return {"roms": roms, "notes": notes}


@method
def setup_launch():
    """Start RetroDECK, which runs its first-time setup in its own window."""
    frontend.launch_retrodeck()


@method
def setup_poll():
    """RetroDECK's ROMs folder once its first-time setup has made one, else ""."""
    return frontend.retrodeck_roms() or ""


@method
def setup_done(roms=None):
    """Don't offer setup by itself again; with roms, use that as the ROMs folder. -> the main window's overview,
    plus tips for what to do next."""
    with ctx["state_lock"]:
        cfg = ctx["cfg"]
        cfg["setup_offered"] = True
        if roms:
            cfg["roms_root"] = os.path.realpath(roms)
            ctx["current"]["sc"] = None
        ctx["save_cfg"]()
        out = ctx["overview"]()
    if roms:
        if is_windows():
            tips = [f"Next, add emulators: put them in {os.path.join(os.path.dirname(roms), 'Emulators')} (for example "
                    "RetroArch) or install them normally. ES-DE's user guide lists which one each system uses."]
        else:
            tips = ["Put BIOS files in the bios folder next to roms; RetroDECK's Configurator can check them."]
        tips.append("Add games with the store windows in the ☰ menu (Homebrew Hub, itch.io, PDRoms, free arcade "
                    "games), or copy your own dumps into the system folders.")
        out["tips"] = tips
    return out
