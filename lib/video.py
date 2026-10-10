"""Gameplay clips playing inside RetroShelf's windows (Tk can't play video itself).

Two ways, whichever is installed:
  - mpv draws the clip straight into a box in our window (--wid), smooth and with sound on request. Its window id
    is an X11 one on Linux, so mpv is kept off Wayland (Tk runs under XWayland there). The Flatpak build of mpv
    (Steam Deck's Discover) works too, given the clip's folder;
  - otherwise ffmpeg decodes frames that we paint into a Tk image: no sound, but smooth enough at small sizes.
With neither, the panel keeps showing still artwork. RETROSHELF_VIDEO=mpv / ffmpeg / off picks one by hand.

Clips are ES-DE's own: downloaded_media/<system>/videos/<rom>.mp4 (lib/screenscraper.py fetches them)."""
import json, os, re, shutil, socket, subprocess, tempfile, threading
import tkinter as tk

from fsutil import NO_WINDOW, is_windows

EXTS = (".mp4", ".mkv", ".webm", ".avi", ".mov")
FPS = 24
DELAY_MS = 700  # wait this long on a game before starting its clip, so arrowing through a list stays quick
FLATPAK_MPV = "io.mpv.Mpv"
_backend = None
_listings = {}  # videos folder -> (mtime, {stem: file name})


def video_for(media_dir, stems):
    """The game's clip in <media_dir>/videos, or None."""
    folder = os.path.join(media_dir or "", "videos")
    try:
        mtime = os.stat(folder).st_mtime
    except OSError:
        return None
    cached = _listings.get(folder)
    if not cached or cached[0] != mtime:
        by_stem = {}
        for f in sorted(os.listdir(folder)):
            stem, ext = os.path.splitext(f)
            if ext.lower() in EXTS:
                by_stem.setdefault(stem, f)
        cached = _listings[folder] = (mtime, by_stem)
    for stem in stems:
        if stem in cached[1]:
            return os.path.join(folder, cached[1][stem])
    return None


def _flatpak_has(app):
    exe = shutil.which("flatpak")
    if not exe:
        return False
    try:
        return subprocess.run([exe, "info", app], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _find_mpv():
    exe = shutil.which("mpv")
    if not exe and is_windows():
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("LOCALAPPDATA", "")):
            for rel in (r"mpv\mpv.exe", r"Programs\mpv\mpv.exe"):
                p = os.path.join(base, rel)
                if base and os.path.exists(p):
                    exe = p
                    break
    if exe:
        return ("mpv", [exe])
    if not is_windows() and _flatpak_has(FLATPAK_MPV):
        return ("mpv-flatpak", [shutil.which("flatpak"), "run"])
    return None


def backend():
    """("mpv" | "mpv-flatpak", argv prefix) or ("ffmpeg", [exe]) or (None, None). Found once."""
    global _backend
    if _backend is None:
        want = os.environ.get("RETROSHELF_VIDEO", "").lower()
        found = None
        if want != "off":
            if want in ("", "mpv"):
                found = _find_mpv()
            if not found and want in ("", "ffmpeg") and shutil.which("ffmpeg"):
                found = ("ffmpeg", [shutil.which("ffmpeg")])
        _backend = found or (None, None)
    return _backend


def describe():
    kind = backend()[0]
    return {"mpv": "mpv", "mpv-flatpak": "mpv (Flatpak)", "ffmpeg": "ffmpeg (no sound)"}.get(kind)


# ---------- players ----------
class MpvPlayer:
    can_sound = True

    def __init__(self, frame, path, prefix, flatpak=False):
        self.proc, self.ipc = None, None
        tag = f"retroshelf-mpv-{os.getpid()}-{id(self)}"
        if is_windows():
            self.ipc = rf"\\.\pipe\{tag}"
        else:
            base = tempfile.gettempdir()
            if flatpak:  # the sandbox sees this folder of ours
                base = os.path.join(os.environ.get("XDG_RUNTIME_DIR", base), "app", FLATPAK_MPV)
                os.makedirs(base, exist_ok=True)
            self.ipc = os.path.join(base, tag + ".sock")
        args = [f"--wid={frame.winfo_id()}", "--no-config", "--loop-file=inf", "--mute=yes", "--volume=70",
                "--no-osc", "--osd-level=0", "--no-input-default-bindings", "--input-vo-keyboard=no",
                "--input-cursor=no", "--cursor-autohide=always", "--keepaspect=yes", "--hwdec=auto-safe",
                "--audio-display=no", "--really-quiet", "--no-terminal", f"--input-ipc-server={self.ipc}"]
        if not is_windows():  # only outputs that draw into our window (else mpv may open one of its own)
            args += ["--vo=gpu,xv,x11", "--gpu-context=x11egl"]
        env = dict(os.environ)
        cmd = list(prefix)
        if flatpak:
            folder = os.path.dirname(path)
            cmd += [f"--filesystem={folder}:ro", "--socket=x11", "--unset-env=WAYLAND_DISPLAY", FLATPAK_MPV]
        if not is_windows():
            env.pop("WAYLAND_DISPLAY", None)  # our window id is an X11 one
        self.proc = subprocess.Popen(cmd + args + ["--", path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, env=env, creationflags=NO_WINDOW)

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _send(self, command):
        line = (json.dumps({"command": command}) + "\n").encode()
        try:
            if is_windows():
                with open(self.ipc, "r+b", buffering=0) as pipe:
                    pipe.write(line)
            else:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(1)
                    s.connect(self.ipc)
                    s.sendall(line)
            return True
        except OSError:
            return False

    def set_sound(self, on):
        return self._send(["set_property", "mute", not on])

    def stop(self, widgets=True):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        if self.ipc and not is_windows():
            try:
                os.unlink(self.ipc)
            except OSError:
                pass


class FfmpegPlayer:
    """ffmpeg writes PPM frames at the clip's own pace; the newest one is shown every 1/FPS s."""
    can_sound = False
    HEADER = re.compile(rb"P6\s+(\d+)\s+(\d+)\s+(\d+)\s")

    def __init__(self, frame, path, prefix, width, height, bg):
        self.frame, self.latest, self.shown = frame, None, None
        self.label = tk.Label(frame, bg=bg, borderwidth=0, highlightthickness=0)
        self.label.place(relx=0.5, rely=0.5, anchor="center")
        self.image = tk.PhotoImage(master=frame)
        self.label.configure(image=self.image)
        vf = f"fps={FPS},scale={width}:{height}:force_original_aspect_ratio=decrease"
        self.proc = subprocess.Popen(prefix + ["-nostdin", "-loglevel", "error", "-stream_loop", "-1", "-re", "-i",
                                               path, "-an", "-vf", vf, "-f", "image2pipe", "-c:v", "ppm", "pipe:1"],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     creationflags=NO_WINDOW)
        threading.Thread(target=self._read, daemon=True).start()
        self.job = frame.after(1000 // FPS, self._paint)

    def _read(self):
        out = self.proc.stdout
        buf = b""
        while self.proc:
            m = self.HEADER.match(buf)
            if not m:
                chunk = out.read1(1 << 16) if hasattr(out, "read1") else out.read(1 << 16)
                if not chunk:
                    return
                buf += chunk
                continue
            need = m.end() + int(m.group(1)) * int(m.group(2)) * 3
            while len(buf) < need:
                chunk = out.read(need - len(buf))
                if not chunk:
                    return
                buf += chunk
            self.latest, buf = buf[:need], buf[need:]

    def _paint(self):
        self.job = None
        if not self.proc:
            return
        frame = self.latest
        if frame is not None and frame is not self.shown:
            try:
                self.image.configure(data=frame, format="PPM")
                self.shown = frame
            except tk.TclError:
                pass
        self.job = self.frame.after(1000 // FPS, self._paint)

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def set_sound(self, on):
        return False

    def stop(self, widgets=True):
        proc, self.proc = self.proc, None
        if self.job and widgets:
            try:
                self.frame.after_cancel(self.job)
            except tk.TclError:
                pass
        self.job = None
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait()
        if proc and proc.stdout:
            proc.stdout.close()
        if widgets:
            try:
                self.label.destroy()
            except tk.TclError:
                pass


class Spot:
    """A box that shows a game's clip over its artwork: schedule(path) after a short pause on the game, stop()
    when it changes. on_change(playing, can_sound) lets the owner show a sound button."""

    def __init__(self, parent, width, height, bg, on_change=lambda playing, can_sound: None):
        self.parent, self.width, self.height, self.bg, self.on_change = parent, width, height, bg, on_change
        self.frame = tk.Frame(parent, bg="black", width=width, height=height, highlightthickness=0, borderwidth=0)
        self.player, self.job, self.check_job, self.path, self.sound = None, None, None, None, False
        self.enabled = lambda: True
        parent.bind("<Destroy>", lambda e: self._gone() if e.widget is parent else None, add="+")

    def schedule(self, path):
        self.stop()
        if path and self.enabled() and backend()[0]:
            self.path = path
            self.job = self.parent.after(DELAY_MS, self._start)

    def _start(self):
        self.job = None
        kind, prefix = backend()
        if not kind or not self.path or not self.parent.winfo_viewable():
            return
        self.frame.place(x=0, y=0, relwidth=1, relheight=1)
        self.frame.update_idletasks()
        try:
            if kind.startswith("mpv"):
                self.frame.configure(bg="black")
                self.player = MpvPlayer(self.frame, self.path, prefix, flatpak=kind == "mpv-flatpak")
            else:
                self.frame.configure(bg=self.bg)
                self.player = FfmpegPlayer(self.frame, self.path, prefix, self.width, self.height, self.bg)
        except OSError:
            self.player = None
            self.frame.place_forget()
            return
        self.sound = False
        self.on_change(True, self.player.can_sound)
        self.check_job = self.parent.after(1500, self._check)

    def _check(self):
        """mpv that couldn't open its window (no X11, an odd Flatpak) quits at once: fall back to the artwork."""
        self.check_job = None
        if self.player and not self.player.alive():
            self.stop()

    def _gone(self):
        """The window is closing: only end the player's process (Tk is taking the widgets down itself)."""
        self.job = self.check_job = None
        if self.player:
            self.player.stop(widgets=False)
            self.player = None

    def toggle_sound(self):
        if self.player and self.player.can_sound and self.player.set_sound(not self.sound):
            self.sound = not self.sound
        return self.sound

    def playing(self):
        return self.player is not None

    def stop(self):
        for job in (self.job, self.check_job):  # pending timers: cancelled, never left to pile up
            if job:
                try:
                    self.parent.after_cancel(job)
                except tk.TclError:
                    pass
        self.job = self.check_job = None
        was = self.player is not None
        if self.player:
            self.player.stop()
            self.player = None
        self.path = None
        try:
            self.frame.place_forget()
        except tk.TclError:
            pass
        if was:
            self.on_change(False, False)

