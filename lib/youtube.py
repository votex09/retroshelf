"""A gameplay video from YouTube for games ES-DE has no clip for. The new app plays it in YouTube's own embedded
player (youtube-nocookie.com), which YouTube allows, unlike playing streams outside it. The video is the top result of
YouTube's search for "<title> <console> gameplay"; answers are remembered in cache/youtube.json."""
import json, os, re, threading, urllib.parse, urllib.request

from fsutil import write_json

SEARCH = "https://www.youtube.com/results?search_query="
EMBED = "https://www.youtube-nocookie.com/embed/"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
VIDEO_ID = re.compile(r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})"')
_lock = threading.Lock()


def query(title, console):
    return " ".join(x for x in (title, console, "gameplay") if x)


def page(title, console):
    """YouTube's search in the browser."""
    return SEARCH + urllib.parse.quote_plus(query(title, console))


def first_video(html):
    """The first video (not an ad, channel or playlist) in a YouTube search results page, or None."""
    m = VIDEO_ID.search(html)
    return m.group(1) if m else None


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", "replace")


def find(title, console, cache_dir, fetch=None):
    """-> the video id for this game (from the cache, else searched), or None when YouTube has none.
    Raises OSError when YouTube can't be reached."""
    q = query(title, console)
    path = os.path.join(cache_dir, "youtube.json")
    with _lock:
        try:
            with open(path, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, ValueError):
            cache = {}
    if q in cache:
        return cache[q]
    vid = first_video((fetch or _fetch)(SEARCH + urllib.parse.quote_plus(q)))
    with _lock:
        cache[q] = vid
        os.makedirs(cache_dir, exist_ok=True)
        write_json(path, cache, ensure_ascii=False)
    return vid


def embed(vid):
    """YouTube's player for the video: muted autoplay, looping, without suggestions from other channels."""
    return f"{EMBED}{vid}?autoplay=1&mute=1&loop=1&playlist={vid}&rel=0&modestbranding=1&playsinline=1"
