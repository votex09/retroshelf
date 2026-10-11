// One of the two game lists. Rows are a fixed height and only the ones in view are in the page, so a system with
// thousands of games scrolls as smoothly as one with ten. The ring glides to the selected row.
"use strict";

const ROW = 56, PAD = 6, OVERSCAN = 6;

class GameList {
  // el: the .list element; rowHTML(game) -> inner HTML of a row; onClick(i, event), onOpen(i): mouse
  constructor(el, { rowHTML, onClick, onOpen, empty }) {
    Object.assign(this, { el, rowHTML, onClick, onOpen, emptyText: empty });
    this.spacer = el.querySelector(".spacer");
    this.ring = el.querySelector(".ring");
    this.emptyEl = el.querySelector(".empty");
    this.items = [];
    this.sel = 0;
    this.marked = new Set();
    this.rows = new Map();  // key -> row element in the page
    this.frame = 0;
    el.addEventListener("scroll", () => {
      if (!this.frame) this.frame = requestAnimationFrame(() => { this.frame = 0; this.draw(); });
    });
    new ResizeObserver(() => this.draw()).observe(el);
    el.addEventListener("click", (e) => {
      const row = e.target.closest(".row");
      if (row) this.onClick(Number(row.dataset.i), e);
    });
    el.addEventListener("dblclick", (e) => {
      const row = e.target.closest(".row");
      if (row) this.onOpen(Number(row.dataset.i));
    });
  }

  get current() { return this.items[this.sel]; }
  get page() { return Math.max(1, Math.floor(this.el.clientHeight / ROW) - 1); }
  top(i) { return PAD + i * ROW; }
  indexOf(key) { return this.items.findIndex((g) => g.key === key); }

  // New contents. keepKey: the game to stay on if it's still here (else the nearest place).
  set(items, keepKey) {
    const before = new Map(this.items.map((g, i) => [g.key, i]));
    this.items = items;
    const i = keepKey == null ? -1 : this.indexOf(keepKey);
    this.sel = i >= 0 ? i : Math.max(0, Math.min(this.sel, items.length - 1));
    this.spacer.style.height = `${PAD * 2 + items.length * ROW}px`;
    this.emptyEl.hidden = items.length > 0;
    this.emptyEl.textContent = typeof this.emptyText === "function" ? this.emptyText() : this.emptyText;
    this.draw(true);
    return before;
  }

  // Rows that stayed but shifted glide from where they were (before: key -> old index, from set()).
  slide(before) {
    for (const [key, row] of this.rows) {
      const old = before.get(key), now = Number(row.dataset.i);
      if (old == null || old === now) continue;
      const dy = (old - now) * ROW;
      if (Math.abs(dy) > this.el.clientHeight * 2) continue;
      row.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }], { duration: 260, easing: "cubic-bezier(.2,.8,.2,1)" });
    }
  }

  draw(rebuild = false) {
    const h = this.el.clientHeight, st = this.el.scrollTop;
    const first = Math.max(0, Math.floor((st - PAD) / ROW) - OVERSCAN);
    const last = Math.min(this.items.length - 1, Math.ceil((st + h - PAD) / ROW) + OVERSCAN);
    const want = new Map();
    for (let i = first; i <= last; i++) want.set(this.items[i].key, i);
    for (const [key, row] of this.rows) {
      if (!want.has(key)) { row.remove(); this.rows.delete(key); }
    }
    for (const [key, i] of want) {
      let row = this.rows.get(key);
      if (!row) {
        row = document.createElement("div");
        row.className = "row";
        this.el.appendChild(row);
        this.rows.set(key, row);
      }
      if (!row.html || rebuild) {  // (rebuilt in place, so a row that's animating keeps going)
        const html = this.rowHTML(this.items[i]);
        if (html !== row.html) { row.innerHTML = html; row.html = html; }
      }
      row.dataset.i = i;
      row.style.top = `${this.top(i)}px`;
      row.classList.toggle("selected", i === this.sel);
      row.classList.toggle("marked", this.marked.has(key));
    }
    this.placeRing(false);
  }

  placeRing(animate = true) {
    const has = this.items.length > 0;
    this.ring.classList.toggle("on", has);
    if (!has) return;
    if (!animate) this.ring.style.transition = "none";
    this.ring.style.transform = `translateY(${this.top(this.sel)}px)`;
    if (!animate) { void this.ring.offsetHeight; this.ring.style.transition = ""; }
  }

  select(i, smooth = true) {
    if (!this.items.length) return false;
    i = Math.max(0, Math.min(i, this.items.length - 1));
    const changed = i !== this.sel;
    this.rows.get(this.items[this.sel]?.key)?.classList.remove("selected");
    this.sel = i;
    this.rows.get(this.items[i].key)?.classList.add("selected");
    this.placeRing(true);
    this.reveal(i, smooth);
    return changed;
  }

  reveal(i, smooth = true) {
    const top = this.top(i), h = this.el.clientHeight, st = this.el.scrollTop;
    let to = null;
    if (top < st + PAD) to = top - PAD;
    else if (top + ROW > st + h - PAD) to = top + ROW - h + PAD;
    if (to != null) this.el.scrollTo({ top: to, behavior: smooth && Math.abs(to - st) < h * 2 ? "smooth" : "auto" });
  }

  // Where row i is on screen, scrolled or not.
  rectOf(i) {
    const r = this.el.getBoundingClientRect();
    return { left: r.left + 6, top: r.top + this.top(i) - this.el.scrollTop, width: r.width - 12 - (this.el.offsetWidth - this.el.clientWidth) };
  }

  pulse() { this.ring.classList.remove("pulse"); void this.ring.offsetHeight; this.ring.classList.add("pulse"); }

  refreshMarks() { for (const [key, row] of this.rows) row.classList.toggle("marked", this.marked.has(key)); }
}
