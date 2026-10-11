# GUI mock-ups: PySide6 and Electron

Two throwaway mock-ups of RetroShelf's main window, built to compare GUI toolkits before deciding whether to move off
Tk. They show the same screen, sample games (`shared/games.json`) and keys, so the only difference is the toolkit.
Neither is wired to RetroShelf's real code: nothing is scanned, moved or saved, and the box art is generated
placeholders.

What both do:
- The Keeping / Moving lists with richer rows (cover, two lines of text, rating, size), filter chips, search, and a
  details panel with blurred artwork behind it.
- ↑ ↓ move, → (or Delete) moves a game, ← keeps it, Space marks, Enter flips the marked games, Tab switches lists,
  Ctrl+Z or Backspace undoes, `/` searches. A gamepad works too (D-pad, A marks, X flips, Y undoes, LB / RB switch).
- The animations RetroShelf has now, done with each toolkit's own tools: the gliding focus ring, the flipped game
  flying across and glowing where it lands, the other rows sliding into place, rolling counts, the details fading in,
  hover fades, smooth wheel scrolling, the sliding notification.

## Running them

**PySide6** (about 200 MB; a venv keeps it away from the system Python):

```sh
python3 -m venv ~/.venvs/retroshelf-qt
~/.venvs/retroshelf-qt/bin/pip install PySide6
~/.venvs/retroshelf-qt/bin/python mockups/pyside6/mockup.py
```

On Windows: `py -m pip install PySide6`, then `py mockups\pyside6\mockup.py`.

**Electron** (needs [Node.js](https://nodejs.org/); `npm install` downloads Electron, about 100 MB):

```sh
cd mockups/electron
npm install
npm start
```

## What building them showed

- **Electron** got there with the least code (about 570 lines of HTML, CSS and JavaScript). Blur, see-through panels,
  shadows and animations are each a line or two of CSS, and the notification has real frosted glass behind it.
- **PySide6** reached the same look but took more work (about 1,000 lines of Python): list rows are painted by hand,
  Qt's widget effects can't be nested (the cover's shadow is baked into the picture), there's no frosted glass behind
  widgets, and live shadows on big panels are slow, so the lists don't have one. It reuses RetroShelf's own
  `lib/gamepad.py` unchanged, since Qt 6 has no gamepad support; Electron uses the browser's gamepad support instead.

Both were run and filmed on Linux under a virtual display without a graphics card; neither has been tried on Windows
or a Steam Deck yet.
