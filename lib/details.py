"""Game details panel: artwork already on disk (ES-DE downloaded_media), LaunchBox text, and a gameplay-video link.
Pillow, when installed, shows JPEG art and draws every picture to fill one fixed box (rounded, with a shadow), so
nothing moves between games; without it only PNG / GIF art can be shown, as it comes."""
import math, os, urllib.parse, webbrowser
import tkinter as tk
from tkinter import ttk

import motion
import video
from ui import stars

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageTk
except ImportError:
    Image = ImageTk = None

MEDIA_ORDER = ["covers", "3dboxes", "miximages", "screenshots", "titlescreens", "physicalmedia", "marquees"]
IMG_W, IMG_H = 280, 220
WIDE_W, WIDE_H = 224, 168  # the main window's details band: as tall as the filter tabs beside it allow
RADIUS, MARGIN = 10, 6      # artwork corners, and room around it for its shadow
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


def load_picture(path, w=IMG_W, h=IMG_H, bg="#202020"):
    """(Pillow image or None, PhotoImage) for a picture in a w x h box. With Pillow, the picture is scaled to fill
    the box as far as it goes either way (a small marquee comes up to size, not lost in the middle), with rounded
    corners and a soft shadow, on the box's background: every picture is then exactly w x h."""
    if Image:
        with Image.open(path) as im:
            im = im.convert("RGBA")
        out = framed(im, w, h, bg)
        return out, ImageTk.PhotoImage(out)
    return None, _tk_image(path, w, h)


def _rgb(color):
    color = color.lstrip("#")
    if len(color) == 12:  # #rrrrggggbbbb from Tk
        return tuple(int(color[i:i + 2], 16) for i in (0, 4, 8))
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4)) if len(color) == 6 else (32, 32, 32)


def framed(im, w, h, bg):
    """im fitted into w x h less a margin, rounded, over a soft shadow, on bg (an RGB image w x h)."""
    aw, ah = w - 2 * MARGIN, h - 2 * MARGIN
    scale = min(aw / im.width, ah / im.height)
    size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
    # pixel art and tiny pictures stay crisp when blown up a lot; everything else is smoothed
    im = im.resize(size, Image.NEAREST if scale >= 3 else Image.LANCZOS)
    base = _rgb(bg) if isinstance(bg, str) and bg.startswith("#") else (32, 32, 32)
    out = Image.new("RGB", (w, h), base)
    x, y = (w - size[0]) // 2, (h - size[1]) // 2
    r = min(RADIUS, size[0] // 4, size[1] // 4)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), r, fill=255)
    shadow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shadow).rounded_rectangle((x + 1, y + 3, x + size[0] + 1, y + size[1] + 3), r, fill=150)
    shadow = shadow.filter(ImageFilter.GaussianBlur(4))
    out.paste((0, 0, 0), (0, 0), shadow)
    alpha = Image.composite(im.getchannel("A"), Image.new("L", size, 0), mask)
    out.paste(im.convert("RGB"), (x, y), alpha)
    return out


def card(w, h, bg, fill):
    """An empty rounded card the size of the artwork box: what stands in when there's no picture."""
    out = Image.new("RGB", (w, h), _rgb(bg))
    ImageDraw.Draw(out).rounded_rectangle((MARGIN, MARGIN, w - MARGIN - 1, h - MARGIN - 1), RADIUS,
                                          fill=_rgb(fill))
    return out


def _tk_image(path, w, h):
    img = tk.PhotoImage(file=path)
    factor = max(1, math.ceil(max(img.width() / w, img.height() / h)))
    return img.subsample(factor) if factor > 1 else img


def video_url(title, console):
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(f"{title} {console} gameplay")


class DetailsPanel(ttk.Frame):
    """show(info) with info = {title, console, lb (LaunchBox game dict or None), det (LaunchBox details dict),
    media_dir, stems, file, size}; clear(text) for nothing / several selected."""

    def __init__(self, parent, field_style=None, wide=False, padding=(10, 0, 0, 0), art=None):
        """wide: artwork on the left and text on the right, for a short band instead of a tall column.
        art: (width, height) of the artwork box, for a window with room for more than the usual."""
        super().__init__(parent, padding=padding)
        self.images, self.index, self.photo, self.info = [], 0, None, None
        self.img_w, self.img_h = art or ((WIDE_W, WIDE_H) if wide else (IMG_W, IMG_H))
        left = ttk.Frame(self)
        left.pack(side="left", fill="y") if wide else left.pack(fill="x")
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0)) if wide else \
            right.pack(fill="both", expand=True)
        box = ttk.Frame(left, width=self.img_w, height=self.img_h)  # fixed size: no jumping between games
        box.pack_propagate(False)
        box.pack()
        self.pic = tk.Label(box, borderwidth=0, highlightthickness=0, wraplength=self.img_w - 40, compound="center",
                            font="SunValleyCaptionFont")
        self.pic.pack(fill="both", expand=True)
        self.fader = motion.Fader(self.pic, (self.img_w, self.img_h)) if Image else None
        self.spot = video.Spot(box, self.img_w, self.img_h, "black", self._video_state, under=self.pic)
        self.spot.enabled = lambda: PLAY_VIDEOS
        nav = ttk.Frame(left)
        nav.pack(fill="x", pady=(4, 0))
        self.prev_btn = ttk.Button(nav, text="‹", width=3, command=lambda: self._step(-1))
        self.prev_btn.pack(side="left")
        self.next_btn = ttk.Button(nav, text="›", width=3, command=lambda: self._step(1))
        self.next_btn.pack(side="right")
        self.sound_btn = ttk.Button(nav, text="🔇", width=3, command=self._toggle_sound)  # shown while a video plays
        # width=1: a long caption ("screenshots · 12 / 14", "finding a video…") is cut short, never widening the
        # column and shifting everything beside it
        self.pic_lbl = ttk.Label(nav, style="Muted.TLabel", anchor="center", width=1)
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
        self.muted = muted or "gray"
        motion.cancel(self.desc, "text")
        self.desc.tag_configure("meta", foreground=self.muted)
        for tag in ("title", "gap"):
            self.desc.tag_configure(tag, foreground="")
        if getattr(self, "info", None) and not self.spot.playing():  # artwork is drawn on the background: redraw
            self._show_image()
        elif getattr(self, "card_text", None) is not None:
            self._card(self.card_text)

    def _bg(self):
        return "#%02x%02x%02x" % motion.rgb(self.pic, self.pic.cget("bg"))

    def _card(self, text):
        """The empty artwork box: a rounded card with text on it (plain text without Pillow)."""
        self.card_text = text
        if self.fader:
            self.fader.forget()
        if not Image:
            self.pic.configure(image="", text=text)
            return
        bg = self._bg()
        pil = card(self.img_w, self.img_h, bg, motion.mix(self.pic, bg, self.muted, 0.12))
        self.card_photo = ImageTk.PhotoImage(pil)
        self.pic.configure(image=self.card_photo, text=text)
        self.fader.shown = pil  # the next picture fades in from the card

    def _set_desc(self, *parts, fade=False):
        """parts: (text, tag) pairs. fade: the text fades in from the background."""
        self.desc.configure(state="normal")
        self.desc.delete("1.0", "end")
        for text, tag in parts:
            self.desc.insert("end", text, tag)
        self.desc.configure(state="disabled")
        self.desc.yview_moveto(0)
        if fade and motion.ENABLED:
            fg = self.desc.cget("foreground")
            motion.fade_text(self.desc, "text", {"title": fg, "meta": self.muted, "gap": fg}, done=lambda: [
                self.desc.tag_configure(t, foreground="") for t in ("title", "gap")])  # follow the theme again

    def placeholder(self, title, body, image=None, action=None):
        """Friendly state when no single game is selected: an icon, a heading, some tips and an optional button
        (action = (label, command)) in place of the video link."""
        calm = self._calm()
        self.clear()
        if image is not None:
            self.card_text = None
            if self.fader:
                self.fader.forget()
            self.pic.configure(image=image, text="")
            self.photo = image
        self._set_desc((title + "\n", "title"), (body, "meta"), fade=calm)
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

    def _calm(self):
        """Whether this change may animate: not while flicking quickly from game to game."""
        return self.fader.calm() if self.fader else False

    def clear(self, text=""):
        self.spot.stop()
        if self.fader:
            self.fader.forget()
        self.info, self.images, self.photo = None, [], None
        self.pic.configure(fg=self.muted)
        self._card(text)
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
        calm = self._calm()
        self._show_image(animate=calm)
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
                       ((det.get("o") or "").strip() or "No description.", "gap"), fade=calm)
        self.video_btn.state(["!disabled"])

    def _show_image(self, animate=False):
        self.photo = pil = None
        while self.images and self.photo is None:
            try:
                pil, self.photo = load_picture(self.images[self.index][1], self.img_w, self.img_h, self._bg())
            except Exception:  # unreadable / unsupported file: drop it and try the next one
                del self.images[self.index]
                self.index = min(self.index, max(len(self.images) - 1, 0))
        if self.photo is None:
            note = "No artwork on disk — Scrape metadata… adds it"
            if not Image:
                note += "\n(install Pillow to show JPEG art)"
            self._card(note)
        elif self.fader:
            self.card_text = None
            self.fader.show(pil, self.photo, self._bg(), animate)  # (sets the image first: the old one's gone)
            self.pic.configure(text="")
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
            self._show_image(animate=self._calm())

    def _video(self):
        if self.info:
            webbrowser.open(video_url(self.info["title"], self.info["console"]))
