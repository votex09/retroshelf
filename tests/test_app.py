"""End-to-end: the real RetroShelf window on the sandbox library (see sandbox.py), driven through its own methods
and buttons. Needs tkinter and a display; tests/run.sh supplies a virtual one with xvfb-run."""
import importlib.util, json, os, shutil, sys, tempfile, unittest
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

LIB_MODULES = ["sv_ttk", "launchbox", "nps", "nps_gui", "scraper", "desktop", "details", "ui", "updater", "fsutil"]
SNES_N = len(sandbox.SNES_GAMES)
SPORTS = "Sports"


def widgets(w):
    yield w
    for c in w.winfo_children():
        yield from widgets(c)


def button(win, text):
    return next(b for b in widgets(win) if isinstance(b, ttk.Button) and b.cget("text") == text)


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
