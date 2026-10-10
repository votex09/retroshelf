"""Game details panel: artwork already on disk (ES-DE downloaded_media), LaunchBox text, and a gameplay-video link.
Pillow, when installed, shows JPEG art and scales smoothly; without it only PNG / GIF art can be shown."""
import math, os, urllib.parse, webbrowser
import tkinter as tk
from tkinter import ttk

import video
from ui import stars

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

MEDIA_ORDER = ["covers", "3dboxes", "miximages", "screenshots", "titlescreens", "physicalmedia", "marquees"]
IMG_W, IMG_H = 280, 220
PLAY_VIDEOS = True     # View → Play gameplay videos: ES-DE's local clips (the app sets these from config.json)
STREAM_VIDEOS = False  # View → … and stream from YouTube when there's no clip (mpv + yt-dlp)
_listings = {}  # media folder -> (mtime, {stem: [file names]})


def media_for(media_dir, stems):
    """Image paths for a game, in MEDIA_ORDER, skipping formats Tk can't show without Pillow."""
    out = []
    for mtype in MEDIA_ORDER:
        folder = os.path.join(media_dir, mtype)
        try:
            mtime = os.stat(folder).st_mtime
        except OSError:
            continue
        cached = _listings.get(folder)
        if not cached or cached[0] != mtime:
            by_stem = {}
            for f in os.listdir(folder):
                by_stem.setdefault(os.path.splitext(f)[0], []).append(f)
            cached = _listings[folder] = (mtime, by_stem)
        for stem in stems:
            for f in cached[1].get(stem, []):
                if Image or f.lower().endswith((".png", ".gif")):
                    out.append((mtype, os.path.join(folder, f)))
    return out


def load_image(path, w=IMG_W, h=IMG_H):
    if Image:
        with Image.open(path) as im:
            im.thumbnail((w, h))
            return ImageTk.PhotoImage(im.convert("RGBA"))
    img = tk.PhotoImage(file=path)
    factor = max(1, math.ceil(max(img.width() / w, img.height() / h)))
    return img.subsample(factor) if factor > 1 else img


def video_url(title, console):
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(f"{title} {console} gameplay")


class DetailsPanel(ttk.Frame):
    """show(info) with info = {title, console, lb (LaunchBox game dict or None), det (LaunchBox details dict),
    media_dir, stems, file, size}; clear(text) for nothing / several selected."""

    def __init__(self, parent, field_style=None, wide=False, padding=(10, 0, 0, 0)):
        """wide: artwork on the left and text on the right, for a short band instead of a tall column."""
        super().__init__(parent, padding=padding)
        self.images, self.index, self.photo, self.info = [], 0, None, None
        self.img_w, self.img_h = (200, 150) if wide else (IMG_W, IMG_H)
        left = ttk.Frame(self)
        left.pack(side="left", fill="y") if wide else left.pack(fill="x")
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0)) if wide else \
            right.pack(fill="both", expand=True)
        box = ttk.Frame(left, width=self.img_w, height=self.img_h)  # fixed size: no jumping between games
        box.pack_propagate(False)
        box.pack()
        self.pic = tk.Label(box, borderwidth=0, highlightthickness=0, wraplength=self.img_w - 20)
        self.pic.pack(fill="both", expand=True)
        self.spot = video.Spot(box, self.img_w, self.img_h, "black", self._video_state, under=self.pic)
        self.spot.enabled = lambda: PLAY_VIDEOS
        nav = ttk.Frame(left)
        nav.pack(fill="x", pady=(4, 0))
        self.prev_btn = ttk.Button(nav, text="‹", width=3, command=lambda: self._step(-1))
        self.prev_btn.pack(side="left")
        self.next_btn = ttk.Button(nav, text="›", width=3, command=lambda: self._step(1))
        self.next_btn.pack(side="right")
        self.sound_btn = ttk.Button(nav, text="🔇", width=3, command=self._toggle_sound)  # shown while a video plays
        self.pic_lbl = ttk.Label(nav, style="Muted.TLabel", anchor="center")
        self.pic_lbl.pack(side="left", fill="x", expand=True)
        self.video_btn = ttk.Button(right, text="Gameplay video ↗", command=self._video)
        self.video_btn.pack(side="bottom", fill="x", pady=(6 if wide else 8, 0))
        # title, facts and description share one scrolling box, so long text never pushes anything off screen
        self.desc = tk.Text(right, wrap="word", width=1, height=4, padx=10, pady=8, cursor="arrow",
                            font="SunValleyBodyFont", spacing1=1, spacing3=1)
        self.desc.tag_configure("title", font="SunValleyBodyStrongFont", spacing3=4)
        self.desc.tag_configure("gap", spacing1=8)
        self.desc.pack(fill="both", expand=True, pady=(0 if wide else 8, 0))
        self.restyle(field_style)
        self.clear("Select a game to see its details.")

    def restyle(self, field_style):
        st = ttk.Style()
        bg = st.lookup("TFrame", "background") or st.lookup(".", "background")
        if bg:
            self.pic.configure(bg=bg)
        if field_style:
            self.desc.configure(**{k: v for k, v in field_style.items() if k != "selectforeground"},
                                insertbackground=field_style["fg"])
        muted = st.lookup("Muted.TLabel", "foreground")
        if muted:
            self.desc.tag_configure("meta", foreground=muted)

    def _set_desc(self, *parts):
        """parts: (text, tag) pairs."""
        self.desc.configure(state="normal")
        self.desc.delete("1.0", "end")
        for text, tag in parts:
            self.desc.insert("end", text, tag)
        self.desc.configure(state="disabled")
        self.desc.yview_moveto(0)

    def placeholder(self, title, body, image=None, action=None):
        """Friendly state when no single game is selected: an icon, a heading, some tips and an optional button
        (action = (label, command)) in place of the video link."""
        self.clear()
        if image is not None:
            self.pic.configure(image=image, text="")
            self.photo = image
        self._set_desc((title + "\n", "title"), (body, "meta"))
        if action:
            self.video_btn.configure(text=action[0], command=action[1], style="Accent.TButton")
            self.video_btn.state(["!disabled"])

    def _video_state(self, state, kind, can_sound):
        if state == "playing" and can_sound:
            self.sound_btn.configure(text="🔇")
            self.sound_btn.pack(side="right", padx=(0, 4), before=self.pic_lbl)
        else:
            self.sound_btn.pack_forget()
        if state == "loading" and kind == "stream":
            self.pic_lbl.config(text="finding a video…")
        elif state == "playing":
            self.pic_lbl.config(text="YouTube" if kind == "stream" else "video")
            self.prev_btn.state(["!disabled"])
            self.next_btn.state(["!disabled"])
        elif state == "stopped":
            self._caption()

    def _toggle_sound(self):
        self.sound_btn.configure(text="🔊" if self.spot.toggle_sound() else "🔇")

    def clear(self, text=""):
        self.spot.stop()
        self.info, self.images, self.photo = None, [], None
        self.pic.configure(image="", text=text, fg=ttk.Style().lookup("Muted.TLabel", "foreground") or "gray")
        self.pic_lbl.config(text="")
        self.prev_btn.state(["disabled"])
        self.next_btn.state(["disabled"])
        self._set_desc()
        self.video_btn.configure(text="Gameplay video ↗", command=self._video, style="TButton")
        self.video_btn.state(["disabled"])

    def show(self, info):
        self.info = info
        self.video_btn.configure(text="Gameplay video ↗", command=self._video, style="TButton")
        self.images = media_for(info["media_dir"], info["stems"])
        self.index = 0
        self._show_image()
        self.spot.schedule(video.video_for(info["media_dir"], info["stems"]),
                           video.youtube_query(info["title"], info["console"]) if STREAM_VIDEOS else None)
        g, det = info.get("lb"), info.get("det") or {}
        bits = [b for b in (
            (det.get("rd") or "")[:4], det.get("d"),
            det.get("p") if det.get("p") != det.get("d") else None,
            f"{det['mp']} players" if (det.get("mp") or 0) > 1 else None,
        ) if b]
        lines = ["  ·  ".join(bits)] if bits else []
        if g:
            rating = f"{stars(g['r'])}  {g['r']:.1f}  ·  {g['v']} votes" if g.get("r") is not None else "No rating"
            lines.append("  ·  ".join([rating] + ([", ".join(g["g"])] if g.get("g") else [])))
        else:
            lines.append("Not matched in LaunchBox")
        lines.append(f"{info['file']}  ·  {info['size']}")
        self._set_desc((info["title"] + "\n", "title"), ("\n".join(lines) + "\n", "meta"),
                       ((det.get("o") or "").strip() or "No description.", "gap"))
        self.video_btn.state(["!disabled"])

    def _show_image(self):
        self.photo = None
        while self.images and self.photo is None:
            try:
                self.photo = load_image(self.images[self.index][1], self.img_w, self.img_h)
            except Exception:  # unreadable / unsupported file: drop it and try the next one
                del self.images[self.index]
                self.index = min(self.index, max(len(self.images) - 1, 0))
        if self.photo is None:
            note = "No artwork on disk — Scrape metadata… adds it"
            if not Image:
                note += "\n(install Pillow to show JPEG art)"
            self.pic.configure(image="", text=note)
        else:
            self.pic.configure(image=self.photo, text="")
        self._caption()

    def _caption(self):
        """Which picture this is, and the ‹ › buttons for the others."""
        self.pic_lbl.config(text=f"{self.images[self.index][0]}  ·  {self.index + 1} / {len(self.images)}"
                            if self.photo is not None and self.images else "")
        many = len(self.images) > 1
        self.prev_btn.state(["!disabled" if many else "disabled"])
        self.next_btn.state(["!disabled" if many else "disabled"])

    def _step(self, d):
        if self.spot.playing():  # back to the pictures, starting with the first
            self.spot.stop()
            self._show_image()
            return
        if self.images:
            self.index = (self.index + d) % len(self.images)
            self._show_image()

    def _video(self):
        if self.info:
            webbrowser.open(video_url(self.info["title"], self.info["console"]))
