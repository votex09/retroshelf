"""NoPayStation window for RetroShelf: search the NPS lists, queue packages, download and install them."""
import datetime, os, queue, re, shutil, threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import launchbox as lb
import nps
import scraper
import ui
from fsutil import is_windows

REGION_CHOICES = ["All regions"] + list(nps.REGIONS)
PARALLEL_DOWNLOADS = 2
OWNED = ("Installed", "Have as ROM", "Have (other region)")
REGION_TAG = re.compile(r"\((?:[^)]*\b)?(?:USA|Europe|Japan|World|Asia|Korea|Australia)\b")


def human(n):
    return f"{n / 1073741824:.2f} GB" if n >= 1073741824 else f"{n / 1048576:.1f} MB"


def open_window(app):
    """One NoPayStation window at a time: a second click just brings the open one forward."""
    w = getattr(app, "nps_window", None)
    if w and w.win.winfo_exists() and w.system != app.system and not w.running:
        w._finish()  # idle window for another system: reopen for the one picked now
    elif w and w.win.winfo_exists():
        w.win.deiconify()
        w.win.lift()
        w.win.focus_force()
        return w
    app.nps_window = NpsWindow(app)
    return app.nps_window


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
        self._index_library()

        win = self.win = tk.Toplevel(app.root)
        win.title(f"NoPayStation — {app.fullname or self.system}")
        win.transient(app.root)
        win.geometry("1150x860")
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        self._build()
        win.protocol("WM_DELETE_WINDOW", self.close)
        self.load_kind()

    def _index_library(self):
        """What's already here: title ids the emulator has, and loose titles of the ROMs in this system's folder."""
        self.owned_ids = nps.owned_ids(self.system, self.roms_root)
        self.rom_titles = {}  # title key -> [ROM key]
        # shortcut / .psvita entries are a specific installed title id (shown as Installed), never another region
        self.launchers = {k for k, u in self.app.units.items() if u.get("extra")}
        for key in self.app.units:
            self.rom_titles.setdefault(nps.title_key(key), []).append(key)

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
        self.fw_anchor = ttk.Label(body, text=self._install_note(), style="Muted.TLabel", wraplength=1080,
                                   justify="left")
        self.fw_anchor.pack(anchor="w", pady=(2, 0))
        self.fw_lbl = ttk.Label(body, style="Move.TLabel", wraplength=1080, justify="left")
        self._show_problems()

        flt = ttk.Frame(body, padding=(0, 10, 0, 0))
        flt.pack(fill="x")
        self.kind = tk.StringVar(value=next(iter(self.kinds)))
        kind_cb = ttk.Combobox(flt, textvariable=self.kind, values=list(self.kinds), state="readonly", width=10)
        kind_cb.pack(side="left")
        kind_cb.bind("<<ComboboxSelected>>", lambda e: self.load_kind())
        self.region = tk.StringVar(value="US")
        reg_cb = ttk.Combobox(flt, textvariable=self.region, values=REGION_CHOICES, state="readonly", width=12)
        reg_cb.pack(side="left", padx=(6, 0))
        reg_cb.bind("<<ComboboxSelected>>", lambda e: self.render())
        ttk.Label(flt, text="Search").pack(side="left", padx=(16, 8))
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *_: self._debounce())
        search = ttk.Entry(flt, textvariable=self.query)
        search.pack(side="left", fill="x", expand=True)
        search.focus_set()
        self.only_mine = tk.BooleanVar(value=False)
        if self.system in ("ps3", "psvita"):
            ttk.Checkbutton(flt, text="Only for my games", variable=self.only_mine,
                            command=self.render).pack(side="left", padx=(12, 0))
        self.hide_installed = tk.BooleanVar(value=False)
        ttk.Checkbutton(flt, text="Hide ones I have", variable=self.hide_installed,
                        command=self.render).pack(side="left", padx=(12, 0))

        # footer first, packed to the bottom, so the panes can never squeeze it out
        foot = ttk.Frame(body, padding=(0, 10, 0, 0))
        foot.pack(side="bottom", fill="x")
        ttk.Label(foot, text="Downloads").pack(side="left")
        self.dir_lbl = ttk.Label(foot, text=self.dl_dir(), style="Muted.TLabel")
        self.dir_lbl.pack(side="left", padx=(8, 6))
        ttk.Button(foot, text="Change…", command=self.browse_dir).pack(side="left")
        emulator = nps.SYSTEM_EMULATOR.get(self.system)
        if is_windows() and emulator:
            pick = ttk.Button(foot, text="Emulators…", command=lambda: self.pick_emulator(emulator))
            pick.pack(side="left", padx=(6, 0))
            ui.Tooltip(pick, lambda: f"{nps.EMULATOR_NAMES[emulator]}: "
                                     f"{nps.find_emulator(emulator, self.roms_root) or 'not found'}")
        self.keep_pkg = tk.BooleanVar(value=self.app.cfg.get("nps_keep_pkg", False))
        ttk.Checkbutton(foot, text="Keep .pkg after install", variable=self.keep_pkg,
                        command=self._save_opts).pack(side="left", padx=(16, 0))
        self.do_scrape = tk.BooleanVar(value=self.app.cfg.get("nps_scrape", True))
        ttk.Checkbutton(foot, text="Scrape new games (LaunchBox)", variable=self.do_scrape,
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
        self.hint = ttk.Label(row, text="Double-click or Enter to queue · ctrl / shift-click for several",
                              style="Muted.TLabel")
        self.hint.pack(side="left")
        ttk.Button(row, text="Add to queue", command=self.enqueue).pack(side="right")
        self.res_tv = self._tree(top, (("id", "Title ID", 95, "w"), ("region", "Region", 70, "w"),
                                       ("size", "Size", 90, "e"), ("status", "Status", 150, "w")))
        for col in ("#0", "id", "region", "size"):
            self.res_tv.heading(col, command=lambda c=col: self.sort(c))
        self.res_tv.bind("<Double-Button-1>", lambda e: self.enqueue())
        self.res_tv.bind("<Return>", lambda e: self.enqueue())
        self.res_tv.bind("<<TreeviewSelect>>", lambda e: self._show_have())
        panes.add(top, weight=3)

        bot = ttk.Frame(panes, padding=(0, 10, 0, 0))
        self.q_lbl = ttk.Label(bot, text="Queue", style="Section.TLabel")
        self.q_lbl.pack(anchor="w", pady=(0, 4))
        self.q_tv = self._tree(bot, (("size", "Size", 90, "e"), ("status", "Status", 260, "w")), height=5)
        self.q_tv.bind("<Delete>", lambda e: self.dequeue())
        self.q_tv.bind("<Button-3>", self._queue_menu)
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
        tv.tag_configure("have", foreground=self.app.colors["manual"])
        return tv

    def _install_note(self):
        return {
            "PS3": "Packages are decrypted straight into RPCS3's dev_hdd0/game, the license (.rap) goes to exdata, "
                   "and games get a shortcut in roms/ps3 so ES-DE lists them (ES-DE's default RPCS3 Shortcut "
                   "emulator launches it). Updates come from Sony's update "
                   "server for the games RPCS3 already has.",
            "PSV": "Packages are installed by Vita3K (license included), and games get a .psvita entry in "
                   "roms/psvita. Updates aren't offered: NPS has no license for them and Vita3K needs one.",
            "PSP": "The game's EBOOT.PBP is pulled out of the package into roms/psp; PPSSPP plays it directly. "
                   "PC Engine / NeoGeo titles are hidden since PPSSPP can't run them.",
        }[self.console]

    def _show_problems(self):
        fw = nps.firmware_problem(self.system, self.roms_root)
        if fw:
            self.fw_lbl.config(text="⚠ " + fw)
            self.fw_lbl.pack(anchor="w", pady=(6, 0), after=self.fw_anchor)
        else:
            self.fw_lbl.pack_forget()

    # ---------- options ----------
    def pick_emulator(self, name):
        """Windows: the folder with rpcs3.exe / Vita3K.exe, kept in config.json."""
        exe = nps.EMULATOR_EXES[name]
        path = filedialog.askdirectory(title=f"Folder with {exe}", parent=self.win,
                                       initialdir=nps.find_emulator(name, self.roms_root) or self.roms_root)
        if not path:
            return
        if not os.path.isfile(os.path.join(path, exe)):
            messagebox.showerror(f"No {exe}", f"There's no {exe} in\n{path}", parent=self.win)
            return
        self.app.cfg["emulator_dirs"][name] = nps.emulator_dirs[name] = os.path.normpath(path)
        self.app.save_cfg()
        self._index_library()
        self._show_problems()
        self.render()


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
        self.app.cfg["nps_scrape"] = self.do_scrape.get()
        self.app.save_cfg()

    # ---------- lists ----------
    def _in_thread(self, work, done):
        """Run work(say) off the UI thread, then done(result or exception) on it. say(text) updates the status."""
        box, said = queue.Queue(), queue.Queue()

        def run():
            try:
                box.put(work(said.put))
            except Exception as e:
                box.put(e)

        def poll():
            while not said.empty():
                self.status.config(text=said.get())
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
        updates = self.kinds[kind] is None
        self.status.config(text="Checking Sony's update server …" if updates else
                           f"Loading {self.console} {kind} list …")

        def done(res):
            if isinstance(res, Exception):
                self.status.config(text=f"Couldn't load the list: {res}")
                return
            self.rows[kind] = res
            self.status.config(text=f"{len(res)} updates found for {len(self.owned_ids)} games" if updates else "")
            self.render()
        if updates:
            self._in_thread(lambda say: nps.load_updates(self.roms_root, say), done)
        else:
            self._in_thread(lambda say: nps.load_list(self.system, kind), done)

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
        self._in_thread(lambda say: [nps.fetch_list(n) for n in self.kinds.values() if n], done)

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

    def _have(self, row):
        """ROM keys in this system's folder that look like the same game (ordinary ROMs, e.g. a CHD of a PSN title)."""
        if row["kind"] not in ("Games", "Demos"):
            return []
        return self.rom_titles.get(nps.title_key(row["name"]), [])

    def _status_of(self, row):
        if id(row) in self.job_state:
            return self.job_state[id(row)]
        if nps.is_installed(row, self.roms_root):
            return "Installed"
        have = self._have(row)
        if have:
            region = nps.REGIONS.get(row["region"], row["region"])
            # untagged files (Ape_Quest.cso) count as a match; installed launchers never do (other title id)
            tagged = [k for k in have if REGION_TAG.search(k) or k in self.launchers]
            return "Have as ROM" if len(tagged) < len(have) or any(
                k not in self.launchers and (f"({region}" in k or f", {region}" in k) for k in tagged) \
                else "Have (other region)"
        return ""

    def _show_have(self):
        sel = self.res_tv.selection()
        have = self._have(self.shown[int(sel[0])]) if len(sel) == 1 else []
        self.hint.config(text=("You have: " + "  ·  ".join(have[:3])) if have else
                         "Double-click or Enter to queue · ctrl / shift-click for several")

    def render(self):
        self._after = None
        kind = self.kind.get()
        rows = self.rows.get(kind)
        if rows is None:
            return
        words = self.query.get().lower().split()
        region = self.region.get()
        mine = self.only_mine.get() or kind == "Updates"
        shown = [r for r in rows
                 if (region not in nps.REGIONS or r["region"] == region or kind == "Updates")
                 and (not mine or r["id"] in self.owned_ids)
                 and all(w in f"{r['name']} {r['id']}".lower() for w in words)]
        status = {id(r): self._status_of(r) for r in shown}
        if self.hide_installed.get():
            shown = [r for r in shown if status[id(r)] not in OWNED]
        col, desc = self.sort_by
        if kind == "Updates" and col == "name":  # keep each game's updates in install order
            shown.sort(key=lambda r: (r["name"].split("  ·  ")[0].lower(), nps.ver(r["version"])), reverse=desc)
        else:
            shown.sort(key=lambda r: r[col] if col != "name" else r["name"].lower(), reverse=desc)
        self.shown = shown
        tv = self.res_tv
        tv.delete(*tv.get_children())
        for i, r in enumerate(shown):
            st = status[id(r)]
            name = r["name"] + (f"  ·  {r['subtype']}" if r["subtype"] and r["subtype"] != "PSP" else "")
            tv.insert("", "end", iid=str(i), text=name,
                      values=(r["id"], nps.REGIONS.get(r["region"], r["region"]), human(r["size"]), st),
                      tags=("installed",) if st == "Installed" else ("have",) if st in OWNED else ())
        age = nps.list_age(self.system)
        self.age_lbl.config(text=f"Lists from {datetime.datetime.fromtimestamp(age):%Y-%m-%d}" if age else "")
        self.res_lbl.config(text=f"{len(shown):,} of {len(rows):,} {kind.lower()}")
        self._show_have()

    # ---------- queue ----------
    def enqueue(self):
        picked = [self.shown[int(iid)] for iid in self.res_tv.selection()]
        if self.kind.get() == "Updates":
            # PS3 updates usually aren't cumulative: pull in every older one the game is still missing, in order
            ids = {r["id"] for r in picked}
            newest = {i: max(nps.ver(r["version"]) for r in picked if r["id"] == i) for i in ids}
            picked = sorted((r for r in self.rows["Updates"] if r["id"] in ids
                             and nps.ver(r["version"]) <= newest[r["id"]] and not nps.is_installed(r, self.roms_root)),
                            key=lambda r: (r["id"], nps.ver(r["version"])))
        added = 0
        for r in picked:
            queued = next((j for j in self.jobs if j is r), None)
            if queued is not None:
                if self.job_state.get(id(r), "").startswith("Failed"):  # adding a failed one again retries it
                    self._set_job(r, "Queued")
                    added += 1
                continue
            self.jobs.append(r)
            self.job_state[id(r)] = "Queued"
            added += 1
        if added:
            self.render_queue()
            self.render()

    def dequeue(self):
        picked = [self.jobs[int(iid)] for iid in self.q_tv.selection()]  # resolve before removing shifts indices
        for r in picked:
            st = self.job_state.get(id(r), "")
            if st in ("Queued", "Done") or st.startswith("Failed"):
                self.jobs = [j for j in self.jobs if j is not r]
                self.job_state.pop(id(r), None)
        self.render_queue()
        self.render()

    def _failed(self, rows):
        return [r for r in rows if self.job_state.get(id(r), "").startswith("Failed")]

    def _queue_menu(self, e):
        row = self.q_tv.identify_row(e.y)
        if row and row not in self.q_tv.selection():
            self.q_tv.selection_set(row)
        picked = [self.jobs[int(iid)] for iid in self.q_tv.selection()]
        failed, all_failed = self._failed(picked), self._failed(self.jobs)
        removable = [r for r in picked if self.job_state.get(id(r), "") in ("Queued", "Done")] + failed
        menu = tk.Menu(self.win, tearoff=0)
        menu.add_command(label=f"Retry ({len(failed)})" if len(failed) > 1 else "Retry",
                         state="normal" if failed else "disabled", command=lambda: self.retry(failed))
        menu.add_command(label=f"Retry all failed ({len(all_failed)})", state="normal" if all_failed else "disabled",
                         command=lambda: self.retry(all_failed))
        menu.add_separator()
        menu.add_command(label="Remove", state="normal" if removable else "disabled", command=self.dequeue)
        menu.tk_popup(e.x_root, e.y_root)

    def retry(self, rows):
        """Failed jobs go back to Queued; an already-downloaded .pkg is reused, so they go straight to installing."""
        for r in rows:
            self._set_job(r, "Queued")
        self.render_queue()
        self.render()
        self.status.config(text=f"{len(rows)} queued again" +
                                ("  ·  they run after the current batch, press Start then" if self.running
                                 else "  ·  press Start"))

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
        i = next((n for n, j in enumerate(self.jobs) if j is row), None)
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
        scrape = None
        if self.do_scrape.get() and self.app.platform and lb.has_details():
            scrape = (self.app.platform, self.app.gamelist_path(), not scraper.es_de_running())
        self.running, self.cancel = True, False
        self.start_btn.config(text="Stop")
        self.dl_bytes, self.dl_total = {}, sum(r["size"] for r in pending) or 1
        self.bar.config(maximum=self.dl_total, value=0)
        threading.Thread(target=self._work, args=(pending, dl_dir, self.keep_pkg.get(), scrape), daemon=True).start()
        self.poll()

    def _work(self, pending, dl_dir, keep, scrape):
        """Downloads run PARALLEL_DOWNLOADS at a time; installs run one by one in queue order (updates need it)."""
        msgs, cancelled = self.msgs, lambda: self.cancel
        ready = [threading.Event() for _ in pending]
        ok = [False] * len(pending)
        todo, lock = iter(range(len(pending))), threading.Lock()

        def downloader():
            while not self.cancel:
                with lock:
                    i = next(todo, None)
                if i is None:
                    return
                row = pending[i]
                msgs.put(("job", row, "Downloading"))
                try:
                    ok[i] = nps.download(row, nps.pkg_path(row, dl_dir),
                                         lambda d, t: msgs.put(("prog", row, "Downloading", d, t)), cancelled)
                    msgs.put(("job", row, "Downloaded, waiting to install" if ok[i] else "Queued"))
                except Exception as e:
                    msgs.put(("job", row, f"Failed: {str(e).splitlines()[0]}"))
                    msgs.put(("log", f"{row['name']}: {e}"))
                ready[i].set()

        threads = [threading.Thread(target=downloader, daemon=True) for _ in range(PARALLEL_DOWNLOADS)]
        for t in threads:
            t.start()
        new_entries = []
        for i, row in enumerate(pending):
            while not ready[i].wait(0.2):
                if not any(t.is_alive() for t in threads):
                    break
            if not ok[i]:
                continue
            if self.cancel:  # downloaded but not installed yet: the .pkg stays, Start picks it up again
                msgs.put(("job", row, "Queued"))
                continue
            pkg = nps.pkg_path(row, dl_dir)
            msgs.put(("job", row, "Installing"))
            try:
                if not nps.install(row, pkg, self.roms_root, lambda m: msgs.put(("log", m)),
                                   lambda d, t: msgs.put(("prog", row, "Installing", d, t)), cancelled):
                    msgs.put(("job", row, "Queued"))
                    continue
                if not keep:
                    os.unlink(pkg)
                msgs.put(("job", row, "Done"))
                msgs.put(("installed",))
                if row.get("entry") and row["kind"] in ("Games", "Demos"):
                    new_entries.append(row)
            except Exception as e:
                msgs.put(("job", row, f"Failed: {str(e).splitlines()[0]}"))
                msgs.put(("log", f"{row['name']}: {e}"))
        for t in threads:
            t.join()
        if scrape and new_entries and not self.cancel:
            self._scrape(new_entries, *scrape)
        msgs.put(("end",))

    def _scrape(self, rows, platform, gamelist, do_text):
        msgs = self.msgs
        platforms = [platform]  # Matcher also searches lb.PLATFORM_EXTRAS (e.g. PSP minis)
        matchers = {p: lb.Matcher(p) for p in platforms}
        jobs = {p: [] for p in platforms}
        for r in rows:
            title = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", r["name"]).strip()
            for p, m in matchers.items():
                gid, _, _ = m.match(title)
                if gid:
                    jobs[p].append((r["entry"], gid, (nps.REGIONS.get(r["region"], r["region"]),)))
                    break
        for m in matchers.values():
            m.save()
        matched = sum(len(j) for j in jobs.values())
        if not matched:
            msgs.put(("scraped", "no LaunchBox match for the new games, nothing scraped"))
            return
        media = [k for k, (_, _, default) in scraper.MEDIA.items() if default]
        images = text = 0
        try:
            for p, j in jobs.items():
                if j:
                    s = scraper.scrape(j, p, self.system, self.roms_root, gamelist, do_text, media,
                                       lambda t_, d, t: msgs.put(("log", f"Scraping: {t_}")), lambda: self.cancel)
                    images, text = images + s["images"], text + s["text"]
            msgs.put(("scraped", f"scraped {matched} of {len(rows)} new games: {images} images"
                                 + (f", {text} text fields" if do_text else
                                    " (text skipped while RetroDECK runs: scrape again after closing it)")))
        except Exception as e:
            msgs.put(("scraped", f"scraping failed: {e}"))

    def poll(self):
        try:
            while True:
                m = self.msgs.get_nowait()
                if m[0] == "job":
                    self._set_job(m[1], m[2])
                    self.status.config(text=f"{m[2]}: {m[1]['name']}")
                elif m[0] == "prog":
                    _, row, what, d, t = m
                    if what == "Downloading":
                        self.dl_bytes[id(row)] = d
                        self.bar.config(value=sum(self.dl_bytes.values()))
                    if t:
                        self._set_job(row, f"{what}  {d * 100 // t}%  ({human(d)} / {human(t)})")
                elif m[0] == "log":
                    self.status.config(text=m[1])
                elif m[0] == "scraped":
                    self.scraped = m[1]
                elif m[0] == "installed":
                    self.installed_any = True
                elif m[0] == "end":
                    self.running = False
                    self.start_btn.config(state="normal", text="Start")
                    self.bar.config(value=self.bar.cget("maximum") if not self.cancel else self.bar.cget("value"))
                    done = sum(self.job_state.get(id(r)) == "Done" for r in self.jobs)
                    failed = sum(self.job_state.get(id(r), "").startswith("Failed") for r in self.jobs)
                    self.status.config(text=("Stopped. " if self.cancel else "") +
                                       f"{done} installed, {failed} failed" +
                                       ("  ·  partial downloads resume next time" if self.cancel else "") +
                                       (f"  ·  {self.scraped}" if getattr(self, "scraped", None) else ""))
                    self.cancel, self.scraped = False, None
                    self.owned_ids = nps.owned_ids(self.system, self.roms_root)
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
        self.app.nps_window = None
        self.win.destroy()
        if self.installed_any and self.app.system == self.system:
            self.app.rescan()
