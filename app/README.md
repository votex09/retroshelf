# RetroShelf's new app (Electron, in progress)

RetroShelf is moving from Tk to Electron (the plan: Electron draws the windows, RetroShelf's Python code keeps doing
the work). This folder is that app. It doesn't do much yet: it finds your ROMs folder and lists its systems. The
Tk app (`retroshelf.py`) is still the one that's released, until this one can do everything it does.

```
main.js            the app: opens the window, runs the helper, answers the window's requests
helper.js          runs the Python helper and matches its answers to requests
preload.js         what the window is allowed to ask for (window.retroshelf)
renderer/          the window: HTML, CSS, JavaScript; the look comes from mockups/electron
helper/helper.py   the Python helper: JSON lines over stdin / stdout, calling lib/ (see its docstring)
helper/*.spec      how PyInstaller bundles the helper (and lib/) for the built app
updates.js         self-updates from GitHub Releases; off until this app is the one released
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

Add a function with `@method` to `helper/helper.py` (its keyword arguments are the request's `params`, its return
value the answer, an exception becomes an error the window gets), then call it from the window with
`await window.retroshelf.call("name", {...})`. Keep the work itself in `lib/`, without Tk, so both apps and the tests
can use it; `tests/test_helper.py` shows how to test through the helper.
