"""MAMEDEV window: arcade games their owners released for free, non-commercial use, installed with one click into
roms/mame (see lib/mamedev.py)."""
import catalog_gui
import mamedev


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

    def install(self, g, roms_root):
        return mamedev.install(g, roms_root)

    def want(self, g):
        return mamedev.want(g)

    def es_de_fields(self, g):
        return mamedev.es_de_fields(g)


def open_window(app):
    return catalog_gui.open_window(app, MamedevSource())
