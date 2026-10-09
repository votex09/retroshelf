"""Self-update from GitHub. Git clones fast-forward with git pull; zip copies follow the published releases (made
for every change on main by .github/workflows/release.yml): they download the latest release's archive and swap in
its files (cache/, config and logs aren't in the archive, so they're left alone). Until a release exists, zip copies
follow the main branch instead."""
import json, os, re, shutil, subprocess, sys, tempfile, urllib.error, urllib.request, zipfile

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "votex09/retroshelf"
BRANCH = "main"
VERSION_FILE = os.path.join(APP_DIR, "lib", "version.txt")  # commit id, filled in by git archive (export-subst)
USER_AGENT = "RetroShelf-updater"
SHA_RE = re.compile(r"[0-9a-f]{40}")


def _git(*args, timeout=60):
    return subprocess.run(["git", "-C", APP_DIR, *args], capture_output=True, text=True, timeout=timeout)


def is_git():
    return os.path.isdir(os.path.join(APP_DIR, ".git")) and bool(shutil.which("git"))


def local_sha():
    if is_git():
        r = _git("rev-parse", "HEAD")
        return r.stdout.strip() if r.returncode == 0 else None
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            v = f.read().strip()
    except OSError:
        return None
    return v if SHA_RE.fullmatch(v) else None


def _api(path):
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/{path}",
                                 headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def latest_release():
    """-> (tag, release notes) of the newest published release, or (None, "") if there isn't one yet."""
    try:
        rel = _api("releases/latest")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, ""
        raise
    return rel["tag_name"], (rel.get("body") or "").strip()


def check():
    """-> {"behind": commits to pull (None = unknown), "commits": [subject lines, newest first], "note": str,
    "tag": release to install (None = the main branch, or a git clone), "notes": that release's notes}.
    Raises RuntimeError with a readable message when the check can't be done."""
    if is_git():
        if _git("rev-parse", "--abbrev-ref", "@{u}").returncode:
            raise RuntimeError("this git checkout has no upstream branch to update from")
        r = _git("fetch", "--quiet")
        if r.returncode:
            raise RuntimeError(f"git fetch failed: {r.stderr.strip() or r.stdout.strip()}")
        behind = int(_git("rev-list", "--count", "HEAD..@{u}").stdout.strip() or 0)
        ahead = int(_git("rev-list", "--count", "@{u}..HEAD").stdout.strip() or 0)
        log = _git("log", "--format=%s", "HEAD..@{u}").stdout.splitlines()
        note = f"You have {ahead} local commits that aren't on GitHub; git can't fast-forward." if ahead and behind \
            else ""
        return {"behind": behind, "commits": log, "note": note, "tag": None, "notes": ""}
    try:
        tag, notes = latest_release()
        target = tag or BRANCH
        res = {"behind": None, "commits": [], "note": "", "tag": tag, "notes": notes}
        local = local_sha()
        if not local:
            return dict(res, note="This copy doesn't know its version, so updating replaces it with the latest one.")
        try:
            cmp = _api(f"compare/{local}...{target}")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            return dict(res, note="This version isn't in the GitHub history any more.")
        # "behind": this copy is newer than the release (e.g. downloaded from main), so there's nothing to install
        if cmp["status"] in ("identical", "behind"):
            return dict(res, behind=0)
        commits = [c["commit"]["message"].splitlines()[0] for c in reversed(cmp["commits"])]
        return dict(res, behind=cmp["ahead_by"], commits=commits)
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        raise RuntimeError(f"couldn't reach GitHub: {getattr(e, 'reason', e)}")


def apply(tag=None):
    """Bring the files up to date: git pull, or for zip copies the release tag (None = the main branch).
    -> short description. Raises RuntimeError if nothing was changed."""
    if is_git():
        if _git("status", "--porcelain", "--untracked-files=no").stdout.strip():
            raise RuntimeError("this checkout has uncommitted changes; commit or stash them first")
        r = _git("pull", "--ff-only", timeout=300)
        if r.returncode:
            raise RuntimeError(f"git pull failed: {r.stderr.strip() or r.stdout.strip()}")
        return "updated with git pull"

    work = tempfile.mkdtemp(prefix=".update-", dir=APP_DIR)  # same filesystem, so the swap is just renames
    try:
        zpath = os.path.join(work, "update.zip")
        ref = f"tags/{tag}" if tag else f"heads/{BRANCH}"
        req = urllib.request.Request(f"https://codeload.github.com/{REPO}/zip/refs/{ref}",
                                     headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(zpath, "wb") as f:
                shutil.copyfileobj(r, f)
        except (urllib.error.URLError, OSError) as e:
            raise RuntimeError(f"download failed: {getattr(e, 'reason', e)}")
        new = os.path.join(work, "new")
        with zipfile.ZipFile(zpath) as z:
            sha = z.comment.decode("ascii", "ignore").strip()  # git archive stores the commit id here
            for name in z.namelist():
                target = os.path.realpath(os.path.join(new, name))
                if not target.startswith(os.path.realpath(new) + os.sep):
                    raise RuntimeError(f"refusing odd path in the download: {name}")
            z.extractall(new)
            for info in z.infolist():  # zipfile drops permissions; retroshelf.sh must stay executable
                mode = (info.external_attr >> 16) & 0o777
                if mode and not info.is_dir():
                    os.chmod(os.path.join(new, info.filename), mode)
        tops = os.listdir(new)
        src = os.path.join(new, tops[0]) if len(tops) == 1 else new
        if not os.path.isfile(os.path.join(src, "retroshelf.py")):
            raise RuntimeError("the download doesn't look like RetroShelf")
        if SHA_RE.fullmatch(sha):
            with open(os.path.join(src, "lib", "version.txt"), "w", encoding="utf-8") as f:
                f.write(sha + "\n")

        old = os.path.join(work, "old")
        os.makedirs(old)
        swapped = []  # (name, had an old copy) so a failure halfway puts everything back
        try:
            for name in os.listdir(src):
                dest = os.path.join(APP_DIR, name)
                had = os.path.lexists(dest)
                if had:
                    os.rename(dest, os.path.join(old, name))
                swapped.append((name, had))
                os.rename(os.path.join(src, name), dest)
        except OSError as e:
            for name, had in reversed(swapped):
                dest = os.path.join(APP_DIR, name)
                if os.path.lexists(dest) and not os.path.lexists(os.path.join(src, name)):
                    os.rename(dest, os.path.join(src, name))
                if had:
                    os.rename(os.path.join(old, name), dest)
            raise RuntimeError(f"couldn't swap in the new files, nothing was changed: {e}")
        return f"installed {tag}" if tag else "downloaded the latest version"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def restart():
    os.execv(sys.executable, [sys.executable, os.path.join(APP_DIR, "retroshelf.py")] + sys.argv[1:])
