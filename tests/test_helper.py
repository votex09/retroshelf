"""The Electron app's Python helper (app/helper/helper.py), spoken to the way the app does: JSON lines over a pipe.
Needs no tkinter or display. Also lib/library.py, the Tk-free ROMs-folder code it shares with retroshelf.py."""
import io, json, os, subprocess, sys, tempfile, unittest, zipfile

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS)
HELPER = os.path.join(REPO, "app", "helper", "helper.py")
sys.path.insert(0, os.path.join(REPO, "lib"))
sys.path.insert(0, TESTS)
import discs  # noqa: E402
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
    """Run script in a fresh helper process (the window's methods as h.name), with settings in data -> what it
    prints, as JSON.
    The window's requests can come back in any order, so steps that build on each other are tested this way."""
    code = (f"import json, sys; sys.path.insert(0, {os.path.dirname(HELPER)!r}); import helper\n"
            "h = type('H', (), {'__getattr__': lambda self, name: helper.METHODS[name]})()\n" + script)
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

    def test_rename_and_undo(self):
        out = session(self.data, """
h.startup(); s = h.open_system("snes")
h.decide(dict(s["state"], flips={"Chrono Trigger (USA)": True}))
info = h.rename_info()
plan = h.rename_plan("{title}")
done = h.rename_apply("{title}")
runs = h.rename_runs()
undo = h.rename_undo([runs[0]["id"]])
print(json.dumps({"info": info, "plan": plan, "done": done, "runs": runs, "undo": undo, "left": h.rename_runs()}))""")
        self.assertFalse(out["info"]["arcade"])
        self.assertEqual((out["plan"]["rename"], out["plan"]["skip"]), (2, 1))  # the .part download is skipped
        self.assertIn({"key": "Chrono Trigger (USA)", "old": "Chrono Trigger (USA).sfc", "new": "Chrono Trigger.sfc",
                       "status": "rename"}, out["plan"]["rows"])
        self.assertEqual(out["done"]["renamed"]["files"], 2)
        self.assertEqual(out["done"]["state"]["flips"], {"Chrono Trigger": True})  # the flip follows the game
        self.assertEqual(self.config()["rename_templates"], {"snes": "{title}"})
        self.assertEqual((out["runs"][0]["files"], out["undo"]["back"], out["left"]), (2, 2, []))
        self.assertIn("Chrono Trigger (USA).sfc", os.listdir(os.path.join(self.roms, "snes")))

    def test_jobs_can_be_stopped(self):
        out = session(self.data, """
import rpc
events = []
rpc.event = lambda name, data=None: events.append((name, data))
report, stop = rpc.progress("j1"), rpc.stopped("j1")
before = stop()
rpc.METHODS["cancel"]("j1")
print(json.dumps({"before": before, "after": stop(), "other": rpc.stopped("j2")()}))""")
        self.assertEqual(out, {"before": False, "after": True, "other": False})

    def test_first_run_setup(self):
        place = os.path.join(self.tmp.name, "sd")
        os.makedirs(place)
        out = session(self.data, f"""
import rpc, frontend, tool_setup
events = []
rpc.event = lambda name, data=None: events.append(data["message"])
tool_setup.is_windows = frontend.is_windows = lambda: False  # the Linux flow, wherever the tests run
frontend.retrodeck_installed = lambda: False
frontend.install_retrodeck = lambda log, cancelled: [log("$ install"), log("done")]
start = h.startup()
info = h.setup_info()
res = h.setup_install("j1", "custom", {place!r})
try:
    h.setup_install("j2", "custom", {os.path.join(place, "nope")!r})
    bad = ""
except PermissionError as e:
    bad = str(e)
done = h.setup_done({self.roms!r})
print(json.dumps({{"offered": start["setup_offered"], "name": info["name"], "res": res, "events": events, "bad": bad,
                  "roms": done["roms"], "tips": len(done["tips"])}}))""")
        self.assertFalse(out["offered"])
        self.assertEqual(out["name"], "RetroDECK")
        self.assertEqual(out["events"], ["$ install", "done"])
        self.assertEqual(out["res"]["expected"], os.path.join(place, "retrodeck", "roms"))
        self.assertIn(place, out["res"]["steps"][1])
        self.assertIn("can't write", out["bad"])
        self.assertEqual(out["roms"], os.path.realpath(self.roms))
        self.assertEqual(out["tips"], 2)
        self.assertTrue(self.config()["setup_offered"])
        self.assertEqual(session(self.data, 'print(json.dumps(h.startup()["setup_offered"]))'), True)

    def test_storage_overview(self):
        with open(os.path.join(self.roms, "snes", "Chrono Trigger (USA).sfc"), "w") as f:
            f.write("x" * 100)
        out = session(self.data, """
import rpc
events = []
rpc.event = lambda name, data=None: events.append(data)
h.startup()
print(json.dumps({"st": h.storage_scan("j1"), "events": events}))""")
        (snes,) = out["st"]["systems"]
        self.assertEqual((snes["code"], snes["label"]), ("snes", "snes — Nintendo SNES (Super Nintendo)"))
        self.assertEqual((snes["games"], snes["size"], snes["media"], snes["more"]), (3, 100, 0, 0))
        self.assertEqual(snes["biggest"][0], ["Chrono Trigger (USA)", 100])  # the main window's keys
        self.assertGreater(out["st"]["drive"]["total"], 0)
        self.assertEqual(out["events"][0]["job"], "j1")

    def test_health_check(self):
        out = session(self.data, """
h.startup(); h.open_system("snes")
found = h.health_scan("j1", system="snes")
ids = [p["id"] for p in found["problems"] if p["fix"]]
plan = h.health_fix_plan(ids)
print(json.dumps({"found": found, "plan": plan, "fixed": h.health_fix(ids), "again": h.health_scan("j2")}))""")
        self.assertEqual([(p["kind"], p["name"]) for p in out["found"]["problems"]],
                         [("empty", "Chrono Trigger (USA).sfc"), ("empty", "Super Metroid (USA).zip")])
        self.assertEqual(out["plan"], {"lines": ["Empty game files: 2 (delete it)"], "deletes": 2})
        self.assertEqual(out["fixed"]["done"], {"0": "Deleted Chrono Trigger (USA).sfc",
                                                "1": "Deleted Super Metroid (USA).zip"})
        self.assertEqual((out["fixed"]["failed"], out["fixed"]["systems"]), ({}, ["snes"]))
        self.assertEqual(out["again"]["problems"], [])
        self.assertNotIn("Chrono Trigger (USA).sfc", os.listdir(os.path.join(self.roms, "snes")))

    def test_find_duplicates(self):
        game = os.path.join(self.roms, "snes", "Chrono Trigger (USA).sfc")
        with open(game, "w") as f:
            f.write("x" * 100)
        os.makedirs(os.path.join(self.roms, "sfc"))
        with open(os.path.join(self.roms, "sfc", "Chrono Trigger (USA).sfc"), "w") as f:
            f.write("x" * 100)
        out = session(self.data, """
h.startup()
found = h.dupes_scan("j1")
s = found["sets"][0]
keep = [i for i, c in enumerate(s["copies"]) if c["system"] == "sfc"][0]  # keep the sfc one instead
done = h.dupes_resolve({str(s["id"]): keep})
print(json.dumps({"found": found, "done": done, "twice": h.dupes_resolve({str(s["id"]): keep}),
                  "runs": h.moves()}))""")
        (s,) = out["found"]["sets"]
        self.assertEqual((s["kind"], s["title"], s["extra"]), ("copies", "Chrono Trigger (USA)", 100))
        self.assertEqual(s["copies"][s["keep"]]["system"], "snes")  # the fuller folder keeps its copy
        self.assertEqual(out["found"]["holding"], os.path.join(self.tmp.name, "pruned", "to_delete"))
        self.assertEqual(out["done"], {"moved": 1, "sets": [0], "systems": ["snes"], "problems": []})
        self.assertEqual(out["twice"]["moved"], 0)  # a set is only moved once
        self.assertFalse(os.path.exists(game))
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "pruned", "to_delete", "snes",
                                                    "Chrono Trigger (USA).sfc")))
        self.assertEqual((out["runs"][0]["system"], out["runs"][0]["files"]), ("snes", 1))

    def test_needs_a_system(self):
        with self.assertRaisesRegex(AssertionError, "No system is open"):
            session(self.data, 'h.startup(); h.decide({})')

    def write(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def test_compress(self):
        psx = os.path.join(self.roms, "psx")
        sotn = "Castlevania - Symphony of the Night (USA)"
        self.write(os.path.join(psx, f"{sotn}.cue"), f'FILE "{sotn} (Track 1).bin" BINARY\n  TRACK 01 MODE2/2352\n'
                   f'FILE "{sotn} (Track 2).bin" BINARY\n  TRACK 02 AUDIO\n'.encode())
        for t in (1, 2):
            self.write(os.path.join(psx, f"{sotn} (Track {t}).bin"), b"\0" * 300_000)
        self.write(os.path.join(psx, "Final Fantasy VII (USA).chd"), b"\0" * 1000)
        out = session(self.data, f"""
import compress, rpc, tool_files
compress.find_tool = lambda name: compress.Tool(name, "the tests", [sys.executable, {os.path.join(TESTS, "fake_disc_tool.py")!r}])
events = []
rpc.event = tool_files.event = lambda name, data=None: events.append(data)
h.startup()
snes = h.open_system("snes") and h.compress_info()
h.open_system("psx")
info, tool = h.compress_info(), h.compress_tool()
done = h.compress_games("j1", [{sotn!r}])
print(json.dumps({{"snes": snes, "info": info, "tool": tool, "done": done, "after": h.compress_info(),
                  "rows": [e for e in events if "key" in e], "runs": h.moves()}}))""")
        self.assertEqual(out["snes"], {"supported": False, "listed": False})
        self.assertEqual(out["info"]["format"], "CHD")
        self.assertEqual([(r["key"], r["now"], r["discs"]) for r in out["info"]["rows"]], [(sotn, "cue + 2 bin", 1)])
        self.assertEqual(out["info"]["skipped"], [{"key": "Final Fantasy VII (USA)", "why": "already compressed"}])
        self.assertEqual(out["info"]["holding"], os.path.join(self.tmp.name, "pruned", "to_delete", "psx"))
        self.assertEqual(out["tool"]["where"], "the tests")
        self.assertEqual((out["done"]["games"], out["done"]["problems"], out["done"]["stopped"]), (1, [], False))
        self.assertEqual(out["rows"][-1]["tag"], "done")
        self.assertEqual(sorted(n for n in os.listdir(psx) if n.startswith(sotn)), [f"{sotn}.chd"])
        self.assertEqual(len(os.listdir(out["info"]["holding"])), 3)
        self.assertEqual(out["after"]["rows"], [])
        self.assertEqual((out["runs"][0]["system"], out["runs"][0]["files"]), ("psx", 3))  # Restore a move can undo it

    def test_import(self):
        inbox = os.path.join(self.tmp.name, "import")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("mystery.p1", b"x" * 10)
        for name, data in (("Gran Turismo 4 (USA).7z", discs.seven_zip({"Gran Turismo 4 (USA).iso": discs.ps2()})),
                           ("mystery.zip", buf.getvalue()), ("Tetris (World).gb", b"T" * 64)):
            self.write(os.path.join(inbox, name), data)
        nas = os.path.join(self.tmp.name, "nas", "PS2 Collection")
        for rel in ("Okami (USA)/Okami (USA).7z", "Ico (USA).7z"):
            self.write(os.path.join(nas, rel), discs.seven_zip({"x.iso": discs.ps2()}))
        out = session(self.data, f"""
import rpc
rpc.event = lambda name, data=None: None
h.startup()
info = h.import_info()
scanned = h.import_scan()
h.import_set_system([r["id"] for r in scanned["rows"] if r["name"] == "mystery.zip"], "fbneo")
done = h.import_run("j1")
try:
    h.import_set_inbox({os.path.join(self.roms, "inbox")!r})
    inside = None
except ValueError as e:
    inside = str(e)
folder = h.import_folder({nas!r})
added = h.import_add_folder()
with open({os.path.join(inbox, "Metroid (USA).gba")!r}, "wb") as f:
    f.write(b"M" * 64)
watch = [h.import_watch(), h.import_watch()]
print(json.dumps({{"info": info, "scanned": scanned, "done": done, "inside": inside, "folder": folder,
                  "added": added, "watch": watch}}))""")
        self.assertEqual(out["info"]["inbox"], inbox)
        self.assertTrue(all(r["status"] == "Checking …" for r in out["info"]["rows"]))
        self.assertEqual({r["name"]: r["system"] for r in out["scanned"]["rows"]},
                         {"Gran Turismo 4 (USA).7z": "PlayStation 2", "mystery.zip": "?", "Tetris (World).gb": "Game Boy"})
        self.assertEqual((out["scanned"]["ready"], out["scanned"]["unknown"]), (2, 1))
        self.assertEqual((out["done"]["imported"], out["done"]["systems"]), (3, ["fbneo", "gb", "ps2"]))
        for rel in ("ps2/Gran Turismo 4 (USA).iso", "fbneo/mystery.zip", "gb/Tetris (World).gb"):
            self.assertTrue(os.path.exists(os.path.join(self.roms, *rel.split("/"))), rel)
        self.assertEqual(out["inside"], "The import folder can't be inside your ROMs folder.")
        self.assertEqual(out["folder"], {"games": 2, "folders": 2})
        self.assertEqual(sorted(r["name"] for r in out["added"]["rows"] if r["status"] == "Checking …"),
                         ["Ico (USA).7z", "Okami (USA).7z"])
        self.assertIsNone(out["watch"][0])  # seen once: it might still be copying
        self.assertIn("Metroid (USA).gba", [r["name"] for r in out["watch"][1]["rows"]])
        self.assertTrue(os.path.exists(os.path.join(nas, "Ico (USA).7z")))  # added from elsewhere: copied, not moved


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
