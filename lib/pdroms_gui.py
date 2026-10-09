"""PDRoms window: homebrew for old consoles and handhelds from pdroms.de, downloaded in your browser and filed by
RetroShelf (see lib/pdroms.py)."""
import catalog_gui
import pdroms


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

    def install(self, g, roms_root):
        raise PermissionError("PDRoms games download in your browser")

    def want(self, g):
        return pdroms.want(g)

    def browse_url(self, code):
        return pdroms.browse_url(code)

    def browse_want(self, code):
        return pdroms.browse_want(code)

    def es_de_fields(self, g):
        return pdroms.es_de_fields(g)


def open_window(app):
    return catalog_gui.open_window(app, PdromsSource())
