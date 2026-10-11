"""Gameplay videos from YouTube for games without an ES-DE clip (lib/youtube.py), when ☰ → Settings has it on."""
import os

import youtube
from rpc import ctx, method


@method
def youtube_video(title, console=""):
    """-> {"id", "embed", "page"}; id and embed are None when YouTube has no video for the game."""
    vid = youtube.find(title, console, os.path.join(ctx["data_dir"], "cache"))
    return {"id": vid, "embed": youtube.embed(vid) if vid else None, "page": youtube.page(title, console)}
