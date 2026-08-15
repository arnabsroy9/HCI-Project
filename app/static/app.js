// Protocol-aware study frontend. Walks the counterbalanced trial list;
// GUI trials are interactive, tangible trials are a read-only display that
// polls state while the ArUco tracker drives the same operations.
import WaveSurfer from "/static/vendor/wavesurfer.esm.js";
import RegionsPlugin from "/static/vendor/regions.esm.js";

const COLORS = { S1: "#e63946", S2: "#457b9d", S3: "#2a9d8f" };
const rgba = (hex, a) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`;
};

let ws, regions, segments = [], speakers = [], clip = "";
let mode = "gui", running = false, t0 = 0, timerId = null, pollId = null, lastVersion = 0;
let seeking = false;
const byId = new Map();
const $ = (id) => document.getElementById(id);
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
  ).join("");
}

function buildRegions() {
  regions.clearRegions();
  byId.clear();
  const interactive = mode === "gui";
  segments.forEach((seg, idx) => {
    const r = regions.addRegion({
      id: String(seg.id), start: seg.start, end: seg.end,
      content: seg.speaker, color: rgba(COLORS[seg.speaker], 0.28),
      drag: false, resize: interactive,
      resizeStart: interactive && idx > 0,
      resizeEnd: interactive && idx < segments.length - 1,
    });
    byId.set(seg.id, r);
  });
}

function reconcile(newSegs) {
  segments = newSegs;
  segments.forEach((seg) => {
    const r = byId.get(seg.id);
    if (!r) return;
    if (Math.abs(r.start - seg.start) > 1e-4 || Math.abs(r.end - seg.end) > 1e-4)
      r.setOptions({ start: seg.start, end: seg.end });
    if (r.content?.textContent !== seg.speaker)
      r.setOptions({ content: seg.speaker, color: rgba(COLORS[seg.speaker], 0.28) });
  });
}

async function onReassign(region) {
  if (!running || mode !== "gui") return;
  const sid = Number(region.id);
  const cur = segments[sid].speaker;
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
  regions.on("region-clicked", (r, e) => { e.stopPropagation(); onReassign(r); });
  regions.on("region-updated", (r, side) => onBoundary(r, side));
  // transport
  $("play").textContent = "▶ Play";
  ws.on("decode", () => updateTime(0));
  ws.on("timeupdate", updateTime);
  ws.on("play", () => { $("play").textContent = "⏸ Pause"; pb("play", ws.getCurrentTime()); });
  ws.on("pause", () => { $("play").textContent = "▶ Play"; pb("pause", ws.getCurrentTime()); });
}

// log a playback event so analysis can subtract navigation from total time
function pb(event, media_t) {
  if (!running) return;
  fetch("/api/playback", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event, media_t, source: mode === "gui" ? "mouse" : "aruco" }),
  }).catch(() => {});
}

function tick() {
  const s = Math.floor((Date.now() - t0) / 1000);
  $("timer").textContent =
    String((s / 60) | 0).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
}

async function poll() {                       // tangible: reflect tracker edits
  try {
    const st = await api("/api/state");
    if (st.version !== lastVersion) { lastVersion = st.version; reconcile(st.segments); }
  } catch { /* ignore transient */ }
}

function showTrial(cur) {
  if (cur.done) return showResults(cur);
  $("setup").hidden = true; $("trialbar").hidden = false;
  mode = cur.condition; clip = cur.clip;
  segments = cur.segments; speakers = cur.speakers; lastVersion = 0;
  $("progress").innerHTML =
    `Trial ${cur.trial_index + 1}/${cur.total} · <b>${cur.phase.toUpperCase()}</b> · `
    + `<span class="cond ${mode}">${mode.toUpperCase()}</span> · ${cur.clip}`;
  $("tnote").hidden = mode !== "tangible";
  $("ghelp").hidden = mode !== "gui";
  $("summary").hidden = true;
  legend(); initWave();
  running = true; t0 = Date.now();
  clearInterval(timerId); timerId = setInterval(tick, 200);
  clearInterval(pollId);
  if (mode === "tangible") pollId = setInterval(poll, 300);
  setStatus(mode === "gui" ? "correct with mouse" : "correct with tokens");
}

function showResults(res) {
  running = false; clearInterval(timerId); clearInterval(pollId);
  $("trialbar").hidden = true; $("tnote").hidden = true; $("ghelp").hidden = true;
  $("setup").hidden = false;
  const meas = res.results.filter((r) => r.phase === "measured");
  const by = {};
  meas.forEach((r) => {
    const k = r.condition;
    by[k] = by[k] || { cn: 0, cc: 0, bn: 0, bc: 0, t: 0 };
    by[k].cn += r.confusion.n; by[k].cc += r.confusion.corrected;
    by[k].bn += r.boundary.n; by[k].bc += r.boundary.corrected;
    by[k].t += r.total_time_s || 0;
  });
  let out = `Session complete — group ${res.group}\n\nMeasured trials by condition:\n`;
  for (const [c, v] of Object.entries(by))
    out += `  ${c.padEnd(9)} confusion ${v.cc}/${v.cn}  boundary ${v.bc}/${v.bn}`
      + `  time ${v.t.toFixed(1)}s\n`;
  out += `\nFull per-trial results saved to logs/${res.results.length ? "" : ""}...`;
  $("summary").hidden = false; $("summary").textContent = out;
  setStatus("session complete");
}

async function begin() {
  try {
    const g = $("group").value;
    const cur = await api("/api/protocol/start",
      { participant: $("pid").value, ...(g !== "" ? { group: Number(g) } : {}) });
    showTrial(cur);
  } catch (e) { alert("begin error: " + e.message); }
}

async function finishTrial() {
  running = false; clearInterval(timerId); clearInterval(pollId);
  try { showTrial(await api("/api/protocol/next", {})); }
  catch (e) { setStatus("finish error: " + e.message); }
}

$("begin").onclick = begin;
$("finish").onclick = finishTrial;
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
  if (e.code === "Space" && ws && e.target.tagName !== "INPUT") {
    e.preventDefault(); ws.playPause();
  }
});
