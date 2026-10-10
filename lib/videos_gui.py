"""Tools → Download gameplay videos…: fetch ScreenScraper's clips into ES-DE's videos folder for the games in the
list (see lib/screenscraper.py), with the user's own free ScreenScraper account."""
import os, queue, threading, webbrowser
import tkinter as tk
from tkinter import ttk, messagebox

import scraper
import screenscraper as ss
import video

TITLE = "Download gameplay videos"


def open_window(app):
    w = getattr(app, "videos_window", None)
    if w and w.win.winfo_exists():
        w.win.deiconify()
        w.win.lift()
        return w
    if not app.units:
        messagebox.showinfo(TITLE, "Pick a system with games first.")
        return None
    app.videos_window = VideosWindow(app)
    return app.videos_window


class VideosWindow:
    def __init__(self, app):
        self.app = app
        self.cancel = threading.Event()
        self.busy = False
        self.box = queue.Queue()
        selected = set(app.keep_tv.selection()) | set(app.move_tv.selection())
        self.scopes = [("Keeping list", list(app.kept)), ("All games", list(app.units)),
                       ("Selected rows", [k for k in app.units if k in selected])]
        self.mroot = scraper.media_root(app.cfg["roms_root"])
        win = self.win = tk.Toplevel(app.root)
        win.title(f"{TITLE} — {app.system}")
        win.transient(app.root)
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        win.protocol("WM_DELETE_WINDOW", self.close)
        body = ttk.Frame(win, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"Gameplay videos for {app.fullname or app.system}", style="Section.TLabel").pack(
            anchor="w")
        ttk.Label(body, text="Short clips from ScreenScraper, the community database ES-DE scrapes from. They go in "
                             "ES-DE's videos folder, so ES-DE plays them in its menus and RetroShelf in its details "
                             "panel. Games that already have a video are skipped.", style="Muted.TLabel",
                  wraplength=540, justify="left").pack(anchor="w", pady=(2, 12))

        acct = ttk.LabelFrame(body, text="Your ScreenScraper account", padding=(12, 8))
        acct.pack(fill="x")
        acct.columnconfigure(1, weight=1)
        self.user = tk.StringVar(value=app.cfg.get("ss_user", ""))
        self.password = tk.StringVar(value=app.cfg.get("ss_password", ""))
        ttk.Label(acct, text="Username").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(acct, textvariable=self.user).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(acct, text="Password").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(acct, textvariable=self.password, show="•").grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Button(acct, text="Create a free account ↗", command=lambda: webbrowser.open(ss.SIGNUP)).grid(
            row=0, column=2, rowspan=2, padx=(10, 0))
        ttk.Label(acct, text="Free, and needed for a useful daily allowance. Saved in config.json next to "
                             "RetroShelf (as ES-DE does).", style="Muted.TLabel", wraplength=520,
                  justify="left").grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

        self.dev = ss.dev_credentials(app.cfg)
        self.dev_id = tk.StringVar(value=app.cfg.get("ss_devid", ""))
        self.dev_pw = tk.StringVar(value=app.cfg.get("ss_devpassword", ""))
        if not self.dev:
            devf = ttk.LabelFrame(body, text="Developer ID", padding=(12, 8))
            devf.pack(fill="x", pady=(10, 0))
            devf.columnconfigure(1, weight=1)
            ttk.Label(devf, text="This copy of RetroShelf has no ScreenScraper developer ID (release downloads "
                                 "include one; a git checkout doesn't). Enter one ScreenScraper gave you:",
                      wraplength=520, justify="left").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
            ttk.Label(devf, text="ID").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
            ttk.Entry(devf, textvariable=self.dev_id).grid(row=1, column=1, sticky="ew", pady=2)
            ttk.Label(devf, text="Password").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=2)
            ttk.Entry(devf, textvariable=self.dev_pw, show="•").grid(row=2, column=1, sticky="ew", pady=2)

        scope_box = ttk.LabelFrame(body, text="Games", padding=(12, 8))
        scope_box.pack(fill="x", pady=(10, 0))
        self.scope = tk.IntVar(value=0)
        folder = ss.videos_dir(self.mroot, app.system)
        for i, (label, keys) in enumerate(self.scopes):
            have = sum(1 for k in keys if ss.has_video(folder, self._stem(k)))
            ttk.Radiobutton(scope_box, text=f"{label}  —  {len(keys):,} games, {have:,} with a video already",
                            variable=self.scope, value=i, state="normal" if keys else "disabled").pack(anchor="w",
                                                                                                    pady=1)
        if app.system not in ss.SYSTEM_IDS:
            ttk.Label(body, text=f"⚠ ScreenScraper has no system called “{app.system}”, so games are looked up by "
                                 "name alone and may not be found.", style="Move.TLabel", wraplength=540,
                      justify="left").pack(anchor="w", pady=(10, 0))
        if not video.backend()[0]:
            ttk.Label(body, text="To watch them inside RetroShelf, install mpv (on Steam Deck: from Discover) or "
                                 "ffmpeg. ES-DE plays them either way.", style="Muted.TLabel", wraplength=540,
                      justify="left").pack(anchor="w", pady=(10, 0))

        self.bar = ttk.Progressbar(body, mode="determinate")
        self.bar.pack(fill="x", pady=(14, 4))
        self.status = ttk.Label(body, style="Muted.TLabel", wraplength=540, justify="left")
        self.status.pack(anchor="w")
        foot = ttk.Frame(body, padding=(0, 12, 0, 0))
        foot.pack(fill="x")
        self.start_btn = ttk.Button(foot, text="Start", style="Accent.TButton", command=self.start)
        self.start_btn.pack(side="right")
        ttk.Button(foot, text="Close", command=self.close).pack(side="right", padx=(0, 6))

    def _stem(self, key):
        """ES-DE names a game's media after the file it lists for it."""
        return os.path.splitext(os.path.basename(scraper.primary_file(self.app.units[key]["paths"])))[0]

    def start(self):
        if self.busy:
            self.cancel.set()
            self.start_btn.config(state="disabled", text="Stopping…")
            return
        cfg = self.app.cfg
        cfg["ss_user"], cfg["ss_password"] = self.user.get().strip(), self.password.get()
        if not self.dev and self.dev_id.get().strip() and self.dev_pw.get():
            cfg["ss_devid"], cfg["ss_devpassword"] = self.dev_id.get().strip(), self.dev_pw.get()
        self.app.save_cfg()
        dev = ss.dev_credentials(cfg)
        if not dev:
            messagebox.showinfo(TITLE, "Enter a ScreenScraper developer ID first (or use a release download of "
                                       "RetroShelf, which has one).", parent=self.win)
            return
        keys = self.scopes[self.scope.get()][1]
        jobs = [(scraper.primary_file(self.app.units[k]["paths"]), self._stem(k)) for k in keys]
        if not jobs:
            return
        self.busy = True
        self.cancel.clear()
        self.start_btn.config(text="Stop")
        self.bar.config(maximum=len(jobs), value=0)
        args = (jobs, self.app.system, self.mroot, dev, cfg["ss_user"] or None, cfg["ss_password"] or None,
                lambda text, done, total: self.box.put(("progress", text, done)), self.cancel.is_set)

        def work():
            try:
                self.box.put(("done", ss.run(*args), None))
            except Exception as e:  # shown in the window
                self.box.put(("done", e, None))
        threading.Thread(target=work, daemon=True).start()
        self._poll()

    def _poll(self):
        if not self.win.winfo_exists():
            return
        while True:
            try:
                kind, a, b = self.box.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self.status.config(text=a)
                self.bar["value"] = b
            else:
                self._finished(a)
                return
        self.win.after(150, self._poll)

    def _finished(self, stats):
        self.busy = False
        self.start_btn.config(state="normal", text="Start")
        if isinstance(stats, Exception):
            self.status.config(text=f"Stopped: {stats}")
            return
        bits = [f"{stats['videos']:,} downloaded"]
        if stats["had"]:
            bits.append(f"{stats['had']:,} had one already")
        if stats["no_video"]:
            bits.append(f"{stats['no_video']:,} have no video on ScreenScraper")
        if stats["not_found"]:
            bits.append(f"{stats['not_found']:,} not found")
        if stats["failed"]:
            bits.append(f"{stats['failed']:,} failed ({stats.get('last_error', '')})")
        text = ", ".join(bits) + "."
        if stats["allowance"]:
            text += f"  Allowance: {stats['allowance']}."
        if stats["stopped"]:
            text = f"{stats['stopped']}\n\n{text}"
        self.status.config(text=text)
        self.bar["value"] = self.bar["maximum"]
        if stats["videos"]:
            self.app.toast(f"Downloaded {stats['videos']:,} gameplay video{'s' if stats['videos'] != 1 else ''}.")
            sel = self.app.keep_tv.selection() or self.app.move_tv.selection()
            if sel:  # play the selected game's new clip
                self.app._show_selected(self.app.keep_tv if self.app.keep_tv.selection() else self.app.move_tv)

    def close(self):
        if self.busy:
            if not messagebox.askyesno(TITLE, "Stop downloading videos?", parent=self.win):
                return
            self.cancel.set()
        self.app.videos_window = None
        self.win.destroy()
