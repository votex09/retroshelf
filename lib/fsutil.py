"""Small file helpers shared by the app and lib modules."""
import json, os


def write_json(path, data, **kw):
    """Write JSON through a temp file and a rename, so a crash or full disk mid-write never leaves a truncated
    file behind (config.json, matches.json and the logs would otherwise read back as empty and be overwritten)."""
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, **kw)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
