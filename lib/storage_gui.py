"""Library → Storage overview: space per system (games and ES-DE media) and each system's biggest games, so it's
clear where pruning or compressing helps most. Double-click a system or game to open it in the main window."""
import queue, threading
import tkinter as tk
from tkinter import ttk, messagebox

import storage
import ui
from frontend import human_size as human

TITLE = "Storage overview"
BAR = 14  # characters in the share-of-library bar


def open_window(app):
    w = getattr(app, "storage_window", None)
    if w and w.win.winfo_exists():
        w.win.deiconify()
        w.win.lift()
        return w
    if not app.cfg.get("roms_root"):
        messagebox.showinfo(TITLE, "Pick your ROMs folder first (or set up RetroDECK / ES-DE from Tools).")
        return None
    w = app.storage_window = StorageWindow(app)
    return w


def bar(fraction):
    full = round(max(0.0, min(1.0, fraction)) * BAR)
    return "█" * full + "·" * (BAR - full)


class StorageWindow:
    def __init__(self, app):
        self.app = app
        self.roms_root = app.cfg["roms_root"]
        self.systems = {}  # name -> storage.System
        self.box = queue.Queue()
        self.busy = False
        self.cancel = threading.Event()
        self.poll_job = None

        win = self.win = tk.Toplevel(app.root)
        win.title(TITLE)
        win.transient(app.root)
        scale = max(1.0, app.root.winfo_fpixels("1i") / 96)
        win.geometry(f"{min(round(980 * scale), app.root.winfo_screenwidth())}x"
                     f"{min(round(720 * scale), app.root.winfo_screenheight() - 80)}")
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Escape>", lambda e: self.close())
        self._build()
        self._poll()
        self.scan()

    def _build(self):
        body = ttk.Frame(self.win, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=TITLE, style="Section.TLabel").pack(anchor="w")
        self.drive_lbl = ttk.Label(body, style="Muted.TLabel")
        self.drive_lbl.pack(anchor="w", pady=(2, 4))
        self.drive_bar = ttk.Progressbar(body, mode="determinate", maximum=100)
        self.drive_bar.pack(fill="x", pady=(0, 10))

        foot = ttk.Frame(body, padding=(0, 10, 0, 0))
        foot.pack(side="bottom", fill="x")
        ttk.Button(foot, text="Close", command=self.close).pack(side="right")
        self.open_btn = ttk.Button(foot, text="Open in the main window", style="Accent.TButton", command=self.open)
        self.open_btn.pack(side="right", padx=(0, 6))
        self.again_btn = ttk.Button(foot, text="Add up again", command=self.scan)
        self.again_btn.pack(side="right", padx=(0, 6))
        self.status = ttk.Label(foot, style="Muted.TLabel", wraplength=560, justify="left")
        self.status.pack(side="left")

        panes = ttk.PanedWindow(body, orient="vertical")
        panes.pack(fill="both", expand=True)
        top = ttk.Frame(panes)
        bottom = ttk.Frame(panes, padding=(0, 10, 0, 0))
        panes.add(top, weight=3)
        panes.add(bottom, weight=2)

        self.sys_tv = self._tree(top, (("#0", "System", 230, "w"), ("games", "Games", 70, "e"),
                                       ("roms", "Games' size", 100, "e"), ("media", "Media", 90, "e"),
                                       ("total", "Total", 100, "e"), ("share", "", 150, "w"),
                                       ("compress", "Could compress", 120, "e")))
        ui.Tooltip(self.sys_tv, "Media is ES-DE's artwork, videos and manuals for the system. Could compress: disc "
                                "images Tools → Compress games would turn into .chd / .rvz (usually a third to a "
                                "half smaller).")
        self.sys_tv.bind("<<TreeviewSelect>>", lambda e: self.show_games())
        self.sys_tv.bind("<Double-Button-1>", lambda e: self.open())
        self.games_lbl = ttk.Label(bottom, text="Biggest games", style="Section.TLabel")
        self.games_lbl.pack(anchor="w", pady=(0, 6))
        self.game_tv = self._tree(bottom, (("#0", "Game", 520, "w"), ("size", "Size", 110, "e"),
                                           ("share", "", 150, "w")))
        self.game_tv.bind("<Double-Button-1>", lambda e: self.open(game=True))
        self.game_tv.bind("<Return>", lambda e: self.open(game=True))
        self.sys_tv.bind("<Return>", lambda e: self.open())

    def _tree(self, parent, cols):
        box = ttk.Frame(parent)
        box.pack(fill="both", expand=True)
        tv = ttk.Treeview(box, columns=[c[0] for c in cols[1:]], selectmode="browse")
        for col, text, width, anchor in cols:
            tv.heading(col, text=text, anchor=anchor)
            tv.column(col, width=width, anchor=anchor, stretch=col == "#0")
        sb = ttk.Scrollbar(box, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tv.pack(side="left", fill="both", expand=True)
        return tv

    # ---------- adding up ----------
    def scan(self):
        if self.busy:
            return
        self.busy = True
        self.again_btn.state(["disabled"])
        self.status.config(text="Adding up …")
        unit_key = self.app.unit_key

        def work():
            try:
                self.box.put(("done", storage.scan(self.roms_root, unit_key,
                                                   lambda t, f: self.box.put(("progress", t)), self.cancel.is_set)))
            except InterruptedError:
                pass
            except Exception as e:
                self.box.put(("error", str(e)[:300]))
        threading.Thread(target=work, daemon=True).start()

    def show(self, systems):
        keep = self.sys_tv.selection()
        self.systems = {s.name: s for s in systems}
        tv = self.sys_tv
        tv.delete(*tv.get_children())
        total = sum(s.total for s in systems) or 1
        for s in systems:
            label = self.app.system_label(s.name) if hasattr(self.app, "system_label") else s.name
            tv.insert("", "end", iid=s.name, text=label, values=(
                f"{len(s.games):,}", human(s.size), human(s.media) if s.media else "—", human(s.total),
                bar(s.total / total), human(s.compressible) if s.compressible else ""))
        pick = next((k for k in keep if tv.exists(k)), None) or (self.app.system if tv.exists(self.app.system or "")
                                                                 else None) or next(iter(tv.get_children()), None)
        if pick:
            tv.selection_set(pick)
            tv.focus(pick)
            tv.see(pick)
        lib = sum(s.size for s in systems)
        media = sum(s.media for s in systems)
        comp = sum(s.compressible for s in systems)
        self.status.config(text=f"{len(systems):,} systems: {human(lib)} of games and {human(media)} of media."
                           + (f" {human(comp)} of disc images could be compressed (Tools → Compress games)."
                              if comp else ""))
        self._drive()
        self.show_games()

    def _drive(self):
        d = storage.drive(self.roms_root)
        if not d:
            self.drive_lbl.config(text="")
            return
        free, total = d
        used = total - free
        self.drive_lbl.config(text=f"The drive with your ROMs: {human(free)} free of {human(total)} "
                                   f"({100 * used / total:.0f}% used)" if total else "")
        self.drive_bar.config(value=100 * used / total if total else 0)

    def show_games(self):
        tv = self.game_tv
        tv.delete(*tv.get_children())
        sel = self.sys_tv.selection()
        s = self.systems.get(sel[0]) if sel else None
        if not s:
            self.games_lbl.config(text="Biggest games")
            return
        rows = s.biggest()
        self.games_lbl.config(text=f"Biggest games in {self.sys_tv.item(s.name, 'text')}")
        top = rows[0][1] if rows else 1
        for key, size in rows[:200]:
            tv.insert("", "end", iid=key, text=key, values=(human(size), bar(size / (top or 1))))
        if len(rows) > 200:
            tv.insert("", "end", iid="\0more", text=f"… and {len(rows) - 200:,} smaller ones", values=("", ""))

    # ---------- going there ----------
    def open(self, game=False):
        sel = self.sys_tv.selection()
        if not sel:
            return
        system = sel[0]
        key = None
        if game:
            g = self.game_tv.selection()
            key = g[0] if g and g[0] != "\0more" else None
            if not key:
                return
        app = self.app
        if system not in getattr(app, "system_codes", [system]):
            return
        if app.system != system:
            app.load_system(system)
        app.root.deiconify()
        app.root.lift()
        if key:
            app.show_game(key)
        else:
            app.root.focus_force()

    # ---------- plumbing ----------
    def _poll(self):
        if not self.win.winfo_exists():
            return
        try:
            while True:
                kind, data = self.box.get_nowait()
                if kind == "progress":
                    self.status.config(text=data)
                    continue
                self.busy = False
                self.again_btn.state(["!disabled"])
                if kind == "done":
                    self.show(data)
                else:
                    self.status.config(text=f"Couldn't add up: {data}")
        except queue.Empty:
            pass
        self.poll_job = self.win.after(100, self._poll)

    def close(self):
        self.cancel.set()
        if self.poll_job:
            try:
                self.win.after_cancel(self.poll_job)
            except tk.TclError:
                pass
        self.app.storage_window = None
        self.win.destroy()

