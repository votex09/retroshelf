"""Homebrew Hub window: browse free Game Boy / GBC / GBA / NES homebrew and put it in your ROMs folder.

Open-source games install with one click. For the rest, Open on Homebrew Hub shows the game's page in your browser;
download it there and RetroShelf files it from your Downloads folder (see lib/homebrew.py for why). The site itself is
catalog.HomebrewSource."""
import catalog
import catalog_gui


def open_window(app):
    return catalog_gui.open_window(app, catalog.HomebrewSource())
