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


# ---------- geometry / mapping ----------
def time_of(x_mm, mm_per_s):
    return (x_mm - X0_MM) / mm_per_s


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


def token_to_op(mid, x_mm, mm_per_s, segments, speakers):
    """Map a settled token to an operation dict, or None."""
    t = time_of(x_mm, mm_per_s)
    if mid >= BOUNDARY_ID0:                      # boundary handle
        b = nearest_boundary(segments, t)
        if b is None:
            return None
        return {"op": "move_boundary", "boundary": b, "t": round(t, 3)}
    idx = mid - SPEAKER_ID0                       # speaker token
    if not (0 <= idx < len(speakers)):
        return None
    spk = speakers[idx]
    seg = segment_at(segments, t)
    if seg is None or seg["speaker"] == spk:
        return None                               # nothing to change
    return {"op": "reassign", "segment": seg["id"], "speaker": spk}


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
def run_sim(server, holds, mm_per_s, still, dwell, rearm, pbc=None):
    """Play scripted token holds: [{id, x_mm, y_mm, hold_s}, ...]."""
    st = api(server, "/api/state")
    segments, speakers = st["segments"], st["speakers"]
    com = Committer(still, dwell, rearm)
    emitted = []
    for hold in holds:
        mid = hold["id"]
        steps = max(2, int(hold["hold_s"] * 10))
        for _ in range(steps):
            now = time.time()
            if pbc is not None and mid == PLAYBACK_ID:
                cmd = pbc.update(hold["x_mm"], hold.get("y_mm", 0.0))
                if cmd:
                    api(server, "/api/playback", {**cmd, "source": "aruco"})
                    emitted.append(cmd)
                    print("  playback ->", cmd)
            elif com.update(mid, hold["x_mm"], hold.get("y_mm", 90.0), now):
                op = token_to_op(mid, hold["x_mm"], mm_per_s, segments, speakers)
                if op:
                    segments = send_op(server, op) or segments
                    emitted.append(op)
                    print("  commit id%-3d -> %s" % (mid, op))
            time.sleep(0.1)
        com.absent(mid)
    print(f"emitted {len(emitted)} command(s)")
    return emitted


def run_camera(server, index, mm_per_s, still, dwell, rearm, pbc=None):
    import cv2
    import live_detect as L
    det = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),
        cv2.aruco.DetectorParameters())
    cap = L.setup_camera(index)
    com = Committer(still, dwell, rearm)
    st = api(server, "/api/state")
    segments, speakers = st["segments"], st["speakers"]
    print("tracking... Ctrl+C to stop")
    last_hb = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            corners, ids, _ = det.detectMarkers(gray)
            cen = L.centers(corners, ids)
            _, toks, have = L.analyze(cen, mm_per_s)
            now = time.time()
            if now - last_hb > 0.4:              # heartbeat -> browser camera dot
                last_hb = now
                try:
                    api(server, "/api/tracker",
                        {"corners": len(have), "tokens": len(toks)})
                except Exception:
                    pass
            seen = set()
            for mid, t, lane, x_mm, y_mm in toks:
                seen.add(mid)
                if pbc is not None and mid == PLAYBACK_ID:
                    cmd = pbc.update(x_mm, y_mm)
                    if cmd:
                        api(server, "/api/playback", {**cmd, "source": "aruco"})
                        print("  playback ->", cmd)
                elif com.update(mid, x_mm, y_mm, now):
                    op = token_to_op(mid, x_mm, mm_per_s, segments, speakers)
                    if op:
                        segments = send_op(server, op) or segments
                        print("  commit id%-3d -> %s" % (mid, op))
            for mid in list(com.ref):
                if mid not in seen:
                    com.absent(mid)
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
    mm_per_s = (400.0 - X0_MM) / args.duration

    zones = load_zones()
    pbc = PlaybackController(zones) if zones else None

    if args.sim:
        holds = json.load(open(args.sim))
        run_sim(args.server, holds, mm_per_s, args.still_mm, args.dwell_ms,
                args.rearm_mm, pbc)
    else:
        run_camera(args.server, args.index, mm_per_s,
                   args.still_mm, args.dwell_ms, args.rearm_mm, pbc)


if __name__ == "__main__":
    main()
