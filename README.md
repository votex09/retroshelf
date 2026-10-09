<p align="center"><img src="assets/icon-256.png" width="128" alt="RetroShelf icon"></p>

# RetroShelf

A desktop tool for tidying up an [ES-DE](https://es-de.org/) / [RetroDECK](https://retrodeck.net/) game library on
Linux or Windows. Point it at your `roms` folder, pick a system, and it helps you decide what to keep, fills in metadata and
artwork, gives your files consistent names, and installs PS3 / PS Vita / PSP games through NoPayStation.

Nothing is deleted unless you ask: pruned games are moved to a holding folder outside `roms`, every move and
rename can be undone, and games only go for good when you delete them from the holding folder.

![RetroShelf main window with a SNES library, Chrono Trigger's details, filters, and the games to keep and move](docs/screenshots/main.png)

## Features

**Prune your library**
- Two side-by-side lists, *Keeping* and *Moving*, that update live as you change filters.
- Shows how much space is free on the drive your ROMs are on.
- Filters sit in tabs (Presets & ratings, Genres, Regions, Patterns) whose names count what's switched on, so the
  layout fits a Steam Deck screen next to the details panel.
- Presets: junk (demos, betas, protos, kiosk, unlicensed), sports, kids / licensed tie-ins, and region duplicates
  (keeps one copy per game, using a region priority you can reorder).
- Name patterns with `*` / `?` wildcards and `!` keep rules.
- Filter by LaunchBox rating, vote count, genre and region.
- Played games are protected by default (play counts from ES-DE's `gamelist.xml`).
- Double-click any game to flip it by hand.
- Each system remembers its patterns, filters and flips, so it opens the way you left it.
- Multi-file games (cue/bin, multi-disc + m3u) are treated as one game and moved together.
- **Library → Restore a move…** puts a whole batch of moved games back, including RPCS3 / Vita3K data that went with them.
- **Library → Holding folder…** lists everything you've moved out, with artwork and details. Put games back one by one,
  or delete them for good (with their ES-DE artwork and gamelist entries) to free the space.
- A details panel shows the selected game's artwork, LaunchBox description, year, developer,
  rating and genres, plus a button that searches YouTube for gameplay videos.

**LaunchBox metadata**
- Downloads the free LaunchBox Games Database once and matches your games to it automatically.
- Right-click a game to pick its LaunchBox entry by hand when the match is missing or wrong.
- **Tools → Scrape metadata…** fills ES-DE text (description, developer, release date, genre, rating …) and images (covers,
  screenshots, title screens, marquees, 3D boxes …). It only fills gaps and never overwrites what's already there.

**Rename files**
- **Tools → Rename files…** renames ROMs to a pattern, by default the No-Intro order:
  `{title} ({region}) ({lang}) ({rev}) {tags}`. This also strips set numbers like `0012 - `.
- Live preview, conflict detection, and undo.
- Games you matched by hand, and scene-style names like `Final_Fantasy_IV_Complete_Collection_US.chd`, take
  their title from LaunchBox (`Final Fantasy IV - The Complete Collection (USA).chd`). Hand-picked matches
  follow the game through renames and undo.
- ES-DE media and `gamelist.xml` entries are renamed along with each game, so play counts, favorites and artwork
  stay with it. File names inside `.cue` / `.m3u` files are updated too.

**NoPayStation (PS3, PS Vita, PSP)**
- **Tools → NoPayStation…** searches the NoPayStation lists. Queue games, DLC, demos and PS3 updates, and download and install them.
- Shows which games you already have; can list available updates for installed PS3 games.
- Parallel, resumable downloads. Right-click the queue to retry failed jobs.
- PS3 packages are installed into RPCS3, PS Vita packages through Vita3K, PSP packages into your `roms` folder.

**Homebrew Hub (Game Boy, Game Boy Color, Game Boy Advance, NES)**
- **Tools → Homebrew Hub…** browses the free homebrew on [Homebrew Hub](https://hh.gbdev.io): search by name or
  developer, filter by system and type (games, demos, tools, music), with screenshots and descriptions.
- Open-source games install with one click. Homebrew Hub lets each author decide which apps may download their game,
  so for the others **Open on Homebrew Hub** opens the game's page in your browser; download it there and RetroShelf
  moves it from your Downloads folder into the right `roms` folder (zips are unpacked).
- New games are named `Title (Homebrew).ext` and get Homebrew Hub's description, developer, date and screenshot in
  ES-DE.

## Screenshots

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/holding.png" alt="Holding folder window with a moved game's cover and
      description"><br><sub><b>Holding folder</b>: review moved games, put them back or delete them for good.</sub></td>
    <td width="50%"><img src="docs/screenshots/rename.png" alt="Rename preview turning set-numbered names into
      No-Intro names"><br><sub><b>Rename files</b>: preview No-Intro style names before anything changes.</sub></td>
  </tr>
  <tr>
    <td colspan="2"><img src="docs/screenshots/light.png" alt="Main window in light mode with a genre filter
      active"><br><sub><b>Light mode</b>, with a genre filter moving the fighting games.</sub></td>
  </tr>
</table>

<sub>Screenshots use a small demo library; artwork and descriptions come from the LaunchBox Games Database.</sub>

## Requirements

- **Linux:** Python 3.9 or newer and Tk (`tkinter`). Most desktop distros ship both; on Debian / Ubuntu run
  `sudo apt install python3-tk`.
- **Windows:** Python 3.9 or newer from [python.org](https://www.python.org/downloads/windows/) (it includes Tk).
  Works with both the installer and the portable release of ES-DE: RetroShelf finds `C:\Users\<you>\ROMs` and
  `C:\Users\<you>\ES-DE`, or `ES-DE\ROMs` next to `ES-DE\ES-DE` for the portable one.
- No other Python packages are needed. With Pillow installed (`python3-pil.imagetk` on Debian / Ubuntu, `python-pillow` on Arch,
  `py -m pip install pillow` on Windows), the details panel
  can show JPEG artwork too; without it only PNG artwork is shown.
- PS3 / PSP package decryption uses the `cryptography` module if it's installed
  and the system's OpenSSL library otherwise.
- For PS Vita installs: Vita3K (the RetroDECK flatpak or a standalone build).
- NoPayStation on Windows uses the standalone RPCS3 and Vita3K. They're found in ES-DE portable's `Emulators`
  folder or on `PATH`; otherwise pick their folders with **Emulators…** in the NoPayStation window. PS3 games get
  an RPCS3 `.lnk` shortcut in `ROMs\ps3`, which ES-DE's default *RPCS3 Shortcut* emulator launches.

## Install

Either clone the repository:

```sh
git clone https://github.com/votex09/retroshelf.git
```

or download `retroshelf-<version>.zip` from the [latest release](https://github.com/votex09/retroshelf/releases/latest)
and unpack it anywhere.

## Run

```sh
./retroshelf.sh            # Linux, or: python3 retroshelf.py
retroshelf.bat             # Windows: double-click it, or: py retroshelf.py
```

- **App menu:** use **Help → Add to app menu** (Windows: **Add to Start menu**), or run the launcher with
  `--install-desktop`, to add RetroShelf to your application menu with its icon. If you move the folder, add it again.
- **Steam / Steam Deck:** add `retroshelf.sh` (Windows: `retroshelf.bat`) to Steam as a non-Steam game.

On first start, run **Tools → Download LaunchBox data** (about 110 MB) to enable ratings, genres, matching and scraping.

## Updating

RetroShelf checks GitHub for updates when it starts (you can turn this off) and has **Help → Check for updates**.
Updating keeps your settings, logs and downloaded data and restarts the app. Git clones update with `git pull`; zip
copies download the latest [release](https://github.com/votex09/retroshelf/releases) and swap it in.

Every change to the app that lands on `main` passes the tests and is then published as a release automatically
(`.github/workflows/release.yml`), versioned by date: `v2026.10.09`, then `v2026.10.09.2` for a second one that
day. Changes to docs, tests or CI alone don't make a release; **Run workflow** on the Actions tab forces one.

## Your data

These files live next to `retroshelf.py` and are never part of the repository:

| File / folder | What it holds |
| --- | --- |
| `config.json` | Settings: folders, theme, region priority, rename patterns, each system's filters and flips |
| `moves.json` | Log of moved games, used by **Restore a move…** and **Holding folder…** |
| `renames.json` | Log of renames, used by **Undo…** in the rename dialog |
| `matches.json` | LaunchBox matches you picked by hand |
| `cache/` | LaunchBox and NoPayStation data (safe to delete; download it again from the app) |

## Testing

Nothing here touches your real library: tests and the sandbox work on a generated RetroDECK folder with fake
SNES and PlayStation games, a small offline LaunchBox database, and `HOME` pointed at a temp folder.

```sh
tests/run.sh                        # whole suite (uses xvfb-run when there's no display)
py -m unittest discover -s tests -t . -v   # the same on Windows
tests/run.sh -v tests.test_app      # just the end-to-end window tests
tests/sandbox.py --run              # open RetroShelf on a throwaway library to try changes by hand
tests/sandbox.py --screenshot a.png # same, headless: saves a screenshot (needs xvfb and ImageMagick)
```

The tests need Python with Tk (`python3-tk`); the window tests also need a display or `xvfb-run`. CI runs them
on both Linux and Windows.

## Credits

- Game metadata and images: [LaunchBox Games Database](https://gamesdb.launchbox-app.com/)
- Package lists: [NoPayStation](https://nopaystation.com/)
- Theme: [Sun Valley ttk theme](https://github.com/rdbende/Sun-Valley-ttk-theme) (MIT, bundled in `vendor/`)
