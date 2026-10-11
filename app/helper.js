// Runs RetroShelf's Python helper (helper/helper.py) and talks to it: call() sends a request and resolves with
// its answer; "event" fires for messages the helper sends on its own; "exit" if it stops.
// Packaged builds carry the helper as a bundled program (PyInstaller) in resources/helper/; from a checkout it
// runs with the Python on the PATH (RETROSHELF_PYTHON overrides).
const { spawn } = require("child_process");
const { EventEmitter } = require("events");
const path = require("path");
const readline = require("readline");

function helperCommand(app) {
  if (app.isPackaged) {
    const exe = process.platform === "win32" ? "retroshelf-helper.exe" : "retroshelf-helper";
    return [path.join(process.resourcesPath, "helper", exe), []];
  }
  const python = process.env.RETROSHELF_PYTHON || (process.platform === "win32" ? "python" : "python3");
  return [python, [path.join(__dirname, "helper", "helper.py")]];
}

class Helper extends EventEmitter {
  constructor(app) {
    super();
    this.app = app;
    this.nextId = 1;
    this.pending = new Map();
    this.stderr = [];
    this.ready = null;
  }

  start() {
    const [cmd, args] = helperCommand(this.app);
    this.proc = spawn(cmd, args, { stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
      env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8",
        RETROSHELF_DATA: process.env.RETROSHELF_DATA || this.app.getPath("userData") } });
    this.ready = new Promise((resolve, reject) => {
      this.once("event:ready", resolve);
      this.once("exit", (info) => reject(new Error(`The helper stopped before it was ready: ${info.stderr}`)));
    });
    readline.createInterface({ input: this.proc.stdout }).on("line", (line) => this.onLine(line));
    readline.createInterface({ input: this.proc.stderr }).on("line", (line) => {
      this.stderr.push(line);
      if (this.stderr.length > 40) this.stderr.shift();
      if (!this.app.isPackaged) console.error(`[helper] ${line}`);
    });
    const stopped = (code, error) => {
      if (this.stopped) return;
      this.stopped = true;
      const info = { code, error: error && error.message, stderr: this.stderr.join("\n") };
      for (const { reject } of this.pending.values()) reject(new Error("The helper stopped"));
      this.pending.clear();
      this.emit("exit", info);
    };
    this.proc.on("error", (e) => stopped(null, e));
    this.proc.on("exit", (code) => stopped(code));
    return this.ready;
  }

  onLine(line) {
    let msg;
    try { msg = JSON.parse(line); } catch { return; }
    if (msg.event) {
      this.emit(`event:${msg.event}`, msg.data);
      this.emit("event", msg.event, msg.data);
      return;
    }
    const waiting = this.pending.get(msg.id);
    if (!waiting) return;
    this.pending.delete(msg.id);
    if (msg.error) {
      const e = new Error(msg.error.message);
      e.type = msg.error.type;
      waiting.reject(e);
    } else {
      waiting.resolve(msg.result);
    }
  }

  call(method, params = {}) {
    if (this.stopped) return Promise.reject(new Error("The helper isn't running"));
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.proc.stdin.write(JSON.stringify({ id, method, params }) + "\n");
    });
  }

  stop() {
    if (this.proc && !this.stopped) this.proc.stdin.end();  // the helper finishes what it was asked, then exits
  }
}

module.exports = { Helper };
