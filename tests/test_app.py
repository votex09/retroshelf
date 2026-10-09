"""End-to-end: the real RetroShelf window on the sandbox library (see sandbox.py), driven through its own methods
and buttons. Needs tkinter and a display; tests/run.sh supplies a virtual one with xvfb-run."""
import base64, importlib.util, io, json, os, shutil, sys, tempfile, time, unittest, zipfile
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
import sandbox  # noqa: E402

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError as e:
    raise unittest.SkipTest(f"no tkinter: {e}")
if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    raise unittest.SkipTest("no display (run tests/run.sh, which uses xvfb-run)")

LIB_MODULES = ["sv_ttk", "launchbox", "nps", "nps_gui", "scraper", "desktop", "details", "ui", "updater", "fsutil",
               "homebrew", "homebrew_gui", "downloads", "catalog_gui", "itch", "itch_gui", "pdroms",
               "pdroms_gui", "mamedev", "mamedev_gui", "frontend", "setup_gui"]
SNES_N = len(sandbox.SNES_GAMES)
SPORTS = "Sports"


def widgets(w):
    yield w
    for c in w.winfo_children():
        yield from widgets(c)


def button(win, text):
    return next(b for b in widgets(win) if isinstance(b, ttk.Button) and b.cget("text") == text)


def zip_bytes(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in members.items():
            z.writestr(n, d)
    return buf.getvalue()


class AppTest(unittest.TestCase):
    """One sandbox (app copy + LaunchBox cache) for the class; library, config and logs are reset per test."""

    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="retroshelf-test-")
        sandbox.build(cls.base)
        cls.env = mock.patch.dict(os.environ, sandbox.env(cls.base))
        cls.env.start()
        # import the sandbox copy, with its own lib/ modules (their paths are fixed when they're imported)
        cls.saved = {n: sys.modules.pop(n) for n in LIB_MODULES if n in sys.modules}
        cls.saved_path = list(sys.path)
        spec = importlib.util.spec_from_file_location("retroshelf_sandbox",
                                                      os.path.join(cls.base, "RetroShelf", "retroshelf.py"))
        cls.rs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.rs)

    @classmethod
    def tearDownClass(cls):
        for n in LIB_MODULES:
            sys.modules.pop(n, None)
        sys.modules.update(cls.saved)
        sys.path[:] = cls.saved_path
        cls.env.stop()
        shutil.rmtree(cls.base, ignore_errors=True)

    def setUp(self):
        self.p = sandbox.reset(self.base)
        self.snes = os.path.join(self.p["roms"], "snes")
        self.mb = mock.patch.multiple(self.rs.messagebox, askyesno=mock.DEFAULT, showerror=mock.DEFAULT,
                                      showinfo=mock.DEFAULT, showwarning=mock.DEFAULT)
        self.boxes = self.mb.start()
        self.boxes["askyesno"].return_value = True
        self.app = self.start()

    def tearDown(self):
        self.close()
        self.mb.stop()

    def start(self):
        self.root = tk.Tk(className="retroshelf")
        app = self.rs.App(self.root)
        self.root.update()
        return app

    def close(self):
        if self.root:
            for job in self.root.tk.splitlist(self.root.tk.call("after", "info")):  # debounces, toasts
                self.root.after_cancel(job)
            self.app._close()
            self.root = None

    def restart(self):
        self.close()
        self.app = self.start()

    def preset(self, name, on=True):
        self.app.preset_vars[name].set(on)
        self.app.refresh()

    def cfg(self):
        with open(os.path.join(self.p["app"], "config.json"), encoding="utf-8") as f:
            return json.load(f)

    def assertNoErrors(self):
        self.boxes["showerror"].assert_not_called()

    # ---------- tests ----------
    def test_loads_library_with_launchbox_data(self):
        a = self.app
        self.assertEqual(a.system, "snes")
        self.assertEqual(len(a.units), SNES_N)  # readme.txt isn't a game; the .part is
        self.assertEqual(a.platform, sandbox.SNES)
        self.assertEqual(a.ratings["Final_Fantasy_III_USA"]["n"], "Final Fantasy III")
        self.assertEqual(a.ratings["Zelda no Densetsu (Japan)"]["n"], "The Legend of Zelda: A Link to the Past")
        self.assertEqual(a.played, {"Bebe's Kids (USA)"})
        self.assertEqual(a.to_move, [])

    def test_multi_file_games_are_one_unit(self):
        self.app.load_system("psx")
        self.root.update()
        units = self.app.units
        self.assertEqual(len(units), 2)
        self.assertEqual(len(units["Castlevania - Symphony of the Night (USA)"]["paths"]), 3)
        self.assertEqual(len(units["Final Fantasy VII (USA)"]["paths"]), 3)
        self.assertEqual(self.app.platform, sandbox.PSX)

    def test_presets_ratings_and_played_protection(self):
        a = self.app
        self.preset("Junk (demo/kiosk/beta/proto/unl)")
        self.assertEqual(set(a.to_move), {"Star Fox (USA) (Beta)", "Donkey Kong Country (USA) (Demo) (Kiosk)",
                                          "Obscure Homebrew (World) (Unl)"})
        self.preset("Junk (demo/kiosk/beta/proto/unl)", False)
        a.use_rating.set(True)
        a.refresh()
        self.assertEqual(set(a.to_move), {"Barbie - Super Model (USA)"})  # Bebe's Kids (1.2) was played
        self.assertEqual(a.why["Bebe's Kids (USA)"], "played")
        a.protect_played.set(False)
        a.refresh()
        self.assertEqual(set(a.to_move), {"Barbie - Super Model (USA)", "Bebe's Kids (USA)"})

    def test_patterns_and_keep_rules(self):
        a = self.app
        a.pat_text.insert("1.0", "chrono\n!*(USA)*\n# comment")
        a.refresh()
        self.assertEqual(a.to_move, ["Chrono Trigger (Japan)"])
        self.assertEqual(a.why["Chrono Trigger (USA)"], "!*(USA)*")

    def test_region_dupes_preset(self):
        self.preset(self.rs.DUPES)
        self.assertEqual(set(self.app.to_move), {"Chrono Trigger (Japan)", "Super Metroid (Europe) (En,Fr,De)"})

    def test_move_then_restore(self):
        a = self.app
        self.preset(SPORTS)
        a.execute()
        self.assertNoErrors()
        held = os.path.join(self.p["holding"], "to_delete", "snes")
        self.assertEqual(sorted(os.listdir(held)), ["Madden NFL '94 (USA).sfc", "NBA Jam (USA) (Rev 1).sfc"])
        self.assertEqual(len(a.units), SNES_N - 2)
        with open(os.path.join(self.p["app"], "moves.json"), encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)[0]["moves"]), 2)

        a.restore_dialog()
        win = self.root.winfo_children()[-1]
        tv = next(w for w in widgets(win) if isinstance(w, ttk.Treeview))
        tv.selection_set(tv.get_children()[0])
        button(win, "Restore selected").invoke()
        self.assertNoErrors()
        self.assertTrue(os.path.exists(os.path.join(self.snes, "NBA Jam (USA) (Rev 1).sfc")))
        self.assertFalse(os.path.exists(held))  # emptied folders are pruned
        self.assertEqual(len(a.units), SNES_N)

    def test_keep_flips_survive_a_move(self):
        a = self.app
        self.preset(SPORTS)
        a.manual["Madden NFL '94 (USA)"] = False  # flipped back to keep by hand
        a.refresh()
        self.assertEqual(a.to_move, ["NBA Jam (USA) (Rev 1)"])
        a.execute()
        self.assertEqual(a.manual, {"Madden NFL '94 (USA)": False})
        self.assertIn("Madden NFL '94 (USA)", a.kept)
        self.assertEqual(a.to_move, [])

    def test_per_system_state_is_remembered(self):
        a = self.app
        self.preset(SPORTS)
        a.pat_text.insert("1.0", "zelda")
        a.refresh()
        a.load_system("psx")
        self.assertEqual(a.pat_text.get("1.0", "end").strip(), "")
        self.restart()  # back on psx, the last system used
        self.assertEqual(self.app.system, "psx")
        self.app.load_system("snes")
        self.assertEqual(self.app.pat_text.get("1.0", "end").strip(), "zelda")
        self.assertTrue(self.app.preset_vars[SPORTS].get())
        self.assertEqual(self.cfg()["system_state"]["snes"]["patterns"], "zelda")

    def test_unreadable_config_is_set_aside(self):
        self.close()
        cfg = os.path.join(self.p["app"], "config.json")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write('{"roms_root": "/somewhere", "system_st')  # cut off mid-write
        self.app = self.start()
        with open(cfg + ".bad", encoding="utf-8") as f:
            self.assertIn("/somewhere", f.read())
        self.assertEqual(self.app.cfg["roms_root"], os.path.realpath(self.p["roms"]))  # found next to the app
        self.assertFalse(any(n.endswith(".tmp") for n in os.listdir(self.p["app"])))

    def test_default_holding_folder_sits_next_to_roms(self):
        a = self.app
        a.cfg["holding_root"] = ""
        for roms in (self.p["roms"], self.p["roms"] + os.sep):  # a trailing separator mustn't put it inside roms
            a.cfg["roms_root"] = roms
            self.assertEqual(a.holding_root(), os.path.join(os.path.dirname(self.p["roms"]), "pruned"))

    def test_window_fits_the_screen(self):
        self.assertLessEqual(self.root.winfo_width(), self.root.winfo_screenwidth())
        self.assertLessEqual(self.root.winfo_height(), self.root.winfo_screenheight())

    def test_nopaystation_window_on_windows(self):
        """Windows mode: missing RPCS3 is reported, and picking its folder fixes that and is remembered."""
        nps, nps_gui = sys.modules["nps"], sys.modules["nps_gui"]
        rows = [{"id": "NPUB30133", "name": "Braid", "region": "US", "kind": "Games", "console": "PS3",
                 "size": 1 << 20, "content_id": "UP0001-NPUB30133_00-BRAID0000000001", "rap": "NOT REQUIRED",
                 "url": "http://example.invalid/braid.pkg", "zrif": "", "sha256": "", "sha1": "", "subtype": "",
                 "version": "0"}]
        self.addCleanup(nps.emulator_dirs.clear)
        with mock.patch.object(nps, "is_windows", return_value=True), \
                mock.patch.object(nps_gui, "is_windows", return_value=True), \
                mock.patch.object(nps.shutil, "which", return_value=None), \
                mock.patch.object(nps, "load_list", return_value=rows), \
                mock.patch.object(nps_gui.filedialog, "askdirectory") as ask:
            self.app.load_system("ps3")  # listed even without a folder, so it can be filled
            w = nps_gui.open_window(self.app)
            self.root.update()
            self.assertIn("RPCS3 wasn't found", w.fw_lbl.cget("text"))
            rpcs3 = os.path.join(self.base, "Emulators", "RPCS3")
            os.makedirs(rpcs3, exist_ok=True)
            open(os.path.join(rpcs3, "rpcs3.exe"), "w").close()
            ask.return_value = rpcs3
            button(w.win, "Emulators…").invoke()
            self.root.update()
            self.assertIn("firmware", w.fw_lbl.cget("text"))  # found now; firmware is the next thing missing
            self.assertEqual(self.cfg()["emulator_dirs"], {"rpcs3": os.path.normpath(rpcs3)})
            w.close()

    def test_homebrew_hub_window(self):
        """One-click install for an open-source game, and filing a game the user downloads in their browser."""
        hb, hbg, scraper = sys.modules["homebrew"], sys.modules["homebrew_gui"], sys.modules["scraper"]
        cg = sys.modules["catalog_gui"]
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0g"
                               "AAAABJRU5ErkJggg==")  # 1x1 PNG
        game = {"filename": "game.gb", "playable": True, "default": True}
        entries = [
            {"slug": "open", "title": "Open Racer", "platform": "GB", "typetag": "game", "gameLicense": "MIT",
             "developer": "Ann", "date": "2020-05-01", "description": "Fast.", "screenshots": ["s.png"],
             "basepath": "database", "files": [game]},
            {"slug": "closed", "title": "Closed Quest", "platform": "GB", "typetag": "game", "developer": "Bo",
             "screenshots": [], "basepath": "database", "files": [game]},
            {"slug": "nsfw", "title": "Hidden", "platform": "GB", "nsfw": True, "files": [game]},
        ]

        class Resp(io.BytesIO):
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else req
            return Resp(png if url.endswith(".png") else b"GB ROM")

        downloads = os.path.join(self.base, "home", "Downloads")
        os.makedirs(downloads, exist_ok=True)
        self.app.cfg["homebrew_downloads"] = downloads
        opened = []
        with mock.patch.object(hb, "load_catalog", return_value=entries), \
                mock.patch.object(hb.urllib.request, "urlopen", side_effect=fake_urlopen), \
                mock.patch.object(scraper, "es_de_running", return_value=False), \
                mock.patch.object(cg.webbrowser, "open", side_effect=opened.append):
            w = hbg.open_window(self.app)
            self.pump(lambda: w.entries)
            self.assertEqual(w.tv.get_children(), ("closed", "open"))  # sorted, NSFW left out
            self.assertEqual(w.tv.set("closed", "status"), "via website")

            w.tv.selection_set("open")
            self.pump(lambda: "open" in w.shots)
            self.assertIn("Fast.", w.info.get("1.0", "end"))
            self.assertIsNotNone(w.shots["open"])
            self.assertNotIn("disabled", button(w.win, "Install").state())
            button(w.win, "Install").invoke()
            rom = os.path.join(self.p["roms"], "gb", "Open Racer (Homebrew).gb")
            self.pump(lambda: os.path.exists(rom))
            self.pump(lambda: w.tv.set("open", "status") == "Installed")
            gamelist = scraper.gamelist_path(self.p["roms"], "gb")
            with open(gamelist, encoding="utf-8") as f:
                text = f.read()
            self.assertIn("<desc>Fast.</desc>", text)
            self.assertIn("<releasedate>20200501T000000</releasedate>", text)
            shot = os.path.join(scraper.media_root(self.p["roms"]), "gb", "screenshots", "Open Racer (Homebrew).png")
            self.assertTrue(os.path.exists(shot))

            w.tv.selection_set("closed")
            self.root.update()
            self.assertIn("disabled", button(w.win, "Install").state())
            button(w.win, "Open on Homebrew Hub ↗").invoke()
            self.assertEqual(opened, ["https://hh.gbdev.io/game/closed"])
            self.assertEqual(w.tv.set("closed", "status"), "Waiting")
            with open(os.path.join(downloads, "game.gb"), "wb") as f:  # the user's browser saves it
                f.write(b"GB ROM")
            w._watch()
            w._watch()
            self.assertTrue(os.path.exists(os.path.join(self.p["roms"], "gb", "Closed Quest (Homebrew).gb")))
            self.assertFalse(os.path.exists(os.path.join(downloads, "game.gb")))
            self.assertEqual(w.watcher.waiting, [])
            w.close()

    def test_itch_window(self):
        """Blocked feed: Browse on itch.io files any ROM. Listed game: Open on itch.io files it under its title."""
        itch, cg, scraper = sys.modules["itch"], sys.modules["catalog_gui"], sys.modules["scraper"]
        downloads = os.path.join(self.base, "home", "Downloads")
        os.makedirs(downloads, exist_ok=True)
        self.app.cfg["homebrew_downloads"] = downloads
        opened = []
        game = {"url": "https://gee.itch.io/tiny-quest", "title": "Tiny Quest", "author": "gee", "image": "",
                "description": "A small quest.", "year": "2021", "price": "", "system": "nes"}
        with mock.patch.object(itch, "load_catalog", side_effect=itch.Blocked("itch.io turned the request away")), \
                mock.patch.object(scraper, "es_de_running", return_value=False), \
                mock.patch.object(cg.webbrowser, "open", side_effect=opened.append):
            self.app.system = "nes"  # the window opens on the system being looked at
            w = sys.modules["itch_gui"].open_window(self.app)
            self.pump(lambda: "turned the request away" in w.status.cget("text"))
            self.assertIn("Browse on itch.io still works", w.status.cget("text"))
            self.assertEqual(w.tv.get_children(), ())
            button(w.win, "Browse on itch.io ↗").invoke()
            self.assertEqual(opened, ["https://itch.io/games/price-free/tag-nes"])
            with open(os.path.join(downloads, "space_blaster.nes"), "wb") as f:
                f.write(b"NES")
            w._watch()
            w._watch()
            self.assertTrue(os.path.exists(os.path.join(self.p["roms"], "nes", "space blaster (Homebrew).nes")))
            self.assertEqual([x["id"] for x in w.watcher.waiting], ["any:nes"])  # still browsing

            itch.load_catalog.side_effect, itch.load_catalog.return_value = None, [game]
            button(w.win, "Refresh list").invoke()
            self.pump(lambda: w.tv.get_children() == (game["url"],))
            self.assertEqual(w.tv.item(game["url"], "text"), "Tiny Quest")
            w.tv.selection_set(game["url"])
            self.root.update()
            self.assertIn("A small quest.", w.info.get("1.0", "end"))
            button(w.win, "Open on itch.io ↗").invoke()
            self.assertEqual(opened[-1], "https://gee.itch.io/tiny-quest")
            with open(os.path.join(downloads, "tinyquest-1.1.nes"), "wb") as f:
                f.write(b"NES2")
            w._watch()
            w._watch()
            self.assertTrue(os.path.exists(os.path.join(self.p["roms"], "nes", "Tiny Quest (Homebrew).nes")))
            with open(scraper.gamelist_path(self.p["roms"], "nes"), encoding="utf-8") as f:
                self.assertIn("<desc>A small quest.</desc>", f.read())
            self.assertEqual(w.tv.set(game["url"], "status"), "Installed")
            w.watcher.cancel()
            w.close()

    def test_pdroms_window(self):
        """Details load when a game is picked; Open on PDRoms files the download with them."""
        pdroms, cg, scraper = sys.modules["pdroms"], sys.modules["catalog_gui"], sys.modules["scraper"]
        downloads = os.path.join(self.base, "home", "Downloads")
        os.makedirs(downloads, exist_ok=True)
        self.app.cfg["homebrew_downloads"] = downloads
        url = "https://pdroms.de/files/nintendo-game-boy-gb-gbc/alpha-wing"
        game = {"url": url, "title": "Alpha Wing", "added": "2007", "thumb": "", "system": "gb"}
        opened = []
        with mock.patch.object(pdroms, "load_catalog", return_value=[game]), \
                mock.patch.object(pdroms, "load_details",
                                  return_value={"author": "kedo", "description": "A shooter.", "image": ""}), \
                mock.patch.object(scraper, "es_de_running", return_value=False), \
                mock.patch.object(cg.webbrowser, "open", side_effect=opened.append):
            self.app.system = "gb"  # the window opens on the system being looked at
            w = sys.modules["pdroms_gui"].open_window(self.app)
            self.pump(lambda: w.tv.get_children() == (url,))
            self.assertEqual(w.tv.set(url, "license"), "2007")
            w.tv.selection_set(url)
            self.pump(lambda: "A shooter." in w.info.get("1.0", "end"))
            self.assertIn("kedo", w.info.get("1.0", "end"))
            pdroms.load_details.assert_called_once()
            button(w.win, "Open on PDRoms ↗").invoke()
            self.assertEqual(opened, [url])
            with open(os.path.join(downloads, "alpha_wing.zip"), "wb") as f:
                f.write(zip_bytes({"alpha.gb": b"GB", "readme.txt": b"hi"}))
            w._watch()
            w._watch()
            rom = os.path.join(self.p["roms"], "gb", "Alpha Wing (Homebrew).gb")
            self.assertTrue(os.path.exists(rom))
            with open(scraper.gamelist_path(self.p["roms"], "gb"), encoding="utf-8") as f:
                text = f.read()
            self.assertIn("<desc>A shooter.</desc>", text)
            self.assertIn("<developer>kedo</developer>", text)
            button(w.win, "Browse on PDRoms ↗").invoke()
            self.assertEqual(opened[-1], "https://pdroms.de/system/nintendo-game-boy-gb-gbc/games/")
            w.watcher.cancel()
            w.close()

    def test_mamedev_window(self):
        """Nothing downloads until the user confirms non-commercial use; the set keeps MAME's file name."""
        mamedev, scraper = sys.modules["mamedev"], sys.modules["scraper"]
        game = {"id": "gridlee", "title": "Gridlee", "year": "1982", "company": "Videa, Inc.", "thumb": "",
                "page": "https://www.mamedev.org/roms/gridlee/", "image": "",
                "zips": ["https://www.mamedev.org/roms/gridlee/gridlee.zip"],
                "notice": "Gridlee has been made available for free, non-commercial use.", "description": "Never sold."}
        rom = os.path.join(self.p["roms"], "mame", "gridlee.zip")
        with mock.patch.object(mamedev, "load_catalog", return_value=[game]), \
                mock.patch.object(mamedev, "_fetch", return_value=zip_bytes({"gridlee.1": b"ROM"})), \
                mock.patch.object(scraper, "es_de_running", return_value=False):
            w = sys.modules["mamedev_gui"].open_window(self.app)
            self.pump(lambda: w.tv.get_children() == ("gridlee",))
            w.tv.selection_set("gridlee")
            self.root.update()
            self.assertIn("non-commercial", w.info.get("1.0", "end"))
            self.boxes["askyesno"].return_value = False
            button(w.win, "Install").invoke()
            self.root.update()
            self.assertIn("non-commercial use only", self.boxes["askyesno"].call_args[0][1])
            mamedev._fetch.assert_not_called()
            self.assertFalse(os.path.exists(rom))
            self.boxes["askyesno"].return_value = True
            button(w.win, "Install").invoke()
            self.pump(lambda: w.tv.set("gridlee", "status") == "Installed")
            self.assertTrue(os.path.exists(rom))
            with open(scraper.gamelist_path(self.p["roms"], "mame"), encoding="utf-8") as f:
                text = f.read()
            self.assertIn("<path>./gridlee.zip</path>", text)
            self.assertIn("<name>Gridlee</name>", text)
            self.assertNoErrors()
            w.tv.selection_set("gridlee")
            with mock.patch.object(sys.modules["catalog_gui"].webbrowser, "open") as web:
                button(w.win, "Open on mamedev.org ↗").invoke()
            web.assert_called_once_with("https://www.mamedev.org/roms/gridlee/")
            self.assertEqual(w.watcher.waiting, [])  # just a page to read: Install is how sets arrive
            self.assertNotIn("license", w.tv["displaycolumns"])
            w.close()

    def test_rename_leaves_arcade_systems_alone(self):
        self.app.system = "mame"
        with mock.patch.object(self.rs.tk, "Toplevel") as top:
            self.app.rename_dialog()
        top.assert_not_called()
        self.assertIn("ROM set", self.boxes["showinfo"].call_args[0][1])

    def test_setup_retrodeck(self):
        """Pick an SD card, install, and RetroShelf follows RetroDECK's own setup to the new roms folder."""
        fe, sg = sys.modules["frontend"], sys.modules["setup_gui"]
        home = os.environ["HOME"]
        sd = os.path.join(self.base, "sdcard")
        os.makedirs(sd, exist_ok=True)
        logged = []

        def install(log, cancelled):
            log("Installing net.retrodeck.retrodeck")
            logged.append(True)

        with mock.patch.object(sg, "is_windows", return_value=False), \
                mock.patch.object(fe, "is_windows", return_value=False), \
                mock.patch.object(sg, "POLL_MS", 30), \
                mock.patch.object(fe, "flatpak", return_value="/usr/bin/flatpak"), \
                mock.patch.object(fe, "retrodeck_installed", return_value=False), \
                mock.patch.object(fe, "install_retrodeck", side_effect=install), \
                mock.patch.object(fe, "launch_retrodeck") as launch, \
                mock.patch.object(fe, "storage_choices",
                                  return_value=[("home", "Home folder", home), ("drive", "SD card", sd)]):
            w = sg.open_window(self.app)
            w.choice.set(f"drive:{sd}")
            w._update_target()
            self.assertIn(os.path.join(sd, "retrodeck", "roms"), w.target_lbl.cget("text"))
            button(w.win, "Install").invoke()
            self.pump(lambda: launch.called)
            self.assertTrue(logged)
            self.assertEqual(self.root.clipboard_get(), sd)  # ready to paste into RetroDECK's folder picker
            self.assertIn("Waiting", w.status.cget("text"))
            roms = os.path.join(sd, "retrodeck", "roms")  # what RetroDECK's setup makes
            os.makedirs(os.path.join(roms, "snes"))
            with open(os.path.join(roms, "snes", "Game (USA).sfc"), "wb") as f:
                f.write(b"x")
            cfg = fe.rd_config_dir()
            os.makedirs(cfg, exist_ok=True)
            with open(os.path.join(cfg, "retrodeck.json"), "w") as f:
                json.dump({"paths": {"rd_home_path": os.path.dirname(roms), "roms_path": roms}}, f)
            open(os.path.join(cfg, ".lock"), "w").close()
            self.pump(lambda: self.app.cfg["roms_root"] == roms)
            self.assertIn("snes", self.app.system_codes)
            self.assertIn("RetroDECK is set up", "\n".join(lbl.cget("text") for lbl in widgets(w.win)
                                                             if isinstance(lbl, ttk.Label)))
            w.close()
        shutil.rmtree(os.path.join(home, ".var"), ignore_errors=True)

    def test_setup_esde_on_windows(self):
        """Pick a drive: ES-DE's portable build is downloaded, unpacked and its ROMs folder becomes the library."""
        fe, sg = sys.modules["frontend"], sys.modules["setup_gui"]
        drive = os.path.join(self.base, "D")
        os.makedirs(drive, exist_ok=True)

        def download(url, dest, md5=None, progress=lambda d, t: None, cancelled=lambda: False):
            with zipfile.ZipFile(dest, "w") as z:
                z.writestr("ES-DE/ES-DE.exe", b"MZ")
                z.writestr("ES-DE/ROMs_ALL/gb/systeminfo.txt", b"gb")
                z.writestr("ES-DE/ROMs_ALL/snes/systeminfo.txt", b"snes")
            progress(5, 10)
            progress(10, 10)
            return dest

        pkg = {"filename": "ES-DE_x64_Portable.zip", "url": "https://gitlab.com/x", "md5": "ab"}
        with mock.patch.object(sg, "is_windows", return_value=True), \
                mock.patch.object(fe, "is_windows", return_value=True), \
                mock.patch.object(fe, "esde_release", return_value=("3.5.0", pkg)), \
                mock.patch.object(fe, "download", side_effect=download) as dl, \
                mock.patch.object(fe, "add_esde_shortcut") as shortcut, \
                mock.patch.object(fe, "storage_choices", return_value=[("drive", "Drive D:", drive)]):
            w = sg.open_window(self.app)
            self.assertEqual(w.win.title(), "Set up ES-DE")
            button(w.win, "Install").invoke()
            roms = os.path.join(drive, "ES-DE", "ROMs")
            self.pump(lambda: self.app.cfg["roms_root"] == roms)
            self.assertEqual(dl.call_args[0][2], "ab")  # the checksum is checked
            self.assertEqual(sorted(os.listdir(roms)), ["gb", "snes"])
            self.assertFalse(os.path.exists(os.path.join(drive, pkg["filename"])))  # the zip is cleaned up
            shortcut.assert_called_once_with(drive)
            self.assertEqual(self.app.cfg["esde_bases"], [drive])
            self.assertIn(os.path.join(drive, "ES-DE", "Emulators"),
                          "\n".join(lbl.cget("text") for lbl in widgets(w.win) if isinstance(lbl, ttk.Label)))
            w.close()
        self.restart()  # found again next time from the remembered install
        self.assertEqual(self.app.cfg["roms_root"], roms)

    def test_first_start_without_a_library_offers_setup(self):
        with open(os.path.join(self.p["app"], "config.json"), "w") as f:
            json.dump({"roms_root": ""}, f)
        with mock.patch.object(self.rs, "guess_roms_root", return_value=""):
            self.restart()
            self.pump(lambda: getattr(self.app, "setup_window", None))
            self.app.setup_window.close()
            self.assertTrue(self.cfg()["setup_offered"])
            self.restart()
            for _ in range(10):
                self.root.update()
                time.sleep(0.07)
            self.assertIsNone(getattr(self.app, "setup_window", None))  # offered once, not on every start

    def pump(self, done, timeout=5.0):
        """Run Tk's event loop until done() is true (background work finishes through after() polls)."""
        end = time.monotonic() + timeout
        while not done():
            if time.monotonic() > end:
                self.fail("timed out waiting for the window")
            self.root.update()
            time.sleep(0.02)

    def test_rename_dialog_and_undo(self):
        a = self.app
        a.rename_dialog()
        win = self.root.winfo_children()[-1]
        button(win, "Rename").invoke()
        self.assertNoErrors()
        names = set(os.listdir(self.snes))
        self.assertIn("Super Mario World (USA).sfc", names)        # set number dropped
        self.assertIn("Final Fantasy III (USA).sfc", names)        # scene name -> LaunchBox title
        self.assertIn("Earthbound (USA).sfc.part", names)          # partial downloads are left alone
        self.assertEqual(len(a.units), SNES_N)

        a.undo_renames_dialog(win, lambda: None)
        undo = win.winfo_children()[-1]
        tv = next(w for w in widgets(undo) if isinstance(w, ttk.Treeview))
        tv.selection_set(tv.get_children()[0])
        next(b for b in widgets(undo) if isinstance(b, ttk.Button) and b.cget("text").startswith("Undo")).invoke()
        self.assertNoErrors()
        self.assertEqual(set(os.listdir(self.snes)), {n for n, *_ in sandbox.SNES_GAMES} | {"systeminfo.txt",
                                                                                              "readme.txt"})

    def test_rename_updates_cue_and_m3u(self):
        a = self.app
        a.load_system("psx")
        a.cfg["rename_templates"]["psx"] = "{title} [{region}]"  # the dialog opens with the system's template
        a.rename_dialog()
        button(self.root.winfo_children()[-1], "Rename").invoke()
        self.assertNoErrors()
        psx = os.path.join(self.p["roms"], "psx")
        for sheet in ("Castlevania - Symphony of the Night [USA].cue", "Final Fantasy VII [USA].m3u"):
            with open(os.path.join(psx, sheet), encoding="utf-8") as f:
                refs = [ln.split('"')[1] if '"' in ln else ln for ln in f.read().splitlines()
                        if ln.startswith("FILE") or ln.endswith(".chd")]
            self.assertEqual(len(refs), 2)
            for r in refs:
                self.assertIn("[USA]", r)
                self.assertTrue(os.path.exists(os.path.join(psx, r)), r)


if __name__ == "__main__":
    unittest.main()
