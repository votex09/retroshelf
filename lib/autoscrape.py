"""Scraping games right after Import (or a copy from a source) filed them: LaunchBox text and artwork for the new
games, matched by name like ☰ → Scrape metadata does. Images already there are kept, and so is gamelist text unless
it's missing (scraper.scrape never overwrites here)."""
import os, re

import launchbox as lb
import library
import nps
import scraper

GAME_FILES = (".m3u", ".cue", ".gdi")  # what ES-DE lists for a game made of several files


def main_file(paths):
    """The file ES-DE lists for a game imported as these paths (a .cue over its tracks …)."""
    for ext in GAME_FILES:
        for p in paths:
            if p.lower().endswith(ext):
                return p
    return paths[0]


def regions(name):
    return tuple(r.strip() for tag in re.findall(r"\(([^)]*)\)", name) for r in tag.split(","))


def scrape_new(placed, roms_root, overrides, progress=lambda message: None, cancelled=lambda: False):
    """placed: [[paths of one imported game]]. -> a line saying what was scraped, or "" when nothing could be."""
    if not placed or not lb.has_details():
        return ""
    by_system = {}
    for paths in placed:
        if paths:
            main = main_file(paths)
            by_system.setdefault(os.path.basename(os.path.dirname(main)), []).append(main)
    do_text = not scraper.es_de_running()
    done = images = 0
    for system, files in sorted(by_system.items()):
        if cancelled():
            break
        name, fullname, _ = library.read_systeminfo(os.path.join(roms_root, system))
        fullname = fullname if name == system else nps.FULL_NAMES.get(system)
        platform = lb.resolve_platform(system, fullname, overrides)
        if not platform:
            continue
        matcher = lb.Matcher(platform)
        jobs = []
        for f in files:
            stem = os.path.splitext(os.path.basename(f))[0]
            gid, _, _ = matcher.match(re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", stem).strip())
            if gid:
                jobs.append((f, gid, regions(stem)))
        matcher.save()
        if not jobs:
            continue
        media = [k for k, (_, _, default) in scraper.MEDIA.items() if default]
        s = scraper.scrape(jobs, platform, system, roms_root, scraper.gamelist_path(roms_root, system), do_text, media,
                           lambda m, d, t: progress(f"Scraping: {m}"), cancelled)
        done, images = done + len(jobs), images + s["images"]
    total = sum(len(f) for f in by_system.values())
    return f"Scraped {done} of {total} with LaunchBox ({images} images)" if done else ""
