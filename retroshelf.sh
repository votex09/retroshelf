#!/bin/sh
# Start RetroShelf. Double-click it, or add it to Steam as a non-Steam game.
# ./retroshelf.sh --install-desktop adds RetroShelf to your app menu.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
exec python3 retroshelf.py "$@"
