"""itch.io window: free homebrew for retro consoles from itch.io, downloaded in your browser and filed by RetroShelf
(see lib/itch.py; the site itself is catalog.ItchSource)."""
import catalog
import catalog_gui


def open_window(app):
    return catalog_gui.open_window(app, catalog.ItchSource())
