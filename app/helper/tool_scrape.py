"""Tools → Scrape metadata: fill ES-DE's gamelist text and download artwork from LaunchBox for the open system."""
import launchbox as lb
import scraper
from rpc import ctx, method, progress, stopped, working_on


@method
def scrape_info():
    """What the scrape window needs: whether it can run, the image types, and which games LaunchBox matched."""
    sc = ctx["need_system"]()
    return {"platform": sc.platform, "has_details": lb.has_details(), "es_de_running": scraper.es_de_running(),
            "media": [{"type": t, "label": label, "default": default} for t, (label, _, default) in scraper.MEDIA.items()],
            "linked": sorted(sc.lb_links), "close": sorted(k for k in sc.lb_ids if k not in sc.lb_links)}


@method
def scrape(job, keys, text=True, media=(), close=False, overwrite=False):
    """Scrape these games (exact matches, or close ones too). Progress comes as "progress" events for job."""
    sc = ctx["need_system"]()
    if text and scraper.es_de_running():
        raise RuntimeError("ES-DE is running and would overwrite gamelist.xml when it quits. Close it, or untick "
                           "Text to only download images.")
    links = sc.lb_ids if close else sc.lb_links
    jobs = [(scraper.primary_file(sc.units[k]["paths"]), links[k], sc.regions[k]) for k in keys if k in links]
    report, stop = progress(job), stopped(job)
    with working_on(job, sc.system, f"Scraping {ctx['current']['fullname'] or sc.system}"):
        stats = scraper.scrape(jobs, sc.platform, sc.system, sc.roms_root,
                               scraper.gamelist_path(sc.roms_root, sc.system), text, list(media),
                               lambda m, d, t: report(m, d, t), stop, overwrite)
    return {**stats, "unmatched": len(keys) - len(jobs), "stopped": stop()}
