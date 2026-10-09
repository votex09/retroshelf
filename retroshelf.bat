@echo off
rem Start RetroShelf on Windows. Double-click it, or add it to Steam as a non-Steam game.
rem retroshelf.bat --install-desktop adds RetroShelf to the Start menu.
cd /d "%~dp0"
if "%~1"=="--install-desktop" (python retroshelf.py %* & exit /b)
rem pythonw / pyw open no console window; plain python is the fallback
where pyw >nul 2>nul && (start "" pyw -3 retroshelf.py %* & exit /b)
where pythonw >nul 2>nul && (start "" pythonw retroshelf.py %* & exit /b)
python retroshelf.py %*
