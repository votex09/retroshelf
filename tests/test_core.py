"""Name parsing, presets, region dupes, rename planning, LaunchBox matching and file helpers. No window needed,
but retroshelf.py imports tkinter, so run these with a Python that has it (tests/run.sh picks one)."""
import json, ntpath, os, posixpath, shutil, subprocess, sys, tempfile, unittest
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
import launchbox as lb  # noqa: E402
import nps  # noqa: E402
import scraper  # noqa: E402
import updater  # noqa: E402
import sandbox  # noqa: E402


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
        self.assertIsNone(nps.emulator_problem("ps3", self.roms))  # not on Linux

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
