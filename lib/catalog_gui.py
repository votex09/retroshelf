"""A window for browsing a site's homebrew and getting games into roms/<system>/ (Homebrew Hub, itch.io).

Each site is a "source" object (see homebrew_gui.HomebrewSource and itch_gui.ItchSource) that lists entries and
says how to show them. Games the source may fetch itself install with one click; the rest open in the user's browser,
where they download them, and the Downloads watcher (lib/downloads.py) files what lands there."""
import base64, io, os, queue, threading, urllib.request, webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import downloads
import scraper
import ui

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

WATCH_MS = 1500
SHOT_W, SHOT_H = 320, 288
USER_AGENT = "RetroShelf/1.0 (+https://github.com/votex09/retroshelf)"


def short_path(path):
    """The last two folders, so a long path can't crowd the window."""
    parts = os.path.normpath(path).split(os.sep)
    return path if len(parts) <= 3 else os.sep.join(["…"] + parts[-2:])


def open_window(app, source):
    """One window per source: a second click brings the open one forward."""
    w = getattr(app, source.window_attr, None)
    if w and w.win.winfo_exists():
        w.win.deiconify()
        w.win.lift()
        w.win.focus_force()
        return w
    w = CatalogWindow(app, source)
    setattr(app, source.window_attr, w)
    return w


class CatalogWindow:
    def __init__(self, app, source):
        self.app, self.src = app, source
        self.roms_root = app.cfg["roms_root"]
        self.entries, self.shown, self.by_key = [], [], {}
        self.shots = {}  # key -> PhotoImage (or None when it couldn't load)
        self.selected = None
        self.watcher = downloads.DownloadWatcher(self.dl_dir(), self.roms_root)

        win = self.win = tk.Toplevel(app.root)
        win.title(source.name)
        win.transient(app.root)
        win.geometry("1150x800")
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        self._build(source.default_code(app.system))
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Escape>", lambda e: self.close())
        self.load()
        self.win.after(WATCH_MS, self._watch)

    # ---------- UI ----------
    def _build(self, code):
        src = self.src
        body = ttk.Frame(self.win, padding=16)
        body.pack(fill="both", expand=True)
        head = ttk.Frame(body)
        head.pack(fill="x")
        ttk.Label(head, text=src.heading, style="Section.TLabel").pack(side="left")
        ttk.Button(head, text="Refresh list", command=lambda: self.load(refresh=True)).pack(side="right")
        self.age_lbl = ttk.Label(head, style="Muted.TLabel")
        self.age_lbl.pack(side="right", padx=(0, 8))
        ttk.Label(body, text=src.note, style="Muted.TLabel", wraplength=1080, justify="left").pack(
            anchor="w", pady=(2, 0))

        flt = ttk.Frame(body, padding=(0, 10, 0, 0))
        flt.pack(fill="x")
        self.codes = [c for c, _ in src.systems]
        self.code = code
        self.system_cb = ttk.Combobox(flt, values=[label for _, label in src.systems], state="readonly", width=26)
        self.system_cb.current(self.codes.index(code))
        self.system_cb.pack(side="left")
        self.system_cb.bind("<<ComboboxSelected>>", lambda e: self._set_system())
        self.kind = tk.StringVar(value=src.default_kind)
        if src.kinds:
            kind_cb = ttk.Combobox(flt, textvariable=self.kind, values=["all"] + src.kinds, state="readonly", width=9)
            kind_cb.pack(side="left", padx=(6, 0))
            kind_cb.bind("<<ComboboxSelected>>", lambda e: self.render())
        ttk.Label(flt, text="Search").pack(side="left", padx=(16, 8))
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *_: self.render())
        search = ttk.Entry(flt, textvariable=self.query)
        search.pack(side="left", fill="x", expand=True)
        search.focus_set()
        self.one_click = tk.BooleanVar(value=False)
        if src.one_click:
            ttk.Checkbutton(flt, text="One-click only", variable=self.one_click,
                            command=self.render).pack(side="left", padx=(12, 0))
        self.hide_have = tk.BooleanVar(value=False)
        ttk.Checkbutton(flt, text="Hide ones I have", variable=self.hide_have,
                        command=self.render).pack(side="left", padx=(12, 0))

        foot = ttk.Frame(body, padding=(0, 10, 0, 0))
        foot.pack(side="bottom", fill="x")
        # buttons first: pack() hands out space in order, so a long path can't squeeze them
        self.install_btn = ttk.Button(foot, text="Install", style="Accent.TButton", command=self.install)
        if src.one_click:
            self.install_btn.pack(side="right")
        self.open_btn = ttk.Button(foot, text=src.open_label, command=self.open_page,
                                   style="TButton" if src.one_click else "Accent.TButton")
        self.open_btn.pack(side="right", padx=(0, 6) if src.one_click else 0)
        if src.browse_label:
            browse = ttk.Button(foot, text=src.browse_label, command=self.browse_site)
            browse.pack(side="right", padx=(0, 6))
            ui.Tooltip(browse, lambda: f"Opens {src.name} in your browser. Every {self.system_label()} ROM you "
                                       f"download there is put in roms/{src.system_for(self.code)}.")
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
        self.status = ttk.Label(body, style="Muted.TLabel", anchor="w", wraplength=1080, justify="left")
        self.status.pack(side="bottom", fill="x", pady=(8, 0))

        panes = ttk.PanedWindow(body, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=(10, 0))
        left = ttk.Frame(panes)
        self.res_lbl = ttk.Label(left, style="Muted.TLabel")
        self.res_lbl.pack(anchor="w", pady=(0, 4))
        f = ttk.Frame(left)
        f.pack(fill="both", expand=True)
        cols = (("dev", "Developer", 160, "w"), ("type", "Type", 65, "w"), ("license", src.license_header, 105, "w"),
                ("status", "", 165, "w"))
        tv = self.tv = ttk.Treeview(f, columns=[c[0] for c in cols], selectmode="browse")
        tv.heading("#0", text="Title", anchor="w")
        tv.column("#0", width=300, minwidth=160, stretch=True)
        for col, text, width, anchor in cols:
            tv.heading(col, text=text, anchor=anchor)
            tv.column(col, width=width, minwidth=50, stretch=False, anchor=anchor)
        if not src.kinds:
            tv["displaycolumns"] = ("dev", "license", "status")  # no types to show
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

    def system_label(self):
        return dict(self.src.systems)[self.code]

    # ---------- options ----------
    def dl_dir(self):
        return self.app.cfg.get("homebrew_downloads") or downloads.downloads_dir()

    def browse_dir(self):
        path = filedialog.askdirectory(initialdir=self.dl_dir(), title="Where your browser saves downloads",
                                       parent=self.win)
        if path:
            self.app.cfg["homebrew_downloads"] = path
            self.app.save_cfg()
            self.dir_lbl.config(text=short_path(path))
            waiting = self.watcher.waiting
            self.watcher = downloads.DownloadWatcher(path, self.roms_root)
            for w in waiting:
                self.watcher.expect(w)

    def _set_system(self):
        self.code = self.codes[self.system_cb.current()]
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
        code = self.code
        self.status.config(text=f"Loading the {self.system_label()} list from {self.src.name} …")

        def done(res):
            if code != self.code:
                return  # switched while loading
            if isinstance(res, Exception):
                self.entries, self.by_key = [], {}
                self.status.config(text=self.src.load_error(res, code))
                self.render()
                return
            self.entries = res
            self.by_key = {self.src.key(e): e for e in res}
            age = self.src.cached_age(code)
            self.age_lbl.config(text="" if age is None else "list from today" if age < 1 else
                                f"list from {int(age)} day{'s' if age >= 2 else ''} ago")
            self.status.config(text="")
            self.render()
        self._in_thread(lambda: self.src.load(code, refresh), done)

    def _waiting_for(self, e):
        return any(w["id"] == self.src.key(e) for w in self.watcher.waiting)

    def _status_of(self, e):
        if self._waiting_for(e):
            return "Waiting"
        if self.src.installed_path(e, self.roms_root):
            return "Installed"
        return "" if self.src.can_download(e) or not self.src.one_click else "via website"

    def render(self):
        src, q, kind = self.src, self.query.get().lower().strip(), self.kind.get()
        shown = []
        for e in self.entries:
            if src.kinds and kind != "all" and src.kind(e) != kind:
                continue
            if q and q not in src.title(e).lower() and q not in src.developer(e).lower():
                continue
            if self.one_click.get() and not src.can_download(e):
                continue
            if self.hide_have.get() and src.installed_path(e, self.roms_root):
                continue
            if src.hidden(e):
                continue
            shown.append(e)
        shown.sort(key=lambda e: src.title(e).lower())
        self.shown = shown
        keep = self.tv.selection()
        self.tv.delete(*self.tv.get_children())
        for e in shown:
            status = self._status_of(e)
            tags = ("installed",) if status == "Installed" else ("waiting",) if status == "Waiting" else ()
            self.tv.insert("", "end", iid=src.key(e), text=src.title(e),
                           values=(src.developer(e), src.kind(e), src.license(e), status), tags=tags)
        if keep and self.tv.exists(keep[0]):
            self.tv.selection_set(keep)
        text = f"{len(shown):,} shown"
        if src.one_click:
            text += f"  ·  {sum(src.can_download(e) for e in shown):,} one-click installs"
        self.res_lbl.config(text=text)
        self._select()

    # ---------- details ----------
    def _select(self):
        src = self.src
        sel = self.tv.selection()
        e = self.selected = self.by_key.get(sel[0]) if sel else None
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        if not e:
            self.info.insert("end", "Pick a game to see its details.", "meta")
            self.pic.configure(image="", text="")
        else:
            bits = [b for b in (src.developer(e), src.year(e), src.license(e)) if b]
            self.info.insert("end", src.title(e) + "\n", "title")
            self.info.insert("end", "  ·  ".join(bits) + "\n\n", "meta")
            self.info.insert("end", src.description(e) or "No description.")
            if src.one_click and not src.can_download(e):
                self.info.insert("end", f"\n\nThe author hasn't allowed apps to download this one: use "
                                        f"{src.open_label.rstrip(' ↗')} and download it from the game's page.", "meta")
            self._show_shot(e)
        self.info.configure(state="disabled")
        self.install_btn.state(["!disabled" if self._can_install() else "disabled"])
        self.open_btn.state(["!disabled" if e else "disabled"])

    def _show_shot(self, e):
        key = self.src.key(e)
        if key in self.shots:
            img = self.shots[key]
            self.pic.configure(image=img or "", text="" if img else "No screenshot")
            return
        url = self.src.screenshot_url(e)
        if not url:
            self.shots[key] = None
            self.pic.configure(image="", text="No screenshot")
            return
        self.pic.configure(image="", text="Loading screenshot …")

        def fetch():
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read(4 << 20)

        def done(data):
            img = None
            if not isinstance(data, Exception):
                try:
                    img = self._photo(data)
                except Exception:
                    img = None
            self.shots[key] = img
            if self.selected and self.src.key(self.selected) == key:
                self.pic.configure(image=img or "", text="" if img else "No screenshot")
        self._in_thread(fetch, done)

    def _photo(self, data):
        if Image:
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
        return bool(self.src.one_click and e and self.src.can_download(e)
                    and not self.src.installed_path(e, self.roms_root))

    def install(self):
        e = self.selected
        if not self._can_install():
            return
        self.install_btn.state(["disabled"])
        self.status.config(text=f"Downloading {self.src.title(e)} …")
        self._in_thread(lambda: self.src.install(e, self.roms_root),
                        lambda res: self._filed(self.src.want(e), res))

    def open_page(self):
        e = self.selected
        if not e:
            return
        webbrowser.open(self.src.page_url(e))
        if self.src.installed_path(e, self.roms_root):
            return  # just looking
        self.watcher.expect(self.src.want(e))
        self._show_waiting()
        self.render()

    def browse_site(self):
        """Browse the site freely: any ROM for this system that lands in Downloads is filed."""
        webbrowser.open(self.src.browse_url(self.code))
        self.watcher.expect(self.src.browse_want(self.code))
        self._show_waiting()

    def stop_waiting(self):
        self.watcher.cancel()
        self._show_waiting()
        self.render()

    def _show_waiting(self):
        w = self.watcher.waiting
        if w:
            names = ", ".join(x["title"] for x in w[:3]) + (f" +{len(w) - 3}" if len(w) > 3 else "")
            self.wait_lbl.config(text=f"Waiting for {names} to land in {short_path(self.watcher.folder)}")
            self.stop_btn.pack(side="right", before=self.wait_lbl)
        else:
            self.wait_lbl.config(text="")
            self.stop_btn.pack_forget()

    def _watch(self):
        if not self.win.winfo_exists():
            return
        for want, res in self.watcher.poll():
            self._filed(want, res)
        self._show_waiting()
        self.win.after(WATCH_MS, self._watch)

    def _filed(self, want, res):
        """A ROM landed in roms/<system> (or failed to): add ES-DE metadata, tell the user, refresh the lists."""
        if isinstance(res, Exception):
            self.status.config(text=f"{want['title']}: {res}")
            messagebox.showerror("Couldn't add the game", f"{want['title']}:\n{res}", parent=self.win)
            self.render()
            return
        system, item = want["system"], want.get("item")
        note = self._add_metadata(item, res, system) if item else ""
        self.status.config(text=f"Added {os.path.basename(res)} to roms/{system}{note}")
        self.app.toast(f"Added {os.path.splitext(os.path.basename(res))[0]} to roms/{system}.")
        if self.app.system == system:
            self.app.rescan()
        self.render()

    def _add_metadata(self, e, rom, system):
        """The site's description, developer and screenshot for ES-DE, where nothing is there yet."""
        if scraper.es_de_running():
            return " (close ES-DE and rescrape to add its description)"
        name = os.path.basename(rom)
        try:
            scraper.write_gamelist(scraper.gamelist_path(self.roms_root, system),
                                   {name: self.src.es_de_fields(e)}, lambda m: None)
            url = self.src.screenshot_url(e)
            folder = os.path.join(scraper.media_root(self.roms_root), system, "screenshots")
            stem = os.path.splitext(name)[0]
            ext = os.path.splitext(url.split("?")[0])[1].lower() if url else ""
            if url and not scraper.has_media(folder, stem):
                os.makedirs(folder, exist_ok=True)
                scraper.download(url, os.path.join(folder, stem + (ext if len(ext) <= 5 and ext else ".png")))
            return " with its description and screenshot"
        except Exception as ex:
            return f" (metadata not added: {ex})"

    def close(self):
        if self.watcher.waiting and not messagebox.askyesno(
                "Still waiting", "RetroShelf is still waiting for downloads to put in your ROMs folder. Close anyway?",
                parent=self.win):
            return
        setattr(self.app, self.src.window_attr, None)
        self.win.destroy()
