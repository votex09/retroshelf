"""Gamepads, without Steam Input or any library: buttons become the keys RetroShelf already understands, sent to
the RetroShelf window that has focus (nothing happens while another app does).

    D-pad / left stick  arrows (held: repeats)      A (✕)  Space     B (○)  Escape    X  Enter    Y  Ctrl+Z
    LB / RB             Shift+Tab / Tab             LT / RT  PgUp / PgDn             Start  Ctrl+R (review)

Where they come from:
  - Linux: /dev/input/event* devices that have gamepad buttons, read directly (desktops let the logged-in user read
    gamepads). Pads plugged in later are picked up within a couple of seconds. On a Steam Deck, Steam holds the
    built-in controls while it runs (in desktop mode it turns them into mouse and keyboard); other pads work as long
    as Steam isn't remapping them.
  - Windows: XInput (xinput1_4.dll, in every Windows), which Xbox-style pads and most others speak.
Button names follow the Xbox layout; the kernel reports other pads' buttons by the same codes (on PlayStation pads:
✕ is A, ○ is B, △ is X and □ is Y)."""
import ctypes, glob, os, struct, sys, time

from fsutil import is_windows

POLL_MS = 16
RESCAN_S = 2.0
REPEAT_DELAY, REPEAT_EVERY = 0.40, 0.08  # seconds: holding a direction repeats it
STICK = 0.55  # how far a stick goes before it counts as a press (0..1)

DIRECTIONS = ("up", "down", "left", "right")
KEYS = {"up": "<Up>", "down": "<Down>", "left": "<Left>", "right": "<Right>", "a": "<space>", "b": "<Escape>",
        "x": "<Return>", "y": "<Control-z>", "rb": "<Tab>", "lt": "<Prior>", "rt": "<Next>", "start": "<Control-r>"}
REPEATS = set(DIRECTIONS) | {"lt", "rt"}

HELP = [
    ("D-pad / left stick", "Move through the list (hold to keep going)"),
    ("A (✕)", "Mark a game and go to the next (Space); press buttons and ticks"),
    ("X", "Flip the marked games, or the selected one (Enter)"),
    ("Y", "Undo (Ctrl+Z)"),
    ("B (○)", "Close the window (Esc)"),
    ("LB / RB", "Switch between Keeping and Moving, or move between controls (Shift+Tab / Tab)"),
    ("LT / RT", "A page up / down"),
    ("Start", "Review one at a time (Ctrl+R)"),
    ("In Review", "A keeps, X moves, ← → back / skip, Y undoes, B closes"),
]


def shift_tab():
    """Tk's name for Shift+Tab: X11 calls it ISO_Left_Tab."""
    return "<Shift-Tab>" if is_windows() or sys.platform == "darwin" else "<ISO_Left_Tab>"


# ---------- Linux: evdev ----------
EV_KEY, EV_ABS = 0x01, 0x03
EVENT = struct.Struct("llHHi")  # struct input_event: timeval, type, code, value
BUTTONS = {0x130: "a", 0x131: "b", 0x133: "x", 0x134: "y", 0x136: "lb", 0x137: "rb", 0x138: "lt", 0x139: "rt",
           0x13a: "select", 0x13b: "start", 0x13c: "mode",
           0x220: "up", 0x221: "down", 0x222: "left", 0x223: "right"}
BTN_SOUTH = 0x130
ABS_X, ABS_Y, ABS_Z, ABS_RZ, ABS_HAT0X, ABS_HAT0Y = 0x00, 0x01, 0x02, 0x05, 0x10, 0x11


def _has_bit(mask_text, bit):
    """sysfs capability masks are hex words, most significant first, one per C long."""
    words = mask_text.split()
    size = struct.calcsize("l") * 8
    i = bit // size
    return i < len(words) and bool(int(words[-1 - i], 16) >> (bit % size) & 1)


def linux_pads(root="/sys/class/input"):
    """[(device path, name)] of the input devices with gamepad buttons."""
    out = []
    for cap in sorted(glob.glob(os.path.join(root, "event*", "device", "capabilities", "key"))):
        try:
            with open(cap, encoding="ascii") as f:
                if not _has_bit(f.read(), BTN_SOUTH):
                    continue
            with open(os.path.join(os.path.dirname(os.path.dirname(cap)), "name"), encoding="utf-8",
                      errors="replace") as f:
                name = f.read().strip()
        except OSError:
            continue
        out.append(("/dev/input/" + cap.split(os.sep)[-4], name or "Gamepad"))
    return out


def _abs_range(fd, code):
    """(min, max) of an axis, from EVIOCGABS; (-32768, 32767) if the device won't say."""
    try:
        import fcntl
        req = (2 << 30) | (24 << 16) | (ord("E") << 8) | (0x40 + code)
        _, lo, hi, _, _, _ = struct.unpack("6i", fcntl.ioctl(fd, req, bytes(24)))
        return (lo, hi) if hi > lo else (-32768, 32767)
    except (OSError, ImportError):
        return (-32768, 32767)


class LinuxPad:
    """One evdev gamepad: read() drains its events into .pressed (logical button names)."""

    def __init__(self, path, name, fd=None):
        self.path, self.name = path, name
        self.fd = fd if fd is not None else os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        self.ranges = {}
        self.buttons, self.axes = set(), {}

    def _axis(self, code, value):
        if code not in self.ranges:
            self.ranges[code] = _abs_range(self.fd, code)
        lo, hi = self.ranges[code]
        mid, half = (lo + hi) / 2, max((hi - lo) / 2, 1)
        return (value - mid) / half  # -1 .. 1

    def read(self):
        """-> False once the device is gone (unplugged)."""
        while True:
            try:
                data = os.read(self.fd, EVENT.size * 64)
            except BlockingIOError:
                return True
            except OSError:
                return False
            if not data:
                return True
            for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
                _, _, kind, code, value = EVENT.unpack_from(data, i)
                if kind == EV_KEY and code in BUTTONS:
                    (self.buttons.add if value else self.buttons.discard)(BUTTONS[code])
                elif kind == EV_ABS:
                    if code in (ABS_HAT0X, ABS_HAT0Y):
                        self.axes[code] = max(-1, min(1, value))
                    elif code in (ABS_X, ABS_Y):
                        self.axes[code] = self._axis(code, value)
                    elif code in (ABS_Z, ABS_RZ):  # analog triggers (Xbox): 0 .. max
                        lo, hi = self.ranges.get(code) or self.ranges.setdefault(code, _abs_range(self.fd, code))
                        self.axes[code] = (value - lo) / max(hi - lo, 1)

    @property
    def pressed(self):
        p = set(self.buttons)
        hx, hy = self.axes.get(ABS_HAT0X, 0), self.axes.get(ABS_HAT0Y, 0)
        sx, sy = self.axes.get(ABS_X, 0), self.axes.get(ABS_Y, 0)
        if hx < 0 or sx < -STICK:
            p.add("left")
        if hx > 0 or sx > STICK:
            p.add("right")
        if hy < 0 or sy < -STICK:
            p.add("up")
        if hy > 0 or sy > STICK:
            p.add("down")
        if self.axes.get(ABS_Z, 0) > 0.6:
            p.add("lt")
        if self.axes.get(ABS_RZ, 0) > 0.6:
            p.add("rt")
        return p

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


class LinuxSource:
    def __init__(self):
        self.pads, self.next_scan, self.denied = {}, 0.0, set()

    def scan(self):
        """-> names of pads that just appeared."""
        new = []
        for path, name in linux_pads():
            if path in self.pads or path in self.denied:
                continue
            try:
                self.pads[path] = LinuxPad(path, name)
                new.append(name)
            except OSError:  # no permission (not the logged-in user's device): don't keep trying
                self.denied.add(path)
        return new

    def poll(self, now):
        new = []
        if now >= self.next_scan:
            self.next_scan = now + RESCAN_S
            new = self.scan()
        pressed = set()
        for path, pad in list(self.pads.items()):
            if not pad.read():
                pad.close()
                del self.pads[path]
                continue
            pressed |= pad.pressed
        return pressed, new


# ---------- Windows: XInput ----------
XI_BUTTONS = {0x0001: "up", 0x0002: "down", 0x0004: "left", 0x0008: "right", 0x0010: "start", 0x0020: "select",
              0x0100: "lb", 0x0200: "rb", 0x1000: "a", 0x2000: "b", 0x4000: "x", 0x8000: "y"}


class _Gamepad(ctypes.Structure):
    _fields_ = [("buttons", ctypes.c_ushort), ("lt", ctypes.c_ubyte), ("rt", ctypes.c_ubyte),
                ("lx", ctypes.c_short), ("ly", ctypes.c_short), ("rx", ctypes.c_short), ("ry", ctypes.c_short)]


class _State(ctypes.Structure):
    _fields_ = [("packet", ctypes.c_uint), ("pad", _Gamepad)]


def xinput_pressed(pad):
    """An XINPUT_GAMEPAD -> logical buttons."""
    p = {name for bit, name in XI_BUTTONS.items() if pad.buttons & bit}
    if pad.lx < -STICK * 32768:
        p.add("left")
    if pad.lx > STICK * 32767:
        p.add("right")
    if pad.ly > STICK * 32767:  # XInput's y points up
        p.add("up")
    if pad.ly < -STICK * 32768:
        p.add("down")
    if pad.lt > 150:
        p.add("lt")
    if pad.rt > 150:
        p.add("rt")
    return p


class XInputSource:
    def __init__(self):
        self.dll = None
        for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                self.dll = ctypes.WinDLL(name)
                break
            except OSError:
                continue
        self.connected, self.next_scan = set(), 0.0

    def poll(self, now):
        if not self.dll:
            return set(), []
        pressed, new = set(), []
        scan = now >= self.next_scan  # asking for an absent pad is slow: only look for new ones now and then
        if scan:
            self.next_scan = now + RESCAN_S
        for i in range(4):
            if i not in self.connected and not scan:
                continue
            state = _State()
            if self.dll.XInputGetState(i, ctypes.byref(state)) != 0:
                self.connected.discard(i)
                continue
            if i not in self.connected:
                self.connected.add(i)
                new.append(f"Controller {i + 1}")
            pressed |= xinput_pressed(state.pad)
        return pressed, new


# ---------- buttons -> keys ----------
class Repeater:
    """Turns the set of held buttons into presses: each new button once, directions (and page) again while held."""

    def __init__(self):
        self.held = {}  # button -> time of its next repeat

    def update(self, pressed, now):
        out = []
        for b in pressed:
            if b not in self.held:
                out.append(b)
                self.held[b] = now + REPEAT_DELAY
            elif b in REPEATS and now >= self.held[b]:
                out.append(b)
                self.held[b] = now + REPEAT_EVERY
        for b in list(self.held):
            if b not in pressed:
                del self.held[b]
        return out


def default_source():
    if is_windows():
        return XInputSource()
    if sys.platform.startswith("linux"):
        return LinuxSource()
    return None


class Gamepads:
    """Polls the pads on Tk's timer and sends the matching key to the widget that has the keyboard."""

    def __init__(self, root, on_connect=lambda name: None, source=None, clock=time.monotonic):
        self.root, self.on_connect, self.clock = root, on_connect, clock
        self.source = source if source is not None else default_source()
        self.repeater = Repeater()
        self.enabled = True
        self.keys = dict(KEYS, lb=shift_tab())
        self.cmd = root.register(self._tick)  # registered once (see video.Timer for why not after())
        self.job = None
        if self.source is not None:
            self.job = root.tk.call("after", POLL_MS, self.cmd)

    def _tick(self):
        self.job = None
        try:
            self.step()
        finally:
            if self.source is not None:
                self.job = self.root.tk.call("after", POLL_MS, self.cmd)

    def step(self):
        pressed, new = self.source.poll(self.clock())
        for name in new:
            self.on_connect(name)
        target = self.root.focus_get()  # None while another app has the focus
        if not self.enabled or target is None:
            self.repeater.update(set(), self.clock())  # a button held while away doesn't fire on return
            return []
        sent = []
        for b in self.repeater.update(pressed, self.clock()):
            seq = self.keys.get(b)
            if seq:
                self.press(target, seq)
                sent.append(b)
        return sent

    def press(self, widget, seq):
        try:
            widget.event_generate(seq)
        except Exception:  # the widget went away between polls
            pass

    def names(self):
        """The pads found so far."""
        src = self.source
        if isinstance(src, LinuxSource):
            return [p.name for p in src.pads.values()]
        if isinstance(src, XInputSource):
            return [f"Controller {i + 1}" for i in sorted(src.connected)]
        return []

    def stop(self):
        if self.job:
            try:
                self.root.tk.call("after", "cancel", self.job)
            except Exception:
                pass
        self.job, self.source = None, None
