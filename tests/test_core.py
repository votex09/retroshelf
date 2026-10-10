"""Name parsing, presets, region dupes, rename planning, LaunchBox matching and file helpers. No window needed,
but retroshelf.py imports tkinter, so run these with a Python that has it (tests/run.sh picks one)."""
import io, json, ntpath, os, posixpath, shutil, struct, subprocess, sys, tempfile, time, unittest, zipfile
import xml.etree.ElementTree as ET
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS)
sys.path.insert(0, TESTS)
sys.path.insert(0, REPO)
try:
    import retroshelf as rs
except ImportError as e:  # no tkinter
    raise unittest.SkipTest(f"can't import retroshelf: {e}")
import fsutil  # noqa: E402  (lib/ is on sys.path once retroshelf is imported)
import desktop  # noqa: E402
import downloads  # noqa: E402
import frontend  # noqa: E402
import homebrew as hb  # noqa: E402
import itch  # noqa: E402
import mamedev  # noqa: E402
import pdroms  # noqa: E402
import launchbox as lb  # noqa: E402
import nps  # noqa: E402
import scraper  # noqa: E402
import updater  # noqa: E402
import dialogs  # noqa: E402
import romimport as ri  # noqa: E402
import video  # noqa: E402
import gamepad  # noqa: E402
import padhints  # noqa: E402
import compress  # noqa: E402
import sevenzip  # noqa: E402
import sandbox  # noqa: E402
import discs  # noqa: E402


class Names(unittest.TestCase):
    def test_unit_key_joins_tracks_and_discs(self):
        self.assertEqual(rs.unit_key("Game (USA) (Track 2).bin"), "Game (USA)")
        self.assertEqual(rs.unit_key("Game (USA) (Disc 1).chd"), "Game (USA)")
        self.assertEqual(rs.unit_key("Game (USA).cue"), "Game (USA)")

    def test_title_strips_tags_and_set_numbers(self):
        self.assertEqual(rs.title_of("0123 - Super Mario World (USA) [!]"), "Super Mario World")

    def test_regions(self):
        self.assertEqual(set(rs.regions_of("Super Metroid (Japan, USA) (En,Ja)")), {"Japan", "USA"})

    def test_wildcards(self):
        self.assertTrue(rs.wildcard_re("mario", True).match("Super MARIO World"))
        self.assertTrue(rs.wildcard_re("*(Beta)*", True).match("Star Fox (USA) (Beta)"))
        self.assertFalse(rs.wildcard_re("0002*", True).match("x0002 - Game"))
        self.assertTrue(rs.wildcard_re("[b]", True).match("Game [b]"))  # brackets are literal
        self.assertFalse(rs.wildcard_re("Mario", False).match("mario"))

    def test_human(self):
        self.assertEqual(rs.human(0), "0 KB")
        self.assertEqual(rs.human(3 * 1048576), "3.0 MB")


class Presets(unittest.TestCase):
    keys = [rs.unit_key(n) for n, *_ in sandbox.SNES_GAMES if not n.endswith(".part")]

    def test_junk(self):
        self.assertEqual(rs.junk(self.keys), {"Star Fox (USA) (Beta)", "Donkey Kong Country (USA) (Demo) (Kiosk)",
                                              "Obscure Homebrew (World) (Unl)"})

    def test_sports_and_kids(self):
        self.assertEqual(rs.PRESETS["Sports"](self.keys), {"Madden NFL '94 (USA)", "NBA Jam (USA) (Rev 1)"})
        self.assertEqual(rs.PRESETS["Kids / licensed tie-ins"](self.keys), {"Barbie - Super Model (USA)"})

    def test_kids_tie_ins_named_after_the_film(self):
        kids = ["Finding Nemo (USA)", "Ratatouille (USA)", "Rugrats - Royal Ransom (USA)", "Cars (USA)", "Up (USA)",
                "Cars 2 (USA)", "0123 - Bolt (USA)", "Monsters vs. Aliens (USA)", "Lilo & Stitch (USA)",
                "Spongebob_Squarepants_-_Lights_Camera_Pants_USA", "Jimmy Neutron Boy Genius (USA)",
                # cartoon and film tie-ins of the NES / SNES / Mega Drive years
                "Adventures of Yogi Bear (USA)", "DuckTales 2 (USA)", "Chip 'n Dale - Rescue Rangers (USA)",
                "Tiny Toon Adventures - Buster Busts Loose! (USA)", "Simpsons, The - Bart's Nightmare (USA)",
                "Home Alone 2 - Lost in New York (USA)", "Hook (USA)", "Lion King, The (USA)"]
        others = ["Crazy Cars (USA)", "Up'n Down (USA)", "Brave Fencer Musashi (USA)", "Super Cars (USA)",
                  "Robotech - Battlecry (USA)", "King Arthur (USA)", "Frozen Synapse", "Kingdom Hearts (USA)",
                  "Earthworm Jim (USA)", "Doug Flutie's Football (USA)", "Home Improvement (USA)", "EarthBound (USA)"]
        self.assertEqual(rs.PRESETS["Kids / licensed tie-ins"](kids + others), set(kids))

    def test_region_dupes_keep_the_preferred_region(self):
        d = rs.region_dupes(self.keys)
        self.assertEqual(d["Chrono Trigger (Japan)"], "Chrono Trigger (USA)")
        self.assertEqual(d["Super Metroid (Europe) (En,Fr,De)"], "Super Metroid (Japan, USA) (En,Ja)")
        self.assertNotIn("Chrono Trigger (USA)", d)

    def test_region_dupes_follow_launchbox_links(self):
        links = {"Zelda no Densetsu (Japan)": "1", "Legend of Zelda, The - A Link to the Past (USA)": "1"}
        d = rs.region_dupes(list(links), links=links)
        self.assertEqual(d, {"Zelda no Densetsu (Japan)": "Legend of Zelda, The - A Link to the Past (USA)"})

    def test_priority_order(self):
        d = rs.region_dupes(["Game (USA)", "Game (Europe)"], rs.parse_priority("Europe, USA"))
        self.assertEqual(d, {"Game (USA)": "Game (Europe)"})


class Renames(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def touch(self, name, text=""):
        p = os.path.join(self.dir, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_no_intro_order_and_set_number(self):
        p = self.touch("0123 - Super Mario World (USA).sfc")
        [row] = rs.plan_renames([("k", [p], None, False)], rs.DEFAULT_TEMPLATE)
        self.assertEqual((row["status"], os.path.basename(row["new"])), ("rename", "Super Mario World (USA).sfc"))

    def test_scene_name_takes_launchbox_title(self):
        p = self.touch("Final_Fantasy_III_USA.sfc")
        [row] = rs.plan_renames([("k", [p], "Final Fantasy III", True)], rs.DEFAULT_TEMPLATE)
        self.assertEqual(os.path.basename(row["new"]), "Final Fantasy III (USA).sfc")

    def test_collision_skips_the_whole_game(self):
        a, b = self.touch("A (USA).bin"), self.touch("A (USA) (Track 2).bin")
        c = self.touch("B (USA).bin")
        rows = rs.plan_renames([("A", [a, b], None, False), ("B", [c], None, False)], "X {region}")
        self.assertIn("two games get this name", [r["status"] for r in rows])
        self.assertNotIn("rename", [r["status"] for r in rows])

    def test_unknown_field(self):
        [row] = rs.plan_renames([("k", [self.touch("A.sfc")], None, False)], "{nope}")
        self.assertIn("unknown field", row["status"])

    def test_apply_swaps_and_fixes_cue(self):
        cue = self.touch("Old (USA).cue", 'FILE "Old (USA) (Track 1).bin" BINARY\n')
        bin_ = self.touch("Old (USA) (Track 1).bin")
        x, y = self.touch("x.sfc", "x"), self.touch("y.sfc", "y")
        done, failed = rs.apply_renames([(cue, cue.replace("Old", "New")), (bin_, bin_.replace("Old", "New")),
                                         (x, y), (y, x)])
        self.assertEqual(failed, [])
        self.assertEqual(len(done), 4)
        with open(os.path.join(self.dir, "New (USA).cue")) as f:
            self.assertIn('"New (USA) (Track 1).bin"', f.read())
        with open(x) as f:
            self.assertEqual(f.read(), "y")


class WriteJson(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = os.path.join(self.dir, "c.json")

    def test_writes(self):
        fsutil.write_json(self.path, {"a": 1}, indent=1)
        with open(self.path) as f:
            self.assertEqual(json.load(f), {"a": 1})

    def test_failed_write_keeps_old_file_and_leaves_no_temp(self):
        fsutil.write_json(self.path, {"a": 1})
        with self.assertRaises(TypeError):
            fsutil.write_json(self.path, {"a": object()})
        with open(self.path) as f:
            self.assertEqual(json.load(f), {"a": 1})
        self.assertEqual(os.listdir(self.dir), ["c.json"])


class LaunchBox(unittest.TestCase):
    """Builds the sandbox's small database into a temp cache."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cache = os.path.join(cls.dir, "cache", "launchbox")
        cls.patches = [mock.patch.object(lb, "APP_DIR", cls.dir), mock.patch.object(lb, "CACHE", cache),
                       mock.patch.object(lb, "META", os.path.join(cache, "_meta.json")),
                       mock.patch.object(lb, "MANUAL", os.path.join(cls.dir, "matches.json"))]
        for p in cls.patches:
            p.start()
        lb.update(sandbox.build_metadata_zip(os.path.join(cls.dir, "Metadata.zip")), progress=lambda m: None)

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()
        shutil.rmtree(cls.dir)

    def test_platforms(self):
        self.assertIn(sandbox.SNES, lb.platforms())
        self.assertEqual(lb.resolve_platform("snes", None), sandbox.SNES)
        self.assertEqual(lb.resolve_platform("psx", "Sony PlayStation"), sandbox.PSX)

    def test_matching(self):
        m = lb.Matcher(sandbox.SNES)
        self.assertTrue(m.ok)
        gid, g, kind = m.match("Chrono Trigger")
        self.assertEqual((g["n"], kind), ("Chrono Trigger", "exact"))
        self.assertEqual(m.match("Final_Fantasy_III_USA")[1]["n"], "Final Fantasy III")  # scene clean-up
        self.assertEqual(m.match("Zelda no Densetsu")[1]["n"], "The Legend of Zelda: A Link to the Past")  # alt
        self.assertEqual(m.match("Barbie - Super Model")[1]["n"], "Barbie: Super Model")
        self.assertEqual(m.match("Completely Unknown"), (None, None, None))

    def test_manual_pick_wins_and_is_saved(self):
        gid = lb.Matcher(sandbox.SNES).match("Chrono Trigger")[0]
        lb.set_manual(sandbox.SNES, "Mystery Cart", gid)
        self.addCleanup(lb.set_manual, sandbox.SNES, "Mystery Cart", None, clear=True)
        self.assertEqual(lb.Matcher(sandbox.SNES).match("Mystery Cart")[2], "manual")
        lb.copy_manual(sandbox.SNES, {"Mystery Cart": "Mystery Cart 2"})
        self.assertEqual(lb.load_manual()[sandbox.SNES]["Mystery Cart 2"], gid)

    def test_details(self):
        gid = lb.Matcher(sandbox.SNES).match("Super Metroid")[0]
        self.assertIn("Super Metroid", lb.load_details(sandbox.SNES)[gid]["o"])

    def test_failed_download_leaves_no_temp_file(self):
        before = set(os.listdir(tempfile.gettempdir()))
        with mock.patch.object(lb.urllib.request, "urlopen", side_effect=OSError("network down")):
            with self.assertRaises(OSError):
                lb.update(progress=lambda m: None)
        self.assertEqual(set(os.listdir(tempfile.gettempdir())) - before, set())


class Updater(unittest.TestCase):
    """Zip copies (not a git checkout) follow releases; GitHub's API is faked."""
    LOCAL = "a" * 40

    def check(self, api):
        def fake(path):
            r = api(path)
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch.object(updater, "is_git", return_value=False), \
                mock.patch.object(updater, "local_sha", return_value=self.LOCAL), \
                mock.patch.object(updater, "_api", side_effect=fake) as m:
            return updater.check(), [c.args[0] for c in m.call_args_list]

    @staticmethod
    def http(code):
        return updater.urllib.error.HTTPError("u", code, "x", {}, None)

    def release(self, path, status="ahead", ahead=2):
        if path == "releases/latest":
            return {"tag_name": "v2026.10.09", "body": "## Changes"}
        return {"status": status, "ahead_by": ahead,
                "commits": [{"commit": {"message": "Old\n\nbody"}}, {"commit": {"message": "New"}}]}

    def test_newer_release(self):
        res, calls = self.check(self.release)
        self.assertEqual(calls[1], f"compare/{self.LOCAL}...v2026.10.09")
        self.assertEqual((res["behind"], res["tag"], res["commits"]), (2, "v2026.10.09", ["New", "Old"]))
        self.assertEqual(res["notes"], "## Changes")

    def test_up_to_date_or_newer_than_the_release(self):
        for status in ("identical", "behind"):
            res, _ = self.check(lambda p: self.release(p, status, 0))
            self.assertEqual(res["behind"], 0, status)

    def test_no_release_yet_follows_main(self):
        res, calls = self.check(lambda p: self.http(404) if p == "releases/latest" else self.release(p))
        self.assertEqual(calls[1], f"compare/{self.LOCAL}...main")
        self.assertIsNone(res["tag"])
        self.assertEqual(res["behind"], 2)

    def test_unknown_version(self):
        res, _ = self.check(lambda p: self.http(404) if p.startswith("compare") else self.release(p))
        self.assertIsNone(res["behind"])

    def test_offline(self):
        with self.assertRaises(RuntimeError):
            self.check(lambda p: updater.urllib.error.URLError("no network"))

    def test_apply_downloads_the_release(self):
        with mock.patch.object(updater, "is_git", return_value=False), \
                mock.patch.object(updater.urllib.request, "urlopen", side_effect=OSError("stop")) as m, \
                mock.patch.object(updater, "APP_DIR", tempfile.mkdtemp()) as d:
            self.addCleanup(shutil.rmtree, d)
            with self.assertRaises(RuntimeError):
                updater.apply("v2026.10.09")
            self.assertTrue(m.call_args.args[0].full_url.endswith("/zip/refs/tags/v2026.10.09"))
            with self.assertRaises(RuntimeError):
                updater.apply()
            self.assertTrue(m.call_args.args[0].full_url.endswith("/zip/refs/heads/main"))


class Windows(unittest.TestCase):
    """Windows code paths, checked on any system by pretending (and for real on the Windows CI runner)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def test_emulator_data_on_another_drive(self):
        self.assertEqual(rs.held_rel(r"D:\Emu\rpcs3\dev_hdd0\game\X", r"C:\Users\me", ntpath),
                         r"external\D\Emu\rpcs3\dev_hdd0\game\X")
        self.assertEqual(rs.held_rel(r"C:\Users\me\storage\x", r"C:\Users\me", ntpath), r"storage\x")
        self.assertEqual(rs.held_rel(r"\\nas\share\x", r"C:\Users\me", ntpath), r"external\nas\share\x")
        # same answers as before on Linux
        self.assertEqual(rs.held_rel("/home/me/.var/x", "/home/me/retrodeck", posixpath), "external/home/me/.var/x")
        self.assertEqual(rs.held_rel("/home/me/retrodeck/storage/x", "/home/me/retrodeck", posixpath), "storage/x")

    def test_es_de_running_uses_tasklist(self):
        out = '"System Idle Process","0","Services","0","8 K"\n"ES-DE.exe","4242","Console","1","200,000 K"\n'
        with mock.patch.object(scraper, "is_windows", return_value=True), \
                mock.patch.object(scraper.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0, out, "")) as run:
            self.assertTrue(scraper.es_de_running())
            self.assertEqual(run.call_args.args[0][0], "tasklist")
            run.return_value = subprocess.CompletedProcess([], 0, out.replace("ES-DE.exe", "notepad.exe"), "")
            self.assertFalse(scraper.es_de_running())
            run.side_effect = OSError("no tasklist")
            self.assertFalse(scraper.es_de_running())

    def test_es_de_running_without_proc(self):
        with mock.patch.object(scraper, "is_windows", return_value=False), \
                mock.patch.object(scraper.os, "listdir", side_effect=FileNotFoundError("/proc")):
            self.assertFalse(scraper.es_de_running())  # macOS: no /proc, no crash

    def test_start_menu_shortcut(self):
        appdata = os.path.join(self.dir, "Roaming")

        def powershell(cmd, env, **kw):
            self.assertEqual(cmd[0], "powershell")
            with open(env["RS_LNK"], "wb") as f:  # what WScript.Shell would write, roughly
                f.write(b"L\0\0\0" + env["RS_DIR"].encode("utf-16-le"))
            self.env = env
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with mock.patch.object(desktop, "is_windows", return_value=True), \
                mock.patch.dict(os.environ, {"APPDATA": appdata}), \
                mock.patch.object(fsutil.subprocess, "run", side_effect=powershell):
            self.assertEqual(desktop.menu_label(), "Add to Start menu")
            self.assertFalse(desktop.is_installed())
            path = desktop.install()
            self.assertEqual(path, os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs",
                                                "RetroShelf.lnk"))
            self.assertTrue(desktop.is_installed())
            self.assertTrue(self.env["RS_ICON"].endswith("icon.ico") and os.path.exists(self.env["RS_ICON"]))
            self.assertIn("retroshelf.py", self.env["RS_ARGS"])

    def test_start_menu_shortcut_failure_is_an_oserror(self):
        with mock.patch.object(desktop, "is_windows", return_value=True), \
                mock.patch.dict(os.environ, {"APPDATA": self.dir}), \
                mock.patch.object(fsutil.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 1, "", "blocked by policy")):
            with self.assertRaisesRegex(OSError, "blocked by policy"):
                desktop.install()

    def test_windowed_python(self):
        for name in ("python.exe", "pythonw.exe"):
            open(os.path.join(self.dir, name), "w").close()
        with mock.patch.object(desktop.sys, "executable", os.path.join(self.dir, "python.exe")):
            self.assertEqual(desktop.windowed_python(), os.path.join(self.dir, "pythonw.exe"))

    def test_restart_starts_a_new_process(self):
        with mock.patch.object(updater, "is_windows", return_value=True), \
                mock.patch.object(updater.subprocess, "Popen") as popen, \
                mock.patch.object(updater.os, "_exit", side_effect=SystemExit) as exit_, \
                mock.patch.object(updater.os, "execv") as execv:
            with self.assertRaises(SystemExit):
                updater.restart()
            self.assertTrue(popen.call_args.args[0][1].endswith("retroshelf.py"))
            exit_.assert_called_once_with(0)
            execv.assert_not_called()

    def test_names_windows_cant_use(self):
        rows = rs.plan_renames([("k", [os.path.join(self.dir, "x (USA).sfc")], None, False)], "CON")
        self.assertEqual(rows[0]["status"], "name Windows can't use")
        rows = rs.plan_renames([("k", [os.path.join(self.dir, "Game (USA).sfc")], None, False)], "Con Man")
        self.assertEqual(rows[0]["status"], "rename")
        long_name = "A" * 300
        with mock.patch.object(rs, "is_windows", return_value=True):
            rows = rs.plan_renames([("k", [os.path.join(self.dir, "x.sfc")], None, False)], long_name)
        self.assertEqual(rows[0]["status"], "path too long for Windows")


class NpsLayouts(unittest.TestCase):
    """Where RPCS3 / Vita3K keep their data: RetroDECK on Linux, standalone builds on Windows."""

    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.roms = self.mkdir("ES-DE", "ROMs")  # ES-DE portable: ES-DE/ROMs next to ES-DE/Emulators
        self.addCleanup(nps.emulator_dirs.clear)
        self.win = mock.patch.object(nps, "is_windows", return_value=True)

    def mkdir(self, *parts):
        p = os.path.join(self.dir, *parts)
        os.makedirs(p, exist_ok=True)
        return p

    def touch(self, *parts, text=""):
        p = os.path.join(self.dir, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_rpcs3_in_es_de_portable_emulators_folder(self):
        rpcs3 = os.path.dirname(self.touch("ES-DE", "Emulators", "RPCS3-v0.0.34", "rpcs3.exe"))
        with self.win:
            self.assertEqual(nps.find_emulator("rpcs3", self.roms), rpcs3)
            self.assertIsNone(nps.emulator_problem("ps3", self.roms))
            self.assertEqual(nps.rpcs3_hdd0(self.roms), os.path.join(rpcs3, "dev_hdd0"))  # RPCS3's default
            os.makedirs(os.path.join(rpcs3, "portable"))
            self.assertEqual(nps.rpcs3_hdd0(self.roms), os.path.join(rpcs3, "portable", "dev_hdd0"))

    def test_rpcs3_vfs_and_games_yml(self):
        rpcs3 = os.path.dirname(self.touch("Emu", "rpcs3", "rpcs3.exe"))
        hdd0 = self.mkdir("Big drive", "hdd0")
        self.touch("Emu", "rpcs3", "config", "vfs.yml",
                   text=f'$(EmulatorDir): ""\n/dev_hdd0/: {hdd0.replace(os.sep, "/")}/\n'
                        "/dev_flash/: $(EmulatorDir)dev_flash/\n")
        self.touch("Emu", "rpcs3", "config", "games.yml", text="BLUS30443: D:/PS3/Demon's Souls/\n")
        self.mkdir("Big drive", "hdd0", "game", "NPUB30133")
        self.touch("Big drive", "hdd0", "game", "NPUB30133", "PARAM.SFO")
        nps.emulator_dirs["rpcs3"] = rpcs3  # picked by hand
        with self.win:
            self.assertEqual(nps.rpcs3_hdd0(self.roms), hdd0)
            self.assertEqual(nps.rpcs3_vfs("/dev_flash/", self.roms), os.path.join(rpcs3, "dev_flash"))
            self.assertEqual(nps.owned_ids("ps3", self.roms), {"NPUB30133", "BLUS30443"})

    def test_missing_emulator(self):
        nps.emulator_dirs["rpcs3"] = self.mkdir("not rpcs3")
        with self.win, mock.patch.object(nps.shutil, "which", return_value=None):
            self.assertIsNone(nps.find_emulator("rpcs3", self.roms))
            self.assertIn("rpcs3.exe", nps.emulator_problem("ps3", self.roms))
            self.assertIn("RPCS3 wasn't found", nps.firmware_problem("ps3", self.roms))
            self.assertIn("Vita3K wasn't found", nps.emulator_problem("psvita", self.roms))
            with self.assertRaisesRegex(RuntimeError, "Vita3K wasn't found"):
                nps.install({"console": "PSV"}, "x.pkg", self.roms, print, print, lambda: False)
        with mock.patch.object(nps, "is_windows", return_value=False):
            self.assertIsNone(nps.emulator_problem("ps3", self.roms))  # Linux uses RetroDECK's, nothing to find

    def test_vita3k_paths(self):
        vita = os.path.dirname(self.touch("ES-DE", "Emulators", "Vita3K", "Vita3K.exe"))
        appdata = self.mkdir("AppData", "Roaming")
        with self.win, mock.patch.dict(os.environ, {"APPDATA": appdata}):
            self.assertEqual(nps.vita3k_pref(self.roms), os.path.join(appdata, "Vita3K", "Vita3K"))
            self.touch("ES-DE", "Emulators", "Vita3K", "config.yml", text="pref-path: 'E:\\Vita'\n")
            self.assertEqual(nps.vita3k_pref(self.roms), os.path.normpath("E:\\Vita"))
            os.makedirs(os.path.join(vita, "portable"))
            self.assertEqual(nps.vita3k_pref(self.roms), os.path.join(vita, "portable", "fs"))
            self.assertEqual(nps.vita3k_command("pkgs", self.roms), [os.path.join(vita, "Vita3K.exe")])

    def test_linux_retrodeck_unchanged(self):
        flatpak = self.mkdir("flatpak")
        roms = self.mkdir("retrodeck", "roms")
        with mock.patch.object(nps, "is_windows", return_value=False), \
                mock.patch.object(nps, "FLATPAK_CONFIG", flatpak):
            self.assertEqual(nps.rpcs3_hdd0(roms), os.path.join(self.dir, "retrodeck", "storage", "rpcs3", "dev_hdd0"))
            self.assertEqual(nps.vita3k_pref(roms), os.path.join(self.dir, "retrodeck", "storage", "psvita", "Vita3K"))
            self.touch("flatpak", "rpcs3", "vfs.yml", text="/dev_hdd0: x\n/dev_hdd0/: /mnt/hdd0/\n")
            self.assertEqual(nps.rpcs3_hdd0(roms), os.path.normpath("/mnt/hdd0"))

    def test_shortcut_game_id_and_linked_data(self):
        lnk = os.path.join(self.roms, "ps3", "Braid (USA).lnk")
        os.makedirs(os.path.dirname(lnk))
        args = '--no-gui "%RPCS3_GAMEID%:NPUB30133"'.encode("utf-16-le")
        with open(lnk, "wb") as f:  # strings in a .lnk can start at an odd offset
            f.write(b"L\0\0\0\x01" + args + b"\0\0")
        desktop_file = self.touch("ES-DE", "ROMs", "ps3", "Other.desktop",
                                  text='Exec=x --no-gui "%%RPCS3_GAMEID%%:NPEB00001"\n')
        self.assertEqual(nps.shortcut_game_id(lnk), "NPUB30133")
        self.assertEqual(nps.shortcut_game_id(desktop_file), "NPEB00001")
        self.assertEqual(nps.ps3_shortcut(self.roms, "NPUB30133"), "Braid (USA).lnk")
        self.touch("ES-DE", "Emulators", "RPCS3", "rpcs3.exe")
        game = self.mkdir("ES-DE", "Emulators", "RPCS3", "dev_hdd0", "game", "NPUB30133")
        rap = self.touch("ES-DE", "Emulators", "RPCS3", "dev_hdd0", "home", "00000001", "exdata",
                         "UP0001-NPUB30133_00-BRAID0000000001.rap")
        with self.win:
            self.assertEqual(nps.linked_data("ps3", lnk, self.roms), [game, rap])


def hh_entry(slug="pong", title="Pong: Deluxe", platform="GB", license=None, tags=(), files=None, **kw):
    """A Homebrew Hub manifest like the API returns."""
    e = {"slug": slug, "title": title, "platform": platform, "typetag": "game", "tags": list(tags),
         "developer": [{"name": "Ann"}, "Bo"], "basepath": "database", "screenshots": ["shot.png"],
         "files": files if files is not None else [{"filename": "game.gb", "playable": True, "default": True}]}
    if license:
        e["gameLicense"] = license
    e.update(kw)
    return e


class HomebrewHub(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.roms = os.path.join(self.dir, "roms")
        self.dl = os.path.join(self.dir, "Downloads")
        os.makedirs(self.dl)

    def write(self, folder, name, data=b"ROM"):
        p = os.path.join(folder, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_who_may_be_downloaded_directly(self):
        self.assertTrue(hb.can_download(hh_entry(license="MIT")))
        self.assertTrue(hb.can_download({"slug": "x", "license": "mit"}))  # what the API calls it
        self.assertEqual(hb.license_text({"slug": "x", "license": "Zlib"}), "Zlib")
        # licence texts seen in the real catalogue
        for ok in ("MIT", "GPL-3.0-only", "GPL-3.0", "GPL-3.0-or-later", "ZLib", "CC-BY-SA 4.0", "CC-BY-NC-ND-4.0",
                   "CC-BY-NC-SA", "MIT / CC-BY-4.0 (Assets)", "Unlicense", "GPL-2.0-or-later", "BSD-3-Clause"):
            self.assertTrue(hb.open_license(ok), ok)
        for no in ("", "CC-BY ish", "All rights reserved", "Proprietary", "MIT / proprietary assets", "Freeware"):
            self.assertFalse(hb.open_license(no), no)
        self.assertTrue(hb.can_download(hh_entry(license={"spdx": "GPL-3.0-only"})))
        self.assertTrue(hb.can_download(hh_entry(tags=["Open Source"])))
        self.assertTrue(hb.can_download(hh_entry(**{"third-party": ["retroshelf"]})))
        self.assertFalse(hb.can_download(hh_entry()))  # no license: the author decides, so via the website
        self.assertFalse(hb.can_download(hh_entry(**{"third-party": ["sameboy"]})))
        self.assertFalse(hb.can_download(hh_entry(license="MIT", **{"use-requirements": {"disable-downloads": True}})))
        with self.assertRaises(PermissionError):
            hb.install(hh_entry(), self.roms)

    def test_entry_helpers(self):
        files = [{"filename": "manual.pdf"}, {"filename": "a.gb", "playable": True},
                 {"filename": "b.gb", "playable": True, "default": True}]
        self.assertEqual(hb.rom_file(hh_entry(files=files))["filename"], "b.gb")
        self.assertEqual(hb.rom_file(hh_entry(files=[{"filename": "x.gb"}]))["filename"], "x.gb")
        self.assertIsNone(hb.rom_file(hh_entry(files=[])))
        e = hh_entry(slug="my game")
        self.assertEqual(hb.file_url(e, "a b.gb"), "https://hh3.gbdev.io/static/database/entries/my game/a%20b.gb")
        self.assertEqual(hb.page_url(e), "https://hh.gbdev.io/game/my%20game")
        self.assertEqual(hb.developer_text(e["developer"]), "Ann, Bo")
        self.assertEqual(hb.rom_name(e, ".GB"), "Pong - Deluxe (Homebrew).gb")
        self.assertEqual(hb.es_de_fields(hh_entry(date="2021-3"))["releasedate"], "20210301T000000")
        self.assertEqual(hb.es_de_fields(hh_entry())["developer"], "Ann, Bo")

    def test_catalog_is_cached(self):
        api = mock.Mock(return_value={"entries": [hh_entry(), hh_entry(slug="gba", platform="GBA")]})
        with mock.patch.object(hb, "CACHE", self.dir), mock.patch.object(hb, "_get_json", api):
            self.assertEqual([e["slug"] for e in hb.load_catalog("GB")], ["pong"])  # other platforms dropped
            self.assertIn("platform=GB", api.call_args.args[0])
            api.return_value = {"entries": [{"slug": "noplat", "title": "No Platform"}]}
            self.assertEqual(hb.load_catalog("NES", refresh=True)[0]["platform"], "NES")  # filed under nes/
            hb.load_catalog("GB")
            self.assertEqual(api.call_count, 2)
            self.assertLess(hb.cached_age("GB"), 1)
            hb.load_catalog("GB", refresh=True)
            self.assertEqual(api.call_count, 3)

    def test_file_rom_and_zip(self):
        e = hh_entry()
        path = hb.file_rom(self.write(self.dl, "game.gb"), e, self.roms)
        self.assertEqual(path, os.path.join(self.roms, "gb", "Pong - Deluxe (Homebrew).gb"))
        self.assertEqual(hb.installed_path(e, self.roms), path)
        with self.assertRaises(FileExistsError):
            hb.file_rom(self.write(self.dl, "game.gb"), e, self.roms)
        zipped = self.write(self.dl, "racer.zip", self._zip({"readme.txt": "hi", "dist/racer.gbc": b"GBC ROM"}))
        e2 = hh_entry(slug="racer", title="Racer", platform="GBC", files=[{"filename": "racer.gbc"}])
        with self.assertRaises(ValueError):
            hb.file_rom(self.write(self.dl, "empty.zip", self._zip({"readme.txt": "hi"})), e2, self.roms)
        path = hb.file_rom(zipped, e2, self.roms)
        self.assertEqual(path, os.path.join(self.roms, "gbc", "Racer (Homebrew).gbc"))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"GBC ROM")
        self.assertFalse(os.path.exists(zipped))

    @staticmethod
    def _zip(members):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n, d in members.items():
                z.writestr(n, d)
        return buf.getvalue()

    def test_install_open_source_game(self):
        class Resp(io.BytesIO):
            headers = {"Content-Length": "3"}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        seen = []
        with mock.patch.object(hb.urllib.request, "urlopen", side_effect=lambda req, timeout: (
                seen.append(req.full_url), Resp(b"ROM"))[1]):
            path = hb.install(hh_entry(license="MIT"), self.roms)
        self.assertEqual(seen, ["https://hh3.gbdev.io/static/database/entries/pong/game.gb"])
        self.assertEqual(os.path.basename(path), "Pong - Deluxe (Homebrew).gb")

    def test_watcher_files_what_the_user_downloads(self):
        self.write(self.dl, "old.gb")  # there before: never touched
        w = downloads.DownloadWatcher(self.dl, self.roms)
        self.assertEqual(w.poll(), [])
        a = hh_entry()
        b = hh_entry(slug="racer", title="Racer", platform="GBC", files=[{"filename": "racer.gbc"}])
        w.expect(hb.want(a))
        w.expect(hb.want(b))
        w.expect(hb.want(a))
        self.assertEqual(len(w.waiting), 2)
        self.write(self.dl, "game (1).gb.part")
        self.write(self.dl, "notes.txt")
        self.assertEqual(w.poll(), [])
        self.write(self.dl, "game (1).gb")  # the browser renamed a repeat download
        self.assertEqual(w.poll(), [])  # first sight: wait until its size settles
        [(want, path)] = w.poll()
        self.assertEqual((want["id"], path), ("pong", os.path.join(self.roms, "gb", "Pong - Deluxe (Homebrew).gb")))
        self.assertTrue(os.path.exists(os.path.join(self.dl, "old.gb")))
        self.assertEqual([x["id"] for x in w.waiting], ["racer"])
        self.write(self.dl, "racer.gbc")
        w.poll()
        [(want, path)] = w.poll()
        self.assertEqual(path, os.path.join(self.roms, "gbc", "Racer (Homebrew).gbc"))
        self.assertEqual(w.waiting, [])

    def test_watcher_leaves_ambiguous_files_alone(self):
        w = downloads.DownloadWatcher(self.dl, self.roms)
        w.expect(hb.want(hh_entry(slug="a", files=[{"filename": "a.gb"}])))
        w.expect(hb.want(hh_entry(slug="b", files=[{"filename": "b.gb"}])))
        self.write(self.dl, "something-else.gb")  # two GB games waiting: can't tell which this is
        w.poll()
        self.assertEqual(w.poll(), [])
        self.assertEqual(len(w.waiting), 2)
        w.cancel("a")
        self.assertEqual([x["id"] for x in w.waiting], ["b"])
        w.cancel()
        self.assertEqual(w.waiting, [])

    def test_downloads_dir(self):
        cfg = os.path.join(self.dir, "cfg")
        os.makedirs(cfg)
        self.write(cfg, "user-dirs.dirs", b'XDG_DOWNLOAD_DIR="$HOME/Telechargements"\n')
        with mock.patch.object(downloads, "is_windows", return_value=False), \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": cfg}):
            self.assertEqual(downloads.downloads_dir(), os.path.join(os.path.expanduser("~"), "Telechargements"))
        with mock.patch.object(downloads, "is_windows", return_value=True):
            self.assertEqual(downloads.downloads_dir(), os.path.join(os.path.expanduser("~"), "Downloads"))


def itch_feed(*games, extra=""):
    """An itch.io browse feed (RSS 2.0, with the extra fields itch.io adds)."""
    items = "".join(
        f"<item><title>{t}</title><plainTitle>{t}</plainTitle><link>https://{a}.itch.io/{t.lower().replace(' ', '-')}"
        f"</link><guid>x</guid><pubDate>Sat, 01 May 2021 10:00:00 GMT</pubDate><price>{p}</price>"
        f"<imageurl>https://img.itch.zone/{t[:3]}.png</imageurl>"
        f"<description><![CDATA[<img src=\"https://img.itch.zone/{t[:3]}.png\"/><p>About {t} &amp; more.</p>]]>"
        f"</description></item>" for t, a, p in games)
    head = '<?xml version="1.0"?><rss version="2.0"><channel><title>itch</title>'
    return f"{head}{items}{extra}</channel></rss>".encode()


class ItchIo(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.roms = os.path.join(self.dir, "roms")
        self.dl = os.path.join(self.dir, "Downloads")
        os.makedirs(self.dl)
        p = mock.patch.object(itch, "CACHE", os.path.join(self.dir, "cache"))
        p.start()
        self.addCleanup(p.stop)

    def write(self, name, data=b"ROM"):
        p = os.path.join(self.dl, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_parse_feed(self):
        [g] = itch.parse_feed(itch_feed(("Tiny Quest", "gee", "$0.00")))
        self.assertEqual(g["url"], "https://gee.itch.io/tiny-quest")
        self.assertEqual((g["title"], g["author"], g["year"]), ("Tiny Quest", "gee", "2021"))
        self.assertEqual(g["image"], "https://img.itch.zone/Tin.png")
        self.assertEqual(g["description"], "About Tiny Quest & more.")
        self.assertTrue(itch.is_free(g))
        self.assertFalse(itch.is_free({"price": "$2.99"}))
        self.assertTrue(itch.is_free({"price": ""}))

    def test_catalog_pages_merges_and_caches(self):
        page1 = itch_feed(*[(f"Game {i:02}", "dev", "") for i in range(12)])
        page2 = itch_feed(("Game 00", "dev", ""), ("Paid", "dev", "$5.00"), ("Last", "dev", "0"))
        urls = []

        def fetch(url, timeout=30):
            urls.append(url)
            if "game-boy" in url and "page=2" in url:
                return page2
            if "game-boy" in url and "page" not in url:
                return page1
            return itch_feed()

        with mock.patch.object(itch, "_fetch", side_effect=fetch):
            games = itch.load_catalog("gb")
            self.assertEqual(len(games), 13)  # 12 + "Last"; the repeat merged, the paid one dropped
            self.assertEqual({g["system"] for g in games}, {"gb"})
            self.assertIn("https://itch.io/games/price-free/tag-game-boy.xml", urls)
            self.assertIn("https://itch.io/games/price-free/made-with-gb-studio.xml", urls)
            n = len(urls)
            itch.load_catalog("gb")
            self.assertEqual(len(urls), n)  # from the cache
            self.assertLess(itch.cached_age("gb"), 1)

    def test_blocked_by_cloudflare(self):
        err = itch.urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
        with mock.patch.object(itch, "_fetch", side_effect=err):
            with self.assertRaises(itch.Blocked):
                itch.load_catalog("gb", refresh=True)
        with mock.patch.object(itch, "_fetch", side_effect=itch.urllib.error.URLError("offline")):
            with self.assertRaises(itch.urllib.error.URLError):
                itch.load_catalog("nes", refresh=True)

    def test_open_game_is_filed_with_its_title(self):
        g = dict(itch.parse_feed(itch_feed(("Tiny Quest", "gee", "")))[0], system="nes")
        w = downloads.DownloadWatcher(self.dl, self.roms)
        w.expect(itch.want(g))
        self.write("tinyquest_v1.0.nes")
        w.poll()
        [(want, path)] = w.poll()
        self.assertEqual(path, os.path.join(self.roms, "nes", "Tiny Quest (Homebrew).nes"))
        self.assertEqual(itch.installed_path(g, self.roms), path)

    def test_browsing_freely_files_any_rom_for_the_system(self):
        w = downloads.DownloadWatcher(self.dl, self.roms)
        w.expect(itch.browse_want("gba"))
        self.write("cool_game-v2 (1).gba")
        self.write("windows-build.zip", HomebrewHub._zip({"game.exe": b"MZ"}))  # not a GBA game: left alone
        self.write("screenshot.png")
        w.poll()
        [(want, path)] = w.poll()
        self.assertEqual(path, os.path.join(self.roms, "gba", "cool game-v2 (Homebrew).gba"))
        self.assertTrue(os.path.exists(os.path.join(self.dl, "windows-build.zip")))
        self.assertTrue(os.path.exists(os.path.join(self.dl, "screenshot.png")))
        self.assertEqual(len(w.waiting), 1)  # keeps watching while browsing
        self.write("other.gba")
        w.poll()
        self.assertEqual(len(w.poll()), 1)

    def test_a_game_waits_before_free_browsing(self):
        w = downloads.DownloadWatcher(self.dl, self.roms)
        w.expect(itch.browse_want("nes"))
        g = dict(itch.parse_feed(itch_feed(("Tiny Quest", "gee", "")))[0], system="nes")
        w.expect(itch.want(g))
        self.write("x.nes")
        w.poll()
        [(want, path)] = w.poll()
        self.assertEqual(os.path.basename(path), "Tiny Quest (Homebrew).nes")
        self.assertEqual([x["id"] for x in w.waiting], ["any:nes"])

    def test_pico8_carts(self):
        self.assertEqual(downloads.rom_ext("celeste.p8.png", downloads.SYSTEM_EXTS["pico8"]), ".p8.png")
        self.assertIsNone(downloads.rom_ext("cover.png", downloads.SYSTEM_EXTS["pico8"]))
        self.assertEqual(downloads.stem_from_download("celeste.p8.png", downloads.SYSTEM_EXTS["pico8"]), "celeste")


PDROMS_ARTICLE = """
\t\t<article class="file_post">
\t\t<div class="post-title">
\t\t\t<a href="https://pdroms.de/files/nintendo-entertainment-system-nes-famicom/{slug}" title="{title}">
\t\t\t\t{title}\t\t\t</a>
\t\t</div><!--post-title-->
\t\t<div class="file-meta-data">
\t\t\tAdded May 28, 2014, Under: <a href="https://pdroms.de/files/nintendo-entertainment-system-nes-famicom/">Nintendo
 Entertainment System (Famicom)</a> | <a href="https://pdroms.de/files/system/games" rel="tag">Games</a>\t\t</div>
\t\t\t\t\t<a href="https://pdroms.de/files/nintendo-entertainment-system-nes-famicom/{slug}" aria-label="{title}">
\t\t\t\t<img width="256" height="150" src="https://pdroms.de/wp-content/uploads/2014/05/{slug}-256x150.png"
 class="thumbs-in-files wp-post-image" alt="" decoding="async" loading="lazy" />\t\t\t</a>
\t\t<div class="author-box-small">
\t\t\tBy <a href="https://pdroms.de/author/kojote" rel="author">Shahzad Sahaib</a>\t\t</div><!--author-box-->
\t</article>"""


def pdroms_page(titles, total):
    """A PDRoms games page as the site serves it (trimmed)."""
    arts = "".join(PDROMS_ARTICLE.format(slug=t.lower().replace(" ", "-"), title=t) for t in titles)
    return (f'<main id="main-content"><h1>NES Games <span class="entry-count">({total})</span></h1>'
            f'<a href="?show_restricted=1" class="card file-restricted-toggle">Show +18 / copyright-restricted files'
            f'</a><div class="grid">{arts}</div></main>')


PDROMS_FILE = """<h1 class="post-title-big"><a href="https://pdroms.de/files/nes/1k2p" title="1k2p">1k2p</a></h1>
<dl class="pdr-fact-box">
\t\t\t\t<div class="pdr-fact-box-row">
\t\t\t<dt>Author</dt>
\t\t\t<dd>Sly Dog Studios</dd>
\t\t</div>
\t\t\t\t<div class="pdr-fact-box-row">
\t\t\t<dt>Version</dt>
\t\t\t<dd>v1</dd>
\t\t</div>
\t</dl>
<div class="file-card">
\t<div class="file-card-body">
\t\t<div class="file_thumb_single"><img decoding="async" src="https://pdroms.de/wp-content/uploads/2014/05/1k2p.png"
 alt="" /></div>
<p><em>Sly Dog Games</em> made up the very basic version of Pong, named <strong>1k2p</strong>. It&#8217;s a two player
 only game.<br style="clear:both;" /></p>
\t\t\t\t\t</div><!--file-card-body-->
\t\t<div class="download_link file-card-download">
\t\t\t\t<a href="https://pdroms.de/?__df=540e57153a" class="download-btn">Download 1k2p</a>"""

MAMEDEV_INDEX = """<div class="panel-heading">Exidy Games</div>
\t\t<table class="table">
\t\t\t<tr>
\t\t\t\t<td class="link" width="20%">
\t\t\t\t\t<a href="circus"><img src="circus/circus-thumb.png" width="80" height="60" alt="Circus" /></a><br/>
\t\t\t\t\t<a href="circus">Circus</a><br/>
\t\t\t\t\t&copy;1977 Exidy
\t\t\t\t</td>
\t\t\t\t<td class="link" width="20%">
\t\t\t\t\t<a href="witchcrd"><img src="witchcrd/witchcrd-thumb.png" width="80" height="60" alt="Witch Card" /></a><br/>
\t\t\t\t\t<a href="witchcrd">Witch Card</a><br/>
\t\t\t\t\t&copy;1991 Video Klein
\t\t\t\t</td>
\t\t\t</tr>
\t\t</table>"""


def mamedev_page(title, zips):
    links = "".join(f'<h4><a href="{z}" onclick="return isChecked();" title="Download now" class="btn-success">'
                    f'Download the {title} ROM images</a></h4>' for z in zips)
    return f"""<div class="container">
\t<h1 class="page-header" style="text-align: center">{title} (Exidy, 1977)</h1>
\t<p>
\tThanks to the kind generosity of H.R. Kauffman, the original ROM images for <b>{title}</b> have been made
\t\t\t\t\t\t\tavailable for free, non-commercial use.
\t</p>
\t<p>
\tBefore downloading, you must acknowledge that you understand these images are to be used only for
\tnon-commercial purposes. Do this by checking the box below the download button.
\t</p>
\t<script language="JavaScript" type="text/javascript">function isChecked() {{ return true; }}</script>
\t<center><div class="btn btn-success">{links}
\t\t\t<form name="agreeform" action="#"><input type="checkbox" name="agree" />
\t\t\t\t<label for="agree">I understand that these ROM images are for non-commercial use only</label></form>
\t</div></center>
\t<h2>Description</h2>
\t<p>
\t<b>{title}</b> was one of the first games produced by Exidy
\tthat used a CPU (6502).
\t</p>
\t<p>At least 13,000 units were produced.</p>
\t<table width="100%"><tr><th colspan="2">Scoring</th></tr><tr><td>Jump</td><td>10 points</td></tr></table>
\t<div>
\t\t<h2>Screenshots</h2>
\t\t<img src="0000.png" width="320" height="240" alt="Exidy Screenshot" />
\t</div>
\t<h2>Additional Images</h2>
\t<img src="circus-cabinet.jpg" width="300" height="547" alt="Exidy cabinet" />
</div>"""


def fsutil_md5(data):
    import hashlib
    return hashlib.md5(data).hexdigest()


class Frontend(unittest.TestCase):
    """Finding and setting up RetroDECK / ES-DE (lib/frontend.py)."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        p = mock.patch.dict(os.environ, {"HOME": self.home, "USERPROFILE": self.home})
        p.start()
        self.addCleanup(p.stop)

    def retrodeck_config(self, rd_home, lock=True):
        cfg = frontend.rd_config_dir()
        os.makedirs(cfg, exist_ok=True)
        with open(os.path.join(cfg, "retrodeck.json"), "w", encoding="utf-8") as f:
            json.dump({"version": "0.10.0", "paths": {"rd_home_path": rd_home,
                                                      "roms_path": os.path.join(rd_home, "roms")}}, f)
        if lock:
            open(os.path.join(cfg, ".lock"), "w").close()

    @staticmethod
    def esde_zip(path, extra=None):
        members = {"ES-DE/ES-DE.exe": b"MZ", "ES-DE/portable.txt": b"", "ES-DE/ES-DE/settings/": b"",
                   "ES-DE/ROMs_ALL/snes/systeminfo.txt": b"snes", "ES-DE/ROMs_ALL/gb/systeminfo.txt": b"gb"}
        members.update(extra or {})
        with zipfile.ZipFile(path, "w") as z:
            for n, d in members.items():
                z.writestr(n, d)
        return path

    def test_retrodeck_roms_once_its_setup_has_finished(self):
        rd_home = os.path.join(self.home, "sd", "retrodeck")
        os.makedirs(os.path.join(rd_home, "roms"))
        self.assertIsNone(frontend.retrodeck_roms())  # not installed / set up
        self.retrodeck_config(rd_home, lock=False)
        self.assertIsNone(frontend.retrodeck_roms())  # setup still running (it writes .lock last)
        self.retrodeck_config(rd_home)
        self.assertEqual(frontend.retrodeck_roms(), os.path.join(rd_home, "roms"))
        with mock.patch.object(rs.frontend, "esde_installs", return_value=[]):
            self.assertEqual(rs.guess_roms_root(), os.path.realpath(os.path.join(rd_home, "roms")))

    def test_esde_rom_dir(self):
        settings = os.path.join(self.home, "es_settings.xml")
        self.assertEqual(frontend.esde_rom_dir(settings, self.home), os.path.join(self.home, "ROMs"))  # no file
        with open(settings, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0"?>\n<bool name="Debug" value="false" />\n'
                    '<string name="ROMDirectory" value="%ESPATH%/Games" />\n')
        self.assertEqual(frontend.esde_rom_dir(settings, self.home, "/es"), os.path.normpath("/es/Games"))
        with open(settings, "w", encoding="utf-8") as f:
            f.write('<string name="ROMDirectory" value="" />')
        self.assertEqual(frontend.esde_rom_dir(settings, self.home), os.path.join(self.home, "ROMs"))

    def test_esde_installs(self):
        base = os.path.join(self.home, "Games")
        os.makedirs(frontend.esde_roms(base))
        self.assertEqual(frontend.esde_installs([base]), [frontend.esde_roms(base)])
        os.makedirs(os.path.join(self.home, "ES-DE", "settings"))
        os.makedirs(os.path.join(self.home, "ROMs"))
        with open(os.path.join(self.home, "ES-DE", "settings", "es_settings.xml"), "w") as f:
            f.write("")
        self.assertEqual(frontend.esde_installs(), [os.path.join(self.home, "ROMs")])  # the regular install

    def test_unpack_and_create_system_dirs(self):
        base = os.path.join(self.home, "Games")
        os.makedirs(base)
        frontend.unpack_esde(self.esde_zip(os.path.join(self.home, "p.zip")), base)
        self.assertTrue(os.path.exists(frontend.esde_exe(base)))
        with mock.patch.object(frontend, "is_windows", return_value=False):
            roms = frontend.create_system_dirs(base)
        self.assertEqual(roms, os.path.join(base, "ES-DE", "ROMs"))
        self.assertEqual(sorted(os.listdir(roms)), ["gb", "snes"])
        self.assertEqual(frontend.games_folder("drive", base) if os.name == "nt" else roms, roms)

    def test_unpack_refuses_other_zips(self):
        bad = os.path.join(self.home, "bad.zip")
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("something/else.exe", b"MZ")
        with self.assertRaises(ValueError):
            frontend.unpack_esde(bad, self.home)
        slip = self.esde_zip(os.path.join(self.home, "slip.zip"), {"../evil.txt": b"x"})
        with self.assertRaises(ValueError):
            frontend.unpack_esde(slip, os.path.join(self.home, "x"))
        self.assertFalse(os.path.exists(os.path.join(self.home, "evil.txt")))

    def test_esde_release_and_checked_download(self):
        data = self.esde_zip(os.path.join(self.home, "src.zip"))
        with open(data, "rb") as f:
            blob = f.read()
        release = json.dumps({"stable": {"version": "3.5.0", "packages": [
            {"name": "LinuxAppImage", "filename": "x.AppImage", "url": "https://a/1", "md5": ""},
            {"name": "WindowsPortable", "filename": "ES-DE_3.5.0-x64_Portable.zip", "url": "https://a/2",
             "md5": fsutil_md5(blob)}]}}).encode()

        class Resp(io.BytesIO):
            def __init__(self, b):
                super().__init__(b)
                self.headers = {"Content-Length": str(len(b))}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(frontend.urllib.request, "urlopen",
                               side_effect=lambda req, timeout=None: Resp(release if "latest" in req.full_url
                                                                          else blob)):
            version, pkg = frontend.esde_release()
            self.assertEqual((version, pkg["url"]), ("3.5.0", "https://a/2"))
            seen = []
            dest = frontend.download(pkg["url"], os.path.join(self.home, pkg["filename"]), pkg["md5"],
                                     lambda d, t: seen.append((d, t)))
            self.assertTrue(zipfile.is_zipfile(dest))
            self.assertEqual(seen[-1], (len(blob), len(blob)))
            with self.assertRaises(ValueError):  # damaged: checksum doesn't match
                frontend.download(pkg["url"], os.path.join(self.home, "bad.zip"), "0" * 32)
            self.assertEqual([n for n in os.listdir(self.home) if n.startswith("bad")], [])

    @unittest.skipIf(os.name == "nt", "uses a shell script as a stand-in for flatpak")
    def test_install_retrodeck_runs_flatpak_for_the_user(self):
        bin_dir = os.path.join(self.home, "bin")
        os.makedirs(bin_dir)
        calls = os.path.join(self.home, "calls")
        fake = os.path.join(bin_dir, "flatpak")
        with open(fake, "w") as f:
            f.write(f'#!/bin/sh\necho "$@" >> {calls}\necho "Installing $1"\n'
                    '[ "$1" = info ] && exit 1\nexit 0\n')
        os.chmod(fake, 0o755)
        with mock.patch.dict(os.environ, {"PATH": bin_dir}):
            self.assertFalse(frontend.retrodeck_installed())
            lines = []
            frontend.install_retrodeck(lines.append)
        with open(calls) as f:
            ran = f.read().splitlines()
        self.assertEqual(ran[1:], ["remote-add --user --if-not-exists flathub " + frontend.FLATHUB,
                                   "install --user --noninteractive -y flathub net.retrodeck.retrodeck"])
        self.assertIn("Installing install", lines)
        with open(fake, "w") as f:
            f.write("#!/bin/sh\necho nope\nexit 3\n")
        with mock.patch.dict(os.environ, {"PATH": bin_dir}), self.assertRaises(RuntimeError):
            frontend.install_retrodeck(lambda line: None)

    def test_retrodeck_steps(self):
        with mock.patch.object(frontend, "is_steam_deck", return_value=False):
            self.assertIn("Home Directory", frontend.retrodeck_steps("home", "/home/me")[0])
        with mock.patch.object(frontend, "is_steam_deck", return_value=True):
            self.assertIn("Internal Storage", frontend.retrodeck_steps("home", "/home/deck")[0])
        steps = frontend.retrodeck_steps("drive", "/run/media/deck/SD")
        self.assertIn("Custom Location", steps[0])
        self.assertIn("/run/media/deck/SD", steps[1])

    def test_storage_choices_start_with_home(self):
        with mock.patch.object(frontend, "is_windows", return_value=False):
            choices = frontend.storage_choices()
        self.assertEqual(choices[0], ("home", "Home folder", self.home))
        with mock.patch.object(frontend, "is_windows", return_value=True):
            win_home = frontend.storage_choices()[0]
        self.assertEqual(win_home, ("home", "Home folder", os.path.join(self.home, "Games")))  # not ~\ES-DE
        self.assertIsNotNone(frontend.free_bytes(win_home[2]))  # measured on the folder it will be made in
        self.assertTrue(all(kind in ("home", "drive") and os.path.isdir(p) for kind, _, p in choices))
        self.assertEqual(frontend.human_size(3 * 1024 ** 3), "3.0 GB")


class Pdroms(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.roms = os.path.join(self.dir, "roms")
        self.dl = os.path.join(self.dir, "Downloads")
        os.makedirs(self.dl)
        p = mock.patch.object(pdroms, "CACHE", os.path.join(self.dir, "cache"))
        p.start()
        self.addCleanup(p.stop)

    def test_parse_page(self):
        games, total = pdroms.parse_page(pdroms_page(["2048", "Robo-Ninja Climb (NES Game)"], 74))
        self.assertEqual(total, 74)
        self.assertEqual([g["title"] for g in games], ["2048", "Robo-Ninja Climb"])
        self.assertEqual(games[0]["url"], "https://pdroms.de/files/nintendo-entertainment-system-nes-famicom/2048")
        self.assertEqual(games[0]["added"], "2014")
        self.assertEqual(games[0]["thumb"], "https://pdroms.de/wp-content/uploads/2014/05/2048-256x150.png")

    def test_parse_file_page(self):
        d = pdroms.parse_file_page(PDROMS_FILE)
        self.assertEqual((d["author"], d["version"]), ("Sly Dog Studios", "v1"))
        self.assertEqual(d["image"], "https://pdroms.de/wp-content/uploads/2014/05/1k2p.png")
        self.assertEqual(d["description"], "Sly Dog Games made up the very basic version of Pong, named 1k2p. "
                                           "It\u2019s a two player only game.")

    def test_catalog_reads_every_page_and_caches(self):
        pages = {1: pdroms_page([f"Game {i:02}" for i in range(10)], 23),
                 2: pdroms_page([f"Game {i:02}" for i in range(10, 20)], 23),
                 3: pdroms_page(["Game 20", "Game 21", "Game 00"], 23)}
        urls = []

        def fetch(url, timeout=30):
            urls.append(url)
            n = int(url.rstrip("/").rsplit("/", 1)[-1]) if "/page/" in url else 1
            return pages[n]

        with mock.patch.object(pdroms, "_fetch", side_effect=fetch):
            games = pdroms.load_catalog("nes", pause=0)
            self.assertEqual(len(games), 22)  # the repeat on page 3 merged
            self.assertEqual(urls, ["https://pdroms.de/system/nintendo-entertainment-system-nes-famicom/games/",
                                    "https://pdroms.de/system/nintendo-entertainment-system-nes-famicom/games/page/2/",
                                    "https://pdroms.de/system/nintendo-entertainment-system-nes-famicom/games/page/3/"])
            self.assertTrue(all("show_restricted" not in u for u in urls))  # fan games stay hidden
            self.assertEqual({g["system"] for g in games}, {"nes"})
            pdroms.load_catalog("nes")
            self.assertEqual(len(urls), 3)  # from the cache
            self.assertLess(pdroms.cached_age("nes"), 1)

    def test_every_system_is_known_to_the_downloads_watcher(self):
        for system, _, _ in pdroms.SYSTEMS:
            self.assertTrue(downloads.SYSTEM_EXTS.get(system), system)

    def test_open_game_is_filed_from_its_zip(self):
        g = dict(pdroms.parse_page(pdroms_page(["Streemerz"], 1))[0][0], system="nes")
        w = downloads.DownloadWatcher(self.dl, self.roms)
        w.expect(pdroms.want(g))
        with open(os.path.join(self.dl, "streemerz_(01-02-2013).zip"), "wb") as f:
            f.write(HomebrewHub._zip({"readme.txt": b"hi", "streemerz.nes": b"NES"}))
        w.poll()
        [(want, path)] = w.poll()
        self.assertEqual(path, os.path.join(self.roms, "nes", "Streemerz (Homebrew).nes"))
        self.assertEqual(pdroms.installed_path(g, self.roms), path)
        fields = pdroms.es_de_fields(dict(g, author="Faux Game Company", description="Infiltrate."))
        self.assertEqual((fields["developer"], fields["desc"]), ("Faux Game Company", "Infiltrate."))
        self.assertNotIn("releasedate", fields)  # PDRoms' date is when it was listed, not released


class Mamedev(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.roms = os.path.join(self.dir, "roms")
        p = mock.patch.object(mamedev, "CACHE", os.path.join(self.dir, "cache"))
        p.start()
        self.addCleanup(p.stop)

    def test_parse_index(self):
        games = mamedev.parse_index(MAMEDEV_INDEX)
        self.assertEqual([(g["id"], g["title"], g["year"], g["company"]) for g in games],
                         [("circus", "Circus", "1977", "Exidy"), ("witchcrd", "Witch Card", "1991", "Video Klein")])
        self.assertEqual(games[0]["page"], "https://www.mamedev.org/roms/circus/")
        self.assertEqual(games[0]["thumb"], "https://www.mamedev.org/roms/circus/circus-thumb.png")

    def test_parse_game_page(self):
        page = "https://www.mamedev.org/roms/circus/"
        d = mamedev.parse_game_page(mamedev_page("Circus", ["circus.zip", "circuso.zip"]), page)
        self.assertEqual(d["zips"], [page + "circus.zip", page + "circuso.zip"])
        self.assertEqual(d["notice"], "Thanks to the kind generosity of H.R. Kauffman, the original ROM images for "
                                      "Circus have been made available for free, non-commercial use.")
        self.assertEqual(d["description"], "Circus was one of the first games produced by Exidy that used a CPU "
                                           "(6502).\n\nAt least 13,000 units were produced.")
        self.assertEqual(d["image"], page + "0000.png")  # a screenshot, not the cabinet

    def test_catalog_and_install_keep_the_set_name(self):
        def fetch(url, timeout=30):
            if url == mamedev.SITE:
                return MAMEDEV_INDEX.encode()
            if url.endswith(".zip"):
                return HomebrewHub._zip({"wc.u3": b"ROM"})
            if "witchcrd" in url:
                return mamedev_page("Witch Card", ["witchcrde.zip"]).encode()
            return mamedev_page("Circus", ["circus.zip", "circuso.zip"]).encode()

        with mock.patch.object(mamedev, "_fetch", side_effect=fetch) as f:
            games = mamedev.load_catalog(pause=0)
            self.assertEqual(f.call_count, 3)
            mamedev.load_catalog()
            self.assertEqual(f.call_count, 3)  # from the cache
            witch = games[1]
            self.assertEqual(mamedev.rom_name(witch), "witchcrde.zip")  # MAME's set name, not the page's
            self.assertIsNone(mamedev.installed_path(witch, self.roms))
            path = mamedev.install(witch, self.roms)
            self.assertEqual(path, os.path.join(self.roms, "mame", "witchcrde.zip"))
            self.assertTrue(zipfile.is_zipfile(path))
            self.assertEqual(mamedev.installed_path(witch, self.roms), path)
            with self.assertRaises(FileExistsError):
                mamedev.install(witch, self.roms)
        self.assertEqual(mamedev.es_de_fields(witch)["releasedate"], "19910101T000000")

    def test_not_a_zip_is_refused(self):
        g = {"zips": ["https://www.mamedev.org/roms/x/x.zip"], "title": "X"}
        with mock.patch.object(mamedev, "_fetch", return_value=b"<html>error</html>"):
            with self.assertRaises(ValueError):
                mamedev.install(g, self.roms)
        self.assertFalse(os.path.exists(os.path.join(self.roms, "mame", "x.zip")))

    def test_arcade_systems_are_not_renamed(self):
        self.assertIn("mame", rs.ARCADE_SYSTEMS)
        self.assertNotIn("snes", rs.ARCADE_SYSTEMS)


def zip_bytes(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in members.items():
            z.writestr(n, d)
    return buf.getvalue()


@unittest.skipIf(os.name == "nt", "the desktop's own pickers are a Linux thing (Windows' Tk dialogs are native)")
class Dialogs(unittest.TestCase):
    """lib/dialogs.py: the desktop's own file picker when there is one, Tk's otherwise."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.log = os.path.join(self.tmp, "args")

    def tool(self, name, output, code=0):
        """A stand-in kdialog / zenity that records its arguments and prints output."""
        p = os.path.join(self.bin, name)
        with open(p, "w") as f:
            f.write(f'#!/bin/sh\nfor a in "$@"; do echo "$a"; done > "{self.log}"\nprintf %s "{output}"\nexit {code}\n')
        os.chmod(p, 0o755)

    def env(self, desktop="KDE"):
        return mock.patch.dict(os.environ, {"PATH": self.bin, "DISPLAY": ":0", "XDG_CURRENT_DESKTOP": desktop})

    def args(self):
        with open(self.log) as f:
            return f.read().splitlines()

    def test_kdialog_on_kde(self):
        self.tool("kdialog", "/mnt/nas/PS2 Collection\n")
        self.tool("zenity", "/wrong")
        with self.env():
            self.assertEqual(dialogs.ask_directory(None, "Add a folder", self.tmp), "/mnt/nas/PS2 Collection")
        self.assertEqual(self.args(), ["--title", "Add a folder", "--getexistingdirectory", self.tmp])

    def test_zenity_elsewhere_and_several_files(self):
        self.tool("kdialog", "/wrong")
        self.tool("zenity", "/a/x.7z\n/a/y.iso\n")
        with self.env("GNOME"):
            self.assertEqual(dialogs.ask_open_files(None, "Add games", self.tmp), ("/a/x.7z", "/a/y.iso"))
        self.assertIn("--multiple", self.args())

    def test_cancel_and_network_locations(self):
        self.tool("kdialog", "", code=1)
        with self.env():
            self.assertEqual(dialogs.ask_directory(None, "x", self.tmp), "")
        self.tool("kdialog", "smb://mini@192.168.50.2/downloads")
        with self.env(), mock.patch.object(dialogs.messagebox, "showerror") as err:
            self.assertEqual(dialogs.ask_directory(None, "x", self.tmp), "")
        self.assertIn("Mount it as a folder", err.call_args[0][1])

    def test_tk_without_either(self):
        with self.env(), mock.patch.object(dialogs.filedialog, "askdirectory", return_value="/tk") as tk_dialog:
            self.assertEqual(dialogs.ask_directory(None, "x", self.tmp), "/tk")
        tk_dialog.assert_called_once()


class SystemNames(unittest.TestCase):
    def test_games_go_in_folders_es_de_scans(self):
        """Every system RetroShelf files games under is one of ES-DE's folder names (atarilynx, not lynx)."""
        with open(os.path.join(TESTS, "esde_systems.txt"), encoding="utf-8") as f:
            esde = {line.strip() for line in f if line.strip() and not line.startswith("#")}
        used = {"import": set(ri.LABELS) | set(ri.EXT_SYSTEMS.values()) | set(ri.HINTS.values()),
                "downloads": set(downloads.SYSTEM_EXTS), "pdroms": {s for s, _, _ in pdroms.SYSTEMS},
                "homebrew": set(hb.PLATFORMS.values())}
        for where, systems in used.items():
            self.assertEqual(sorted(systems - esde), [], where)


class Video(unittest.TestCase):
    """lib/video.py: where a game's video comes from and how mpv is asked to play it."""

    def test_finds_es_de_clips(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(os.path.join(d, "videos"))
        for n in ("Game (USA).mp4", "Other.txt", "Old (USA).MKV"):
            open(os.path.join(d, "videos", n), "w").close()
        self.assertEqual(video.video_for(d, ["Nope", "Game (USA)"]), os.path.join(d, "videos", "Game (USA).mp4"))
        self.assertEqual(video.video_for(d, ["Old (USA)"]), os.path.join(d, "videos", "Old (USA).MKV"))
        self.assertIsNone(video.video_for(d, ["Other"]))
        self.assertIsNone(video.video_for(os.path.join(d, "missing"), ["Game (USA)"]))

    def pick(self, env, have, flatpak=False):
        with mock.patch.dict(os.environ, {"RETROSHELF_VIDEO": env}), \
                mock.patch.object(video.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}" if n in have else None), \
                mock.patch.object(video, "_flatpak_has", return_value=flatpak), \
                mock.patch.object(video, "is_windows", return_value=False), \
                mock.patch.object(video, "_backend", None), mock.patch.object(video, "_ytdl", None):
            return video.backend()[0], video.can_stream(), video.missing_for_streams()

    def test_backend_and_streaming_needs(self):
        self.assertEqual(self.pick("", {"mpv", "ffmpeg", "yt-dlp"}), ("mpv", True, ""))
        self.assertEqual(self.pick("", {"mpv", "ffmpeg"})[1:], (False, "yt-dlp"))
        self.assertEqual(self.pick("", {"ffmpeg", "yt-dlp"})[:2], ("ffmpeg", False))  # ffmpeg can't stream
        self.assertIn("mpv and yt-dlp", self.pick("", {"ffmpeg"})[2])
        self.assertEqual(self.pick("", {"flatpak"}, flatpak=True), ("mpv-flatpak", True, ""))  # bundles yt-dlp
        self.assertEqual(self.pick("ffmpeg", {"mpv", "ffmpeg"})[0], "ffmpeg")
        self.assertIsNone(self.pick("off", {"mpv", "ffmpeg"})[0])
        self.assertIsNone(self.pick("", set())[0])

    def test_mpv_command(self):
        frame = mock.Mock()
        frame.winfo_id.return_value = 4242
        with mock.patch.object(video.subprocess, "Popen") as popen, \
                mock.patch.object(video, "is_windows", return_value=False):
            q = video.youtube_query("Chrono Trigger", "Super Nintendo")
            self.assertEqual(q, "ytdl://ytsearch1:Chrono Trigger Super Nintendo gameplay")
            p = video.MpvPlayer(frame, q, ["/usr/bin/mpv"], stream=True)
            self.assertEqual(p.cmd[-2:], ["--", q])
            self.assertIn("--wid=4242", p.cmd)
            self.assertIn("--mute=yes", p.cmd)
            self.assertTrue(any(a.startswith("--ytdl-format=") for a in p.cmd))
            self.assertIn("--start=50%", p.cmd)  # streams open halfway in, past the intro
            self.assertNotIn("WAYLAND_DISPLAY", popen.call_args.kwargs["env"])  # kept on X11, where it can embed
            clip = os.path.join(tempfile.gettempdir(), "clips", "Game.mp4")
            p = video.MpvPlayer(frame, clip, ["/usr/bin/flatpak", "run"], flatpak=True)
            self.assertIn(f"--filesystem={os.path.dirname(clip)}:ro", p.cmd)
            self.assertLess(p.cmd.index(f"--filesystem={os.path.dirname(clip)}:ro"), p.cmd.index(video.FLATPAK_MPV))
            self.assertFalse(any(a.startswith("--ytdl-format=") for a in p.cmd))
            self.assertFalse(any(a.startswith("--start=") for a in p.cmd))  # local clips play from the top


class Gamepad(unittest.TestCase):
    """lib/gamepad.py: reading pads without any library, and turning buttons into keys."""

    def test_capability_masks(self):
        word = struct.calcsize("l") * 8
        words = ["0"] * 12
        words[-1 - 0x130 // word] = format(1 << (0x130 % word), "x")
        self.assertTrue(gamepad._has_bit(" ".join(words), 0x130))
        self.assertFalse(gamepad._has_bit(" ".join(words), 0x131))
        self.assertFalse(gamepad._has_bit("ffff", 0x130))  # a keyboard-sized mask

    def test_finds_pads_in_sysfs(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        word = struct.calcsize("l") * 8
        pad = ["0"] * 12
        pad[-1 - 0x130 // word] = format(1 << (0x130 % word), "x")
        for ev, name, mask in (("event3", "Xbox Wireless Controller", " ".join(pad)), ("event1", "AT Keyboard", "fffe")):
            os.makedirs(os.path.join(root, ev, "device", "capabilities"))
            with open(os.path.join(root, ev, "device", "capabilities", "key"), "w") as f:
                f.write(mask + "\n")
            with open(os.path.join(root, ev, "device", "name"), "w") as f:
                f.write(name + "\n")
        self.assertEqual(gamepad.linux_pads(root), [("/dev/input/event3", "Xbox Wireless Controller")])

    @unittest.skipIf(os.name == "nt", "evdev is Linux's")
    def test_reads_evdev_events(self):
        r, w = os.pipe()
        os.set_blocking(r, False)
        self.addCleanup(os.close, w)
        pad = gamepad.LinuxPad("/dev/input/event9", "Pad", fd=r)
        self.addCleanup(pad.close)

        def send(*events):
            os.write(w, b"".join(gamepad.EVENT.pack(0, 0, *e) for e in events))
            self.assertTrue(pad.read())
            return pad.pressed
        self.assertEqual(send((gamepad.EV_KEY, 0x130, 1)), {"a"})
        self.assertEqual(send((gamepad.EV_KEY, 0x130, 0), (gamepad.EV_ABS, gamepad.ABS_HAT0Y, 1)), {"down"})
        self.assertEqual(send((gamepad.EV_ABS, gamepad.ABS_HAT0Y, 0), (gamepad.EV_ABS, gamepad.ABS_X, -30000)),
                         {"left"})  # the stick, past the dead zone
        self.assertEqual(send((gamepad.EV_ABS, gamepad.ABS_X, -4000)), set())
        self.assertEqual(send((gamepad.EV_KEY, 0x221, 1), (gamepad.EV_KEY, 0x13b, 1)), {"down", "start"})

    def test_xinput_state(self):
        st = gamepad._Gamepad(buttons=0x1000 | 0x0001, lt=0, rt=255, lx=0, ly=-32000)
        self.assertEqual(gamepad.xinput_pressed(st), {"a", "up", "rt", "down"})

    def test_held_directions_repeat_and_buttons_dont(self):
        r = gamepad.Repeater()
        self.assertEqual(sorted(r.update({"down", "a"}, 0.0)), ["a", "down"])
        self.assertEqual(r.update({"down", "a"}, 0.2), [])          # not yet
        self.assertEqual(r.update({"down", "a"}, 0.45), ["down"])   # the direction repeats, A doesn't
        self.assertEqual(r.update({"down", "a"}, 0.50), [])
        self.assertEqual(r.update({"down", "a"}, 0.54), ["down"])
        self.assertEqual(r.update(set(), 0.6), [])
        self.assertEqual(r.update({"a"}, 0.7), ["a"])                # pressed again

    def test_glyph_style_from_the_pad_name(self):
        for name, style in (("Xbox Wireless Controller", "xbox"), ("Microsoft X-Box 360 pad", "xbox"),
                            ("Steam Deck", "xbox"), ("8BitDo Ultimate Wireless Controller", "xbox"),
                            ("Sony Interactive Entertainment Wireless Controller", "playstation"),
                            ("Wireless Controller", "playstation"),  # a DualShock 4 over Bluetooth
                            ("DualSense Wireless Controller", "playstation"), ("PS3 Controller", "playstation"),
                            ("Nintendo Switch Pro Controller", "nintendo"), ("Joy-Con (L/R)", "nintendo"),
                            ("", "xbox"), (None, "xbox")):
            self.assertEqual(padhints.style_for(name), style, name)
        for style in padhints.STYLES.values():  # every button the hints use has a glyph in every style
            self.assertTrue({"a", "b", "x", "y", "lb", "rb", "lt", "rt", "start"} <= set(style))

    def test_the_last_pad_pressed_picks_the_glyphs(self):
        src = gamepad.LinuxSource()
        src.next_scan = float("inf")
        xbox, ps = mock.Mock(pressed=set(), read=lambda: True), mock.Mock(pressed=set(), read=lambda: True)
        xbox.name, ps.name = "Xbox Wireless Controller", "DualSense Wireless Controller"
        src.pads = {"/dev/input/event1": xbox, "/dev/input/event2": ps}
        src.poll(0)
        self.assertIsNone(src.last)
        ps.pressed = {"a"}
        src.poll(0)
        self.assertEqual(src.last, ps.name)
        root = mock.Mock()
        pads = gamepad.Gamepads(root, source=src)
        self.assertEqual(pads.style(), "playstation")


FAKE_TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_disc_tool.py")


class Compress(unittest.TestCase):
    """lib/compress.py: what becomes a .chd / .rvz, and replacing the originals safely."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tool = compress.Tool("chdman", "tests", [sys.executable, FAKE_TOOL])

    def put(self, system, rel, data=b"\0" * 4096):
        p = os.path.join(self.tmp, system, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode())
        return p

    def units(self, system):
        folder = os.path.join(self.tmp, system)
        out = {}
        for n in sorted(os.listdir(folder)):
            key = n if os.path.isdir(os.path.join(folder, n)) else rs.unit_key(n)
            out.setdefault(key, {"paths": []})["paths"].append(os.path.join(folder, n))
        return out

    def cue(self, system, stem, tracks=1):
        text = "".join(f'FILE "{stem} (Track {t}).bin" BINARY\n  TRACK {t:02d} MODE2/2352\n    INDEX 01 00:00:00\n'
                       for t in range(1, tracks + 1))
        for t in range(1, tracks + 1):
            self.put(system, f"{stem} (Track {t}).bin")
        return self.put(system, f"{stem}.cue", text)

    def test_what_each_game_becomes(self):
        self.cue("psx", "Alpha (USA)", tracks=2)
        self.put("psx", "Done (USA).chd")
        for d in (1, 2):
            self.cue("psx", f"Multi (USA) (Disc {d})")
        self.put("psx", "Multi (USA).m3u", "Multi (USA) (Disc 1).cue\nMulti (USA) (Disc 2).cue\n")
        self.put("psx", "Broken (USA).cue", 'FILE "Broken (USA).bin" BINARY\n  TRACK 01 MODE2/2352\n')
        self.put("psx", "Iso (USA).iso")
        plan = {k: (jobs, why) for k, jobs, why in compress.plan("psx", self.units("psx"))}
        jobs, _ = plan["Alpha (USA)"]
        self.assertEqual([(j.kind, os.path.basename(j.out), len(j.parts)) for j in jobs], [("cd", "Alpha (USA).chd", 3)])
        self.assertEqual(plan["Done (USA)"], ([], "already compressed"))
        self.assertEqual(sorted(os.path.basename(j.out) for j in plan["Multi (USA)"][0]),
                         ["Multi (USA) (Disc 1).chd", "Multi (USA) (Disc 2).chd"])
        self.assertEqual(plan["Broken (USA)"][0], [])
        self.assertIn("isn't there", plan["Broken (USA)"][1])
        self.assertEqual(plan["Iso (USA)"][0][0].kind, "cd")
        # PS2 images are DVDs; GameCube / Wii become RVZ, but not NKit images or split WBFS
        self.put("ps2", "Game (USA).iso")
        self.assertEqual(compress.plan("ps2", self.units("ps2"))[0][1][0].kind, "dvd")
        self.put("gc", "Cube (USA).iso")
        self.put("gc", "Trim (USA).nkit.iso")
        self.put("wii", "Split (USA).wbfs")
        self.put("wii", "Split (USA).wbf1")
        gc = {k: (jobs, why) for k, jobs, why in compress.plan("gc", self.units("gc"))}
        self.assertEqual(gc["Cube (USA)"][0][0].kind, "rvz")
        self.assertIn("NKit", gc["Trim (USA).nkit"][1])
        self.assertIn("split", compress.plan("wii", self.units("wii"))[0][2])
        # a Dreamcast game in its own folder becomes Game.chd next to it
        self.put("dreamcast", "Shen (USA)/track01.bin")
        self.put("dreamcast", "Shen (USA)/track02.raw")
        self.put("dreamcast", "Shen (USA)/disc.gdi", "2\n1 0 4 2352 track01.bin 0\n2 600 0 2352 track02.raw 0\n")
        (key, jobs, _), = compress.plan("dreamcast", self.units("dreamcast"))
        self.assertEqual((jobs[0].src.endswith("disc.gdi"), os.path.basename(jobs[0].out)), (True, "Shen (USA).chd"))
        # systems that aren't disc-based, or whose ES-DE folder doesn't list the format, are left alone
        self.assertIsNone(compress.supported("snes"))
        self.assertIsNone(compress.supported("psx", [".cue", ".bin"]))
        self.assertEqual(compress.supported("psx", [".cue", ".CHD"]), ".chd")
        self.assertEqual(compress.plan("snes", {}), [])

    def test_convert_then_replace(self):
        for d in (1, 2):
            self.cue("psx", f"Multi (USA) (Disc {d})")
        m3u = self.put("psx", "Multi (USA).m3u", "Multi (USA) (Disc 1).cue\nMulti (USA) (Disc 2).cue\n")
        folder = os.path.join(self.tmp, "psx")
        gamelist = self.put("gl", "gamelist.xml", '<?xml version="1.0"?>\n<gameList>\n<game><path>./Multi (USA) '
                            '(Disc 1).cue</path><name>Multi (USA) (Disc 1)</name><playcount>4</playcount></game>\n'
                            "</gameList>\n")
        holding = os.path.join(self.tmp, "pruned", "to_delete", "psx")
        units = self.units("psx")
        (_, jobs, _), = compress.plan("psx", units)
        seen = []
        size = compress.convert(jobs[0], self.tool, lambda stage, f, w: seen.append((stage, f)))
        self.assertTrue(os.path.isfile(jobs[0].out))
        self.assertEqual(size, os.path.getsize(jobs[0].out))
        self.assertIn(("compress", 1.0), seen)
        self.assertIn("check", {s for s, _ in seen})  # checked before anything is replaced
        self.assertEqual([n for n in os.listdir(folder) if n.startswith(".")], [])  # no temporary file left
        moves, problems = compress.finish(jobs[0], folder, compress.playlists_for(jobs[0], units["Multi (USA)"]["paths"]),
                                          gamelist, None, holding)
        self.assertEqual(problems, [])
        self.assertEqual(sorted(os.path.basename(t) for _, t in moves),
                         ["Multi (USA) (Disc 1) (Track 1).bin", "Multi (USA) (Disc 1).cue"])
        self.assertTrue(all(os.path.exists(t) and not os.path.exists(s) for s, t in moves))
        with open(m3u) as f:
            self.assertEqual(f.read(), "Multi (USA) (Disc 1).chd\nMulti (USA) (Disc 2).cue\n")
        with open(gamelist) as f:
            text = f.read()
        self.assertIn("<path>./Multi (USA) (Disc 1).chd</path>", text)
        self.assertIn("<playcount>4</playcount>", text)
        # deleting instead of holding
        compress.convert(jobs[1], self.tool, verify=False)
        moves, _ = compress.finish(jobs[1], folder, [m3u], None, None, None)
        self.assertEqual(moves, [])
        self.assertEqual(sorted(os.listdir(folder)), ["Multi (USA) (Disc 1).chd", "Multi (USA) (Disc 2).chd",
                                                      "Multi (USA).m3u"])

    def test_a_folder_game_brings_its_media_along(self):
        self.put("dreamcast", "Shen (USA)/track01.bin")
        self.put("dreamcast", "Shen (USA)/disc.gdi", "1\n1 0 4 2352 track01.bin 0\n")
        media = os.path.join(self.tmp, "media", "dreamcast")
        self.put("media", "dreamcast/covers/Shen (USA)/disc.png")
        folder = os.path.join(self.tmp, "dreamcast")
        (_, (job,), _), = compress.plan("dreamcast", self.units("dreamcast"))
        compress.convert(job, self.tool)
        compress.finish(job, folder, [], None, media, os.path.join(self.tmp, "held"))
        self.assertTrue(os.path.isfile(os.path.join(media, "covers", "Shen (USA).png")))
        self.assertEqual(os.listdir(folder), ["Shen (USA).chd"])
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "held", "Shen (USA)")))

    def test_a_failure_leaves_the_game_alone(self):
        cue = self.cue("psx", "Alpha (USA)")
        (_, (job,), _), = compress.plan("psx", self.units("psx"))
        with mock.patch.dict(os.environ, {"FAKE_TOOL_FAIL": "1"}):
            with self.assertRaises(RuntimeError) as cm:
                compress.convert(job, self.tool)
        self.assertIn("not valid", str(cm.exception))
        self.assertEqual(sorted(os.listdir(os.path.dirname(cue))), ["Alpha (USA) (Track 1).bin", "Alpha (USA).cue"])
        with mock.patch.dict(os.environ, {"FAKE_TOOL_SLOW": "6"}):  # stopping kills the tool and cleans up
            t0 = time.monotonic()
            with self.assertRaises(InterruptedError):
                compress.convert(job, self.tool, cancelled=lambda: time.monotonic() - t0 > 0.5)
        self.assertEqual(sorted(os.listdir(os.path.dirname(cue))), ["Alpha (USA) (Track 1).bin", "Alpha (USA).cue"])

    @unittest.skipUnless(shutil.which("chdman"), "chdman isn't installed")
    def test_real_chdman(self):
        stem = "Real (USA)"
        self.put("psx", f"{stem} (Track 1).bin", bytes(2352 * 300))
        self.put("psx", f"{stem}.cue", f'FILE "{stem} (Track 1).bin" BINARY\n  TRACK 01 MODE2/2352\n'
                                       "    INDEX 01 00:00:00\n")
        self.put("ps2", "Dvd (USA).iso", bytes(2048 * 600))
        for system in ("psx", "ps2"):
            (_, (job,), _), = compress.plan(system, self.units(system))
            compress.convert(job, compress.find_tool("chdman"))
            with open(job.out, "rb") as f:
                self.assertEqual(f.read(8), b"MComprHD")
            with open(job.out, "rb") as f:
                self.assertEqual(ri.sniff_chd(f)[0], "ps2" if system == "ps2" else None)


class SevenZip(unittest.TestCase):
    """lib/sevenzip.py: 7z archives unpacked with Python's own lzma."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_unpacks_and_streams(self):
        files = {"Game (USA)/Game (USA).iso": discs.ps2(), "readme.txt": b"hi" * 500, "b.bin": os.urandom(5000)}
        z = sevenzip.SevenZip(io.BytesIO(discs.seven_zip(files)))
        self.assertEqual([e.name for e in z.files()], list(files))
        out = os.path.join(self.tmp, "out")
        z.extract_all(out)
        for name, data in files.items():
            with open(os.path.join(out, *name.split("/")), "rb") as f:
                self.assertEqual(f.read(), data)
        s = z.open(z.files()[2])
        s.seek(4000)
        self.assertEqual(s.read(10), files["b.bin"][4000:4010])
        s.seek(3)  # back: decodes again from the start
        self.assertEqual(s.read(4), files["b.bin"][3:7])

    def test_wanted_skips_files(self):
        z = sevenzip.SevenZip(io.BytesIO(discs.seven_zip({"a.gba": b"x" * 100, "tool.exe": b"MZ" * 50})))
        out = os.path.join(self.tmp, "out")
        z.extract_all(out, wanted=lambda e: not e.name.endswith(".exe"))
        self.assertEqual(os.listdir(out), ["a.gba"])

    def test_damage_and_bad_paths_are_caught(self):
        data = bytearray(discs.seven_zip({"a.gba": os.urandom(3000)}))
        data[40] ^= 0xFF  # inside the packed data
        with self.assertRaises(ValueError):
            sevenzip.SevenZip(io.BytesIO(bytes(data))).extract_all(os.path.join(self.tmp, "x"))
        with self.assertRaisesRegex(ValueError, "unsafe"):
            sevenzip.SevenZip(io.BytesIO(discs.seven_zip({"../evil.gba": b"x"}))).extract_all(self.tmp + "/y")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.gba")))

    @unittest.skipUnless(shutil.which("7z") or shutil.which("7zz"), "7-Zip isn't installed")
    def test_what_7zip_makes(self):
        """Archives from the real 7-Zip, with each method it offers: all the ones games use unpack."""
        exe = shutil.which("7z") or shutil.which("7zz")
        src = os.path.join(self.tmp, "src")
        os.makedirs(os.path.join(src, "sub"))
        files = {"game.iso": discs.ps2() + os.urandom(20000), "sub/notes.txt": b"text " * 2000,
                 "tool.exe": b"MZ\x90\x00" + b"\xe8\x10\x00\x00\x00\x55\x8b\xec" * 20000}
        for name, data in files.items():
            with open(os.path.join(src, *name.split("/")), "wb") as f:
                f.write(data)
        for i, opts in enumerate([["-m0=lzma"], ["-m0=lzma2"], ["-m0=lzma2", "-ms=off"], ["-m0=bcj", "-m1=lzma2"],
                                  ["-m0=delta:4", "-m1=lzma"], ["-m0=deflate"], ["-m0=bzip2"], ["-m0=copy"],
                                  ["-mhc=off"], ["-mx=9"]]):
            arc = os.path.join(self.tmp, f"t{i}.7z")
            subprocess.run([exe, "a", "-bd", "-y", *opts, arc, "game.iso", "sub", "tool.exe"], cwd=src,
                           capture_output=True, check=True)
            out = os.path.join(self.tmp, f"out{i}")
            with sevenzip.SevenZip(arc) as z:  # -mx=9 packs .exe files with BCJ2, which only 7-Zip reads
                z.extract_all(out, wanted=(lambda e: not e.name.endswith(".exe")) if "-mx=9" in opts else None)
            for name, data in files.items():
                if name.endswith(".exe") and "-mx=9" in opts:
                    continue
                with open(os.path.join(out, *name.split("/")), "rb") as f:
                    self.assertEqual(f.read(), data, f"{name} with {opts}")
        arc = os.path.join(self.tmp, "locked.7z")
        subprocess.run([exe, "a", "-bd", "-psecret", arc, "game.iso"], cwd=src, capture_output=True, check=True)
        with self.assertRaises(sevenzip.Encrypted), sevenzip.SevenZip(arc) as z:
            z.extract_all(os.path.join(self.tmp, "locked"))


class RomImport(unittest.TestCase):
    """lib/romimport.py: which system a game is for, and filing it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.roms = os.path.join(self.tmp, "roms")
        self.inbox = os.path.join(self.tmp, "import")
        os.makedirs(self.roms)
        os.makedirs(self.inbox)

    def put(self, rel, data, base=None):
        p = os.path.join(base or self.inbox, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode())
        return p

    def sniff(self, name, data):
        return ri.sniff_rom(name, io.BytesIO(data), len(data))[0]

    def test_discs_say_what_they_are(self):
        self.assertEqual(self.sniff("a.iso", discs.ps2()), "ps2")
        self.assertEqual(self.sniff("a.iso", discs.ps1()), "psx")
        self.assertEqual(self.sniff("a.bin", discs.raw(discs.ps1())), "psx")
        self.assertEqual(self.sniff("a.bin", discs.raw(discs.ps1(), mode=1)), "psx")
        self.assertEqual(self.sniff("a.iso", discs.psp()), "psp")
        self.assertEqual(self.sniff("a.cso", discs.cso(discs.psp())), "psp")
        self.assertEqual(self.sniff("a.cso", discs.cso(discs.ps2())), "ps2")
        self.assertEqual(self.sniff("a.iso", discs.gamecube()), "gc")
        self.assertEqual(self.sniff("a.iso", discs.gamecube(wii=True)), "wii")
        self.assertEqual(self.sniff("a.bin", discs.raw(discs.saturn(), mode=1)), "saturn")
        self.assertIsNone(self.sniff("a.iso", discs.iso({"DATA.BIN": b"x"})))
        self.assertIsNone(self.sniff("a.iso", discs.iso({"PS3_DISC.SFB": b"x"}, system_id=b"PS3VOLUME")))

    def test_roms_and_containers(self):
        self.assertEqual(self.sniff("Metroid.gba", b"x"), "gba")
        self.assertEqual(self.sniff("Sonic.md", bytes(0x100) + b"SEGA MEGA DRIVE " + bytes(100)), "megadrive")
        self.assertIsNone(self.sniff("README.md", b"# Read me\n" * 40))
        self.assertEqual(self.sniff("Sonic.bin", bytes(0x100) + b"SEGA GENESIS    " + bytes(100)), "megadrive")
        self.assertEqual(self.sniff("Knuckles.bin", bytes(0x100) + b"SEGA 32X        " + bytes(100)), "sega32x")
        pbp = b"\x00PBP" + bytes(0x20) + struct.pack("<I", 0x40) + bytes(0x18)
        self.assertEqual(self.sniff("EBOOT.PBP", pbp + b"PSISOIMG0000"), "psx")
        self.assertEqual(self.sniff("EBOOT.PBP", pbp + b"NPUMDIMG"), "psp")
        self.assertEqual(self.sniff("a.rvz", b"RVZ\x01" + bytes(0x44) + struct.pack(">I", 2)), "wii")
        self.assertEqual(self.sniff("a.gcz", b"\x01\xc0\x0b\xb1" + struct.pack("<I", 0)), "gc")

        def chd(tag):
            head = bytearray(124)
            head[:8], head[12:16], head[48:56] = b"MComprHD", struct.pack(">I", 5), struct.pack(">Q", 124)
            return bytes(head) + tag + bytes(4) + struct.pack(">Q", 0)
        self.assertEqual(self.sniff("a.chd", chd(b"CHGD")), "dreamcast")
        self.assertEqual(self.sniff("a.chd", chd(b"DVD ")), "ps2")
        self.assertIsNone(self.sniff("a.chd", chd(b"CHT2")))

    def test_folder_names_help_when_the_file_cant(self):
        self.assertEqual(ri.hint("/x/Sony - PlayStation 2/game.chd"), "ps2")
        self.assertEqual(ri.hint("/x/PS1 games/Disc/game.chd"), "psx")
        self.assertEqual(ri.hint(r"C:\Games\Sega Saturn\a.chd".replace("\\", os.sep)), "saturn")
        self.assertIsNone(ri.hint("/home/me/Downloads/a.chd"))
        self.assertIsNone(ri.hint("/x/psxtools/a.chd"))  # whole words only
        p = self.put("PS1/Crash.chd", b"MComprHD" + bytes(200))
        row = ri.scan(ri.collect([p])[0])
        self.assertEqual((row.system(), row.unit.how), ("psx", "folder name"))

    def test_cue_sheets_keep_their_tracks(self):
        cue = ('FILE "Game (Track 1).bin" BINARY\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n'
               'FILE "Game (Track 2).bin" BINARY\n  TRACK 02 MODE1/2352\n    INDEX 01 00:00:00\n')
        self.put("Game.cue", cue)
        self.put("Game (Track 1).bin", bytes(2352 * 4))
        self.put("Game (Track 2).bin", discs.raw(discs.saturn(), mode=1))
        self.put("Other.gba", b"x")
        rows = [ri.scan(r) for r in ri.collect([self.inbox], self.inbox)]
        game = next(r for r in rows if r.name == "Game.cue")
        self.assertEqual(game.unit.files, ["Game.cue", "Game (Track 1).bin", "Game (Track 2).bin"])
        self.assertEqual(game.system(), "saturn")
        self.assertEqual(sorted(r.name for r in rows), ["Game.cue", "Other.gba"])
        # picking just one track brings the whole game
        picked = ri.collect([os.path.join(self.inbox, "Game (Track 2).bin")])
        self.assertEqual([r.unit.files for r in picked], [["Game.cue", "Game (Track 1).bin", "Game (Track 2).bin"]])

    def test_importing_archives_and_loose_files(self):
        self.put("Gran Turismo 4 (USA).7z", discs.seven_zip({"Gran Turismo 4 (USA).iso": discs.ps2(),
                                                             "Readme.txt": b"hi"}))
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Crash (USA)/Crash (USA).cue", 'FILE "Crash (USA).bin" BINARY\n  TRACK 01 MODE2/2352\n'
                                                       '    INDEX 01 00:00:00\n')
            zf.writestr("Crash (USA)/Crash (USA).bin", discs.raw(discs.ps1()))
            zf.writestr("Crash (USA)/README.md", "# notes")
        self.put("Crash (USA).zip", z.getvalue())
        self.put("Spyro (USA).bin", discs.raw(discs.ps1()))
        self.put("mame/gridlee.zip", zip_bytes({"gridlee.1": b"\x01" * 50}))
        self.put("mystery.zip", zip_bytes({"a.1": b"x"}))
        self.put("notes.txt", "keep me")
        outside = self.put("Metroid (USA).gba", b"M" * 64, base=os.path.join(self.tmp, "elsewhere"))
        rows = ri.collect([self.inbox], self.inbox) + ri.collect([outside], self.inbox)
        for r in rows:
            ri.scan(r)
        by = {r.name: r for r in rows}
        self.assertEqual({n: r.system() for n, r in by.items()},
                         {"Gran Turismo 4 (USA).7z": "ps2", "Crash (USA).zip": "psx", "Spyro (USA).bin": "psx",
                          "gridlee.zip": "mame", "mystery.zip": None, "Metroid (USA).gba": "gba"})
        self.assertIn("arcade", by["mystery.zip"].status)
        self.assertFalse(by["Metroid (USA).gba"].inbox)
        with self.assertRaisesRegex(ValueError, "pick one"):
            ri.import_row(ri.Row(os.path.join(self.inbox, "x.bin"), self.inbox, ri.Unit(["x.bin"])), self.roms)
        by["mystery.zip"].override = "fbneo"
        for r in rows:
            for unit, res in ri.import_row(r, self.roms):
                self.assertNotIsInstance(res, Exception, r.name)
        listing = {d: sorted(os.listdir(os.path.join(self.roms, d))) for d in os.listdir(self.roms)}
        self.assertEqual(listing, {"ps2": ["Gran Turismo 4 (USA).iso"],
                                   "psx": ["Crash (USA).bin", "Crash (USA).cue", "Spyro (USA).bin", "Spyro (USA).cue"],
                                   "mame": ["gridlee.zip"], "fbneo": ["mystery.zip"], "gba": ["Metroid (USA).gba"]})
        with open(os.path.join(self.roms, "psx", "Spyro (USA).cue")) as f:
            self.assertIn('FILE "Spyro (USA).bin" BINARY\n  TRACK 01 MODE2/2352', f.read())
        with open(os.path.join(self.roms, "ps2", "Gran Turismo 4 (USA).iso"), "rb") as f:
            self.assertEqual(f.read(), discs.ps2())
        left = sorted(os.path.relpath(os.path.join(d, n), self.inbox) for d, _, fs in os.walk(self.inbox) for n in fs)
        self.assertEqual(left, ["notes.txt"])  # the import folder empties; things that aren't games stay
        self.assertTrue(os.path.exists(outside))  # games added from elsewhere are copied
        self.assertFalse(os.path.exists(ri.staging_dir(self.roms)))
        # importing it again: already there, and the source is left alone
        again = self.put("Spyro (USA).bin", discs.raw(discs.ps1()))
        row = ri.scan(ri.collect([again], self.inbox)[0])
        with self.assertRaises(FileExistsError):
            ri.import_row(row, self.roms)
        self.assertTrue(os.path.exists(again))

    def test_split_archives_and_no_space(self):
        data = discs.seven_zip({"Game.iso": discs.ps2() + os.urandom(3000)})
        self.put("Game.7z.001", data[:1000])
        self.put("Game.7z.002", data[1000:])
        rows = ri.collect([self.inbox], self.inbox)
        self.assertEqual([r.name for r in rows], ["Game.7z.001"])
        ri.scan(rows[0])
        self.assertEqual(rows[0].system(), "ps2")
        with mock.patch.object(ri, "free_bytes", return_value=10):
            with self.assertRaisesRegex(OSError, "not enough space"):
                ri.import_row(rows[0], self.roms)
        ri.import_row(rows[0], self.roms)
        self.assertEqual(os.listdir(os.path.join(self.roms, "ps2")), ["Game.iso"])
        self.assertEqual(os.listdir(self.inbox), [])

    def test_full_xbox_dumps_are_cut_to_the_game(self):
        with mock.patch.object(ri, "XBOX_REDUMP_OFFSET", 0x20000):
            game = bytes(0x10000) + ri.XBOX_MAGIC + bytes(5000)
            p = self.put("Halo.iso", bytes(0x20000) + game)
            row = ri.scan(ri.collect([p], self.inbox)[0])
            self.assertEqual(row.system(), "xbox")
            ri.import_row(row, self.roms)
        with open(os.path.join(self.roms, "xbox", "Halo.iso"), "rb") as f:
            self.assertEqual(f.read(), game)

    @unittest.skipUnless(ri.find_tool()[1], "no 7-Zip / unrar / bsdtar installed")
    def test_a_real_unpacker_takes_over(self):
        """Archives the built-in readers can't do go to an installed 7-Zip."""
        with mock.patch.object(sevenzip, "_pipeline", side_effect=sevenzip.Unsupported("7z method PPMd")):
            self.put("Game.7z", discs.seven_zip({"Game.gba": b"G" * 300}))
            row = ri.scan(ri.collect([self.inbox], self.inbox)[0])
            self.assertEqual(row.system(), "gba")
            ri.import_row(row, self.roms)
        with open(os.path.join(self.roms, "gba", "Game.gba"), "rb") as f:
            self.assertEqual(f.read(), b"G" * 300)


@unittest.skipUnless(os.environ.get("RETROSHELF_LIVE_TESTS"),
                     "talks to the real Homebrew Hub; set RETROSHELF_LIVE_TESTS=1")
class LiveHomebrewHub(unittest.TestCase):
    """Checks the API still has the shape lib/homebrew.py expects (run by CI, not by default)."""

    def test_catalog_entry_and_urls(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        with mock.patch.object(hb, "CACHE", d):
            entries = hb.load_catalog("GB", refresh=True)
        self.assertGreater(len(entries), 100)
        untitled = [e["slug"] for e in entries if not e.get("title")]
        print(f"\n{len(entries)} GB entries; fields in the search results: {sorted(entries[0])}; "
              f"{sum(bool(e.get('files')) for e in entries)} list files; untitled: {untitled[:10]}")
        self.assertTrue(all(e.get("slug") for e in entries))
        self.assertLess(len(untitled), len(entries) / 10)  # the window shows the slug for these
        e = next(e for e in entries if e.get("screenshots"))
        full = hb.load_entry(e["slug"])
        print(f"entry {e['slug']}: fields {sorted(full)}")
        import collections
        print("licenses:", collections.Counter(hb.game_license(x) for x in entries).most_common(15))
        print("one-click installs:", sum(hb.can_download(x) for x in entries), "of", len(entries))
        self.assertEqual(full["slug"], e["slug"])
        self.assertIsNotNone(hb.rom_file(full))
        for url in (hb.screenshot_url(full), hb.file_url(full, hb.rom_file(full)["filename"])):
            req = hb.urllib.request.Request(url, headers={"User-Agent": hb.USER_AGENT})
            with hb.urllib.request.urlopen(req, timeout=30) as r:
                self.assertEqual(r.status, 200, url)
                self.assertTrue(r.read(16))


@unittest.skipUnless(os.environ.get("RETROSHELF_LIVE_TESTS"),
                     "talks to the real itch.io; set RETROSHELF_LIVE_TESTS=1")
class LiveItchIo(unittest.TestCase):
    """Whether itch.io's feeds answer an app, and in what shape (run by CI, not by default)."""

    def test_feed(self):
        url = itch.feed_url(itch.FILTERS["gb"][0])
        try:
            data = itch._fetch(url)
        except itch.urllib.error.HTTPError as e:
            print(f"\n{url}: HTTP {e.code} (blocked: the window falls back to Browse on itch.io)")
            self.skipTest(f"itch.io answered {e.code}")
        root = ET.fromstring(data)
        item = next(root.iter("item"), None)
        print(f"\n{url}: {len(list(root.iter('item')))} items; fields: "
              f"{sorted(c.tag for c in item) if item is not None else None}")
        games = itch.parse_feed(data)
        print("sample:", {k: v[:60] for k, v in games[0].items()} if games else None)
        self.assertTrue(games)
        self.assertTrue(all(g["url"].startswith("https://") and g["title"] for g in games))


@unittest.skipUnless(os.environ.get("RETROSHELF_LIVE_TESTS"),
                     "talks to the real PDRoms; set RETROSHELF_LIVE_TESTS=1")
class LivePdroms(unittest.TestCase):
    """PDRoms' games pages and file pages still have the shape lib/pdroms.py reads (run by CI, not by default)."""

    def test_games_page_and_file_page(self):
        games, total = pdroms.parse_page(pdroms._fetch(pdroms.games_url("nes")))
        print(f"\nPDRoms NES games: {total} on the site, {len(games)} on page 1; first: {games[:1]}")
        self.assertGreater(total or 0, 20)
        self.assertEqual(len(games), pdroms.PER_PAGE)
        self.assertTrue(all(g["url"].startswith("https://pdroms.de/files/") and g["title"] for g in games))
        d = pdroms.load_details(games[0])
        print("details:", {k: v[:80] for k, v in d.items()})
        self.assertTrue(d.get("description"))
        counts = {}
        for system in ("gb", "gba", "megadrive", "atari2600"):
            counts[system] = pdroms.parse_page(pdroms._fetch(pdroms.games_url(system)))[1]
        print("games per system:", counts)
        self.assertTrue(all(counts.values()))


@unittest.skipUnless(os.environ.get("RETROSHELF_LIVE_TESTS"),
                     "talks to the real mamedev.org; set RETROSHELF_LIVE_TESTS=1")
class LiveMamedev(unittest.TestCase):
    """The whole MAMEDEV list reads, and a ROM set downloads as a zip (run by CI, not by default)."""

    def test_catalog_and_download(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        with mock.patch.object(mamedev, "CACHE", d):
            games = mamedev.load_catalog(refresh=True)
        print(f"\n{len(games)} MAMEDEV games; sets: {[mamedev.rom_name(g) for g in games]}")
        print("sample:", {k: (v[:80] if isinstance(v, str) else v) for k, v in games[0].items()})
        self.assertGreaterEqual(len(games), 20)
        self.assertTrue(all(g["notice"] and g["zips"] for g in games), [g["id"] for g in games if not g["notice"]])
        roms = os.path.join(d, "roms")
        path = mamedev.install(next(g for g in games if g["id"] == "gridlee"), roms)
        self.assertTrue(zipfile.is_zipfile(path))
        print("gridlee.zip holds:", zipfile.ZipFile(path).namelist())


@unittest.skipUnless(os.environ.get("RETROSHELF_LIVE_TESTS"),
                     "talks to ES-DE's GitLab; set RETROSHELF_LIVE_TESTS=1")
class LiveEsde(unittest.TestCase):
    """ES-DE's release list still names a Windows portable build with a checksum (run by CI, not by default)."""

    def test_release_list(self):
        version, pkg = frontend.esde_release()
        print(f"\nES-DE {version}: {pkg}")
        self.assertTrue(pkg["filename"].endswith(".zip") and pkg["url"].startswith("https://"))
        self.assertRegex(pkg["md5"], r"^[0-9a-f]{32}$")


@unittest.skipUnless(os.name == "nt", "real Windows only")
class RealWindows(unittest.TestCase):
    """Things only a real Windows can check: PowerShell shortcuts and Python's own OpenSSL."""

    def test_shortcut_round_trip(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        lnk = os.path.join(d, "Braid (USA).lnk")
        fsutil.make_shortcut(lnk, sys.executable, '--no-gui "%RPCS3_GAMEID%:NPUB30133"', d, sys.executable, "Braid")
        self.assertEqual(nps.shortcut_game_id(lnk), "NPUB30133")
        self.assertIn(d, fsutil.shortcut_text(lnk))

    def test_openssl_from_python(self):
        with mock.patch.object(nps._OpenSSLCtr, "lib", None):
            ctr = nps._OpenSSLCtr(bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c"),
                                  bytes.fromhex("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff"))
            self.assertEqual(ctr.update(bytes.fromhex("874d6191b620e3261bef6864990db6ce")).hex(),
                             "6bc1bee22e409f96e93d7e117393172a")  # NIST SP 800-38A F.5.2


if __name__ == "__main__":
    unittest.main()
