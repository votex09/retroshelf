// Long jobs (importing, copying from a source, compressing, scraping …) go on in the background while you use the
// rest of the app: one at a time, the rest waiting their turn. The main window's footer (#bg-job) shows the one
// running and how many wait; clicking it opens that job's window again, which picks the job back up (bgFind).
// Closing RetroShelf while one runs asks first. (Uses app.js: runJob, toast, overlay …)
"use strict";

const JOBS = { cur: null, queue: [], quitAfter: false };

// A job: { kind, label: what the footer says until progress comes, window: the window it opens ("Compress games"),
//   open(): opens it, method, params, progress(p): every progress event, finish(r): when it's done (also with the
//   window closed), stopNote: what stopping it on quitting loses }.
// -> the entry: done (a promise of the answer), stop(), and while it's going message / count / total; set view(p) to
// hear its progress while a window shows it. A job stopped before its turn rejects with e.cancelled.
function bgRun(job) {
  const e = { ...job, message: "", done: null, count: 0, total: 0, view: null, job: null, started: false };
  e.done = new Promise((resolve, reject) => { e.resolve = resolve; e.reject = reject; });
  e.stop = () => {
    if (e.job) { e.job.stop(); return; }
    JOBS.queue = JOBS.queue.filter((x) => x !== e);
    const err = new Error("Stopped before it started"); err.cancelled = true;
    e.reject(err);
    bgShow();
  };
  e.done.catch(() => {});  // (whoever follows it hears the failure; nobody has to)
  JOBS.queue.push(e);
  if (JOBS.cur) e.message = `Waiting for ${JOBS.cur.label.replace(/ …$/, "")} to finish …`;
  bgNext();
  bgShow();
  return e;
}

// The running or waiting job of this kind (a window opening again picks it up), or null.
const bgFind = (kind) => [JOBS.cur, ...JOBS.queue].find((e) => e?.kind === kind) || null;

function bgNext() {
  if (JOBS.cur) return;
  const e = JOBS.queue.shift();
  if (!e) {
    if (JOBS.quitAfter) rs.quit();
    return;
  }
  JOBS.cur = e;
  e.started = true;
  e.message = "";
  e.job = runJob(e.method, e.params, (p) => {
    if (p.message) e.message = p.message;
    if (p.total) { e.count = p.done; e.total = p.total; }
    e.progress?.(p);
    bgShow();
    e.view?.(p);
  });
  e.view?.({ message: e.label });
  e.job.done.then(async (r) => {
    bgDone(e);
    e.resolve(r);
    if (!JOBS.quitAfter) await e.finish?.(r);
  }, (err) => {
    bgDone(e);
    e.reject(err);
    if (!e.view && !JOBS.quitAfter) toast(`${e.window}: ${err.message}`, { error: true });
  }).catch(oops);
}
function bgDone(e) {
  if (JOBS.cur === e) JOBS.cur = null;
  bgShow();
  setTimeout(bgNext, 0);  // (after the one that finished has had its say)
}

function bgShow() {
  const b = $("bg-job"), e = JOBS.cur || JOBS.queue[0];
  b.hidden = !e;
  rs.setBusy(Boolean(e));
  if (!e) return;
  const waiting = JOBS.queue.length - (JOBS.cur ? 0 : 1);
  const text = (JOBS.quitAfter ? "Quits when done · " : "") + (e.message || e.label) +
    (waiting ? `  ·  ${waiting} more waiting` : "");
  b.querySelector(".bg-text").textContent = text;
  b.title = `${text}\nOpen ${e.window}`;
  b.querySelector(".progress-bar > span").style.width = `${e.total ? (100 * e.count) / e.total : 0}%`;
}
$("bg-job").onclick = () => {
  const e = JOBS.cur || JOBS.queue[0];
  if (e) Promise.resolve().then(e.open).catch(oops);
};

// Closing the window while one works: keep going, quit once everything's done, or stop (losing only what's half done).
rs.onCloseAsked(() => {
  const e = JOBS.cur;
  if (!e && !JOBS.queue.length) { rs.quit(); return; }  // (nothing going: never stuck open)
  const waiting = JOBS.queue.length;
  overlay(`<h2>${esc(e ? `${e.window} is still going` : "Jobs are waiting their turn")}</h2>
    ${e?.message ? `<p>${esc(e.message)}</p>` : ""}
    <p class="lines">${esc([e?.stopNote, waiting ? `${plural(waiting, "job")} waiting won't run.` : ""].filter(Boolean).join(" "))}</p>`, [
    ["Keep going", closeOverlay],
    ["Quit when it's done", () => { closeOverlay(); JOBS.quitAfter = true; bgShow(); toast("RetroShelf closes when it's done"); }, true],
    ["Stop and quit", () => {
      closeOverlay();
      JOBS.quitAfter = true;
      for (const q of [...JOBS.queue]) q.stop();
      if (JOBS.cur) JOBS.cur.stop(); else rs.quit();
      bgShow();
    }],
  ]);
  overlayCancel = closeOverlay;
});
