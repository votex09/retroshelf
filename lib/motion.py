"""Short animations for Tk: eased tweens on after() timers, colour mixing, and a few ready-made effects.

Everything here is quick (well under half a second) and can be switched off (View → Animations); with ENABLED
False every effect jumps straight to its end state, so nothing depends on an animation having run."""
import math
import time
import tkinter as tk

ENABLED = True   # View → Animations (the app sets this from config.json)
FRAME_MS = 15    # ~60 frames a second; durations are wall-clock, so a slow frame shortens the tween, not stretches it
_running = {}    # (widget path, name) -> after id, so starting an effect again replaces the one in flight


def ease_out(t):
    """Fast start, gentle stop (cubic)."""
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def rgb(widget, color):
    """'#57c8ff' or a Tk colour name -> (r, g, b) in 0..255."""
    if isinstance(color, str) and color.startswith("#") and len(color) == 7:
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(v // 257 for v in widget.winfo_rgb(color))


def mix(widget, a, b, t):
    """The colour t of the way from a to b, as '#rrggbb'."""
    ca, cb = rgb(widget, a), rgb(widget, b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


def cancel(widget, name):
    after_id = _running.pop((str(widget), name), None)
    if after_id:
        try:
            widget.after_cancel(after_id)
        except Exception:
            pass


def running(widget, name):
    return (str(widget), name) in _running


def tween(widget, name, ms, step, done=None, ease=ease_out):
    """Call step(p) with p eased from 0 to 1 over ms milliseconds, then done(). Starting another tween with the same
    widget and name stops this one (without calling its done). Off, or for a widget that has gone: step(1) at once."""
    cancel(widget, name)
    key = (str(widget), name)

    def finish():
        _running.pop(key, None)
        try:
            step(1.0)
            if done:
                done()
        except Exception:  # the widget went away mid-way: nothing left to animate
            pass

    if not ENABLED or ms <= 0:
        finish()
        return
    start = time.perf_counter()

    def frame():
        try:
            if not widget.winfo_exists():
                _running.pop(key, None)
                return
        except Exception:
            _running.pop(key, None)
            return
        t = (time.perf_counter() - start) * 1000 / ms
        if t >= 1:
            finish()
            return
        try:
            step(ease(t))
        except Exception:
            _running.pop(key, None)
            return
        _running[key] = widget.after(FRAME_MS, frame)

    _running[key] = widget.after(0, frame)


def count(label, name, old, new, fmt, ms=260):
    """A label's numbers rolling from old to new: fmt(value) gives the text, with value a float between them
    (old and new are numbers, or tuples of numbers that roll together)."""
    if not isinstance(new, tuple):
        old, new = (old,), (new,)
        fmt_one = fmt
        fmt = lambda v: fmt_one(v[0])
    if old is None or len(old) != len(new) or old == new:
        cancel(label, name)
        label.config(text=fmt(new))
        return
    tween(label, name, ms, lambda p: label.config(
        text=fmt(new if p >= 1 else tuple(a + (b - a) * p for a, b in zip(old, new)))))


class RowGlow:
    """Rows that have just arrived in a Treeview light up in a colour that fades back to the row's own over a moment,
    so a flipped game is easy to spot in its new list. Uses tags glow0…glowN (even rows) and glowodd0… (odd rows,
    which carry the "odd" stripe tag). Tk lets the tag configured first win, so style(...) has to run before the stripe
    tag is first configured."""
    STEPS = 12

    def __init__(self, tv, ms=700):
        self.tv, self.ms, self.rows = tv, ms, {}  # iid -> colour family

    def style(self, colors, base, stripe):
        """colors: {family: glow colour}; base / stripe: the even / odd row backgrounds the glow fades into."""
        self.families = list(colors)
        for fam, col in colors.items():
            for i in range(self.STEPS):
                p = i / (self.STEPS - 1)
                self.tv.tag_configure(f"glow-{fam}-{i}", background=mix(self.tv, col, base, p))
                self.tv.tag_configure(f"glowodd-{fam}-{i}", background=mix(self.tv, col, stripe, p))

    def start(self, iids, family):
        """Light up these rows (already in the list) in one of the colour families given to style()."""
        if not ENABLED or not iids:
            return
        for iid in iids:
            self.rows[iid] = family
        tween(self.tv, "glow", self.ms, self._paint, ease=lambda t: t ** 0.6)

    def _paint(self, p):
        i = min(self.STEPS - 1, int(p * (self.STEPS - 1) + 0.5))
        last = p >= 1
        for iid, fam in list(self.rows.items()):
            if not self.tv.exists(iid):
                self.rows.pop(iid)
                continue
            tags = [t for t in self.tv.item(iid, "tags") if not t.startswith(("glow-", "glowodd-"))]
            if not last:
                tags.append(f"{'glowodd' if 'odd' in tags else 'glow'}-{fam}-{i}")
            self.tv.item(iid, tags=tags)
        if last:
            self.rows.clear()


class Fader:
    """Cross-fades a Label's picture from one image to the next (Pillow), and fades text tags in a Text widget.
    Rapid changes (holding an arrow key down a list) skip the fade so browsing never waits on it."""
    QUICK_MS = 140  # a change sooner than this after the last one shows at once

    def __init__(self, label, size, ms=170):
        self.label, self.size, self.ms = label, size, ms
        self.last_change = 0.0
        self.shown = None   # the PIL image on screen now (RGB, self.size), or None
        self.frames = None  # PhotoImages kept alive while fading

    def calm(self):
        """True when the last change was long enough ago that this one may animate."""
        now = time.perf_counter()
        calm = (now - self.last_change) * 1000 > self.QUICK_MS
        self.last_change = now
        return ENABLED and calm

    def show(self, pil, photo, bg, animate=True):
        """Put photo on the label; pil is the same picture as a Pillow image (or None when Pillow isn't there).
        With an earlier picture on screen, blend from it."""
        from PIL import Image, ImageTk
        cancel(self.label, "fade")
        new = None
        if pil is not None:
            new = Image.new("RGB", self.size, bg)
            im = pil.convert("RGBA")
            new.paste(im, ((self.size[0] - im.width) // 2, (self.size[1] - im.height) // 2), im)
        old, self.shown = self.shown, new
        if not animate or new is None:
            self.label.configure(image=photo)
            self.frames = None  # (after the label lets go of them: Tk forgets a PhotoImage once Python does)
            return
        start_im = old if old is not None else Image.new("RGB", self.size, bg)
        start = ImageTk.PhotoImage(start_im)
        self.label.configure(image=start)
        frames = self.frames = [photo, start]

        def step(p):
            if p >= 1:
                self.label.configure(image=photo)
                self.frames = None
                return
            f = ImageTk.PhotoImage(Image.blend(start_im, new, p))
            self.label.configure(image=f)
            frames[1] = f  # only the one on screen (and the final picture) stay referenced

        tween(self.label, "fade", self.ms, step)

    def forget(self):
        """The label now shows something else (text, a video): the next picture fades in from blank."""
        cancel(self.label, "fade")
        if self.frames:
            self.label.configure(image="")
        self.shown = self.frames = None


def fade_text(text, name, tags, ms=200, done=None):
    """Text widget tags fading in from the background: tags = {tag: final foreground}."""
    bg = text.cget("background")
    tween(text, name, ms, lambda p: [text.tag_configure(tag, foreground=mix(text, bg, fg, p))
                                     for tag, fg in tags.items()], done=done)


def progress(bar, name, value, ms=420):
    """A determinate ttk.Progressbar gliding to value."""
    try:
        old = float(bar.cget("value"))
    except (TypeError, ValueError):
        old = 0.0
    tween(bar, name, ms, lambda p: bar.config(value=old + (value - old) * p), ease=ease_in_out)


class RowHover:
    """The row under the mouse lights up gently instead of at once, and the one it left fades back. Tags hover-1…N
    (even rows) and hoverodd-1…N (striped rows); like RowGlow's, style(...) runs before the stripe tag is first
    configured, and before the glow's, so a hovered row shows the hover."""
    STEPS, MS = 6, 130

    def __init__(self, tv):
        self.tv, self.levels, self.target = tv, {}, None  # iid -> 0..1 shown now

    def style(self, hover, base, stripe):
        for i in range(1, self.STEPS + 1):
            p = i / self.STEPS
            self.tv.tag_configure(f"hover-{i}", background=mix(self.tv, base, hover, p))
            self.tv.tag_configure(f"hoverodd-{i}", background=mix(self.tv, stripe, hover, p))

    def set(self, row):
        """The mouse is over row now (None: over no row)."""
        if row == self.target:
            return
        self.target = row
        start = dict(self.levels)
        if row and row not in start:
            start[row] = 0.0
        tween(self.tv, "hover", self.MS if ENABLED else 0, lambda p: self._paint(start, p), ease=lambda t: t)

    def reset(self):
        """The list was rebuilt: no row is lit."""
        cancel(self.tv, "hover")
        self.levels, self.target = {}, None

    def _paint(self, start, p):
        for iid, level in start.items():
            goal = 1.0 if iid == self.target else 0.0
            now = level + (goal - level) * p
            if not self.tv.exists(iid):
                self.levels.pop(iid, None)
                continue
            step = round(now * self.STEPS)
            tags = [t for t in self.tv.item(iid, "tags") if not t.startswith(("hover-", "hoverodd-"))]
            if step:
                tags.append(f"{'hoverodd' if 'odd' in tags else 'hover'}-{step}")
                self.levels[iid] = now
            else:
                self.levels.pop(iid, None)
            self.tv.item(iid, tags=tags)


def fly(root, text, src, dst, bg, fg, font, delay=0, ms=420):
    """A game's name lifting off one list and flying to its place in the other: a label from src to dst, rectangles
    (x, y, w, h) in root's coordinates, gone when it lands (the row it lands on then glows)."""
    if not ENABLED:
        return
    lbl = tk.Label(root, text=text, bg=bg, fg=fg, font=font, anchor="w", padx=6, bd=0, highlightthickness=1,
                   highlightbackground=fg)
    lbl.pad_ring = True  # (not a widget anyone navigates to)

    def step(p):
        x, y, w, h = (a + (b - a) * p for a, b in zip(src, dst))
        lift = 6 * (1 - abs(1 - 2 * p))  # rises a little mid-flight
        lbl.place(in_=root, x=round(x - lift), y=round(y - lift), width=max(20, round(w)), height=round(h))
        tk.Misc.lift(lbl)

    def go():
        tween(lbl, "fly", ms, step, done=lbl.destroy, ease=ease_in_out)

    if delay:
        lbl.after(delay, go)
    else:
        go()


WHEEL_ROWS = 3       # a notch of the wheel: rows in a list…
WHEEL_PIXELS = 60    # …or pixels in a text box
WHEEL_TAU_MS = 60    # how quickly a glide catches up with the wheel: it eases out, mostly done in ~3x this
_wheel_left = {}     # widget path -> how far it still has to go (rows or pixels, signed)


def smooth_scroll(root):
    """Wheel scrolling in every list (Treeview, Listbox) and text box glides to where it is going instead of jumping
    there, easing out, and quick flicks add up into one longer glide. Lists move a row at a time (Tk can't scroll them
    by the pixel), text by the pixel. Set once for the whole app: it replaces Tk's class bindings, so dialogs get it
    too."""
    system = root.tk.call("tk", "windowingsystem")
    per_notch = 1 if system == "aqua" else 120  # what one notch of the wheel reports as its delta
    for cls, unit in (("Treeview", "units"), ("Listbox", "units"), ("Text", "pixels")):
        root.bind_class(cls, "<MouseWheel>", lambda e, u=unit: _wheel(e.widget, -e.delta / per_notch, u))
        if system == "x11":  # X11 wheels come through as buttons 4 and 5
            root.bind_class(cls, "<Button-4>", lambda e, u=unit: _wheel(e.widget, -1, u))
            root.bind_class(cls, "<Button-5>", lambda e, u=unit: _wheel(e.widget, 1, u))


def _wheel(w, notches, unit):
    key = str(w)
    left = _wheel_left.get(key, 0.0)
    if left * notches < 0:  # turned the other way: drop what was left of the last glide
        left = 0.0
        cancel(w, "wheel")
    left += notches * (WHEEL_PIXELS if unit == "pixels" else WHEEL_ROWS)
    _wheel_left[key] = left
    if not ENABLED:
        if int(left):
            _scroll(w, key, int(left), unit)
        return "break"
    if running(w, "wheel"):
        return "break"  # the glide under way picks up the extra distance
    state = {"last": time.perf_counter(), "due": 0.0}  # due: movement owed but not yet a whole row / pixel

    def frame():
        now = time.perf_counter()
        left = _wheel_left.get(key, 0.0)
        state["due"] += left * (1 - math.exp(-(now - state["last"]) * 1000 / WHEEL_TAU_MS))
        state["last"] = now
        n = int(state["due"])
        if abs(left - n) < 0.5:  # close enough: land
            n = round(left)
        if n:
            if not _scroll(w, key, n, unit):
                _running.pop((key, "wheel"), None)  # at an end
                return
            state["due"] -= n
        if abs(_wheel_left.get(key, 0.0)) < 0.5:
            _running.pop((key, "wheel"), None)  # arrived (a touchpad's part-notch stays for its next nudge)
            return
        _running[(key, "wheel")] = w.after(FRAME_MS, frame)

    _running[(key, "wheel")] = w.after(0, frame)
    return "break"


def _scroll(w, key, n, unit):
    """Scroll w by n rows / pixels and take them off what it has left; False when it couldn't move (at an end, or
    gone), which also forgets the rest."""
    try:
        before = w.yview()
        w.yview_scroll(n, unit)
        moved = w.yview() != before
    except Exception:
        moved = False
    if moved:
        _wheel_left[key] = _wheel_left.get(key, 0.0) - n
    else:
        _wheel_left.pop(key, None)
    return moved
