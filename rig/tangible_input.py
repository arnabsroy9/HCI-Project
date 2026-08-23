#!/usr/bin/env python
# =============================================================
#  tangible_input.py  --  the tangible condition's input source.
#  Reads ArUco token positions (from the C920 via live_detect,
#  or from a scripted --sim feed for testing without hardware)
#  and emits the SAME operations the GUI emits, to the same
#  backend, tagged source="aruco". No backend change needed.
#
#  Operation mapping (v0 -- refine in the Phase-0 paper prototype):
#    speaker token S_j settled at time t  -> reassign the segment
#        containing t to speaker j (if it is not already j)
#    boundary handle settled at time t    -> move the nearest
#        internal boundary to t
#
#  Commit semantics (resolves proposal problem 4): an operation
#  fires only when a token has been STATIONARY (centroid spread
#  below --still-mm) for --dwell-ms, and re-arms only after the
#  token moves more than --rearm-mm. No button, no gesture
#  vocabulary -- appropriate for passive tokens.
#
#  Usage:
#    python tangible_input.py --duration 60             # live camera
#    python tangible_input.py --sim demo_sim.json       # scripted test
# =============================================================

import argparse, json, math, time, urllib.request

X0_MM = 40.0
SPEAKER_ID0 = 10
BOUNDARY_ID0 = 20
PLAYBACK_ID = 30
BAND_X_MARGIN = 8.0     # mm past an axis end still counts; further = off the sheet


# ---------- geometry / mapping ----------
def band_time(x_mm, y_mm, bands):
    """Map a token at (x_mm, y_mm) to GLOBAL clip time using the folded-band
    geometry: the row (y) picks the band, x picks the time within it. Returns
    None if the token isn't inside a band row, OR is parked off the sheet past
    an axis end -- so a token set aside within the camera frame doesn't fire a
    spurious op via homography extrapolation."""
    for b in bands:
        if b["y0"] <= y_mm <= b["y1"]:
            if not (b["x0"] - BAND_X_MARGIN <= x_mm <= b["x1"] + BAND_X_MARGIN):
                return None                          # off the sheet (parked)
            t = b["t0"] + (x_mm - b["x0"]) / b["mm_per_s"]
            return max(b["t0"], min(b["t1"], t))     # clamp to the band's span
    return None


def segment_at(segments, t):
    for s in segments:
        if s["start"] <= t < s["end"]:
            return s
    return None


def nearest_boundary(segments, t):
    best, bd = None, None
    for i in range(len(segments) - 1):
        d = abs(segments[i]["end"] - t)
        if best is None or d < best:
            best, bd = d, i
    return bd


def nearer_edge(segments, t):
    """Boundary index of the nearer edge (start or end) of the segment that
    CONTAINS t -- i.e. which of THIS segment's two edges a handle here grabs."""
    seg = segment_at(segments, t)
    if seg is None:
        return None
    i, n = seg["id"], len(segments)
    cands = []
    if i > 0:      cands.append((abs(t - seg["start"]), i - 1))   # start edge
    if i < n - 1:  cands.append((abs(t - seg["end"]),   i))       # end edge
    return min(cands)[1] if cands else None


def process_token(mid, t, segments, speakers, committed, latch, prog):
    """One token per frame -> (op_to_send_or_None, live_target_or_None).

    Speaker token: reassign the segment under it (and keep it highlighted).
    Boundary handle: grab the nearer edge of the segment it's over and, once
    grabbed, stay LATCHED to that edge so dragging never jumps to another
    boundary -- until the token lifts (latch cleared on absent)."""
    if t is None:
        return None, None
    if BOUNDARY_ID0 <= mid < PLAYBACK_ID:                # boundary handle
        b = latch.get(mid)
        if b is None:
            b = nearer_edge(segments, t)
        if b is None:
            return None, None
        tgt = {"id": mid, "kind": "boundary", "time": round(t, 3),
               "boundary": b, "latched": mid in latch, "progress": prog}
        op = None
        if committed:
            latch[mid] = b                               # grab / keep this edge
            op = {"op": "move_boundary", "boundary": b, "t": round(t, 3)}
        return op, tgt
    idx = mid - SPEAKER_ID0                               # speaker token
    if not (0 <= idx < len(speakers)):
        return None, None
    spk = speakers[idx]
    seg = segment_at(segments, t)
    tgt = {"id": mid, "kind": "speaker", "time": round(t, 3), "speaker": spk,
           "segment": seg["id"] if seg else None, "progress": prog}
    op = None
    if committed and seg is not None and seg["speaker"] != spk:
        op = {"op": "reassign", "segment": seg["id"], "speaker": spk}
    return op, tgt


# ---------- dwell-based commit ----------
class Committer:
    """Edge-trigger a commit when a token holds still, then re-arm on move.

    Anchors a stationary reference position; as long as the token stays
    within --still-mm of it, the stationary duration grows. When it exceeds
    --dwell-ms (and the token is armed), a commit fires. The token re-arms
    only after moving more than --rearm-mm from where it last committed.
    """
    def __init__(self, still_mm=3.0, dwell_ms=600, rearm_mm=8.0):
        self.still, self.dwell = still_mm, dwell_ms / 1000.0
        self.rearm = rearm_mm
        self.ref = {}           # id -> (x, y, t_start) stationary anchor
        self.armed = {}         # id -> bool
        self.last_emit = {}     # id -> (x, y)

    def update(self, mid, x, y, now):
        rx, ry, t0 = self.ref.get(mid, (x, y, now))
        if math.hypot(x - rx, y - ry) > self.still:
            rx, ry, t0 = x, y, now          # moved: reset stationary anchor
        self.ref[mid] = (rx, ry, t0)
        if mid in self.last_emit:
            ex, ey = self.last_emit[mid]
            if math.hypot(x - ex, y - ey) > self.rearm:
                self.armed[mid] = True
        else:
            self.armed.setdefault(mid, True)
        if now - t0 >= self.dwell and self.armed.get(mid, True):
            self.armed[mid] = False
            self.last_emit[mid] = (x, y)
            self.ref[mid] = (x, y, now)      # reset so it will not refire
            return True
        return False

    def progress(self, mid, now):
        """Fraction (0..1) of the dwell a stationary, armed token has held --
        drives the on-screen 'committing...' ring."""
        ref = self.ref.get(mid)
        if not ref or not self.armed.get(mid, True):
            return 0.0
        return max(0.0, min(1.0, (now - ref[2]) / self.dwell))

    def absent(self, mid):
        self.ref.pop(mid, None)


# ---------- playback token: zone-based transport ----------
def load_zones(path=None):
    import os
    p = path or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "transport_zones.json")
    return json.load(open(p)) if os.path.exists(p) else None


class PlaybackController:
    """Classify the playback token's position into a transport zone (STOP /
    PLAY / PAUSE boxes, or the SEEK strip) and emit playback commands. Boxes
    fire once on entry; the seek strip scrubs continuously."""
    def __init__(self, cfg):
        self.zones = cfg["zones"]
        self.x0 = cfg["x0_mm"]
        self.mmps = cfg["mm_per_second"]
        self.state = None
        self.last_seek = None

    def zone_of(self, x, y):
        for name, z in self.zones.items():
            if z["x0"] <= x <= z["x1"] and z["y0"] <= y <= z["y1"]:
                return name
        return None

    def update(self, x, y):
        z = self.zone_of(x, y)
        if z is None:
            return None
        if z == "seek":
            t = max(0.0, (x - self.x0) / self.mmps)
            if self.last_seek is None or abs(t - self.last_seek) > 0.3:
                self.last_seek = t
                return {"event": "seek", "media_t": round(t, 3)}
            return None
        if z != self.state:                      # entered a STOP/PLAY/PAUSE box
            self.state = z
            self.last_seek = None
            return {"event": z}
        return None


# ---------- backend I/O ----------
def api(server, path, body=None):
    url = server.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def send_op(server, op):
    op = {**op, "source": "aruco"}
    res = api(server, "/api/op", op)
    return res.get("segments")


# ---------- run modes ----------
def run_sim(server, holds, bands, still, dwell, rearm):
    """Play scripted token holds: [{id, x_mm, y_mm, hold_s}, ...]."""
    st = api(server, "/api/state")
    segments, speakers = st["segments"], st["speakers"]
    com = Committer(still, dwell, rearm)
    latch, emitted = {}, []
    for hold in holds:
        mid = hold["id"]
        y = hold.get("y_mm", bands[0]["y0"])
        steps = max(2, int(hold["hold_s"] * 10))
        for _ in range(steps):
            now = time.time()
            t = band_time(hold["x_mm"], y, bands)
            committed = com.update(mid, hold["x_mm"], y, now)
            op, _tg = process_token(mid, t, segments, speakers, committed,
                                    latch, round(com.progress(mid, now), 2))
            if op:
                segments = send_op(server, op) or segments
                emitted.append(op)
                print("  commit id%-3d -> %s" % (mid, op))
            time.sleep(0.1)
        com.absent(mid); latch.pop(mid, None)
    print(f"emitted {len(emitted)} command(s)")
    return emitted


def run_camera(server, index, bands, still, dwell, rearm):
    import cv2
    import live_detect as L
    det = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),
        cv2.aruco.DetectorParameters())
    cap = L.setup_camera(index)
    com = Committer(still, dwell, rearm)
    latch = {}                                   # boundary token -> grabbed edge
    st = api(server, "/api/state")
    segments, speakers = st["segments"], st["speakers"]
    print("tracking... Ctrl+C to stop")
    last_hb = last_hover = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            corners, ids, _ = det.detectMarkers(gray)
            cen = L.centers(corners, ids)
            _, toks, have = L.analyze(cen, 1.0)  # per-token t ignored; band maps it
            now = time.time()
            if now - last_hb > 0.4:              # heartbeat -> browser camera dot
                last_hb = now
                try:
                    api(server, "/api/tracker",
                        {"corners": len(have), "tokens": len(toks)})
                except Exception:
                    pass
            seen, targets = set(), []
            for mid, _t, _lane, x_mm, y_mm in toks:
                seen.add(mid)
                t = band_time(x_mm, y_mm, bands)
                committed = com.update(mid, x_mm, y_mm, now)
                op, tg = process_token(mid, t, segments, speakers, committed,
                                       latch, round(com.progress(mid, now), 2))
                if op:
                    segments = send_op(server, op) or segments
                    print("  commit id%-3d -> %s" % (mid, op))
                if tg:
                    targets.append(tg)
            if now - last_hover > 0.08:          # live target cue -> display
                last_hover = now
                try:
                    api(server, "/api/hover", {"targets": targets})
                except Exception:
                    pass
            for mid in list(com.ref):
                if mid not in seen:
                    com.absent(mid); latch.pop(mid, None)   # release on lift
    except KeyboardInterrupt:
        cap.release()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://localhost:8000")
    ap.add_argument("--duration", type=float, default=60.0, help="clip seconds")
    ap.add_argument("--index", type=int, default=1)
    ap.add_argument("--sim", help="path to a scripted holds JSON")
    ap.add_argument("--still-mm", type=float, default=3.0)
    ap.add_argument("--dwell-ms", type=float, default=600.0)
    ap.add_argument("--rearm-mm", type=float, default=8.0)
    args = ap.parse_args()

    # Folded-band geometry from generate_sheets; fall back to one full-width
    # 60 s band (old single-timeline sheet) if the JSON predates bands.
    geo = load_zones()
    bands = (geo or {}).get("bands") or [{
        "index": 0, "t0": 0.0, "t1": args.duration, "x0": X0_MM, "x1": 400.0,
        "mm_per_s": (400.0 - X0_MM) / args.duration, "y0": 0.0, "y1": 300.0}]

    if args.sim:
        holds = json.load(open(args.sim))
        run_sim(args.server, holds, bands, args.still_mm, args.dwell_ms,
                args.rearm_mm)
    else:
        run_camera(args.server, args.index, bands,
                   args.still_mm, args.dwell_ms, args.rearm_mm)


if __name__ == "__main__":
    main()
