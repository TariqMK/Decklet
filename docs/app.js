// Decklet product page: draws the made-up sample cards, runs the live previews (3D viewer, corners, gallery search, several cards) and links the downloads to the latest release.
"use strict";

const REPO = "TariqMK/Decklet";
const ASSET = { windows: /windows-x64\.exe$/i, macos: /macos-arm64\.zip$/i, linux: /linux-x64\.tar\.gz$/i };
const OS_NAME = { windows: "Windows", macos: "macOS", linux: "Linux" };

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- sample cards (all made up: .example domains, Ofcom drama phone numbers) ---------- */
// design: [style, paper, ink, accent, mark]; serif styles set the name in Cormorant.
const PEOPLE = [
  { folder: "Maya Okafor", name: "Maya Okafor", tags: ["design", "landscape"], notes: "Interested in the courtyard project.",
    cards: [
      { key: "", company: "City Parks Trust", role: "Project designer", email: "m.okafor@cityparks.example", phone: "+44 20 7946 0904", website: "cityparks.example", design: ["plain", "#ffffff", "#2e5d34", "#7aa35a", "CPT"] },
      { key: "Fernhill Landscape Studio", company: "Fernhill Landscape Studio", role: "Landscape architect", email: "maya@fernhill.example", phone: "+44 20 7946 0127", website: "fernhill.example", address: "9 Orchard Yard, London", design: ["leaf", "#f4f1ea", "#2f4a3a", "#2f4a3a", "Fernhill"] },
    ] },
  { folder: "Sam Hollis", name: "Sam Hollis", tags: ["print", "suppliers"], notes: "Quoted for 500 cards on cotton stock.",
    cards: [{ key: "", company: "Hollis Letterpress", role: "Printer", email: "sam@hollispress.example", phone: "+44 113 496 0915", website: "hollispress.example", design: ["square", "#f7f2e8", "#b3362b", "#b3362b", "H"] }] },
  { folder: "Priya Natarajan", name: "Priya Natarajan", tags: ["engineering", "conference"], notes: "",
    cards: [{ key: "", company: "Northlight Optics", role: "Lead optical engineer", email: "priya@northlight.example", phone: "+44 1223 496 077", website: "northlight.example", design: ["lens", "#ffffff", "#1f2f4d", "#1f2f4d", "N"] }] },
  { folder: "Tomás Rivera", name: "Tomás Rivera", tags: ["food", "suppliers"], notes: "Does wholesale sourdough from March.",
    cards: [{ key: "", company: "Rivera & Hale Bakery", role: "Head baker", email: "tomas@riverahale.example", phone: "+44 117 496 0833", address: "7 Quay Street, Bristol", website: "riverahale.example", design: ["stamp", "#e8d6bd", "#3a2616", "#3a2616", "R&H"] }] },
  { folder: "Aiko Tanaka", name: "Aiko Tanaka", tags: ["tea", "suppliers"], notes: "",
    cards: [{ key: "", company: "Kumo Tea House", role: "Owner", email: "aiko@kumotea.example", phone: "+44 161 496 0720", address: "14 Mill Lane, Manchester", website: "kumotea.example", design: ["circles", "#eef1ec", "#24584f", "#24584f", "Kumo"] }] },
  { folder: "Lena Fischer", name: "Lena Fischer", tags: ["legal"], notes: "",
    cards: [{ key: "", company: "Fischer & Moss", role: "Partner, solicitor", email: "l.fischer@fischermoss.example", phone: "+44 20 7946 0581", address: "2 Temple Row, Birmingham", website: "fischermoss.example", design: ["serif", "#fbf8f1", "#6b2234", "#6b2234", "F&M"] }] },
  { folder: "Jonas Weber", name: "Jonas Weber", tags: ["bikes"], notes: "",
    cards: [{ key: "", company: "Weber Cycles", role: "Head mechanic", email: "jonas@webercycles.example", phone: "+44 131 496 0264", website: "webercycles.example", design: ["dark", "#1d1c1b", "#f0ebe1", "#e0703a", "WC"] }] },
  { folder: "Grace Liu", name: "Grace Liu", tags: ["books", "events"], notes: "",
    cards: [{ key: "", company: "Ledger & Lamp Books", role: "Bookseller", email: "grace@ledgerlamp.example", phone: "+44 20 7946 0318", website: "ledgerlamp.example", design: ["plain", "#f6f1e4", "#3b2f1e", "#c4932a", "L&L"] }] },
  { folder: "Daniel Price", name: "Daniel Price", tags: ["sailing"], notes: "",
    cards: [{ key: "", company: "Harbour Sailing School", role: "Senior instructor", email: "dan@harboursailing.example", phone: "+44 117 496 0452", website: "harboursailing.example", design: ["waves", "#ffffff", "#1f5f8b", "#1f5f8b", "HSS"] }] },
];
const person = (folder) => PEOPLE.find((p) => p.folder === folder);
const SERIF = new Set(["serif", "leaf", "stamp"]);

function frontHTML(p, c) {
  const [style, paper, ink, acc, mark] = c.design;
  const lines = [c.company, c.email, c.phone].filter(Boolean).map(esc).join("<br>");
  return `<div class="cf ${style}${SERIF.has(style) ? " serif" : ""}" style="--paper:${paper};--ink:${ink};--acc:${acc}">
    <div class="mk"><i></i>${esc(mark)}</div><div class="nm">${esc(p.name)}</div><div class="rl">${esc(c.role)}</div>
    <div class="ct">${lines}</div><div class="rule"></div></div>`;
}
function backHTML(c) {
  const [style, paper, ink, acc, mark] = c.design;
  const bk = style === "stamp" || style === "dark" ? paper : acc;
  const bi = style === "stamp" ? ink : style === "dark" ? acc : paper;
  return `<div class="cb${SERIF.has(style) ? "" : " sans"}" style="--bk:${bk};--bi:${bi}"><span>${esc(c.company === "Hollis Letterpress" ? "Hollis" : mark)}</span><small>${esc(c.website || "")}</small></div>`;
}

/* ---------- one clock for the scripted previews: once a second, paused while the tab is hidden ---------- */
const ticks = [];
if (!calm) setInterval(() => { if (!document.hidden) ticks.forEach((f) => f()); }, 1000);

/* ---------- hero: the 3D viewer ---------- */
(function hero() {
  const stage = $("#stage"), card = $("#card3d"), floor = $("#floor"), hint = $("#hint"), sideLbl = $("#side-lbl");
  const gf = $("#glare-f"), gb = $("#glare-b"), spinBtn = $('[data-act="spin"]');
  const sam = person("Sam Hollis"), c = sam.cards[0];
  $("#hero-front").insertAdjacentHTML("afterbegin", frontHTML(sam, c));
  $("#hero-back").insertAdjacentHTML("afterbegin", backHTML(c));

  const DRAG = 0.45, FRICTION = 0.95, SPIN = 0.3;
  let rx = -6, ry = 14, vx = 0, vy = 0, tween = null, dragging = false, spin = false;
  let lastX = 0, lastY = 0, idleUntil = 0, running = false, inView = true, swayT = 0;

  function size() {
    const w = Math.round(Math.min(stage.clientWidth * 0.66, 460, (stage.clientHeight - 170) * 1.75));
    const h = Math.round(w / 1.75);
    card.style.setProperty("--w", w + "px"); card.style.setProperty("--h", h + "px");
    card.style.setProperty("--t", "3px"); card.style.setProperty("--r", Math.round(w * 0.022) + "px");
    floor.style.setProperty("--w", w + "px"); floor.style.setProperty("--h", h + "px");
  }
  function apply() {
    card.style.transform = `rotateX(${rx}deg) rotateY(${ry}deg)`;
    const d = Math.PI / 180, gx = 50 - Math.sin(ry * d) * 75, gy = 35 + Math.sin(rx * d) * 75;
    gf.style.setProperty("--gx", gx + "%"); gf.style.setProperty("--gy", gy + "%");
    gb.style.setProperty("--gx", 100 - gx + "%"); gb.style.setProperty("--gy", gy + "%");
    sideLbl.textContent = Math.cos(rx * d) * Math.cos(ry * d) >= 0 ? "front" : "back";
    floor.style.transform = `translateX(-50%) scale(${0.3 + 0.7 * Math.abs(Math.cos(ry * d))}, 1)`;
    floor.style.opacity = 0.4 + 0.6 * Math.abs(Math.cos(rx * d));
  }
  const auto = () => !calm && !spin && !dragging && performance.now() > idleUntil;
  function frame() {
    if (tween) {
      rx += (tween.rx - rx) * 0.12; ry += (tween.ry - ry) * 0.12;
      if (Math.abs(tween.rx - rx) < 0.05 && Math.abs(tween.ry - ry) < 0.05) { rx = tween.rx; ry = tween.ry; tween = null; }
    } else if (!dragging) {
      rx += vx; ry += vy; vx *= FRICTION; vy *= FRICTION;
      if (spin && Math.abs(vx) < 0.05 && Math.abs(vy) < 0.05) ry += SPIN;
      if (auto() && Math.abs(vy) < 0.05) { swayT += 0.008; ry += Math.cos(swayT) * 0.06; rx = rx * 0.98 + (-6 + Math.sin(swayT * 0.7) * 3) * 0.02; }
    }
    apply();
    const busy = tween || dragging || spin || Math.abs(vx) > 0.01 || Math.abs(vy) > 0.01 || (auto() && inView);
    if (busy && !document.hidden) requestAnimationFrame(frame); else running = false;
  }
  const kick = () => { if (!running) { running = true; requestAnimationFrame(frame); } };
  const touch = () => { idleUntil = performance.now() + 8000; hint.style.opacity = 0; };

  const snap = (n, step) => Math.round(n / step) * step;
  const act = {
    front: () => { tween = { rx: snap(rx, 360), ry: snap(ry, 360) }; },
    back: () => { tween = { rx: snap(rx, 360), ry: snap(ry - 180, 360) + 180 }; },
    flip: () => { tween = { rx: snap(rx, 360), ry: snap(ry, 180) + 180 }; },
    reset: () => { tween = { rx: snap(rx, 360), ry: snap(ry, 360) }; spin = false; spinBtn.setAttribute("aria-pressed", "false"); },
    spin: () => { spin = !spin; spinBtn.setAttribute("aria-pressed", String(spin)); },
  };
  const run = (name) => { touch(); vx = vy = 0; act[name](); kick(); };
  $$(".hbtn").forEach((b) => b.addEventListener("click", () => run(b.dataset.act)));

  stage.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button")) return;
    dragging = true; tween = null; vx = vy = 0; lastX = e.clientX; lastY = e.clientY;
    stage.setPointerCapture(e.pointerId); stage.classList.add("dragging"); touch(); kick();
  });
  stage.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const dx = e.clientX - lastX, dy = e.clientY - lastY; lastX = e.clientX; lastY = e.clientY;
    const sign = Math.cos(rx * Math.PI / 180) >= 0 ? 1 : -1;
    vy = dx * DRAG * sign; vx = -dy * DRAG; ry += vy; rx += vx;
  });
  const end = () => { dragging = false; stage.classList.remove("dragging"); touch(); };
  stage.addEventListener("pointerup", end); stage.addEventListener("pointercancel", end);
  stage.addEventListener("dblclick", (e) => { if (!e.target.closest("button")) run("flip"); });
  document.addEventListener("keydown", (e) => {
    if (!inView || e.metaKey || e.ctrlKey || e.altKey || e.target.closest("input, textarea")) return;
    const k = e.key.toLowerCase();
    if (k === "f") run("flip"); else if (k === "r") run("reset");
  });

  // Scripted story while nobody is touching it: turn the card over every few seconds.
  let n = 0;
  ticks.push(() => { if (inView && auto() && ++n % 6 === 0) { act.flip(); kick(); } });
  new IntersectionObserver(([en]) => { inView = en.isIntersecting; if (inView) kick(); }).observe(stage);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) kick(); });

  size(); apply();
  addEventListener("resize", size);
  if (!calm) kick();
})();

/* ---------- corners: handles find the card in each photo, both sides come out the same size ---------- */
(function corners() {
  const rivera = person("Tomás Rivera"), c = rivera.cards[0];
  // Card corners in each photo, as % of the photo (TL, TR, BL; BR follows). The two photos are framed differently.
  const PHOTOS = {
    front: { tl: [20, 27], tr: [79, 17], bl: [23, 76], html: frontHTML(rivera, c) },
    back: { tl: [30, 31], tr: [73, 38], bl: [27, 68], html: backHTML(c) },
  };
  const START = [[6, 8], [94, 8], [94, 92], [6, 92]]; // where the handles start: the edge of the photo
  const BW = 400, BH = BW / 1.75;
  const boxes = [];

  for (const el of $$("#corners [data-photo]")) {
    const ph = PHOTOS[el.dataset.photo];
    const br = [ph.tr[0] + ph.bl[0] - ph.tl[0], ph.tr[1] + ph.bl[1] - ph.tl[1]];
    const target = [ph.tl, ph.tr, br, ph.bl];
    el.innerHTML = `<div class="desk"></div><div class="pc">${ph.html}</div>
      <svg preserveAspectRatio="none"><polygon/><line/></svg>
      <span class="h tl"></span><span class="h"></span><span class="h"></span><span class="h"></span>`;
    const pc = $(".pc", el);
    pc.style.width = BW + "px"; pc.style.height = BH + "px";
    boxes.push({ el, ph, target, pc, poly: $("polygon", el), line: $("line", el), hs: $$(".h", el), svg: $("svg", el), now: START.map((p) => p.slice()) });
  }

  function place(b) {
    const W = b.el.clientWidth, H = b.el.clientHeight, px = ([x, y]) => [x / 100 * W, y / 100 * H];
    const [tl, tr, , bl] = b.target.map(px);
    b.pc.style.transform = `matrix(${(tr[0] - tl[0]) / BW},${(tr[1] - tl[1]) / BW},${(bl[0] - tl[0]) / BH},${(bl[1] - tl[1]) / BH},${tl[0]},${tl[1]})`;
    b.svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const pts = b.now.map(px);
    b.poly.setAttribute("points", pts.map((p) => p.join(",")).join(" "));
    b.line.setAttribute("x1", pts[0][0]); b.line.setAttribute("y1", pts[0][1]);
    b.line.setAttribute("x2", pts[1][0]); b.line.setAttribute("y2", pts[1][1]);
    b.hs.forEach((h, i) => { h.style.transform = `translate(${pts[i][0]}px, ${pts[i][1]}px)`; });
  }
  const ease = (t) => 1 - Math.pow(1 - t, 3);
  function glide(b, from, to, ms) {
    const t0 = performance.now();
    (function step(t) {
      const k = ease(Math.min(1, (t - t0) / ms));
      b.now = from.map((p, i) => [p[0] + (to[i][0] - p[0]) * k, p[1] + (to[i][1] - p[1]) * k]);
      place(b);
      if (k < 1) requestAnimationFrame(step);
    })(t0);
  }

  // The straightened result: both faces the same size, turning over.
  $("#r-front").innerHTML = frontHTML(rivera, c);
  $("#r-back").innerHTML = backHTML(c);
  const rcard = $("#rcard"), rside = $("#result-side");
  const showSide = (back) => { rcard.classList.toggle("flipped", back); rside.textContent = back ? "back" : "front"; };

  if (calm) { boxes.forEach((b) => { b.now = b.target.map((p) => p.slice()); place(b); }); }
  else { boxes.forEach(place); }
  addEventListener("resize", () => boxes.forEach(place));

  // 10 s loop: handles start at the photo edge, find the card (front, then back), then the result turns over.
  let s = 0, seen = false;
  new IntersectionObserver(([en]) => { seen = en.isIntersecting; }, { threshold: 0.3 }).observe($("#corners"));
  ticks.push(() => {
    if (!seen && s === 0) return;
    s = (s + 1) % 10;
    if (s === 1) glide(boxes[0], boxes[0].now, boxes[0].target, 900);
    if (s === 2) glide(boxes[1], boxes[1].now, boxes[1].target, 900);
    if (s === 4) showSide(true);
    if (s === 7) showSide(false);
    if (s === 9) boxes.forEach((b) => glide(b, b.now, START, 700));
  });
})();

/* ---------- gallery: one tile per person, newest card first, live search ---------- */
(function gallery() {
  const grid = $("#ggrid"), input = $("#gsearch"), count = $("#gcount");
  const total = PEOPLE.reduce((n, p) => n + p.cards.length, 0);
  const people = (n) => (n === 1 ? "1 person" : `${n} people`);
  const hay = (p) => [p.name, p.notes, ...p.tags, ...p.cards.flatMap((c) => [c.company, c.role, c.email, c.website, c.address])].join(" ").toLowerCase();
  let cols = 3, shown = "";

  function layout() {
    cols = matchMedia("(max-width:760px)").matches ? 2 : 3;
    const W = grid.clientWidth, tw = (W - 14 * (cols - 1)) / cols;
    grid.style.height = Math.ceil(2 * (tw / 1.75 + 8 + 32) + 18) + "px"; // exactly two rows of tiles
    render();
  }
  function render() {
    const q = input.value.trim().toLowerCase();
    const view = PEOPLE.filter((p) => !q || hay(p).includes(q));
    count.textContent = view.length === PEOPLE.length ? `${people(PEOPLE.length)} · ${total} cards` : `${view.length} of ${people(PEOPLE.length)}`;
    const sig = (view.length ? view.map((p) => p.folder).join("|") : "none:" + q) + "#" + cols;
    if (sig === shown) return; // same tiles: keep them, so they don't fade in again
    shown = sig;
    grid.innerHTML = view.length ? view.slice(0, cols * 2).map((p) => {
      const c = p.cards[p.cards.length - 1];
      return `<div class="gt"><div class="thumb">${frontHTML(p, c)}</div><div class="n">${esc(p.name)}</div><div class="c">${esc(c.company)}</div></div>`;
    }).join("") : `<div class="gempty">No cards match “${esc(input.value.trim())}”.</div>`;
  }
  input.addEventListener("input", render);
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !e.target.closest("input, textarea")) {
      const r = grid.getBoundingClientRect();
      if (r.top < innerHeight && r.bottom > 0) { e.preventDefault(); input.focus(); }
    }
  });

  // Scripted typing while the visitor isn't using the box.
  const QUERIES = ["suppliers", "tea", "design"];
  let qi = 0, step = 0, hold = 0, mine = false, seen = false;
  input.addEventListener("focus", () => { mine = true; });
  input.addEventListener("blur", () => { if (!input.value) setTimeout(() => { mine = false; step = 0; hold = 2; }, 6000); });
  new IntersectionObserver(([en]) => { seen = en.isIntersecting; }).observe(grid);
  ticks.push(() => {
    if (mine || !seen) return;
    if (hold > 0) { hold--; return; }
    const q = QUERIES[qi];
    if (step < q.length) { step = Math.min(q.length, step + 3); input.value = q.slice(0, step); render(); if (step === q.length) hold = 3; }
    else { input.value = ""; render(); step = 0; hold = 2; qi = (qi + 1) % QUERIES.length; }
  });

  addEventListener("resize", layout);
  layout();
})();

/* ---------- several cards for one person ---------- */
(function multi() {
  const maya = person("Maya Okafor");
  const thumb = $("#mthumb");
  thumb.innerHTML = maya.cards.map((c, i) => `<div class="layer" style="opacity:${i === 1 ? 1 : 0}">${frontHTML(maya, c)}</div>`).join("");
  const layers = $$(".layer", thumb);
  const els = ["m-of", "m-co", "m-role", "m-email", "m-path"].map((id) => document.getElementById(id));
  els.forEach((e) => e.classList.add("fade"));
  let cur = 1;

  function show(i) {
    cur = (i + maya.cards.length) % maya.cards.length;
    const c = maya.cards[cur];
    layers.forEach((l, k) => { l.style.opacity = k === cur ? 1 : 0; });
    els.forEach((e) => e.classList.add("out"));
    setTimeout(() => {
      const [of, co, role, email, path] = els;
      of.textContent = `Card ${cur + 1} of ${maya.cards.length}`;
      co.textContent = c.company; role.textContent = c.role; email.textContent = c.email;
      path.textContent = c.key ? `${maya.folder} / ${c.key} /` : `${maya.folder} /`;
      els.forEach((e) => e.classList.remove("out"));
    }, calm ? 0 : 250);
  }
  let pausedUntil = 0, n = 0;
  $$("#multi .sbtn").forEach((b) => b.addEventListener("click", () => { pausedUntil = Date.now() + 10000; show(cur + Number(b.dataset.dir)); }));
  ticks.push(() => { if (Date.now() > pausedUntil && ++n % 4 === 0) show(cur + 1); });
})();

/* ---------- downloads ---------- */
function detectOS() {
  const platform = (navigator.userAgentData?.platform || navigator.platform || "").toLowerCase();
  const ua = navigator.userAgent.toLowerCase();
  if (/android|iphone|ipad|ipod/.test(ua)) return null; // Phones and tablets get no direct download.
  if (platform.includes("win")) return "windows";
  if (platform.includes("mac")) return "macos";
  if (platform.includes("linux")) return "linux";
  return null;
}

async function wireDownloads() {
  const os = detectOS();
  const hero = document.getElementById("hero-download");
  if (os) {
    hero.textContent = `Download for ${OS_NAME[os]}`;
    document.querySelector(`.platform[data-os="${os}"]`)?.classList.add("detected");
  }
  try {
    const res = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`,
      { headers: { Accept: "application/vnd.github+json" } });
    if (!res.ok) return;
    const rel = await res.json();
    for (const [key, pattern] of Object.entries(ASSET)) {
      const asset = rel.assets?.find((a) => pattern.test(a.name));
      if (!asset) continue;
      const card = document.querySelector(`.platform[data-os="${key}"]`);
      card.querySelector(".get").href = asset.browser_download_url;
      const size = card.querySelector(".size");
      size.textContent = `${size.textContent} · ${(asset.size / 1048576).toFixed(0)} MB`;
      if (key === os) hero.href = asset.browser_download_url;
    }
    const date = new Date(rel.published_at).toLocaleDateString("en-GB",
      { day: "numeric", month: "short", year: "numeric" });
    document.getElementById("dl-version").textContent = `${rel.tag_name} · released ${date}`;
    document.getElementById("hero-meta").textContent = `${rel.tag_name} · Free · Offline · No tracking · Windows, macOS, Linux`;
  } catch {
    // Offline, rate-limited (60 requests an hour) or no release yet: change nothing.
  }
}
wireDownloads();
