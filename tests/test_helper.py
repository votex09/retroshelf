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


def session(data, script):
    """Run script in a fresh helper process (its methods as h.name), with settings in data -> what it prints, as JSON.
    The window's requests can come back in any order, so steps that build on each other are tested this way."""
    code = f"import json, sys; sys.path.insert(0, {os.path.dirname(HELPER)!r}); import helper as h\n{script}"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, encoding="utf-8",
                         env={**os.environ, "RETROSHELF_DATA": data})
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout.splitlines()[-1])


class MainWindow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.roms = os.path.join(self.tmp.name, "roms")
        self.data = os.path.join(self.tmp.name, "data")
        make_roms(self.roms)
        os.makedirs(self.data)
        with open(os.path.join(self.data, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"roms_root": self.roms}, f)

    def tearDown(self):
        self.tmp.cleanup()

    def config(self):
        with open(os.path.join(self.data, "config.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_open_decide_and_remember(self):
        out = session(self.data, """
ov = h.startup()
sys_ = h.open_system("snes")
st = dict(sys_["state"], presets=["Partial downloads (.part)"], flips={"Chrono Trigger (USA)": True})
d = h.decide(st, cursor_key="Super Metroid (USA)")
print(json.dumps({"ov": ov, "sys": sys_, "d": d, "det": h.details("Chrono Trigger (USA)")}))""")
        self.assertEqual(out["ov"]["roms"], self.roms)
        self.assertIn("snes", [s["code"] for s in out["ov"]["systems"]])
        self.assertEqual(out["sys"]["fullname"], "Nintendo SNES (Super Nintendo)")
        self.assertEqual([g["key"] for g in out["sys"]["games"]],
                         ["Chrono Trigger (USA)", "EarthBound (USA).sfc.part", "Super Metroid (USA)"])
        self.assertEqual(out["sys"]["decision"]["move"], [])  # no filters yet
        self.assertEqual(sorted(out["d"]["move"]), ["Chrono Trigger (USA)", "EarthBound (USA).sfc.part"])
        self.assertEqual(out["d"]["why"]["Chrono Trigger (USA)"], "manual")
        self.assertEqual(out["d"]["tabs"], [1, 0, 0, 0])
        self.assertEqual(out["det"]["file"], "Chrono Trigger (USA).sfc")
        self.assertEqual(out["det"]["images"], [])
        saved = self.config()
        self.assertEqual(saved["system"], "snes")
        self.assertEqual(saved["system_state"]["snes"]["presets"], ["Partial downloads (.part)"])
        self.assertEqual(saved["system_state"]["snes"]["cursor_key"], "Super Metroid (USA)")
        # opened again, the system comes back with its filters and flips
        again = session(self.data, 'h.startup(); print(json.dumps(h.open_system("snes")))')
        self.assertEqual(sorted(again["decision"]["move"]), ["Chrono Trigger (USA)", "EarthBound (USA).sfc.part"])
        self.assertEqual(again["cursor"], "Super Metroid (USA)")

    def test_move(self):
        out = session(self.data, """
h.startup(); s = h.open_system("snes")
h.decide(dict(s["state"], flips={"Chrono Trigger (USA)": True, "Super Metroid (USA)": True}))
plan = h.move_plan("to_delete")
print(json.dumps({"plan": plan, "moved": h.move("to_delete")}))""")
        holding = os.path.join(self.tmp.name, "pruned", "to_delete", "snes")
        self.assertEqual(out["plan"]["games"], 2)
        self.assertEqual(out["plan"]["dest_dir"], holding)
        self.assertTrue(out["plan"]["same_drive"])
        self.assertEqual(out["moved"]["moved"], {"files": 2, "failed": [], "dest": "to_delete"})
        self.assertEqual([g["key"] for g in out["moved"]["games"]], ["EarthBound (USA).sfc.part"])
        self.assertEqual(sorted(os.listdir(holding)), ["Chrono Trigger (USA).sfc", "Super Metroid (USA).zip"])
        with open(os.path.join(self.data, "moves.json"), encoding="utf-8") as f:
            log = json.load(f)
        self.assertEqual((log[0]["system"], log[0]["games"], len(log[0]["moves"])), ("snes", 2, 2))

    def test_holding_folder_and_restore(self):
        out = session(self.data, """
h.startup(); s = h.open_system("snes")
h.decide(dict(s["state"], flips={"Chrono Trigger (USA)": True, "Super Metroid (USA)": True}))
h.move("to_delete")
held = h.holding_list()
chrono = [g["id"] for g in held["games"] if g["key"] == "Chrono Trigger (USA)"]
back = h.holding_restore(chrono)
runs = h.moves()
undo = h.restore_moves([runs[0]["id"]])
print(json.dumps({"held": held, "back": back, "runs": runs, "undo": undo, "after": h.holding_list(),
                  "moves": h.moves()}))""")
        self.assertEqual(sorted(g["key"] for g in out["held"]["games"]), ["Chrono Trigger (USA)", "Super Metroid (USA)"])
        self.assertEqual(out["held"]["root"], os.path.join(self.tmp.name, "pruned"))
        self.assertEqual((out["back"]["back"], out["back"]["failed"]), (1, []))
        self.assertEqual([g["key"] for g in out["back"]["holding"]["games"]], ["Super Metroid (USA)"])
        self.assertEqual((out["runs"][0]["files"], out["runs"][0]["left"]), (1, 1))  # Chrono left the log
        self.assertEqual((out["undo"]["back"], out["undo"]["failed"]), (1, []))
        self.assertEqual((out["after"]["games"], out["moves"]), ([], []))
        self.assertEqual(sorted(os.listdir(os.path.join(self.roms, "snes"))),
                         ["Chrono Trigger (USA).sfc", "EarthBound (USA).sfc.part", "Super Metroid (USA).zip",
                          "readme.txt", "systeminfo.txt"])

    def test_holding_delete(self):
        out = session(self.data, """
h.startup(); s = h.open_system("snes")
h.decide(dict(s["state"], flips={"Super Metroid (USA)": True}))
h.move("review_low_value")
print(json.dumps(h.holding_delete([g["id"] for g in h.holding_list()["games"]], forget=True)))""")
        self.assertEqual((out["deleted"], out["failed"], out["holding"]["games"]), (1, [], []))
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "pruned", "review_low_value", "snes")))

    def test_hide_and_priority(self):
        out = session(self.data, """
h.startup(); s = h.open_system("snes")
h.decide(dict(s["state"], flips={"Chrono Trigger (USA)": True}))
check = h.hide_check(["Chrono Trigger (USA)"])
hid = h.hide(["Chrono Trigger (USA)"])
prio = h.region_priority()
d = h.set_region_priority(["Japan", "USA"])
print(json.dumps({"check": check, "hid": hid, "prio": prio, "d": d}))""")
        self.assertEqual(out["check"]["games"], 1)
        self.assertEqual(out["hid"]["hidden"], 1)
        chrono = [g for g in out["hid"]["games"] if g["key"] == "Chrono Trigger (USA)"][0]
        self.assertTrue(chrono["hidden"])
        self.assertFalse(chrono["move"])  # the flip that sent it to Moving is dropped; hidden games stay
        self.assertEqual(out["hid"]["state"]["flips"], {})
        self.assertEqual(out["prio"]["order"][0], "USA")
        self.assertEqual(self.config()["region_priority"], "Japan, USA")
        gl = os.path.join(self.roms, "snes", "gamelist.xml")
        if not os.path.exists(gl):
            gl = [os.path.join(d, f) for d, _, fs in os.walk(self.tmp.name) for f in fs if f == "gamelist.xml"][0]
        with open(gl, encoding="utf-8") as f:
            self.assertIn("<hidden>true</hidden>", f.read())

    def test_export(self):
        path = os.path.join(self.tmp.name, "out.txt")
        session(self.data, f"""
h.startup(); s = h.open_system("snes")
h.decide(dict(s["state"], presets=["Partial downloads (.part)"]))
print(json.dumps(h.export_moves({path!r})))""")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "EarthBound (USA).sfc.part\n")

    def test_collections(self):
        out = session(self.data, """
h.startup(); h.open_system("snes")
first = h.save_collection(["Chrono Trigger (USA)", "Super Metroid (USA)"], "My: Faves", show=False)
again = h.save_collection(["Chrono Trigger (USA)", "EarthBound (USA).sfc.part"], "My Faves", show=False)
print(json.dumps({"first": first, "again": again, "list": h.collections()}))""")
        self.assertEqual((out["first"]["name"], out["first"]["new"], out["first"]["added"]), ("My Faves", True, 2))
        self.assertEqual((out["again"]["new"], out["again"]["added"], out["again"]["files"]), (False, 1, 2))
        self.assertEqual(out["list"], {"names": {"My Faves": 3}, "last": "My Faves"})

    def test_needs_a_system(self):
        with self.assertRaisesRegex(AssertionError, "No system is open"):
            session(self.data, 'h.startup(); h.decide({})')


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
