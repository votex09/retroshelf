"""Name parsing, presets, region dupes, rename planning, LaunchBox matching and file helpers. No window needed,
but retroshelf.py imports tkinter, so run these with a Python that has it (tests/run.sh picks one)."""
import json, os, shutil, sys, tempfile, unittest
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
import launchbox as lb  # noqa: E402
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
        with open(p, "w") as f:
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


if __name__ == "__main__":
    unittest.main()
