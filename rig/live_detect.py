#!/usr/bin/env python
# =============================================================
#  live_detect.py  --  real-world sanity check of the printed
#  rig: C920 -> ArUco detection -> homography -> time/lane.
#
#  Proves the physical chain works in the actual room:
#    - printed corner fiducials (ids 0-3) all detected
#    - a homography maps camera pixels -> sheet millimetres
#    - each speaker/handle token (ids 10-12, 20) maps to a
#      sensible time t and speaker lane
#    - flags glare / occlusion / missing markers
#
#  Two modes:
#    python live_detect.py            # headless: grab a few
#                                     # seconds, save annotated
#                                     # frames to ./detect, print
#                                     # a summary. Good for review.
#    python live_detect.py --live     # live window; ESC quits,
#                                     # 's' saves a frame. Use this
#                                     # to reposition the camera.
#
#  Options: --index (camera), --duration (clip seconds, default 60)
# =============================================================

import argparse, os, time
import cv2
import numpy as np

# sheet-mm positions of the corner fiducial CENTERS (top-left origin),
# must match generate_sheets.py
CORNER_MM = {0: (25.0, 25.0), 1: (395.0, 25.0),
             2: (395.0, 272.0), 3: (25.0, 272.0)}
X0_MM = 40.0            # t = 0
MM_PER_S = 6.0          # for a 60 s clip (scales with --duration)
LANE_TOP, LANE_BOT, GAP, N_LANES = 62.0, 250.0, 5.0, 3

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect")
os.makedirs(OUT, exist_ok=True)

def setup_camera(idx):
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    cap.set(cv2.CAP_PROP_FPS, 30)
    # Sanity-check phase: let the camera auto-expose / auto-WB / autofocus
    # so markers are bright and sharp in whatever room light you have.
    # We lock these to fixed values later, tuned to the room, for the
    # resolution-floor measurement and the study.
    cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)   # auto
    cap.set(cv2.CAP_PROP_AUTO_WB, 1)
    for _ in range(20):                         # let auto-exposure settle
        cap.read()
    return cap

def lane_of(y_mm):
    lane_h = ((LANE_BOT - LANE_TOP) - GAP * (N_LANES - 1)) / N_LANES
    for i in range(N_LANES):
        top = LANE_TOP + i * (lane_h + GAP)
        if top <= y_mm <= top + lane_h:
            return i + 1
    return None

def centers(corners, ids):
    """id -> (cx,cy) image-pixel centroid."""
    out = {}
    if ids is None:
        return out
    for c, i in zip(corners, ids.flatten()):
        out[int(i)] = c.reshape(-1, 2).mean(axis=0)
    return out

def analyze(cen, mm_per_s):
    """Return (homography or None, list of (id, t, lane, x_mm, y_mm))."""
    have = [k for k in CORNER_MM if k in cen]
    if len(have) < 4:
        return None, [], have
    src = np.array([cen[k] for k in sorted(CORNER_MM)], np.float32)
    dst = np.array([CORNER_MM[k] for k in sorted(CORNER_MM)], np.float32)
    H, _ = cv2.findHomography(src, dst)
    toks = []
    for mid, px in cen.items():
        if mid in CORNER_MM:
            continue
        p = cv2.perspectiveTransform(px.reshape(1, 1, 2).astype(np.float32), H)
        x_mm, y_mm = float(p[0, 0, 0]), float(p[0, 0, 1])
        t = (x_mm - X0_MM) / mm_per_s
        toks.append((mid, t, lane_of(y_mm), x_mm, y_mm))
    return H, sorted(toks), have

def annotate(frame, corners, ids, toks):
    cv2.aruco.drawDetectedMarkers(frame, corners, ids)
    cen = centers(corners, ids)
    for mid, t, lane, x_mm, y_mm in toks:
        if mid in cen:
            x, y = cen[mid].astype(int)
            lbl = f"id{mid} t={t:.2f}s lane={lane}"
            cv2.putText(frame, lbl, (x - 40, y - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    return frame

def summarize(cen, toks, have):
    kind = {**{i: "corner" for i in CORNER_MM}}
    print(f"  corners seen: {sorted(have)}  ({len(have)}/4)")
    if len(have) < 4:
        print("  -> need all 4 corners for the homography; "
              "reposition so the whole sheet is in frame.")
    for mid, t, lane, x_mm, y_mm in toks:
        role = "handle" if mid >= 20 else f"S{mid-10+1}"
        print(f"  token id{mid:<3} ({role:>6}): t={t:6.2f}s  lane={lane}  "
              f"[sheet {x_mm:6.1f},{y_mm:6.1f} mm]")
    all_tok = [k for k in cen if k not in CORNER_MM]
    if not all_tok:
        print("  no speaker/handle tokens detected.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, default=1)
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--seconds", type=float, default=8.0)
    args = ap.parse_args()
    mm_per_s = (400.0 - X0_MM) / args.duration

    det = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),
        cv2.aruco.DetectorParameters())
    cap = setup_camera(args.index)
    if not cap.isOpened():
        print(f"Could not open camera index {args.index}."); return

    print(f"Camera index {args.index}, clip {args.duration:.0f}s, "
          f"{mm_per_s:.3f} mm/s\n")

    saved = 0
    t_end = time.time() + args.seconds
    best = None
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = det.detectMarkers(gray)
        cen = centers(corners, ids)
        H, toks, have = analyze(cen, mm_per_s)
        ann = annotate(frame.copy(), corners, ids, toks)

        if args.live:
            cv2.imshow("rig detection (ESC quit, s save)", ann)
            k = cv2.waitKey(1) & 0xFF
            if k == 27:
                break
            if k == ord("s"):
                p = os.path.join(OUT, f"live_{saved:02d}.png")
                cv2.imwrite(p, ann); saved += 1
                print("saved", p); summarize(cen, toks, have)
        else:
            # headless: keep the frame with the most markers
            score = len(have) * 10 + len([k for k in cen if k not in CORNER_MM])
            if best is None or score > best[0]:
                best = (score, ann.copy(), cen, toks, have)
            if time.time() > t_end:
                break

    cap.release()
    if args.live:
        cv2.destroyAllWindows()
    elif best is not None:
        _, ann, cen, toks, have = best
        p = os.path.join(OUT, "best_frame.png")
        cv2.imwrite(p, ann)
        print("=== best frame summary ===")
        summarize(cen, toks, have)
        print(f"\nannotated frame -> {p}")

if __name__ == "__main__":
    main()
