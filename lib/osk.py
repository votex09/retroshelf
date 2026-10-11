"""An on-screen keyboard for typing with a gamepad: A in a text box opens it under the box.

    D-pad  move    A  type the key    Y  delete    LB  capitals    X  done    B  close

Typed letters go straight into the box (so a search box filters as you type). Real key presses work too."""
import tkinter as tk
from tkinter import ttk

ROWS = ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm-.!"]
SPECIAL = [("⇧", "shift"), ("Space", " "), ("⌫", "back"), ("Clear", "clear"), ("Done", "done")]
TITLE = "Keyboard"


def open_keyboard(root, entry):
    """Show the keyboard for an Entry (one at a time)."""
    old = getattr(root, "_osk", None)
    if old is not None and old.win.winfo_exists():
        old.close()
    root._osk = Keyboard(root, entry)
    return root._osk


class Keyboard:
    def __init__(self, root, entry):
        self.root, self.entry = root, entry
        self.caps = False
        self.row, self.col = 1, 0
        win = self.win = tk.Toplevel(root)
        win.title(TITLE)
        win.transient(entry.winfo_toplevel())
        win.resizable(False, False)
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        win._centered = True  # placed under the box, not in the middle (see App._center_dialog)
        body = ttk.Frame(win, padding=10)
        body.pack()
        self.cells = []  # [[(button, value)]]
        for r, keys in enumerate(ROWS):
            line = ttk.Frame(body)
            line.pack(pady=1)
            row = []
            for ch in keys:
                b = ttk.Button(line, text=ch, width=3, takefocus=False, command=lambda ch=ch: self.type(ch))
                b.pack(side="left", padx=1)
                row.append((b, ch))
            self.cells.append(row)
        line = ttk.Frame(body)
        line.pack(pady=(4, 0))
        row = []
        for text, value in SPECIAL:
            b = ttk.Button(line, text=text, width=10 if value == " " else 6, takefocus=False,
                           command=lambda v=value: self.press(v))
            b.pack(side="left", padx=1)
            row.append((b, value))
        self.cells.append(row)
        for seq, fn in (("<Up>", lambda: self.move(-1, 0)), ("<Down>", lambda: self.move(1, 0)),
                        ("<Left>", lambda: self.move(0, -1)), ("<Right>", lambda: self.move(0, 1)),
                        ("<space>", self.activate), ("<Return>", self.close), ("<KP_Enter>", self.close),
                        ("<Escape>", self.close), ("<Control-z>", lambda: self.press("back")),
                        ("<BackSpace>", lambda: self.press("back")),
                        ("<ISO_Left_Tab>", lambda: self.press("shift")), ("<Shift-Tab>", lambda: self.press("shift"))):
            win.bind(seq, lambda e, fn=fn: (fn(), "break")[1])
        win.bind("<Key>", self._typed)
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.pad_hints = lambda: [("dpad:udlr", "Move"), ("a", "Type"), ("y", "Delete"), ("lb", "Capitals"),
                                 ("x", "Done")]
        self._place()
        self._show()
        win.focus_force()

    def _place(self):
        self.win.update_idletasks()
        e = self.entry
        x, y = e.winfo_rootx(), e.winfo_rooty() + e.winfo_height() + 4
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        x = max(0, min(x, e.winfo_screenwidth() - w))
        if y + h > e.winfo_screenheight():
            y = max(0, e.winfo_rooty() - h - 4)
        self.win.geometry(f"+{x}+{y}")

    def _show(self):
        for r, row in enumerate(self.cells):
            for c, (b, value) in enumerate(row):
                if len(value) == 1 and value.isalpha():
                    b.config(text=value.upper() if self.caps else value)
                b.config(style="Accent.TButton" if (r, c) == (self.row, self.col) else "TButton")
        shift = self.cells[-1][0][0]
        shift.config(text="⇧ ON" if self.caps else "⇧")

    def move(self, dr, dc):
        r = (self.row + dr) % len(self.cells)
        c = self.col
        if dr:  # keep roughly the same place across rows of different lengths
            frac = (self.col + 0.5) / len(self.cells[self.row])
            c = min(len(self.cells[r]) - 1, int(frac * len(self.cells[r])))
        else:
            c = (c + dc) % len(self.cells[r])
        self.row, self.col = r, c
        self._show()

    def activate(self):
        _, value = self.cells[self.row][self.col]
        if len(value) == 1:
            self.type(value)
        else:
            self.press(value)

    def type(self, ch):
        if ch.isalpha() and self.caps:
            ch = ch.upper()
        try:
            if self.entry.selection_present():
                self.entry.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        self.entry.insert("insert", ch)
        self.entry.xview_moveto(1)

    def press(self, value):
        if value == " ":
            self.type(" ")
        elif value == "back":
            i = self.entry.index("insert")
            if i:
                self.entry.delete(i - 1)
        elif value == "clear":
            self.entry.delete(0, "end")
        elif value == "shift":
            self.caps = not self.caps
            self._show()
        elif value == "done":
            self.close()

    def _typed(self, e):
        if e.char and e.char.isprintable() and not e.state & 0x4:
            self.entry.insert("insert", e.char)
            return "break"
        return None

    def close(self):
        if self.win.winfo_exists():
            self.win.destroy()
        try:
            self.entry.focus_set()
        except tk.TclError:
            pass
