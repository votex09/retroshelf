"""The homebrew stores without Tk: Homebrew Hub, itch.io, PDRoms and MAMEDEV as "source" objects, and what the
windows that browse them share (catalog_gui.py for the Tk app, app/helper/tool_stores.py for the Electron one).

A source lists a site's entries and says how to show them. Games the source may fetch itself install with one click;
the rest open in the user's browser, where they download them, and the Downloads watcher (lib/downloads.py) files
what lands there.

Optional source hooks: fill(e) -> dict of details fetched when a game is picked (for lists that only carry titles),
confirm(e) -> text the user must agree to before a one-click install, one_click_filter (default: one_click),
browser_downloads = False when the site's page is only for reading (no Downloads watching), license_header = None to
leave that column out."""
import os

import downloads
import homebrew as hb
import itch
import mamedev
import pdroms
import scraper

USER_AGENT = "RetroShelf/1.0 (+https://github.com/votex09/retroshelf)"  # for screenshots

class HomebrewSource:
    name = "Homebrew Hub"
    window_attr = "homebrew_window"
    heading = "Homebrew Hub  ·  free homebrew games"
    note = ("Open-source games install with one click. For the others, Open on Homebrew Hub shows the game's page in "
            "your browser: download it there and RetroShelf puts it in your ROMs folder as soon as it lands in your "
            "Downloads folder.")
    open_label = "Open on Homebrew Hub ↗"
    browse_label = None
    license_header = "License"
    one_click = True
    systems = [(p, f"{p} — {hb.PLATFORM_NAMES[p]}") for p in hb.PLATFORMS]
    kinds = hb.TYPES
    default_kind = "game"

    def default_code(self, system):
        return next((p for p, s in hb.PLATFORMS.items() if s == system), "GB")

    def system_for(self, code):
        return hb.PLATFORMS[code]

    def load(self, code, refresh):
        return hb.load_catalog(code, refresh)

    def cached_age(self, code):
        return hb.cached_age(code)

    def load_error(self, err, code):
        return f"Couldn't load the list: {err}"

    def key(self, e):
        return e["slug"]

    def title(self, e):
        return hb.entry_title(e)

    def developer(self, e):
        return hb.developer_text(e.get("developer"))

    def kind(self, e):
        return e.get("typetag") or "game"

    def license(self, e):
        return hb.license_text(e)

    def year(self, e):
        return str(e.get("date") or "")[:4]

    def description(self, e):
        return (e.get("description") or "").strip()

    def hidden(self, e):
        return bool(e.get("nsfw"))

    def screenshot_url(self, e):
        return hb.screenshot_url(e)

    def page_url(self, e):
        return hb.page_url(e)

    def can_download(self, e):
        return hb.can_download(e)

    def installed_path(self, e, roms_root):
        return hb.installed_path(e, roms_root)

    def details(self, e):
        """The search list may leave out files; fetch the full manifest when it does."""
        return e if e.get("files") else dict(e, **hb.load_entry(e["slug"]))

    def install(self, e, roms_root, progress=lambda done, total: None):
        return hb.install(self.details(e), roms_root, progress)

    def want(self, e):
        try:
            e = self.details(e)  # so the watcher knows the file name Homebrew Hub will serve
        except Exception:
            pass
        return hb.want(e)

    def es_de_fields(self, e):
        return hb.es_de_fields(e)


class ItchSource:
    name = "itch.io"
    window_attr = "itch_window"
    heading = "itch.io  ·  free homebrew games"
    note = ("Games download from itch.io in your browser, where their authors can ask for an optional donation: pick a "
            "game and Open on itch.io, or Browse on itch.io to look around. Every ROM for this system that lands in "
            "your Downloads folder is put in your ROMs folder.")
    open_label = "Open on itch.io ↗"
    browse_label = "Browse on itch.io ↗"
    license_header = "Price"
    one_click = False
    systems = [(s, label) for s, label, _ in itch.SYSTEMS]
    kinds = None
    default_kind = "all"

    def default_code(self, system):
        return system if system in itch.LABELS else "gb"

    def system_for(self, code):
        return code

    def load(self, code, refresh):
        return itch.load_catalog(code, refresh)

    def cached_age(self, code):
        return itch.cached_age(code)

    def load_error(self, err, code):
        if isinstance(err, itch.Blocked):
            return (f"{err}. Browse on itch.io still works: every {itch.LABELS[code]} ROM you download there is put "
                    f"in roms/{code}.")
        return f"Couldn't load the list: {err}. Browse on itch.io still works."

    def key(self, g):
        return g["url"]

    def title(self, g):
        return g["title"]

    def developer(self, g):
        return g.get("author") or ""

    def kind(self, g):
        return ""

    def license(self, g):
        return "Free"  # only free games are listed

    def year(self, g):
        return g.get("year") or ""

    def description(self, g):
        return g.get("description") or ""

    def hidden(self, g):
        return False

    def screenshot_url(self, g):
        return g.get("image") or None

    def page_url(self, g):
        return g["url"]

    def can_download(self, g):
        return False

    def installed_path(self, g, roms_root):
        return itch.installed_path(g, roms_root)

    def install(self, g, roms_root, progress=None):
        raise PermissionError("itch.io games download in your browser")

    def want(self, g):
        return itch.want(g)

    def browse_url(self, code):
        return itch.browse_url(code)

    def browse_want(self, code):
        return itch.browse_want(code)

    def es_de_fields(self, g):
        return itch.es_de_fields(g)


class PdromsSource:
    name = "PDRoms"
    window_attr = "pdroms_window"
    heading = "PDRoms  ·  homebrew since 1998"
    note = ("Free and legally cleared homebrew, downloaded from PDRoms in your browser: pick a game and Open on "
            "PDRoms, or Browse on PDRoms to look around. Every ROM for this system that lands in your Downloads "
            "folder is put in your ROMs folder. Fan games PDRoms marks as copyright-restricted aren't listed.")
    open_label = "Open on PDRoms ↗"
    browse_label = "Browse on PDRoms ↗"
    license_header = "Added"
    one_click = False
    systems = [(s, label) for s, label, _ in pdroms.SYSTEMS]
    kinds = None
    default_kind = "all"

    def default_code(self, system):
        return system if system in pdroms.LABELS else "gb"

    def system_for(self, code):
        return code

    def load(self, code, refresh):
        return pdroms.load_catalog(code, refresh)

    def cached_age(self, code):
        return pdroms.cached_age(code)

    def load_error(self, err, code):
        return f"Couldn't load the list: {err}. Browse on PDRoms still works."

    def key(self, g):
        return g["url"]

    def title(self, g):
        return g["title"]

    def developer(self, g):
        return g.get("author") or ""

    def kind(self, g):
        return ""

    def license(self, g):
        return g.get("added") or ""  # the year PDRoms listed it

    def year(self, g):
        return ""

    def description(self, g):
        return g.get("description") or ""

    def hidden(self, g):
        return False

    def fill(self, g):
        return pdroms.load_details(g)  # the list has titles only: author, text and screenshot are on its page

    def screenshot_url(self, g):
        return g.get("image") or g.get("thumb") or None

    def page_url(self, g):
        return g["url"]

    def can_download(self, g):
        return False

    def installed_path(self, g, roms_root):
        return pdroms.installed_path(g, roms_root)

    def install(self, g, roms_root, progress=None):
        raise PermissionError("PDRoms games download in your browser")

    def want(self, g):
        return pdroms.want(g)

    def browse_url(self, code):
        return pdroms.browse_url(code)

    def browse_want(self, code):
        return pdroms.browse_want(code)

    def es_de_fields(self, g):
        return pdroms.es_de_fields(g)


class MamedevSource:
    name = "MAMEDEV free ROMs"
    window_attr = "mamedev_window"
    heading = "MAMEDEV  ·  arcade games released for free"
    note = ("Classic arcade games whose owners let the MAME team give them away for free, non-commercial use. They "
            "download from mamedev.org into roms/mame under the file names MAME needs, after you confirm you'll only "
            "use them non-commercially.")
    open_label = "Open on mamedev.org ↗"
    browse_label = None
    license_header = None  # all the same: free for non-commercial use (shown with each game)
    one_click = True
    one_click_filter = False  # every game here installs with one click
    browser_downloads = False  # the page is for reading: MAME needs the set's own file name, which Install keeps
    systems = [(mamedev.SYSTEM, "Arcade (MAME)")]
    kinds = None
    default_kind = "all"

    def default_code(self, system):
        return mamedev.SYSTEM

    def system_for(self, code):
        return mamedev.SYSTEM

    def load(self, code, refresh):
        return mamedev.load_catalog(refresh)

    def cached_age(self, code):
        return mamedev.cached_age()

    def load_error(self, err, code):
        return f"Couldn't load the list: {err}"

    def key(self, g):
        return g["id"]

    def title(self, g):
        return g["title"]

    def developer(self, g):
        return g.get("company") or ""

    def kind(self, g):
        return ""

    def license(self, g):
        return "Non-commercial"

    def year(self, g):
        return g.get("year") or ""

    def description(self, g):
        return "\n\n".join(t for t in (g.get("notice"), g.get("description")) if t)

    def hidden(self, g):
        return False

    def screenshot_url(self, g):
        return g.get("image") or g.get("thumb") or None

    def page_url(self, g):
        return g["page"]

    def can_download(self, g):
        return bool(g.get("zips"))

    def installed_path(self, g, roms_root):
        return mamedev.installed_path(g, roms_root)

    def confirm(self, g):
        return (f"{g.get('notice') or g['title'] + ' is free for non-commercial use only.'}\n\n"
                f"{mamedev.ACKNOWLEDGE}\n\nIt will be saved as roms/{mamedev.SYSTEM}/{mamedev.rom_name(g)}.")

    def install(self, g, roms_root, progress=None):
        return mamedev.install(g, roms_root)

    def want(self, g):
        return mamedev.want(g)

    def es_de_fields(self, g):
        return mamedev.es_de_fields(g)


SOURCES = {"homebrew": HomebrewSource, "itch": ItchSource, "pdroms": PdromsSource, "mamedev": MamedevSource}


# ---------- what both windows show ----------
def short_path(path):
    """The last two folders, so a long path can't crowd the window."""
    parts = os.path.normpath(path).split(os.sep)
    return path if len(parts) <= 3 else os.sep.join(["…"] + parts[-2:])


def downloads_folder(cfg):
    """Where the user's browser saves downloads (picked in the window, else the usual Downloads folder)."""
    return cfg.get("homebrew_downloads") or downloads.downloads_dir()


def one_click_filter(src):
    return getattr(src, "one_click_filter", src.one_click)


def age_text(age):
    return "" if age is None else "list from today" if age < 1 else f"list from {int(age)} day{'s' if age >= 2 else ''} ago"


def status_of(src, e, roms_root, waiting=()):
    if any(w["id"] == src.key(e) for w in waiting):
        return "Waiting"
    if src.installed_path(e, roms_root):
        return "Installed"
    return "" if src.can_download(e) or not src.one_click else "via website"


def shown(src, entries, roms_root, query="", kind="all", one_click=False, hide_have=False):
    """The entries the filters let through, sorted by title."""
    q = query.lower().strip()
    out = []
    for e in entries:
        if src.kinds and kind != "all" and src.kind(e) != kind:
            continue
        if q and q not in src.title(e).lower() and q not in src.developer(e).lower():
            continue
        if one_click and not src.can_download(e):
            continue
        if hide_have and src.installed_path(e, roms_root):
            continue
        if src.hidden(e):
            continue
        out.append(e)
    out.sort(key=lambda e: src.title(e).lower())
    return out


def results_text(src, shown_entries):
    text = f"{len(shown_entries):,} shown"
    if one_click_filter(src):
        text += f"  ·  {sum(src.can_download(e) for e in shown_entries):,} one-click installs"
    return text


def can_install(src, e, roms_root):
    return bool(src.one_click and e and src.can_download(e) and not src.installed_path(e, roms_root))


def website_only_note(src, e):
    """Under the description of a game that has to come from the site's page, else ""."""
    if src.one_click and not src.can_download(e):
        return (f"The author hasn't allowed apps to download this one: use {src.open_label.rstrip(' ↗')} and download "
                f"it from the game's page.")
    return ""


def watches_downloads(src):
    return getattr(src, "browser_downloads", True)


def waiting_text(waiting, folder):
    if not waiting:
        return ""
    names = ", ".join(x["title"] for x in waiting[:3]) + (f" +{len(waiting) - 3}" if len(waiting) > 3 else "")
    return f"Waiting for {names} to land in {short_path(folder)}"


def add_metadata(src, e, rom, system, roms_root):
    """The site's description, developer and screenshot for ES-DE, where nothing is there yet. -> a note for the
    status line."""
    if scraper.es_de_running():
        return " (close ES-DE and rescrape to add its description)"
    name = os.path.basename(rom)
    try:
        scraper.write_gamelist(scraper.gamelist_path(roms_root, system), {name: src.es_de_fields(e)}, lambda m: None)
        url = src.screenshot_url(e)
        folder = os.path.join(scraper.media_root(roms_root), system, "screenshots")
        stem = os.path.splitext(name)[0]
        ext = os.path.splitext(url.split("?")[0])[1].lower() if url else ""
        if url and not scraper.has_media(folder, stem):
            os.makedirs(folder, exist_ok=True)
            scraper.download(url, os.path.join(folder, stem + (ext if len(ext) <= 5 and ext else ".png")))
        return " with its description and screenshot"
    except Exception as ex:
        return f" (metadata not added: {ex})"
