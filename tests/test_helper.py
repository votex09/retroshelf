"""The Electron app's Python helper (app/helper/helper.py), spoken to the way the app does: JSON lines over a pipe.
Needs no tkinter or display. Also lib/library.py, the Tk-free ROMs-folder code it shares with retroshelf.py."""
import json, os, subprocess, sys, tempfile, unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS)
HELPER = os.path.join(REPO, "app", "helper", "helper.py")
sys.path.insert(0, os.path.join(REPO, "lib"))
import library  # noqa: E402


def talk(*requests):
    """Send requests to a fresh helper, close its input -> (the ready event, {id: answer})."""
    lines = "".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in requests)
    out = subprocess.run([sys.executable, HELPER], input=lines, capture_output=True, text=True, timeout=60,
                         encoding="utf-8").stdout
    msgs = [json.loads(x) for x in out.splitlines()]
    return msgs[0], {m["id"]: m for m in msgs[1:]}


def make_roms(base):
    snes = os.path.join(base, "snes")
    os.makedirs(snes)
    with open(os.path.join(snes, "systeminfo.txt"), "w", encoding="utf-8") as f:
        f.write("System name:\nsnes\n\nFull system name:\nNintendo SNES (Super Nintendo)\n\n"
                "Supported file extensions:\n.sfc .zip\n")
    for name in ("Chrono Trigger (USA).sfc", "Super Metroid (USA).zip", "readme.txt", "EarthBound (USA).sfc.part"):
        open(os.path.join(snes, name), "w").close()
    os.makedirs(os.path.join(base, "empty"))
    os.makedirs(os.path.join(base, "_hidden"))


class Helper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.roms = os.path.join(self.tmp.name, "roms")
        make_roms(self.roms)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ready_then_answers(self):
        ready, answers = talk({"id": 1, "method": "hello"},
                              {"id": 2, "method": "systems", "params": {"roms": self.roms}},
                              {"id": 3, "method": "disk", "params": {"path": os.path.join(self.roms, "not", "yet")}})
        self.assertEqual(ready["event"], "ready")
        self.assertEqual(ready["data"]["protocol"], 1)
        self.assertEqual(answers[1]["result"]["protocol"], 1)
        snes = [s for s in answers[2]["result"] if s["code"] == "snes"]
        self.assertEqual(snes, [{"code": "snes", "name": "Nintendo SNES (Super Nintendo)", "games": 3}])
        codes = {s["code"] for s in answers[2]["result"]}
        self.assertNotIn("empty", codes)
        self.assertNotIn("_hidden", codes)
        self.assertIn("ps3", codes)  # NoPayStation systems are listed even without a folder
        self.assertGreater(answers[3]["result"]["total"], 0)

    def test_errors_come_back_as_answers(self):
        _, answers = talk({"id": 1, "method": "nope"}, "not json",
                          {"id": 2, "method": "systems", "params": {"roms": os.path.join(self.roms, "missing")}},
                          {"id": 3, "method": "systems", "params": {"wrong": 1}},
                          {"id": 4, "method": "hello"})
        self.assertEqual(answers[1]["error"]["type"], "LookupError")
        self.assertEqual(answers[None]["error"]["type"], "ValueError")
        self.assertEqual(answers[2]["error"]["type"], "FileNotFoundError")
        self.assertEqual(answers[3]["error"]["type"], "TypeError")
        self.assertIn("result", answers[4])  # the helper keeps going after errors


class Library(unittest.TestCase):
    def test_systems_and_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_roms(tmp)
            found = {code: (name, n) for code, name, n in library.systems(tmp)}
            self.assertEqual(found["snes"], ("Nintendo SNES (Super Nintendo)", 3))
            self.assertEqual(found["ps3"][1], 0)
            names = sorted(e.name for e in library.list_entries(os.path.join(tmp, "snes"), {".sfc", ".zip"}))
            self.assertEqual(names, ["Chrono Trigger (USA).sfc", "EarthBound (USA).sfc.part", "Super Metroid (USA).zip"])


if __name__ == "__main__":
    unittest.main()
