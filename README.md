<p align="center"><img src="assets/icon-256.png" width="128" alt="RetroShelf icon"></p>

# RetroShelf

A desktop tool for tidying up an [ES-DE](https://es-de.org/) / [RetroDECK](https://retrodeck.net/) game library on
Linux. Point it at your `roms` folder, pick a system, and it helps you decide what to keep, fills in metadata and
artwork, gives your files consistent names, and installs PS3 / PS Vita / PSP games through NoPayStation.

Nothing is ever deleted: pruned games are moved to a holding folder outside `roms`, and every move and rename can be
undone.

## Features

**Prune your library**
- Two side-by-side lists, *Keeping* and *Moving*, that update live as you change filters.
- Presets: junk (demos, betas, protos, kiosk, unlicensed), sports, kids / licensed tie-ins, and region duplicates
  (keeps one copy per game, using a region priority you can reorder).
- Name patterns with `*` / `?` wildcards, `!` keep rules, and lists loaded from a text file.
- Filter by LaunchBox rating, vote count, genre and region.
- Played games are protected by default (play counts from ES-DE's `gamelist.xml`).
- Double-click any game to flip it by hand.
- Multi-file games (cue/bin, multi-disc + m3u) are treated as one game and moved together.
- **Restore…** puts moved games back, including RPCS3 / Vita3K data that went with them.

**LaunchBox metadata**
- Downloads the free LaunchBox Games Database once and matches your games to it automatically.
- Right-click a game to pick its LaunchBox entry by hand when the match is missing or wrong.
- **Scrape metadata…** fills ES-DE text (description, developer, release date, genre, rating …) and images (covers,
  screenshots, title screens, marquees, 3D boxes …). It only fills gaps and never overwrites what's already there.

**Rename files**
- **Rename…** renames ROMs to a pattern, by default the No-Intro order:
  `{title} ({region}) ({lang}) ({rev}) {tags}`. This also strips set numbers like `0012 - `.
- Live preview, conflict detection, and undo.
- ES-DE media and `gamelist.xml` entries are renamed along with each game, so play counts, favorites and artwork
  stay with it. File names inside `.cue` / `.m3u` files are updated too.

**NoPayStation (PS3, PS Vita, PSP)**
- Search the NoPayStation lists, queue games, DLC, demos and PS3 updates, and download and install them.
- Shows which games you already have; can list available updates for installed PS3 games.
- Parallel, resumable downloads. Right-click the queue to retry failed jobs.
- PS3 packages are installed into RPCS3, PS Vita packages through Vita3K, PSP packages into your `roms` folder.

## Requirements

- Linux with Python 3.9 or newer and Tk (`tkinter`). Most desktop distros ship both; on Debian / Ubuntu run
  `sudo apt install python3-tk`.
- No other Python packages are needed. PS3 / PSP package decryption uses the `cryptography` module if it's installed
  and the system's OpenSSL library otherwise.
- For PS Vita installs: Vita3K (the RetroDECK flatpak or a standalone build).

## Install

Either clone the repository:

```sh
git clone https://github.com/votex09/retroshelf.git
```

or download the [latest zip](https://github.com/votex09/retroshelf/archive/refs/heads/main.zip) and unpack it
anywhere.

## Run

```sh
./retroshelf.sh            # or: python3 retroshelf.py
```

- **App menu:** click **Add to app menu** in the top bar (or run `./retroshelf.sh --install-desktop`) to add RetroShelf
  to your desktop's application menu with its icon. If you move the folder, add it again.
- **Steam / Steam Deck:** add `retroshelf.sh` to Steam as a non-Steam game.

On first start, click **Download LaunchBox data** (about 110 MB) to enable ratings, genres, matching and scraping.

## Updating

RetroShelf checks GitHub for updates when it starts (you can turn this off) and has a **Check for updates** button.
Updating keeps your settings, logs and downloaded data and restarts the app. Git clones update with `git pull`; zip
copies download the new version and swap it in.

## Your data

These files live next to `retroshelf.py` and are never part of the repository:

| File / folder | What it holds |
| --- | --- |
| `config.json` | Settings: folders, theme, region priority, rename patterns |
| `moves.json` | Log of moved games, used by **Restore…** |
| `renames.json` | Log of renames, used by **Undo…** in the rename dialog |
| `matches.json` | LaunchBox matches you picked by hand |
| `cache/` | LaunchBox and NoPayStation data (safe to delete; download it again from the app) |

## Credits

- Game metadata and images: [LaunchBox Games Database](https://gamesdb.launchbox-app.com/)
- Package lists: [NoPayStation](https://nopaystation.com/)
- Theme: [Sun Valley ttk theme](https://github.com/rdbende/Sun-Valley-ttk-theme) (MIT, bundled in `vendor/`)
