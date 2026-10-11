# PyInstaller recipe for the helper the Electron app runs: npm run helper (from app/).
# One folder, not one file, so it starts fast; RetroShelf's lib/ modules are bundled in.
import os

HERE = os.path.dirname(os.path.abspath(SPEC))
LIB = os.path.join(HERE, "..", "..", "lib")

a = Analysis([os.path.join(HERE, "helper.py")], pathex=[LIB], excludes=["tkinter", "_tkinter"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="retroshelf-helper", console=True,
          upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="retroshelf-helper", upx=False)
