// Updates through electron-updater and GitHub Releases. Off until the switch-over (phase 4 of the Electron plan):
// releases carry the Tk zip until then, with no update feed for this app. RETROSHELF_UPDATES=1 turns it on to try.
const LIVE = false;

function checkForUpdates(app, log = console.log) {
  if (!app.isPackaged || !(LIVE || process.env.RETROSHELF_UPDATES === "1")) return;
  if (process.platform === "linux" && !process.env.APPIMAGE) return;  // only the AppImage can replace itself
  try {
    const { autoUpdater } = require("electron-updater");
    autoUpdater.on("error", (e) => log(`Update check failed: ${e.message}`));
    autoUpdater.checkForUpdatesAndNotify();
  } catch (e) {
    log(`Update check failed: ${e.message}`);
  }
}

module.exports = { checkForUpdates };
