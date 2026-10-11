"""The Import ROMs window: a bucket folder to throw games into (and Add files / Add a folder for games elsewhere).
Each game's system is worked out and shown before anything moves; the user can change it, then Import unpacks and
files everything (see lib/romimport.py)."""
import os, queue, shutil, threading
import tkinter as tk
from tkinter import ttk, messagebox

import romimport
import dialogs
import ui
from fsutil import open_folder

WATCH_MS = 2000
TITLE = "Import ROMs"


def inbox_dir(app):
    return romimport.inbox_dir(app.cfg)


def waiting(app):
    """How many things are in the import folder."""
    return romimport.waiting(inbox_dir(app))


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def open_window(app, paths=()):
    w = getattr(app, "import_window", None)
    if not (w and w.win.winfo_exists()):
        if not app.cfg.get("roms_root"):
            messagebox.showinfo(TITLE, "Pick your ROMs folder first (or set up RetroDECK / ES-DE from Tools).")
            return None
        w = app.import_window = ImportWindow(app)
    w.win.deiconify()
    w.win.lift()
    if paths:
        w.add(paths)
    return w


class ImportWindow:
    def __init__(self, app):
        self.app = app
        self.roms_root = app.cfg["roms_root"]
        self.inbox = inbox_dir(app)
        try:
            os.makedirs(self.inbox, exist_ok=True)
        except OSError:
            pass
        # a half-finished import (RetroShelf closed mid-way) left its staging folder behind
        shutil.rmtree(romimport.staging_dir(self.roms_root), ignore_errors=True)
        self.rows = {}         # tree id -> Row
        self.box = queue.Queue()
        self.busy = False      # importing
        self.scanning = 0
        self.cancel = threading.Event()
        self.snapshot, self.pending = None, False

        win = self.win = tk.Toplevel(app.root)
        win.title(TITLE)
        win.transient(app.root)
        win.geometry("1100x700")
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Escape>", lambda e: self.close())
        self._build()
        self.refresh_inbox()
        self._poll()
        self.watch_job = win.after(WATCH_MS, self._watch)

    # ---------- UI ----------
    def _build(self):
        body = ttk.Frame(self.win, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=TITLE, style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text="Put games in the import folder (or add them from anywhere): ROM files, disc images and "
                             "zip / 7z / rar archives, as they are. RetroShelf works out which system each one is "
                             "for, unpacks it, and files it into your ROMs folder in a form the emulators read. "
                             "Check the systems below, change any that are wrong, then press Import.",
                  style="Muted.TLabel", wraplength=1040, justify="left").pack(anchor="w", pady=(2, 10))

        inbox = ttk.Frame(body)
        inbox.pack(fill="x")
        ttk.Label(inbox, text="Import folder").pack(side="left")
        self.inbox_lbl = ttk.Label(inbox, text=self.inbox, style="Muted.TLabel")
        self.inbox_lbl.pack(side="left", padx=(8, 0))
        ttk.Button(inbox, text="Change…", command=self.change_inbox).pack(side="right")
        ttk.Button(inbox, text="Open folder", command=lambda: self._open(self.inbox)).pack(side="right", padx=(0, 6))
        ui.Tooltip(self.inbox_lbl, "Files put here are moved into your ROMs folder when imported. RetroShelf "
                                   "notices new ones while this window is open.")

        bar = ttk.Frame(body, padding=(0, 10, 0, 0))
        bar.pack(fill="x")
        ttk.Button(bar, text="Add files…", command=self.add_files).pack(side="left")
        ttk.Button(bar, text="Add a folder…", command=self.add_folder).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Remove from list", command=self.remove_selected).pack(side="left", padx=(6, 0))
        self.set_btn = ttk.Button(bar, text="Set", command=self.set_system)
        self.set_btn.pack(side="right")
        self.codes = self._systems()
        self.system_cb = ttk.Combobox(bar, state="readonly", width=34,
                                      values=["Detected"] + [f"{romimport.label(c)} ({c})" for c in self.codes])
        self.system_cb.current(0)
        self.system_cb.pack(side="right", padx=(0, 6))
        ttk.Label(bar, text="System for the selected games").pack(side="right", padx=(0, 8))

        foot = ttk.Frame(body, padding=(0, 10, 0, 0))
        foot.pack(side="bottom", fill="x")
        ttk.Button(foot, text="Close", command=self.close).pack(side="right")
        self.import_btn = ttk.Button(foot, text="Import", style="Accent.TButton", command=self.start)
        self.import_btn.pack(side="right", padx=(0, 6))
        self.delete_var = tk.BooleanVar(value=bool(self.app.cfg.get("import_delete_originals")))
        delete = ttk.Checkbutton(foot, text="Also delete the originals of games added from other folders",
                                 variable=self.delete_var, command=self._save_delete)
        delete.pack(side="left")
        ui.Tooltip(delete, "Games in the import folder are always moved out of it. Games added with Add files / "
                           "Add a folder are copied, leaving the originals, unless this is ticked.")
        prog = ttk.Frame(body)
        prog.pack(side="bottom", fill="x", pady=(8, 0))
        self.bar = ttk.Progressbar(prog, mode="determinate", maximum=1000, length=220)
        self.bar.pack(side="right", fill="x", padx=(12, 0))
        self.status = ttk.Label(prog, style="Muted.TLabel", anchor="w")
        self.status.pack(side="left", fill="x", expand=True)

        frame = ttk.Frame(body)
        frame.pack(fill="both", expand=True, pady=(10, 0))
        cols = ("system", "how", "size", "status")
        tv = self.tv = ttk.Treeview(frame, columns=cols, selectmode="extended")
        for col, text, width, stretch in (("#0", "Game", 300, True), ("system", "System", 190, False),
                                          ("how", "Found by", 140, False), ("size", "Size", 70, False),
                                          ("status", "Status", 260, True)):
            tv.heading(col, text=text, anchor="w")
            tv.column(col, width=width, stretch=stretch, anchor="e" if col == "size" else "w")
        sb = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        c = self.app.colors
        tv.tag_configure("odd", background=c["stripe"])
        tv.tag_configure("done", foreground=c["keep"])
        tv.tag_configure("problem", foreground=c["move"])
        tv.bind("<<TreeviewSelect>>", lambda e: self._sync_combo())
        self._update_buttons()

    def _systems(self):
        """Systems to offer: every known one plus any other folder in the ROMs folder."""
        return romimport.system_choices(self.roms_root)

    def _open(self, path):
        try:
            os.makedirs(path, exist_ok=True)
            open_folder(path)
        except OSError as e:
            messagebox.showerror(TITLE, f"Couldn't open {path}: {e}", parent=self.win)

    def _save_delete(self):
        self.app.cfg["import_delete_originals"] = self.delete_var.get()
        self.app.save_cfg()

    # ---------- the list ----------
    def _show(self, iid):
        v = romimport.shown(self.rows[iid])
        tags = [t for t in self.tv.item(iid, "tags") if t == "odd"] + ([v["tag"]] if v["tag"] else [])
        self.tv.item(iid, text=v["name"], values=(v["system"], v["how"], human(v["size"]) if v["size"] else "",
                                                  v["status"]), tags=tags)

    def _new(self, rows):
        """The rows that aren't in the list yet."""
        return romimport.new_rows(rows, self.rows.values())

    def add(self, paths, inbox=None, rows=None):
        new = self._new(romimport.collect(paths, inbox) if rows is None else rows)
        for r in new:
            r.status = "Checking …"
            iid = self.tv.insert("", "end", text=r.name, tags=("odd",) if len(self.rows) % 2 else ())
            self.rows[iid] = r
            self._show(iid)
        if new:
            self.scanning += 1
            threading.Thread(target=self._scan, args=([(iid, r) for iid, r in self.rows.items() if r in new],),
                             daemon=True).start()
        self._update_buttons()
        return new

    def _scan(self, items):
        for iid, r in items:
            romimport.scan_row(r)
            self.box.put(("row", iid))
        self.box.put(("scanned", None))

    def refresh_inbox(self):
        """Pick up what's in the import folder; forget rows whose files have gone."""
        for iid, r in list(self.rows.items()):
            if romimport.gone(r):
                self.tv.delete(iid)
                del self.rows[iid]
        if os.path.isdir(self.inbox):
            self.add(romimport.inbox_paths(self.inbox), self.inbox)

    def _watch(self):
        """New files in the import folder show up once they've finished copying (two looks the same)."""
        if not self.win.winfo_exists():
            return
        if not self.busy:
            state = romimport.inbox_state(self.inbox)
            if state != self.snapshot:
                self.pending = True
                self.snapshot = state
            elif self.pending:
                self.pending = False
                self.refresh_inbox()
        self.watch_job = self.win.after(WATCH_MS, self._watch)

    def add_files(self):
        paths = dialogs.ask_open_files(self.win, "Add games", os.path.expanduser("~"))
        if paths:
            self.add(list(paths), self.inbox)

    def add_folder(self):
        path = dialogs.ask_directory(self.win, "Add a folder of games", os.path.expanduser("~"))
        if not path:
            return
        rows = self._new(romimport.collect([path], self.inbox))
        if not rows:
            messagebox.showinfo(TITLE, f"There are no games or archives in\n{path}\n(or they're already in the "
                                       "list).", parent=self.win)
            return
        folders = len({os.path.dirname(r.path) for r in rows})
        where = f" in {folders} folders" if folders > 1 else ""
        if messagebox.askyesno(TITLE, f"Add {len(rows)} game{'s' if len(rows) != 1 else ''}{where} from\n\n{path}"
                                      f"{' (and the folders inside it)' if folders > 1 else ''}?\n\n"
                                      "They're copied: the originals stay where they are.", parent=self.win):
            self.add([], rows=rows)

    def remove_selected(self):
        if self.busy:
            return
        for iid in self.tv.selection():
            self.tv.delete(iid)
            self.rows.pop(iid, None)
        self._update_buttons()

    def change_inbox(self):
        path = dialogs.ask_directory(self.win, "Import folder", self.inbox)
        if not path:
            return
        path = os.path.normpath(path)
        problem = romimport.inbox_problem(path, self.roms_root)
        if problem:
            messagebox.showerror(TITLE, problem, parent=self.win)
            return
        self.inbox = path
        self.app.cfg["import_dir"] = path
        self.app.save_cfg()
        self.inbox_lbl.config(text=path)
        for iid, r in list(self.rows.items()):
            if r.inbox and not r.status.startswith("Imported"):
                self.tv.delete(iid)
                del self.rows[iid]
        self.snapshot = None
        self.refresh_inbox()

    def _sync_combo(self):
        sel = [self.rows[i] for i in self.tv.selection() if i in self.rows]
        picks = {r.override for r in sel}
        if len(picks) == 1 and None not in picks:
            self.system_cb.current(self.codes.index(next(iter(picks))) + 1)
        else:
            self.system_cb.current(0)

    def set_system(self):
        i = self.system_cb.current()
        code = self.codes[i - 1] if i > 0 else None
        for iid in self.tv.selection():
            r = self.rows.get(iid)
            if r and not r.status.startswith("Imported"):
                romimport.set_system(r, code)
                self._show(iid)
        self._update_buttons()

    def todo(self):
        ready = set(romimport.to_import(self.rows.values()))
        return [(iid, r) for iid, r in self.rows.items() if r in ready]

    def _update_buttons(self):
        n = len(self.todo())
        state = "normal" if n and not self.busy and not self.scanning else "disabled"
        self.import_btn.config(text=f"Import {n} game{'s' if n != 1 else ''}" if n else "Import", state=state)
        if self.busy:
            return
        if self.scanning:
            self.status.config(text="Looking at what's in the list …")
        elif not self.rows:
            self.status.config(text="Nothing to import yet: put games in the import folder, or press Add files.")
        else:
            unknown = sum(1 for r in self.rows.values() if not r.status.startswith("Imported") and not r.ready())
            self.status.config(text=f"{unknown} can't be placed: select them and pick their system." if unknown
                               else "Ready.")

    # ---------- importing ----------
    def start(self):
        items = self.todo()
        if not items or self.busy:
            return
        self.busy = True
        self.cancel.clear()
        self.import_btn.config(state="disabled")
        delete = self.delete_var.get()
        threading.Thread(target=self._import, args=(items, delete), daemon=True).start()

    def _import(self, items, delete):
        total = len(items)
        for k, (iid, r) in enumerate(items):
            if self.cancel.is_set():
                break

            def report(text=None, fraction=None, k=k):
                self.box.put(("progress", (text, (k + (fraction or 0)) / total)))
            report(f"Importing {r.name} …")
            romimport.import_one(r, self.roms_root, self.inbox, report, self.cancel.is_set, delete)
            self.box.put(("row", iid))
        self.box.put(("done", None))

    def _poll(self):
        if not self.win.winfo_exists():
            return
        while True:
            try:
                kind, data = self.box.get_nowait()
            except queue.Empty:
                break
            if kind == "row" and data in self.rows:
                self._show(data)
            elif kind == "scanned":
                self.scanning = max(0, self.scanning - 1)
                self._update_buttons()
            elif kind == "progress":
                text, fraction = data
                if text:
                    self.status.config(text=text)
                self.bar["value"] = int(fraction * 1000)
            elif kind == "done":
                self.busy = False
                self.bar["value"] = 0
                self._finished()
        self.win.after(100, self._poll)

    def _finished(self):
        done = [r for r in self.rows.values() if r.status.startswith("Imported")]
        self._update_buttons()
        systems = romimport.imported_systems(done)
        if done:
            self.status.config(text=f"Imported {len(done)} — they're in your ROMs folder now.")
            self.app.load_roms_root(self.roms_root)  # new system folders show up in the main window
            self.app.toast(f"Imported {len(done)} game{'s' if len(done) != 1 else ''}"
                           + (f" into {', '.join(systems)}" if systems else "") + ".")

    def close(self):
        if self.busy:
            if not messagebox.askyesno(TITLE, "Stop importing? The game being imported now is left where it was.",
                                       parent=self.win):
                return
            self.cancel.set()
        if self.watch_job:
            self.win.after_cancel(self.watch_job)
        self.app.import_window = None
        self.win.destroy()
