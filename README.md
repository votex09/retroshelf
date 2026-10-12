<p align="center"><img src="assets/icon-256.png" width="128" alt="RetroShelf icon"></p>

# RetroShelf

A desktop app for tidying up an [ES-DE](https://es-de.org/) / [RetroDECK](https://retrodeck.net/) game library on
Linux, Steam Deck or Windows. Point it at your `roms` folder, pick a system, and it helps you decide what to keep, fills
in metadata and artwork, gives your files consistent names, imports games from archives or a home server, and installs
PS3 / PS Vita / PSP games through NoPayStation and free homebrew from several stores. It works with a mouse, a keyboard
or a gamepad, and fits a Steam Deck's screen.

Nothing is deleted unless you ask: pruned games are moved to a holding folder outside `roms`, every move and
rename can be undone, and games only go for good when you delete them from the holding folder.

![RetroShelf's main window with a SNES library: the Keeping and Moving lists, three filters switched on, and Chrono Trigger's details](docs/screenshots/main.png)

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
- Double-click any game to flip it by hand, or use the keyboard or any gamepad (no Steam Input needed). Every
  button has a key that does the same (**☰ → Help** lists them; **Change buttons and keys…** there gives a job to
  another button or key, swapping with whatever had it, and **Back to the defaults** undoes it all):

  | | Gamepad | Keyboard |
  |---|---|---|
  | Choose a game / switch Keeping and Moving | D-pad ▲ ▼ / ◀ ▶ | ↑ ↓ / ← → |
  | Mark / flip to the other list (the marked games, if any) | A / X | Space / Enter |
  | Undo | Y | Ctrl+Z |
  | Unmark all, else clear the search; elsewhere back | B | Esc |
  | The game's menu (hide in ES-DE, LaunchBox match, collections) | R3 | Shift+F10 |
  | Page / scroll | L2 / R2, right stick | PgUp / PgDn |
  | Next part of the window (header, filters, lists, details, buttons) | L1 / R1 | F6 / Shift+F6 |
  | Search / ☰ menu | View / Menu | / / F10 |

  With a keyboard you can also type a few letters to jump to a game, and Shift+↑ ↓ or Ctrl+A select several.
  Outside the lists the D-pad or arrow keys move a ring from control to control and A or Enter presses; each part
  of the window remembers where you were. In a window's table the row under the ring is the picked one; L2 / R2
  (PgUp / PgDn) page through it, Home / End jump to its ends, and ▲ past the first row or ▼ past the last leaves
  it. In every window L1 / R1 (F6 / Shift+F6) go round its parts too (the filters, the table, the panel beside it,
  the buttons along the bottom). Folders and files are picked in RetroShelf's own browser, which a pad can work.
  A in a text box opens an on-screen keyboard. The bar along the bottom
  shows what works right there, as Steam Deck buttons or keys, whichever you used last. **☰ → Settings → Use a
  gamepad** turns the pad off; on a Steam Deck, Steam keeps the built-in controls while it runs.
- Each system goes back to the game you were on when you left it, after a restart too.
- **☰ → Review one at a time…** (Ctrl+R) goes through the list with each game's artwork and details: A / Space
  keeps, X / Enter moves, ◀ ▶ go back and skip, Y / Ctrl+Z undoes, L2 / R2 or the right stick (PgUp / PgDn) scroll
  the details and B / Esc closes.
- **Hide in ES-DE** (next to Move) is the gentler choice for the Moving list's games: they stay on disk and ES-DE
  leaves them out of its menus (it marks them hidden in its gamelist, and turns off ES-DE's "Show hidden games"
  if it's on). Hidden games stay in Keeping, like played ones, and show "hidden in ES-DE"; right-click →
  **Show in ES-DE again** undoes it.
- **☰ → Library → This console → Save as an ES-DE collection…** (or right-click → **Add to an ES-DE collection…**) puts the Keeping
  list, the Moving list or the selected games into an ES-DE custom collection, new or existing ("Best of SNES",
  "Party games" …). ES-DE then shows it next to the systems; RetroShelf turns it on in ES-DE's settings when ES-DE
  isn't running.
- Each system remembers its patterns, filters and flips, so it opens the way you left it.
- Multi-file games (cue/bin, multi-disc + m3u) are treated as one game and moved together.
- **☰ → Moved games → Restore a move…** puts a whole batch of moved games back, including RPCS3 / Vita3K data that went with them.
- **☰ → Moved games → Holding folder…** lists everything you've moved out, with artwork and details. Put games back one by one,
  or delete them for good (with their ES-DE artwork and gamelist entries) to free the space.
- A details panel shows the selected game's artwork, LaunchBox description, year, developer,
  rating and genres, plus a button that searches YouTube for gameplay videos. Artwork and videos always fill the
  same box (small pictures are scaled up), so the panel never shifts between games; Review shows them bigger.
- Short, quick animations show what just happened: a flipped game's name flies across to the other list and glows
  where it lands, the row under the mouse lights up gently, the keyboard gets the same gliding highlight as a gamepad
  (Tab, arrows, F6; moving the mouse puts it away), tooltips fade in, the list counts roll
  to their new numbers, artwork and details fade in (not while you're flicking down a list, so browsing stays
  instant), notifications slide in and out, the gamepad's button bar rises into view, and Review slides each game's
  name in as its progress bar glides along. The mouse wheel scrolls every list and text box smoothly, easing to a stop
  (quick flicks add up into one longer glide). **☰ → Settings → Animations** turns them off.

**Storage overview**
- **☰ → Library → Storage overview…** shows how much each system takes:
  its games, its ES-DE media (artwork, videos, manuals), and how much of it is disc images that
  **Compress games** could shrink. Pick a system to see its biggest games. Double-click a system or a
  game to go to it in the main window.

**Import ROMs**
- **☰ → Library → Import ROMs…** (Ctrl+I) is a bucket for games in whatever form you have them:
  zip / 7z / rar archives, disc images, loose ROMs, folders full of them. Put them in the `import` folder next to
  your `roms` folder (RetroShelf notices new files while the window is open), or add them from anywhere with
  **Add files…** / **Add a folder…** (which says how many games it found in the folder before listing them).
  A network share has to be mounted as a folder first (for example under `/mnt`).
- Each game's system is shown before anything moves, with how it was found: the file type when only one system
  uses it, the disc itself for images (PS2 and PS1 discs by their `SYSTEM.CNF`, PSP, GameCube, Wii, Saturn,
  Sega CD, Dreamcast, 3DO, PC Engine CD, Neo Geo CD, Xbox; `.cso`, `.rvz`, `.gcz`, `.pbp` and `.chd` too), or the
  folder name (`PS2`, `Sony - PlayStation 2`, …) when the file can't tell. Select any game to pick its system by hand.
- **Import** unpacks archives (7z needs nothing installed; rar and 7z's rarer methods use 7-Zip, unrar or bsdtar if
  you have one) and files the games into `roms/<system>`: a `.bin` without a `.cue` gets one, `.cue` / `.gdi` games
  keep their tracks together, full Xbox dumps are cut down to the part xemu reads, and arcade zips stay zipped under
  their set name. Readmes and tools inside archives are left out.
  An archive holding one game names it after the archive (`Tekken 3 (USA).7z` → `Tekken 3 (USA).iso`, a `.cue`'s
  tracks and the `.cue` itself too), since the name inside is often a scene name; packs of several games keep theirs.
- **Sources** (the second tab) lists games kept in another folder, like a home server's share mounted on this
  computer: add the folder once with **Add source…**, browse its games by system with box art and a gameplay video,
  queue them (A / Space) and **Add to Library** (or press Menu / F10). They're unpacked and filed like imports; the
  source is only read.
  Games you already have (same title, any region) say **In library**. **Look again** re-reads the folder.
  A source can also be a web address (`http://` or `https://`): a web server's folder listing, the page nginx,
  Apache, Caddy, lighttpd, a NAS's web share or `python -m http.server` show for a folder. Its folders are read
  for games, and the ones you queue are downloaded and then imported. If the server asks for a user name and
  password, give them when adding it; the password is kept encrypted with your system's keyring (when there's no
  keyring it's only kept until RetroShelf closes).
- Importing and copying keep going when you close the window (B / Esc), like compressing and scraping: see
  **Background jobs** below.
- Imported and copied games are scraped with LaunchBox right away (artwork and text they don't have yet) while
  **☰ → Settings → Scrape imported games** is on, which it is by default. It needs the LaunchBox data downloaded.
- Games unpack into a hidden staging folder first, so ES-DE never sees half a game, and the drive's free space is
  checked before a big archive is unpacked. Games from the import folder are moved out of it; games added from
  elsewhere are copied, unless you tick **Also delete the originals**.

**LaunchBox metadata**
- Downloads the free LaunchBox Games Database once and matches your games to it automatically.
- Right-click a game to pick its LaunchBox entry by hand when the match is missing or wrong.
- **☰ → Library → This console → Scrape metadata…** fills ES-DE text (description, developer, release date, genre, rating …) and images (covers,
  screenshots, title screens, marquees, 3D boxes …). It only fills gaps and never overwrites what's already there.
- Right-click a game (or the marked games) → **Scrape this game** does the same for just those, with the usual images,
  without opening the window. Close matches are scraped only after you say so.

**Gameplay videos**
- The details panel and the review window play the selected game's gameplay clip, muted and looping, a moment
  after you land on it: 🔇 Sound turns the sound on, the thumbnails go back to the pictures. Clips are ES-DE's own,
  from the `videos` folder of its media folder (ES-DE's scraper downloads them). RetroShelf looks for that folder
  where ES-DE's settings put it (Other settings → Game media directory), next to the ROMs folder (RetroDECK,
  portable ES-DE), in `~/ES-DE`, and in EmuDeck's `Emulation/tools/downloaded_media`. A clip that can't play says
  why under the picture.
- For games without a clip, **☰ → Settings → Gameplay from YouTube when there's no clip** plays the top YouTube
  result for "*title* *console* gameplay" in YouTube's own embedded player (it needs the internet, and the top result
  isn't always plain gameplay of the right game). It's off by default. **Gameplay videos on YouTube ↗** opens the
  search in your browser instead. **☰ → Settings → Play gameplay videos** turns videos off.

**Rename files**
- **☰ → Library → This console → Rename files…** renames ROMs to a pattern, by default the No-Intro order:
  `{title} ({region}) ({lang}) ({rev}) {tags}`. This also strips set numbers like `0012 - `.
- Live preview, conflict detection, and undo.
- Games you matched by hand, and scene-style names like `Final_Fantasy_IV_Complete_Collection_US.chd`, take
  their title from LaunchBox (`Final Fantasy IV - The Complete Collection (USA).chd`). Hand-picked matches
  follow the game through renames and undo.
- ES-DE media and `gamelist.xml` entries are renamed along with each game, so play counts, favorites and artwork
  stay with it. File names inside `.cue` / `.m3u` files are updated too.
- Arcade systems (`mame`, `arcade`, `fbneo`, `neogeo` and the like) are left alone: their emulators find games by
  ROM set file name, so renaming them would stop them starting.

**Background jobs**
- Importing, copying from a source, **Compress games**, **Scrape metadata**, NoPayStation and homebrew store downloads,
  and downloading the LaunchBox data keep going when you close their window, so you can carry on using RetroShelf.
  They run one at a time; one started while another runs waits its turn. A NoPayStation queue is kept for when the
  window opens again.
- While a system's games are being compressed or scraped, its games can't be moved, hidden, renamed or put back
  from the holding folder (RetroShelf says why): both would be rewriting the same files and gamelist.
- **Health check**, **Find duplicates** and **Storage overview** keep looking when you close them too, alongside
  the others (they only read), and show what they found when you open them again.
- The main window's footer shows the one running (and how many more are going or waiting). Selecting it opens its window again,
  where **Stop** ends it, leaving the game it's on as it was.
- Closing RetroShelf while one runs asks first: keep going, quit when everything's done, or stop and quit.

**Compress games**
- **☰ → Library → This console → Compress games…** turns disc images into the compressed formats the emulators read, usually a third
  to a half smaller: CD games (PlayStation, Saturn, Sega CD, Dreamcast, PC Engine CD, Neo Geo CD, 3DO, PC-FX) and
  PS2 discs become `.chd`, GameCube and Wii discs become `.rvz`. Select games to do only those.
- Each new file is written next to the game and checked before anything is replaced. `.m3u` playlists, ES-DE's
  gamelist entry (play counts, favorites) and artwork follow it, and the originals go to the holding folder
  (or are deleted, if you tick that), where **Restore a move…** can still put them back.
- Uses chdman (from RetroDECK or MAME) and dolphin-tool (from RetroDECK or Dolphin), found by themselves.

**Things to fix**
- A little after RetroShelf starts, then every hour and whenever a window that fixes something closes, it quietly
  looks for duplicates, health check problems, a nearly full ROMs drive (under 5% or 2 GB free) and a missing
  RetroDECK / ES-DE. ☰ shows how many it found, **☰ → Things to fix** lists them (each opens the window that fixes
  it), and a short message says when something new turns up. **☰ → Settings → Tell me about things to fix** turns it off.

**Library health check**
- **☰ → Library → Health check…** looks through every system folder (or just the current one) for what stops
  games starting: `.cue` / `.gdi` sheets and `.m3u` playlists naming files that aren't there, and raw `.bin`
  images with no `.cue`, and games on several discs with no `.m3u` playlist (one is written, and the separate
  discs are hidden in ES-DE so the game shows once). It also finds what takes space for nothing: empty game files, unfinished downloads,
  and ES-DE artwork, videos and gamelist entries for games that are gone.
- Whatever can be fixed is fixed in one go after you confirm: names in the wrong case (which break on Linux),
  playlists still naming discs that have since been compressed, a missing `.cue` written, leftovers deleted.
  Problems it can't fix are listed with what's missing.

**Find duplicates**
- **☰ → Library → Find duplicates…** finds games kept twice in one folder in different forms (a `.cue` / `.bin` and a
  `.chd`, a `.zip` and the ROM it holds), and identical files anywhere in the library, compared by content: the
  same game in two folders (`snes` and `sfc`, `genesis` and `megadrive`) or under two names.
- One copy of each stays, chosen for you: the one ES-DE's gamelist knows, then the better form (`.chd` over
  `.cue` / `.bin`), then the copy in the fuller folder. Double-click another copy to keep that one instead. The rest
  go to the holding folder, so **Restore a move…** can bring them back. When a game is kept in another form, its
  gamelist entry (play count, favorite) is moved over to it.

**NoPayStation (PS3, PS Vita, PSP)**
- **☰ → Get games → NoPayStation…** searches the NoPayStation lists. Queue games, DLC, demos and PS3 updates, and download and install them.
- The list fills the window; beside it are the picked game (with LaunchBox box art and a screenshot, then the top
  YouTube gameplay video), the queue and **Start**. A / Space (or double-click)
  adds a game to the queue, Y / Backspace takes it off.
- Shows which games you already have; can list available updates for installed PS3 games.
- Parallel, resumable downloads. Right-click the queue to retry failed jobs.
- PS3 packages are installed into RPCS3, PS Vita packages through Vita3K, PSP packages into your `roms` folder.

**Homebrew Hub (Game Boy, Game Boy Color, Game Boy Advance, NES)**
- **☰ → Get games → Homebrew Hub…** browses the free homebrew on [Homebrew Hub](https://hh.gbdev.io): search by name or
  developer, filter by system and type (games, demos, tools, music), with screenshots and descriptions.
- Open-source games install with one click. Homebrew Hub lets each author decide which apps may download their game,
  so for the others **Open on Homebrew Hub** opens the game's page in your browser; download it there and RetroShelf
  moves it from your Downloads folder into the right `roms` folder (zips are unpacked).
- New games are named `Title (Homebrew).ext` and get Homebrew Hub's description, developer, date and screenshot in
  ES-DE.

**itch.io homebrew (Game Boy, GBA, NES, SNES, Mega Drive, Master System, PC Engine, Atari 2600, PICO-8)**
- **☰ → Get games → itch.io homebrew…** lists free games itch.io tags for the system, from itch.io's official browse feeds.
- Games download on itch.io in your browser, where their authors can ask for an optional donation: **Open on
  itch.io** for a listed game, or **Browse on itch.io** to look around. Every ROM for the system that lands in your
  Downloads folder is put in the right `roms` folder (zips are unpacked; other downloads are left alone).
- itch.io's Cloudflare protection sometimes turns apps away from its feeds; the list is then empty, and Browse on
  itch.io still works.

**PDRoms homebrew (19 systems, from Game Boy, NES and Mega Drive to Lynx, Neo Geo Pocket and WonderSwan)**
- **☰ → Get games → PDRoms homebrew…** lists the games on [PDRoms](https://pdroms.de), a homebrew archive running since
  1998 that only carries freeware, open-source and legally cleared software. Fan games it marks as
  copyright-restricted aren't listed.
- Pick a game to see its author, description and screenshot. Games download on PDRoms in your browser (**Open on
  PDRoms** or **Browse on PDRoms**) and land in the right `roms` folder, as with itch.io.

**Free arcade games (MAMEDEV)**
- **☰ → Get games → Free arcade games (MAMEDEV)…** lists the [arcade games their owners released for free,
  non-commercial use](https://www.mamedev.org/roms/) through the MAME team: Gridlee, Robby Roto, Alien Arena, the
  Exidy classics and more.
- **Install** asks you to confirm non-commercial use, as mamedev.org does, then downloads the game from mamedev.org
  into `roms/mame` under the ROM set name MAME needs (`gridlee.zip`), with its description in ES-DE.

## Screenshots

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/review.png" alt="Review one at a time showing Super Metroid, with
      Keep and Move buttons and Steam Deck button hints"><br><sub><b>Review one at a time</b>: keep or move each game,
      here with a gamepad's buttons.</sub></td>
    <td width="50%"><img src="docs/screenshots/import.png" alt="Import ROMs listing a zip, a cue sheet and loose ROMs
      with the system found for each"><br><sub><b>Import ROMs</b>: each game's system is worked out before anything
      moves.</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/holding.png" alt="Holding folder window listing ten moved games"><br>
      <sub><b>Holding folder</b>: put moved games back or delete them for good.</sub></td>
    <td width="50%"><img src="docs/screenshots/rename.png" alt="Rename preview turning set-numbered and scene-style
      names into No-Intro names"><br><sub><b>Rename files</b>: preview No-Intro style names before anything
      changes.</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/storage.png" alt="Storage overview with each system's size and its
      biggest games"><br><sub><b>Storage overview</b>: what each system takes and what could be compressed.</sub></td>
    <td width="50%"><img src="docs/screenshots/light.png" alt="Main window in the light theme with the Genres filter
      open and Fighting picked"><br><sub><b>Light theme</b>, with a genre filter moving the fighting games.</sub></td>
  </tr>
</table>

<sub>Screenshots use a small demo library with descriptions from the LaunchBox Games Database. It has no scraped
artwork, so the games show RetroShelf's stand-in covers; with ES-DE's media they show their box art.</sub>

## Requirements

The app needs nothing else installed: Python and everything RetroShelf uses are inside, and it plays ES-DE's video
clips itself. PS Vita installs need Vita3K (the RetroDECK flatpak or a standalone build); compressing games uses the
chdman and dolphin-tool that come with RetroDECK.

The rest of this section is for the older Tk version.

- **Linux:** Python 3.9 or newer and Tk (`tkinter`). Most desktop distros ship both; on Debian / Ubuntu run
  `sudo apt install python3-tk`.
- **Windows:** Python 3.9 or newer from [python.org](https://www.python.org/downloads/windows/) (it includes Tk).
  Works with both the installer and the portable release of ES-DE: RetroShelf finds `C:\Users\<you>\ROMs` and
  `C:\Users\<you>\ES-DE`, or `ES-DE\ROMs` next to `ES-DE\ES-DE` for the portable one.
- On Linux, file and folder pickers are your desktop's own (`kdialog` on KDE / Steam Deck, `zenity` on GNOME), with
  Tk's built-in one only when neither is installed.
- No other Python packages are needed. With Pillow installed (`python3-pil.imagetk` on Debian / Ubuntu, `python-pillow` on Arch,
  `py -m pip install pillow` on Windows), the details panel
  can show JPEG artwork too; without it only PNG artwork is shown.
- Optional, for videos inside RetroShelf: `mpv` (plus `yt-dlp` to stream from YouTube), or `ffmpeg`.
- PS3 / PSP package decryption uses the `cryptography` module if it's installed
  and the system's OpenSSL library otherwise.
- For PS Vita installs: Vita3K (the RetroDECK flatpak or a standalone build).
- NoPayStation on Windows uses the standalone RPCS3 and Vita3K. They're found in ES-DE portable's `Emulators`
  folder or on `PATH`; otherwise pick their folders with **Emulators…** in the NoPayStation window. PS3 games get
  an RPCS3 `.lnk` shortcut in `ROMs\ps3`, which ES-DE's default *RPCS3 Shortcut* emulator launches.

## Install

Download the app from the [latest release](https://github.com/votex09/retroshelf/releases/latest). Python and
everything else it needs are inside.

- **Linux / Steam Deck:** `RetroShelf-<version>-linux-x86_64.AppImage`. Make it executable (right-click →
  Properties, or `chmod +x`) and run it. **☰ → Settings → Add to app menu** adds it to your application menu (updates
  keep the entry pointing at the new file); on a Steam Deck, add it to Steam as a non-Steam game.
- **Windows:** `RetroShelf-<version>-win-x64.exe` installs it (no administrator needed), or run
  `RetroShelf-<version>-portable.exe` from anywhere.

Coming from the older version (the zip with `retroshelf.py`)? The first time the app runs it finds the old copy
(from its app-menu entry, or in your home folder), brings your settings, move and rename logs, hand-picked matches and
downloaded data over without undoing anything you've set in the app, and points the app-menu entry (Windows: the
Start menu shortcut) at the app. Then it offers to remove the old copy. For a copy kept somewhere else:
**☰ → Settings → Bring settings over from the old RetroShelf…**, then pick its folder.

### The older version

The Tk version (`retroshelf.py`) still runs from a clone or the release's `retroshelf-<version>.zip`, but gets no
new features. It needs the requirements above.

```sh
./retroshelf.sh            # Linux, or: python3 retroshelf.py
retroshelf.bat             # Windows: double-click it, or: py retroshelf.py
```

### No RetroDECK or ES-DE yet?

On first start without a games library, RetroShelf offers to set one up (later: **☰ → Library → Set up RetroDECK…**,
or **Set up ES-DE…** on Windows). Pick where your games should go (your home folder, an SD card or drive, or any
folder, each with its free space), and RetroShelf does the rest:

- **Linux:** installs [RetroDECK](https://retrodeck.net) from Flathub for your user (no password needed; Flatpak
  must be installed, which it is on Steam Deck and most desktops). RetroDECK then runs its own first-time setup,
  which asks where its data goes: RetroShelf tells you which button to press and copies the folder path for you.
  When the setup finishes, RetroShelf switches to the new `retrodeck/roms` folder by itself.
- **Windows:** downloads the official portable build of [ES-DE](https://es-de.org) (its checksum is checked),
  unpacks it to `<your folder>\ES-DE`, creates a folder for each system in `ES-DE\ROMs` and can add ES-DE to the
  Start menu. ES-DE has no emulators of its own: add the ones you want to `ES-DE\Emulators` or install them
  normally.

RetroShelf also finds an existing RetroDECK wherever its data folder is (from RetroDECK's own settings), and an
existing ES-DE from its settings.

- **App menu:** the Windows installer adds RetroShelf to the Start menu; the AppImage adds itself to your
  application menu from **☰ → Settings → Add to app menu**. (The Tk version: **Help → Add to app menu**.)
- **Steam / Steam Deck:** add the AppImage to Steam as a non-Steam game.

On first start, run **☰ → Library → Download LaunchBox data** (about 110 MB) to enable ratings, genres, matching and scraping.

## Updating

The app checks GitHub for updates when it starts and every hour while it stays open (you can turn this off in
**☰ → Settings**, which also has **Check for updates**). The installed Windows app and the AppImage download a new version by themselves, and it goes in when
you restart RetroShelf (or press **⬆ Restart to update**). The portable .exe says when a new version is out.

Every change to the app that lands on `main` passes the tests and is then published as a release automatically
(`.github/workflows/release.yml`), versioned by date: `v2026.10.09`, then `v2026.10.09.2` for a second one that
day. Changes to docs, tests or CI alone don't make a release; **Run workflow** on the Actions tab forces one.

## Your data

The app keeps these files in `~/.config/RetroShelf` on Linux and `%APPDATA%\RetroShelf` on Windows (the older Tk
version keeps them next to `retroshelf.py`):

| File / folder | What it holds |
| --- | --- |
| `config.json` | Settings: folders, theme, region priority, rename patterns, each system's filters and flips |
| `moves.json` | Log of moved games, used by **Restore a move…** and **Holding folder…** |
| `renames.json` | Log of renames, used by **Undo…** in the rename dialog |
| `matches.json` | LaunchBox matches you picked by hand |
| `cache/` | LaunchBox and NoPayStation data (safe to delete; download it again from the app) |

**Import ROMs** uses an `import` folder next to your `roms` folder (change it in the window), and unpacks into a
hidden `.retroshelf-import` folder inside `roms` that's removed when it's done.

## Testing

Nothing here touches your real library: tests and the sandbox work on a generated RetroDECK folder with fake
SNES and PlayStation games, a small offline LaunchBox database, and `HOME` pointed at a temp folder.

```sh
tests/run.sh                        # whole suite (uses xvfb-run when there's no display)
py -m unittest discover -s tests -t . -v   # the same on Windows
tests/run.sh -v tests.test_app      # just the end-to-end window tests
tests/sandbox.py --run              # open the Tk RetroShelf on a throwaway library to try changes by hand
tests/sandbox.py --screenshot a.png # same, headless: saves a screenshot (needs xvfb and ImageMagick)
(cd app && npm install && npm run smoke)   # the app: start it, check the window and helper work together, quit
```

The tests need Python with Tk (`python3-tk`); the window tests also need a display or `xvfb-run`. CI runs them
on both Linux and Windows.

The app is built with Electron, in `app/` (see [app/README.md](app/README.md)); the work itself is done by the Python
code in `lib/`, which both versions share.

## Credits

- Game metadata and images: [LaunchBox Games Database](https://gamesdb.launchbox-app.com/)
- Package lists: [NoPayStation](https://nopaystation.com/)
- Homebrew: [Homebrew Hub](https://hh.gbdev.io), [itch.io](https://itch.io), [PDRoms](https://pdroms.de); free arcade
  ROMs: [MAMEDEV](https://www.mamedev.org/roms/)
- Theme of the older Tk version: [Sun Valley ttk theme](https://github.com/rdbende/Sun-Valley-ttk-theme) (MIT, bundled in `vendor/`)
