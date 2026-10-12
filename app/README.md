# RetroShelf's app (Electron)

This folder is RetroShelf's app: Electron draws the windows and RetroShelf's Python code (`lib/`) does the work,
through a helper process. It's the version that's released; the older Tk app (`retroshelf.py`) still runs but gets no
new features. What it does is in the [main README](../README.md).

It keeps its settings (config.json, moves.json, LaunchBox's cache/) in its data folder (`~/.config/RetroShelf` on
Linux, `%APPDATA%\RetroShelf` on Windows), in the Tk app's formats. The first time it runs it brings the Tk app's
settings over by itself (`lib/handoff.py`).

```
main.js            the app: opens the window, runs the helper, answers the window's requests
helper.js          runs the Python helper and matches its answers to requests
preload.js         what the window is allowed to ask for (window.retroshelf)
renderer/          the window: app.js (the main window), list.js (the game lists), sheets.js (holding folder,
                   restore, Review, collections, region priority, LaunchBox match), jobs.js (background jobs and
                   the footer that shows them), bindings.js (your own buttons and keys), the ☰ menu's tool windows
                   (tools.js: scrape, rename; file-tools.js: compress, import; library-tools.js: storage, health
                   check, duplicates; stores.js: NoPayStation, homebrew stores; setup.js: first-run setup;
                   settings.js: settings and help), pad.js (the gamepad and keyboard cursor outside the lists,
                   drop-down lists and the on-screen keyboard), art.js (stand-in box art); the look comes from
                   mockups/electron
helper/helper.py   the Python helper: JSON lines over stdin / stdout, calling lib/ (see its docstring)
helper/rpc.py      its plumbing: @method, events, long jobs with progress and Stop
helper/tool_*.py   each tool window's Python side
helper/*.spec      how PyInstaller bundles the helper (and lib/) for the built app
updates.js         self-updates from GitHub Releases
```

## Running it from a checkout

Needs [Node.js](https://nodejs.org/) 22 and Python 3.9 or newer (no Tk needed).

```sh
cd app
npm install
npm start                 # the helper runs with python3 (RETROSHELF_PYTHON=... to pick another)
npm run smoke             # start, check the window and helper work together, print SMOKE OK, quit
```

## Building it

```sh
python3 -m pip install pyinstaller==6.22.3   # bundles Python and lib/ into the helper
npm run dist                                  # Linux: dist/*.AppImage; Windows: installer + portable .exe
```

Builds are for the system they're made on. CI (`.github/workflows/app.yml`) builds both on every pull request
that touches `app/` or `lib/`, starts each once with `--smoke`, and keeps them as downloads on the run's page.
The Linux build is made on Ubuntu 22.04 so the bundled helper runs on distros that old or newer, including SteamOS.

## Adding something the window can ask Python for

Add a function with `@method` to `helper/helper.py`, or to a `helper/tool_*.py` for a tool window (its keyword arguments are the request's `params`, its return
value the answer, an exception becomes an error the window gets), then call it from the window with
`await window.retroshelf.call("name", {...})`. Keep the work itself in `lib/`, without Tk, so both apps and the tests
can use it; `tests/test_helper.py` shows how to test through the helper.
