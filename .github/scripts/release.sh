#!/bin/bash
# Publish HEAD as a dated GitHub release. Run by .github/workflows/release.yml; needs gh and GH_TOKEN.
#   .github/scripts/release.sh --tag       # print the next tag and the app's version for it (tag=..., version=...)
#   TAG=v2026.10.11 ASSETS=dir .github/scripts/release.sh   # publish with that tag and the app's builds in dir
#   DRY_RUN=1 .github/scripts/release.sh   # print the tag and notes and build the zip, publish nothing
set -euo pipefail
cd "$(dirname "$0")/../.."

if git tag --points-at HEAD | grep -q '^v'; then
  echo "HEAD is already released as $(git tag --points-at HEAD | grep '^v' | head -1); nothing to do." >&2
  exit 0
fi

tag=${TAG:-}
if [ -z "$tag" ]; then
  base="v$(date -u +%Y.%m.%d)"
  tag=$base
  n=2
  while git rev-parse -q --verify "refs/tags/$tag" >/dev/null; do
    tag="$base.$n"
    n=$((n + 1))
  done
fi
if [ "${1:-}" = "--tag" ]; then
  # the app's version: semver from the date, so newer releases compare higher (app/updates.js tagVersion)
  IFS=. read -r y m d k <<<"${tag#v}"
  echo "tag=$tag"
  echo "version=$((10#$y)).$((10#$m * 100 + 10#$d)).$((${k:-1} - 1))"
  exit 0
fi

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
  echo "**Install:** download the app below: \`RetroShelf-…-linux-x86_64.AppImage\` on Linux and Steam Deck (make it"
  echo "executable and run it), \`RetroShelf-…-win-x64.exe\` (installer) or \`RetroShelf-…-portable.exe\` on Windows."
  echo "Installed copies update themselves. The old Tk version (\`retroshelf-$tag.zip\`) gets no new features; its"
  echo "last update brings your settings over to the app."
} >"$notes"

zip="retroshelf-$tag.zip"
git archive --format=zip --prefix=retroshelf/ -o "$zip" HEAD  # fills in lib/version.txt (export-subst)

echo "Release $tag ($(git rev-parse --short HEAD)):"
cat "$notes"
if [ -n "${DRY_RUN:-}" ]; then
  echo "DRY_RUN: built $zip, not publishing."
  exit 0
fi
assets=("$zip")
if [ -n "${ASSETS:-}" ]; then
  shopt -s nullglob
  assets+=("$ASSETS"/*)
fi
gh release create "$tag" "${assets[@]}" --target "$(git rev-parse HEAD)" --title "RetroShelf $tag" \
  --notes-file "$notes" --latest
