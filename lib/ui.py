"""Small UI helpers: star ratings, tooltips, toast notifications and centred dialogs."""
import tkinter as tk
from tkinter import ttk


def stars(rating):
    """3.7 -> '★★★★☆' (rounded to whole stars; LaunchBox ratings are out of 5)."""
    full = max(0, min(5, round(rating)))
    return "★" * full + "☆" * (5 - full)


def center(win, parent):
    """Place a dialog in the middle of its parent window once it knows its size."""
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    geo = win.geometry().split("+")[0]
    if "x" in geo and geo != "1x1":
        w, h = (int(v) for v in geo.split("x"))
    x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - h) // 3
    win.geometry(f"+{max(0, x)}+{max(0, y)}")


class Tooltip:
    """Shows text after hovering a widget for a moment. text may be a callable, evaluated on show."""

    def __init__(self, widget, text, delay=450):
        self.widget, self.text, self.delay = widget, text, delay
        self.tip = self.after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _=None):
        self._hide()
        self.after_id = self.widget.after(self.delay, self._show)

    def _show(self):
        text = self.text() if callable(self.text) else self.text
        if not text:
            return
        st = ttk.Style()
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        tk.Label(self.tip, text=text, justify="left", wraplength=360, padx=10, pady=6,
                 bg=st.lookup("TEntry", "fieldbackground") or "#333", fg=st.lookup("TLabel", "foreground") or "#eee",
                 highlightthickness=1, highlightbackground="#777", font="SunValleyCaptionFont").pack()
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip.wm_geometry(f"+{x}+{y}")

    def _hide(self, _=None):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


class Toaster:
    """Short-lived notifications sliding up in the bottom-right corner of a window. Click one to dismiss it."""

    def __init__(self, root, colors):
        self.root, self.colors, self.shown = root, colors, []

    def show(self, text, kind="ok", ms=4200):
        c = self.colors()
        accent = {"ok": c["keep"], "warn": c["manual"], "info": c["accent"]}.get(kind, c["accent"])
        icon = {"ok": "✓", "warn": "!", "info": "i"}.get(kind, "i")
        box = tk.Frame(self.root, bg=c["field"], highlightthickness=1, highlightbackground=c["border"])
        tk.Frame(box, bg=accent, width=4).pack(side="left", fill="y")
        tk.Label(box, text=icon, bg=c["field"], fg=accent, font="SunValleyBodyStrongFont", padx=10).pack(side="left")
        tk.Label(box, text=text, bg=c["field"], fg=c["fg"], justify="left", wraplength=380,
                 font="SunValleyBodyFont", pady=10).pack(side="left", padx=(0, 14))
        for w in [box] + box.winfo_children():
            w.bind("<Button-1>", lambda e, b=box: self._close(b))
        self.shown.append(box)
        self._layout(animate=box)
        self.root.after(ms, lambda: self._close(box))

    def _layout(self, animate=None):
        """Stack toasts upwards from the bottom-right corner; a new one slides up into place."""
        self.root.update_idletasks()
        bottom = -64
        for box in reversed(self.shown):
            h = box.winfo_reqheight()
            target = bottom
            if box is animate:
                self._slide(box, target + 40, target)
            else:
                box.place(relx=1.0, rely=1.0, x=-20, y=target, anchor="se")
            bottom = target - h - 10

    def _slide(self, box, y, target, step=0):
        if not box.winfo_exists():
            return
        box.place(relx=1.0, rely=1.0, x=-20, y=y, anchor="se")
        box.lift()
        if y > target:
            self.root.after(12, lambda: self._slide(box, max(target, y - 8), target, step + 1))

    def _close(self, box):
        if box in self.shown:
            self.shown.remove(box)
            box.destroy()
            self._layout()
