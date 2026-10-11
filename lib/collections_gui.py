"""Library → Save as an ES-DE collection: put the Keeping list, the Moving list or the selected games into an ES-DE
custom collection (lib/esde_collections.py), new or existing."""
import tkinter as tk
from tkinter import ttk, messagebox

import esde_collections as ec
import scraper

TITLE = "Save as an ES-DE collection"


def open_window(app, scope=None):
    w = getattr(app, "collections_window", None)
    if w and w.win.winfo_exists():
        w.win.destroy()
    if not app.units:
        messagebox.showinfo(TITLE, "There are no games in this system to put in a collection.")
        return None
    w = app.collections_window = CollectionWindow(app, scope)
    return w


class CollectionWindow:
    def __init__(self, app, scope=None):
        self.app = app
        self.home = ec.home(app.cfg["roms_root"])
        self.existing = ec.names(self.home)
        win = self.win = tk.Toplevel(app.root)
        win.title(TITLE)
        win.transient(app.root)
        win.resizable(False, False)
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        win.bind("<Escape>", lambda e: win.destroy())
        body = ttk.Frame(win, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=TITLE, style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text="ES-DE shows a custom collection as its own entry next to the systems, with the games "
                             "from any system you put in it.", style="Muted.TLabel", wraplength=480,
                  justify="left").pack(anchor="w", pady=(2, 12))

        sel = self.selected()
        choices = [("keep", f"The Keeping list ({len(app.kept):,} games)", app.kept),
                   ("move", f"The Moving list ({len(app.to_move):,} games)", app.to_move),
                   ("selected", f"The selected games ({len(sel):,})", sel)]
        self.lists = {k: keys for k, _, keys in choices}
        self.scope = tk.StringVar(value=scope or ("selected" if len(sel) > 1 else "keep"))
        ttk.Label(body, text="Which games").pack(anchor="w")
        for k, text, keys in choices:
            rb = ttk.Radiobutton(body, text=text, value=k, variable=self.scope, command=self._update)
            rb.pack(anchor="w", padx=(12, 0), pady=1)
            if not keys:
                rb.state(["disabled"])
        if not self.lists[self.scope.get()]:
            self.scope.set(next((k for k, _, keys in choices if keys), "keep"))

        ttk.Label(body, text="Collection").pack(anchor="w", pady=(12, 2))
        self.name = tk.StringVar(value=app.cfg.get("last_collection", ""))
        self.name_cb = ttk.Combobox(body, textvariable=self.name, values=list(self.existing), width=40)
        self.name_cb.pack(anchor="w", padx=(12, 0))
        self.name.trace_add("write", lambda *a: self._update())
        self.about = ttk.Label(body, style="Muted.TLabel")
        self.about.pack(anchor="w", padx=(12, 0), pady=(2, 0))
        self.mode = tk.StringVar(value="add")
        self.mode_row = ttk.Frame(body)
        self.mode_row.pack(anchor="w", padx=(12, 0), pady=(4, 0))
        ttk.Radiobutton(self.mode_row, text="Add to it", value="add", variable=self.mode).pack(side="left")
        ttk.Radiobutton(self.mode_row, text="Replace what's in it", value="replace",
                        variable=self.mode).pack(side="left", padx=(12, 0))
        self.show_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(body, text="Show it in ES-DE", variable=self.show_var).pack(anchor="w", pady=(12, 0))

        foot = ttk.Frame(body, padding=(0, 16, 0, 0))
        foot.pack(fill="x")
        ttk.Button(foot, text="Cancel", command=win.destroy).pack(side="right")
        self.save_btn = ttk.Button(foot, text="Save", style="Accent.TButton", command=self.save)
        self.save_btn.pack(side="right", padx=(0, 6))
        win.bind("<Return>", lambda e: self.save())
        self._update()
        self.name_cb.focus_set()

    def selected(self):
        out = []
        for tv in (self.app.keep_tv, self.app.move_tv):
            out += [k for k in tv.selection() if k in self.app.units and k not in out]
        return out

    def _update(self):
        name = ec.clean_name(self.name.get())
        if not name:
            self.about.config(text="Type a new name, or pick one of yours.")
        elif name in self.existing:
            n = len(ec.games(self.existing[name]))
            self.about.config(text=f"Already has {n:,} game{'s' if n != 1 else ''}.")
        else:
            self.about.config(text="A new collection.")
        for w in self.mode_row.winfo_children():
            w.state(["!disabled"] if name in self.existing else ["disabled"])
        keys = self.lists.get(self.scope.get()) or []
        self.save_btn.state(["!disabled"] if name and keys else ["disabled"])

    def save(self):
        name = ec.clean_name(self.name.get())
        keys = self.lists.get(self.scope.get()) or []
        if not name or not keys:
            return
        files = [scraper.primary_file(self.app.units[k]["paths"]) for k in keys if k in self.app.units]
        replace = self.mode.get() == "replace" and name in self.existing
        try:
            added = ec.save(self.home, name, files, self.app.cfg["roms_root"], replace=replace)
        except (OSError, ValueError) as e:
            messagebox.showerror(TITLE, f"Couldn't save the collection: {e}", parent=self.win)
            return
        note = ""
        if self.show_var.get():
            if scraper.es_de_running():
                note = " Close ES-DE and save again to have it shown, or turn it on in ES-DE's Game collection " \
                       "settings."
            else:
                try:
                    ec.enable(self.home, name)
                except OSError as e:
                    note = f" (Couldn't turn it on in ES-DE: {e})"
        self.app.cfg["last_collection"] = name
        self.app.save_cfg()
        self.win.destroy()
        what = "Replaced the games in" if replace else "Made"
        if replace or name not in self.existing:
            self.app.toast(f"{what} the ES-DE collection “{name}” ({len(files):,} games).{note}")
        else:
            self.app.toast(f"Added {added:,} game{'s' if added != 1 else ''} to the ES-DE collection “{name}”."
                           + ("" if added == len(files) else f" {len(files) - added:,} were in it already.") + note)
