"""Gameplay videos from YouTube for games without an ES-DE clip (lib/youtube.py), when ☰ → Settings has it on."""
import os

import youtube
from rpc import ctx, method


@method
def youtube_video(title, console=""):
    """-> {"id", "embed", "page"}; id and embed are None when YouTube has no video for the game. The embed starts
    halfway in when the video's length is known."""
    v = youtube.find(title, console, os.path.join(ctx["data_dir"], "cache"))
    return {"id": v and v["id"], "embed": youtube.embed(v["id"], v["secs"]) if v else None,
            "page": youtube.page(title, console)}
