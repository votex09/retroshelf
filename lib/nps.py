"""NoPayStation: browse the NPS lists, download PS3 / PS Vita / PSP packages and install them for RetroDECK.

PS3  -> pkg decrypted here into RPCS3's dev_hdd0/game/<id>/, rap copied to exdata, .desktop shortcut in roms/ps3;
        updates for installed games come from Sony's update server (NPS doesn't list PS3 updates)
PSV  -> Vita3K --pkg/--zrif (headless), <name>.psvita in roms/psvita holding the title id
PSP  -> pkg decrypted here, USRDIR/CONTENT/EBOOT.PBP written as roms/psp/<name>.pbp (PPSSPP plays it as-is)
PSX is left out on purpose: PS1 Classics come out as encrypted PBPs that DuckStation / Beetle refuse to load.
"""
import csv, ctypes, ctypes.util, hashlib, json, os, re, shutil, ssl, struct, subprocess, urllib.error, urllib.request
import xml.etree.ElementTree as ET

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(APP_DIR, "cache", "nps")
TSV_URL = "https://nopaystation.com/tsv/{}.tsv"
USER_AGENT = "RetroShelf/1.0"
FLATPAK = "net.retrodeck.retrodeck"
FLATPAK_CONFIG = os.path.expanduser(f"~/.var/app/{FLATPAK}/config")

# ES-DE system -> (NPS console, {type label: TSV name})
CONSOLES = {
    "ps3": ("PS3", {"Games": "PS3_GAMES", "DLC": "PS3_DLCS", "Demos": "PS3_DEMOS", "Updates": None}),
    "psvita": ("PSV", {"Games": "PSV_GAMES", "DLC": "PSV_DLCS", "Demos": "PSV_DEMOS"}),
    "psp": ("PSP", {"Games": "PSP_GAMES"}),
}
FULL_NAMES = {"ps3": "Sony PlayStation 3", "psvita": "Sony PlayStation Vita", "psp": "Sony PlayStation Portable"}
REGIONS = {"US": "USA", "EU": "Europe", "JP": "Japan", "ASIA": "Asia", "INT": "World"}
CID_REGIONS = {"UP": "US", "EP": "EU", "JP": "JP", "HP": "ASIA", "KP": "ASIA"}  # content id prefix -> NPS region
PS3_UPDATE_URL = "https://a0.ww.np.dl.playstation.net/tpl/np/{0}/{0}-ver.xml"
PSP_SKIP_TYPES = {"PC Engine", "NeoGeo"}  # need the PSP's built-in emulators, which PPSSPP doesn't have

PS3_KEY = bytes.fromhex("2E7B71D7C9C9A14EA3221F188828B8F8")
PSP_KEY = bytes.fromhex("07F2C68290B50D2C33818D709B60E62B")
CHUNK = 4 << 20


# ---------- lists ----------
def tsv_path(name):
    return os.path.join(CACHE, name + ".tsv")


def fetch_list(name):
    os.makedirs(CACHE, exist_ok=True)
    req = urllib.request.Request(TSV_URL.format(name), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    tmp = tsv_path(name) + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, tsv_path(name))


def load_list(system, kind):
    """-> list of row dicts that can actually be downloaded and installed. Fetches the TSV if it isn't cached."""
    console, kinds = CONSOLES[system]
    name = kinds[kind]
    if not os.path.exists(tsv_path(name)):
        fetch_list(name)
    with open(tsv_path(name), encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
        rows = []
        for r in reader:
            link = (r.get("PKG direct link") or "").strip()
            if not link.startswith("http"):
                continue
            if console == "PSV" and len((r.get("zRIF") or "").strip()) < 20:
                continue
            rap = (r.get("RAP") or "").strip()
            if console == "PS3" and not (rap == "NOT REQUIRED" or re.fullmatch(r"[0-9A-Fa-f]{32}", rap)):
                continue
            if console == "PSP" and r.get("Type") in PSP_SKIP_TYPES:
                continue
            try:
                size = int(r.get("File Size") or 0)
            except ValueError:
                size = 0
            rows.append({
                "system": system, "console": console, "kind": kind,
                "id": r["Title ID"].strip(), "region": r["Region"].strip(), "name": r["Name"].strip(),
                "url": link, "content_id": (r.get("Content ID") or "").strip(), "size": size,
                "sha256": (r.get("SHA256") or "").strip().lower(), "rap": rap if console == "PS3" else "",
                "zrif": (r.get("zRIF") or "").strip(), "subtype": (r.get("Type") or "").strip(),
            })
    return rows


def list_age(system):
    """mtime of the oldest cached list for this system, or None if any is missing."""
    names = [n for n in CONSOLES[system][1].values() if n]
    times = [os.path.getmtime(tsv_path(n)) for n in names if os.path.exists(tsv_path(n))]
    return min(times) if len(times) == len(names) else None


def title_key(name):
    """Loose title for spotting the same game across NPS names and ROM file names:
    'Ape_Academy_2.cso' and 'Ape Academy 2 (MINIS)' both give 'ape academy 2'."""
    name = re.sub(r"\.(chd|cso|iso|pbp|desktop|psvita|zip|7z)$", "", name, flags=re.I)
    name = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", re.sub(r"^[a-z]?\d{3,4} - ", "", name, flags=re.I))
    name = re.sub(r"^(.*), (the|a|an)\b", r"\2 \1", name.replace("_", " "), flags=re.I)
    name = re.sub(r"[™®©]", "", name).lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", name).split())


# ---------- PS3 updates ----------
def read_sfo(path):
    """PARAM.SFO -> {key: value}"""
    with open(path, "rb") as f:
        d = f.read()
    if d[:4] != b"\0PSF":
        return {}
    keys_at, data_at, count = struct.unpack("<III", d[8:20])
    out = {}
    for i in range(count):
        koff, fmt, length, _, doff = struct.unpack("<HHIII", d[20 + i * 16:36 + i * 16])
        key = d[keys_at + koff:d.index(b"\0", keys_at + koff)].decode("ascii", "replace")
        raw = d[data_at + doff:data_at + doff + length]
        out[key] = struct.unpack("<I", raw[:4])[0] if fmt == 0x0404 else raw.split(b"\0")[0].decode("utf-8", "replace")
    return out


def ver(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def installed_version(roms_root, title_id):
    """APP_VER of an installed PS3 game (updates bump it), or None."""
    try:
        sfo = read_sfo(os.path.join(rpcs3_hdd0(roms_root), "game", title_id, "PARAM.SFO"))
    except OSError:
        return None
    return sfo.get("APP_VER") or sfo.get("VERSION")


def load_updates(roms_root, progress=lambda m: None):
    """Ask Sony's update server about every PS3 game RPCS3 knows (installed or disc) -> update rows, oldest first."""
    ctx = ssl._create_unverified_context()  # Sony signs this host with its own CA
    rows = []
    ids = sorted(owned_ids("ps3", roms_root))
    for n, tid in enumerate(ids, 1):
        progress(f"Checking updates {n} / {len(ids)}: {tid}")
        req = urllib.request.Request(PS3_UPDATE_URL.format(tid), headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                root = ET.fromstring(r.read())
        except Exception:
            continue  # 404 / empty body = no updates
        for pkg in root.iter("package"):
            url = pkg.get("url") or ""
            if not url.startswith("http"):
                continue
            cid = re.search(r"/([A-Z]{2}\d{4}-[A-Z]{4}\d{5}_\d\d-[A-Z0-9]{16})", url)
            title = re.sub(r"\s+v?\d+\.\d+$", "", (pkg.findtext("paramsfo/TITLE") or tid).strip())
            rows.append({
                "system": "ps3", "console": "PS3", "kind": "Updates", "id": tid,
                "region": CID_REGIONS.get(cid.group(1)[:2], "") if cid else "",
                "name": f"{title}  ·  update {pkg.get('version')}", "url": url,
                "content_id": f"{cid.group(1) if cid else tid}-{pkg.get('version')}",
                "size": int(pkg.get("size") or 0), "sha256": "", "sha1": (pkg.get("sha1sum") or "").lower(),
                "rap": "NOT REQUIRED", "zrif": "", "subtype": "", "version": pkg.get("version") or "0",
            })
    return rows


# ---------- what's there ----------
def owned_ids(system, roms_root):
    """Title ids the emulator already has: PS3 installed games + disc games RPCS3 registered; Vita installed apps."""
    ids = set()
    if system == "ps3":
        game = os.path.join(rpcs3_hdd0(roms_root), "game")
        try:
            ids |= {d for d in os.listdir(game) if re.fullmatch(r"[A-Z]{4}\d{5}", d)
                    and os.path.exists(os.path.join(game, d, "PARAM.SFO"))}
        except OSError:
            pass
        try:
            with open(os.path.join(FLATPAK_CONFIG, "rpcs3", "games.yml"), encoding="utf-8") as f:
                ids |= set(re.findall(r"^([A-Z]{4}\d{5}):", f.read(), re.M))
        except OSError:
            pass
    elif system == "psvita":
        try:
            ids |= set(os.listdir(os.path.join(vita3k_pref(roms_root), "ux0", "app")))
        except OSError:
            pass
    return ids


def firmware_problem(system, roms_root):
    """A short warning if the emulator's firmware is missing, else None."""
    if system == "ps3":
        flash = rpcs3_vfs("/dev_flash/") or os.path.join(retrodeck_root(roms_root), "storage", "rpcs3", "dev_flash")
        if not os.path.exists(os.path.join(flash, "vsh", "module", "vsh.self")):
            return ("RPCS3 has no PS3 firmware installed, so games won't boot. Get PS3UPDAT.PUP from "
                    "playstation.com and install it in RPCS3 (File → Install Firmware).")
    elif system == "psvita":
        ext = os.path.join(vita3k_pref(roms_root), "vs0", "sys", "external")
        if not (os.path.isdir(ext) and os.listdir(ext)):
            return ("Vita3K has no PS Vita firmware installed, so games won't boot. Get PSVUPDAT.PUP (and the "
                    "font package PSP2UPDAT.PUP) from playstation.com and install them in Vita3K.")
    return None


# ---------- install state ----------
STATE = os.path.join(CACHE, "state.json")
_state = None


def state():
    """{"incomplete": [PS3 game dirs being written], "dlc": [content ids installed]}, cached in memory."""
    global _state
    if _state is None:
        try:
            with open(STATE, encoding="utf-8") as f:
                _state = json.load(f)
        except (OSError, ValueError):
            _state = {}
        _state.setdefault("incomplete", [])
        _state.setdefault("dlc", [])
    return _state


def save_state():
    os.makedirs(CACHE, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state(), f, indent=1)
    os.replace(tmp, STATE)


# ---------- paths ----------
def retrodeck_root(roms_root):
    return os.path.dirname(os.path.realpath(roms_root).rstrip("/"))


def rpcs3_vfs(mount):
    """Host folder RPCS3 maps a device to (e.g. "/dev_hdd0/"), from its vfs.yml, or None."""
    try:
        with open(os.path.join(FLATPAK_CONFIG, "rpcs3", "vfs.yml"), encoding="utf-8") as f:
            vfs = dict(re.findall(r"^(\S+): (.*)$", f.read(), re.M))
    except OSError:
        return None
    emu = vfs.get("$(EmulatorDir)", "").strip('"')
    path = vfs.get(mount, "").strip('"').replace("$(EmulatorDir)", emu)
    return path.rstrip("/") or None


def rpcs3_hdd0(roms_root):
    """RPCS3's dev_hdd0 (RetroDECK points it into retrodeck/storage)."""
    return rpcs3_vfs("/dev_hdd0/") or os.path.join(retrodeck_root(roms_root), "storage", "rpcs3", "dev_hdd0")


def vita3k_pref(roms_root):
    try:
        with open(os.path.join(FLATPAK_CONFIG, "Vita3K", "config.yml"), encoding="utf-8") as f:
            m = re.search(r"^pref-path: (.+)$", f.read(), re.M)
        if m and m.group(1).strip():
            return m.group(1).strip().rstrip("/")
    except OSError:
        pass
    return os.path.join(retrodeck_root(roms_root), "storage", "psvita", "Vita3K")


def safe_name(s):
    s = s.replace(":", " -").replace("/", "-").replace("\\", "-")
    s = re.sub(r'[<>"|?*\x00-\x1f]', "", s)
    return re.sub(r"\s+", " ", s).strip(" .") or "game"


def rom_name(row):
    return f"{safe_name(row['name'])} ({REGIONS.get(row['region'], row['region'])})"


def is_installed(row, roms_root):
    if row["kind"] == "Updates":
        have = installed_version(roms_root, row["id"])
        return have is not None and ver(have) >= ver(row["version"])
    if row["console"] == "PS3" and row["kind"] == "DLC" and row["rap"] == "NOT REQUIRED":
        return row["content_id"] in state()["dlc"]  # nothing on disk says which DLC a game folder holds
    target = install_target(row, roms_root)
    if row["console"] == "PS3" and os.path.dirname(os.path.dirname(target)) in state()["incomplete"]:
        return False  # an install that was stopped or failed part way
    return os.path.exists(target)


def install_target(row, roms_root):
    """The file or folder whose existence means this row is installed."""
    if row["console"] == "PS3":
        if row["kind"] != "DLC":
            return os.path.join(rpcs3_hdd0(roms_root), "game", row["id"], "USRDIR", "EBOOT.BIN")
        return os.path.join(rpcs3_hdd0(roms_root), "home", "00000001", "exdata", row["content_id"] + ".rap") \
            if row["rap"] != "NOT REQUIRED" else os.path.join(rpcs3_hdd0(roms_root), "game", row["id"])
    if row["console"] == "PSV":
        ux0 = os.path.join(vita3k_pref(roms_root), "ux0")
        if row["kind"] == "DLC":  # addcont/<title id>/<entitlement label, the last part of the content id>
            return os.path.join(ux0, "addcont", row["id"], row["content_id"].rsplit("-", 1)[-1])
        return os.path.join(ux0, "app", row["id"])
    return os.path.join(roms_root, "psp", rom_name(row) + " (PSN).pbp")


def pkg_path(row, dl_dir):
    return os.path.join(dl_dir, row["console"], (row["content_id"] or row["id"]) + ".pkg")


# ---------- download ----------
def file_hash(path, algo, skip_tail=0):
    h, left = hashlib.new(algo), os.path.getsize(path) - skip_tail
    with open(path, "rb") as f:
        while left > 0 and (b := f.read(min(CHUNK, left))):
            h.update(b)
            left -= len(b)
    return h.hexdigest()


def download(row, dest, progress, cancelled):
    """Resumable download into dest (via dest.part), hash-checked when one is known. progress(done, total).
    NPS gives SHA256 of the whole file; Sony's update XML gives SHA1 of all but the 32-byte PKG footer."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        return True
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    headers = {"User-Agent": USER_AGENT}
    if have:
        headers["Range"] = f"bytes={have}-"
    try:
        r = urllib.request.urlopen(urllib.request.Request(row["url"], headers=headers), timeout=60)
    except urllib.error.HTTPError as e:
        if not (have and e.code == 416):  # 416 = the .part is already complete; go straight to the hash check
            raise
        r = None
    if r:
        with r:
            if have and r.status != 206:  # server ignored the range: start over
                have = 0
            total = have + int(r.headers.get("Content-Length") or 0)
            with open(part, "ab" if have else "wb") as f:
                done = have
                while b := r.read(1 << 20):
                    if cancelled():
                        return False
                    f.write(b)
                    done += len(b)
                    progress(done, total)
    algo, want, tail = ("sha1", row["sha1"], 32) if row.get("sha1") else ("sha256", row["sha256"], 0)
    if want and file_hash(part, algo, tail) != want:
        os.unlink(part)
        raise OSError(f"{algo.upper()} mismatch, download was corrupt (deleted, try again)")
    os.replace(part, dest)
    return True


# ---------- pkg ----------
class Pkg:
    """Retail PS3/PSP .pkg reader: AES-128-CTR, PS3 key for PS3 items, PSP key for PSP items (flags 0x90xxxxxx)."""

    def __init__(self, path):
        self.f = open(path, "rb")
        h = self.f.read(0x100)
        magic, rev, ptype, meta_off, meta_count, _, count, _, self.data_off, _ = struct.unpack(">IHHIIIIQQQ",
                                                                                            h[:0x30])
        if magic != 0x7F504B47:
            raise ValueError("not a PKG file")
        if rev != 0x8000:
            raise ValueError("debug PKGs aren't supported")
        self.content_id = h[0x30:0x54].rstrip(b"\0").decode("ascii", "replace")
        self.title_id = self.content_id[7:16]
        self.iv = int.from_bytes(h[0x70:0x80], "big")
        ext = h[0xC0:0xC4] == b"\x7fext"
        if ptype == 1:
            self.key = PS3_KEY
        elif ext and h[0xE7] & 7 == 1:
            self.key = PSP_KEY
        else:
            raise ValueError("PS Vita PKGs are installed through Vita3K")

        self.install_dir = None  # metadata packet 0xA, used by a few PS3 packages instead of the title id
        self.f.seek(meta_off)
        for _ in range(meta_count):
            pid, size = struct.unpack(">II", self.f.read(8))
            data = self.f.read(size)
            if pid == 0xA and size > 8:
                self.install_dir = data[8:].split(b"\0")[0].decode("ascii", "replace") or None

        table = self._read(self.key, 0, count * 32)
        self.items = []
        for i in range(count):
            name_off, name_size, off, size, flags = struct.unpack(">IIQQI", table[i * 32:i * 32 + 28])
            key = PSP_KEY if flags >> 24 == 0x90 else PS3_KEY
            name = self._read(key, name_off, name_size).split(b"\0")[0].decode("utf-8", "replace")
            self.items.append({"name": name, "off": off, "size": size, "flags": flags, "key": key,
                               "dir": flags & 0xFF in (0x04, 0x12)})

    def _cipher(self, key, off):
        return aes_ctr(key, ((self.iv + off // 16) % (1 << 128)).to_bytes(16, "big"))

    def _read(self, key, off, size):
        skip = off % 16
        self.f.seek(self.data_off + off - skip)
        return self._cipher(key, off).update(self.f.read(size + skip))[skip:]

    def extract(self, item, dest, progress=None, cancelled=lambda: False):
        """Decrypt one item to dest (via dest.part). progress(bytes) is called per chunk."""
        skip = item["off"] % 16
        dec = self._cipher(item["key"], item["off"])
        self.f.seek(self.data_off + item["off"] - skip)
        left, first = item["size"], True
        tmp = dest + ".part"
        with open(tmp, "wb") as out:
            while left > 0:
                if cancelled():
                    out.close()
                    os.unlink(tmp)
                    return False
                n = min(CHUNK, left + (skip if first else 0))
                b = dec.update(self.f.read(n))
                if first:
                    b, first = b[skip:], False
                b = b[:left]
                out.write(b)
                left -= len(b)
                if progress:
                    progress(len(b))
        os.replace(tmp, dest)
        return True

    def close(self):
        self.f.close()


class _OpenSSLCtr:
    """AES-128-CTR straight from the system's libcrypto, for machines without the cryptography module
    (SteamOS has OpenSSL but no pip)."""
    lib = None

    @classmethod
    def load(cls):
        if cls.lib is None:
            names = [ctypes.util.find_library("crypto"), "libcrypto.so.3", "libcrypto.so.1.1", "libcrypto.so"]
            for name in filter(None, names):
                try:
                    lib = ctypes.CDLL(name)
                    break
                except OSError:
                    continue
            else:
                raise RuntimeError("Installing PS3/PSP packages needs OpenSSL's libcrypto or the Python "
                                   "'cryptography' module (pip install cryptography); neither was found")
            lib.EVP_CIPHER_CTX_new.restype = ctypes.c_void_p
            lib.EVP_aes_128_ctr.restype = ctypes.c_void_p
            lib.EVP_DecryptInit_ex.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p,
                                               ctypes.c_char_p]
            lib.EVP_DecryptUpdate.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int),
                                              ctypes.c_char_p, ctypes.c_int]
            lib.EVP_CIPHER_CTX_free.argtypes = [ctypes.c_void_p]
            cls.lib = lib
        return cls.lib

    def __init__(self, key, iv):
        lib = self.load()
        self.ctx = lib.EVP_CIPHER_CTX_new()
        if not self.ctx or lib.EVP_DecryptInit_ex(self.ctx, lib.EVP_aes_128_ctr(), None, key, iv) != 1:
            raise RuntimeError("OpenSSL couldn't set up AES-128-CTR")

    def update(self, data):
        out, n = ctypes.create_string_buffer(len(data)), ctypes.c_int(0)
        if self.lib.EVP_DecryptUpdate(self.ctx, out, ctypes.byref(n), data, len(data)) != 1:
            raise RuntimeError("OpenSSL AES decrypt failed")
        return out.raw[:n.value]

    def __del__(self):
        if getattr(self, "ctx", None) and self.lib:
            self.lib.EVP_CIPHER_CTX_free(self.ctx)


def aes_ctr(key, iv):
    """AES-128-CTR decryptor with .update(): the cryptography module if installed, else system OpenSSL."""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        return _OpenSSLCtr(key, iv)
    return Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()


def _need_crypto():
    try:
        import cryptography  # noqa: F401
    except ImportError:
        _OpenSSLCtr.load()  # fail before downloading/installing anything, with a clear message


# ---------- install ----------
def install_ps3(row, pkg_file, roms_root, log, progress, cancelled):
    _need_crypto()
    hdd0 = rpcs3_hdd0(roms_root)
    pkg = Pkg(pkg_file)
    try:
        dest = os.path.join(hdd0, "game", pkg.install_dir or pkg.title_id)
        files = [i for i in pkg.items if not i["dir"]]
        total, done = sum(i["size"] for i in files), 0
        log(f"Installing into {dest}")
        if dest not in state()["incomplete"]:
            state()["incomplete"].append(dest)
            save_state()
        for item in pkg.items:
            if not item["name"].strip("/"):
                continue
            target = os.path.join(dest, *item["name"].split("/"))
            if not os.path.realpath(target).startswith(os.path.realpath(dest) + os.sep):
                raise ValueError(f"unsafe path in package: {item['name']}")
            if item["dir"]:
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.exists(target) and not item["flags"] & 0x80000000:
                done += item["size"]  # RPCS3 leaves these alone too (PARAM.SFO / ICON0.PNG of an installed game)
                continue

            def step(n):
                nonlocal done
                done += n
                progress(done, total)
            if not pkg.extract(item, target, step, cancelled):
                return False
    finally:
        pkg.close()
    state()["incomplete"].remove(dest)
    if row["kind"] == "DLC" and row["content_id"] not in state()["dlc"]:
        state()["dlc"].append(row["content_id"])
    save_state()

    if row["rap"] != "NOT REQUIRED":
        exdata = os.path.join(hdd0, "home", "00000001", "exdata")
        os.makedirs(exdata, exist_ok=True)
        with open(os.path.join(exdata, pkg.content_id + ".rap"), "wb") as f:
            f.write(bytes.fromhex(row["rap"]))
        log("License (.rap) installed")

    game_id = pkg.install_dir or pkg.title_id
    existing = ps3_shortcut(roms_root, game_id)
    if existing:
        row["entry"] = os.path.join(roms_root, "ps3", existing)
    elif row["kind"] in ("Games", "Demos"):
        shortcut = row["entry"] = os.path.join(roms_root, "ps3", rom_name(row) + ".desktop")
        os.makedirs(os.path.dirname(shortcut), exist_ok=True)
        with open(shortcut, "w", encoding="utf-8") as f:
            f.write("[Desktop Entry]\nEncoding=UTF-8\nVersion=1.0\nType=Application\nTerminal=false\n"
                    f'Exec="/app/retrodeck/components/rpcs3/component_launcher.sh" --no-gui '
                    f'"%%RPCS3_GAMEID%%:{game_id}"\n'
                    f"Name={row['name']}\nCategories=Application;Game\nComment={row['name']}\n"
                    f"Icon={os.path.join(hdd0, 'game', game_id, 'ICON0.PNG')}\n")
        os.chmod(shortcut, 0o700)
        log(f"Shortcut added: roms/ps3/{os.path.basename(shortcut)}")
    return True


def ps3_shortcut(roms_root, game_id):
    """An existing roms/ps3 .desktop that launches game_id (e.g. one RPCS3 or RetroDECK made), or None."""
    folder = os.path.join(roms_root, "ps3")
    try:
        names = [n for n in os.listdir(folder) if n.endswith(".desktop")]
    except OSError:
        return None
    for n in names:
        try:
            with open(os.path.join(folder, n), encoding="utf-8", errors="replace") as f:
                if f'%:{game_id}"' in f.read():
                    return n
        except OSError:
            pass
    return None


def linked_data(system, entry, roms_root):
    """Installed emulator data behind a roms entry that is only a launcher: a PS3 .desktop shortcut -> RPCS3's
    dev_hdd0/game/<id> plus its .rap licenses; a .psvita file -> Vita3K's app/addcont/patch/license/<id>.
    Saves are left out on purpose. -> list of existing paths ([] for ordinary ROMs)."""
    try:
        if system == "ps3" and entry.endswith(".desktop"):
            with open(entry, encoding="utf-8", errors="replace") as f:
                m = re.search(r'%:([A-Z]{4}\d{5})"', f.read())
            if not m:
                return []
            hdd0, gid = rpcs3_hdd0(roms_root), m.group(1)
            exdata = os.path.join(hdd0, "home", "00000001", "exdata")
            raps = [os.path.join(exdata, n) for n in os.listdir(exdata) if f"-{gid}_" in n] \
                if os.path.isdir(exdata) else []
            return [p for p in [os.path.join(hdd0, "game", gid)] if os.path.isdir(p)] + raps
        if system == "psvita" and entry.endswith(".psvita"):
            with open(entry, encoding="utf-8", errors="replace") as f:
                gid = f.read().strip()
            if not re.fullmatch(r"[A-Z]{4}\d{5}", gid):
                return []
            ux0 = os.path.join(vita3k_pref(roms_root), "ux0")
            return [p for p in (os.path.join(ux0, d, gid) for d in ("app", "addcont", "patch", "license"))
                    if os.path.isdir(p)]
    except OSError:
        pass
    return []


def install_psp(row, pkg_file, roms_root, log, progress, cancelled):
    _need_crypto()
    pkg = Pkg(pkg_file)
    try:
        eboot = next((i for i in pkg.items if i["name"].upper() == "USRDIR/CONTENT/EBOOT.PBP"), None)
        if not eboot:
            raise ValueError("no EBOOT.PBP in this package")
        dest = install_target(row, roms_root)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        done = 0

        def step(n):
            nonlocal done
            done += n
            progress(done, eboot["size"])
        if not pkg.extract(eboot, dest, step, cancelled):
            return False
    finally:
        pkg.close()
    row["entry"] = dest
    log(f"Added roms/psp/{os.path.basename(dest)}")
    return True


def vita3k_command(pkg_dir):
    if shutil.which("flatpak") and subprocess.run(["flatpak", "info", FLATPAK], capture_output=True).returncode == 0:
        # the sandbox can't see every host folder (e.g. /tmp), so grant the package's folder for this run
        return ["flatpak", "run", f"--filesystem={os.path.realpath(pkg_dir)}:ro", "--command=sh", FLATPAK, "-c",
                'cd /app/retrodeck/components/vita3k && exec bin/Vita3K "$@"', "sh"]
    exe = shutil.which("Vita3K") or shutil.which("vita3k")
    if exe:
        return [exe]
    raise RuntimeError("Vita3K not found (neither the RetroDECK flatpak nor Vita3K on PATH)")


def install_psv(row, pkg_file, roms_root, log, progress, cancelled):
    log("Installing with Vita3K …")
    progress(0, 0)
    r = subprocess.run(vita3k_command(os.path.dirname(pkg_file)) + ["-z", "--pkg", pkg_file, "--zrif", row["zrif"]],
                       capture_output=True, text=True, timeout=3600)
    target = install_target(row, roms_root)
    if not os.path.isdir(target):
        tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-5:])
        raise RuntimeError(f"Vita3K didn't install it (exit {r.returncode})\n{tail}")
    if row["kind"] != "DLC":
        entry = os.path.join(roms_root, "psvita", rom_name(row) + ".psvita")
        os.makedirs(os.path.dirname(entry), exist_ok=True)
        with open(entry, "w", encoding="utf-8") as f:
            f.write(row["id"])
        row["entry"] = entry
        log(f"Added roms/psvita/{os.path.basename(entry)}")
    return True


INSTALLERS = {"PS3": install_ps3, "PSP": install_psp, "PSV": install_psv}


def install(row, pkg_file, roms_root, log, progress, cancelled):
    return INSTALLERS[row["console"]](row, pkg_file, roms_root, log, progress, cancelled)
