"""Keyboard work in the Keeping / Moving lists: flip games without losing your place, undo, mark several and apply
them together, jump by typing, and select ranges.

    ↑ ↓ Home End PgUp PgDn   move the cursor          Shift+↑ ↓   extend the selection     Ctrl+A   select all
    → or Delete (Keeping)    move the selected games  ← or Insert / Delete (Moving)   keep them
    Space                    mark / unmark, then go to the next game: marked games flip together on Enter or
                             when you leave the list (Tab, a click elsewhere)
    Enter                    flip the marked games (or, with none marked, the selected ones)
    Tab / Shift+Tab          the other list, back where you were in it
    Ctrl+Z or Backspace      undo the last flip       letters      jump to the first game starting with them

The app provides keep_tv / move_tv, manual ({key: True to move, False to keep}), refresh(), status (a label) and
colors; flip(tv, to_move) here is what double-click and every key use."""
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

TYPE_PAUSE = 1.0  # seconds: typing after a longer gap starts a new search
UNDO_DEPTH = 200

HELP = [
    ("↑ ↓  Home  End  PgUp  PgDn", "Move through the list"),
    ("Shift+↑ ↓   Ctrl+A", "Select a range / every game shown"),
    ("→ or Delete", "Keeping: move the selected games now"),
    ("← or Insert", "Moving: keep the selected games now"),
    ("Space", "Mark or unmark a game and go to the next; marked games flip together on Enter or when you leave "
              "the list"),
    ("Enter", "Flip the marked games (or the selected ones)"),
    ("Tab  Shift+Tab", "Switch between Keeping and Moving, back where you were"),
    ("Ctrl+Z  Backspace", "Undo the last flip"),
    ("Letters", "Jump to the first game whose name starts with what you type"),
    ("Ctrl+R", "Review the list one game at a time"),
    ("Double-click", "Flip a game"),
]


class PaneKeys:
    def __init__(self, app):
        self.app = app
        self.undo_stack = []  # [(changes {key: previous manual value or None}, list name, label)]
        self.typed, self.typed_at = "", 0.0
        for tv in (app.keep_tv, app.move_tv):
            tv.marked = set()
            tv.last = 0        # cursor row, for Tab coming back
            tv.anchor_item = None
            self._bind(tv)

    # ---------- setup ----------
    def _bind(self, tv):
        keep = tv is self.app.keep_tv
        to = keep  # what flipping from this list means: keeping list -> move

        def b(seq, fn):
            tv.bind(seq, lambda e: (fn(e), "break")[1])
        b("<Right>" if keep else "<Left>", lambda e: self.flip(tv, to))
        b("<Left>" if keep else "<Right>", lambda e: None)  # no tree to open or close here
        b("<Delete>", lambda e: self.flip(tv, to))
        if not keep:
            b("<Insert>", lambda e: self.flip(tv, to))
        b("<space>", lambda e: self.toggle_mark(tv))
        b("<Return>", lambda e: self.apply(tv) if tv.marked else self.flip(tv, to))
        b("<KP_Enter>", lambda e: self.apply(tv) if tv.marked else self.flip(tv, to))
        b("<Tab>", lambda e: self.switch(tv))
        b("<Shift-Tab>", lambda e: self.switch(tv))
        b("<ISO_Left_Tab>", lambda e: self.switch(tv))
        b("<Shift-Up>", lambda e: self.extend(tv, -1))
        b("<Shift-Down>", lambda e: self.extend(tv, 1))
        b("<Control-a>", lambda e: self.select_all(tv))
        b("<Home>", lambda e: self.place(tv, 0))
        b("<End>", lambda e: self.place(tv, len(tv.get_children()) - 1))
        b("<Prior>", lambda e: self.page(tv, -1))
        b("<Next>", lambda e: self.page(tv, 1))
        b("<BackSpace>", lambda e: self.undo())
        tv.bind("<Up>", lambda e: self._step(tv, -1))
        tv.bind("<Down>", lambda e: self._step(tv, 1))
        tv.bind("<Key>", lambda e: self.type_jump(tv, e), add="+")
        tv.bind("<FocusOut>", lambda e: self.apply(tv, refocus=False) if tv.marked else None, add="+")
        tv.bind("<ButtonRelease-1>", lambda e: self._remember(tv), add="+")

    def style(self, colors):
        """Marked rows: struck through, in the colour of the list they're going to."""
        name = ttk.Style().lookup("Treeview", "font") or "TkDefaultFont"
        try:
            base = tkfont.nametofont(name)
        except tk.TclError:  # a font description, not a named font
            base = tkfont.Font(font=name)
        self.strike = tkfont.Font(**{**base.actual(), "overstrike": 1})
        self.app.keep_tv.tag_configure("marked", font=self.strike, foreground=colors["move"])
        self.app.move_tv.tag_configure("marked", font=self.strike, foreground=colors["keep"])

    # ---------- cursor ----------
    def _rows(self, tv):
        return tv.get_children()

    def cursor(self, tv):
        """Index of the cursor row (the focus item, else the first selected), or None."""
        rows = self._rows(tv)
        item = tv.focus() if tv.focus() in rows else next((s for s in tv.selection() if tv.exists(s)), "")
        return rows.index(item) if item in rows else None

    def place(self, tv, index, select=True):
        """Put the cursor (and the selection) on row index, clamped, and keep the keyboard in this list."""
        rows = self._rows(tv)
        tv.focus_set()
        if not rows:
            return None
        index = max(0, min(index, len(rows) - 1))
        item = rows[index]
        if select:
            tv.selection_set(item)
            tv.anchor_item = item
        tv.focus(item)
        tv.see(item)
        tv.last = index
        return item

    def _remember(self, tv):
        i = self.cursor(tv)
        if i is not None:
            tv.last = i
            tv.anchor_item = tv.focus() or tv.anchor_item

    def _step(self, tv, step):
        """Plain ↑ ↓ (Tk's own would do, but this keeps the anchor and position in step)."""
        i = self.cursor(tv)
        self.place(tv, 0 if i is None else i + step)
        return "break"

    def page(self, tv, direction):
        rows = self._rows(tv)
        if not rows:
            return
        row_h = max(1, int(ttk.Style().lookup("Treeview", "rowheight") or 24))
        per_page = max(1, tv.winfo_height() // row_h - 2)
        i = self.cursor(tv) or 0
        self.place(tv, i + direction * per_page)

    def extend(self, tv, step):
        rows = self._rows(tv)
        if not rows:
            return
        i = self.cursor(tv)
        if i is None:
            self.place(tv, 0)
            return
        anchor = tv.anchor_item if tv.anchor_item in rows else rows[i]
        j = max(0, min(i + step, len(rows) - 1))
        a, z = sorted((rows.index(anchor), j))
        tv.selection_set(rows[a:z + 1])
        tv.anchor_item = anchor
        tv.focus(rows[j])
        tv.see(rows[j])
        tv.last = j

    def select_all(self, tv):
        rows = self._rows(tv)
        if rows:
            tv.selection_set(rows)
            if tv.focus() not in rows:
                tv.focus(rows[0])

    def switch(self, tv):
        """Tab: the other list, at the row you were last on there."""
        if tv.marked:
            self.apply(tv, refocus=False)
        self._remember(tv)
        other = self.app.move_tv if tv is self.app.keep_tv else self.app.keep_tv
        if other.get_children():
            self.place(other, other.last)
        else:
            other.focus_set()

    def type_jump(self, tv, e):
        if not e.char or not e.char.isprintable() or e.char == " " or e.state & 0x4 or e.state & 0x8:
            return None  # not a letter (or a Ctrl / Alt shortcut): leave it to the other bindings
        now = time.monotonic()
        self.typed = (self.typed if now - self.typed_at < TYPE_PAUSE else "") + e.char.lower()
        self.typed_at = now
        rows = self._rows(tv)
        for want in (self.typed, self.typed[-1:]):  # still nothing: start again from the last letter
            for strip in (False, True):
                for i, item in enumerate(rows):
                    text = tv.item(item, "text").lower()
                    if strip:
                        text = text.split(" - ", 1)[-1] if text[:1].isdigit() else text
                        text = text[4:] if text.startswith("the ") else text
                    if text.startswith(want):
                        self.typed = want
                        self.place(tv, i)
                        return "break"
        return "break"

    # ---------- flipping ----------
    def _record(self, keys, where, label):
        changes = {k: self.app.manual.get(k) for k in keys}
        self.undo_stack.append((changes, where, label))
        del self.undo_stack[:-UNDO_DEPTH]

    def flip(self, tv, to_move, keys=None, refocus=True):
        """Flip keys (default: the selection) out of tv and put the cursor where they were."""
        keys = [k for k in (keys if keys is not None else tv.selection()) if tv.exists(k)]
        if not keys:
            return []
        rows = self._rows(tv)
        index = min(rows.index(k) for k in keys)
        names = [tv.item(k, "text") for k in keys]
        self._record(keys, "move" if to_move else "keep", names[0] if len(keys) == 1 else f"{len(keys)} games")
        for k in keys:
            self.app.manual[k] = to_move
            tv.marked.discard(k)
        self.app.refresh()
        if refocus:
            self.place(tv, index)
        else:
            tv.last = index
        what = names[0] if len(keys) == 1 else f"{len(keys)} games"
        self.say(f"{'Moving' if to_move else 'Keeping'} {what}  ·  Ctrl+Z undoes")
        return keys

    def toggle_mark(self, tv):
        sel = [s for s in tv.selection() if tv.exists(s)]
        if not sel:
            i = self.cursor(tv)
            if i is None:
                return
            sel = [self._rows(tv)[i]]
        if all(k in tv.marked for k in sel):
            tv.marked.difference_update(sel)
        else:
            tv.marked.update(sel)
        for k in sel:
            self.tag(tv, k)
        rows = self._rows(tv)
        last = max(rows.index(k) for k in sel)
        if last + 1 < len(rows):
            self.place(tv, last + 1)
        n = len(tv.marked)
        dest = "Moving" if tv is self.app.keep_tv else "Keeping"
        self.say(f"{n} marked for {dest}  ·  Enter (or leaving the list) flips them  ·  Space unmarks" if n else
                 "Nothing marked")

    def tag(self, tv, key):
        tags = [t for t in tv.item(key, "tags") if t != "marked"]
        if key in tv.marked:
            tags.append("marked")
        tv.item(key, tags=tags)

    def after_render(self):
        """The lists were rebuilt: marks stay on games still in their list."""
        for tv in (self.app.keep_tv, self.app.move_tv):
            tv.marked = {k for k in tv.marked if tv.exists(k)}
            for k in tv.marked:
                self.tag(tv, k)

    def apply(self, tv, refocus=True):
        if not tv.marked:
            return []
        return self.flip(tv, tv is self.app.keep_tv, sorted(tv.marked, key=self._rows(tv).index), refocus)

    def undo(self):
        if not self.undo_stack:
            self.say("Nothing to undo")
            return []
        changes, where, label = self.undo_stack.pop()
        for k, old in changes.items():
            if old is None:
                self.app.manual.pop(k, None)
            else:
                self.app.manual[k] = old
        self.app.refresh()
        back = self.app.keep_tv if where == "move" else self.app.move_tv  # the list they were flipped out of
        keys = [k for k in changes if back.exists(k)]
        if keys:
            back.selection_set(keys)
            self.place(back, self._rows(back).index(keys[0]), select=False)
            back.selection_set(keys)
        self.say(f"Undid: {label}")
        return list(changes)

    def say(self, text):
        self.app.status.config(text=text)
