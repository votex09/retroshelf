"""Compress disc images: CD and PS2 images become .chd (chdman, from MAME), GameCube and Wii images become .rvz
(dolphin-tool, from Dolphin). Every emulator ES-DE / RetroDECK uses for these systems reads them, and they're
often a third to a half smaller.

    plan(system, units)            -> what each game would become (Jobs), or why it's left alone
    find_tool("chdman" | "dolphin-tool") -> Tool, or None: on the PATH, in RetroDECK, or in Dolphin's Flatpak
    convert(job, tool, ...)        -> writes a hidden temporary file next to the game, checks it, renames it in place
    finish(job, folder, ...)       -> points .m3u playlists, the ES-DE gamelist and media at the new file, then moves
                                      the originals to the holding folder (or deletes them, when asked)

Nothing is replaced until the new file has been written and checked."""
import os, re, shutil, subprocess, threading, time

import romimport
import scraper
from fsutil import NO_WINDOW, is_windows

RETRODECK = "net.retrodeck.retrodeck"
DOLPHIN = "org.DolphinEmu.dolphin-emu"

# systems whose emulators read CD-image CHDs; PS2 discs are DVDs (except a few early CD games, which come as .cue)
CD_SYSTEMS = {"psx", "saturn", "saturnjp", "segacd", "megacd", "megacdjp", "pcenginecd", "tg-cd", "neogeocd", "3do",
              "dreamcast", "pcfx"}
DVD_SYSTEMS = {"ps2"}
RVZ_SYSTEMS = {"gc", "wii"}
SYSTEMS = CD_SYSTEMS | DVD_SYSTEMS | RVZ_SYSTEMS

SHEETS = (".cue", ".gdi")
CD_IMAGES = (".iso",)
RVZ_IMAGES = (".iso", ".gcm", ".wbfs", ".gcz", ".wia")
DONE = (".chd", ".rvz")


def target_ext(system):
    if system in RVZ_SYSTEMS:
        return ".rvz"
    return ".chd" if system in SYSTEMS else None


def supported(system, exts=None):
    """The format a system's games become, or None. exts: what the system's ES-DE folder says it reads
    (systeminfo.txt), when known: a system that doesn't list the format is left alone."""
    ext = target_ext(system)
    if ext and exts and ext not in {e.lower() for e in exts}:
        return None
    return ext


class Job:
    """One image to convert: src is what the tool reads (a .cue / .gdi / image), parts every file or folder it
    replaces, out the new file."""

    def __init__(self, kind, src, parts, out):
        self.kind, self.src, self.parts, self.out = kind, src, list(parts), out
        self.size = sum(_size(p) for p in self.parts)

    def __repr__(self):
        return f"Job({self.kind}, {os.path.basename(self.src)} -> {os.path.basename(self.out)})"


def _size(p):
    if os.path.isdir(p):
        return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(p) for f in fs)
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _sheet_job(kind, sheet, out):
    """A .cue / .gdi and the track files it names. -> Job, or a reason it can't be converted."""
    try:
        text = _read(sheet)
    except OSError as e:
        return f"can't read {os.path.basename(sheet)}: {e}"
    refs = [t[0] for t in romimport.parse_cue(text)] if sheet.lower().endswith(".cue") else romimport.parse_gdi(text)
    if not refs:
        return f"{os.path.basename(sheet)} names no tracks"
    here = os.path.dirname(sheet)
    parts = [sheet]
    for r in refs:
        p = os.path.join(here, r.replace("\\", os.sep))
        if not os.path.isfile(p):
            return f"{os.path.basename(sheet)} names {r}, which isn't there"
        if p not in parts:
            parts.append(p)
    return Job(kind, sheet, parts, out)


def _unit_jobs(system, paths):
    """-> ([Job], reason when there are none)."""
    kind = "rvz" if system in RVZ_SYSTEMS else "cd"
    ext = target_ext(system)
    jobs, used, reasons = [], set(), []
    files = [p for p in paths if os.path.isfile(p)]
    for d in (p for p in paths if os.path.isdir(p)):  # a game kept in its own folder (common for Dreamcast .gdi)
        inside = sorted(os.path.join(d, f) for f in os.listdir(d))
        images = [p for p in inside if p.lower().endswith(SHEETS if kind == "cd" else RVZ_IMAGES)]
        if kind == "cd" and not images:
            images = [p for p in inside if p.lower().endswith(CD_IMAGES)]
        if len(images) != 1:
            reasons.append(f"{os.path.basename(d)}/ holds {len(images) or 'no'} disc images")
            continue
        out = os.path.join(os.path.dirname(d), os.path.basename(d) + ext)
        if kind == "rvz":
            job = Job("rvz", images[0], [d], out)
        elif images[0].lower().endswith(SHEETS):
            job = _sheet_job("cd", images[0], out)
            if isinstance(job, Job):
                job.parts = [d]
                job.size = _size(d)
        else:
            job = Job("dvd" if system in DVD_SYSTEMS else "cd", images[0], [d], out)
        (jobs.append if isinstance(job, Job) else reasons.append)(job)
    if kind == "cd":
        for sheet in (p for p in files if p.lower().endswith(SHEETS)):
            job = _sheet_job("cd", sheet, os.path.splitext(sheet)[0] + ext)
            if isinstance(job, Job):
                jobs.append(job)
                used.update(job.parts)
            else:
                reasons.append(job)
        for img in (p for p in files if p.lower().endswith(CD_IMAGES) and p not in used):
            jobs.append(Job("dvd" if system in DVD_SYSTEMS else "cd", img, [img], os.path.splitext(img)[0] + ext))
    else:
        names = {os.path.basename(p).lower() for p in files}
        for img in (p for p in files if p.lower().endswith(RVZ_IMAGES)):
            base = os.path.basename(img).lower()
            if ".nkit." in base:
                reasons.append(f"{os.path.basename(img)} is an NKit image (Dolphin can't turn it back into a "
                               "full disc)")
                continue
            if base.endswith(".wbfs") and base[:-5] + ".wbf1" in names:
                reasons.append(f"{os.path.basename(img)} is split into parts")
                continue
            jobs.append(Job("rvz", img, [img], os.path.splitext(img)[0] + ext))
    ok = []
    for job in jobs:
        if os.path.lexists(job.out):
            reasons.append(f"{os.path.basename(job.out)} is already there")
        else:
            ok.append(job)
    if ok:
        return ok, None
    if reasons:
        return [], "; ".join(reasons)
    if any(p.lower().endswith(DONE) for p in paths):
        return [], "already compressed"
    return [], "nothing to compress"


def plan(system, units, exts=None):
    """units: {key: {"paths": [...]}} -> [(key, [Job], reason or None)], one per game, in key order."""
    if not supported(system, exts):
        return []
    return [(key, *_unit_jobs(system, units[key]["paths"])) for key in sorted(units, key=str.lower)]


# ---------- the tools ----------
class Tool:
    """argv(folder) -> the command's start; flatpak tools get to see folder."""

    def __init__(self, name, where, exe=None, app=None, command=None):
        self.name, self.where, self.exe, self.app, self.command = name, where, exe, app, command

    def argv(self, folder):
        if self.app:
            return [shutil.which("flatpak") or "flatpak", "run", f"--filesystem={folder}",
                    f"--command={self.command}", self.app]
        return list(self.exe) if isinstance(self.exe, (list, tuple)) else [self.exe]


def _flatpak_command(app, command):
    exe = shutil.which("flatpak")
    if not exe:
        return False
    try:
        if subprocess.run([exe, "info", app], capture_output=True, timeout=30).returncode:
            return False
        return subprocess.run([exe, "run", "--command=sh", app, "-c", f"command -v {command}"], capture_output=True,
                              timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _windows_dirs(*rels):
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", ""),
                 os.environ.get("LOCALAPPDATA", ""), "C:\\"):
        for rel in rels:
            p = os.path.join(base, rel)
            if base and os.path.isfile(p):
                yield p


def find_tool(name):
    """name: 'chdman' or 'dolphin-tool'. -> Tool, or None. (Asking Flatpak takes a moment: call it off the UI
    thread.)"""
    names = {"chdman": ["chdman"], "dolphin-tool": ["dolphin-tool", "DolphinTool"]}[name]
    for n in names:
        exe = shutil.which(n)
        if exe:
            return Tool(name, exe, exe)
    if is_windows():
        rels = ([r"MAME\chdman.exe", r"mame\chdman.exe"] if name == "chdman" else
                [r"Dolphin\DolphinTool.exe", r"Dolphin-x64\DolphinTool.exe", r"Dolphin Emulator\DolphinTool.exe"])
        for p in _windows_dirs(*rels):
            return Tool(name, p, p)
        return None
    apps = [RETRODECK] if name == "chdman" else [RETRODECK, DOLPHIN]
    for app in apps:
        if _flatpak_command(app, names[0]):
            return Tool(name, "RetroDECK" if app == RETRODECK else "Dolphin (Flatpak)", app=app, command=names[0])
    return None


def tool_name(kind):
    return "dolphin-tool" if kind == "rvz" else "chdman"


INSTALL_HINT = {
    "chdman": ("chdman comes with RetroDECK, and with MAME (Debian / Ubuntu: sudo apt install mame-tools; "
               "Fedora: sudo dnf install mame-tools; Windows: from the MAME download, put chdman.exe on the PATH)."),
    "dolphin-tool": ("dolphin-tool comes with RetroDECK and with Dolphin (its Flatpak, or DolphinTool.exe in the "
                     "Windows download)."),
}


# ---------- converting ----------
PERCENT = re.compile(r"(\d+(?:\.\d+)?)% complete")


def _run(name, cmd, progress, cancelled, watch=None):
    """Run a tool, reporting progress(fraction or None, written bytes or None) from chdman's "n% complete" or,
    for tools that don't say, how big the file being written has grown. Raises InterruptedError when cancelled,
    RuntimeError (with the tool's last words) when it fails."""
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=NO_WINDOW)
    lines, state = [], {"pct": None}

    def read():
        buf = b""
        while True:
            chunk = p.stdout.read1(4096) if hasattr(p.stdout, "read1") else p.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            *done, buf = re.split(rb"[\r\n]", buf)
            for raw in done:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                m = PERCENT.search(line)
                if m:
                    state["pct"] = float(m.group(1)) / 100
                else:
                    lines.append(line)
                    del lines[:-30]
        if buf.strip():
            lines.append(buf.decode("utf-8", "replace").strip())
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        while p.poll() is None:
            if cancelled():
                p.kill()
                p.wait()
                raise InterruptedError("cancelled")
            written = None
            if watch and os.path.exists(watch):
                written = os.path.getsize(watch)
            progress(state["pct"], written)
            time.sleep(0.25)
    finally:
        reader.join(5)
        p.stdout.close()
    progress(state["pct"], os.path.getsize(watch) if watch and os.path.exists(watch) else None)
    if p.returncode:
        why = next((ln for ln in reversed(lines) if re.search(r"error|invalid|unknown|fail|can't|cannot|unable", ln,
                                                              re.I)), lines[-1] if lines else "")
        raise RuntimeError(f"{name} failed: {why[:200] or f'exit code {p.returncode}'}")


def temp_path(out):
    return os.path.join(os.path.dirname(out), "." + os.path.basename(out) + ".retroshelf-tmp")


def convert(job, tool, progress=lambda stage, fraction, written: None, cancelled=lambda: False, verify=True):
    """Write job.out from job.src. progress(stage 'compress' | 'check', fraction or None, bytes written or None).
    -> the new file's size. The originals aren't touched."""
    folder = os.path.dirname(job.out)
    tmp = temp_path(job.out)
    base = tool.argv(folder)
    if os.path.lexists(tmp):
        os.remove(tmp)

    def stage(name):
        return lambda fraction, written: progress(name, fraction, written)
    try:
        if job.kind == "rvz":
            _run(tool.name, base + ["convert", "-i", job.src, "-o", tmp, "-f", "rvz", "-b", "131072", "-c", "zstd", "-l", "5"],
                 stage("compress"), cancelled, watch=tmp)
        else:
            try:
                _run(tool.name, base + ["createdvd" if job.kind == "dvd" else "createcd", "-i", job.src, "-o", tmp],
                     stage("compress"), cancelled, watch=tmp)
            except RuntimeError as e:
                if job.kind != "dvd" or not re.search(r"invalid command|unknown command|usage", str(e), re.I):
                    raise
                if os.path.lexists(tmp):  # an older chdman, without DVDs: PCSX2 reads CD-style CHDs too
                    os.remove(tmp)
                _run(tool.name, base + ["createcd", "-i", job.src, "-o", tmp], stage("compress"), cancelled, watch=tmp)
        if not os.path.isfile(tmp) or not os.path.getsize(tmp):
            raise RuntimeError(f"{tool.name} wrote nothing")
        if verify:
            _run(tool.name, base + ["verify", "-i", tmp], stage("check"), cancelled)
        if os.path.lexists(job.out):
            raise RuntimeError(f"{os.path.basename(job.out)} appeared while it was being written")
        os.rename(tmp, job.out)
    except BaseException:
        try:
            if os.path.lexists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise
    return os.path.getsize(job.out)


# ---------- afterwards ----------
def fix_refs(path, by_name):
    """Swap old file names for new ones inside a .cue / .m3u / .gdi."""
    if not by_name:
        return False
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
        text = f.read()
    rx = re.compile("|".join(re.escape(n) for n in sorted(by_name, key=len, reverse=True)))
    new = rx.sub(lambda m: by_name[m.group(0)], text)
    if new != text:
        with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
            f.write(new)
    return new != text


def _rel(path, folder):
    return os.path.relpath(path, folder).replace(os.sep, "/")


def repath_gamelist(gamelist, mapping):
    """mapping {old path relative to the system folder: new one}. -> entries changed. Backs the file up first."""
    if not mapping or not gamelist or not os.path.exists(gamelist):
        return 0
    want = {k.lower(): v for k, v in mapping.items()}
    tops, root = scraper.read_gamelist(gamelist)
    changed = 0
    for g in root.iter("game"):
        el = g.find("path")
        text = (el.text or "").strip() if el is not None else ""
        rel = text[2:] if text.startswith("./") else text
        new = want.get(rel.rstrip("/").lower())
        if new is None:
            continue
        el.text = "./" + new
        name = g.find("name")
        old_stem = os.path.splitext(os.path.basename(rel.rstrip("/")))[0]
        if name is not None and (name.text or "").strip() == old_stem:
            name.text = os.path.splitext(os.path.basename(new))[0]  # ES-DE's placeholder name, unscraped games
        changed += 1
    if changed:
        shutil.copy2(gamelist, f"{gamelist}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        scraper.save_gamelist(gamelist, tops)
    return changed


def move_media(media_dir, mapping):
    """Media follows the file name (and folder) ES-DE knows the game by. -> files moved."""
    moved = 0
    if not os.path.isdir(media_dir):
        return 0
    for old, new in mapping.items():
        o, n = os.path.splitext(old)[0], os.path.splitext(new)[0]
        if o == n:
            continue
        for mtype in os.listdir(media_dir):
            src_dir = os.path.join(media_dir, mtype, *o.split("/")[:-1])
            if not os.path.isdir(src_dir):
                continue
            stem = o.split("/")[-1]
            for f in os.listdir(src_dir):
                s, ext = os.path.splitext(f)
                if s != stem:
                    continue
                dst = os.path.join(media_dir, mtype, *n.split("/")) + ext
                if os.path.lexists(dst):
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.rename(os.path.join(src_dir, f), dst)
                moved += 1
    return moved


def _free_name(path):
    if not os.path.lexists(path):
        return path
    stem, ext = os.path.splitext(path)
    i = 2
    while os.path.lexists(f"{stem} ({i}){ext}"):
        i += 1
    return f"{stem} ({i}){ext}"


def finish(job, folder, playlists=(), gamelist=None, media_dir=None, holding=None, es_de_running=False):
    """After convert(): playlists naming the old file name the new one, ES-DE's gamelist and media follow it, and
    the originals go into holding (a folder), or are deleted when holding is None.
    -> ([[original, where it went]], [problems])."""
    problems, moves = [], []
    old_name, new_name = os.path.basename(job.src), os.path.basename(job.out)
    for m3u in playlists:
        try:
            fix_refs(m3u, {old_name: new_name})
        except OSError as e:
            problems.append(f"{os.path.basename(m3u)}: {e}")
    mapping = {_rel(job.src, folder): _rel(job.out, folder)}
    for part in job.parts:
        if os.path.isdir(part):
            mapping[_rel(part, folder)] = _rel(job.out, folder)
    if gamelist and os.path.exists(gamelist):
        if es_de_running:
            problems.append("gamelist.xml not updated while ES-DE is running: rescrape the game's text later, or "
                            "keep its .cue name in mind")
        else:
            try:
                repath_gamelist(gamelist, mapping)
            except Exception as e:
                problems.append(f"gamelist.xml: {e}")
    if media_dir:
        try:
            move_media(media_dir, mapping)
        except OSError as e:
            problems.append(f"media: {e}")
    if holding:
        os.makedirs(holding, exist_ok=True)
    for part in job.parts:
        try:
            if holding:
                target = _free_name(os.path.join(holding, os.path.basename(part)))
                shutil.move(part, target)
                moves.append([part, target])
            elif os.path.isdir(part):
                shutil.rmtree(part)
            else:
                os.remove(part)
        except OSError as e:
            problems.append(f"{os.path.basename(part)}: {e}")
    return moves, problems


def playlists_for(job, paths):
    """The game's .m3u files that name the image being replaced."""
    name = os.path.basename(job.src)
    out = []
    for p in paths:
        if p.lower().endswith(".m3u") and os.path.isfile(p):
            try:
                if name in romimport.parse_m3u(_read(p)) or any(os.path.basename(r.replace("\\", "/")) == name
                                                                for r in romimport.parse_m3u(_read(p))):
                    out.append(p)
            except OSError:
                pass
    return out


def free_space(folder):
    try:
        return shutil.disk_usage(folder).free
    except OSError:
        return None

