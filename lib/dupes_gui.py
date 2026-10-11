"""Tools → Find duplicates: games kept in two forms, and identical copies anywhere in the library (lib/dupes.py).
Each set shows which copy stays (double-click another to keep that one instead); the rest go to the holding
folder, from where Restore a move can bring them back."""
import datetime, os, queue, threading
import tkinter as tk
from tkinter import ttk, messagebox

import dupes
import scraper
import ui
from frontend import human_size as human

TITLE = "Find duplicates"
KINDS = {"formats": "Same game, two forms", "copies": "Identical copies"}


def open_window(app):
    w = getattr(app, "dupes_window", None)
    if w and w.win.winfo_exists():
        w.win.deiconify()
        w.win.lift()
        return w
    if not app.cfg.get("roms_root"):
        messagebox.showinfo(TITLE, "Pick your ROMs folder first (or set up RetroDECK / ES-DE from Tools).")
        return None
    w = app.dupes_window = DupesWindow(app)
    return w


class DupesWindow:
    def __init__(self, app):
        self.app = app
        self.roms_root = app.cfg["roms_root"]
        self.sets = {}    # tree id of a set -> dupes.Set
        self.copies = {}  # tree id of a copy -> (set id, index)
        self.box = queue.Queue()
        self.busy = False
        self.cancel = threading.Event()
        self.poll_job = None

        win = self.win = tk.Toplevel(app.root)
        win.title(TITLE)
        win.transient(app.root)
        scale = max(1.0, app.root.winfo_fpixels("1i") / 96)
        win.geometry(f"{min(round(1080 * scale), app.root.winfo_screenwidth())}x"
                     f"{min(round(700 * scale), app.root.winfo_screenheight() - 80)}")
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
        ttk.Label(body, text="Games kept twice in one folder in different forms (a .cue / .bin and a .chd, a .zip "
                             "and the ROM inside it …), and identical files anywhere in the library, compared by "
                             "content (the same game in snes and sfc, or under two names). One copy of each stays: "
                             "the one ES-DE knows, or the best form. Double-click another copy to keep that one "
                             "instead. The others go to the holding folder.",
                  style="Muted.TLabel", wraplength=1020, justify="left").pack(anchor="w", pady=(2, 10))

        foot = ttk.Frame(body, padding=(0, 10, 0, 0))
        foot.pack(side="bottom", fill="x")
        ttk.Button(foot, text="Close", command=self.close).pack(side="right")
        self.go_btn = ttk.Button(foot, text="Move the extra copies", style="Accent.TButton", command=self.resolve)
        self.go_btn.pack(side="right", padx=(0, 6))
        ui.Tooltip(self.go_btn, "For the selected sets, or every set when none is selected: the copies not kept "
                                "move to the holding folder (Library → Restore a move… puts them back).")
        self.keep_btn = ttk.Button(foot, text="Keep this copy", command=self.keep_selected)
        self.keep_btn.pack(side="right", padx=(0, 6))
        self.again_btn = ttk.Button(foot, text="Look again", command=self.scan)
        self.again_btn.pack(side="right", padx=(0, 6))
        self.summary = ttk.Label(foot, style="Muted.TLabel")
        self.summary.pack(side="left")

        prog = ttk.Frame(body)
        prog.pack(side="bottom", fill="x", pady=(8, 0))
        self.bar = ttk.Progressbar(prog, mode="determinate", maximum=1000, length=220)
        self.bar.pack(side="right", padx=(12, 0))
        self.status = ttk.Label(prog, style="Muted.TLabel", anchor="w")
        self.status.pack(side="left", fill="x", expand=True)

        box = ttk.Frame(body)
        box.pack(fill="both", expand=True)
        tv = self.tv = ttk.Treeview(box, columns=("what", "system", "form", "size"), selectmode="extended")
        for col, text, width, anchor, stretch in (("#0", "Game", 400, "w", True), ("what", "", 170, "w", False),
                                                  ("system", "System", 110, "w", False),
                                                  ("form", "Form", 140, "w", False), ("size", "Size", 100, "e", False)):
            tv.heading(col, text=text, anchor=anchor)
            tv.column(col, width=width, anchor=anchor, stretch=stretch)
        sb = ttk.Scrollbar(box, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tv.pack(side="left", fill="both", expand=True)
        c = self.app.colors
        tv.tag_configure("set", font="SunValleyBodyStrongFont")
        tv.tag_configure("keep", foreground=c["keep"])
        tv.tag_configure("go", foreground=c["move"])
        tv.tag_configure("done", foreground=c["muted"])
        tv.bind("<Double-Button-1>", lambda e: self.keep_selected())
        tv.bind("<<TreeviewSelect>>", lambda e: self._update_summary())

    # ---------- looking ----------
    def scan(self):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        for b in (self.again_btn, self.go_btn):
            b.state(["disabled"])
        self.status.config(text="Looking …")
        unit_key = self.app.unit_key

        def work():
            try:
                self.box.put(("found", dupes.find(self.roms_root, unit_key,
                                                  lambda t, f: self.box.put(("progress", (t, f))),
                                                  self.cancel.is_set)))
            except InterruptedError:
                pass
            except Exception as e:
                self.box.put(("error", str(e)[:300]))
        threading.Thread(target=work, daemon=True).start()

    def show(self, sets):
        tv = self.tv
        tv.delete(*tv.get_children())
        self.sets, self.copies = {}, {}
        for s in sets:
            sid = tv.insert("", "end", text=s.title, open=True, tags=("set",),
                            values=(KINDS[s.kind], "", f"{len(s.copies)} copies", ""))
            self.sets[sid] = s
            for i, c in enumerate(s.copies):
                cid = tv.insert(sid, "end", text=c.rel, values=("", c.system, c.fmt, human(c.size)))
                self.copies[cid] = (sid, i)
            self._mark(sid)
        extra = sum(s.extra for s in sets)
        self.status.config(text="No duplicates found." if not sets else
                           f"{len(sets):,} games with duplicates: {human(extra)} in the copies that would go.")
        self._update_summary()

    def _mark(self, sid):
        s = self.sets[sid]
        for cid in self.tv.get_children(sid):
            _, i = self.copies[cid]
            keep = i == s.keep
            self.tv.set(cid, "what", "✓ Keep" if keep else "→ Holding folder")
            self.tv.item(cid, tags=("keep" if keep else "go",))
        self.tv.set(sid, "size", f"{human(s.extra)} extra")

    def keep_selected(self):
        for cid in self.tv.selection():
            if cid in self.copies and "done" not in self.tv.item(cid, "tags"):
                sid, i = self.copies[cid]
                self.sets[sid].keep = i
                self._mark(sid)
        self._update_summary()

    def chosen(self):
        ids = []
        for iid in self.tv.selection():
            sid = self.copies[iid][0] if iid in self.copies else iid
            if sid in self.sets and sid not in ids:
                ids.append(sid)
        return [sid for sid in (ids or list(self.sets)) if "done" not in self.tv.item(sid, "tags")]

    def _update_summary(self):
        if self.busy:
            return
        ids = self.chosen()
        sel = self.tv.selection()
        self.keep_btn.state(["!disabled"] if any(i in self.copies for i in sel) else ["disabled"])
        self.go_btn.state(["!disabled"] if ids else ["disabled"])
        extra = sum(self.sets[i].extra for i in ids)
        self.summary.config(text=f"{len(ids):,} games  ·  frees {human(extra)}" if ids else "")

    # ---------- moving ----------
    def resolve(self):
        ids = self.chosen()
        if not ids or self.busy:
            return
        sets = [self.sets[i] for i in ids]
        n = sum(len(s.copies) - 1 for s in sets)
        holding = self.app.holding_root()
        note = ("\n\n(The holding folder is on the same drive: the space comes back when you delete them there.)"
                if self.app.holding_on_same_drive() else "")
        if not messagebox.askyesno(TITLE, f"Move {n:,} extra cop{'y' if n == 1 else 'ies'} of {len(sets):,} games "
                                          f"({human(sum(s.extra for s in sets))}) into\n"
                                          f"{os.path.join(holding, 'to_delete')}/ ?{note}", parent=self.win):
            return
        moves, problems = dupes.resolve(sets, self.roms_root, holding, scraper.es_de_running())
        now = datetime.datetime.now().isoformat(timespec="seconds")
        for system, done in moves.items():
            self.app._log_moves({"time": now, "system": system, "dest": "to_delete",
                                 "games": len({os.path.basename(s) for s, _ in done}),
                                 "size": sum(dupes._size(t) for _, t in done), "moves": done, "why": "duplicates"})
        for sid in ids:
            self.tv.item(sid, tags=("set", "done"), open=False)
            self.tv.set(sid, "size", "done")
            for cid in self.tv.get_children(sid):
                self.tv.item(cid, tags=("done",))
        if moves:
            self.app.rescan()
            moved = sum(len(v) for v in moves.values())
            self.app.toast(f"Moved {moved:,} duplicate files to the holding folder.")
        self.status.config(text=f"Moved the extra copies of {len(ids):,} games." if moves else "Nothing moved.")
        self._update_summary()
        if problems:
            messagebox.showerror(TITLE, "\n".join(problems[:30]), parent=self.win)

    # ---------- plumbing ----------
    def _poll(self):
        if not self.win.winfo_exists():
            return
        try:
            while True:
                kind, data = self.box.get_nowait()
                if kind == "progress":
                    text, fraction = data
                    self.status.config(text=text)
                    self.bar.config(value=int(fraction * 1000))
                    continue
                self.busy = False
                self.bar.config(value=0)
                self.again_btn.state(["!disabled"])
                if kind == "found":
                    self.show(data)
                else:
                    self.status.config(text=f"Couldn't look: {data}")
                self._update_summary()
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
        self.app.dupes_window = None
        self.win.destroy()
