// Protocol-aware study frontend. Walks the counterbalanced trial list;
// GUI trials are interactive, tangible trials are a read-only display that
// polls state while the server-managed ArUco tracker drives the same ops.
import WaveSurfer from "/static/vendor/wavesurfer.esm.js";
import RegionsPlugin from "/static/vendor/regions.esm.js";

const COLORS = { S1: "#e63946", S2: "#457b9d", S3: "#2a9d8f" };
const rgba = (hex, a) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`;
};
const SIL = "SIL";  // non-speech: neutral, not a reassignable speaker
const colorFor = (spk) => (spk === SIL ? "rgba(120,120,120,0.13)" : rgba(COLORS[spk], 0.28));
const labelFor = (spk) => (spk === SIL ? "" : spk);

// per-condition copy, so a student always knows exactly what to do
const COND = {
  gui: {
    icon: "🖱️", title: "Mouse",
    sub: "Correct the labels with the mouse.",
    steps: [
      "<b>Click</b> a coloured block to change who is speaking.",
      "<b>Drag the edge</b> between two blocks to move where one speaker stops and the next begins.",
      "Press <b>Space</b> (or ▶ Play) to listen back.",
      "Press <b>Ctrl+Z</b> to undo your last change.",
    ],
  },
  tangible: {
    icon: "✋", title: "Physical tokens",
    sub: "Correct the labels with the tokens on the sheet. Use the mouse only for the player.",
    steps: [
      "<b>Place a speaker token</b> (S1 / S2 / S3) on a block to set who is speaking.",
      "<b>Put the boundary handle</b> on a block and slide to move its nearer edge.",
      "<b>Hold each token still</b> a moment so the camera registers it; lift it off to release.",
      "Listen with the <b>▶ on-screen player</b>; press <b>Ctrl+Z</b> to undo.",
    ],
  },
};

let ws, regions, segments = [], speakers = [], clip = "";
let mode = "gui", running = false, t0 = 0, timerId = null, pollId = null, lastVersion = 0;
let seeking = false, lastPv = -1, isLast = false;
const byId = new Map();
const $ = (id) => document.getElementById(id);
const show = (id, on) => ($(id).hidden = !on);
const setStatus = (m) => ($("status").textContent = m);
const fmt = (s) => `${(s / 60) | 0}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function updateTime(cur) {
  const d = (ws && ws.getDuration()) || 0;
  if (!seeking) $("seek").value = d ? String(Math.round((cur / d) * 1000)) : "0";
  $("time").textContent = `${fmt(cur || 0)} / ${fmt(d)}`;
}

async function api(path, body) {
  const r = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.status);
  return j;
}

function legend() {
  $("legend").innerHTML = speakers.map(
    (s) => `<span class="chip"><span class="swatch" style="background:${COLORS[s]}"></span>${s}</span>`
  ).join("") +
    `<span class="chip"><span class="swatch" style="background:rgba(120,120,120,0.35)"></span>silence</span>`;
}

// A 0-60s time ruler under the waveform. Fixed whole-clip scale (no zoom),
// so a tick at time t sits at (t/duration)% across. Shared by both conditions.
function buildRuler() {
  const el = $("ruler");
  el.innerHTML = "";
  const d = (ws && ws.getDuration()) || 0;
  if (!d) return;
  const last = Math.round(d);
  for (let t = 0; t <= last; t += 1) {              // 1 s minor ticks, label every 5 s
    const pct = (t / d) * 100;
    const major = t % 5 === 0;
    const tick = document.createElement("div");
    tick.className = "tick" + (major ? " major" : "");
    tick.style.left = pct + "%";
    el.appendChild(tick);
    if (major) {
      const lab = document.createElement("span");
      lab.className = "ticklabel" + (t === 0 ? " first" : t + 5 > last ? " last" : "");
      lab.style.left = pct + "%";
      lab.textContent = fmt(t);
      el.appendChild(lab);
    }
  }
}

// ---- live "what am I pointing at" cue overlay (matched GUI + tangible) ----
const pct = (t) => { const d = (ws && ws.getDuration()) || 0; return d ? (t / d) * 100 : 0; };
const segById = (id) => segments.find((s) => s.id === id);
const segmentAt = (t) => segments.find((s) => s.start <= t && t < s.end);

// cue: {t, seg:id|null, bnd:index|null, spk:name|null, progress:0..1|null}
function renderCues(cues) {
  const ov = $("overlay");
  ov.innerHTML = "";
  if (!((ws && ws.getDuration()) || 0)) return;
  const add = (cls, left, extra) => {
    const e = document.createElement("div");
    e.className = cls; e.style.left = left + "%";
    if (extra) extra(e); ov.appendChild(e); return e;
  };
  cues.forEach((c) => {
    if (c.t == null) return;
    const onTarget = c.seg != null || c.bnd != null;
    if (c.seg != null) {                          // target-segment highlight
      const s = segById(c.seg);
      if (s) add("ov-hl" + (c.spk ? " tinted" : ""), pct(s.start), (e) => {
        e.style.width = (pct(s.end) - pct(s.start)) + "%";
        if (c.spk) e.style.setProperty("--tint", COLORS[c.spk] || "#888");
      });
    }
    if (c.bnd != null) {                          // boundary edge + ghost target
      const seg = segments[c.bnd];
      if (seg) add("ov-edge", pct(seg.end));
      add("ov-ghost", pct(c.t));
    }
    add("ov-cursor" + (onTarget ? "" : " off"), pct(c.t));
    add("ov-time", pct(c.t), (e) => { e.textContent = onTarget ? fmt(c.t) : "no target"; });
    if (c.progress != null && c.progress > 0.01)  // dwell ring (tangible)
      add("ov-ring", pct(c.t), (e) => e.style.setProperty("--p", c.progress));
  });
}
const clearCues = () => ($("overlay").innerHTML = "");

function guiHover(ev) {                            // GUI: mouse is the pointer
  if (!running || mode !== "gui") return;
  const r = $("overlay").parentElement.getBoundingClientRect();
  const d = (ws && ws.getDuration()) || 0;
  if (!d) return;
  const t = Math.max(0, Math.min(d, ((ev.clientX - r.left) / r.width) * d));
  const s = segmentAt(t);
  renderCues([{ t, seg: s ? s.id : null, bnd: null, spk: null, progress: null }]);
}

function buildRegions() {
  regions.clearRegions();
  byId.clear();
  const interactive = mode === "gui";
  segments.forEach((seg, idx) => {
    const r = regions.addRegion({
      id: String(seg.id), start: seg.start, end: seg.end,
      content: labelFor(seg.speaker), color: colorFor(seg.speaker),
      drag: false, resize: interactive,
      resizeStart: interactive && idx > 0,
      resizeEnd: interactive && idx < segments.length - 1,
    });
    r._spk = seg.speaker;
    byId.set(seg.id, r);
  });
}

function flash(r) {                                // brief pulse on a changed segment
  const el = r && r.element;
  if (!el) return;
  el.classList.remove("ws-flash"); void el.offsetWidth; el.classList.add("ws-flash");
}

function reconcile(newSegs) {
  segments = newSegs;
  segments.forEach((seg) => {
    const r = byId.get(seg.id);
    if (!r) return;
    const moved = Math.abs(r.start - seg.start) > 1e-4 || Math.abs(r.end - seg.end) > 1e-4;
    if (moved) r.setOptions({ start: seg.start, end: seg.end });
    const recolored = r._spk !== seg.speaker;
    if (recolored) {
      r._spk = seg.speaker;
      r.setOptions({ content: labelFor(seg.speaker), color: colorFor(seg.speaker) });
    }
    if (moved || recolored) flash(r);
  });
}

async function onReassign(region) {
  if (!running || mode !== "gui") return;
  const sid = Number(region.id);
  const cur = segments[sid].speaker;
  if (cur === SIL) return;                        // silence is not reassignable
  const next = speakers[(speakers.indexOf(cur) + 1) % speakers.length];
  try {
    const res = await api("/api/op", { op: "reassign", segment: sid, speaker: next, source: "mouse" });
    reconcile(res.segments);
  } catch (e) { setStatus("op error: " + e.message); }
}

async function onBoundary(region, side) {
  if (!running || mode !== "gui" || !side) return;
  const sid = Number(region.id);
  const boundary = side === "end" ? sid : sid - 1;
  const t = side === "end" ? region.end : region.start;
  if (boundary < 0 || boundary >= segments.length - 1) return;
  try {
    const res = await api("/api/op", { op: "move_boundary", boundary, t, source: "mouse" });
    reconcile(res.segments);
  } catch (e) { setStatus("op error: " + e.message); }
}

function initWave() {
  if (ws) ws.destroy();
  ws = WaveSurfer.create({
    container: "#wave", url: `/stimuli/${clip}/audio.wav`, height: 120,
    waveColor: "#c9c9c9", progressColor: "#9aa", cursorColor: "#333",
    fillParent: true, autoScroll: false, hideScrollbar: true, // fixed scale, no zoom
  });
  regions = ws.registerPlugin(RegionsPlugin.create());
  ws.on("decode", buildRegions);
  ws.on("decode", buildRuler);
  regions.on("region-clicked", (r, e) => { e.stopPropagation(); onReassign(r); });
  regions.on("region-updated", (r, side) => onBoundary(r, side));
  // transport
  $("play").textContent = "▶ Play";
  ws.on("decode", () => updateTime(0));
  ws.on("timeupdate", updateTime);
  ws.on("play", () => { $("play").textContent = "⏸ Pause"; pb("play", ws.getCurrentTime()); });
  ws.on("pause", () => { $("play").textContent = "▶ Play"; pb("pause", ws.getCurrentTime()); });
}

// log a playback event so analysis can subtract navigation from total time.
// Playback is mouse-driven in BOTH conditions now, so log it in both.
function pb(event, media_t) {
  if (!running) return;
  fetch("/api/playback", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event, media_t, source: "mouse" }),
  }).catch(() => {});
}

function tick() {
  const s = Math.floor((Date.now() - t0) / 1000);
  $("timer").textContent =
    String((s / 60) | 0).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
}

// tangible: reflect tracker edits + playback, and show the live camera dot
function trackPill(tk) {
  const el = $("trackpill");
  if (mode !== "tangible" || !tk) { el.hidden = true; return; }
  el.hidden = false;
  const map = {
    tracking:  ["ok",       `● Camera on — ${tk.tokens} token${tk.tokens === 1 ? "" : "s"} visible`],
    no_sheet:  ["bad",      "⚠ Point the camera at the whole sheet"],
    starting:  ["starting", "◍ Starting camera…"],
    off:       ["starting", "◍ Starting camera…"],
    error:     ["bad",      "⚠ Camera problem — ask the researcher"],
  };
  const [cls, txt] = map[tk.state] || map.starting;
  el.className = "trackpill " + cls;
  el.textContent = txt;
}

async function poll() {
  try {
    const st = await api("/api/state");
    trackPill(st.tracker);
    renderCues((st.targets || []).map((g) => g.kind === "boundary"
      ? { t: g.time, seg: null, bnd: g.boundary, spk: null, progress: g.progress }
      : { t: g.time, seg: g.segment, spk: g.speaker, progress: g.progress }));
    if (st.version !== lastVersion) { lastVersion = st.version; reconcile(st.segments); }
  } catch { /* ignore transient */ }
}

function showTrial(cur) {
  if (cur.done) return showResults(cur);
  show("setup", false); show("results", false); show("trial", true);
  mode = cur.condition; clip = cur.clip;
  segments = cur.segments; speakers = cur.speakers; lastVersion = 0;
  isLast = cur.trial_index + 1 >= cur.total;

  // header: progress + which trial + practice/measured
  $("progressbar").style.width = `${((cur.trial_index + 1) / cur.total) * 100}%`;
  $("trialcount").textContent = `Trial ${cur.trial_index + 1} of ${cur.total}`;
  const badge = $("phasebadge");
  badge.textContent = cur.phase;
  badge.className = "badge" + (cur.phase === "training" ? " practice" : "");
  badge.textContent = cur.phase === "training" ? "practice" : "recorded";

  // condition banner + steps
  const c = COND[mode];
  $("condbanner").className = "condbanner " + mode;
  $("condicon").textContent = c.icon;
  $("condtitle").textContent = c.title;
  $("condsub").textContent = c.sub;
  $("steps").innerHTML = c.steps.map((s) => `<li>${s}</li>`).join("");
  trackPill(null);

  legend(); initWave(); clearCues();
  running = true; t0 = Date.now();
  $("timer").textContent = "00:00";
  clearInterval(timerId); timerId = setInterval(tick, 200);
  clearInterval(pollId);
  lastPv = -1;
  $("play").disabled = false;                 // playback is mouse-driven in both
  $("seek").disabled = false;
  $("finish").textContent = isLast ? "Finish session ✓" : "Done — next →";
  if (mode === "tangible") { poll(); pollId = setInterval(poll, 90); }
  setStatus(mode === "gui"
    ? "When it looks fixed, press Done."
    : "Move the tokens to correct; use ▶ / the bar to listen.");
}

function showResults(res) {
  running = false; clearInterval(timerId); clearInterval(pollId); clearCues();
  show("trial", false); show("setup", false); show("results", true);
  const meas = res.results.filter((r) => r.phase === "measured");
  const by = {};
  meas.forEach((r) => {
    const k = r.condition;
    by[k] = by[k] || { cn: 0, cc: 0, bn: 0, bc: 0, t: 0 };
    by[k].cn += r.confusion.n; by[k].cc += r.confusion.corrected;
    by[k].bn += r.boundary.n; by[k].bc += r.boundary.corrected;
    by[k].t += r.total_time_s || 0;
  });
  let rows = "";
  for (const [c, v] of Object.entries(by))
    rows += `<tr><td class="cond">${c}</td>`
      + `<td>${v.cc}/${v.cn}</td><td>${v.bc}/${v.bn}</td>`
      + `<td>${v.t.toFixed(1)} s</td></tr>`;
  $("resultsbody").innerHTML = meas.length
    ? `<p class="lead">Group ${res.group}. Corrections you made in the recorded trials:</p>
       <table class="rtable"><thead><tr><th>Condition</th><th>Speaker fixes</th>
       <th>Boundary fixes</th><th>Total time</th></tr></thead><tbody>${rows}</tbody></table>`
    : `<p class="lead">Group ${res.group}. Session recorded.</p>`;
}

async function begin() {
  const err = $("setuperr");
  err.hidden = true;
  const pid = $("pid").value.trim();
  if (!pid) { err.textContent = "Please enter a participant ID."; err.hidden = false; return; }
  try {
    const g = $("group").value;
    const cur = await api("/api/protocol/start",
      { participant: pid, ...(g !== "" ? { group: Number(g) } : {}) });
    showTrial(cur);
  } catch (e) { err.textContent = "Could not start: " + e.message; err.hidden = false; }
}

async function undo() {                            // Ctrl+Z: revert last correction
  if (!running) return;
  try {
    const res = await api("/api/undo", { source: mode === "gui" ? "mouse" : "aruco" });
    reconcile(res.segments);
    setStatus("undid last change");
  } catch (e) { setStatus("undo error: " + e.message); }
}

async function finishTrial() {
  running = false; clearInterval(timerId); clearInterval(pollId);
  $("finish").disabled = true;
  try { showTrial(await api("/api/protocol/next", {})); }
  catch (e) { setStatus("finish error: " + e.message); }
  finally { $("finish").disabled = false; }
}

const wavewrap = document.querySelector(".wavewrap");
wavewrap.addEventListener("pointermove", guiHover);
wavewrap.addEventListener("pointerleave", () => { if (mode === "gui") clearCues(); });

$("begin").onclick = begin;
$("finish").onclick = finishTrial;
$("restart").onclick = () => { show("results", false); show("setup", true); };
$("play").onclick = () => ws && ws.playPause();
$("seek").oninput = () => {
  const d = (ws && ws.getDuration()) || 0;
  if (!seeking) { seeking = true; pb("seek_start", (ws && ws.getCurrentTime()) || 0); }
  $("time").textContent = `${fmt(($("seek").value / 1000) * d)} / ${fmt(d)}`;
};
$("seek").onchange = () => {
  const d = (ws && ws.getDuration()) || 0;
  const t = ($("seek").value / 1000) * d;
  if (ws) ws.setTime(t);
  pb("seek", t); pb("seek_end", t);
  seeking = false;
};
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && (e.key === "z" || e.key === "Z")) {
    if (running) { e.preventDefault(); undo(); }
    return;
  }
  if (e.code === "Space" && ws && e.target.tagName !== "INPUT") {
    e.preventDefault(); ws.playPause();
  }
});
