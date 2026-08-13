// GUI condition frontend. Emits the shared operations (reassign,
// move_boundary) to the backend, which owns the state and the log.
import WaveSurfer from "/static/vendor/wavesurfer.esm.js";
import RegionsPlugin from "/static/vendor/regions.esm.js";

const COLORS = { S1: "#e63946", S2: "#457b9d", S3: "#2a9d8f" };
const rgba = (hex, a) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`;
};

let ws, regions, segments = [], speakers = [], duration = 0, clip = "clipA";
let running = false, t0 = 0, timerId = null;
const byId = new Map();

const $ = (id) => document.getElementById(id);
const setStatus = (m) => ($("status").textContent = m);

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
  segments.forEach((seg, idx) => {
    const r = regions.addRegion({
      id: String(seg.id),
      start: seg.start, end: seg.end,
      content: seg.speaker,
      color: rgba(COLORS[seg.speaker], 0.28),
      drag: false, resize: true,
      resizeStart: idx > 0,                    // clip's outer edges are fixed
      resizeEnd: idx < segments.length - 1,
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
  if (!running) return;
  const sid = Number(region.id);
  const cur = segments[sid].speaker;
  const next = speakers[(speakers.indexOf(cur) + 1) % speakers.length];
  try {
    const res = await api("/api/op", { op: "reassign", segment: sid, speaker: next, source: "mouse" });
    reconcile(res.segments);
  } catch (e) { setStatus("op error: " + e.message); }
}

async function onBoundary(region, side) {
  if (!running || !side) return;
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
    container: "#wave",
    url: `/stimuli/${clip}/audio.wav`,
    height: 120,
    waveColor: "#c9c9c9", progressColor: "#9aa",
    cursorColor: "#333",
    fillParent: true, autoScroll: false, hideScrollbar: true, // fixed whole-clip scale, no zoom
  });
  regions = ws.registerPlugin(RegionsPlugin.create());
  ws.on("decode", buildRegions);
  regions.on("region-clicked", (r, e) => { e.stopPropagation(); onReassign(r); });
  regions.on("region-updated", (r, side) => onBoundary(r, side));
}

function tick() {
  const s = Math.floor((Date.now() - t0) / 1000);
  $("timer").textContent =
    String((s / 60) | 0).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
}

async function start() {
  try {
    clip = $("clip").value;
    const st = await api("/api/session/start",
      { participant: $("pid").value, condition: "gui", clip });
    segments = st.segments; speakers = st.speakers; duration = st.duration;
    legend(); initWave();
    running = true; t0 = Date.now();
    clearInterval(timerId); timerId = setInterval(tick, 200);
    $("start").disabled = true; $("finish").disabled = false;
    $("summary").hidden = true;
    setStatus("correcting — click segments, drag edges");
  } catch (e) { setStatus("start error: " + e.message); }
}

async function finish() {
  running = false; clearInterval(timerId);
  try {
    const sum = await api("/api/session/finish", {});
    $("summary").hidden = false;
    $("summary").textContent = JSON.stringify(sum, null, 2);
    setStatus(`done — confusion ${sum.confusion.corrected}/${sum.confusion.n}, `
      + `boundary ${sum.boundary.corrected}/${sum.boundary.n}`);
    $("start").disabled = false; $("finish").disabled = true;
  } catch (e) { setStatus("finish error: " + e.message); }
}

$("start").onclick = start;
$("finish").onclick = finish;
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && ws) { e.preventDefault(); ws.playPause(); }
});
