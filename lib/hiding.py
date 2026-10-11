"""Hide games in ES-DE instead of moving them: the files stay, ES-DE's menus leave them out.

ES-DE keeps the flag in the game's gamelist.xml entry (<hidden>true</hidden>), and only leaves hidden games out
when its "Show hidden games" setting is off; it's on until someone turns it off, so hide_games() can turn it off
too (es_settings.xml: ShowHiddenGames).

    hidden(gamelist)                      -> {file name: True} for games marked hidden
    set_hidden(gamelist, files, hidden)   -> how many entries changed (entries are made for games that have none)
    shows_hidden(es_home)                 -> True / False, or None when ES-DE hasn't been set up
    stop_showing_hidden(es_home)          -> True if es_settings.xml changed"""
import datetime, os, re, shutil
import xml.etree.ElementTree as ET

import scraper

TRUE = {"true", "1", "yes"}


def hidden(gamelist):
    """File names (not paths) of the games ES-DE has marked hidden."""
    out = set()
    if not gamelist or not os.path.exists(gamelist):
        return out
    try:
        _, root = scraper.read_gamelist(gamelist)
    except (OSError, ET.ParseError):
        return out
    for g in root.iter("game"):
        if (g.findtext("hidden") or "").strip().lower() in TRUE:
            out.add(os.path.basename((g.findtext("path") or "").rstrip("/")))
    return out


def set_hidden(gamelist, files, hide=True):
    """files: the game files (as ES-DE lists them) to hide or show again. -> entries changed."""
    names = {os.path.basename(f.rstrip("/\\")) for f in files}
    if not names:
        return 0
    if os.path.exists(gamelist):
        tops, root = scraper.read_gamelist(gamelist)  # parse first, so a broken file fails before anything's touched
        shutil.copy2(gamelist, f"{gamelist}.bak-{datetime.datetime.now():%Y%m%d-%H%M%S}")
    elif not hide:
        return 0
    else:
        os.makedirs(os.path.dirname(gamelist), exist_ok=True)
        root = ET.Element("gameList")
        tops = [root]
    seen, changed = set(), 0
    for g in root.iter("game"):
        name = os.path.basename((g.findtext("path") or "").rstrip("/"))
        if name not in names:
            continue
        seen.add(name)
        el = g.find("hidden")
        now = el is not None and (el.text or "").strip().lower() in TRUE
        if now == hide:
            continue
        if hide:
            if el is None:
                el = ET.SubElement(g, "hidden")
            el.text = "true"
        else:
            g.remove(el)
        changed += 1
    if hide:
        for name in sorted(names - seen):  # never scraped: ES-DE makes the same entry, with the file name as name
            g = ET.SubElement(root, "game")
            ET.SubElement(g, "path").text = f"./{name}"
            ET.SubElement(g, "name").text = os.path.splitext(name)[0]
            ET.SubElement(g, "hidden").text = "true"
            changed += 1
    if changed:
        scraper.save_gamelist(gamelist, tops)
    return changed


SETTING = re.compile(r'<bool\s+name="ShowHiddenGames"\s+value="(\w+)"\s*/>')


def _settings(es_home):
    return os.path.join(es_home, "settings", "es_settings.xml")


def shows_hidden(es_home):
    try:
        with open(_settings(es_home), encoding="utf-8") as f:
            m = SETTING.search(f.read())
    except OSError:
        return None
    return True if not m else m.group(1).lower() in TRUE  # missing means ES-DE's default: shown


def stop_showing_hidden(es_home):
    path = _settings(es_home)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return False
    if SETTING.search(text):
        if not SETTING.search(text).group(1).lower() in TRUE:
            return False
        new = SETTING.sub('<bool name="ShowHiddenGames" value="false" />', text, count=1)
    else:
        new = text.rstrip("\n") + '\n<bool name="ShowHiddenGames" value="false" />\n'
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    os.replace(tmp, path)
    return True
