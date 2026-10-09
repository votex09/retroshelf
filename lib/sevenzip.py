"""Reading .7z archives with nothing but Python's own lzma, zlib and bz2 modules, so unpacking games needs no 7-Zip.

It covers what 7z archives of games use in practice: LZMA and LZMA2 (with the BCJ / ARM / PPC / SPARC / IA64 and
Delta filters), Deflate, BZip2 and stored files, solid or not, with packed ("encoded") headers. Anything else
(BCJ2, PPMd, encryption, ...) raises Unsupported, and the caller can hand the archive to a real 7-Zip instead.

The format, briefly: a 32-byte start header points at the archive's header at the end of the file. That header
lists "folders" (one compressed stream each, decoded by a chain of coders) and the files, which are cut out of the
folders' output one after another, in order.
"""
import bz2, io, lzma, os, struct, zlib

SIGNATURE = b"7z\xbc\xaf\x27\x1c"
CHUNK = 1 << 20

(K_END, K_HEADER, K_ARCHIVE_PROPS, K_ADDITIONAL_STREAMS, K_MAIN_STREAMS, K_FILES, K_PACK_INFO, K_UNPACK_INFO,
 K_SUBSTREAMS, K_SIZE, K_CRC, K_FOLDER, K_UNPACK_SIZE, K_NUM_UNPACK, K_EMPTY_STREAM, K_EMPTY_FILE, K_ANTI,
 K_NAME) = range(18)
K_ENCODED_HEADER = 0x17
K_DUMMY = 0x19

COPY, LZMA, LZMA2, DELTA = b"\x00", b"\x03\x01\x01", b"\x21", b"\x03"
DEFLATE, BZIP2 = b"\x04\x01\x08", b"\x04\x02\x02"
AES = b"\x06\xf1\x07\x01"
BRANCH_FILTERS = {b"\x03\x03\x01\x03": lzma.FILTER_X86, b"\x03\x03\x02\x05": lzma.FILTER_POWERPC,
                  b"\x03\x03\x04\x01": lzma.FILTER_IA64, b"\x03\x03\x05\x01": lzma.FILTER_ARM,
                  b"\x03\x03\x07\x01": lzma.FILTER_ARMTHUMB, b"\x03\x03\x08\x05": lzma.FILTER_SPARC}
METHOD_NAMES = {b"\x03\x03\x01\x1b": "BCJ2", b"\x03\x04\x01": "PPMd", b"\x04\x01\x09": "Deflate64", AES: "AES"}


class Unsupported(ValueError):
    """The archive uses something this reader can't decode (a real 7-Zip can)."""


class Encrypted(Unsupported):
    pass


def is_7z(path):
    try:
        with open(path, "rb") as f:
            return f.read(6) == SIGNATURE
    except OSError:
        return False


# ---------- reading the header ----------
class _Buf:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def byte(self):
        if self.pos >= len(self.data):
            raise ValueError("the 7z header is cut short")
        self.pos += 1
        return self.data[self.pos - 1]

    def read(self, n):
        if self.pos + n > len(self.data):
            raise ValueError("the 7z header is cut short")
        self.pos += n
        return self.data[self.pos - n:self.pos]

    def u32(self):
        return struct.unpack("<I", self.read(4))[0]

    def number(self):
        """7z's variable-length number: the leading 1 bits of the first byte say how many bytes follow."""
        first, mask, value = self.byte(), 0x80, 0
        for i in range(8):
            if not first & mask:
                return value | ((first & (mask - 1)) << (8 * i))
            value |= self.byte() << (8 * i)
            mask >>= 1
        return value

    def bits(self, n):
        out, byte, mask = [], 0, 0
        for _ in range(n):
            if not mask:
                byte, mask = self.byte(), 0x80
            out.append(bool(byte & mask))
            mask >>= 1
        return out

    def defined(self, n):
        """An "all defined" byte, else a bit per item."""
        return [True] * n if self.byte() else self.bits(n)


class Folder:
    def __init__(self):
        self.coders = []      # [{"id", "props", "ins", "outs"}]
        self.binds = []       # [(in index, out index)]
        self.packed = []      # in-stream indexes fed by the archive's packed streams, in order
        self.unpack_sizes = []
        self.crc = None
        self.pack_start = 0   # first packed stream (index into the archive's list)

    def size(self):
        """The folder's decoded size: the out-stream nothing else consumes."""
        bound = {o for _, o in self.binds}
        return next(s for i, s in enumerate(self.unpack_sizes) if i not in bound)


class Entry:
    def __init__(self, name):
        self.name, self.size, self.is_dir, self.crc = name, 0, False, None
        self.folder, self.offset = None, 0  # where its bytes are in the folder's output

    def __repr__(self):
        return f"Entry({self.name!r}, {self.size})"


def _read_digests(b, n):
    defined = b.defined(n)
    return [b.u32() if d else None for d in defined]


def _read_pack_info(b, info):
    info["pack_pos"] = b.number()
    n = b.number()
    info["pack_sizes"] = [0] * n
    while True:
        t = b.number()
        if t == K_END:
            return
        if t == K_SIZE:
            info["pack_sizes"] = [b.number() for _ in range(n)]
        elif t == K_CRC:
            _read_digests(b, n)
        else:
            raise ValueError(f"unexpected 7z header field {t}")


def _read_folder(b):
    f = Folder()
    n_in = n_out = 0
    for _ in range(b.number()):
        flags = b.byte()
        if flags & 0x80:
            raise Unsupported("7z alternative coders")
        cid = b.read(flags & 0x0F)
        ins, outs = (b.number(), b.number()) if flags & 0x10 else (1, 1)
        props = b.read(b.number()) if flags & 0x20 else b""
        f.coders.append({"id": cid, "props": props, "ins": ins, "outs": outs})
        n_in += ins
        n_out += outs
    f.binds = [(b.number(), b.number()) for _ in range(n_out - 1)]
    n_packed = n_in - len(f.binds)
    if n_packed == 1:
        bound_ins = {i for i, _ in f.binds}
        f.packed = [next(i for i in range(n_in) if i not in bound_ins)]
    else:
        f.packed = [b.number() for _ in range(n_packed)]
    return f


def _read_unpack_info(b, info):
    if b.number() != K_FOLDER:
        raise ValueError("bad 7z header")
    folders = info["folders"] = []
    n = b.number()
    if b.byte():
        raise Unsupported("7z external folder data")
    for _ in range(n):
        folders.append(_read_folder(b))
    if b.number() != K_UNPACK_SIZE:
        raise ValueError("bad 7z header")
    for f in folders:
        f.unpack_sizes = [b.number() for _ in range(sum(c["outs"] for c in f.coders))]
    while True:
        t = b.number()
        if t == K_END:
            return
        if t == K_CRC:
            for f, crc in zip(folders, _read_digests(b, n)):
                f.crc = crc
        else:
            raise ValueError(f"unexpected 7z header field {t}")


def _read_substreams(b, info):
    folders = info["folders"]
    counts = [1] * len(folders)
    t = b.number()
    if t == K_NUM_UNPACK:
        counts = [b.number() for _ in folders]
        t = b.number()
    sizes = []  # per folder: its files' sizes
    for f, c in zip(folders, counts):
        part = []
        if c:
            if t == K_SIZE:
                part = [b.number() for _ in range(c - 1)]
            part.append(f.size() - sum(part))
        sizes.append(part)
    if t == K_SIZE:
        t = b.number()
    crcs = [[None] * len(s) for s in sizes]
    known = set()  # folders holding one file, whose CRC is the folder's own
    for i, (f, c) in enumerate(zip(folders, counts)):
        if c == 1 and f.crc is not None:
            crcs[i][0] = f.crc
            known.add(i)
    while t != K_END:
        if t == K_CRC:
            n = sum(len(s) for i, s in enumerate(sizes) if i not in known)
            digests = iter(_read_digests(b, n))
            for i, s in enumerate(sizes):
                if i not in known:
                    crcs[i] = [next(digests) for _ in s]
        else:
            b.read(b.number())
        t = b.number()
    info["counts"], info["sizes"], info["crcs"] = counts, sizes, crcs


def _read_streams_info(b):
    info = {"pack_pos": 0, "pack_sizes": [], "folders": []}
    while True:
        t = b.number()
        if t == K_END:
            break
        if t == K_PACK_INFO:
            _read_pack_info(b, info)
        elif t == K_UNPACK_INFO:
            _read_unpack_info(b, info)
        elif t == K_SUBSTREAMS:
            _read_substreams(b, info)
        else:
            raise ValueError(f"unexpected 7z header field {t}")
    if "counts" not in info:  # no substream info: one file per folder
        info["counts"] = [1] * len(info["folders"])
        info["sizes"] = [[f.size()] for f in info["folders"]]
        info["crcs"] = [[f.crc] for f in info["folders"]]
    start = 0
    for f in info["folders"]:
        f.pack_start = start
        start += len(f.packed)
    return info


def _read_files(b, n):
    names, empty_stream, empty_file, anti = [""] * n, [False] * n, None, None
    while True:
        t = b.number()
        if t == K_END:
            break
        size = b.number()
        prop = _Buf(b.read(size))
        if t == K_NAME:
            if prop.byte():
                raise Unsupported("7z external file names")
            raw = prop.data[prop.pos:].decode("utf-16-le", "replace")
            names = raw.split("\x00")[:n]
        elif t == K_EMPTY_STREAM:
            empty_stream = prop.bits(n)
        elif t == K_EMPTY_FILE:
            empty_file = prop.bits(sum(empty_stream))
        elif t == K_ANTI:
            anti = prop.bits(sum(empty_stream))
        # times, attributes, padding (K_DUMMY) and the rest aren't needed
    entries, k = [], 0
    for i in range(n):
        e = Entry(names[i].replace("\\", "/") if i < len(names) else f"file{i}")
        if empty_stream[i]:
            is_file = empty_file[k] if empty_file else False
            if anti and anti[k]:
                k += 1
                continue
            e.is_dir = not is_file
            k += 1
        e.has_stream = not empty_stream[i]
        entries.append(e)
    return entries


# ---------- decoding ----------
def _lzma_filter(coder):
    cid, props = coder["id"], coder["props"]
    if cid == LZMA:
        if len(props) < 5:
            raise ValueError("bad LZMA properties")
        d = props[0]
        lc, d = d % 9, d // 9
        lp, pb = d % 5, d // 5
        return {"id": lzma.FILTER_LZMA1, "dict_size": max(struct.unpack("<I", props[1:5])[0], 4096),
                "lc": lc, "lp": lp, "pb": pb}
    if cid == LZMA2:
        p = props[0] & 0x3F if props else 0
        size = 0xFFFFFFFF if p >= 40 else (2 | (p & 1)) << (p // 2 + 11)
        return {"id": lzma.FILTER_LZMA2, "dict_size": min(size, 1536 << 20)}
    if cid == DELTA:
        return {"id": lzma.FILTER_DELTA, "dist": (props[0] + 1) if props else 1}
    if cid in BRANCH_FILTERS:
        return {"id": BRANCH_FILTERS[cid]}
    return None


class _Copy:
    eof, needs_input = False, True

    def decompress(self, data, max_length=-1):
        return data


class _Inflate:
    def __init__(self):
        self.z = zlib.decompressobj(-15)
        self.needs_input, self.eof = True, False

    def decompress(self, data, max_length=-1):
        out = self.z.decompress(self.z.unconsumed_tail + data, max(max_length, 0))
        self.needs_input = not self.z.unconsumed_tail
        self.eof = self.z.eof
        return out


class _Bunzip:
    """BZip2, allowing several streams one after another (7-Zip's multi-threaded encoder writes those)."""

    def __init__(self):
        self.d = bz2.BZ2Decompressor()
        self.needs_input, self.eof = True, False

    def decompress(self, data, max_length=-1):
        if self.d.eof:
            rest = self.d.unused_data + data
            if not rest:
                return b""
            self.d = bz2.BZ2Decompressor()
            data = rest
        out = self.d.decompress(data, max_length)
        self.needs_input = self.d.needs_input and not self.d.eof
        if self.d.eof and self.d.unused_data:
            self.needs_input = False
        return out


def _chain(folder):
    """The folder's coders from its output back to its packed input (the order lzma lists filters in)."""
    if len(folder.packed) != 1:
        raise Unsupported("7z method " + "+".join(METHOD_NAMES.get(c["id"], c["id"].hex()) for c in folder.coders))
    for c in folder.coders:
        if c["id"] == AES:
            raise Encrypted("the archive is password-protected")
        if c["ins"] != 1 or c["outs"] != 1:
            raise Unsupported("7z method " + METHOD_NAMES.get(c["id"], c["id"].hex()))
    bound_outs = {o for _, o in folder.binds}
    feeds = {i: o for i, o in folder.binds}  # in-stream -> the out-stream feeding it (1 in / 1 out: = coder index)
    k = next(i for i in range(len(folder.coders)) if i not in bound_outs)
    chain = [folder.coders[k]]
    while k in feeds:
        k = feeds[k]
        chain.append(folder.coders[k])
    return chain


def _stage(dec, src):
    """Run chunks from src through a decompressor, yielding its output."""
    for data in src:
        out = dec.decompress(data, CHUNK)
        if out:
            yield out
        while not dec.eof and not dec.needs_input:
            out = dec.decompress(b"", CHUNK)
            if not out:
                break
            yield out
        if dec.eof:
            return


def _filter_stage(filters, src):
    """Apply branch / delta filters on their own: lzma only runs them in front of LZMA2, so the data goes through
    as LZMA2 "stored" chunks, ended properly so the filters hand over their last bytes."""
    dec = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=filters + [{"id": lzma.FILTER_LZMA2, "dict_size": 1 << 16}])

    def framed():
        control = 1  # the first chunk resets the dictionary
        for data in src:
            for i in range(0, len(data), 1 << 16):
                piece = data[i:i + (1 << 16)]
                yield bytes([control]) + struct.pack(">H", len(piece) - 1) + piece
                control = 2
        yield b"\x00"
    return _stage(dec, framed())


def _pipeline(folder, src):
    """The folder's decoded bytes from its packed bytes (src: chunks)."""
    chain = _chain(folder)
    ids = [c["id"] for c in chain]
    *filters, last = chain
    names = "+".join(METHOD_NAMES.get(i, i.hex()) for i in ids)
    pre = [_lzma_filter(c) for c in filters]
    if None in pre or any(f["id"] in (lzma.FILTER_LZMA1, lzma.FILTER_LZMA2) for f in pre):
        raise Unsupported("7z method " + names)
    if last["id"] == LZMA2:  # the usual case: lzma does it all in one go
        return _stage(lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=pre + [_lzma_filter(last)]), src)
    if last["id"] == LZMA:
        dec = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[_lzma_filter(last)])
    elif last["id"] == COPY:
        dec = _Copy()
    elif last["id"] == DEFLATE:
        dec = _Inflate()
    elif last["id"] == BZIP2:
        dec = _Bunzip()
    else:
        raise Unsupported("7z method " + names)
    out = _stage(dec, src)
    return _filter_stage(pre, out) if pre else out


class SevenZip:
    """A .7z archive: .entries lists what's in it; extract_all() unpacks it; open(entry) streams one file."""

    def __init__(self, path_or_file):
        self.f = open(path_or_file, "rb") if isinstance(path_or_file, (str, os.PathLike)) else path_or_file
        self._own = isinstance(path_or_file, (str, os.PathLike))
        try:
            self._read()
        except BaseException:
            self.close()
            raise

    def close(self):
        if self._own:
            self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _read(self):
        f = self.f
        f.seek(0)
        start = f.read(32)
        if len(start) < 32 or start[:6] != SIGNATURE:
            raise ValueError("not a 7z archive")
        if zlib.crc32(start[12:32]) != struct.unpack("<I", start[8:12])[0]:
            raise ValueError("the 7z archive is damaged (start header)")
        offset, size, crc = struct.unpack("<QQI", start[12:32])
        if size == 0:
            self.folders, self.entries, self.pack_offsets = [], [], []
            return
        f.seek(32 + offset)
        data = f.read(size)
        if len(data) < size:
            raise ValueError("the 7z archive is cut short (is it still downloading, or a split part?)")
        if zlib.crc32(data) != crc:
            raise ValueError("the 7z archive is damaged (header)")
        b = _Buf(data)
        t = b.number()
        while t == K_ENCODED_HEADER:  # the header itself is packed: unpack it and start over
            info = _read_streams_info(b)
            self._layout(info)
            data = b"".join(self._chunks(info["folders"][0]))
            b = _Buf(data)
            t = b.number()
        if t != K_HEADER:
            raise ValueError("bad 7z header")
        info, entries = {"folders": [], "pack_pos": 0, "pack_sizes": [], "counts": [], "sizes": [], "crcs": []}, []
        while True:
            t = b.number()
            if t == K_END:
                break
            if t == K_ARCHIVE_PROPS:
                while b.number():
                    b.read(b.number())
            elif t == K_ADDITIONAL_STREAMS:
                _read_streams_info(b)
            elif t == K_MAIN_STREAMS:
                info = _read_streams_info(b)
            elif t == K_FILES:
                entries = _read_files(b, b.number())
            else:
                raise ValueError(f"unexpected 7z header field {t}")
        self._layout(info)
        self.folders = info["folders"]
        # hand out the folders' substreams to the files that have data, in order
        streams = iter([(fi, size, crc) for fi, (sizes, crcs) in enumerate(zip(info["sizes"], info["crcs"]))
                        for size, crc in zip(sizes, crcs)])
        offsets = {}
        for e in entries:
            if not getattr(e, "has_stream", False):
                continue
            fi, size, crc = next(streams)
            e.folder, e.size, e.crc = fi, size, crc
            e.offset = offsets.get(fi, 0)
            offsets[fi] = e.offset + size
        self.entries = entries

    def _layout(self, info):
        pos = 32 + info["pack_pos"]
        self.pack_offsets = []
        for s in info["pack_sizes"]:
            self.pack_offsets.append((pos, s))
            pos += s

    def _packed(self, folder, cancelled):
        pos, left = self.pack_offsets[folder.pack_start]
        while left > 0:
            if cancelled():
                raise InterruptedError("cancelled")
            self.f.seek(pos)
            data = self.f.read(min(CHUNK, left))
            if not data:
                return
            pos += len(data)
            left -= len(data)
            yield data

    def _chunks(self, folder, cancelled=lambda: False):
        """The folder's decoded bytes, in chunks."""
        want = folder.size()
        for out in _pipeline(folder, self._packed(folder, cancelled)):
            out = out[:want]
            want -= len(out)
            if out:
                yield out
            if want <= 0:
                return
        if want > 0:
            raise ValueError("the 7z archive is cut short or damaged")

    def files(self):
        return [e for e in self.entries if not e.is_dir]

    def total_size(self):
        return sum(e.size for e in self.entries)

    def open(self, entry, cancelled=lambda: False):
        """A read-only, forward-seekable stream of one file (seeking back starts decoding over)."""
        return _EntryStream(self, entry, cancelled)

    def extract_all(self, dest, progress=lambda done, total: None, cancelled=lambda: False, wanted=None):
        """Unpack everything into dest (names that would land outside it are refused). -> [paths written].
        wanted(entry) -> False skips a file; blocks holding only skipped files aren't decoded at all (so a readme
        or .exe packed with a method this reader lacks doesn't stop the games from unpacking)."""
        root = os.path.realpath(dest)
        targets = {}
        for e in self.entries:
            if not (e.is_dir or wanted is None or wanted(e)):
                continue
            target = os.path.realpath(os.path.join(root, *[p for p in e.name.split("/") if p not in ("", ".")]))
            if target == root or not target.startswith(root + os.sep):
                raise ValueError(f"unsafe path in the archive: {e.name}")
            targets[id(e)] = target
        need = {e.folder for e in self.entries if id(e) in targets and e.folder is not None}
        written, done = [], 0
        total = sum(f.size() for i, f in enumerate(self.folders) if i in need)
        for e in self.entries:
            if id(e) not in targets:
                continue
            if e.is_dir:
                os.makedirs(targets[id(e)], exist_ok=True)
            elif e.folder is None:
                os.makedirs(os.path.dirname(targets[id(e)]), exist_ok=True)
                open(targets[id(e)], "wb").close()
                written.append(targets[id(e)])
        for fi, folder in enumerate(self.folders):
            if fi not in need:
                continue
            queue_ = sorted((e for e in self.entries if e.folder == fi), key=lambda e: e.offset)
            state = {"out": None, "crc": 0, "left": 0, "cur": None}

            def advance():
                """Finish the current file (if done) and open the next ones until one has bytes to come."""
                while state["cur"] is None or state["left"] == 0:
                    cur = state["cur"]
                    if cur is not None:
                        if state["out"]:
                            state["out"].close()
                            state["out"] = None
                            if cur.crc is not None and state["crc"] != cur.crc:
                                raise ValueError(f"{cur.name} is damaged in the archive (CRC mismatch)")
                            written.append(targets[id(cur)])
                    if not queue_:
                        state["cur"] = None
                        return
                    cur = state["cur"] = queue_.pop(0)
                    state["crc"], state["left"] = 0, cur.size
                    if id(cur) in targets:
                        os.makedirs(os.path.dirname(targets[id(cur)]), exist_ok=True)
                        state["out"] = open(targets[id(cur)], "wb")

            try:
                advance()
                for chunk in self._chunks(folder, cancelled):
                    view = memoryview(chunk)
                    while view and state["cur"] is not None:
                        part = view[:state["left"]]
                        if state["out"]:
                            state["out"].write(part)
                            state["crc"] = zlib.crc32(part, state["crc"])
                        state["left"] -= len(part)
                        view = view[len(part):]
                        done += len(part)
                        advance()
                    progress(done, total)
                    if state["cur"] is None:
                        break
            finally:
                if state["out"]:
                    state["out"].close()
        return written


class _EntryStream(io.RawIOBase):
    def __init__(self, archive, entry, cancelled):
        self.archive, self.entry, self.cancelled = archive, entry, cancelled
        self._restart()

    def _restart(self):
        self.pos, self.buf = 0, b""
        self.gen = (self.archive._chunks(self.archive.folders[self.entry.folder], self.cancelled)
                    if self.entry.folder is not None else iter(()))
        self._skip(self.entry.offset)
        self.left = self.entry.size

    def _skip(self, n):
        while n > 0:
            if not self.buf:
                self.buf = next(self.gen, b"")
                if not self.buf:
                    return
            take = min(n, len(self.buf))
            self.buf = self.buf[take:]
            n -= take

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        target = offset if whence == 0 else self.pos + offset if whence == 1 else self.entry.size + offset
        target = max(0, min(target, self.entry.size))
        if target < self.pos:
            self._restart()
        self._skip(target - self.pos)
        self.left -= target - self.pos
        self.pos = target
        return self.pos

    def read(self, n=-1):
        n = self.left if n is None or n < 0 else min(n, self.left)
        parts = []
        while n > 0:
            if not self.buf:
                self.buf = next(self.gen, b"")
                if not self.buf:
                    break
            take = self.buf[:n]
            self.buf = self.buf[len(take):]
            parts.append(take)
            n -= len(take)
            self.pos += len(take)
            self.left -= len(take)
        return b"".join(parts)

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)
