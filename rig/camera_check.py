#!/usr/bin/env python
# =============================================================
#  camera_check.py  --  pre-session readiness check for the
#  tangible rig. Run this before EACH participant to confirm the
#  overhead C920 is healthy before you press Begin:
#
#    * resolution is 1080p  (a jostled USB silently drops the
#      C920 to 640x480 -- markers get ~3x coarser and flaky)
#    * all 4 corner fiducials decode  (the homography needs them)
#    * lighting is adequate
#    * each token maps to a sensible band + time
#
#  It reuses the tracker's own detection (live_detect) so the
#  geometry always matches what a real session will read.
#
#  Usage (from the repo root, with the venv python):
#    .venv\Scripts\python.exe rig\camera_check.py
#    .venv\Scripts\python.exe rig\camera_check.py --expect S1=10,S3=50,B1=15
#    .venv\Scripts\python.exe rig\camera_check.py --index 1 --frames 15
#
#  Exit code 0 = PASS (safe to run a session), 1 = FAIL.
#  Writes an annotated frame to rig/camera_check.png to eyeball.
# =============================================================

import argparse, os, sys
import cv2
import live_detect as L

NAMES = {0: "TL", 1: "TR", 2: "BR", 3: "BL",
         10: "S1", 11: "S2", 12: "S3", 20: "B1"}
MIN_BRIGHT = 60          # frame mean below this -> add light
TOL = 0.15               # s, the "corrected" boundary tolerance (accuracy target)


def sharpest_frame(cap, n):
    """Grab n frames, return the sharpest (highest Laplacian variance)."""
    best = None
    for _ in range(n):
        ok, f = cap.read()
        if not ok:
            continue
        s = cv2.Laplacian(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
        if best is None or s > best[0]:
            best = (s, f)
    return best[1] if best else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, default=1, help="camera index (C920)")
    ap.add_argument("--frames", type=int, default=15, help="frames to sample")
    ap.add_argument("--expect", default="",
                    help="accuracy check: token=seconds, e.g. S1=10,S3=50,B1=15")
    ap.add_argument("--out", default=None, help="annotated frame path")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    out = args.out or os.path.join(here, "camera_check.png")

    cap = L.setup_camera(args.index)
    frame = sharpest_frame(cap, args.frames)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if frame is None:
        print(f"FAIL: no frame from camera index {args.index} "
              f"(is it connected / the right index?)")
        return 1

    det = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),
        cv2.aruco.DetectorParameters())
    corners, ids, _ = det.detectMarkers(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    cen = L.centers(corners, ids)
    _, toks, have = L.analyze(cen, 1.0)          # per-token t ignored; band maps it
    bands = L._load_bands()

    cv2.aruco.drawDetectedMarkers(frame, corners, ids)   # annotate then save
    cv2.imwrite(out, frame)
    bright = float(frame.mean())

    good_res = (w, h) == (1920, 1080)
    good_corners = len(have) == 4
    good_light = bright >= MIN_BRIGHT

    print("=== camera check ===")
    print(f"  resolution : {w}x{h}"
          + ("" if good_res else "   <-- NOT 1080p! reconnect USB / use a direct port"))
    print(f"  brightness : {bright:.0f}"
          + ("" if good_light else "   <-- too dim, add light"))
    print(f"  corners    : {sorted(have)}  ({len(have)}/4)"
          + ("" if good_corners else "   <-- reposition so the whole sheet is in frame"))
    if toks:
        print("  tokens seen:")
        for mid, _t, _lane, x, y in sorted(toks):
            b, gt = L.band_time(x, y, bands)
            where = f"band {b}  t={gt:5.2f}s" if b is not None else "(off the sheet)"
            print(f"    {NAMES.get(mid, mid):>3}: {where}")
    else:
        print("  tokens seen: none on the sheet")

    ok = good_res and good_corners and good_light

    # optional accuracy check: tokens placed on known ticks
    expect = {}
    for pair in filter(None, (p.strip() for p in args.expect.split(","))):
        k, _, v = pair.partition("=")
        try:
            expect[k.strip().upper()] = float(v)
        except ValueError:
            print(f"  (ignored bad --expect entry: {pair!r})")
    if expect:
        print("  accuracy (place each token on its tick):")
        seen = {}
        for mid, _t, _lane, x, y in toks:
            _, gt = L.band_time(x, y, bands)
            seen[NAMES.get(mid)] = gt
        errs = []
        for name, target in expect.items():
            gt = seen.get(name)
            if gt is None:
                print(f"    {name}: not on a band (put it on the {target:.0f}s tick)")
                ok = False
            else:
                e = gt - target
                errs.append(abs(e))
                flag = "OK" if abs(e) <= TOL else "OFF"
                print(f"    {name}: {gt:5.2f}s  target {target:4.0f}s  err {e:+.2f}s  {flag}")
                if abs(e) > TOL:
                    ok = False
        if errs:
            print(f"    mean|err| {sum(errs) / len(errs):.3f}s  "
                  f"max {max(errs):.3f}s  (tolerance {TOL}s)")

    print(f"  annotated frame -> {out}")
    print("VERDICT:", "PASS - ready for a session" if ok
          else "FAIL - fix the flagged items above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
