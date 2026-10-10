#!/bin/bash
# Publish HEAD as a dated GitHub release. Run by .github/workflows/release.yml; needs gh and GH_TOKEN.
#   DRY_RUN=1 .github/scripts/release.sh   # print the tag and notes and build the zip, publish nothing
set -euo pipefail
cd "$(dirname "$0")/../.."

if git tag --points-at HEAD | grep -q '^v'; then
  echo "HEAD is already released as $(git tag --points-at HEAD | grep '^v' | head -1); nothing to do."
  exit 0
fi

base="v$(date -u +%Y.%m.%d)"
tag=$base
n=2
while git rev-parse -q --verify "refs/tags/$tag" >/dev/null; do
  tag="$base.$n"
  n=$((n + 1))
done

prev=$(git describe --tags --abbrev=0 --match 'v[0-9]*' HEAD 2>/dev/null || true)
notes=$(mktemp)
{
  if [ -n "$prev" ]; then
    echo "## Changes since $prev"
    echo
    git log --no-merges --format='- %s' "$prev..HEAD"
  else
    echo "## First release"
    echo
    git log --no-merges --format='- %s' -n 20 HEAD
  fi
  echo
  echo "**Install:** download \`retroshelf-$tag.zip\` below, unpack it anywhere and run \`./retroshelf.sh\`."
  echo "Copies you already have update themselves from **Help → Check for updates**."
} >"$notes"

zip="retroshelf-$tag.zip"
git archive --format=zip --prefix=retroshelf/ -o "$zip" HEAD  # fills in lib/version.txt (export-subst)
# RetroShelf's ScreenScraper developer ID, from repository secrets: in release zips, never in the source
if [ -n "${SS_DEVID:-}" ] && [ -n "${SS_DEVPASSWORD:-}" ]; then
  python3 - "$zip" <<'PY'
import base64, json, os, sys, zipfile
def scramble(t):  # matches lib/screenscraper.py
    return base64.b64encode(bytes(b ^ 0x5A for b in t.encode())).decode()
with zipfile.ZipFile(sys.argv[1], "a", zipfile.ZIP_DEFLATED) as z:
    z.writestr("retroshelf/screenscraper_dev.json",
               json.dumps({"id": scramble(os.environ["SS_DEVID"]), "password": scramble(os.environ["SS_DEVPASSWORD"])}))
PY
  echo "Added the ScreenScraper developer ID."
else
  echo "No SS_DEVID / SS_DEVPASSWORD secrets: the release has no ScreenScraper developer ID."
fi

echo "Release $tag ($(git rev-parse --short HEAD)):"
cat "$notes"
if [ -n "${DRY_RUN:-}" ]; then
  echo "DRY_RUN: built $zip, not publishing."
  exit 0
fi
gh release create "$tag" "$zip" --target "$(git rev-parse HEAD)" --title "RetroShelf $tag" \
  --notes-file "$notes" --latest
