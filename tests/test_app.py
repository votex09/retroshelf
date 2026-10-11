"""End-to-end: the real RetroShelf window on the sandbox library (see sandbox.py), driven through its own methods
and buttons. Needs tkinter and a display; tests/run.sh supplies a virtual one with xvfb-run."""
import base64, importlib.util, io, json, os, shutil, subprocess, sys, tempfile, time, unittest, zipfile
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
import sandbox  # noqa: E402
import discs  # noqa: E402

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError as e:
    raise unittest.SkipTest(f"no tkinter: {e}")
if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    raise unittest.SkipTest("no display (run tests/run.sh, which uses xvfb-run)")

LIB_MODULES = ["sv_ttk", "launchbox", "nps", "nps_gui", "scraper", "desktop", "details", "ui", "updater", "fsutil",
               "homebrew", "homebrew_gui", "downloads", "catalog_gui", "itch", "itch_gui", "pdroms",
               "pdroms_gui", "mamedev", "mamedev_gui", "frontend", "setup_gui", "sevenzip", "romimport", "import_gui", "dialogs", "listkeys", "review", "video", "gamepad", "padhints", "compress", "compress_gui", "health", "health_gui", "storage", "storage_gui", "dupes", "dupes_gui", "esde_collections", "collections_gui", "hiding", "osk"]
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
                self.root.tk.call("after", "cancel", job)  # (after_cancel would also delete commands others own)
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

    def test_each_system_goes_back_to_the_game_you_were_on(self):
        a = self.app
        a.keys.place(a.keep_tv, 3)
        here = a.keep_tv.focus()
        a.load_system("psx")
        self.assertNotEqual(a.keep_tv.focus(), here)
        a.load_system("snes")
        self.assertEqual(a.keep_tv.focus(), here)
        # and the list has the keyboard (asked of Tk directly: on Windows CI the window may not be the active one)
        self.assertEqual(str(self.root.tk.call("focus", "-lastfor", self.root)), str(a.keep_tv))
        self.restart()  # and after a restart (it opens on snes, the last system)
        self.assertEqual(self.app.keep_tv.focus(), here)

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
                mock.patch.object(nps_gui.dialogs, "ask_directory") as ask:
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

    def test_import_roms(self):
        """Throw games in the import folder: each one's system is shown, can be changed, and Import files them."""
        ig = sys.modules["import_gui"]
        inbox = ig.inbox_dir(self.app)
        self.assertEqual(inbox, os.path.join(os.path.dirname(self.p["roms"]), "import"))
        os.makedirs(inbox, exist_ok=True)
        for name, data in (("Gran Turismo 4 (USA).7z", discs.seven_zip({"Gran Turismo 4 (USA).iso": discs.ps2()})),
                           ("mystery.zip", zip_bytes({"mystery.p1": b"x" * 10})),
                           ("Tetris (World).gb", b"T" * 64)):
            with open(os.path.join(inbox, name), "wb") as f:
                f.write(data)
        button(self.root, "Import ROMs…").invoke()
        w = self.app.import_window
        self.pump(lambda: not w.scanning)
        shown = {r.name: w.tv.set(iid, "system") for iid, r in w.rows.items()}
        self.assertEqual(shown, {"Gran Turismo 4 (USA).7z": "PlayStation 2", "mystery.zip": "?",
                                 "Tetris (World).gb": "Game Boy"})
        self.assertEqual(w.import_btn.cget("text"), "Import 2 games")
        iid = next(i for i, r in w.rows.items() if r.name == "mystery.zip")
        w.tv.selection_set(iid)
        self.root.update()
        w.system_cb.current(w.codes.index("fbneo") + 1)
        button(w.win, "Set").invoke()
        self.assertEqual(w.tv.set(iid, "system"), "Arcade (FinalBurn Neo)")
        w.import_btn.invoke()
        self.pump(lambda: not w.busy and all(r.status.startswith("Imported") for r in w.rows.values()))
        for rel in ("ps2/Gran Turismo 4 (USA).iso", "fbneo/mystery.zip", "gb/Tetris (World).gb"):
            self.assertTrue(os.path.exists(os.path.join(self.p["roms"], *rel.split("/"))), rel)
        self.assertEqual(os.listdir(inbox), [])
        self.assertIn("ps2", self.app.system_codes)  # the new system shows up in the main window
        with open(os.path.join(inbox, "Metroid (USA).gba"), "wb") as f:  # noticed while the window is open
            f.write(b"M" * 64)
        self.pump(lambda: any(r.name == "Metroid (USA).gba" for r in w.rows.values()), timeout=10)
        # Add a folder: it says where from and how many before listing anything
        nas = os.path.join(self.base, "nas", "downloads")
        for rel in ("PS2 Collection/Okami (USA)/Okami (USA).7z", "PS2 Collection/Ico (USA).7z", "3DS/Other.3ds"):
            os.makedirs(os.path.dirname(os.path.join(nas, rel)), exist_ok=True)
            with open(os.path.join(nas, rel), "wb") as f:
                f.write(discs.seven_zip({"x.iso": discs.ps2()}) if rel.endswith(".7z") else b"x")
        picked = os.path.join(nas, "PS2 Collection")
        before = len(w.rows)
        with mock.patch.object(sys.modules["dialogs"], "ask_directory", return_value=picked):
            self.boxes["askyesno"].return_value = False
            button(w.win, "Add a folder…").invoke()
            question = self.boxes["askyesno"].call_args[0][1]
            self.assertIn("Add 2 games in 2 folders from", question)
            self.assertIn(picked, question)
            self.assertEqual(len(w.rows), before)  # said no: nothing added
            self.boxes["askyesno"].return_value = True
            button(w.win, "Add a folder…").invoke()
        added = sorted(r.name for r in list(w.rows.values())[before:])
        self.assertEqual(added, ["Ico (USA).7z", "Okami (USA).7z"])  # nothing from beside the folder
        self.pump(lambda: not w.scanning)
        w.close()
        self.assertIsNone(self.app.import_window)

    def key(self, widget, seq):
        """Press a key the way a person would: on the widget that has the keyboard."""
        widget.focus_force()

        def focused():  # the virtual display can take a moment to hand focus over
            f = self.root.focus_get()
            return f is not None and (f is widget or str(f).startswith(str(widget) + "."))
        self.pump(focused)
        widget.event_generate(seq)
        self.root.update()

    def test_keyboard_flips_keep_your_place(self):
        a, keep, move = self.app, self.app.keep_tv, self.app.move_tv
        rows = keep.get_children()
        a.keys.place(keep, 1)
        second, third = rows[1], rows[2]
        self.key(keep, "<Right>")  # → moves it, and the cursor stays where it was
        self.assertTrue(move.exists(second) and not keep.exists(second))
        self.assertEqual((keep.selection(), keep.focus(), self.root.focus_get()), ((third,), third, keep))
        self.key(keep, "<Control-z>")  # undo brings it back, selected
        self.assertTrue(keep.exists(second))
        self.assertEqual(keep.selection(), (second,))

        # Space marks and steps down without moving anything; Enter flips the marked ones together
        a.keys.place(keep, 0)
        self.key(keep, "<space>")
        self.key(keep, "<space>")
        first, second = keep.get_children()[:2]
        self.assertEqual(keep.marked, {first, second})
        self.assertIn("marked", keep.item(first, "tags"))
        self.assertFalse(move.get_children())
        self.key(keep, "<Return>")
        self.assertEqual(set(move.get_children()), {first, second})
        self.assertEqual(keep.marked, set())
        # leaving the list applies marks too; Tab lands in the other list
        self.key(keep, "<space>")
        marked = next(iter(keep.marked))
        self.key(keep, "<Tab>")
        self.assertTrue(move.exists(marked))
        self.assertIs(self.root.focus_get(), move)
        # Moving: Ctrl+A, ← keeps them all
        self.key(move, "<Control-a>")
        self.key(move, "<Left>")
        self.assertFalse(move.get_children())
        self.assertEqual(len(keep.get_children()), len(rows))

        # typing jumps; Shift+↓ selects a range; Delete moves it
        for ch in "sup":
            self.key(keep, f"<KeyPress-{ch}>")
        self.assertEqual(keep.focus(), next(k for k in keep.get_children() if keep.item(k, "text").startswith("Sup")))
        self.key(keep, "<Shift-Down>")
        self.key(keep, "<Shift-Down>")
        picked = keep.selection()
        self.assertEqual(len(picked), 3)
        self.key(keep, "<Delete>")
        self.assertTrue(all(move.exists(k) for k in picked))
        self.key(keep, "<BackSpace>")  # Backspace undoes too
        self.assertTrue(all(keep.exists(k) for k in picked))

    def test_a_late_refresh_keeps_the_cursor(self):
        """Lists rebuilt by a filter change (or a refresh queued earlier) keep your place."""
        keep = self.app.keep_tv
        row = self.app.keys.place(keep, 3)
        self.app.refresh()
        self.assertEqual((keep.focus(), keep.selection()), (row, (row,)))

    def test_review_one_at_a_time(self):
        a, keep, move = self.app, self.app.keep_tv, self.app.move_tv
        rows = keep.get_children()
        a.keys.place(keep, 0)
        self.key(keep, "<Control-r>")
        w = a.review_window
        self.assertEqual(w.count.cget("text"), f"1 of {len(rows)}")
        self.assertEqual(w.title.cget("text"), keep.item(rows[0], "text"))
        self.key(w.win, "<m>")  # move the first, keep the second, skip the third
        self.key(w.win, "<k>")
        self.key(w.win, "<s>")
        self.assertTrue(move.exists(rows[0]) and keep.exists(rows[1]))
        self.assertEqual(w.count.cget("text"), f"4 of {len(rows)}")
        self.assertEqual(a.manual.get(rows[0]), True)
        self.key(w.win, "<BackSpace>")  # undo goes back to the game it undid
        self.assertTrue(keep.exists(rows[0]))
        self.assertEqual(w.count.cget("text"), f"1 of {len(rows)}")
        self.key(w.win, "<Escape>")
        self.assertIsNone(a.review_window)

    def clip_folder(self):
        folder = os.path.join(os.path.dirname(self.p["roms"]), "ES-DE", "downloaded_media", "snes", "videos")
        os.makedirs(folder, exist_ok=True)
        return folder

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg isn't installed")
    def test_gameplay_clip_plays_in_the_details_panel(self):
        vid = sys.modules["video"]
        clip = os.path.join(self.clip_folder(), "Chrono Trigger (USA).mp4")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=24",
                        "-t", "2", "-pix_fmt", "yuv420p", clip], check=True)
        keep, spot = self.app.keep_tv, self.app.details.spot
        with mock.patch.object(vid, "_backend", ("ffmpeg", [shutil.which("ffmpeg")])):
            self.app.keys.place(keep, keep.get_children().index("Chrono Trigger (USA)"))
            self.root.update()
            self.assertFalse(spot.playing())  # not straight away: arrowing past a game doesn't start its clip
            self.pump(lambda: spot.playing() and spot.player.started())  # frames are being painted
            self.pump(lambda: self.app.details.pic_lbl.cget("text") == "video")
            proc = spot.player.proc
            self.app.keys.place(keep, 0)  # moving on stops it
            self.root.update()
            self.assertFalse(spot.playing())
            self.assertIsNotNone(proc.poll())
            self.app.keys.place(keep, keep.get_children().index("Chrono Trigger (USA)"))
            self.app.videos_var.set(False)  # View → Play gameplay videos off
            self.app.toggle_videos()
            for _ in range(int(vid.DELAY_MS / 20) + 10):
                self.root.update()
                time.sleep(0.02)
            self.assertFalse(spot.playing())
            self.assertFalse(self.cfg()["play_videos"])

    def test_youtube_when_there_is_no_clip(self):
        """Streaming on: a game without a clip gets the top YouTube result through mpv; a clip still comes first."""
        vid = sys.modules["video"]
        started = []

        class FakeMpv:
            can_sound = True

            def __init__(self, frame, source, prefix, flatpak=False, stream=False):
                started.append((source, stream))

            def alive(self):
                return True

            def started(self):
                return True

            def set_sound(self, on):
                return True

            def stop(self, widgets=True):
                pass
        open(os.path.join(self.clip_folder(), "Super Metroid (Japan, USA) (En,Ja).mp4"), "wb").close()
        keep, spot, a = self.app.keep_tv, self.app.details.spot, self.app
        with mock.patch.object(vid, "_backend", ("mpv", ["/usr/bin/mpv"])), mock.patch.object(vid, "_ytdl", True), \
                mock.patch.object(vid, "MpvPlayer", FakeMpv):
            a.stream_var.set(True)
            a.toggle_streams()
            self.assertTrue(self.cfg()["stream_videos"])
            a.keys.place(keep, keep.get_children().index("Chrono Trigger (USA)"))
            self.pump(lambda: started)
            self.assertEqual(started[-1], (f"ytdl://ytsearch1:Chrono Trigger {a.fullname} gameplay", True))
            self.pump(lambda: a.details.pic_lbl.cget("text") == "YouTube")
            self.assertTrue(a.details.sound_btn.winfo_ismapped())
            a.details.sound_btn.invoke()
            self.assertEqual(a.details.sound_btn.cget("text"), "🔊")
            a.keys.place(keep, keep.get_children().index("Super Metroid (Japan, USA) (En,Ja)"))
            self.pump(lambda: len(started) == 2)
            clip = os.path.join(self.clip_folder(), "Super Metroid (Japan, USA) (En,Ja).mp4")
            self.assertTrue(os.path.samefile(started[-1][0], clip))  # the local clip, not a stream
            self.assertFalse(started[-1][1])
            a.stream_var.set(False)
            a.toggle_streams()
            a.keys.place(keep, keep.get_children().index("Chrono Trigger (USA)"))
            for _ in range(int(vid.STREAM_DELAY_MS / 20) + 10):
                self.root.update()
                time.sleep(0.02)
            self.assertEqual(len(started), 2)  # streaming off: no video for a game without a clip
        with mock.patch.object(vid, "_backend", ("ffmpeg", ["/usr/bin/ffmpeg"])):
            a.stream_var.set(True)
            a.toggle_streams()  # ffmpeg can't stream: it says what to install and stays off
            self.assertFalse(a.stream_var.get())
            self.assertIn("mpv and yt-dlp", self.boxes["showinfo"].call_args[0][1])

    def test_gamepad_drives_the_lists_and_review(self):
        HINT_POLLS = sys.modules["gamepad"].HINT_TICKS + 1
        a = self.app
        keep, move = a.keep_tv, a.move_tv
        held, clock = set(), [0.0]

        class Pad:
            def poll(self, now):
                return set(held), []
        pads = a.gamepads  # the app's own, fed by a pad that only exists here
        pads.source, pads.clock = Pad(), lambda: clock[0]

        def press(*buttons):
            """Press and let go, as a person would; the window with the keyboard gets the key."""
            held.update(buttons)
            clock[0] += 0.05
            sent = pads.step()
            held.clear()
            clock[0] += 0.05
            pads.step()
            self.root.update()
            return sent
        a.keys.place(keep, 0)
        keep.focus_force()
        self.pump(lambda: self.root.focus_get() is keep)
        rows = keep.get_children()
        hints = a.pad_hints
        self.assertEqual(hints.shown(), [])  # no bar before the pad is used
        press("down")
        self.assertEqual(keep.focus(), rows[1])
        # the pad was used last: the main window shows what its buttons do in the Keeping list
        shown = dict(hints.shown(self.root))
        self.assertEqual(shown["a"], "Mark")
        self.assertEqual(shown["x"], "Move it")
        self.assertEqual(shown["lb+rb"], "Moving list")
        self.assertEqual(shown["start"], "Review")
        self.assertNotIn("y", shown)  # nothing to undo yet
        bar = hints.bars[str(self.root)].canvas
        self.assertEqual(bar.winfo_manager(), "pack")
        self.assertTrue(bar.find_withtag("pad"))
        press("a")  # A marks and steps down
        self.assertEqual(keep.marked, {rows[1]})
        self.assertEqual(keep.focus(), rows[2])
        self.assertEqual(dict(hints.shown())["x"], "Move 1 marked")
        press("x")  # X flips what's marked
        self.assertTrue(move.exists(rows[1]))
        self.assertEqual(dict(hints.shown())["y"], "Undo")
        press("y")  # Y undoes
        self.assertTrue(keep.exists(rows[1]))
        press("rb")  # RB: the other list
        self.assertIs(self.root.focus_get(), move)
        shown = dict(hints.shown())  # an empty list: only the way back
        self.assertEqual(shown["lb+rb"], "Keeping list")
        self.assertNotIn("x", shown)
        press("lb")
        self.assertIs(self.root.focus_get(), keep)
        # a real key press puts the keyboard back in charge: the bar goes, until the pad is used again
        keep.event_generate("<KeyPress-Shift_L>")
        self.assertFalse(pads.active)
        self.assertEqual(hints.shown(), [])
        self.assertEqual(bar.winfo_manager(), "")
        press("down")
        self.assertTrue(hints.shown())
        # so does moving the mouse
        x, y = self.root.winfo_pointerxy()
        self.root.event_generate("<Motion>", warp=True, x=40, y=40)
        self.root.update()
        if self.root.winfo_pointerxy() != (x, y):  # the display let the pointer move
            clock[0] += 0.05
            pads.step()
            self.assertFalse(pads.active)
            self.assertEqual(hints.shown(), [])
            # put it back: with no window manager (xvfb) the keyboard follows the pointer, and later tests'
            # new windows would lose the keyboard to the main window it's left over
            self.root.event_generate("<Motion>", warp=True, x=x - self.root.winfo_rootx(), y=y - self.root.winfo_rooty())
            self.root.update()
            press("down")
        # holding the D-pad keeps going
        a.keys.place(keep, 0)
        held.add("down")
        for _ in range(12):
            clock[0] += 0.1
            pads.step()
        held.clear()
        pads.step()
        self.root.update()
        self.assertGreater(keep.get_children().index(keep.focus()), 3)
        # Start opens Review; there A keeps, X moves, B closes
        a.keys.place(keep, 0)
        press("start")
        w = a.review_window
        self.pump(lambda: self.root.focus_get() is not None and self.root.focus_get().winfo_toplevel() is w.win)
        first = w.keys[0]
        for _ in range(HINT_POLLS):  # the hints catch up with the new window on their own
            clock[0] += 0.02
            pads.step()
        shown = dict(hints.shown(w.win))
        self.assertEqual((shown["a"], shown["x"], shown["dpad:lr"], shown["b"]), ("Keep", "Move", "Back / Skip", "Close"))
        self.assertEqual(hints.bars[str(self.root)].shown, [])  # only the window with the keyboard has a bar
        press("x")
        self.assertTrue(move.exists(first))
        self.assertEqual(w.i, 1)
        press("a")
        self.assertEqual(w.i, 2)
        press("b")
        self.assertIsNone(a.review_window)
        # nothing reaches RetroShelf while another app has the keyboard, or with View → Use a gamepad off
        with mock.patch.object(self.root, "focus_get", return_value=None):
            self.assertEqual(press("down"), [])
        a.gamepad_var.set(False)
        a.toggle_gamepad()
        self.assertEqual(press("down"), [])
        self.assertFalse(self.cfg()["gamepad"])
        self.assertEqual(hints.shown(), [])

    def test_gamepad_reaches_search_and_filters_and_types(self):
        a = self.app
        held, clock = set(), [0.0]

        class Pad:
            def poll(self, now):
                return set(held), []
        pads = a.gamepads
        pads.source, pads.clock = Pad(), lambda: clock[0]

        def press(*buttons):
            held.update(buttons)
            clock[0] += 0.05
            pads.step()
            held.clear()
            clock[0] += 0.05
            pads.step()
            self.root.update()
        a.keys.place(a.keep_tv, 2)
        a.keep_tv.focus_force()
        self.pump(lambda: self.root.focus_get() is a.keep_tv)
        press("select")  # View / Select: lists → search box
        self.assertIs(self.root.focus_get(), a.search_entry)
        self.assertEqual(dict(a.pad_hints.shown())["a"], "Keyboard")
        press("a")  # A in a text box: the on-screen keyboard, not a typed space
        kb = self.root._osk
        self.pump(lambda: self.root.focus_get() is not None and self.root.focus_get().winfo_toplevel() is kb.win)
        self.assertEqual(a.search_entry.get(), "")
        press("a")  # types the key under the cursor (q, at the start)
        press("down", "right")
        press("a")
        self.assertEqual(a.search_entry.get(), "qs")
        press("y")  # Y deletes
        self.assertEqual(a.search_entry.get(), "q")
        press("lb")  # LB: capitals
        press("a")
        self.assertEqual(a.search_entry.get(), "qS")
        press("x")  # X: done, back in the search box
        self.assertFalse(kb.win.winfo_exists())
        self.assertIs(self.root.focus_get(), a.search_entry)
        a.view_filter.set("")
        a.refresh()
        press("select")  # → the filter tabs
        self.assertIs(self.root.focus_get(), a.filter_tabs)
        press("select")  # → back to the list, where the cursor was
        self.assertIs(self.root.focus_get(), a.keep_tv)
        self.assertEqual(a.keep_tv.get_children().index(a.keep_tv.focus()), 2)
        a.keep_tv.event_generate("<Shift-F6>")  # and backwards from the keyboard
        self.root.update()
        self.assertIs(self.root.focus_get(), a.filter_tabs)

    def test_compress_window(self):
        a = self.app
        comp, gui = sys.modules["compress"], sys.modules["compress_gui"]
        tools = a.tools_menu
        self.assertEqual(tools.entrycget(a._menu_item(tools, "Compress"), "state"), "disabled")  # SNES: cartridges
        a.load_system("psx")
        self.assertEqual(tools.entrycget(a._menu_item(tools, "Compress"), "state"), "normal")
        fake = comp.Tool("chdman", "the tests", [sys.executable, os.path.join(TESTS, "fake_disc_tool.py")])
        psx = os.path.join(self.p["roms"], "psx")
        sotn, ff7 = sandbox.PSX_GAMES[0][0], sandbox.PSX_GAMES[1][0]
        with mock.patch.object(comp, "find_tool", return_value=fake):
            w = gui.open_window(a)
            self.pump(lambda: w.tools.get("chdman"))
        self.assertEqual(list(w.rows), [sotn])  # the cue / bin game; the CHD one is listed as already compressed
        self.assertEqual(w.tv.set(sotn, "now"), "cue + 2 bin")
        self.assertEqual(w.tv.set(ff7, "result"), "already compressed")
        self.assertIn("Using chdman from the tests", w.tool_lbl.cget("text"))
        w.start()
        self.pump(lambda: not w.busy)
        self.assertNoErrors()
        self.assertEqual(sorted(n for n in os.listdir(psx) if n.startswith(sotn)), [f"{sotn}.chd"])
        held = os.path.join(self.p["holding"], "to_delete", "psx")
        self.assertEqual(sorted(os.listdir(held)), sorted([f"{sotn}.cue", f"{sotn} (Track 1).bin",
                                                           f"{sotn} (Track 2).bin"]))
        batch = a._read_moves()[-1]
        self.assertEqual((batch["system"], batch["games"], len(batch["moves"])), ("psx", 1, 3))
        self.assertEqual(a.units[sotn]["paths"], [os.path.join(psx, f"{sotn}.chd")])  # the main window rescanned
        self.assertEqual(w.rows, {})
        self.assertTrue(w.tv.set(sotn, "result").startswith("Done"))  # still says what happened
        self.assertIn("Compressed 1 game,", w.status.cget("text"))
        w.close()
        self.assertIsNone(a.compress_window)

    def test_health_check_window(self):
        a = self.app
        gui = sys.modules["health_gui"]
        psx = os.path.join(self.p["roms"], "psx")
        lone = os.path.join(psx, "Lone (USA).bin")
        with open(lone, "wb") as f:
            f.write(discs.raw(discs.ps1()))
        media = os.path.join(self.base, "retrodeck", "ES-DE", "downloaded_media", "snes", "videos")
        os.makedirs(media, exist_ok=True)
        with open(os.path.join(media, "Long Gone (USA).mp4"), "wb") as f:
            f.write(b"v" * 4096)
        w = gui.open_window(a)
        self.pump(lambda: not w.busy)
        found = {(p.kind, p.name) for p in w.problems.values()}
        self.assertIn(("lonebin", "Lone (USA).bin"), found)
        self.assertIn(("media", "downloaded_media/snes"), found)
        self.assertEqual(w.fix_btn.cget("text"), f"Fix {sum(1 for p in w.problems.values() if p.fix)}")
        w.fix()
        self.assertNoErrors()
        self.assertTrue(os.path.isfile(os.path.join(psx, "Lone (USA).cue")))
        self.assertFalse(os.path.exists(os.path.join(media, "Long Gone (USA).mp4")))
        self.assertTrue(all("fixed" in w.tv.item(i, "tags") for i, p in w.problems.items() if p.fix))
        self.assertEqual(w.fix_btn.cget("text"), "Fix")
        # just this system
        w.scope.current(1)
        w.scan()
        self.pump(lambda: not w.busy)
        self.assertEqual({p.system for p in w.problems.values()} - {a.system}, set())
        w.close()
        self.assertIsNone(a.health_window)

    def test_storage_overview(self):
        a = self.app
        gui = sys.modules["storage_gui"]
        w = gui.open_window(a)
        self.pump(lambda: not w.busy)
        self.assertEqual(set(w.sys_tv.get_children()), {"snes", "psx"})
        self.assertEqual(w.sys_tv.selection(), ("snes",))  # starts on the system in the main window
        rows = w.game_tv.get_children()
        self.assertEqual(len(rows), SNES_N)
        biggest = max(a.units, key=lambda k: a.units[k]["size"])
        self.assertEqual(rows[0], biggest)  # the same games and sizes as the main window's rows
        self.assertEqual(w.game_tv.set(rows[0], "size"), sys.modules["frontend"].human_size(a.units[biggest]["size"]))
        self.assertIn("Could compress", w.sys_tv.heading("compress", "text"))
        self.assertTrue(w.sys_tv.set("psx", "compress"))  # psx has a cue / bin game
        # double-click a game: the main window goes to it, even when the search box hides it
        a.view_filter.set("zzz no such game")
        a.refresh()
        w.game_tv.selection_set(rows[0])
        w.open(game=True)
        self.root.update()
        self.assertEqual(a.view_filter.get(), "")
        tv = a.keep_tv if a.keep_tv.exists(biggest) else a.move_tv
        self.assertEqual(tv.focus(), biggest)
        # another system
        w.sys_tv.selection_set("psx")
        self.root.update()
        w.open()
        self.assertEqual(a.system, "psx")
        w.close()
        self.assertIsNone(a.storage_window)

    def test_find_duplicates_window(self):
        a = self.app
        gui = sys.modules["dupes_gui"]
        roms = self.p["roms"]
        # an SNES game copied into an sfc folder too, and one kept zipped as well as unzipped
        game = sorted(a.units)[0]
        src = a.units[game]["paths"][0]
        os.makedirs(os.path.join(roms, "sfc"), exist_ok=True)
        shutil.copy2(src, os.path.join(roms, "sfc", os.path.basename(src)))
        other = sorted(a.units)[1]
        with zipfile.ZipFile(os.path.splitext(a.units[other]["paths"][0])[0] + ".zip", "w") as z:
            z.write(a.units[other]["paths"][0], os.path.basename(a.units[other]["paths"][0]))
        w = gui.open_window(a)
        self.pump(lambda: not w.busy)
        sets = {(s.kind, s.title): s for s in w.sets.values()}
        copies = sets[("copies", game)]
        self.assertEqual(copies.copies[copies.keep].system, "snes")  # the fuller folder keeps its copy
        forms = sets[("formats", other)]
        self.assertEqual(os.path.splitext(forms.copies[forms.keep].primary)[1], ".zip")
        # keep the unzipped one instead, by double-clicking it
        sid = next(i for i, s in w.sets.items() if s is forms)
        cid = next(c for c in w.tv.get_children(sid) if not forms.copies[w.copies[c][1]].primary.endswith(".zip"))
        w.tv.selection_set(cid)
        w.keep_selected()
        self.assertFalse(forms.copies[forms.keep].primary.endswith(".zip"))
        w.tv.selection_set(())
        w.resolve()
        self.assertNoErrors()
        self.assertFalse(os.path.exists(os.path.join(roms, "sfc", os.path.basename(src))))
        self.assertTrue(os.path.exists(src))
        self.assertTrue(os.path.exists(a.units[other]["paths"][0]))
        self.assertFalse(any(p.endswith(".zip") for p in a.units[other]["paths"]))
        logged = {b["system"] for b in a._read_moves()}
        self.assertEqual(logged, {"snes", "sfc"})
        w.scan()
        self.pump(lambda: not w.busy)
        self.assertEqual(w.sets, {})
        w.close()

    def test_save_as_an_esde_collection(self):
        a = self.app
        gui, ec = sys.modules["collections_gui"], sys.modules["esde_collections"]
        es = os.path.join(self.base, "retrodeck", "ES-DE")
        os.makedirs(os.path.join(es, "settings"), exist_ok=True)
        with open(os.path.join(es, "settings", "es_settings.xml"), "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0"?>\n<string name="ROMDirectory" value="" />\n')
        w = gui.open_window(a)
        self.assertEqual(w.scope.get(), "keep")
        self.assertTrue(w.save_btn.instate(["disabled"]))  # no name yet
        w.name.set("Best of SNES")
        self.assertEqual(w.about.cget("text"), "A new collection.")
        with mock.patch.object(sys.modules["scraper"], "es_de_running", return_value=False):
            w.save()
        path = ec.path_of(ec.home(self.p["roms"]), "Best of SNES")
        lines = ec.games(path)
        self.assertEqual(len(lines), len(a.kept))
        self.assertTrue(all(line.startswith("%ROMPATH%/snes/") for line in lines))
        self.assertEqual(ec.enabled(ec.home(self.p["roms"])), ["Best of SNES"])
        # again, from the right-click menu's scope: the selected games, added to the same collection
        a.keys.place(a.keep_tv, 0)
        w = gui.open_window(a, scope="selected")
        self.assertEqual(w.name.get(), "Best of SNES")  # remembered
        self.assertTrue(w.about.cget("text").startswith(f"Already has {len(lines)}"))
        w.save()
        self.assertEqual(len(ec.games(path)), len(lines))  # it was in there already
        self.assertFalse(w.win.winfo_exists())  # saving closes it

    def test_hide_in_esde(self):
        a = self.app
        hd = sys.modules["hiding"]
        es = os.path.join(self.base, "retrodeck", "ES-DE")
        os.makedirs(os.path.join(es, "settings"), exist_ok=True)
        with open(os.path.join(es, "settings", "es_settings.xml"), "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0"?>\n<string name="ROMDirectory" value="" />\n')
        self.preset("Sports")
        sports = list(a.to_move)
        self.assertTrue(sports)
        self.assertEqual(str(a.hide_btn.cget("state")), "normal")
        with mock.patch.object(sys.modules["scraper"], "es_de_running", return_value=False):
            a.hide_games(list(a.to_move))
        self.assertNoErrors()
        hidden = hd.hidden(a.gamelist_path())
        self.assertEqual(len(hidden), len(sports))
        self.assertEqual(a.hidden, set(sports))
        self.assertEqual(a.to_move, [])  # hidden games stay in Keeping, like played ones
        self.assertEqual({a.why[k] for k in sports}, {"hidden in ES-DE"})
        self.assertIn("hidden in ES-DE", a.keep_tv.item(sports[0], "text"))
        self.assertIn("hidden", a.keep_tv.item(sports[0], "tags"))
        self.assertFalse(hd.shows_hidden(es))  # ES-DE told to leave hidden games out
        self.assertEqual(str(a.hide_btn.cget("state")), "disabled")
        # show one again: back to where the filters put it
        with mock.patch.object(sys.modules["scraper"], "es_de_running", return_value=False):
            a.hide_games([sports[0]], hide=False)
        self.assertNotIn(sports[0], a.hidden)
        self.assertEqual(a.to_move, [sports[0]])
        # while ES-DE runs nothing is changed
        with mock.patch.object(sys.modules["scraper"], "es_de_running", return_value=True):
            a.hide_games([sports[0]])
        self.assertNotIn(sports[0], a.hidden)
        # a multi-disc game whose separate discs are hidden (so ES-DE lists only its .m3u) isn't a hidden game
        ff7 = sandbox.PSX_GAMES[1][0]
        hd.set_hidden(sys.modules["scraper"].gamelist_path(self.p["roms"], "psx"),
                      [f"{ff7} (Disc 1).chd", f"{ff7} (Disc 2).chd"])
        a.load_system("psx")
        self.assertNotIn(ff7, a.hidden)
        hd.set_hidden(a.gamelist_path(), [f"{ff7}.m3u"])
        a.rescan()
        self.assertIn(ff7, a.hidden)

    def test_pad_hints_for_any_window(self):
        """Windows that don't describe their buttons get hints by the kind of widget; every style draws."""
        import padhints
        win = tk.Toplevel(self.root)
        win.bind("<Escape>", lambda e: win.destroy())
        body = ttk.Frame(win)
        body.pack(fill="both", expand=True)
        b = ttk.Button(body, text="Go")
        off = ttk.Button(body, text="Nope", state="disabled")
        var = tk.BooleanVar(value=True)
        tick = ttk.Checkbutton(body, text="Tick", variable=var)
        tv = ttk.Treeview(body)
        for w in (b, off, tick, tv):
            w.pack()
        self.root.update()
        hints = lambda w: dict(padhints.hints_for(self.root, str(w)))
        self.assertEqual(hints(b), {"a": "Press", "lb+rb": "Previous / next control", "b": "Close"})
        self.assertNotIn("a", hints(off))
        self.assertEqual(hints(tick)["a"], "Untick")
        var.set(False)
        self.assertEqual(hints(tick)["a"], "Tick")
        self.assertEqual(hints(tv)["dpad:ud"], "Browse")
        self.assertEqual(hints(self.app.roms_entry)["start"], "Review")  # the main window has Ctrl+R; no Escape
        self.assertNotIn("b", hints(self.app.roms_entry))
        # a bar in a window laid out with grid lies over its bottom edge instead of joining the grid
        grid = tk.Toplevel(self.root)
        ttk.Button(grid, text="Grid").grid(row=0, column=0)
        h = padhints.Hints(self.root, lambda: self.app.colors)
        for style in padhints.STYLES:
            h.update(True, str(b), style)
            self.root.update()
            self.assertTrue(h.bars[str(win)].canvas.find_withtag("pad"))
        h.update(True, str(grid.winfo_children()[0]), "xbox")
        self.assertEqual(h.bars[str(grid)].canvas.winfo_manager(), "place")
        self.assertEqual(h.bars[str(win)].shown, [])
        h.update(False, str(b), "xbox")
        self.assertEqual(h.shown(), [])
        win.destroy()
        grid.destroy()

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
