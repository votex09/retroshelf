#!/usr/bin/env python3
"""A throwaway RetroDECK setup for trying RetroShelf without touching a real library.

    tests/sandbox.py                    # build one in a temp folder and print where it is
    tests/sandbox.py --dir /tmp/rs      # build it there (replaced if it exists)
    tests/sandbox.py --run              # build it, then start RetroShelf on it
    tests/sandbox.py --screenshot a.png # build, start it (Linux: under a virtual display), save a screenshot, quit

Layout (HOME / USERPROFILE point at <dir>/home, so ~/ES-DE, ~/.local, the Start menu and the RPCS3 / Vita3K config
are fake too):
    <dir>/RetroShelf/            copy of this checkout: config.json, moves.json, cache/ … land here, not in the repo
    <dir>/retrodeck/roms/snes/   No-Intro style names: region dupes, junk, sports, a played game, a .part
    <dir>/retrodeck/roms/psx/    a cue/bin game and a two-disc game with an .m3u
    <dir>/retrodeck/ES-DE/gamelists/<system>/gamelist.xml
    <dir>/pruned/                the holding folder
A small LaunchBox database (ratings, genres, descriptions) is built from a generated Metadata.zip, so matching,
the rating / genre filters and the details panel work offline. Startup update checks are switched off.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, time, zipfile
from xml.sax.saxutils import escape

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNES = "Super Nintendo Entertainment System"
PSX = "Sony Playstation"

# (file name, LaunchBox name or None, rating, votes, genres)
SNES_GAMES = [
    ("Chrono Trigger (USA).sfc", "Chrono Trigger", 4.8, 900, ["Role-Playing"]),
    ("Chrono Trigger (Japan).sfc", "Chrono Trigger", 4.8, 900, ["Role-Playing"]),
    ("Super Metroid (Japan, USA) (En,Ja).sfc", "Super Metroid", 4.7, 700, ["Action", "Platform"]),
    ("Super Metroid (Europe) (En,Fr,De).sfc", "Super Metroid", 4.7, 700, ["Action", "Platform"]),
    ("Madden NFL '94 (USA).sfc", "Madden NFL '94", 3.1, 40, ["Sports"]),
    ("NBA Jam (USA) (Rev 1).sfc", "NBA Jam", 3.6, 120, ["Sports"]),
    ("Bebe's Kids (USA).sfc", "Bebe's Kids", 1.2, 25, ["Beat 'em Up"]),
    ("Star Fox (USA) (Beta).sfc", "Star Fox", 4.1, 300, ["Shooter"]),
    ("Donkey Kong Country (USA) (Demo) (Kiosk).sfc", "Donkey Kong Country", 4.4, 500, ["Platform"]),
    ("Obscure Homebrew (World) (Unl).sfc", None, None, 0, []),
    ("0123 - Super Mario World (USA).sfc", "Super Mario World", 4.6, 800, ["Platform"]),
    ("Final_Fantasy_III_USA.sfc", "Final Fantasy III", 4.7, 650, ["Role-Playing"]),
    ("Barbie - Super Model (USA).sfc", "Barbie: Super Model", 1.5, 12, ["Sports"]),
    ("Zelda no Densetsu (Japan).sfc", "The Legend of Zelda: A Link to the Past", 4.9, 1000, ["Action", "Adventure"]),
    ("Earthbound (USA).sfc.part", None, None, 0, []),
]
SNES_PLAYED = ["Bebe's Kids (USA).sfc"]  # play count > 0: protected from moving by default
LTTP_ALT = "Zelda no Densetsu"           # an alternate name, like LaunchBox has for Japanese titles

PSX_GAMES = [  # (unit name, LaunchBox name, rating, votes, genres)
    ("Castlevania - Symphony of the Night (USA)", "Castlevania: Symphony of the Night", 4.8, 800,
     ["Action", "Platform"]),
    ("Final Fantasy VII (USA)", "Final Fantasy VII", 4.7, 1200, ["Role-Playing"]),
]


def _write(path, data=b"\0" * 1024):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)


def _systeminfo(folder, name, full, exts):
    _write(os.path.join(folder, "systeminfo.txt"),
           f"System name:\n{name}\n\nFull system name:\n{full}\n\nSupported file extensions:\n{exts}\n")


def build_library(base):
    """Fake retrodeck/ tree under base. -> roms folder."""
    roms = os.path.join(base, "retrodeck", "roms")
    snes = os.path.join(roms, "snes")
    _systeminfo(snes, "snes", "Nintendo SNES (Super Nintendo)", ".sfc .SFC .smc .zip .7z")
    for i, (name, *_rest) in enumerate(SNES_GAMES):
        _write(os.path.join(snes, name), b"\0" * (64 * 1024 * (i + 1)))
    _write(os.path.join(snes, "readme.txt"), "not a game\n")

    psx = os.path.join(roms, "psx")
    _systeminfo(psx, "psx", "Sony PlayStation", ".bin .cue .chd .m3u .pbp")
    sotn = PSX_GAMES[0][0]
    _write(os.path.join(psx, f"{sotn}.cue"),
           f'FILE "{sotn} (Track 1).bin" BINARY\n  TRACK 01 MODE2/2352\nFILE "{sotn} (Track 2).bin" BINARY\n'
           "  TRACK 02 AUDIO\n")
    for t in (1, 2):
        _write(os.path.join(psx, f"{sotn} (Track {t}).bin"), b"\0" * 300_000)
    ff7 = PSX_GAMES[1][0]
    for d in (1, 2):
        _write(os.path.join(psx, f"{ff7} (Disc {d}).chd"), b"\0" * 500_000)
    _write(os.path.join(psx, f"{ff7}.m3u"), f"{ff7} (Disc 1).chd\n{ff7} (Disc 2).chd\n")

    gl = os.path.join(base, "retrodeck", "ES-DE", "gamelists")
    games = "".join(f"\t<game>\n\t\t<path>./{escape(n)}</path>\n\t\t<name>{escape(n)}</name>\n"
                    f"\t\t<playcount>3</playcount>\n\t</game>\n" for n in SNES_PLAYED)
    _write(os.path.join(gl, "snes", "gamelist.xml"),
           f'<?xml version="1.0"?>\n<alternativeEmulator>\n\t<label>Snes9x</label>\n</alternativeEmulator>\n'
           f"<gameList>\n{games}</gameList>\n")
    os.makedirs(os.path.join(base, "retrodeck", "ES-DE", "downloaded_media"), exist_ok=True)
    return roms


def build_metadata_zip(path):
    """A LaunchBox Metadata.zip with just the games above."""
    out, gid = ["<LaunchBox>"], 1000
    seen = {}
    for plat, rows in ((SNES, [(lb, r, v, g) for _, lb, r, v, g in SNES_GAMES if lb]),
                       (PSX, [(lb, r, v, g) for _, lb, r, v, g in PSX_GAMES])):
        for name, rating, votes, genres in rows:
            if (plat, name) in seen:
                continue
            gid += 1
            seen[(plat, name)] = gid
            out.append(f"<Game><Name>{escape(name)}</Name><DatabaseID>{gid}</DatabaseID><Platform>{plat}</Platform>"
                       f"<CommunityRating>{rating}</CommunityRating><CommunityRatingCount>{votes}"
                       f"</CommunityRatingCount><Genres>{escape(';'.join(genres))}</Genres>"
                       f"<Overview>Sandbox description of {escape(name)}.</Overview><Developer>Sandbox Soft"
                       f"</Developer><Publisher>Sandbox Pub</Publisher><ReleaseDate>1994-03-11T00:00:00</ReleaseDate>"
                       f"<MaxPlayers>2</MaxPlayers></Game>")
    lttp = seen[(SNES, "The Legend of Zelda: A Link to the Past")]
    out.append(f"<GameAlternateName><DatabaseID>{lttp}</DatabaseID><AlternateName>{LTTP_ALT}</AlternateName>"
               "</GameAlternateName>")
    out.append(f"<Platform><Name>{SNES}</Name></Platform>")
    out.append(f"<PlatformAlternateName><Name>{PSX}</Name><Alternate>Sony PlayStation</Alternate>"
               "</PlatformAlternateName>")
    out.append("</LaunchBox>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Metadata.xml", "\n".join(out))
    return path


def copy_app(dest):
    """This checkout minus git, caches and anything personal (config, logs, matches)."""
    skip = {".git", "cache", "__pycache__", "config.json", "config.json.bad", "moves.json", "renames.json",
            "matches.json", "tests"}
    shutil.copytree(REPO, dest, ignore=lambda d, names: [n for n in names if n in skip or n.endswith(".tmp")])
    return dest


def paths_of(base):
    return {"base": base, "app": os.path.join(base, "RetroShelf"), "roms": os.path.join(base, "retrodeck", "roms"),
            "holding": os.path.join(base, "pruned"), "home": os.path.join(base, "home")}


def reset(base):
    """Fresh library, holding folder, config and logs; keeps the app copy and its LaunchBox cache. -> paths."""
    p = paths_of(base)
    for d in (os.path.join(base, "retrodeck"), p["holding"], p["home"]):
        shutil.rmtree(d, ignore_errors=True)
    for name in ("config.json", "config.json.bad", "moves.json", "renames.json", "matches.json"):
        try:
            os.unlink(os.path.join(p["app"], name))
        except FileNotFoundError:
            pass
    shutil.rmtree(os.path.join(p["app"], "cache", "matches"), ignore_errors=True)
    os.makedirs(p["home"])
    build_library(base)
    with open(os.path.join(p["app"], "config.json"), "w", encoding="utf-8") as f:
        json.dump({"roms_root": p["roms"], "holding_root": p["holding"], "system": "snes", "check_updates": False},
                  f, indent=1)
    return p


def build(base, with_launchbox=True):
    """Everything under base. -> dict of paths. Doesn't change HOME for this process; see env()."""
    if os.path.lexists(base):
        shutil.rmtree(base)
    os.makedirs(base)
    app = copy_app(os.path.join(base, "RetroShelf"))
    reset(base)
    if with_launchbox:
        zpath = build_metadata_zip(os.path.join(base, "Metadata.zip"))
        subprocess.run([sys.executable, os.path.join(app, "lib", "launchbox.py"), "--zip", zpath], check=True,
                       env=env(base), stdout=subprocess.DEVNULL)
    return paths_of(base)


def env(base, extra=None):
    home = os.path.join(base, "home")
    e = dict(os.environ, HOME=home, XDG_DATA_HOME=os.path.join(home, ".local", "share"),
             XDG_CONFIG_HOME=os.path.join(home, ".config"),
             USERPROFILE=home, APPDATA=os.path.join(home, "AppData", "Roaming"),  # Windows' idea of home
             LOCALAPPDATA=os.path.join(home, "AppData", "Local"))
    e.update(extra or {})
    return e


def tk_python():
    """A Python that has tkinter (the default python3 may not), or None."""
    for exe in (sys.executable, shutil.which("python3"), "/usr/bin/python3", "/usr/bin/python3.12",
                "/usr/bin/python3.11"):
        if exe and os.path.exists(exe) and subprocess.run([exe, "-c", "import tkinter"],
                                                          capture_output=True).returncode == 0:
            return exe
    return None


def launch(paths, screenshot=None, wait=6.0):
    py = tk_python()
    if not py:
        sys.exit("No Python with tkinter found. On Debian / Ubuntu: sudo apt install python3-tk")
    cmd = [py, os.path.join(paths["app"], "retroshelf.py")]
    e = env(paths["base"])
    if screenshot is None:
        if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            sys.exit("No display. Use --screenshot to run under a virtual one (needs xvfb-run and ImageMagick).")
        sys.exit(subprocess.call(cmd, env=e))
    if not sys.platform.startswith("linux"):  # Windows / macOS: the real desktop, grabbed with Pillow
        try:
            from PIL import ImageGrab
        except ImportError:
            sys.exit("--screenshot needs Pillow here (pip install pillow)")
        proc = subprocess.Popen(cmd, env=e)
        try:
            time.sleep(wait)
            if proc.poll() is not None:
                sys.exit(f"RetroShelf exited early (code {proc.returncode})")
            ImageGrab.grab().save(os.path.abspath(screenshot))
        finally:
            proc.terminate()
        print(f"Screenshot: {os.path.abspath(screenshot)}")
        return
    if not shutil.which("xvfb-run") or not shutil.which("import"):
        sys.exit("--screenshot needs xvfb-run (xvfb) and import (imagemagick)")
    shot = os.path.abspath(screenshot)
    script = f'{" ".join(map(repr, cmd))} & pid=$!; sleep {wait}; import -window root {shot!r}; kill $pid'
    subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1600x1000x24", "sh", "-c", script], env=e, check=True)
    print(f"Screenshot: {shot}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", help="where to build it (default: a new temp folder)")
    ap.add_argument("--run", action="store_true", help="start RetroShelf on the sandbox")
    ap.add_argument("--screenshot", metavar="PNG", help="start it under xvfb, save a screenshot, quit")
    ap.add_argument("--no-launchbox", action="store_true", help="skip building the small LaunchBox database")
    a = ap.parse_args()
    base = os.path.abspath(a.dir) if a.dir else tempfile.mkdtemp(prefix="retroshelf-sandbox-")
    paths = build(base, not a.no_launchbox)
    print(f"Sandbox ready in {base}\n  app:     {paths['app']}\n  roms:    {paths['roms']}\n"
          f"  holding: {paths['holding']}")
    if a.run or a.screenshot:
        time.sleep(0.1)
        launch(paths, a.screenshot)


if __name__ == "__main__":
    main()
