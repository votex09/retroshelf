"""Homebrew Hub window: browse free Game Boy / GBC / GBA / NES homebrew and put it in your ROMs folder.

Open-source games install with one click. For the rest, Open on Homebrew Hub shows the game's page in your browser;
download it there and RetroShelf files it from your Downloads folder (see lib/homebrew.py for why)."""
import base64, os, queue, threading, urllib.request, webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import homebrew as hb
import scraper
import ui

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

WATCH_MS = 1500
SHOT_W, SHOT_H = 320, 288


def short_path(path):
    """The last two folders, so a long path can't crowd the window."""
    parts = os.path.normpath(path).split(os.sep)
    return path if len(parts) <= 3 else os.sep.join(["…"] + parts[-2:])


def open_window(app):
    """One Homebrew Hub window at a time: a second click brings the open one forward."""
    w = getattr(app, "homebrew_window", None)
    if w and w.win.winfo_exists():
        w.win.deiconify()
        w.win.lift()
        w.win.focus_force()
        return w
    app.homebrew_window = HomebrewWindow(app)
    return app.homebrew_window


class HomebrewWindow:
    def __init__(self, app):
        self.app = app
        self.roms_root = app.cfg["roms_root"]
        self.entries, self.shown, self.by_slug = [], [], {}
        self.shots = {}  # slug -> PhotoImage (or None when it couldn't load)
        self.selected = None
        self.watcher = hb.DownloadWatcher(self.dl_dir(), self.roms_root)
        start = next((p for p, s in hb.PLATFORMS.items() if s == app.system), "GB")

        win = self.win = tk.Toplevel(app.root)
        win.title("Homebrew Hub")
        win.transient(app.root)
        win.geometry("1150x800")
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        self._build(start)
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Escape>", lambda e: self.close())
        self.load()
        self.win.after(WATCH_MS, self._watch)

    # ---------- UI ----------
    def _build(self, platform):
        body = ttk.Frame(self.win, padding=16)
        body.pack(fill="both", expand=True)
        head = ttk.Frame(body)
        head.pack(fill="x")
        ttk.Label(head, text="Homebrew Hub  ·  free homebrew games", style="Section.TLabel").pack(side="left")
        ttk.Button(head, text="Refresh list", command=lambda: self.load(refresh=True)).pack(side="right")
        self.age_lbl = ttk.Label(head, style="Muted.TLabel")
        self.age_lbl.pack(side="right", padx=(0, 8))
        ttk.Label(body, text="Open-source games install with one click. For the others, Open on Homebrew Hub shows "
                             "the game's page in your browser: download it there and RetroShelf puts it in your ROMs "
                             "folder as soon as it lands in your Downloads folder.",
                  style="Muted.TLabel", wraplength=1080, justify="left").pack(anchor="w", pady=(2, 0))

        flt = ttk.Frame(body, padding=(0, 10, 0, 0))
        flt.pack(fill="x")
        self.platform = tk.StringVar(value=platform)
        names = [f"{p} — {hb.PLATFORM_NAMES[p]}" for p in hb.PLATFORMS]
        self.platform_cb = ttk.Combobox(flt, values=names, state="readonly", width=24)
        self.platform_cb.current(list(hb.PLATFORMS).index(platform))
        self.platform_cb.pack(side="left")
        self.platform_cb.bind("<<ComboboxSelected>>", lambda e: self._set_platform())
        self.kind = tk.StringVar(value="game")
        kind_cb = ttk.Combobox(flt, textvariable=self.kind, values=["all"] + hb.TYPES, state="readonly", width=9)
        kind_cb.pack(side="left", padx=(6, 0))
        kind_cb.bind("<<ComboboxSelected>>", lambda e: self.render())
        ttk.Label(flt, text="Search").pack(side="left", padx=(16, 8))
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *_: self.render())
        search = ttk.Entry(flt, textvariable=self.query)
        search.pack(side="left", fill="x", expand=True)
        search.focus_set()
        self.one_click = tk.BooleanVar(value=False)
        ttk.Checkbutton(flt, text="One-click only", variable=self.one_click,
                        command=self.render).pack(side="left", padx=(12, 0))
        self.hide_have = tk.BooleanVar(value=False)
        ttk.Checkbutton(flt, text="Hide ones I have", variable=self.hide_have,
                        command=self.render).pack(side="left", padx=(12, 0))

        foot = ttk.Frame(body, padding=(0, 10, 0, 0))
        foot.pack(side="bottom", fill="x")
        # buttons first: pack() hands out space in order, so a long path can't squeeze them
        self.install_btn = ttk.Button(foot, text="Install", style="Accent.TButton", command=self.install)
        self.install_btn.pack(side="right")
        self.open_btn = ttk.Button(foot, text="Open on Homebrew Hub ↗", command=self.open_page)
        self.open_btn.pack(side="right", padx=(0, 6))
        ttk.Label(foot, text="Downloads").pack(side="left")
        ttk.Button(foot, text="Change…", command=self.browse_dir).pack(side="left", padx=(8, 0))
        self.dir_lbl = ttk.Label(foot, text=short_path(self.dl_dir()), style="Muted.TLabel")
        self.dir_lbl.pack(side="left", padx=(8, 0))
        ui.Tooltip(self.dir_lbl, self.dl_dir)
        wait = ttk.Frame(body)
        wait.pack(side="bottom", fill="x", pady=(8, 0))
        self.stop_btn = ttk.Button(wait, text="Stop waiting", command=self.stop_waiting)
        self.wait_lbl = ttk.Label(wait, style="Muted.TLabel", anchor="w")
        self.wait_lbl.pack(side="left", fill="x", expand=True)
        self.status = ttk.Label(body, style="Muted.TLabel", anchor="w")
        self.status.pack(side="bottom", fill="x", pady=(8, 0))

        panes = ttk.PanedWindow(body, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=(10, 0))
        left = ttk.Frame(panes)
        self.res_lbl = ttk.Label(left, style="Muted.TLabel")
        self.res_lbl.pack(anchor="w", pady=(0, 4))
        f = ttk.Frame(left)
        f.pack(fill="both", expand=True)
        cols = (("dev", "Developer", 160, "w"), ("type", "Type", 65, "w"), ("license", "License", 105, "w"),
                ("status", "", 165, "w"))
        tv = self.tv = ttk.Treeview(f, columns=[c[0] for c in cols], selectmode="browse")
        tv.heading("#0", text="Title", anchor="w")
        tv.column("#0", width=300, minwidth=160, stretch=True)
        for col, text, width, anchor in cols:
            tv.heading(col, text=text, anchor=anchor)
            tv.column(col, width=width, minwidth=50, stretch=False, anchor=anchor)
        sb = ttk.Scrollbar(f, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tv.tag_configure("installed", foreground=self.app.colors["keep"])
        tv.tag_configure("waiting", foreground=self.app.colors["manual"])
        tv.bind("<<TreeviewSelect>>", lambda e: self._select())
        tv.bind("<Double-Button-1>", lambda e: self.install() if self._can_install() else self.open_page())
        tv.bind("<Return>", lambda e: self.install() if self._can_install() else self.open_page())
        panes.add(left, weight=3)

        right = ttk.Frame(panes, padding=(12, 0, 0, 0))
        self.pic = ttk.Label(right, anchor="center")
        self.pic.pack(fill="x")
        self.info = tk.Text(right, wrap="word", width=40, height=14, relief="flat", borderwidth=0,
                            highlightthickness=0, font=ttk.Style().lookup("TLabel", "font") or "TkDefaultFont")
        self.info.tag_configure("title", font=("TkDefaultFont", 12, "bold"))
        self.info.tag_configure("meta", foreground=self.app.colors["muted"])
        self.info.configure(bg=self.app.colors["field"], fg=self.app.colors["fg"], state="disabled")
        self.info.pack(fill="both", expand=True, pady=(8, 0))
        panes.add(right, weight=2)
        self._select()

    # ---------- options ----------
    def dl_dir(self):
        return self.app.cfg.get("homebrew_downloads") or hb.downloads_dir()

    def browse_dir(self):
        path = filedialog.askdirectory(initialdir=self.dl_dir(), title="Where your browser saves downloads",
                                       parent=self.win)
        if path:
            self.app.cfg["homebrew_downloads"] = path
            self.app.save_cfg()
            self.dir_lbl.config(text=short_path(path))
            waiting = self.watcher.waiting
            self.watcher = hb.DownloadWatcher(path, self.roms_root)
            for e in waiting:
                self.watcher.expect(e)

    def _set_platform(self):
        self.platform.set(list(hb.PLATFORMS)[self.platform_cb.current()])
        self.load()

    # ---------- catalogue ----------
    def _in_thread(self, work, done):
        box = queue.Queue()

        def run():
            try:
                box.put(work())
            except Exception as e:
                box.put(e)

        def poll():
            try:
                res = box.get_nowait()
            except queue.Empty:
                self.win.after(100, poll)
                return
            if self.win.winfo_exists():
                done(res)
        threading.Thread(target=run, daemon=True).start()
        poll()

    def load(self, refresh=False):
        platform = self.platform.get()
        self.status.config(text=f"Loading the {hb.PLATFORM_NAMES[platform]} list from Homebrew Hub …")

        def done(res):
            if isinstance(res, Exception):
                self.status.config(text=f"Couldn't load the list: {res}")
                return
            if platform != self.platform.get():
                return  # switched while loading
            self.entries = res
            self.by_slug = {e["slug"]: e for e in res}
            age = hb.cached_age(platform)
            self.age_lbl.config(text="" if age is None else "list from today" if age < 1 else
                                f"list from {int(age)} day{'s' if age >= 2 else ''} ago")
            self.status.config(text="")
            self.render()
        self._in_thread(lambda: hb.load_catalog(platform, refresh), done)

    def _status_of(self, e):
        if any(w["slug"] == e["slug"] for w in self.watcher.waiting):
            return "Waiting"
        if hb.installed_path(e, self.roms_root):
            return "Installed"
        return "" if hb.can_download(e) else "via website"

    def render(self):
        q = self.query.get().lower().strip()
        kind = self.kind.get()
        shown = []
        for e in self.entries:
            if kind != "all" and (e.get("typetag") or "game") != kind:
                continue
            if q and q not in (e.get("title") or "").lower() and q not in hb.developer_text(e.get("developer")).lower():
                continue
            if self.one_click.get() and not hb.can_download(e):
                continue
            if self.hide_have.get() and hb.installed_path(e, self.roms_root):
                continue
            if e.get("nsfw"):
                continue
            shown.append(e)
        shown.sort(key=lambda e: (e.get("title") or e["slug"]).lower())
        self.shown = shown
        keep = self.tv.selection()
        self.tv.delete(*self.tv.get_children())
        for e in shown:
            status = self._status_of(e)
            tags = ("installed",) if status == "Installed" else ("waiting",) if status.startswith("Waiting") else ()
            self.tv.insert("", "end", iid=e["slug"], text=e.get("title") or e["slug"],
                           values=(hb.developer_text(e.get("developer")), e.get("typetag") or "",
                                   hb.license_text(e), status), tags=tags)
        if keep and self.tv.exists(keep[0]):
            self.tv.selection_set(keep)
        one = sum(hb.can_download(e) for e in shown)
        self.res_lbl.config(text=f"{len(shown):,} shown  ·  {one:,} one-click installs")
        self._select()

    # ---------- details ----------
    def _select(self):
        sel = self.tv.selection()
        e = self.selected = self.by_slug.get(sel[0]) if sel else None
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        if not e:
            self.info.insert("end", "Pick a game to see its details.", "meta")
            self.pic.configure(image="", text="")
        else:
            bits = [b for b in (hb.developer_text(e.get("developer")), str(e.get("date") or "")[:4],
                                hb.license_text(e)) if b]
            self.info.insert("end", (e.get("title") or e["slug"]) + "\n", "title")
            self.info.insert("end", "  ·  ".join(bits) + "\n\n", "meta")
            self.info.insert("end", (e.get("description") or "No description.").strip())
            if not hb.can_download(e):
                self.info.insert("end", "\n\nThe author hasn't allowed apps to download this one: use Open on "
                                        "Homebrew Hub and download it from the game's page.", "meta")
            self._show_shot(e)
        self.info.configure(state="disabled")
        self.install_btn.state(["!disabled" if self._can_install() else "disabled"])
        self.open_btn.state(["!disabled" if e else "disabled"])

    def _show_shot(self, e):
        slug = e["slug"]
        if slug in self.shots:
            img = self.shots[slug]
            self.pic.configure(image=img or "", text="" if img else "No screenshot")
            return
        url = hb.screenshot_url(e)
        if not url:
            self.shots[slug] = None
            self.pic.configure(image="", text="No screenshot")
            return
        self.pic.configure(image="", text="Loading screenshot …")

        def fetch():
            req = urllib.request.Request(url, headers={"User-Agent": hb.USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read(4 << 20)

        def done(data):
            img = None
            if not isinstance(data, Exception):
                try:
                    img = self._photo(data)
                except Exception:
                    img = None
            self.shots[slug] = img
            if self.selected and self.selected["slug"] == slug:
                self.pic.configure(image=img or "", text="" if img else "No screenshot")
        self._in_thread(fetch, done)

    def _photo(self, data):
        if Image:
            import io
            with Image.open(io.BytesIO(data)) as im:
                im = im.convert("RGBA")
                scale = max(1, min(SHOT_W // max(im.width, 1), SHOT_H // max(im.height, 1)))  # crisp pixel art
                im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
                im.thumbnail((SHOT_W, SHOT_H))
                return ImageTk.PhotoImage(im)
        img = tk.PhotoImage(data=base64.b64encode(data).decode("ascii"))  # PNG / GIF without Pillow
        zoom = max(1, min(SHOT_W // max(img.width(), 1), SHOT_H // max(img.height(), 1)))
        return img.zoom(zoom) if zoom > 1 else img

    # ---------- getting games ----------
    def _can_install(self):
        e = self.selected
        return bool(e and hb.can_download(e) and not hb.installed_path(e, self.roms_root))

    def _entry_details(self, e):
        """The search list may leave out files; fetch the full manifest when it does."""
        return e if e.get("files") else dict(e, **hb.load_entry(e["slug"]))

    def install(self):
        e = self.selected
        if not self._can_install():
            return
        self.install_btn.state(["disabled"])
        self.status.config(text=f"Downloading {e.get('title')} …")
        self._in_thread(lambda: hb.install(self._entry_details(e), self.roms_root),
                        lambda res: self._filed(e, res))

    def open_page(self):
        e = self.selected
        if not e:
            return
        webbrowser.open(hb.page_url(e))
        if hb.installed_path(e, self.roms_root):
            return  # just looking
        try:
            full = self._entry_details(e)  # so the watcher knows the file name Homebrew Hub will serve
        except Exception:
            full = e
        self.watcher.expect(full)
        self._show_waiting()
        self.render()

    def stop_waiting(self):
        self.watcher.cancel()
        self._show_waiting()
        self.render()

    def _show_waiting(self):
        w = self.watcher.waiting
        if w:
            names = ", ".join(e.get("title") or e["slug"] for e in w[:3]) + (f" +{len(w) - 3}" if len(w) > 3 else "")
            self.wait_lbl.config(text=f"Waiting for {names} to land in {short_path(self.watcher.folder)}")
            self.stop_btn.pack(side="right", before=self.wait_lbl)
        else:
            self.wait_lbl.config(text="")
            self.stop_btn.pack_forget()

    def _watch(self):
        if not self.win.winfo_exists():
            return
        for entry, res in self.watcher.poll():
            self._filed(entry, res)
        self._show_waiting()
        self.win.after(WATCH_MS, self._watch)

    def _filed(self, e, res):
        """A ROM landed in roms/<system> (or failed to): add ES-DE metadata, tell the user, refresh the lists."""
        if isinstance(res, Exception):
            self.status.config(text=f"{e.get('title')}: {res}")
            messagebox.showerror("Couldn't add the game", f"{e.get('title')}:\n{res}", parent=self.win)
            self.render()
            return
        system = hb.PLATFORMS[hb.entry_platform(e)]
        note = self._add_metadata(e, res, system)
        self.status.config(text=f"Added {os.path.basename(res)} to roms/{system}{note}")
        self.app.toast(f"Added {e.get('title')} to roms/{system}.")
        if self.app.system == system:
            self.app.rescan()
        self.render()

    def _add_metadata(self, e, rom, system):
        """Homebrew Hub's description, developer and first screenshot for ES-DE, where nothing is there yet."""
        if scraper.es_de_running():
            return " (close ES-DE and rescrape to add its description)"
        name = os.path.basename(rom)
        try:
            gamelist = scraper.gamelist_path(self.roms_root, system)
            scraper.write_gamelist(gamelist, {name: hb.es_de_fields(e)}, lambda m: None)
            url = hb.screenshot_url(e)
            folder = os.path.join(scraper.media_root(self.roms_root), system, "screenshots")
            stem, ext = os.path.splitext(name)[0], os.path.splitext(url or "")[1].lower() or ".png"
            if url and not scraper.has_media(folder, stem):
                os.makedirs(folder, exist_ok=True)
                scraper.download(url, os.path.join(folder, stem + ext))
            return " with its description and screenshot"
        except Exception as ex:
            return f" (metadata not added: {ex})"

    def close(self):
        if self.watcher.waiting and not messagebox.askyesno(
                "Still waiting", "RetroShelf is still waiting for downloads to put in your ROMs folder. Close anyway?",
                parent=self.win):
            return
        self.app.homebrew_window = None
        self.win.destroy()
