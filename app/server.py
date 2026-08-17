#!/usr/bin/env python
# =============================================================
#  server.py  --  shared-core backend for the tangible/GUI
#  diarization-correction study. Stdlib only (no pip installs).
#
#  Holds ONE segment-state model and an append-only operation
#  log. Both the GUI (mouse) and, later, the ArUco tracker POST
#  the SAME operations here, so the two conditions differ only
#  in the input source -- exactly the design in the proposal's
#  Section 5.4. The op log IS the dataset.
#
#  Operations (the shared schema):
#     {"op":"reassign",      "segment": <id>, "speaker": "S2"}
#     {"op":"move_boundary", "boundary": <i>, "t": <seconds>}
#  Every op is logged with a wall-clock timestamp and the
#  elapsed time since the trial began.
#
#  Run:  python server.py         (then open http://localhost:8000)
# =============================================================

import json, os, sys, subprocess, atexit, threading, time, datetime, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
STIMULI = os.path.join(BASE, "stimuli")
LOGS = os.path.join(BASE, "logs")
os.makedirs(LOGS, exist_ok=True)

MIN_SEG = 0.4          # s, minimum segment length (matches make_stimulus)
BOUND_TOL = 0.15       # s, a boundary counts as "corrected" within this

LOCK = threading.Lock()
STATE = {
    "clip": None, "duration": 0.0, "speakers": [], "segments": [],
    "answer_key": None, "version": 0,
    "session": None,    # {participant, condition, phase, started_epoch, log_path}
    "protocol": None,   # {participant, group, trials, idx, results}
    "playback": {"playing": False, "media_t": 0.0, "pv": 0},
}

# --- counterbalanced within-subjects protocol ---
CONDITIONS = ["gui", "tangible"]
# Defaults use the synthetic clips (always present). Drop a stimuli/protocol.json
# {"train_clip":..., "meas_set1":[...], "meas_set2":[...]} to run on other clips
# (e.g. the real Bengali-Loop set) without editing code.
TRAIN_CLIP = "clipT"
MEAS_SET1 = ["clipA", "clipB"]
MEAS_SET2 = ["clipC", "clipD"]


def clip_config():
    path = os.path.join(STIMULI, "protocol.json")
    if os.path.exists(path):
        c = json.load(open(path))
        return c["train_clip"], c["meas_set1"], c["meas_set2"]
    return TRAIN_CLIP, MEAS_SET1, MEAS_SET2


# ---------- tangible tracker (auto-managed camera process) ----------
# For a tangible trial the server itself launches the ArUco tracker with the
# right clip duration and stops it when the trial ends, so the operator never
# runs a second terminal or matches a --duration by hand. The tracker POSTs a
# heartbeat to /api/tracker so the browser can show a live "camera OK" dot.
RIG = os.path.join(os.path.dirname(BASE), "rig")
PORT = int(os.environ.get("PORT", "8000"))
CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", "1"))
TRACKER = {"proc": None, "error": None, "hb": None, "hb_epoch": 0.0}
# Live pre-commit token targets streamed by the tracker (tangible hover cue).
# The GUI computes its own hover client-side; this is only the tangible feed.
HOVER = {"targets": [], "epoch": 0.0}


def hover_targets():
    """Fresh live targets (<1 s old), else empty so a stale cue doesn't linger."""
    return HOVER["targets"] if (time.time() - HOVER["epoch"]) < 1.0 else []


def start_tracker(duration):
    """Spawn the tracker for a tangible trial (idempotent: stops any old one)."""
    stop_tracker()
    TRACKER.update(error=None, hb=None, hb_epoch=0.0)
    script = os.path.join(RIG, "tangible_input.py")
    cmd = [sys.executable, script, "--duration", str(duration),
           "--server", f"http://127.0.0.1:{PORT}", "--index", str(CAMERA_INDEX)]
    try:
        log = open(os.path.join(LOGS, "tracker.log"), "a", buffering=1)
        log.write(f"\n--- tracker start {datetime.datetime.now():%H:%M:%S} "
                  f"dur={duration} cam={CAMERA_INDEX} ---\n")
        TRACKER["proc"] = subprocess.Popen(cmd, cwd=RIG, stdout=log,
                                           stderr=subprocess.STDOUT)
    except Exception as e:                       # spawn itself failed
        TRACKER["error"] = str(e)


def stop_tracker():
    p = TRACKER.get("proc")
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=2)
        except Exception:
            p.kill()
    TRACKER["proc"] = None


def tracker_status():
    """Student-readable state of the camera process for the on-screen dot."""
    p = TRACKER.get("proc")
    running = bool(p and p.poll() is None)
    hb, epoch = TRACKER.get("hb"), TRACKER.get("hb_epoch") or 0.0
    fresh = bool(hb and (time.time() - epoch) < 2.0)
    if TRACKER.get("error"):
        state = "error"
    elif not running:
        state = "off"
    elif not fresh:
        state = "starting"                       # process up, no frames yet
    elif hb.get("corners", 0) < 4:
        state = "no_sheet"                        # can't see all 4 corners
    else:
        state = "tracking"
    return {"state": state, "running": running,
            "corners": (hb or {}).get("corners", 0),
            "tokens": (hb or {}).get("tokens", 0),
            "error": TRACKER.get("error")}


atexit.register(stop_tracker)


def check_source(source):
    """Reject an input whose source does not match the active trial's condition,
    so tangible ops can never land in a GUI trial (or vice-versa)."""
    s = STATE["session"]
    cond = s and s["condition"]
    if source == "aruco" and cond != "tangible":
        return f"tangible input ignored: the active trial is {cond}"
    if source == "mouse" and cond not in ("gui", None):
        return f"mouse input ignored: the active trial is {cond}"
    return None


# ---------- stimulus / session ----------
def load_stimulus(clip):
    d = os.path.join(STIMULI, clip)
    hyp = json.load(open(os.path.join(d, "hypothesis.json")))
    key = json.load(open(os.path.join(d, "answer_key.json")))
    return hyp, key


def start_session(participant, condition, clip, phase="single", trial_index=None):
    hyp, key = load_stimulus(clip)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    safe = "".join(c for c in participant if c.isalnum()) or "anon"
    log_path = os.path.join(LOGS, f"{safe}_{condition}_{clip}_{phase}_{ts}.jsonl")
    STATE.update(clip=clip, duration=hyp["duration"], speakers=hyp["speakers"],
                 segments=[dict(s) for s in hyp["segments"]],
                 answer_key=key, version=0,
                 session={"participant": participant, "condition": condition,
                          "clip": clip, "phase": phase, "trial_index": trial_index,
                          "started_epoch": time.time(), "log_path": log_path},
                 playback={"playing": False, "media_t": 0.0, "pv": 0})
    log_event({"event": "session_start", "participant": participant,
               "condition": condition, "clip": clip, "phase": phase,
               "trial_index": trial_index})
    HOVER["targets"] = []                        # drop any stale hover cue
    # Auto-manage the camera: a tangible trial launches the tracker itself;
    # any other trial makes sure no tracker is left running.
    if condition == "tangible":
        start_tracker(hyp["duration"])
    else:
        stop_tracker()
    return session_state()


def session_state():
    return {"version": STATE["version"], "clip": STATE["clip"],
            "duration": STATE["duration"], "speakers": STATE["speakers"],
            "segments": STATE["segments"], "session": STATE["session"],
            "playback": STATE["playback"], "tracker": tracker_status(),
            "targets": hover_targets()}


def playback_event(ev, media_t, source):
    """Log a playback event and update shared playback state. Play/pause/seek
    change the state the tangible display follows; seek_start/seek_end just
    time the scrubbing. The log lets analysis subtract navigation from total."""
    pb = STATE["playback"]
    if ev in ("play", "pause", "seek", "stop"):
        pb["playing"] = (ev == "play")
    if ev == "stop":
        pb["media_t"] = 0.0
    elif media_t is not None:
        pb["media_t"] = float(media_t)
    pb["pv"] += 1
    log_event({"event": "playback", "pb": ev, "media_t": media_t, "source": source})
    return {"pv": pb["pv"], "playback": pb}


def build_plan(participant, group=None):
    """Counterbalanced trial list. group bit0 = condition order,
    bit1 = which measured clip set each condition gets. A training
    block precedes each condition's measured trials (novelty control)."""
    if group is None:
        group = sum(ord(c) for c in participant) % 4
    train_clip, set1, set2 = clip_config()
    order = CONDITIONS if not (group & 1) else CONDITIONS[::-1]
    if not (group & 2):
        clips = {"gui": set1, "tangible": set2}
    else:
        clips = {"gui": set2, "tangible": set1}
    trials = []
    for cond in order:
        trials.append({"phase": "training", "condition": cond, "clip": train_clip})
        for cl in clips[cond]:
            trials.append({"phase": "measured", "condition": cond, "clip": cl})
    return group, trials


def protocol_current():
    p = STATE["protocol"]
    tr = p["trials"][p["idx"]]
    return {"done": False, "trial_index": p["idx"], "total": len(p["trials"]),
            "group": p["group"], "phase": tr["phase"],
            "condition": tr["condition"], "clip": tr["clip"],
            "duration": STATE["duration"], "speakers": STATE["speakers"],
            "segments": STATE["segments"]}


def protocol_advance():
    """Move to the next trial (or finish the whole session)."""
    p = STATE["protocol"]
    p["idx"] += 1
    if p["idx"] >= len(p["trials"]):
        stop_tracker()                           # session over: release camera
        path = os.path.join(LOGS, f"{p['participant']}_session_"
                            f"{datetime.datetime.now():%Y%m%d_%H%M%S}.json")
        json.dump({"participant": p["participant"], "group": p["group"],
                   "trials": p["trials"], "results": p["results"]},
                  open(path, "w"), indent=2)
        return {"done": True, "total": len(p["trials"]),
                "group": p["group"], "results": p["results"]}
    tr = p["trials"][p["idx"]]
    start_session(p["participant"], tr["condition"], tr["clip"],
                  phase=tr["phase"], trial_index=p["idx"])
    return protocol_current()


def protocol_start(participant, group=None):
    g, trials = build_plan(participant, group)
    STATE["protocol"] = {"participant": participant, "group": g,
                         "trials": trials, "idx": -1, "results": []}
    return protocol_advance()


def protocol_next():
    """Score the current trial, record it, advance."""
    p = STATE["protocol"]
    summary = score()
    tr = p["trials"][p["idx"]]
    p["results"].append({"trial_index": p["idx"], "phase": tr["phase"],
                         "condition": summary["condition"], "clip": summary["clip"],
                         "total_time_s": summary["total_time_s"],
                         "confusion": summary["confusion"],
                         "boundary": summary["boundary"]})
    log_event({"event": "trial_finish", "summary": summary})
    return protocol_advance()


def log_event(rec):
    s = STATE["session"]
    if not s:
        return
    now = time.time()
    rec = {"t_iso": datetime.datetime.now().isoformat(timespec="milliseconds"),
           "t_epoch": round(now, 3),
           "elapsed_s": round(now - s["started_epoch"], 3), **rec}
    with open(s["log_path"], "a") as f:
        f.write(json.dumps(rec) + "\n")


# ---------- operations ----------
def apply_op(op):
    segs = STATE["segments"]
    kind = op.get("op")
    if kind == "reassign":
        sid = int(op["segment"]); spk = op["speaker"]
        if not (0 <= sid < len(segs)):
            raise ValueError("bad segment id")
        if spk not in STATE["speakers"]:
            raise ValueError("unknown speaker")
        segs[sid]["speaker"] = spk
    elif kind == "move_boundary":
        i = int(op["boundary"]); t = float(op["t"])
        if not (0 <= i < len(segs) - 1):
            raise ValueError("bad boundary index")
        lo = segs[i]["start"] + MIN_SEG
        hi = segs[i + 1]["end"] - MIN_SEG
        t = round(min(max(t, lo), hi), 3)
        segs[i]["end"] = t
        segs[i + 1]["start"] = t
    else:
        raise ValueError("unknown op")
    STATE["version"] += 1


def score():
    """Compare current segments to the answer key; return a summary."""
    segs = STATE["segments"]
    key = STATE["answer_key"]
    per = []
    conf_ok = conf_n = bnd_ok = bnd_n = 0
    resid = []
    for e in key["injected_errors"]:
        if e["type"] == "confusion":
            conf_n += 1
            got = segs[e["segment_id"]]["speaker"]
            ok = (got == e["correct_speaker"])
            conf_ok += ok
            per.append({**e, "final": got, "corrected": ok})
        else:
            bnd_n += 1
            i = e["boundary_index"]
            cur = segs[i]["end"]
            r = abs(cur - e["correct_t"])
            ok = (r <= BOUND_TOL)
            bnd_ok += ok; resid.append(r)
            per.append({**e, "final_t": round(cur, 3),
                        "residual_s": round(r, 3), "corrected": ok})
    s = STATE["session"]
    total_time = round(time.time() - s["started_epoch"], 3) if s else None
    summary = {
        "participant": s and s["participant"], "condition": s and s["condition"],
        "clip": STATE["clip"], "total_time_s": total_time,
        "confusion": {"n": conf_n, "corrected": conf_ok,
                      "accuracy": round(conf_ok / conf_n, 3) if conf_n else None},
        "boundary": {"n": bnd_n, "corrected": bnd_ok,
                     "accuracy": round(bnd_ok / bnd_n, 3) if bnd_n else None,
                     "mean_residual_s": round(sum(resid) / len(resid), 3) if resid else None},
        "per_error": per,
    }
    return summary


# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):        # quiet console
        pass

    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _file(self, path):
        if not os.path.isfile(path):
            return self._send(404, b"not found", "text/plain")
        ext = os.path.splitext(path)[1].lower()
        ctype = {".html": "text/html", ".js": "text/javascript",
                 ".css": "text/css", ".json": "application/json",
                 ".wav": "audio/wav"}.get(ext, "application/octet-stream")
        with open(path, "rb") as f:
            body = f.read()
        self._send(200, body, ctype)

    def _safe(self, root, rel):
        p = os.path.normpath(os.path.join(root, rel.lstrip("/")))
        return p if p.startswith(root) else None

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/" or u.path == "/index.html":
            return self._file(os.path.join(STATIC, "index.html"))
        if u.path.startswith("/static/"):
            p = self._safe(STATIC, u.path[len("/static/"):])
            return self._file(p) if p else self._send(403)
        if u.path.startswith("/stimuli/"):
            p = self._safe(STIMULI, u.path[len("/stimuli/"):])
            return self._file(p) if p else self._send(403)
        if u.path == "/api/state":
            with LOCK:
                return self._json(200, session_state())
        if u.path == "/api/protocol/current":
            with LOCK:
                if not STATE["protocol"]:
                    return self._json(409, {"error": "no protocol running"})
                return self._json(200, protocol_current())
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            if u.path == "/api/session/start":
                with LOCK:
                    st = start_session(body["participant"], body["condition"],
                                       body["clip"])
                return self._json(200, st)
            if u.path == "/api/protocol/start":
                with LOCK:
                    return self._json(200, protocol_start(body["participant"],
                                                          body.get("group")))
            if u.path == "/api/protocol/next":
                with LOCK:
                    if not STATE["protocol"]:
                        return self._json(409, {"error": "no protocol running"})
                    return self._json(200, protocol_next())
            if u.path == "/api/op":
                with LOCK:
                    if not STATE["session"]:
                        return self._json(409, {"error": "no active session"})
                    err = check_source(body.get("source", "mouse"))
                    if err:
                        return self._json(409, {"error": err})
                    apply_op(body)
                    log_event({"event": "op", "source": body.get("source", "mouse"),
                               "op": body})
                    return self._json(200, {"version": STATE["version"],
                                            "segments": STATE["segments"]})
            if u.path == "/api/playback":
                with LOCK:
                    if not STATE["session"]:
                        return self._json(409, {"error": "no active session"})
                    err = check_source(body.get("source", "mouse"))
                    if err:
                        return self._json(409, {"error": err})
                    return self._json(200, playback_event(
                        body.get("event"), body.get("media_t"),
                        body.get("source", "mouse")))
            if u.path == "/api/tracker":          # tracker heartbeat (camera dot)
                with LOCK:
                    TRACKER["hb"] = {"corners": int(body.get("corners", 0)),
                                     "tokens": int(body.get("tokens", 0))}
                    TRACKER["hb_epoch"] = time.time()
                return self._json(200, {"ok": True})
            if u.path == "/api/hover":            # live pre-commit token targets
                with LOCK:
                    HOVER["targets"] = body.get("targets", [])
                    HOVER["epoch"] = time.time()
                return self._json(200, {"ok": True})
            if u.path == "/api/session/finish":
                with LOCK:
                    summary = score()
                    log_event({"event": "session_finish", "summary": summary})
                    path = STATE["session"]["log_path"].replace(".jsonl", "_summary.json")
                    json.dump(summary, open(path, "w"), indent=2)
                return self._json(200, summary)
        except (KeyError, ValueError) as e:
            return self._json(400, {"error": str(e)})
        return self._send(404, b"not found", "text/plain")


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"serving on http://localhost:{PORT}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
    finally:
        stop_tracker()


if __name__ == "__main__":
    main()
