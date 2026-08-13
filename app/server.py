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

import json, os, threading, time, datetime, urllib.parse
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
    "session": None,   # {participant, condition, started_epoch, log_path}
}


# ---------- stimulus / session ----------
def load_stimulus(clip):
    d = os.path.join(STIMULI, clip)
    hyp = json.load(open(os.path.join(d, "hypothesis.json")))
    key = json.load(open(os.path.join(d, "answer_key.json")))
    return hyp, key


def start_session(participant, condition, clip):
    hyp, key = load_stimulus(clip)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c for c in participant if c.isalnum()) or "anon"
    log_path = os.path.join(LOGS, f"{safe}_{condition}_{clip}_{ts}.jsonl")
    STATE.update(clip=clip, duration=hyp["duration"], speakers=hyp["speakers"],
                 segments=[dict(s) for s in hyp["segments"]],
                 answer_key=key, version=0,
                 session={"participant": participant, "condition": condition,
                          "clip": clip, "started_epoch": time.time(),
                          "log_path": log_path})
    log_event({"event": "session_start", "participant": participant,
               "condition": condition, "clip": clip})
    return session_state()


def session_state():
    return {"version": STATE["version"], "clip": STATE["clip"],
            "duration": STATE["duration"], "speakers": STATE["speakers"],
            "segments": STATE["segments"], "session": STATE["session"]}


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
            if u.path == "/api/op":
                with LOCK:
                    if not STATE["session"]:
                        return self._json(409, {"error": "no active session"})
                    apply_op(body)
                    log_event({"event": "op", "source": body.get("source", "mouse"),
                               "op": body})
                    return self._json(200, {"version": STATE["version"],
                                            "segments": STATE["segments"]})
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
    port = int(os.environ.get("PORT", "8000"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"serving on http://localhost:{port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
