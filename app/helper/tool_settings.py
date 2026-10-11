"""☰ → Settings: the window's own options (videos, gamepad, animations, details panel) and which LaunchBox platform
the open system uses."""
import os

import handoff
import launchbox as lb
from rpc import ctx, method

OPTIONS = ("play_videos", "stream_videos", "gamepad", "animations", "show_details", "check_updates")


@method
def settings():
    """The window's options; with a system open, also its LaunchBox platform and the ones to pick from."""
    cfg = ctx["cfg"]
    out = {k: bool(cfg.get(k, k != "stream_videos")) for k in OPTIONS}
    out["light"] = cfg.get("theme") == "light"  # the Tk version's setting, so it carries over
    sc = ctx["current"]["sc"]
    if sc:
        overrides = cfg["platform_overrides"]
        out["platform"] = {"system": sc.system, "fullname": ctx["current"]["fullname"] or sc.system,
                           "current": sc.platform or "", "override": sc.system in overrides,
                           "automatic": lb.resolve_platform(sc.system, ctx["current"]["fullname"]) or "",
                           "choices": lb.platforms()}
    return out


@method
def set_option(name, value):
    if name == "light":
        ctx["cfg"]["theme"] = "light" if value else "dark"
    elif name in OPTIONS:
        ctx["cfg"][name] = bool(value)
    else:
        raise ValueError(f"No option {name!r}")
    ctx["save_cfg"]()
    return settings()


@method
def set_platform(platform=None, automatic=False):
    """Use this LaunchBox platform for the open system ("" for none), or go back to the automatic one. -> the
    system again, scanned with it."""
    sc = ctx["need_system"]()
    with ctx["state_lock"]:
        overrides = ctx["cfg"]["platform_overrides"]
        if automatic:
            overrides.pop(sc.system, None)
        else:
            overrides[sc.system] = platform or ""
        ctx["save_cfg"]()
    return ctx["open_system"](sc.system)


@method
def import_old(folder):
    """Bring the old (Tk) RetroShelf's settings, logs, matches and downloaded data over from its folder (lib/handoff.py).
    -> {"copied": [...], "overview": the main window's overview with them}."""
    if not handoff.has_data(folder):
        raise FileNotFoundError(f"No RetroShelf settings in {folder}: pick the folder with retroshelf.py in it.")
    with ctx["state_lock"]:
        copied = handoff.copy_data(folder, ctx["data_dir"])
        ctx["reload_cfg"]()
        ctx["current"]["sc"] = None
        roms = ctx["cfg"]["roms_root"]
        if roms and not os.path.isdir(roms):
            ctx["cfg"]["roms_root"] = ""
        return {"copied": copied, "overview": ctx["overview"]()}
