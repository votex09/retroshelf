// Stand-in box art for games ES-DE hasn't scraped: a colour from the name, the system, and the title's initials.
"use strict";

const Art = (() => {
  const cache = new Map();
  const hash = (s) => { let h = 2166136261; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };

  function cover(title, system, w = 170, h = 230) {
    const key = `${title}|${system}|${w}`;
    if (cache.has(key)) return cache.get(key);
    const c = document.createElement("canvas");
    const s = 2; c.width = w * s; c.height = h * s;
    const g = c.getContext("2d"); g.scale(s, s);
    const hv = hash(title), h1 = hv % 360, h2 = (h1 + 40 + (hv >> 9) % 80) % 360;
    const grad = g.createLinearGradient(0, 0, w, h);
    grad.addColorStop(0, `hsl(${h1} 55% 42%)`); grad.addColorStop(1, `hsl(${h2} 60% 18%)`);
    g.fillStyle = grad; g.fillRect(0, 0, w, h);
    g.strokeStyle = "rgba(255,255,255,.07)"; g.lineWidth = w / 14;
    for (let x = -h; x < w; x += w / 5) { g.beginPath(); g.moveTo(x, h); g.lineTo(x + h, 0); g.stroke(); }
    if (w >= 80) {
      g.fillStyle = "rgba(0,0,0,.45)"; g.fillRect(0, 0, w, h * .11);
      g.fillStyle = "rgba(255,255,255,.85)"; g.font = `800 ${h * .06}px sans-serif`; g.textBaseline = "middle";
      g.fillText(system.toUpperCase(), w * .07, h * .056);
    }
    const words = title.replace(/^(The|A) /, "").split(/[\s\-_.:]+/).filter((x) => /^[\p{L}\p{N}]/u.test(x));
    const ini = words.slice(0, 2).map((x) => [...x][0]).join("").toUpperCase() || "?";
    g.fillStyle = "rgba(255,255,255,.92)"; g.font = `800 ${w * .36}px sans-serif`;
    g.textAlign = "center"; g.textBaseline = "middle";
    g.shadowColor = "rgba(0,0,0,.4)"; g.shadowBlur = w / 12; g.fillText(ini, w / 2, h * .56);
    const url = c.toDataURL();
    if (cache.size > 2000) cache.clear();
    cache.set(key, url);
    return url;
  }

  // Pictures and clips on disk, through the app's rsmedia: protocol (main.js only serves files the helper named).
  const media = (path) => `rsmedia://file/${encodeURIComponent(path)}`;

  return { cover, media, hash };
})();
