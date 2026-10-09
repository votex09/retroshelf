"""Set up RetroDECK (Linux) or ES-DE (Windows) for someone who doesn't have it yet: pick where games go, install,
and point RetroShelf at the new ROMs folder (see lib/frontend.py for how each install works)."""
import os, queue, threading, webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import frontend
from fsutil import is_windows

POLL_MS = 2000


def title():
    return "Set up ES-DE" if is_windows() else "Set up RetroDECK"


def open_window(app):
    w = getattr(app, "setup_window", None)
    if w and w.win.winfo_exists():
        w.win.deiconify()
        w.win.lift()
        return w
    app.setup_window = SetupWindow(app)
    return app.setup_window


class SetupWindow:
    def __init__(self, app):
        self.app = app
        self.windows = is_windows()
        self.name = "ES-DE" if self.windows else "RetroDECK"
        self.cancel = threading.Event()
        self.busy = False
        self.poll_job = None
        win = self.win = tk.Toplevel(app.root)
        win.title(title())
        win.transient(app.root)
        win.geometry("760x620")
        win.configure(bg=ttk.Style().lookup("TFrame", "background"))
        win.protocol("WM_DELETE_WINDOW", self.close)
        self.body = None
        self.choose_page()

    # ---------- pages ----------
    def _page(self, heading, text=""):
        if self.body:
            self.body.destroy()
        self.body = ttk.Frame(self.win, padding=20)
        self.body.pack(fill="both", expand=True)
        ttk.Label(self.body, text=heading, style="Section.TLabel").pack(anchor="w")
        if text:
            ttk.Label(self.body, text=text, style="Muted.TLabel", wraplength=700, justify="left").pack(
                anchor="w", pady=(4, 12))
        self.foot = ttk.Frame(self.body)
        self.foot.pack(side="bottom", fill="x", pady=(12, 0))
        return self.body

    def choose_page(self):
        found = (frontend.esde_installs(self.app.cfg.get("esde_bases", ())) if self.windows
                 else [r for r in [frontend.retrodeck_roms()] if r])
        if self.windows:
            intro = ("ES-DE is the game menu you play from. RetroShelf downloads its official portable version "
                     "(about 160 MB) into the folder you pick, with your games in its ROMs folder. ES-DE doesn't "
                     "include emulators: once it's set up, add the ones you want (RetroShelf shows you where).")
        else:
            intro = ("RetroDECK is the game menu you play from, with its emulators included. RetroShelf installs it "
                     "from Flathub for your user (a download of a few GB, no password needed), then starts its "
                     "first-time setup, which puts a retrodeck folder (games, BIOS, saves) where you choose.")
        body = self._page(f"Set up {self.name}", intro)

        if found:
            box = ttk.Frame(body)
            box.pack(fill="x", pady=(0, 12))
            ttk.Label(box, text=f"{self.name} is already set up here:\n{found[0]}", justify="left").pack(
                side="left")
            ttk.Button(box, text="Use this folder", style="Accent.TButton",
                       command=lambda: self.finish(found[0], [])).pack(side="right")

        if not self.windows and not frontend.flatpak():
            ttk.Label(body, text="Flatpak isn't installed, and RetroDECK needs it. Flathub's guide shows the one "
                                 "command for your Linux distribution; then come back and press Check again.",
                      wraplength=700, justify="left").pack(anchor="w", pady=(0, 8))
            ttk.Button(self.foot, text="Check again", command=self.choose_page).pack(side="right")
            ttk.Button(self.foot, text="Open Flathub's setup guide ↗",
                       command=lambda: webbrowser.open(frontend.FLATPAK_SETUP)).pack(side="right", padx=(0, 6))
            self._have_roms_button()
            return

        ttk.Label(body, text="Where should your games go?").pack(anchor="w")
        self.choice = tk.StringVar()
        self.custom = None
        self.places = {}
        grid = ttk.Frame(body)
        grid.pack(fill="x", pady=(6, 0))
        for i, (kind, label, folder) in enumerate(frontend.storage_choices()):
            key = f"{kind}:{folder}"
            self.places[key] = (kind, folder)
            ttk.Radiobutton(grid, text=label, value=key, variable=self.choice,
                            command=self._update_target).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Label(grid, text=f"{frontend.human_size(frontend.free_bytes(folder))} free",
                      style="Muted.TLabel").grid(row=i, column=1, sticky="w", padx=(16, 0))
            ttk.Label(grid, text=folder, style="Muted.TLabel").grid(row=i, column=2, sticky="w", padx=(16, 0))
        row = len(self.places)
        ttk.Radiobutton(grid, text="Another folder…", value="custom", variable=self.choice,
                        command=self._pick_custom).grid(row=row, column=0, sticky="w", pady=2)
        self.custom_lbl = ttk.Label(grid, style="Muted.TLabel")
        self.custom_lbl.grid(row=row, column=1, columnspan=2, sticky="w", padx=(16, 0))
        self.choice.set(next(iter(self.places)))
        self.target_lbl = ttk.Label(body, wraplength=700, justify="left")
        self.target_lbl.pack(anchor="w", pady=(14, 0))
        self.shortcut = tk.BooleanVar(value=True)
        if self.windows:
            ttk.Checkbutton(body, text="Add ES-DE to the Start menu", variable=self.shortcut).pack(
                anchor="w", pady=(10, 0))
        self.install_btn = ttk.Button(self.foot, text="Install", style="Accent.TButton", command=self.start)
        self.install_btn.pack(side="right")
        ttk.Button(self.foot, text="Cancel", command=self.close).pack(side="right", padx=(0, 6))
        self._have_roms_button()
        self._update_target()

    def _have_roms_button(self):
        def pick():
            self.close()
            self.app.browse_roms()
        ttk.Button(self.foot, text="I already have a ROMs folder…", command=pick).pack(side="left")

    def _pick_custom(self):
        path = filedialog.askdirectory(parent=self.win, title="Where should your games go?",
                                       initialdir=os.path.expanduser("~"))
        if path:
            self.custom = os.path.normpath(path)
            self.custom_lbl.config(text=f"{frontend.human_size(frontend.free_bytes(path))} free   {self.custom}")
        elif not self.custom:
            self.choice.set(next(iter(self.places)))
        self._update_target()

    def selected(self):
        """-> (kind, folder) the user picked."""
        c = self.choice.get()
        if c == "custom":
            return ("custom", self.custom) if self.custom else next(iter(self.places.values()))
        return self.places[c]

    def _update_target(self):
        kind, folder = self.selected()
        self.target_lbl.config(text=f"Your games will go in:  {frontend.games_folder(kind, folder)}")

    # ---------- installing ----------
    def _progress_page(self, heading):
        body = self._page(heading)
        self.bar = ttk.Progressbar(body, mode="indeterminate")
        self.bar.pack(fill="x", pady=(8, 8))
        self.bar.start(15)
        self.status = ttk.Label(body, style="Muted.TLabel", wraplength=700, justify="left")
        self.status.pack(anchor="w")
        self.log = tk.Text(body, height=14, wrap="none", relief="flat", font=(self.app.mono, 9))
        self.log.configure(bg=self.app.colors["field"], fg=self.app.colors["fg"], state="disabled")
        self.log.pack(fill="both", expand=True, pady=(8, 0))
        ttk.Button(self.foot, text="Cancel", command=self.close).pack(side="right")

    def _log(self, line):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def start(self):
        kind, folder = self.selected()
        if kind == "home" and folder:
            try:
                os.makedirs(folder, exist_ok=True)  # Windows: ~\Games
            except OSError:
                pass
        if not folder or not os.path.isdir(folder) or not os.access(folder, os.W_OK):
            messagebox.showerror(title(), f"RetroShelf can't write to {folder}. Pick another place.", parent=self.win)
            return
        self.kind, self.folder = kind, folder
        self.add_shortcut = self.shortcut.get()  # read here: Tk variables can't be read from the install thread
        self._progress_page(f"Installing {self.name} …")
        work = self._install_esde if self.windows else self._install_retrodeck
        self._run(work, self._installed)

    def _run(self, work, done):
        """work(report) runs in a thread; report(line=None, fraction=None) updates the page; done(result)."""
        box = queue.Queue()
        self.busy = True

        def report(line=None, fraction=None):
            box.put(("report", line, fraction))

        def run():
            try:
                box.put(("done", work(report), None))
            except Exception as e:  # shown on the page
                box.put(("done", e, None))

        def poll():
            if not self.win.winfo_exists():
                return
            while True:
                try:
                    kind, a, b = box.get_nowait()
                except queue.Empty:
                    break
                if kind == "done":
                    self.busy = False
                    done(a)
                    return
                if a:
                    self._log(a)
                    self.status.config(text=a[:200])
                if b is not None:
                    if str(self.bar.cget("mode")) != "determinate":
                        self.bar.stop()
                        self.bar.config(mode="determinate", maximum=1000)
                    self.bar["value"] = int(b * 1000)
            self.win.after(100, poll)
        threading.Thread(target=run, daemon=True).start()
        poll()

    def _install_retrodeck(self, report):
        if frontend.retrodeck_installed():
            report("RetroDECK is already installed.")
            return None
        frontend.install_retrodeck(report, self.cancel.is_set)
        return None

    def _install_esde(self, report):
        base = self.folder
        if os.path.exists(frontend.esde_exe(base)):
            report(f"ES-DE is already in {frontend.esde_dir(base)}: using it.")
        else:
            report("Finding ES-DE's latest version …")
            version, pkg = frontend.esde_release()
            report(f"Downloading ES-DE {version} ({pkg['filename']}) …")
            zpath = os.path.join(base, pkg["filename"])
            last = [-1]

            def progress(done, total):
                if total and int(done * 100 / total) != last[0]:
                    last[0] = int(done * 100 / total)
                    report(None, done / total)
            frontend.download(pkg["url"], zpath, pkg.get("md5"), progress, self.cancel.is_set)
            report("Unpacking …")
            try:
                frontend.unpack_esde(zpath, base)
            finally:
                os.unlink(zpath)
        report("Creating a folder for each system …")
        roms = frontend.create_system_dirs(base)
        notes = []
        if self.add_shortcut:
            try:
                frontend.add_esde_shortcut(base)
                notes.append("ES-DE is in your Start menu.")
            except OSError as e:
                notes.append(f"Couldn't add ES-DE to the Start menu: {e}")
        return roms, notes

    def _installed(self, res):
        if isinstance(res, Exception):
            self.bar.stop()
            if isinstance(res, InterruptedError):
                return
            self.status.config(text=f"Setup stopped: {res}")
            self._log(f"Error: {res}")
            ttk.Button(self.foot, text="Back", command=self.choose_page).pack(side="right", padx=(0, 6))
            return
        if self.windows:
            roms, notes = res
            if self.folder not in self.app.cfg["esde_bases"]:
                self.app.cfg["esde_bases"].append(self.folder)
            self.finish(roms, notes)
        else:
            self.first_run_page()

    # ---------- RetroDECK's own first-time setup ----------
    def first_run_page(self):
        steps = frontend.retrodeck_steps(self.kind, self.folder)
        body = self._page("RetroDECK's first-time setup",
                          "RetroDECK is installed and now runs its own setup in a new window. It asks where to put "
                          "its data, so answer it like this:")
        for i, s in enumerate(steps, 1):
            ttk.Label(body, text=f"{i}.  {s}", wraplength=680, justify="left").pack(anchor="w", pady=3)
        ttk.Label(body, text="Then answer its other questions as you like. When it finishes it opens the game menu; "
                             "RetroShelf picks up the new ROMs folder by itself.", style="Muted.TLabel",
                  wraplength=700, justify="left").pack(anchor="w", pady=(10, 0))
        self.status = ttk.Label(body, text="Waiting for RetroDECK's setup to finish …")
        self.status.pack(anchor="w", pady=(16, 0))
        if self.kind != "home":
            ttk.Button(self.foot, text="Copy folder", command=self._copy_folder).pack(side="left")
            self._copy_folder()
        ttk.Button(self.foot, text="Cancel", command=self.close).pack(side="right")
        ttk.Button(self.foot, text="Start RetroDECK again", command=self._launch).pack(side="right", padx=(0, 6))
        self._launch()
        self._wait_for_retrodeck()

    def _copy_folder(self):
        self.win.clipboard_clear()
        self.win.clipboard_append(self.folder)

    def _launch(self):
        try:
            frontend.launch_retrodeck()
        except OSError as e:
            self.status.config(text=f"Couldn't start RetroDECK: {e}")

    def _wait_for_retrodeck(self):
        self.poll_job = None
        if not self.win.winfo_exists():
            return
        roms = frontend.retrodeck_roms()
        if not roms:
            self.poll_job = self.win.after(POLL_MS, self._wait_for_retrodeck)
            return
        expected = frontend.games_folder(self.kind, self.folder)
        notes = [] if os.path.normpath(roms) == os.path.normpath(expected) else [
            "RetroDECK put its folder somewhere else than planned, so RetroShelf uses where it went."]
        self.finish(roms, notes)

    # ---------- done ----------
    def finish(self, roms, notes):
        if self.poll_job:
            self.win.after_cancel(self.poll_job)
            self.poll_job = None
        self.app.cfg["setup_offered"] = True
        self.app.load_roms_root(roms)
        self.app.save_cfg()
        body = self._page(f"{self.name} is set up")
        ttk.Label(body, text=f"Your games go in:\n{roms}", justify="left").pack(anchor="w")
        tips = list(notes)
        if self.windows:
            tips.append(f"Next, add emulators: put them in {os.path.join(os.path.dirname(roms), 'Emulators')} "
                        "(for example RetroArch) or install them normally. ES-DE's user guide lists which one each "
                        "system uses.")
        else:
            tips.append("Put BIOS files in the bios folder next to roms; RetroDECK's Configurator can check them.")
        tips.append("Add games with Tools → Homebrew Hub, itch.io, PDRoms or free arcade games, or copy your own "
                    "dumps into the system folders.")
        for t in tips:
            ttk.Label(body, text="•  " + t, wraplength=700, justify="left").pack(anchor="w", pady=(8, 0))
        ttk.Button(self.foot, text="Close", style="Accent.TButton", command=self.close).pack(side="right")
        if self.windows:
            ttk.Button(self.foot, text="ES-DE user guide ↗",
                       command=lambda: webbrowser.open(frontend.ESDE_GUIDE)).pack(side="right", padx=(0, 6))
        self.app.toast(f"{self.name} is set up. Games go in {roms}.")

    def close(self):
        if self.busy:
            if not messagebox.askyesno(title(), f"Stop setting up {self.name}?", parent=self.win):
                return
            self.cancel.set()
        if self.poll_job:
            self.win.after_cancel(self.poll_job)
        self.app.cfg["setup_offered"] = True
        self.app.save_cfg()
        self.app.setup_window = None
        self.win.destroy()
