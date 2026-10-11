"""PDRoms window: homebrew for old consoles and handhelds from pdroms.de, downloaded in your browser and filed by
RetroShelf (see lib/pdroms.py; the site itself is catalog.PdromsSource)."""
import catalog
import catalog_gui


def open_window(app):
    return catalog_gui.open_window(app, catalog.PdromsSource())
