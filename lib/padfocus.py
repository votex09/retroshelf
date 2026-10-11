"""A focus ring for gamepad use: while the pad is what's in use, an accent outline sits on whatever it moves — the
row under the cursor in a list, a button, a tick box, a key of the on-screen keyboard — and glides to the next one
as you move, the way a console menu does. Pressing A or X makes it pulse. It goes away with the mouse or keyboard.

Where the ring goes:
  - a widget (or one of its parents, up to its window) with a pad_focus() method names the widget to outline
    (the on-screen keyboard: the key under its cursor);
  - a Treeview: its cursor row, while that row is in view;
  - anything else: the widget with the keyboard itself."""
import tkinter as tk
from tkinter import ttk

import motion
from padhints import _ancestors, _widget

THICK = 3
GAP = 3         # px between a widget and its ring
GLIDE_MS = 120  # moving from one thing to the next
POP_MS = 180    # appearing: it closes in on its target from a little further out


class Ring:
    """Four thin frames in one window, placed as the sides of a rectangle above everything else there."""

    def __init__(self, top, color):
        self.top = top
        self.sides = [tk.Frame(top, bg=color, width=1, height=1, bd=0, highlightthickness=0, takefocus=0)
                      for _ in range(4)]
        for s in self.sides:
            s.pad_ring = True
        self.rect = None    # (x, y, w, h) on screen now, in the window's coordinates
        self.target = None
        self.color = color

    def draw(self, rect):
        x, y, w, h = (round(v) for v in rect)
        t = THICK
        for s, (sx, sy, sw, sh) in zip(self.sides, ((x, y, w, t), (x, y + h - t, w, t), (x, y, t, h),
                                                    (x + w - t, y, t, h))):
            s.place(in_=self.top, x=sx, y=sy, width=max(1, sw), height=max(1, sh))
            tk.Misc.lift(s)
        self.rect = (x, y, w, h)

    def move_to(self, rect):
        if rect == self.target and self.rect is not None:
            return
        self.target = rect
        if self.rect is None:  # appearing: close in from further out
            start, ms = (rect[0] - 10, rect[1] - 10, rect[2] + 20, rect[3] + 20), POP_MS
        else:
            start, ms = self.rect, GLIDE_MS
        motion.tween(self.sides[0], "ring", ms, lambda p: self.draw(
            tuple(a + (b - a) * p for a, b in zip(start, rect))))

    def pulse(self, accent, flash):
        """A press: the ring flashes bright, then settles back to the accent colour."""
        motion.tween(self.sides[1], "pulse", 260, lambda p: self.set_color(motion.mix(self.top, flash, accent, p)))

    def set_color(self, color):
        for s in self.sides:
            s.configure(bg=color)

    def hide(self):
        motion.cancel(self.sides[0], "ring")
        motion.cancel(self.sides[1], "pulse")
        for s in self.sides:
            s.place_forget()
        self.rect = self.target = None

    def exists(self):
        try:
            return bool(self.top.winfo_exists())
        except tk.TclError:
            return False


class FocusRing:
    """Keeps one ring up to date: in the window with the keyboard, while the pad is in use. Hook update() into
    lib/gamepad.py's watchers and pressed() into its presses."""

    def __init__(self, root, colors):
        self.root, self.colors = root, colors
        self.rings = {}  # toplevel path -> Ring

    def target_rect(self, path):
        """(window path, (x, y, w, h) in that window) to outline for the widget at path, or None."""
        w = _widget(self.root, path)
        if w is None:
            return None
        for p in _ancestors(str(path)):
            owner = _widget(self.root, p)
            fn = getattr(owner, "pad_focus", None) if owner is not None else None
            if callable(fn):
                w = fn() or w
                break
        try:
            if not w.winfo_ismapped():
                return None
            top = w.winfo_toplevel()
            ox, oy = w.winfo_rootx() - top.winfo_rootx(), w.winfo_rooty() - top.winfo_rooty()
            ww, wh = w.winfo_width(), w.winfo_height()
            if isinstance(w, ttk.Treeview):
                row = w.focus()
                box = w.bbox(row) if row and w.exists(row) else ""
                if box:  # the cursor row, inside the list
                    x, y, bw, bh = box
                    return str(top), (ox + x, oy + y, min(bw, ww - x), bh)
            return str(top), (ox - GAP, oy - GAP, ww + 2 * GAP, wh + 2 * GAP)
        except tk.TclError:
            return None

    def update(self, active, path, style=None):
        """The gamepad's watcher: active is whether the pad is what's in use; path has the keyboard."""
        for t, ring in list(self.rings.items()):
            if not ring.exists():
                del self.rings[t]
        if not active:
            self.hide()
            return
        if not path:
            return  # another app has the keyboard
        try:
            self.root.update_idletasks()  # a list scrolls to its cursor when idle: measure after that
        except tk.TclError:
            return
        found = self.target_rect(path)
        for t, ring in self.rings.items():
            if found is None or t != found[0]:
                ring.hide()
        if found is None:
            return
        top, rect = found
        ring = self.rings.get(top)
        accent = self.colors()["accent"]
        if ring is None:
            ring = self.rings[top] = Ring(_widget(self.root, top), accent)
        if ring.color != accent:
            ring.color = accent
            ring.set_color(accent)
        ring.move_to(rect)

    def pressed(self, button, target):
        """The gamepad's press callback: A and X (the doing buttons) make the ring pulse."""
        if button not in ("a", "x"):
            return
        try:
            top = str(target.winfo_toplevel()) if hasattr(target, "winfo_toplevel") else None
        except tk.TclError:
            top = None
        ring = self.rings.get(top)
        if ring is not None and ring.target is not None:
            c = self.colors()
            ring.pulse(c["accent"], c["fg"])

    def hide(self):
        for ring in self.rings.values():
            if ring.exists():
                ring.hide()

