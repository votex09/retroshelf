"""itch.io window: free homebrew for retro consoles from itch.io, downloaded in your browser and filed by RetroShelf
(see lib/itch.py)."""
import catalog_gui
import itch


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

    def install(self, g, roms_root):
        raise PermissionError("itch.io games download in your browser")

    def want(self, g):
        return itch.want(g)

    def browse_url(self, code):
        return itch.browse_url(code)

    def browse_want(self, code):
        return itch.browse_want(code)

    def es_de_fields(self, g):
        return itch.es_de_fields(g)


def open_window(app):
    return catalog_gui.open_window(app, ItchSource())
