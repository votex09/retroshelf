"""A gameplay video from YouTube for games ES-DE has no clip for. The new app plays it in YouTube's own embedded
player (youtube-nocookie.com), which YouTube allows, unlike playing streams outside it. The video is the top result of
YouTube's search for "<title> <console> gameplay": its results page, else the same search through the API YouTube's
own page uses. Videos found are remembered in cache/youtube.json; a search that finds none is tried again next run."""
import json, os, re, threading, urllib.parse, urllib.request

from fsutil import write_json

SEARCH = "https://www.youtube.com/results?search_query="
SEARCH_API = "https://www.youtube.com/youtubei/v1/search?prettyPrint=false"
API_CLIENT = {"clientName": "WEB", "clientVersion": "2.20260708.00.00", "hl": "en"}
EMBED = "https://www.youtube-nocookie.com/embed/"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
# In Europe YouTube puts its cookie notice in front of every search until it's answered: answer it (as yt-dlp does)
COOKIE = "SOCS=CAI; CONSENT=YES+"
VIDEO_ID = re.compile(r'"videoRenderer":\s*\{\s*"videoId":\s*"([A-Za-z0-9_-]{11})"')
LOCKUP_ID = re.compile(r'"contentId":\s*"([A-Za-z0-9_-]{11})",\s*"contentType":\s*"LOCKUP_CONTENT_TYPE_VIDEO"')
RESULTS = ('"twoColumnSearchResultsRenderer"', '"sectionListRenderer"', '"itemSectionRenderer"')
_lock = threading.Lock()
_none = set()  # searches that found nothing this run


def query(title, console):
    return " ".join(x for x in (title, console, "gameplay") if x)


def page(title, console):
    """YouTube's search in the browser."""
    return SEARCH + urllib.parse.quote_plus(query(title, console))


def first_video(text):
    """The first video (not an ad, channel or playlist) in a YouTube search results page or API answer, or None."""
    m = VIDEO_ID.search(text) or LOCKUP_ID.search(text)
    return m.group(1) if m else None


def is_results(text):
    """Whether this is a list of search results (perhaps empty), not a cookie notice, sign-in or error page."""
    return any(r in text for r in RESULTS)


def _fetch(url, data=None):
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en", "Cookie": COOKIE}
    if data is not None:
        data, headers["Content-Type"] = json.dumps(data).encode(), "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", "replace")


def search(q, fetch=None):
    """-> the top video's id for this search, or None when YouTube has none.
    Raises OSError when YouTube can't be reached or answers with something other than results."""
    fetch = fetch or _fetch
    tries = (lambda: fetch(SEARCH + urllib.parse.quote_plus(q)),
             lambda: fetch(SEARCH_API, {"context": {"client": API_CLIENT}, "query": q}))
    why = None
    for get in tries:
        try:
            text = get()
        except OSError as e:
            why = e
            continue
        vid = first_video(text)
        if vid or is_results(text):
            return vid
        why = OSError("YouTube didn't send search results")
    raise why


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
    if cache.get(q):  # older versions also saved None for searches that failed: those are searched again
        return cache[q]
    if q in _none:
        return None
    vid = search(q, fetch)
    if not vid:
        _none.add(q)
        return None
    with _lock:
        cache[q] = vid
        os.makedirs(cache_dir, exist_ok=True)
        write_json(path, cache, ensure_ascii=False)
    return vid


def embed(vid):
    """YouTube's player for the video: muted autoplay, looping, without suggestions from other channels."""
    return f"{EMBED}{vid}?autoplay=1&mute=1&loop=1&playlist={vid}&rel=0&modestbranding=1&playsinline=1"
