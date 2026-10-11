"""Review: go through a list one game at a time, with its artwork and details, and decide each one with a key.

    K (or Space)  keep     M (or Enter)  move     S or →  skip     ←  back     Backspace / Ctrl+Z  undo     Esc  close

Decisions are hand flips (the orange ones), recorded in the same undo history as the lists' keys
(lib/listkeys.py). The game list is the one it was opened from, in the order it was shown."""
import tkinter as tk
from tkinter import ttk

import details
import motion

TITLE = "Review"


def open_window(app, keys, start=0):
    w = getattr(app, "review_window", None)
    if w and w.win.winfo_exists():
        w.win.destroy()
    if not keys:
        return None
    app.review_window = ReviewWindow(app, list(keys), start)
    return app.review_window


class ReviewWindow:
    def __init__(self, app, keys, start):
        self.app, self.keys = app, keys
        self.i = max(0, min(start, len(keys) - 1))
        self.decided = {}  # key -> True (move) / False (keep), this session
        win = self.win = tk.Toplevel(app.root)
        win.title(TITLE)
        win.transient(app.root)
        scale = max(1.0, app.root.winfo_fpixels("1i") / 96)
        win.geometry(f"{min(round(1000 * scale), app.root.winfo_screenwidth())}x"
                     f"{min(round(720 * scale), app.root.winfo_screenheight() - 80)}")
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        body = ttk.Frame(win, padding=20)
        body.pack(fill="both", expand=True)

        top = ttk.Frame(body)
        top.pack(fill="x")
        self.count = ttk.Label(top, style="Muted.TLabel")
        self.count.pack(side="right")
        self.title = ttk.Label(top, style="Title.TLabel", wraplength=760, justify="left")
        self.title.pack(side="left", anchor="w")
        self.state = ttk.Label(body, style="Section.TLabel")
        self.state.pack(anchor="w", pady=(4, 6))
        self.bar = ttk.Progressbar(body, mode="determinate", maximum=1000)  # glides along as you go
        self.bar.pack(fill="x", pady=(0, 10))

        foot = ttk.Frame(body)
        foot.pack(side="bottom", fill="x", pady=(12, 0))
        self.buttons = {}
        for key, text, cmd, style in (("k", "Keep  (K)", lambda: self.decide(False), "TButton"),
                                      ("m", "Move  (M)", lambda: self.decide(True), "Accent.TButton"),
                                      ("s", "Skip  (S / →)", lambda: self.go(1), "TButton")):
            b = ttk.Button(foot, text=text, command=cmd, style=style, takefocus=False)
            b.pack(side="left", padx=(0, 6))
            self.buttons[key] = b
        ttk.Button(foot, text="Close  (Esc)", command=self.close, takefocus=False).pack(side="right")
        ttk.Button(foot, text="Undo  (Backspace)", command=self.undo, takefocus=False).pack(side="right", padx=(0, 6))
        ttk.Button(foot, text="‹ Back  (←)", command=lambda: self.go(-1), takefocus=False).pack(side="right", padx=(0, 6))
        self.panel = details.DetailsPanel(body, app.field_style, padding=0)
        self.panel.pack(fill="both", expand=True)
        app.detail_panels.append(self.panel)

        for seq, fn in (("<k>", lambda: self.decide(False)), ("<K>", lambda: self.decide(False)),
                        ("<m>", lambda: self.decide(True)), ("<M>", lambda: self.decide(True)),
                        ("<s>", lambda: self.go(1)), ("<S>", lambda: self.go(1)), ("<Right>", lambda: self.go(1)),
                        ("<Left>", lambda: self.go(-1)), ("<BackSpace>", self.undo), ("<Control-z>", self.undo),
                        ("<Escape>", self.close),
                        # a gamepad's A (Space) keeps and X (Enter) moves; see lib/gamepad.py
                        ("<space>", lambda: self.decide(False)), ("<Return>", lambda: self.decide(True))):
            win.bind(seq, lambda e, fn=fn: (fn(), "break")[1])
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.pad_hints = self.pad_hints
        self.show()
        win.focus_force()

    def pad_hints(self):
        """What a gamepad's buttons do here right now (lib/padhints.py); B closes, added by the window's Escape."""
        out = []
        if self.i < len(self.keys):
            out += [("a", "Keep"), ("x", "Move"), ("dpad:lr", "Back / Skip")]
        elif self.keys:
            out.append(("dpad:l", "Back"))
        if self.app.keys.undo_stack:
            out.append(("y", "Undo"))
        return out

    def where(self, key):
        """("moving" | "keeping", why) for a game as the main window has it now."""
        moving = key in set(self.app.to_move)
        return ("moving" if moving else "keeping"), self.app.why.get(key, "")

    def show(self):
        if self.i >= len(self.keys):
            self.done()
            return
        key = self.keys[self.i]
        if key not in self.app.units:  # gone (rescanned, moved out): skip it
            self.keys.pop(self.i)
            self.show()
            return
        u = self.app.units[key]
        self.title.config(text=self.app._label(key))
        self.count.config(text=f"{self.i + 1:,} of {len(self.keys):,}")
        motion.progress(self.bar, "step", 1000 * (self.i + 1) / len(self.keys), ms=260)
        state, why = self.where(key)
        c = self.app.colors
        self.state.config(text=("●  Moving" if state == "moving" else "●  Keeping") + (f"  ·  {why}" if why else ""),
                          foreground=c["move"] if state == "moving" else c["keep"])
        self.panel.show(self.app.game_info(self.app.system, key, u["paths"], u["size"], self.app.ratings.get(key),
                                           self.app.lb_ids.get(key), self.app.platform))
        for b in self.buttons.values():
            b.state(["!disabled"])

    def decide(self, to_move):
        if self.i >= len(self.keys):
            return
        key = self.keys[self.i]
        state, _ = self.where(key)
        if (state == "moving") != to_move:
            src = self.app.keep_tv if state == "keeping" else self.app.move_tv
            if not src.exists(key):  # hidden by the list's search box: flip it all the same
                self.app.keys._record([key], "move" if to_move else "keep", self.app._label(key))
                self.app.manual[key] = to_move
                self.app.refresh()
            else:
                self.app.keys.flip(src, to_move, [key], refocus=False)
        self.decided[key] = to_move
        self.go(1)

    def go(self, step):
        self.i = max(0, min(self.i + step, len(self.keys)))
        self.show()

    def undo(self):
        keys = self.app.keys.undo()
        for k in keys:
            self.decided.pop(k, None)
        if keys and keys[0] in self.keys:
            self.i = self.keys.index(keys[0])
        self.show()
        self.win.focus_force()

    def done(self):
        moved = sum(1 for v in self.decided.values() if v)
        kept = len(self.decided) - moved
        self.title.config(text="That's the whole list")
        self.count.config(text=f"{len(self.keys):,} of {len(self.keys):,}")
        motion.progress(self.bar, "step", 1000, ms=260)
        self.state.config(text=f"You marked {moved:,} to move and {kept:,} to keep. Nothing has moved yet: press "
                               "Move in the main window when you're ready.", foreground=self.app.colors["fg"])
        self.panel.clear("")
        for b in self.buttons.values():
            b.state(["disabled"])

    def close(self):
        if self.panel in self.app.detail_panels:
            self.app.detail_panels.remove(self.panel)
        self.app.review_window = None
        self.win.destroy()
        self.app.root.focus_force()
