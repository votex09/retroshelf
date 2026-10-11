"""Box art and a screenshot for games that aren't in the library yet (NoPayStation, library sources): LaunchBox's
images, matched by name the way the scraper matches ROMs."""
import re, threading

import launchbox as lb
import scraper

TYPES = (["Box - Front", "Box - Front - Reconstructed", "Fanart - Box - Front"],
         ["Screenshot - Gameplay", "Screenshot - Game Title"])
_platforms = {}  # platform -> (Matcher, details)
_found = {}  # (platform, title, regions) -> find()'s answer
_lock = threading.Lock()


def title(name):
    """The name without its (tags) and [flags]."""
    return re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", name).strip()


def find(platform, name, regions=()):
    """-> {"art": [image urls: the box first, then a screenshot], "problem": why there are none, or ""}.
    regions: the game's regions as ROM tags have them ("USA", "Europe" …), for picking the right box."""
    if not platform or not lb.has_details():
        return {"art": [], "problem": "No artwork: download LaunchBox data from the ☰ menu first"}
    t = title(name)
    k = (platform, t, tuple(regions))
    if k not in _found:
        with _lock:
            if platform not in _platforms:
                _platforms[platform] = (lb.Matcher(platform), lb.load_details(platform))
            matcher, details = _platforms[platform]
            gid, _, _ = matcher.match(t)
        det = details.get(gid) or {}
        art = [scraper.pick_image(det.get("img", []), types, regions) for types in TYPES]
        _found[k] = {"art": [lb.IMAGE_URL + i[1] for i in art if i],
                     "problem": "" if gid else "No artwork: LaunchBox doesn't know this game"}
    return _found[k]
