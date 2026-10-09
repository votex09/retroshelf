"""Tiny disc images for the import tests: just enough of each format for RetroShelf to recognise it."""
import lzma, struct, zlib

SYNC = b"\x00" + b"\xff" * 10 + b"\x00"


def _both(fmt, v):
    return struct.pack("<" + fmt, v) + struct.pack(">" + fmt, v)


def _record(name, lba, size, is_dir=False):
    n = len(name)
    rec = bytearray(33 + n + (1 - n % 2))
    rec[0] = len(rec)
    rec[2:10] = _both("I", lba)
    rec[10:18] = _both("I", size)
    rec[25] = 2 if is_dir else 0
    rec[28:32] = _both("H", 1)
    rec[32] = n
    rec[33:33 + n] = name
    return bytes(rec)


def iso(files, system_id=b"PLAYSTATION", pad_sectors=0, head=b""):
    """An ISO 9660 image with these files in its root ({"SYSTEM.CNF": b"BOOT2 = ..."})."""
    lba = 19
    entries, blobs = [], []
    for name, data in files.items():
        entries.append(_record(name.encode() + (b"" if name.endswith("_GAME") else b";1"), lba, len(data),
                               name.endswith("_GAME")))
        blobs.append(data + bytes(-len(data) % 2048 or (2048 if not data else 0)))
        lba += max(1, -(-len(data) // 2048))
    root = _record(b"\x00", 18, 2048, True) + _record(b"\x01", 18, 2048, True) + b"".join(entries)
    total = lba + pad_sectors
    pvd = bytearray(2048)
    pvd[0], pvd[1:6], pvd[6] = 1, b"CD001", 1
    pvd[8:40] = system_id.ljust(32)
    pvd[80:88] = _both("I", total)
    pvd[128:132] = _both("H", 2048)
    pvd[156:190] = _record(b"\x00", 18, 2048, True)
    term = bytearray(2048)
    term[0], term[1:6], term[6] = 255, b"CD001", 1
    system_area = (head + bytes(16 * 2048))[:16 * 2048]
    return system_area + bytes(pvd) + bytes(term) + root.ljust(2048, b"\x00") + b"".join(blobs) + \
        bytes(pad_sectors * 2048)


def raw(image, mode=2):
    """2048-byte sectors -> raw 2352-byte ones (.bin), as a CD dump has them."""
    out = bytearray()
    for i in range(0, len(image), 2048):
        sector = SYNC + bytes([0, 2, 0, mode])
        if mode == 2:
            sector += bytes(8)
        out += sector + image[i:i + 2048].ljust(2048, b"\x00")
        out += bytes(2352 - len(sector) - 2048)
    return bytes(out)


def gamecube(wii=False):
    head = bytearray(0x440)
    head[0:6] = b"GALE01"
    if wii:
        head[0x18:0x1C] = b"\x5d\x1c\x9e\xa3"
    else:
        head[0x1C:0x20] = b"\xc2\x33\x9f\x3d"
    return bytes(head) + bytes(0x8000)


def cso(image, block=2048):
    blocks = [image[i:i + block] for i in range(0, len(image), block)]
    header = b"CISO" + struct.pack("<IQIBBxx", 0x18, len(image), block, 1, 0)
    pos = len(header) + 4 * (len(blocks) + 1)
    index, data = [], b""
    for b in blocks:
        index.append(pos + len(data))
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        data += c.compress(b) + c.flush()
    index.append(pos + len(data))
    return header + b"".join(struct.pack("<I", i) for i in index) + data


def ps2(name="SLUS_123.45"):
    return iso({"SYSTEM.CNF": f"BOOT2 = cdrom0:\\{name};1\r\nVER = 1.00\r\n".encode(), name: b"\x7fELF" + bytes(4000)})


def ps1(name="SCUS_942.00"):
    return iso({"SYSTEM.CNF": f"BOOT = cdrom:\\{name};1\r\nTCB = 4\r\n".encode(), name: b"PS-X EXE" + bytes(4000)})


def psp():
    return iso({"UMD_DATA.BIN": b"ULUS-10041|0001|G", "PSP_GAME": b""}, system_id=b"PSP GAME")


def saturn():
    return iso({"0.BIN": bytes(100)}, system_id=b"SEGA SEGASATURN", head=b"SEGA SEGASATURN SEGA TP T-81")


def _num(n):
    return bytes([n]) if n < 0x80 else b"\xff" + struct.pack("<Q", n)


def seven_zip(files):
    """A solid LZMA2 .7z of {name: bytes} (no empty files), written the way 7-Zip lays one out."""
    names, data = list(files), b"".join(files.values())
    packed = lzma.compress(data, format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA2, "dict_size": 1 << 20}])
    names_blob = b"\x00" + b"".join(n.encode("utf-16-le") + b"\x00\x00" for n in names)
    sizes = [len(files[n]) for n in names]
    h = b"\x01\x04"
    h += b"\x06" + _num(0) + _num(1) + b"\x09" + _num(len(packed)) + b"\x00"
    h += b"\x07\x0b" + _num(1) + b"\x00" + _num(1) + bytes([0x20 | 1]) + b"\x21" + _num(1) + bytes([16])  # LZMA2, 1 MB
    h += b"\x0c" + _num(len(data)) + b"\x00"
    h += b"\x08\x0d" + _num(len(names))
    if len(names) > 1:
        h += b"\x09" + b"".join(_num(s) for s in sizes[:-1])
    h += b"\x0a\x01" + b"".join(struct.pack("<I", zlib.crc32(files[n])) for n in names) + b"\x00"
    h += b"\x00"
    h += b"\x05" + _num(len(names)) + b"\x11" + _num(len(names_blob)) + names_blob + b"\x00"
    h += b"\x00"
    start = struct.pack("<QQI", len(packed), len(h), zlib.crc32(h))
    return b"7z\xbc\xaf\x27\x1c\x00\x04" + struct.pack("<I", zlib.crc32(start)) + start + packed + h
