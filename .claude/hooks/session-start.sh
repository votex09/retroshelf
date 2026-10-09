#!/bin/bash
# Claude Code cloud sessions: install Tk, Pillow, a virtual display and ImageMagick so tests/run.sh and
# tests/sandbox.py --screenshot work. Does nothing on your own machine.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

pkgs=(python3-tk python3-pil python3-pil.imagetk xvfb xauth imagemagick)
missing=()
for p in "${pkgs[@]}"; do
  dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
done
if [ ${#missing[@]} -gt 0 ]; then
  SUDO=""
  [ "$(id -u)" -eq 0 ] || SUDO="sudo -n"
  $SUDO apt-get update -qq
  DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq --no-install-recommends "${missing[@]}" >/dev/null
fi
