"""Tools → Compress games: turn the current system's disc images into .chd / .rvz (lib/compress.py), one game at a
time, with the originals moved to the holding folder (or deleted, when asked) once each new file is checked."""
import datetime, os, queue, threading
import tkinter as tk
from tkinter import ttk, messagebox

import compress
import scraper
import ui
from frontend import human_size as human

TITLE = "Compress games"
FORMATS = {".chd": "CHD", ".rvz": "RVZ"}


def open_window(app):
    w = getattr(app, "compress_window", None)
    if w and w.win.winfo_exists():
        if w.system == app.system or w.busy:
            w.win.deiconify()
            w.win.lift()
            return w
        w.win.destroy()
    if not compress.supported(app.system, app.exts):
        messagebox.showinfo(TITLE, f"RetroShelf compresses disc images for CD systems (PlayStation, Saturn, "
                                   f"Dreamcast, Sega CD, PC Engine CD …), PS2, GameCube and Wii. "
                                   f"{app.fullname or app.system} isn't one of them"
                                   + (", or its ES-DE folder doesn't list the format." if
                                      compress.target_ext(app.system) else "."), parent=app.root)
        return None
    w = app.compress_window = CompressWindow(app)
    return w


def describe(job):
    """'cue + 2 bin', 'iso', 'folder (gdi)'"""
    if any(os.path.isdir(p) for p in job.parts):
        return f"folder ({os.path.splitext(job.src)[1][1:].lower()})"
    exts = [os.path.splitext(p)[1][1:].lower() for p in job.parts]
    first, rest = exts[0], exts[1:]
    if not rest:
        return first
    counts = {}
    for e in rest:
        counts[e] = counts.get(e, 0) + 1
    return " + ".join([first] + [f"{n} {e}" if n > 1 else e for e, n in counts.items()])


def games(n):
    return f"{n:,} game{'' if n == 1 else 's'}"


class CompressWindow:
    def __init__(self, app):
        self.app, self.system = app, app.system
        self.folder = app.folder
        self.ext = compress.supported(app.system, app.exts)
        self.rows = {}   # tree id (game key) -> [Job]
        self.tools = {}  # tool name -> Tool or None (not found)
        self.box = queue.Queue()
        self.busy = False
        self.closing = False  # closed while busy: the window hides, and goes once the game in hand is done
        self.cancel = threading.Event()
        self.poll_job = None

        win = self.win = tk.Toplevel(app.root)
        win.title(TITLE)
        win.transient(app.root)
        scale = max(1.0, app.root.winfo_fpixels("1i") / 96)
        win.geometry(f"{min(round(1000 * scale), app.root.winfo_screenwidth())}x"
                     f"{min(round(660 * scale), app.root.winfo_screenheight() - 80)}")
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Escape>", lambda e: self.close())
        self._build()
        self.fill()
        self._find_tools()
        self._poll()

    # ---------- UI ----------
    def _build(self):
        body = ttk.Frame(self.win, padding=16)
        body.pack(fill="both", expand=True)
        name = self.app.fullname or self.system
        fmt = FORMATS[self.ext]
        ttk.Label(body, text=f"Compress {name} games to {fmt}", style="Section.TLabel").pack(anchor="w")
        what = ("Disc images become CHD files (MAME's compressed format)" if self.ext == ".chd" else
                "Disc images become RVZ files (Dolphin's compressed format)")
        ttk.Label(body, text=f"{what}: usually a third to a half smaller, and read by the emulators RetroDECK and "
                             "ES-DE use for this system. Each new file is written next to the game and checked "
                             "before it replaces anything; playlists (.m3u), ES-DE's gamelist entry and artwork "
                             "follow it. Select games to compress only those.",
                  style="Muted.TLabel", wraplength=940, justify="left").pack(anchor="w", pady=(2, 8))
        self.tool_lbl = ttk.Label(body, text="Looking for the tools …", style="Muted.TLabel", wraplength=940,
                                  justify="left")
        self.tool_lbl.pack(anchor="w", pady=(0, 8))

        foot = ttk.Frame(body, padding=(0, 10, 0, 0))
        foot.pack(side="bottom", fill="x")
        ttk.Button(foot, text="Close", command=self.close).pack(side="right")
        self.go_btn = ttk.Button(foot, text="Compress", style="Accent.TButton", command=self.start)
        self.go_btn.pack(side="right", padx=(0, 6))
        self.summary = ttk.Label(foot, style="Muted.TLabel")
        self.summary.pack(side="left")

        opts = ttk.Frame(body, padding=(0, 8, 0, 0))
        opts.pack(side="bottom", fill="x")
        self.verify_var = tk.BooleanVar(value=self.app.cfg.get("compress_verify", True))
        self.delete_var = tk.BooleanVar(value=self.app.cfg.get("compress_delete", False))
        v = ttk.Checkbutton(opts, text="Check each new file before it replaces the original", variable=self.verify_var,
                            command=self._save_opts)
        v.pack(side="left")
        ui.Tooltip(v, "Reads the new file back through the tool and compares it with what was written. It takes "
                      "about as long again; without it, a game is replaced as soon as it's written.")
        d = ttk.Checkbutton(opts, text="Delete the originals (instead of moving them to the holding folder)",
                            variable=self.delete_var, command=self._save_opts)
        d.pack(side="left", padx=(16, 0))
        ui.Tooltip(d, lambda: "Originals go to " + os.path.join(self.app.holding_root(), "to_delete", self.system)
                   + ", where Library → Holding folder… deletes them for good (or Restore a move puts them back).")

        prog = ttk.Frame(body)
        prog.pack(side="bottom", fill="x", pady=(8, 0))
        self.bar = ttk.Progressbar(prog, mode="determinate", maximum=1000, length=260)
        self.bar.pack(side="right", padx=(12, 0))
        self.status = ttk.Label(prog, style="Muted.TLabel", anchor="w")
        self.status.pack(side="left", fill="x", expand=True)

        box = ttk.Frame(body)
        box.pack(fill="both", expand=True)
        tv = self.tv = ttk.Treeview(box, columns=("now", "size", "result"), selectmode="extended")
        for col, text, width, anchor in (("#0", "Game", 440, "w"), ("now", "Now", 130, "w"),
                                         ("size", "Size", 90, "e"), ("result", "", 260, "w")):
            tv.heading(col, text=text, anchor=anchor)
            tv.column(col, width=width, anchor=anchor, stretch=col in ("#0", "result"))
        sb = ttk.Scrollbar(box, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tv.pack(side="left", fill="both", expand=True)
        c = self.app.colors
        tv.tag_configure("skip", foreground=c["muted"])
        tv.tag_configure("done", foreground=c["keep"])
        tv.tag_configure("failed", foreground=c["move"])
        tv.bind("<<TreeviewSelect>>", lambda e: self._update_summary())

    def _save_opts(self):
        self.app.cfg["compress_verify"] = self.verify_var.get()
        self.app.cfg["compress_delete"] = self.delete_var.get()
        self.app.save_cfg()

    def fill(self):
        self.tv.delete(*self.tv.get_children())
        self.rows = {}
        skipped = []
        for key, jobs, why in compress.plan(self.system, self.app.units, self.app.exts):
            if jobs:
                self.rows[key] = jobs
                self.tv.insert("", "end", iid=key, text=key, values=(
                    ", ".join(dict.fromkeys(describe(j) for j in jobs)), human(sum(j.size for j in jobs)),
                    f"→ {FORMATS[self.ext]}" + (f" ({len(jobs)} discs)" if len(jobs) > 1 else "")))
            elif why not in ("nothing to compress",):
                skipped.append((key, why))
        for key, why in skipped:
            self.tv.insert("", "end", iid=key, text=key, values=("", "", why), tags=("skip",))
        self._update_summary()

    def chosen(self):
        sel = [k for k in self.tv.selection() if k in self.rows]
        return sel or [k for k in self.tv.get_children() if k in self.rows]

    def _update_summary(self):
        keys = self.chosen()
        size = sum(j.size for k in keys for j in self.rows[k])
        if not self.rows:
            self.summary.config(text="Nothing here to compress.")
        else:
            what = "selected" if [k for k in self.tv.selection() if k in self.rows] else "games"
            self.summary.config(text=f"{len(keys):,} selected  ·  {human(size)}" if what == "selected" else
                                f"{games(len(keys))}  ·  {human(size)}")
        if not self.busy:
            self.go_btn.config(text=f"Compress {games(len(keys))}" if keys else "Compress")
            self.go_btn.state(["!disabled"] if keys and self._tool_ready() else ["disabled"])

    # ---------- tools ----------
    def _find_tools(self):
        need = {compress.tool_name("rvz" if self.ext == ".rvz" else "cd")}

        def look():
            for name in need:
                self.box.put(("tool", (name, compress.find_tool(name))))
        threading.Thread(target=look, daemon=True).start()

    def _tool_ready(self):
        name = compress.tool_name("rvz" if self.ext == ".rvz" else "cd")
        return bool(self.tools.get(name))

    def _show_tool(self, name, tool):
        self.tools[name] = tool
        if tool:
            self.tool_lbl.config(text=f"Using {name} from {tool.where}.", foreground="")
        else:
            self.tool_lbl.config(text=f"{name} isn't installed, so nothing can be compressed yet. "
                                      f"{compress.INSTALL_HINT[name]}", foreground=self.app.colors["manual"])
        self._update_summary()

    # ---------- work ----------
    def start(self):
        if self.busy:
            self.cancel.set()
            self.go_btn.state(["disabled"])
            self.status.config(text="Stopping after the tool lets go …")
            return
        keys = self.chosen()
        if not keys or not self._tool_ready():
            return
        jobs = [(k, j) for k in keys for j in self.rows[k]]
        size = sum(j.size for _, j in jobs)
        delete = self.delete_var.get()
        holding = None if delete else os.path.join(self.app.holding_root(), "to_delete", self.system)
        if delete:
            where = "The originals are deleted once each new file is in place."
        else:
            where = f"The originals move to\n{holding}/\n"
            if self.app.holding_on_same_drive():
                where += "(on the same drive: the space comes back when you delete them there)."
        if not messagebox.askyesno(TITLE, f"Compress {games(len(keys))} ({human(size)})?\n\n{where}\n\n"
                                          "Big discs take a few minutes each.", parent=self.win):
            return
        self.busy = True
        self.cancel.clear()
        self.go_btn.config(text="Stop")
        tool = self.tools[compress.tool_name("rvz" if self.ext == ".rvz" else "cd")]
        ctx = {"gamelist": self.app.gamelist_path(), "holding": holding, "verify": self.verify_var.get(),
               "media": os.path.join(scraper.media_root(self.app.cfg["roms_root"]), self.system),
               "paths": {k: list(self.app.units[k]["paths"]) for k in keys}}
        threading.Thread(target=self._work, args=(jobs, tool, ctx), daemon=True).start()

    def _work(self, jobs, tool, ctx):
        box, total = self.box, len(jobs)
        done_keys, saved, moves, problems = [], 0, [], []
        running = scraper.es_de_running()
        try:
            for n, (key, job) in enumerate(jobs):
                if self.cancel.is_set():
                    break
                name = os.path.basename(job.out)
                box.put(("row", (key, "Compressing …", "")))
                free = compress.free_space(self.folder)
                if free is not None and free < job.size + 64 * 1024 ** 2:
                    box.put(("row", (key, f"Not enough free space ({human(free)} free)", "failed")))
                    problems.append(f"{name}: not enough free space on the drive ({human(free)} free, up to "
                                    f"{human(job.size)} needed)")
                    break

                def progress(stage, fraction, written, n=n, name=name):
                    word = "Checking" if stage == "check" else "Compressing"
                    detail = f"{fraction * 100:.0f}%" if fraction is not None else (
                        f"{human(written)} written" if written else "")
                    part = (fraction or 0) * (0.5 if ctx["verify"] else 1) + (0.5 if stage == "check" else 0)
                    box.put(("progress", (f"{word} {name}  {detail}".rstrip(), (n + min(part, 1)) / total)))
                try:
                    new_size = compress.convert(job, tool, progress, self.cancel.is_set, verify=ctx["verify"])
                except InterruptedError:
                    box.put(("row", (key, "Stopped", "")))
                    break
                except Exception as e:
                    box.put(("row", (key, str(e)[:200], "failed")))
                    problems.append(f"{name}: {str(e)[:200]}")
                    continue
                m, probs = compress.finish(job, self.folder, compress.playlists_for(job, ctx["paths"][key]),
                                           ctx["gamelist"], ctx["media"], ctx["holding"], running)
                moves += m
                problems += [f"{name}: {p}" for p in probs]
                saved += max(0, job.size - new_size)
                done_keys.append(key)
                box.put(("row", (key, f"Done · {human(new_size)} (saved {human(max(0, job.size - new_size))})",
                                 "done")))
        except Exception as e:  # something unexpected: say so rather than leave the window spinning
            problems.append(str(e)[:200])
        box.put(("done", {"keys": done_keys, "saved": saved, "moves": moves, "problems": problems,
                          "holding": ctx["holding"]}))

    def _poll(self):
        if not self.win.winfo_exists():
            return
        try:
            while True:
                kind, data = self.box.get_nowait()
                if kind == "tool":
                    self._show_tool(*data)
                elif kind == "progress":
                    text, fraction = data
                    self.status.config(text=text)
                    self.bar.config(value=int(fraction * 1000))
                elif kind == "row":
                    key, text, tag = data
                    if self.tv.exists(key):
                        self.tv.set(key, "result", text)
                        self.tv.item(key, tags=(tag,) if tag else ())
                        self.tv.see(key)
                elif kind == "done":
                    self._finished(data)
        except queue.Empty:
            pass
        self.poll_job = self.win.after(100, self._poll)

    def _finished(self, res):
        self.busy = False
        self.bar.config(value=0)
        n = len(dict.fromkeys(res["keys"]))
        if res["moves"]:
            self.app._log_moves({"time": datetime.datetime.now().isoformat(timespec="seconds"),
                                 "system": self.system, "dest": "to_delete", "games": n,
                                 "size": sum(compress._size(t) for _, t in res["moves"]), "moves": res["moves"],
                                 "why": "compressed"})
        stopped = self.cancel.is_set()
        if self.closing:
            self.app.rescan()
            self._destroy()
            if res["problems"]:
                messagebox.showerror(TITLE, "\n".join(res["problems"][:30]), parent=self.app.root)
            return
        self.status.config(text=("Stopped. " if stopped else "") +
                           (f"Compressed {games(n)}, saving {human(res['saved'])}." if n else
                            "Nothing was compressed."))
        results = {k: (self.tv.set(k, "result"), self.tv.item(k, "tags")) for k in self.tv.get_children()}
        self.app.rescan()
        self.fill()
        for k, (text, tags) in results.items():  # keep what happened on screen for the games still listed
            if self.tv.exists(k) and ("failed" in tags or "done" in tags):
                self.tv.set(k, "result", text)
                self.tv.item(k, tags=tags)
        if n:
            where = ("" if res["holding"] is None else " The originals are in the holding folder (Library → "
                     "Holding folder…).")
            self.app.toast(f"Compressed {games(n)}, saving {human(res['saved'])}.{where}")
        if res["problems"]:
            messagebox.showerror(TITLE, "\n".join(res["problems"][:30]), parent=self.win)

    def close(self):
        if self.busy:
            if not messagebox.askyesno(TITLE, "Stop compressing? The game being compressed now stays as it was.",
                                       parent=self.win):
                return
            self.cancel.set()
            self.closing = True  # what's finished still has to be logged: go when the worker has stopped
            self.win.withdraw()
            return
        self._destroy()

    def _destroy(self):
        if self.poll_job:
            try:
                self.win.after_cancel(self.poll_job)
            except tk.TclError:
                pass
        self.app.compress_window = None
        self.win.destroy()
