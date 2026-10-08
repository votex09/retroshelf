"""NoPayStation window for ROM Pruner: search the NPS lists, queue packages, download and install them."""
import datetime, os, queue, shutil, threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import nps

REGION_CHOICES = ["All regions"] + list(nps.REGIONS)


def human(n):
    return f"{n / 1073741824:.2f} GB" if n >= 1073741824 else f"{n / 1048576:.1f} MB"


class NpsWindow:
    def __init__(self, app):
        self.app = app
        self.system = app.system
        self.console, self.kinds = nps.CONSOLES[self.system]
        self.roms_root = app.cfg["roms_root"]
        self.rows = {}           # kind -> [row]
        self.shown = []
        self.jobs = []           # queued rows, in order
        self.job_state = {}      # id(row) -> status text
        self.msgs = queue.Queue()
        self.running = self.cancel = False
        self.installed_any = False
        self.sort_by = ("name", False)

        win = self.win = tk.Toplevel(app.root)
        win.title(f"NoPayStation — {app.fullname or self.system}")
        win.transient(app.root)
        win.geometry("1150x820")
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        self._build()
        win.protocol("WM_DELETE_WINDOW", self.close)
        self.load_kind()

    # ---------- UI ----------
    def _build(self):
        body = ttk.Frame(self.win, padding=16)
        body.pack(fill="both", expand=True)
        head = ttk.Frame(body)
        head.pack(fill="x")
        ttk.Label(head, text=f"NoPayStation  ·  {self.console}", style="Section.TLabel").pack(side="left")
        ttk.Button(head, text="Refresh lists", command=self.refresh_lists).pack(side="right")
        self.age_lbl = ttk.Label(head, style="Muted.TLabel")
        self.age_lbl.pack(side="right", padx=(0, 8))
        ttk.Label(body, text=self._install_note(), style="Muted.TLabel", wraplength=1080,
                  justify="left").pack(anchor="w", pady=(2, 10))

        flt = ttk.Frame(body)
        flt.pack(fill="x")
        self.kind = tk.StringVar(value=next(iter(self.kinds)))
        kind_cb = ttk.Combobox(flt, textvariable=self.kind, values=list(self.kinds), state="readonly", width=10)
        kind_cb.pack(side="left")
        kind_cb.bind("<<ComboboxSelected>>", lambda e: self.load_kind())
        self.region = tk.StringVar(value="US" if "US" in nps.REGIONS else REGION_CHOICES[0])
        reg_cb = ttk.Combobox(flt, textvariable=self.region, values=REGION_CHOICES, state="readonly", width=12)
        reg_cb.pack(side="left", padx=(6, 0))
        reg_cb.bind("<<ComboboxSelected>>", lambda e: self.render())
        ttk.Label(flt, text="Search").pack(side="left", padx=(16, 8))
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *_: self._debounce())
        search = ttk.Entry(flt, textvariable=self.query)
        search.pack(side="left", fill="x", expand=True)
        search.focus_set()
        self.hide_installed = tk.BooleanVar(value=False)
        ttk.Checkbutton(flt, text="Hide installed", variable=self.hide_installed,
                        command=self.render).pack(side="left", padx=(12, 0))

        # footer first, packed to the bottom, so the panes can never squeeze it out
        foot = ttk.Frame(body, padding=(0, 10, 0, 0))
        foot.pack(side="bottom", fill="x")
        ttk.Label(foot, text="Downloads").pack(side="left")
        self.dir_lbl = ttk.Label(foot, text=self.dl_dir(), style="Muted.TLabel")
        self.dir_lbl.pack(side="left", padx=(8, 6))
        ttk.Button(foot, text="Change…", command=self.browse_dir).pack(side="left")
        self.keep_pkg = tk.BooleanVar(value=self.app.cfg.get("nps_keep_pkg", False))
        ttk.Checkbutton(foot, text="Keep .pkg after install", variable=self.keep_pkg,
                        command=self._save_opts).pack(side="left", padx=(16, 0))
        self.start_btn = ttk.Button(foot, text="Start", style="Accent.TButton", command=self.start)
        self.start_btn.pack(side="right")
        ttk.Button(foot, text="Remove", command=self.dequeue).pack(side="right", padx=(0, 6))
        self.status = ttk.Label(body, style="Muted.TLabel", anchor="w")
        self.status.pack(side="bottom", fill="x")
        self.bar = ttk.Progressbar(body, mode="determinate")
        self.bar.pack(side="bottom", fill="x", pady=(10, 4))

        panes = ttk.PanedWindow(body, orient="vertical")
        panes.pack(fill="both", expand=True, pady=(10, 0))

        top = ttk.Frame(panes)
        self.res_lbl = ttk.Label(top, style="Muted.TLabel")
        self.res_lbl.pack(anchor="w", pady=(0, 4))
        row = ttk.Frame(top)
        row.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Label(row, text="Double-click or Enter to queue · ctrl / shift-click for several",
                  style="Muted.TLabel").pack(side="left")
        ttk.Button(row, text="Add to queue", command=self.enqueue).pack(side="right")
        self.res_tv = self._tree(top, (("id", "Title ID", 95, "w"), ("region", "Region", 70, "w"),
                                       ("size", "Size", 90, "e"), ("status", "Status", 110, "w")))
        for col in ("#0", "id", "region", "size"):
            self.res_tv.heading(col, command=lambda c=col: self.sort(c))
        self.res_tv.bind("<Double-Button-1>", lambda e: self.enqueue())
        self.res_tv.bind("<Return>", lambda e: self.enqueue())
        panes.add(top, weight=3)

        bot = ttk.Frame(panes, padding=(0, 10, 0, 0))
        self.q_lbl = ttk.Label(bot, text="Queue", style="Section.TLabel")
        self.q_lbl.pack(anchor="w", pady=(0, 4))
        self.q_tv = self._tree(bot, (("size", "Size", 90, "e"), ("status", "Status", 260, "w")), height=5)
        self.q_tv.bind("<Delete>", lambda e: self.dequeue())
        panes.add(bot, weight=1)

        self.win.bind("<Escape>", lambda e: self.close())

    def _tree(self, parent, cols, height=12):
        f = ttk.Frame(parent)
        f.pack(fill="both", expand=True)
        tv = ttk.Treeview(f, columns=[c[0] for c in cols], selectmode="extended", height=height)
        tv.heading("#0", text="Name", anchor="w")
        tv.column("#0", width=420, minwidth=200, stretch=True)
        for col, text, width, anchor in cols:
            tv.heading(col, text=text, anchor=anchor)
            tv.column(col, width=width, minwidth=50, stretch=col == "status", anchor=anchor)
        sb = ttk.Scrollbar(f, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tv.tag_configure("installed", foreground=self.app.colors["keep"])
        return tv

    def _install_note(self):
        return {
            "PS3": "Packages are decrypted straight into RPCS3's dev_hdd0/game, the license (.rap) goes to exdata, "
                   "and games get a shortcut in roms/ps3 so ES-DE lists them.",
            "PSV": "Packages are installed by Vita3K (license included), and games get a .psvita entry in "
                   "roms/psvita. Updates aren't offered: NPS has no license for them and Vita3K needs one.",
            "PSP": "The game's EBOOT.PBP is pulled out of the package into roms/psp; PPSSPP plays it directly. "
                   "PC Engine / NeoGeo titles are hidden since PPSSPP can't run them.",
        }[self.console]

    # ---------- options ----------
    def dl_dir(self):
        return self.app.cfg.get("nps_dir") or os.path.expanduser("~/Downloads/NPS")

    def browse_dir(self):
        path = filedialog.askdirectory(initialdir=self.dl_dir(), title="Where packages are downloaded",
                                       parent=self.win)
        if path:
            self.app.cfg["nps_dir"] = path
            self.app.save_cfg()
            self.dir_lbl.config(text=path)

    def _save_opts(self):
        self.app.cfg["nps_keep_pkg"] = self.keep_pkg.get()
        self.app.save_cfg()

    # ---------- lists ----------
    def _in_thread(self, work, done):
        """Run work() off the UI thread, then done(result or exception) on it."""
        box = queue.Queue()

        def run():
            try:
                box.put(work())
            except Exception as e:
                box.put(e)

        def poll():
            try:
                done(box.get_nowait())
            except queue.Empty:
                self.win.after(100, poll)
        threading.Thread(target=run, daemon=True).start()
        poll()

    def load_kind(self):
        kind = self.kind.get()
        if kind in self.rows:
            self.render()
            return
        self.status.config(text=f"Loading {self.console} {kind} list …")

        def done(res):
            if isinstance(res, Exception):
                self.status.config(text=f"Couldn't load the list: {res}")
                return
            self.rows[kind] = res
            self.status.config(text="")
            self.render()
        self._in_thread(lambda: nps.load_list(self.system, kind), done)

    def refresh_lists(self):
        if self.running:
            return
        self.status.config(text="Downloading NPS lists …")

        def done(res):
            if isinstance(res, Exception):
                self.status.config(text=f"Couldn't refresh: {res}")
                return
            self.rows = {}
            self.load_kind()
        self._in_thread(lambda: [nps.fetch_list(n) for n in self.kinds.values()], done)

    # ---------- results ----------
    def _debounce(self):
        if getattr(self, "_after", None):
            self.win.after_cancel(self._after)
        self._after = self.win.after(200, self.render)

    def sort(self, col):
        col = "name" if col == "#0" else col
        c, desc = self.sort_by
        self.sort_by = (col, not desc if c == col else col == "size")
        self.render()

    def _status_of(self, row):
        if id(row) in self.job_state:
            return self.job_state[id(row)]
        return "Installed" if os.path.exists(nps.install_target(row, self.roms_root)) else ""

    def render(self):
        self._after = None
        rows = self.rows.get(self.kind.get())
        if rows is None:
            return
        words = self.query.get().lower().split()
        region = self.region.get()
        shown = [r for r in rows
                 if (region not in nps.REGIONS or r["region"] == region)
                 and all(w in f"{r['name']} {r['id']}".lower() for w in words)]
        status = {id(r): self._status_of(r) for r in shown}
        if self.hide_installed.get():
            shown = [r for r in shown if status[id(r)] != "Installed"]
        col, desc = self.sort_by
        shown.sort(key=lambda r: r[col] if col != "name" else r["name"].lower(), reverse=desc)
        self.shown = shown
        tv = self.res_tv
        tv.delete(*tv.get_children())
        for i, r in enumerate(shown):
            name = r["name"] + (f"  ·  {r['subtype']}" if r["subtype"] and r["subtype"] != "PSP" else "")
            tv.insert("", "end", iid=str(i), text=name,
                      values=(r["id"], nps.REGIONS.get(r["region"], r["region"]), human(r["size"]), status[id(r)]),
                      tags=("installed",) if status[id(r)] == "Installed" else ())
        age = nps.list_age(self.system)
        self.age_lbl.config(text=f"Lists from {datetime.datetime.fromtimestamp(age):%Y-%m-%d}" if age else "")
        self.res_lbl.config(text=f"{len(shown):,} of {len(rows):,} {self.kind.get().lower()}")

    # ---------- queue ----------
    def enqueue(self):
        added = 0
        for iid in self.res_tv.selection():
            r = self.shown[int(iid)]
            if r in self.jobs:
                continue
            self.jobs.append(r)
            self.job_state[id(r)] = "Queued"
            added += 1
        if added:
            self.render_queue()
            self.render()

    def dequeue(self):
        for iid in self.q_tv.selection():
            r = self.jobs[int(iid)]
            if self.job_state.get(id(r)) in ("Queued", "Done") or self.job_state.get(id(r), "").startswith("Failed"):
                self.jobs.remove(r)
                self.job_state.pop(id(r), None)
        self.render_queue()
        self.render()

    def render_queue(self):
        tv = self.q_tv
        sel = tv.selection()
        tv.delete(*tv.get_children())
        for i, r in enumerate(self.jobs):
            tv.insert("", "end", iid=str(i), text=f"{r['name']}  ({r['id']}, {r['kind']})",
                      values=(human(r["size"]), self.job_state.get(id(r), "")))
        for iid in sel:
            if tv.exists(iid):
                tv.selection_add(iid)
        pending = [r for r in self.jobs if self.job_state.get(id(r)) == "Queued"]
        self.q_lbl.config(text=f"Queue   {len(pending)} waiting  ·  {human(sum(r['size'] for r in pending))}")

    def _set_job(self, row, text):
        self.job_state[id(row)] = text
        i = self.jobs.index(row) if row in self.jobs else None
        if i is not None and self.q_tv.exists(str(i)):
            self.q_tv.set(str(i), "status", text)

    # ---------- worker ----------
    def start(self):
        if self.running:
            self.cancel = True
            self.start_btn.config(state="disabled", text="Stopping…")
            return
        pending = [r for r in self.jobs if self.job_state.get(id(r)) == "Queued"]
        if not pending:
            self.status.config(text="Queue is empty: pick games above and press Add to queue.")
            return
        dl_dir = self.dl_dir()
        os.makedirs(dl_dir, exist_ok=True)
        need = sum(r["size"] for r in pending) + max(r["size"] for r in pending)  # packages + one extraction
        free = shutil.disk_usage(dl_dir).free
        if free < need and not messagebox.askyesno(
                "Low disk space", f"About {human(need)} is needed but only {human(free)} is free in\n{dl_dir}\n\n"
                                  "Start anyway?", parent=self.win):
            return
        self.running, self.cancel = True, False
        self.start_btn.config(text="Stop")
        keep = self.keep_pkg.get()
        msgs = self.msgs

        def work():
            for row in pending:
                if self.cancel:
                    break
                msgs.put(("job", row, "Downloading"))
                pkg = nps.pkg_path(row, dl_dir)
                try:
                    ok = nps.download(row, pkg, lambda d, t: msgs.put(("prog", row, "Downloading", d, t)),
                                      lambda: self.cancel)
                    if not ok:
                        msgs.put(("job", row, "Queued"))
                        break
                    msgs.put(("job", row, "Installing"))
                    ok = nps.install(row, pkg, self.roms_root, lambda m: msgs.put(("log", m)),
                                     lambda d, t: msgs.put(("prog", row, "Installing", d, t)), lambda: self.cancel)
                    if not ok:
                        msgs.put(("job", row, "Queued"))
                        break
                    if not keep:
                        os.unlink(pkg)
                    msgs.put(("job", row, "Done"))
                    msgs.put(("installed",))
                except Exception as e:
                    msgs.put(("job", row, f"Failed: {str(e).splitlines()[0]}"))
                    msgs.put(("log", f"{row['name']}: {e}"))
            msgs.put(("end",))

        threading.Thread(target=work, daemon=True).start()
        self.poll()

    def poll(self):
        try:
            while True:
                m = self.msgs.get_nowait()
                if m[0] == "job":
                    self._set_job(m[1], m[2])
                    self.bar.config(value=0, mode="determinate")
                    self.status.config(text=f"{m[2]}: {m[1]['name']}")
                elif m[0] == "prog":
                    _, row, what, d, t = m
                    if t:
                        self.bar.config(maximum=t, value=d)
                        self._set_job(row, f"{what}  {d * 100 // t}%  ({human(d)} / {human(t)})")
                elif m[0] == "log":
                    self.status.config(text=m[1])
                elif m[0] == "installed":
                    self.installed_any = True
                elif m[0] == "end":
                    self.running = False
                    self.start_btn.config(state="normal", text="Start")
                    done = sum(self.job_state.get(id(r)) == "Done" for r in self.jobs)
                    failed = sum(self.job_state.get(id(r), "").startswith("Failed") for r in self.jobs)
                    self.status.config(text=("Stopped. " if self.cancel else "") +
                                       f"{done} installed, {failed} failed" +
                                       ("  ·  partial downloads resume next time" if self.cancel else ""))
                    self.cancel = False
                    self.render_queue()
                    self.render()
                    return
        except queue.Empty:
            pass
        self.win.after(150, self.poll)

    def close(self):
        if self.running:
            if not messagebox.askyesno("Downloads running", "Stop after the current step and close?",
                                       parent=self.win):
                return
            self.cancel = True
            self.win.after(300, self._close_when_idle)
            return
        self._finish()

    def _close_when_idle(self):
        if self.running:
            self.win.after(300, self._close_when_idle)
        else:
            self._finish()

    def _finish(self):
        self.win.destroy()
        if self.installed_any and self.app.system == self.system:
            self.app.rescan()
