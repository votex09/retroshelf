"""Finding, installing and setting up the frontend RetroShelf manages: RetroDECK on Linux, ES-DE on Windows.

RetroDECK (Linux only) is a Flatpak on Flathub. It's installed for the current user, so no admin password is needed,
as long as Flatpak itself is there (it is on Steam Deck and most desktop distributions). Its first launch always runs
its own setup, which asks where its "retrodeck" data folder goes (that can't be skipped or pre-filled: the only way
around it skips the rest of its setup too). So RetroShelf asks first, then tells the user which button to press, and
reads where the folder really went from RetroDECK's config once the setup is done.

ES-DE on Windows comes from its official portable build (listed in ES-DE's own latest_release.json, with an MD5 that
is checked). It's unpacked to <folder>\\ES-DE, where its ROMs folder is <folder>\\ES-DE\\ROMs and its gamelists and
media sit next to that in <folder>\\ES-DE\\ES-DE: the layout the rest of RetroShelf expects. ES-DE has no emulators of
its own; they go in <folder>\\ES-DE\\Emulators or are installed normally.
"""
import hashlib, json, os, shutil, subprocess, urllib.request, zipfile
import xml.etree.ElementTree as ET

from fsutil import NO_WINDOW, is_windows

USER_AGENT = "RetroShelf/1.0 (+https://github.com/votex09/retroshelf)"

# ---------- RetroDECK ----------
RD_APP = "net.retrodeck.retrodeck"
FLATHUB = "https://dl.flathub.org/repo/flathub.flatpakrepo"
FLATPAK_SETUP = "https://flathub.org/setup"


def rd_config_dir():
    return os.path.join(os.path.expanduser("~"), ".var", "app", RD_APP, "config", "retrodeck")


def retrodeck_paths():
    """RetroDECK's folders from its config (retrodeck.json), or None when it hasn't been set up."""
    try:
        with open(os.path.join(rd_config_dir(), "retrodeck.json"), encoding="utf-8") as f:
            paths = json.load(f).get("paths") or {}
    except (OSError, ValueError, AttributeError):
        return None
    return paths if isinstance(paths, dict) and paths.get("rd_home_path") else None


def retrodeck_roms():
    """RetroDECK's roms folder, once its first-time setup has finished (it writes .lock last)."""
    paths = retrodeck_paths()
    if not paths or not os.path.exists(os.path.join(rd_config_dir(), ".lock")):
        return None
    roms = paths.get("roms_path") or os.path.join(paths["rd_home_path"], "roms")
    return roms if os.path.isdir(roms) else None


def is_steam_deck():
    try:
        with open("/sys/devices/virtual/dmi/id/product_name", encoding="utf-8") as f:
            return f.read().strip() in ("Jupiter", "Galileo")
    except OSError:
        return False


def flatpak():
    return shutil.which("flatpak")


def retrodeck_installed():
    exe = flatpak()
    if not exe:
        return False
    try:
        return subprocess.run([exe, "info", RD_APP], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def frontend_installed(known=()):
    """Is there an ES-DE to play the games with: RetroDECK, ES-DE on its own (its ~/ES-DE folder, or es-de on the
    PATH), or on Windows a portable ES-DE RetroShelf knows of or can find?"""
    if is_windows():
        return bool(esde_installs(known))
    return (os.path.isdir(os.path.join(os.path.expanduser("~"), "ES-DE")) or bool(shutil.which("es-de"))
            or retrodeck_installed())


QUIET_NOTE = 60      # seconds of silence from flatpak before saying what's still happening
QUIET_LIMIT = 900    # seconds with no output and nothing written to disk before calling it stuck


def _free_bytes(path):
    try:
        st = os.statvfs(path)
        return st.f_bavail * st.f_frsize
    except (OSError, AttributeError):
        return None


def flatpak_user_dir():
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share"),
                        "flatpak")


def _run_flatpak(cmd, log, cancelled, quiet_note=QUIET_NOTE, quiet_limit=QUIET_LIMIT):
    """Run one flatpak command, passing on its output as it comes (progress redraws with \r count as lines).
    flatpak run from a pipe goes quiet while it downloads, so while it's silent this says how much has been written
    to disk so far; silent with nothing written for quiet_limit seconds, it's stopped and its last words reported.
    stdin is closed, so anything that would wait for an answer fails instead of waiting for ever."""
    import queue, threading, time
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         start_new_session=True)
    q = queue.Queue()

    def read():
        buf = b""
        for chunk in iter(lambda: p.stdout.read1(4096), b""):
            buf += chunk
            *parts, buf = buf.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
            for part in parts:
                q.put(part)
        q.put(buf)
        q.put(None)
    threading.Thread(target=read, daemon=True).start()
    disk = flatpak_user_dir()
    while not os.path.isdir(disk) and disk != os.path.dirname(disk):
        disk = os.path.dirname(disk)
    tail, last_line, heard = [], None, time.monotonic()
    free = _free_bytes(disk)
    start_free, noted = free, 0

    def stop():  # flatpak and whatever it started (its own session, so the whole group)
        import signal
        for sig, wait in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
            try:
                os.killpg(p.pid, sig)
                p.wait(wait)
                return
            except (OSError, subprocess.TimeoutExpired):
                pass
    try:
        while True:
            if cancelled():
                stop()
                raise InterruptedError("cancelled")
            try:
                raw = q.get(timeout=1)
            except queue.Empty:
                now, now_free = time.monotonic(), _free_bytes(disk)
                if now_free is not None and free is not None and free - now_free > 1 << 20:
                    heard, free = now, now_free  # writing to disk: still downloading
                quiet = now - heard
                if quiet >= quiet_limit:
                    stop()
                    said = "\n".join(tail[-8:]) or "(nothing)"
                    raise RuntimeError(f"flatpak {cmd[1]} stopped making progress: nothing new from it and nothing "
                                       f"written to disk for {int(quiet // 60)} minutes. Its last words:\n{said}")
                if now - max(noted, heard) >= quiet_note:
                    noted = now
                    got = (start_free - now_free) if start_free is not None and now_free is not None else 0
                    log(f"… still working ({human_size(got)} written so far)" if got > 1 << 20 else
                        f"… still working, nothing new from flatpak for {int(quiet)} s")
                continue
            if raw is None:
                break
            line = raw.decode("utf-8", "replace").strip()
            heard = time.monotonic()
            if line and line != last_line:
                last_line = line
                tail = (tail + [line])[-20:]
                log(line)
        p.wait()
    finally:
        if p.poll() is None:
            stop()
    if p.returncode != 0:
        said = "\n".join(tail[-8:])
        raise RuntimeError(f"flatpak {cmd[1]} failed (exit code {p.returncode})" + (f":\n{said}" if said else ""))


def install_retrodeck(log, cancelled=lambda: False):
    """Add Flathub for this user (if needed) and install RetroDECK from it. log(line) gets flatpak's output.
    Raises RuntimeError when flatpak fails or stops making progress, InterruptedError when cancelled."""
    exe = flatpak()
    if not exe:
        raise RuntimeError("Flatpak isn't installed")
    steps = ([exe, "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB],
             [exe, "install", "--user", "--noninteractive", "-y", "flathub", RD_APP])
    for cmd in steps:
        log("$ " + " ".join(cmd[1:]))
        _run_flatpak(cmd, log, cancelled)


def launch_retrodeck():
    return subprocess.Popen([flatpak() or "flatpak", "run", RD_APP], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


def retrodeck_steps(choice, folder):
    """What to press in RetroDECK's first-time setup so its data folder ends up where the user chose."""
    deck = is_steam_deck()
    if choice == "home":
        button = "Internal Storage" if deck else "Home Directory"
        return [f"Press “{button}”."]
    return ["Press “Custom Location”, then “Browse”.",
            f"Pick this folder (press Ctrl+L and paste it — it's been copied for you):\n{folder}",
            "Press “Yes” to confirm. RetroDECK adds the retrodeck folder inside it."]


# ---------- ES-DE (Windows) ----------
LATEST_RELEASE = "https://gitlab.com/es-de/emulationstation-de/-/raw/master/latest_release.json"
ESDE_GUIDE = "https://gitlab.com/es-de/emulationstation-de/-/blob/master/USERGUIDE.md"


def _fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def esde_release(package="WindowsPortable"):
    """-> (version, {filename, url, md5}) of ES-DE's latest stable build."""
    data = json.loads(_fetch(LATEST_RELEASE))
    stable = data["stable"]
    pkg = next((p for p in stable["packages"] if p.get("name") == package), None)
    if not pkg or not pkg.get("url"):
        raise ValueError(f"ES-DE's release list has no {package} build")
    return stable["version"], pkg


def download(url, dest, md5=None, progress=lambda done, total: None, cancelled=lambda: False):
    """Stream url to dest (via dest.part), checking the MD5 if given."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest, done = hashlib.md5(), 0
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(dest + ".part", "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            while True:
                if cancelled():
                    raise InterruptedError("cancelled")
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                progress(done, total)
        if md5 and digest.hexdigest().lower() != md5.lower():
            raise ValueError("the download is damaged (its checksum doesn't match ES-DE's), please try again")
        os.replace(dest + ".part", dest)
    finally:
        if os.path.exists(dest + ".part"):
            os.unlink(dest + ".part")
    return dest


def esde_dir(base):
    return os.path.join(base, "ES-DE")


def esde_exe(base):
    return os.path.join(esde_dir(base), "ES-DE.exe")


def esde_roms(base):
    return os.path.join(esde_dir(base), "ROMs")


def unpack_esde(zpath, base):
    """Unpack the portable zip into base (it holds an ES-DE folder), refusing anything that would land outside."""
    root = os.path.realpath(base)
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        if not any(n.replace("\\", "/") == "ES-DE/ES-DE.exe" for n in names):
            raise ValueError("this isn't ES-DE's portable build")
        for n in names:
            target = os.path.realpath(os.path.join(root, n))
            if target != root and not target.startswith(root + os.sep):
                raise ValueError(f"unsafe path in the zip: {n}")
        z.extractall(root)


def create_system_dirs(base):
    """One folder per system in ES-DE's ROMs folder, as ES-DE's own --create-system-dirs makes them. Falls back to
    the ROMs_ALL template the portable build ships when ES-DE can't be run (not on Windows, or it failed)."""
    roms = esde_roms(base)
    if is_windows():
        try:
            subprocess.run([esde_exe(base), "--create-system-dirs"], cwd=esde_dir(base), timeout=120,
                           capture_output=True, creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            pass
    template = os.path.join(esde_dir(base), "ROMs_ALL")
    if (not os.path.isdir(roms) or not os.listdir(roms)) and os.path.isdir(template):
        shutil.copytree(template, roms, dirs_exist_ok=True)
    os.makedirs(roms, exist_ok=True)
    return roms


def esde_rom_dir(settings_xml, home, exe_dir=None):
    """ES-DE's ROMs folder from its es_settings.xml (ROMDirectory), else its default <home>/ROMs."""
    value = ""
    try:
        with open(settings_xml, encoding="utf-8") as f:
            text = f.read()
        root = ET.fromstring(f"<r>{text.split('?>', 1)[-1] if text.lstrip().startswith('<?') else text}</r>")
        node = next((n for n in root.iter("string") if n.get("name") == "ROMDirectory"), None)
        value = (node.get("value") or "").strip() if node is not None else ""
    except (OSError, ET.ParseError):
        pass
    if not value:
        return os.path.join(home, "ROMs")
    if "%ESPATH%" in value:
        value = value.replace("%ESPATH%", exe_dir or home)
    return os.path.normpath(os.path.expanduser(value))


def esde_installs(known=()):
    """ES-DE ROMs folders that exist: portable installs RetroShelf set up (known: their base folders) and the
    regular install's ~/ES-DE settings."""
    found = []
    for base in known:
        d = esde_dir(base)
        roms = esde_rom_dir(os.path.join(d, "ES-DE", "settings", "es_settings.xml"), d, d)
        if os.path.isdir(roms):
            found.append(roms)
    home = os.path.expanduser("~")
    settings = os.path.join(home, "ES-DE", "settings", "es_settings.xml")
    if os.path.exists(settings):
        roms = esde_rom_dir(settings, home)
        if os.path.isdir(roms):
            found.append(roms)
    return found


def add_esde_shortcut(base):
    """A Start menu entry for ES-DE (Windows)."""
    from fsutil import make_shortcut
    folder = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
    os.makedirs(folder, exist_ok=True)
    make_shortcut(os.path.join(folder, "ES-DE.lnk"), esde_exe(base), "", esde_dir(base), esde_exe(base),
                  "ES-DE game frontend")


# ---------- where games can go ----------
def free_bytes(path):
    """Free space where path is (or would be: the nearest folder that exists)."""
    while path and not os.path.exists(path) and os.path.dirname(path) != path:
        path = os.path.dirname(path)
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def storage_choices():
    """[(kind, label, folder)] to offer: the home folder, then drives / SD cards. kind is "home" or "drive"."""
    home = os.path.expanduser("~")
    if is_windows():  # not straight in the home folder: the ES-DE installer keeps its settings in ~\ES-DE
        out = [("home", "Home folder", os.path.join(home, "Games"))]
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            root = f"{letter}:\\"
            if os.path.isdir(root) and free_bytes(root) is not None:
                out.append(("drive", f"Drive {letter}:", root))
        return out
    out = [("home", "Home folder", home)]
    user = os.path.basename(home)
    seen = set()
    for parent in (f"/run/media/{user}", f"/media/{user}", "/run/media"):
        try:
            names = sorted(os.listdir(parent))
        except OSError:
            continue
        for n in names:
            p = os.path.join(parent, n)
            if p in seen or n == user or not os.path.isdir(p) or not os.access(p, os.W_OK):
                continue
            seen.add(p)
            out.append(("drive", f"{'SD card' if n.startswith('mmcblk') else 'Drive'} {n}", p))
    return out


def games_folder(choice, folder):
    """Where the ROMs will end up for a chosen location."""
    if is_windows():
        return esde_roms(folder)
    return os.path.join(folder, "retrodeck", "roms")


def human_size(n):
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
