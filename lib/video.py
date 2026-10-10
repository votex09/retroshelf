"""Gameplay videos playing inside RetroShelf's windows (Tk can't play video itself).

Where a game's video comes from, first that exists:
  1. ES-DE's own clip: downloaded_media/<system>/videos/<rom>.mp4 (ES-DE's scraper downloads them);
  2. if streaming is switched on (View menu, off by default): the top YouTube result for "<title> <console>
     gameplay", which mpv plays through yt-dlp. That needs mpv and yt-dlp, and plays YouTube outside YouTube's own
     player, which YouTube's terms don't allow; it's the user's choice to switch it on.

How it's shown, whichever is installed:
  - mpv draws the video straight into a box in our window (--wid), smooth and with sound on request. Its window id
    is an X11 one on Linux, so mpv is kept on X11 outputs (Tk runs under XWayland on Wayland). The Flatpak build of
    mpv (Steam Deck's Discover), which bundles yt-dlp, works too;
  - otherwise ffmpeg decodes local clips into frames we paint into a Tk image (no sound, no streams).
With neither, the panel keeps showing still artwork. RETROSHELF_VIDEO=mpv / ffmpeg / off picks one by hand.

While a video loads the artwork stays up; the video box comes forward once mpv reports it's playing."""
import json, os, re, shutil, socket, subprocess, tempfile, threading, urllib.parse
import tkinter as tk

from fsutil import NO_WINDOW, is_windows

EXTS = (".mp4", ".mkv", ".webm", ".avi", ".mov")
FPS = 24
DELAY_MS = 700          # wait this long on a game before starting its clip, so arrowing through a list stays quick
STREAM_DELAY_MS = 1500  # streams cost bandwidth and a few seconds to start: wait a little longer
POLL_MS = 300
LOAD_TIMEOUT_MS = {"clip": 6000, "stream": 25000}
STREAM_FORMAT = "bv*[height<=480]+ba/b[height<=480]/b"  # small panel: no need for HD
FLATPAK_MPV = "io.mpv.Mpv"
_backend = None
_ytdl = None
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


def youtube_query(title, console):
    """What mpv (through yt-dlp) is asked to play: the top YouTube result for the game's gameplay."""
    return "ytdl://ytsearch1:" + " ".join(x for x in (title, console, "gameplay") if x)


def youtube_page(title, console):
    """The same search in a browser, for people who'd rather watch it there."""
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(
        " ".join(x for x in (title, console, "gameplay") if x))


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


def can_stream():
    """Streams need mpv and yt-dlp (the Flatpak mpv bundles yt-dlp)."""
    global _ytdl
    kind = backend()[0]
    if kind == "mpv-flatpak":
        return True
    if kind != "mpv":
        return False
    if _ytdl is None:
        _ytdl = bool(shutil.which("yt-dlp") or shutil.which("youtube-dl"))
    return _ytdl


def missing_for_streams():
    """What to install for streaming, in words, or "" when it's all there."""
    kind = backend()[0]
    if kind in ("mpv", "mpv-flatpak"):
        return "" if can_stream() else "yt-dlp"
    return "mpv and yt-dlp" + (" (on Steam Deck: mpv from Discover, which includes yt-dlp)" if not is_windows() else "")


# ---------- players ----------
class MpvPlayer:
    can_sound = True

    def __init__(self, frame, source, prefix, flatpak=False, stream=False):
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
        if stream:
            args += [f"--ytdl-format={STREAM_FORMAT}", "--demuxer-max-bytes=50MiB", "--cache=yes"]
        if not is_windows():  # only outputs that draw into our window (else mpv may open one of its own)
            args += ["--vo=gpu,xv,x11", "--gpu-context=x11egl"]
        env = dict(os.environ)
        cmd = list(prefix)
        if flatpak:
            sandbox = ["--socket=x11", "--unset-env=WAYLAND_DISPLAY"]
            if not stream:
                sandbox.append(f"--filesystem={os.path.dirname(source)}:ro")
            cmd += sandbox + [FLATPAK_MPV]
        if not is_windows():
            env.pop("WAYLAND_DISPLAY", None)  # our window id is an X11 one
        self.cmd = cmd + args + ["--", source]
        self.proc = subprocess.Popen(self.cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, env=env, creationflags=NO_WINDOW)

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _ipc(self, command, answer=False):
        """Send mpv a command over its IPC socket / pipe; with answer, -> its "data" (None if it has none)."""
        line = (json.dumps({"command": command, "request_id": 1}) + "\n").encode()
        try:
            if is_windows():
                with open(self.ipc, "r+b", buffering=0) as pipe:
                    pipe.write(line)
                    replies = [pipe.readline()] if answer else []
            else:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    s.connect(self.ipc)
                    s.sendall(line)
                    replies = []
                    if answer:
                        buf = b""
                        while b"request_id" not in buf:
                            chunk = s.recv(4096)
                            if not chunk:
                                break
                            buf += chunk
                        replies = buf.splitlines()
        except OSError:
            return None if answer else False
        if not answer:
            return True
        for raw in replies:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if msg.get("request_id") == 1:
                return msg.get("data")
        return None

    def started(self):
        """mpv is showing frames (it knows where it is in the video)."""
        pos = self._ipc(["get_property", "playback-time"], answer=True)
        return isinstance(pos, (int, float))

    def set_sound(self, on):
        return self._ipc(["set_property", "mute", not on])

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

    def started(self):
        return self.shown is not None

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
    """A box that shows a game's video over its artwork. schedule(clip, stream) after a short pause on the game
    (the local clip if there is one, else the stream if given and possible); stop() when the game changes.
    on_change(state, kind, can_sound): state "loading" / "playing" / "stopped", kind "clip" / "stream"."""

    def __init__(self, parent, width, height, bg, on_change=lambda state, kind, can_sound: None, under=None):
        self.parent, self.width, self.height, self.bg, self.on_change = parent, width, height, bg, on_change
        self.under = under  # the artwork widget: the video waits behind it until it's playing
        self.frame = tk.Frame(parent, bg="black", width=width, height=height, highlightthickness=0, borderwidth=0)
        self.player, self.job, self.poll_job = None, None, None
        self.source, self.kind, self.sound, self.waited = None, None, False, 0
        self.enabled = lambda: True
        parent.bind("<Destroy>", lambda e: self._gone() if e.widget is parent else None, add="+")

    def schedule(self, clip=None, stream=None):
        self.stop()
        if not self.enabled() or not backend()[0]:
            return
        if clip:
            self.source, self.kind, delay = clip, "clip", DELAY_MS
        elif stream and can_stream():
            self.source, self.kind, delay = stream, "stream", STREAM_DELAY_MS
        else:
            return
        self.job = self.parent.after(delay, self._start)

    def _start(self):
        self.job = None
        kind, prefix = backend()
        if not kind or not self.source or not self.parent.winfo_viewable():
            return
        self.frame.place(x=0, y=0, relwidth=1, relheight=1)
        if self.under is not None:
            self.frame.lower(self.under)  # behind the artwork until frames arrive
        self.frame.update_idletasks()
        try:
            if kind.startswith("mpv"):
                self.frame.configure(bg="black")
                self.player = MpvPlayer(self.frame, self.source, prefix, flatpak=kind == "mpv-flatpak",
                                        stream=self.kind == "stream")
            else:
                self.frame.configure(bg=self.bg)
                self.player = FfmpegPlayer(self.frame, self.source, prefix, self.width, self.height, self.bg)
        except OSError:
            self.player = None
            self.frame.place_forget()
            return
        self.sound, self.waited = False, 0
        self.on_change("loading", self.kind, False)
        self.poll_job = self.parent.after(POLL_MS, self._poll)

    def _poll(self):
        """Bring the video forward once it plays; give up (artwork stays) if the player quits or takes too long."""
        self.poll_job = None
        if not self.player:
            return
        if not self.player.alive():
            self.stop()
            return
        if self.player.started():
            self.frame.lift()
            self.on_change("playing", self.kind, self.player.can_sound)
            return
        self.waited += POLL_MS
        if self.waited >= LOAD_TIMEOUT_MS[self.kind]:
            self.stop()
            return
        self.poll_job = self.parent.after(POLL_MS, self._poll)

    def _gone(self):
        """The window is closing: only end the player's process (Tk is taking the widgets down itself)."""
        self.job = self.poll_job = None
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
        for job in (self.job, self.poll_job):  # pending timers: cancelled, never left to pile up
            if job:
                try:
                    self.parent.after_cancel(job)
                except tk.TclError:
                    pass
        self.job = self.poll_job = None
        was = self.player is not None
        if self.player:
            self.player.stop()
            self.player = None
        self.source = None
        try:
            self.frame.place_forget()
        except tk.TclError:
            pass
        if was:
            self.on_change("stopped", self.kind, False)
