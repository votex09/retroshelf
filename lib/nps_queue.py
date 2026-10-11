"""The NoPayStation window's work without Tk, shared by nps_gui.py (the Tk app) and app/helper/tool_stores.py (the
Electron app): what the library already has, each row's status, the lists filtered and sorted, the queue, and the
worker that downloads, installs and scrapes. The packages themselves are lib/nps.py's."""
import os, re, threading

import launchbox as lb
import nps
import scraper

REGION_CHOICES = ["All regions"] + list(nps.REGIONS)
PARALLEL_DOWNLOADS = 2
OWNED = ("Installed", "Have as ROM", "Have (other region)")
REGION_TAG = re.compile(r"\((?:[^)]*\b)?(?:USA|Europe|Japan|World|Asia|Korea|Australia)\b")
INSTALL_NOTES = {
    "PS3": "Packages are decrypted straight into RPCS3's dev_hdd0/game, the license (.rap) goes to exdata, "
           "and games get a shortcut in roms/ps3 so ES-DE lists them (ES-DE's default RPCS3 Shortcut "
           "emulator launches it). Updates come from Sony's update "
           "server for the games RPCS3 already has.",
    "PSV": "Packages are installed by Vita3K (license included), and games get a .psvita entry in "
           "roms/psvita. Updates aren't offered: NPS has no license for them and Vita3K needs one.",
    "PSP": "The game's EBOOT.PBP is pulled out of the package into roms/psp; PPSSPP plays it directly. "
           "PC Engine / NeoGeo titles are hidden since PPSSPP can't run them.",
}


def human(n):
    return f"{n / 1073741824:.2f} GB" if n >= 1073741824 else f"{n / 1048576:.1f} MB"


def row_name(r):
    return r["name"] + (f"  ·  {r['subtype']}" if r["subtype"] and r["subtype"] != "PSP" else "")


def default_dir(cfg):
    """Where packages are downloaded."""
    return cfg.get("nps_dir") or os.path.expanduser("~/Downloads/NPS")


# ---------- what's here ----------
class Library:
    """What's already here: title ids the emulator has, and loose titles of the ROMs in this system's folder.
    units: the system's games as a scan has them ({key: {"extra": [installed data] …}})."""

    def __init__(self, system, roms_root, units):
        self.system, self.roms_root = system, roms_root
        self.owned_ids = nps.owned_ids(system, roms_root)
        self.rom_titles = {}  # title key -> [ROM key]
        # shortcut / .psvita entries are a specific installed title id (shown as Installed), never another region
        self.launchers = {k for k, u in units.items() if u.get("extra")}
        for key in units:
            self.rom_titles.setdefault(nps.title_key(key), []).append(key)

    def have(self, row):
        """ROM keys in this system's folder that look like the same game (ordinary ROMs, e.g. a CHD of a PSN
        title)."""
        if row["kind"] not in ("Games", "Demos"):
            return []
        return self.rom_titles.get(nps.title_key(row["name"]), [])

    def status(self, row):
        """Installed, Have as ROM, Have (other region) or ""."""
        if nps.is_installed(row, self.roms_root):
            return "Installed"
        have = self.have(row)
        if have:
            region = nps.REGIONS.get(row["region"], row["region"])
            # untagged files (Ape_Quest.cso) count as a match; installed launchers never do (other title id)
            tagged = [k for k in have if REGION_TAG.search(k) or k in self.launchers]
            return "Have as ROM" if len(tagged) < len(have) or any(
                k not in self.launchers and (f"({region}" in k or f", {region}" in k) for k in tagged) \
                else "Have (other region)"
        return ""


def shown_rows(rows, kind, owned_ids, status, region="All regions", query="", mine=False, hide_have=False,
               sort_by=("name", False)):
    """The rows the filters let through, sorted -> (rows, {id(row): status}). status(row) -> its status text."""
    words = query.lower().split()
    mine = mine or kind == "Updates"
    shown = [r for r in rows
             if (region not in nps.REGIONS or r["region"] == region or kind == "Updates")
             and (not mine or r["id"] in owned_ids)
             and all(w in f"{r['name']} {r['id']}".lower() for w in words)]
    st = {id(r): status(r) for r in shown}
    if hide_have:
        shown = [r for r in shown if st[id(r)] not in OWNED]
    col, desc = sort_by
    if kind == "Updates" and col == "name":  # keep each game's updates in install order
        shown.sort(key=lambda r: (r["name"].split("  ·  ")[0].lower(), nps.ver(r["version"])), reverse=desc)
    else:
        shown.sort(key=lambda r: r[col] if col != "name" else r["name"].lower(), reverse=desc)
    return shown, st


# ---------- the queue ----------
def with_older_updates(picked, update_rows, roms_root):
    """PS3 updates usually aren't cumulative: the picked ones plus every older one the game is still missing, in
    order."""
    ids = {r["id"] for r in picked}
    newest = {i: max(nps.ver(r["version"]) for r in picked if r["id"] == i) for i in ids}
    return sorted((r for r in update_rows if r["id"] in ids
                   and nps.ver(r["version"]) <= newest[r["id"]] and not nps.is_installed(r, roms_root)),
                  key=lambda r: (r["id"], nps.ver(r["version"])))


def space_needed(pending):
    return sum(r["size"] for r in pending) + max(r["size"] for r in pending)  # packages + one extraction


def scrape_plan(wanted, platform, gamelist):
    """What run_queue needs to scrape new games afterwards, or None when it won't."""
    if wanted and platform and lb.has_details():
        return (platform, gamelist, not scraper.es_de_running())
    return None


def summary(states, stopped, scraped=None):
    """The status line after a run. states: every queued row's status text."""
    done = sum(s == "Done" for s in states)
    failed = sum(s.startswith("Failed") for s in states)
    return (("Stopped. " if stopped else "") + f"{done} installed, {failed} failed" +
            ("  ·  partial downloads resume next time" if stopped else "") + (f"  ·  {scraped}" if scraped else ""))


def run_queue(pending, dl_dir, roms_root, keep, scrape, say, cancelled):
    """Download and install the pending rows. Downloads run PARALLEL_DOWNLOADS at a time; installs run one by one in
    queue order (updates need it). Tells the window how it goes with say(message):
        ("job", row, status)  ("prog", row, "Downloading" / "Installing", done, total)  ("log", text)
        ("installed",)  ("scraped", text)  ("end",)
    scrape: scrape_plan(), for new games afterwards."""
    ready = [threading.Event() for _ in pending]
    ok = [False] * len(pending)
    todo, lock = iter(range(len(pending))), threading.Lock()

    def downloader():
        while not cancelled():
            with lock:
                i = next(todo, None)
            if i is None:
                return
            row = pending[i]
            say(("job", row, "Downloading"))
            try:
                ok[i] = nps.download(row, nps.pkg_path(row, dl_dir),
                                     lambda d, t: say(("prog", row, "Downloading", d, t)), cancelled)
                say(("job", row, "Downloaded, waiting to install" if ok[i] else "Queued"))
            except Exception as e:
                say(("job", row, f"Failed: {str(e).splitlines()[0]}"))
                say(("log", f"{row['name']}: {e}"))
            ready[i].set()

    threads = [threading.Thread(target=downloader, daemon=True) for _ in range(PARALLEL_DOWNLOADS)]
    for t in threads:
        t.start()
    new_entries = []
    for i, row in enumerate(pending):
        while not ready[i].wait(0.2):
            if not any(t.is_alive() for t in threads):
                break
        if not ok[i]:
            continue
        if cancelled():  # downloaded but not installed yet: the .pkg stays, Start picks it up again
            say(("job", row, "Queued"))
            continue
        pkg = nps.pkg_path(row, dl_dir)
        say(("job", row, "Installing"))
        try:
            if not nps.install(row, pkg, roms_root, lambda m: say(("log", m)),
                               lambda d, t: say(("prog", row, "Installing", d, t)), cancelled):
                say(("job", row, "Queued"))
                continue
            if not keep:
                os.unlink(pkg)
            say(("job", row, "Done"))
            say(("installed",))
            if row.get("entry") and row["kind"] in ("Games", "Demos"):
                new_entries.append(row)
        except Exception as e:
            say(("job", row, f"Failed: {str(e).splitlines()[0]}"))
            say(("log", f"{row['name']}: {e}"))
    for t in threads:
        t.join()
    if scrape and new_entries and not cancelled():
        _scrape(new_entries, roms_root, *scrape, say, cancelled)
    say(("end",))


def _scrape(rows, roms_root, platform, gamelist, do_text, say, cancelled):
    platforms = [platform]  # Matcher also searches lb.PLATFORM_EXTRAS (e.g. PSP minis)
    matchers = {p: lb.Matcher(p) for p in platforms}
    jobs = {p: [] for p in platforms}
    for r in rows:
        title = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", r["name"]).strip()
        for p, m in matchers.items():
            gid, _, _ = m.match(title)
            if gid:
                jobs[p].append((r["entry"], gid, (nps.REGIONS.get(r["region"], r["region"]),)))
                break
    for m in matchers.values():
        m.save()
    matched = sum(len(j) for j in jobs.values())
    if not matched:
        say(("scraped", "no LaunchBox match for the new games, nothing scraped"))
        return
    media = [k for k, (_, _, default) in scraper.MEDIA.items() if default]
    images = text = 0
    try:
        for p, j in jobs.items():
            if j:
                s = scraper.scrape(j, p, rows[0]["system"], roms_root, gamelist, do_text, media,
                                   lambda t_, d, t: say(("log", f"Scraping: {t_}")), cancelled)
                images, text = images + s["images"], text + s["text"]
        say(("scraped", f"scraped {matched} of {len(rows)} new games: {images} images"
                        + (f", {text} text fields" if do_text else
                           " (text skipped while RetroDECK runs: scrape again after closing it)")))
    except Exception as e:
        say(("scraped", f"scraping failed: {e}"))
