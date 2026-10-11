"""MAMEDEV window: arcade games their owners released for free, non-commercial use, installed with one click into
roms/mame (see lib/mamedev.py; the site itself is catalog.MamedevSource)."""
import catalog
import catalog_gui


def open_window(app):
    return catalog_gui.open_window(app, catalog.MamedevSource())
