"""Homebrew Hub window: browse free Game Boy / GBC / GBA / NES homebrew and put it in your ROMs folder.

Open-source games install with one click. For the rest, Open on Homebrew Hub shows the game's page in your browser;
download it there and RetroShelf files it from your Downloads folder (see lib/homebrew.py for why)."""
import catalog_gui
import homebrew as hb


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

    def install(self, e, roms_root):
        return hb.install(self.details(e), roms_root)

    def want(self, e):
        try:
            e = self.details(e)  # so the watcher knows the file name Homebrew Hub will serve
        except Exception:
            pass
        return hb.want(e)

    def es_de_fields(self, e):
        return hb.es_de_fields(e)


def open_window(app):
    return catalog_gui.open_window(app, HomebrewSource())
