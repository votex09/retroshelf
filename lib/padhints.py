"""On-screen button hints: while a gamepad was the last thing used, the window with the keyboard shows a bar of the
buttons that do something there, drawn as the pad's own glyphs (Xbox letters, PlayStation shapes, Nintendo letters),
and what each one does right now ("Mark", "Move 3 marked", "Keep", …). A key press or a mouse move hides it.

What a button does depends on where the keyboard is:
  - a widget (or one of its parents, up to its window) with a pad_hints() method says so itself: the Keeping /
    Moving lists (lib/listkeys.py) and Review (lib/review.py) do;
  - anything else gets hints by its kind: buttons press, ticks tick, lists browse, …;
  - and Start / B are added wherever the window has their keys (Ctrl+R, Escape).
A hint is (button, label), button one of a b x y lb rb lt rt start, two joined by "+" ("lb+rb"), or "dpad:" with the
directions it uses ("dpad:ud", "dpad:lr")."""
import re
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

TAG = "pad"

# button -> what the pad has printed on it: (text or shape, colour); shoulders and triggers are just text
STYLES = {
    "xbox": {"a": ("A", "#6cc04a"), "b": ("B", "#ec4f45"), "x": ("X", "#4a95e6"), "y": ("Y", "#f2c418"),
             "lb": "LB", "rb": "RB", "lt": "LT", "rt": "RT", "start": "menu", "select": "view"},
    "playstation": {"a": ("cross", "#8fb3ec"), "b": ("circle", "#f07272"), "x": ("triangle", "#41cba5"),
                    "y": ("square", "#e594cf"), "lb": "L1", "rb": "R1", "lt": "L2", "rt": "R2", "start": "menu",
                    "select": "create"},
    # the kernel reports Nintendo pads by position: the bottom button (B on the pad) is the one others call A
    "nintendo": {"a": ("B", "#f0f0f0"), "b": ("A", "#f0f0f0"), "x": ("X", "#f0f0f0"), "y": ("Y", "#f0f0f0"),
                 "lb": "L", "rb": "R", "lt": "ZL", "rt": "ZR", "start": "plus", "select": "minus"},
}
PLAYSTATION = re.compile(r"sony|playstation|dualshock|dualsense|\bps[345]\b|^wireless controller$", re.I)
NINTENDO = re.compile(r"nintendo|switch|pro controller|joy-?con", re.I)

# the keys a window has to bind for Start / B to mean something there
COMMON = [("start", "<Control-r>", "Review"), ("select", "<F6>", "Lists · search · filters"), ("b", "<Escape>", "Close")]


def style_for(name):
    """Which glyphs a pad has, from the name it reports."""
    name = (name or "").strip()
    if PLAYSTATION.search(name):
        return "playstation"
    if NINTENDO.search(name):
        return "nintendo"
    return "xbox"


# ---------- what the buttons do here ----------
def _widget(root, path):
    try:
        return root.nametowidget(path)
    except (KeyError, tk.TclError):
        return None  # made by Tk itself (a combobox's drop-down list)


def _ancestors(path):
    """'.a.b.c' -> '.a.b.c', '.a.b', '.a', '.'"""
    while path and path != ".":
        yield path
        path = path.rsplit(".", 1)[0] or "."
    yield "."


def generic(root, path):
    """Hints for a widget nobody described: by what kind of widget it is."""
    call = root.tk.call
    try:
        kind = str(call("winfo", "class", path))
        disabled = kind.startswith("T") and bool(call(path, "instate", "disabled"))
    except tk.TclError:
        return []
    out = []
    if kind in ("TButton", "Button", "TMenubutton"):
        if not disabled:
            out.append(("a", "Press"))
    elif kind in ("TCheckbutton", "Checkbutton"):
        if not disabled:
            ticked = kind == "TCheckbutton" and bool(call(path, "instate", "selected"))
            out.append(("a", "Untick" if ticked else "Tick"))
    elif kind in ("TRadiobutton", "Radiobutton"):
        if not disabled:
            out.append(("a", "Choose"))
    elif kind == "Treeview":
        out += [("dpad:ud", "Browse"), ("lt+rt", "Page")]
    elif kind == "Listbox":
        out += [("dpad:ud", "Browse"), ("x", "Choose")]
    elif kind == "TCombobox":
        out.append(("dpad:ud", "Open the list"))
    elif kind in ("TEntry", "Entry"):
        try:
            typable = str(call(path, "cget", "-state")) not in ("readonly", "disabled") and not disabled
        except tk.TclError:
            typable = False
        if typable:
            out.append(("a", "Keyboard"))  # the on-screen one (lib/osk.py)
        out.append(("dpad:lr", "Move the cursor"))
    elif kind in ("TSpinbox", "Spinbox"):
        out.append(("dpad:ud", "Change"))
    elif kind in ("TScale", "Scale"):
        out.append(("dpad:lr", "Adjust"))
    elif kind == "TNotebook":
        out.append(("dpad:lr", "Switch tabs"))
    if kind not in ("Text", "Listbox"):  # Tab types a tab in text, and a drop-down list has nowhere to go
        out.append(("lb+rb", "Previous / next control"))
    return out


def hints_for(root, path):
    """[(button, label)] for the widget at path (the one with the keyboard)."""
    path = str(path)
    hints = None
    for p in _ancestors(path):
        w = _widget(root, p)
        fn = getattr(w, "pad_hints", None) if w is not None else None
        if callable(fn):
            hints = fn()
            if hints is not None:
                break
    hints = list(hints) if hints is not None else generic(root, path)
    try:
        top = str(root.tk.call("winfo", "toplevel", path))
    except tk.TclError:
        return hints
    used = {b for hint, _ in hints for b in hint.split("+")}
    for button, seq, label in COMMON:
        if button not in used and root.tk.call("bind", top, seq):
            hints.append((button, label))
    return hints


# ---------- drawing ----------
class Glyphs:
    """Draws buttons on a canvas, at a size that follows the screen's scale."""

    def __init__(self, canvas, scale):
        self.c, self.s = canvas, scale
        self.d = round(22 * scale)  # a face button's diameter
        base = tkfont.nametofont("TkDefaultFont").actual()
        self.bold = tkfont.Font(family=base["family"], size=-round(12 * scale), weight="bold")
        self.small = tkfont.Font(family=base["family"], size=-round(10 * scale), weight="bold")

    def draw(self, button, x, cy, style, chip, ink):
        """-> width drawn. button: one hint's button ('a', 'lb+rb', 'dpad:ud', …)."""
        if "+" in button:
            w = 0
            for i, part in enumerate(button.split("+")):
                w += (round(3 * self.s) if i else 0)
                w += self.draw(part, x + w, cy, style, chip, ink)
            return w
        if button.startswith("dpad"):
            return self.dpad(x, cy, button.partition(":")[2], chip, ink)
        face = STYLES[style].get(button)
        if button in ("a", "b", "x", "y"):
            return self.face(x, cy, *face, chip=chip)
        if button in ("start", "select"):
            return self.start(x, cy, face, chip, ink)
        return self.shoulder(x, cy, face or button.upper(), chip, ink, trigger=button in ("lt", "rt"))

    def face(self, x, cy, mark, color, chip):
        c, d, s = self.c, self.d, self.s
        r = d / 2
        c.create_oval(x, cy - r, x + d, cy + r, fill=chip, outline="", tags=TAG)
        mx, k, w = x + r, r * 0.45, max(2, round(2 * s))
        if mark == "cross":
            c.create_line(mx - k, cy - k, mx + k, cy + k, fill=color, width=w, capstyle="round", tags=TAG)
            c.create_line(mx - k, cy + k, mx + k, cy - k, fill=color, width=w, capstyle="round", tags=TAG)
        elif mark == "circle":
            c.create_oval(mx - k, cy - k, mx + k, cy + k, outline=color, width=w, tags=TAG)
        elif mark == "triangle":
            c.create_polygon(mx, cy - k * 1.1, mx + k * 1.05, cy + k * 0.75, mx - k * 1.05, cy + k * 0.75,
                             outline=color, fill="", width=w, joinstyle="round", tags=TAG)
        elif mark == "square":
            q = k * 0.85
            c.create_rectangle(mx - q, cy - q, mx + q, cy + q, outline=color, width=w, tags=TAG)
        else:
            c.create_text(mx, cy, text=mark, fill=color, font=self.bold, tags=TAG)
        return d

    def _rounded(self, x0, y0, x1, y1, r, fill):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1,
               x0, y1 - r, x0, y0 + r, x0, y0]
        self.c.create_polygon(pts, smooth=True, fill=fill, outline="", tags=TAG)

    def shoulder(self, x, cy, text, chip, ink, trigger=False):
        h = self.d * (0.9 if trigger else 0.72)
        w = max(self.small.measure(text) + round(12 * self.s), self.d * 1.2)
        top = cy - h / 2
        self._rounded(x, top, x + w, cy + h / 2, h / (2.4 if trigger else 2), chip)
        self.c.create_text(x + w / 2, cy, text=text, fill=ink, font=self.small, tags=TAG)
        return round(w)

    def start(self, x, cy, mark, chip, ink):
        d = round(self.d * 0.9)
        r = d / 2
        self.c.create_oval(x, cy - r, x + d, cy + r, fill=chip, outline="", tags=TAG)
        mx, k, w = x + r, r * 0.45, max(1, round(1.6 * self.s))
        if mark == "plus":
            self.c.create_line(mx - k, cy, mx + k, cy, fill=ink, width=w + 1, tags=TAG)
            self.c.create_line(mx, cy - k, mx, cy + k, fill=ink, width=w + 1, tags=TAG)
        elif mark == "minus":
            self.c.create_line(mx - k, cy, mx + k, cy, fill=ink, width=w + 1, tags=TAG)
        elif mark == "view":  # two overlapping windows
            q = k * 0.75
            self.c.create_rectangle(mx - k, cy - k * 0.8, mx - k + 2 * q, cy - k * 0.8 + 1.5 * q, outline=ink,
                                    width=w, tags=TAG)
            self.c.create_rectangle(mx + k - 2 * q, cy + k * 0.8 - 1.5 * q, mx + k, cy + k * 0.8, outline=ink,
                                    fill=chip, width=w, tags=TAG)
        elif mark == "create":  # three short upright strokes
            for dx in (-k * 0.6, 0, k * 0.6):
                self.c.create_line(mx + dx, cy - k * 0.7, mx + dx, cy + k * 0.7, fill=ink, width=w, tags=TAG)
        else:  # ☰
            for dy in (-k * 0.7, 0, k * 0.7):
                self.c.create_line(mx - k, cy + dy, mx + k, cy + dy, fill=ink, width=w, tags=TAG)
        return d

    def dpad(self, x, cy, dirs, chip, ink):
        """A plus-shaped pad; the arms that do something here carry an arrow."""
        c, d = self.c, self.d
        a = d * 0.38  # arm width
        top, mx = cy - d / 2, x + d / 2
        c.create_rectangle(mx - a / 2, top, mx + a / 2, top + d, fill=chip, outline="", tags=TAG)
        c.create_rectangle(x, cy - a / 2, x + d, cy + a / 2, fill=chip, outline="", tags=TAG)
        reach = (d - a) / 4 + a / 2  # from the middle to the middle of an arm
        k = a * 0.36  # half an arrow's width
        for side, (ux, uy) in (("u", (0, -1)), ("d", (0, 1)), ("l", (-1, 0)), ("r", (1, 0))):
            if side not in dirs:
                continue
            px, py = mx + ux * (reach + k * 0.6), cy + uy * (reach + k * 0.6)  # the arrow's point
            bx, by = mx + ux * (reach - k * 0.6), cy + uy * (reach - k * 0.6)  # the middle of its base
            c.create_polygon(px, py, bx + uy * k, by + ux * k, bx - uy * k, by - ux * k, fill=ink, outline="", tags=TAG)
        return d


class Bar:
    """One window's strip of hints, along its bottom edge."""

    def __init__(self, top, colors):
        self.top, self.colors = top, colors
        scale = max(1.0, top.winfo_fpixels("1i") / 96)
        self.scale = scale
        self.canvas = tk.Canvas(top, height=round(36 * scale), highlightthickness=0, bd=0)
        self.canvas.pad_bar = True
        self.glyphs = Glyphs(self.canvas, scale)
        try:
            self.font = tkfont.nametofont("SunValleyBodyFont")
        except tk.TclError:
            self.font = tkfont.nametofont("TkDefaultFont")
        self.shown, self.drawn = [], None

    def show(self, hints, style):
        c = self.colors()
        bg = ttk.Style().lookup("TFrame", "background") or c["field"]
        dark = c["fg"].lower() in ("#fafafa", "#ffffff")
        chip, ink = ("#4a4a50", "#f4f4f4") if dark else ("#34343a", "#f4f4f4")
        key = (tuple(hints), style, bg, c["fg"], c["border"])
        if not self.canvas.winfo_manager():
            self._attach()
        self.shown = list(hints)
        if key == self.drawn:
            return
        self.drawn = key
        cv, s = self.canvas, self.scale
        cv.delete(TAG)
        cv.configure(bg=bg)
        cy = round(36 * s) / 2 + 1
        cv.create_line(0, 0, 10000, 0, fill=c["border"], tags=TAG)
        x = round(16 * s)
        for button, label in hints:
            x += self.glyphs.draw(button, x, cy, style, chip, ink) + round(7 * s)
            cv.create_text(x, cy, text=label, anchor="w", fill=c["fg"], font=self.font, tags=TAG)
            x += self.font.measure(label) + round(20 * s)

    def _attach(self):
        """Below everything else in the window, without disturbing how the window lays itself out."""
        top, cv = self.top, self.canvas
        if top.grid_slaves():  # can't pack next to grid: lie over the bottom edge instead
            cv.place(relx=0, rely=1, relwidth=1, anchor="sw")
            tk.Misc.lift(cv)  # (Canvas.lift raises items)
            return
        slaves = [w for w in top.pack_slaves() if w is not cv]
        if slaves:
            cv.pack(side="bottom", fill="x", before=slaves[0])
        else:
            cv.pack(side="bottom", fill="x")

    def hide(self):
        manager = self.canvas.winfo_manager()
        if manager == "pack":
            self.canvas.pack_forget()
        elif manager == "place":
            self.canvas.place_forget()
        self.shown = []


class Hints:
    """Keeps one bar up to date: the one in the window with the keyboard, while the pad is in use."""

    def __init__(self, root, colors):
        self.root, self.colors = root, colors
        self.bars = {}  # toplevel path -> Bar

    def update(self, active, path, style):
        """active: the pad was the last thing used; path: the widget with the keyboard ('' when none)."""
        if not active:
            self.hide()
            return
        if not path:
            return  # another app has the keyboard: leave things as they are
        hints = []
        try:
            top = str(self.root.tk.call("winfo", "toplevel", path))
        except tk.TclError:
            top = None
        if top and _widget(self.root, top) is not None:
            hints = hints_for(self.root, path)
        for t, bar in list(self.bars.items()):
            if not bar.top.winfo_exists():
                del self.bars[t]
            elif t != top or not hints:
                bar.hide()
        if hints:
            bar = self.bars.get(top)
            if bar is None:
                bar = self.bars[top] = Bar(_widget(self.root, top), self.colors)
            bar.show(hints, style)

    def shown(self, top=None):
        """What the bar in top (default: any) shows now: [(button, label)]."""
        for t, bar in self.bars.items():
            if (top is None or t == str(top)) and bar.shown:
                return list(bar.shown)
        return []

    def hide(self):
        for bar in self.bars.values():
            if bar.top.winfo_exists():
                bar.hide()
