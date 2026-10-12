"""Web sources: a web server's folder listing used like a folder source (lib/sources.py). Most home servers show
folders this way: nginx, Apache, Caddy and lighttpd's autoindex pages, `python -m http.server`, a NAS's web share.
The listing pages are read for their links (a link ending in / is a folder), games are grouped the way the importer
groups files on disk, and a game's files are downloaded to a temporary folder before being imported from there.

Only the http and https addresses under the source's own address are ever fetched. A user name and password, when
the server asks, go with every request (HTTP Basic or Digest)."""
import base64, os, re, shutil, urllib.error, urllib.parse, urllib.request
from html.parser import HTMLParser

import romimport

TIMEOUT = 30
MAX_PAGES = 20000  # folder pages read in one look through a source
MAX_DEPTH = 12
SHEET_EXTS = (".cue", ".gdi", ".m3u")


def is_url(path):
    return isinstance(path, str) and path.strip().lower().startswith(("http://", "https://"))


def normalize(url):
    """A source's address as it's saved: http(s) only, no #fragment or ?query, ending in /."""
    url = url.strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("A web source needs an address starting with http:// or https://")
    if parts.username or parts.password:
        raise ValueError("Put the user name and password in their own boxes, not in the address")
    path = parts.path or "/"
    if not path.endswith("/"):
        path += "/"
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def label(url):
    """What the source is called in the window: its last folder and the server."""
    parts = urllib.parse.urlsplit(url)
    tail = urllib.parse.unquote(parts.path.rstrip("/").rsplit("/", 1)[-1])
    return f"{tail}  ({parts.hostname})" if tail else parts.hostname or url


class Site:
    """Reading one source's pages and files (with its login, if it has one)."""

    def __init__(self, base, user="", password=""):
        self.base = normalize(base)
        handlers = []
        if user:
            mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
            mgr.add_password(None, self.base, user, password or "")
            handlers += [urllib.request.HTTPBasicAuthHandler(mgr), urllib.request.HTTPDigestAuthHandler(mgr)]
            # (sent with the first request too: some servers answer 404 rather than ask)
            self.basic = "Basic " + base64.b64encode(f"{user}:{password or ''}".encode()).decode()
        else:
            self.basic = None
        self.opener = urllib.request.build_opener(*handlers)

    def url(self, rel):
        """The address of a file or folder ('/'-separated, relative to the source)."""
        return self.base + "/".join(urllib.parse.quote(p) for p in rel.split("/") if p)

    def open(self, url):
        if not url.startswith(self.base):
            raise ValueError(f"{url} isn't under {self.base}")
        req = urllib.request.Request(url, headers={"User-Agent": "RetroShelf"})
        if self.basic:
            req.add_header("Authorization", self.basic)
        try:
            return self.opener.open(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise PermissionError("The server wants a user name and password, or the ones given aren't right "
                                      f"({e.code})") from None
            if e.code == 404:
                raise FileNotFoundError(f"The server says {urllib.parse.unquote(url)} isn't there") from None
            raise OSError(f"The server answered {e.code} {e.reason} for {urllib.parse.unquote(url)}") from None
        except urllib.error.URLError as e:
            raise OSError(f"Can't reach {urllib.parse.urlsplit(url).netloc}: {e.reason}") from None

    def text(self, rel, limit=1 << 20):
        with self.open(self.url(rel)) as r:
            return r.read(limit).decode("utf-8", "replace")

    def listing(self, rel=""):
        """A folder page's entries -> [(name, is_folder, size or 0)]."""
        url = self.url(rel)
        if not url.endswith("/"):
            url += "/"
        with self.open(url) as r:
            ctype = r.headers.get("Content-Type", "")
            if "html" not in ctype.lower() and ctype:
                raise ValueError(f"{urllib.parse.unquote(url)} isn't a folder listing (it's {ctype.split(';')[0]})")
            page = r.read(32 << 20).decode(r.headers.get_content_charset() or "utf-8", "replace")
            url = r.geturl()  # (after any redirect)
        return parse_listing(page, url)


class _Links(HTMLParser):
    """Each <a href> with the text and data-* numbers that follow it (not its own text), up to the next link."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []  # [href, text after it, numbers from data-* attributes after it]
        self.in_a = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.in_a = True
            if attrs.get("href") is not None:
                self.links.append([attrs["href"], "", []])
        elif self.links:
            self.links[-1][1] += " "  # (table cells run together otherwise)
            for k in ("data-size", "data-order", "data-value"):
                v = attrs.get(k)
                if v and v.isdigit():
                    self.links[-1][2].append(int(v))

    def handle_endtag(self, tag):
        if tag == "a":
            self.in_a = False

    def handle_data(self, data):
        if self.links and not self.in_a:
            self.links[-1][1] += data


_UNITS = {"": 1, "b": 1, "k": 1 << 10, "m": 1 << 20, "g": 1 << 30, "t": 1 << 40}
_SIZE_RE = re.compile(r"^(\d+(?:\.\d+)?)([kmgt]?)(?:i?b|bytes)?$", re.I)


def _size(text, numbers):
    """A listing row's size: a data-size attribute (Caddy), else the last word when it reads like one (nginx's
    bytes, Apache's 1.2M, lighttpd's 1.2K). 0 when it doesn't show one."""
    if numbers:
        return numbers[0]
    words = text.split()
    if words and words[-1] in ("B", "KiB", "MiB", "GiB", "TiB", "KB", "MB", "GB", "TB", "bytes") and len(words) > 1:
        words = words[:-2] + [words[-2] + words[-1]]
    m = _SIZE_RE.match(words[-1]) if words else None
    if not m or ":" in words[-1]:
        return 0
    return int(float(m.group(1)) * _UNITS[m.group(2).lower()])


def parse_listing(page, url):
    """The entries of a folder page at url -> [(name, is_folder, size)]: links to its own files and folders only
    (sorting links, the parent folder and links elsewhere are left out)."""
    p = _Links()
    p.feed(page)
    here = urllib.parse.urlsplit(url)._replace(query="", fragment="").geturl()
    if not here.endswith("/"):
        here = here.rsplit("/", 1)[0] + "/"
    out, seen = [], set()
    for href, text, numbers in p.links:
        if href.startswith(("?", "#", "javascript:", "mailto:")):
            continue
        target = urllib.parse.urlsplit(urllib.parse.urljoin(here, href))._replace(query="", fragment="").geturl()
        if not target.startswith(here) or target == here:
            continue
        rest = target[len(here):]
        folder = rest.endswith("/")
        rest = rest.rstrip("/")
        if not rest or "/" in rest:
            continue
        name = urllib.parse.unquote(rest)
        if name in (".", "..") or "/" in name or "\\" in name or name in seen:
            continue
        seen.add(name)
        out.append((name, folder, 0 if folder else _size(text, numbers)))
    return out


def walk(site, progress=lambda message: None, cancelled=lambda: False):
    """Every folder of the source -> {folder rel ('' for the top): [(name, size)] of its files}."""
    files, todo, pages = {}, [("", 0)], 0
    while todo:
        if cancelled():
            raise InterruptedError
        rel, depth = todo.pop(0)
        pages += 1
        if pages > MAX_PAGES:
            raise ValueError(f"The source has more than {MAX_PAGES:,} folders; add one of its folders instead")
        progress(f"Reading {urllib.parse.unquote(site.url(rel))} …")
        try:
            entries = site.listing(rel)
        except (FileNotFoundError, ValueError):
            if not rel:
                raise
            continue  # a folder that won't list: skipped
        for name, folder, size in entries:
            if name.startswith(".") or name == romimport.STAGING:
                continue
            if folder:
                if depth < MAX_DEPTH:
                    todo.append((f"{rel}{name}/", depth + 1))
            else:
                files.setdefault(rel, []).append((name, size))
    return files


def _split_first(name):
    """For a split archive's later part (x.7z.002, x.part2.rar): its first part's name; else None."""
    low = name.lower()
    m = romimport.SPLIT_RE.search(low)
    if m and m.group(2) != "001":
        return name[:m.start(2)] + "001"
    r = romimport.RAR_PART_RE.search(low)
    if r and int(r.group(1)) != 1:
        return f"{name[:r.start(1)]}{1:0{len(r.group(1))}d}.rar"
    return None


def games(site, folders, quick_system):
    """Group each folder's files into games like the importer does on disk -> [{key, name, system, how, size,
    files}]: key is the game's main file (or first archive part) and files every file it needs, relative to the
    source. quick_system(rel) -> (system, how)."""
    out = []
    for rel, entries in folders.items():
        sizes = {n: s for n, s in entries}
        parts, loose = {}, []
        for n, _ in entries:
            if romimport._skip_name(n):
                continue
            first = _split_first(n)
            if first:
                parts.setdefault(first, []).append(n)
            elif romimport.is_archive(n):
                parts.setdefault(n, [])
            elif romimport.ext_of(n) in romimport.ROM_EXTS:
                loose.append(n)
        for first, more in parts.items():
            if first not in sizes:
                continue  # (later parts without their first)
            names = [first] + sorted(more)
            out.append(_game(rel, first, names, sizes, quick_system))
        if loose:
            def read(n, rel=rel):
                if romimport.ext_of(n) not in SHEET_EXTS:
                    return ""
                try:
                    return site.text(rel + n)
                except OSError:
                    return ""
            units, _ = romimport.group(sorted(loose), read)
            for u in units:
                out.append(_game(rel, u.main, list(u.files), sizes, quick_system))
    return out


def _game(rel, main, names, sizes, quick_system):
    system, how = quick_system(rel + main)
    return {"key": rel + main, "name": os.path.splitext(main.rsplit("/", 1)[-1])[0], "system": system, "how": how,
            "size": sum(sizes.get(n, 0) for n in names), "files": [rel + n for n in names]}


def download(site, files, dest, report=lambda text=None, fraction=None: None, cancelled=lambda: False, total=0):
    """Fetch a game's files into dest (made fresh), keeping their names -> the local path of the first one."""
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    got, local = 0, []
    for rel in files:
        name = rel.rsplit("/", 1)[-1]
        if not name or name in (".", "..") or "\\" in name:
            raise ValueError(f"Won't download {rel!r}")
        path = os.path.join(dest, name)
        with site.open(site.url(rel)) as r, open(path, "wb") as f:
            total = total or int(r.headers.get("Content-Length") or 0) * len(files)
            while True:
                if cancelled():
                    raise InterruptedError
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                report(f"Downloading {name} … {_human(got)}" + (f" of {_human(total)}" if total else ""),
                       min(got / total, 1) * 0.8 if total else None)
        local.append(path)
    return local[0]


def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
