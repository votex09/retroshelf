"""Tools → Library health check: lists what lib/health.py finds, grouped by kind, and fixes what can be fixed."""
import os, queue, threading
import tkinter as tk
from tkinter import ttk, messagebox

import health
import ui
from frontend import human_size as human

TITLE = "Library health check"


def open_window(app):
    w = getattr(app, "health_window", None)
    if w and w.win.winfo_exists():
        w.win.deiconify()
        w.win.lift()
        return w
    if not app.cfg.get("roms_root"):
        messagebox.showinfo(TITLE, "Pick your ROMs folder first (or set up RetroDECK / ES-DE from Tools).")
        return None
    w = app.health_window = HealthWindow(app)
    return w


class HealthWindow:
    def __init__(self, app):
        self.app = app
        self.roms_root = app.cfg["roms_root"]
        self.problems = {}  # tree id -> Problem
        self.box = queue.Queue()
        self.busy = False
        self.cancel = threading.Event()
        self.poll_job = None

        win = self.win = tk.Toplevel(app.root)
        win.title(TITLE)
        win.transient(app.root)
        scale = max(1.0, app.root.winfo_fpixels("1i") / 96)
        win.geometry(f"{min(round(1080 * scale), app.root.winfo_screenwidth())}x"
                     f"{min(round(680 * scale), app.root.winfo_screenheight() - 80)}")
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
        ttk.Label(body, text="Things that stop games starting (sheets and playlists naming files that aren't there, "
                             "disc images without their .cue), and things that take space for nothing (empty "
                             "files, unfinished downloads, artwork, videos and gamelist entries for games that are "
                             "gone). Nothing changes until you press Fix.",
                  style="Muted.TLabel", wraplength=1020, justify="left").pack(anchor="w", pady=(2, 10))

        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Look at").pack(side="left")
        current = self.app.system
        self.scopes = ["All systems"] + ([f"{self.app.fullname or current} ({current})"] if current else [])
        self.scope = ttk.Combobox(bar, state="readonly", width=40, values=self.scopes)
        self.scope.current(0)
        self.scope.pack(side="left", padx=(8, 0))
        self.scope.bind("<<ComboboxSelected>>", lambda e: self.scan())
        self.rescan_btn = ttk.Button(bar, text="Look again", command=self.scan)
        self.rescan_btn.pack(side="left", padx=(6, 0))

        foot = ttk.Frame(body, padding=(0, 10, 0, 0))
        foot.pack(side="bottom", fill="x")
        ttk.Button(foot, text="Close", command=self.close).pack(side="right")
        self.fix_btn = ttk.Button(foot, text="Fix", style="Accent.TButton", command=self.fix)
        self.fix_btn.pack(side="right", padx=(0, 6))
        ui.Tooltip(self.fix_btn, "Fixes the selected problems that can be fixed, or all of them when nothing is "
                                 "selected. It says what it will do first.")
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
        tv = self.tv = ttk.Treeview(box, columns=("system", "detail", "fix"), selectmode="extended")
        for col, text, width, stretch in (("#0", "Problem", 330, True), ("system", "System", 110, False),
                                          ("detail", "", 430, True), ("fix", "Fix", 150, False)):
            tv.heading(col, text=text, anchor="w")
            tv.column(col, width=width, anchor="w", stretch=stretch)
        sb = ttk.Scrollbar(box, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tv.pack(side="left", fill="both", expand=True)
        c = self.app.colors
        tv.tag_configure("group", font="SunValleyBodyStrongFont")
        tv.tag_configure("nofix", foreground=c["muted"])
        tv.tag_configure("fixed", foreground=c["keep"])
        tv.tag_configure("failed", foreground=c["move"])
        tv.bind("<<TreeviewSelect>>", lambda e: self._update_summary())

    # ---------- scanning ----------
    def scan(self):
        if self.busy:
            return
        only = None if self.scope.current() == 0 else {self.app.system}
        self.busy = True
        self.cancel.clear()
        self.rescan_btn.state(["disabled"])
        self.fix_btn.state(["disabled"])
        self.status.config(text="Looking …")

        def work():
            try:
                found = health.scan(self.roms_root, only, lambda t, f: self.box.put(("progress", (t, f))),
                                    self.cancel.is_set)
                self.box.put(("found", found))
            except InterruptedError:
                self.box.put(("found", None))
            except Exception as e:
                self.box.put(("error", str(e)[:300]))
        threading.Thread(target=work, daemon=True).start()

    def show(self, found):
        tv = self.tv
        tv.delete(*tv.get_children())
        self.problems = {}
        groups = {}
        for p in found:
            if p.kind not in groups:
                groups[p.kind] = tv.insert("", "end", text=health.HEADINGS[p.kind], open=True, tags=("group",))
            iid = tv.insert(groups[p.kind], "end", text=p.name, values=(p.system, p.detail, p.fix or "—"),
                            tags=() if p.fix else ("nofix",))
            self.problems[iid] = p
        for kind, gid in groups.items():
            n = len(tv.get_children(gid))
            tv.item(gid, text=f"{health.HEADINGS[kind]}  ({n:,})")
        fixable = sum(1 for p in found if p.fix)
        self.status.config(text=("Nothing wrong found." if not found else
                                 f"{len(found):,} problem{'s' if len(found) != 1 else ''} found, {fixable:,} that "
                                 "RetroShelf can fix."))
        self._update_summary()

    # ---------- fixing ----------
    def chosen(self):
        sel = set()
        for iid in self.tv.selection():
            if iid in self.problems:
                sel.add(iid)
            else:  # a group: everything in it
                sel.update(self.tv.get_children(iid))
        ids = sel or set(self.problems)
        return [i for i in self.problems if i in ids and self.problems[i].fix
                and "fixed" not in self.tv.item(i, "tags")]

    def _update_summary(self):
        ids = self.chosen()
        if self.busy:
            return
        self.fix_btn.state(["!disabled"] if ids else ["disabled"])
        self.fix_btn.config(text=f"Fix {len(ids):,}" if ids else "Fix")
        freed = sum(self.problems[i].size for i in ids if self.problems[i].kind in ("media", "leftover"))
        self.summary.config(text=(f"{len(ids):,} to fix" + (f"  ·  frees {human(freed)}" if freed else ""))
                            if ids else "")

    def fix(self):
        ids = self.chosen()
        if not ids or self.busy:
            return
        lines, deletes = [], 0
        for kind, heading in health.KINDS:
            mine = [self.problems[i] for i in ids if self.problems[i].kind == kind]
            if not mine:
                continue
            what = mine[0].fix.lower()
            lines.append(f"• {heading}: {len(mine):,} ({what})")
            if kind in ("media", "leftover", "empty"):
                deletes += sum(len(p.paths) for p in mine)
        note = (f"\n\n{deletes:,} files are deleted for good (artwork and videos can be scraped again)."
                if deletes else "")
        if not messagebox.askyesno(TITLE, "Fix these?\n\n" + "\n".join(lines) + note, parent=self.win):
            return
        failed = []
        touched = set()
        for i in ids:
            p = self.problems[i]
            try:
                done = health.fix(p, self.roms_root)
                self.tv.set(i, "fix", "Done")
                self.tv.set(i, "detail", done[:1].upper() + done[1:])
                self.tv.item(i, tags=("fixed",))
                touched.add(p.system)
            except (OSError, RuntimeError) as e:
                self.tv.set(i, "fix", "Failed")
                self.tv.item(i, tags=("failed",))
                failed.append(f"{p.system}/{p.name}: {e}")
        if self.app.system in touched:
            self.app.rescan()
        n = len(ids) - len(failed)
        self.status.config(text=f"Fixed {n:,} problem{'s' if n != 1 else ''}."
                           + (f" {len(failed):,} couldn't be fixed." if failed else ""))
        if n:
            self.app.toast(f"Library health check: fixed {n:,} problem{'s' if n != 1 else ''}.")
        self._update_summary()
        if failed:
            messagebox.showerror(TITLE, "\n".join(failed[:30]), parent=self.win)

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
                self.rescan_btn.state(["!disabled"])
                if kind == "found" and data is not None:
                    self.show(data)
                elif kind == "error":
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
        self.app.health_window = None
        self.win.destroy()
