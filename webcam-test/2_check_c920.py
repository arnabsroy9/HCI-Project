#!/usr/bin/env python
# =============================================================
#  2_check_c920.py  --  native-Windows OpenCV functional test
#  for a second-hand Logitech C920, aimed at TUI/ArUco use.
#
#  This exercises the EXACT code path your tracking pipeline
#  uses (OpenCV CAP_PROP_* over the DirectShow backend), which
#  is a stronger test than v4l2-ctl: it proves the camera not
#  only *reports* manual controls but actually *responds* to
#  them, measured objectively rather than by "wave your hand".
#
#  Objective checks:
#    - enumerate cameras, open the C920 at 1080p30 MJPG
#    - FOCUS  : disable AF, sweep near<->far, measure sharpness
#               (variance of Laplacian) -> proves the motor moves
#    - EXPOSURE: switch to manual, set low/high, measure mean
#               brightness -> proves exposure responds
#    - WB     : disable auto-WB, set two temperatures, read back
#    - dead-pixel hint from a saved frame
#  Frames are saved to ./frames so they can be eyeballed after.
#
#  Usage:
#     python 2_check_c920.py               # auto-pick first working cam
#     python 2_check_c920.py --index 1     # force a camera index
# =============================================================

import argparse, os, sys, time
import cv2
import numpy as np

FRAME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frames")
os.makedirs(FRAME_DIR, exist_ok=True)

def log(msg): print(msg, flush=True)

def grab(cap, warm=8):
    """Read a few frames so the setting settles, return the last."""
    f = None
    for _ in range(warm):
        ok, f = cap.read()
        if not ok:
            f = None
        time.sleep(0.03)
    return f

def sharpness(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())

def brightness(img):
    return float(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).mean())

def enumerate_cams(max_idx=6):
    found = []
    for i in range(max_idx):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            ok, _ = cap.read()
            if ok:
                found.append(i)
        cap.release()
    return found

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, default=None)
    args = ap.parse_args()

    log("OpenCV version: " + cv2.__version__)
    log("=== Enumerating cameras (DirectShow) ===")
    cams = enumerate_cams()
    log("Working camera indices: " + (str(cams) if cams else "NONE FOUND"))
    if not cams:
        log("No camera returned frames. Check the cable/port, then rerun.")
        sys.exit(1)

    idx = args.index if args.index is not None else cams[0]
    log(f"\nUsing camera index {idx}\n")

    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if not cap.isOpened():
        log(f"Could not open index {idx}."); sys.exit(1)

    # Ask for 1080p30 over MJPG -- the C920's native high-res mode.
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    cap.set(cv2.CAP_PROP_FPS, 30)
    grab(cap, warm=10)

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    log("=== Reported capture format ===")
    log(f"  resolution : {w} x {h}")
    log(f"  fps        : {fps}")
    res_ok = (w >= 1920 and h >= 1080)
    log(f"  1080p available: {'YES' if res_ok else 'NO -- unexpected for a real C920'}")

    base = grab(cap)
    if base is not None:
        p = os.path.join(FRAME_DIR, "00_baseline.png")
        cv2.imwrite(p, base)
        log(f"  saved baseline frame -> {p}")

    results = {"resolution": res_ok}

    # ---------------- FOCUS TEST ----------------
    log("\n=== FOCUS control test ===")
    af_ok = cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    log(f"  disable autofocus accepted: {af_ok}")
    focus_sharp = {}
    for name, val in (("near", 255), ("far", 0)):
        cap.set(cv2.CAP_PROP_FOCUS, val)
        img = grab(cap, warm=12)
        if img is None:
            log(f"  focus={val}: no frame"); continue
        s = sharpness(img)
        focus_sharp[name] = s
        readback = cap.get(cv2.CAP_PROP_FOCUS)
        fp = os.path.join(FRAME_DIR, f"01_focus_{name}_{val}.png")
        cv2.imwrite(fp, img)
        log(f"  focus set {val:>3} (readback {readback:>5.0f})  sharpness={s:8.1f}  -> {fp}")
    if len(focus_sharp) == 2:
        lo, hi = sorted(focus_sharp.values())
        ratio = (hi / lo) if lo > 0 else 0
        moved = ratio > 1.15  # >15% sharpness change = motor physically moved
        results["focus"] = moved
        log(f"  sharpness ratio far/near = {ratio:.2f}")
        log(f"  FOCUS MOTOR RESPONDS: {'YES' if moved else 'NO -- focus may be stuck/dead'}")
    else:
        results["focus"] = False

    # ---------------- EXPOSURE TEST ----------------
    log("\n=== EXPOSURE control test ===")
    # DSHOW: CAP_PROP_AUTO_EXPOSURE 0.25 = manual, 0.75 = auto
    man = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    log(f"  switch to manual exposure accepted: {man}")
    exp_bright = {}
    for name, val in (("dark", -9), ("bright", -4)):
        cap.set(cv2.CAP_PROP_EXPOSURE, val)
        img = grab(cap, warm=12)
        if img is None:
            log(f"  exposure={val}: no frame"); continue
        b = brightness(img)
        exp_bright[name] = b
        readback = cap.get(cv2.CAP_PROP_EXPOSURE)
        ep = os.path.join(FRAME_DIR, f"02_exposure_{name}_{val}.png")
        cv2.imwrite(ep, img)
        log(f"  exposure set {val:>3} (readback {readback:>6.1f})  mean_brightness={b:6.1f}  -> {ep}")
    if len(exp_bright) == 2:
        delta = abs(exp_bright["bright"] - exp_bright["dark"])
        responds = delta > 10  # >10 gray levels between settings
        results["exposure"] = responds
        log(f"  brightness delta bright-dark = {delta:.1f}")
        log(f"  EXPOSURE RESPONDS: {'YES' if responds else 'NO -- control ignored'}")
    else:
        results["exposure"] = False

    # ---------------- WHITE BALANCE TEST ----------------
    log("\n=== WHITE BALANCE control test ===")
    wb_off = cap.set(cv2.CAP_PROP_AUTO_WB, 0)
    log(f"  disable auto white-balance accepted: {wb_off}")
    wb_reads = []
    for val in (3000, 6500):
        set_ok = cap.set(cv2.CAP_PROP_WB_TEMPERATURE, val)
        grab(cap, warm=6)
        rb = cap.get(cv2.CAP_PROP_WB_TEMPERATURE)
        wb_reads.append(rb)
        log(f"  WB temp set {val} (accepted {set_ok}, readback {rb:.0f})")
    wb_ok = len(set(round(x) for x in wb_reads)) > 1 or any(w in (3000, 6500) for w in [round(x) for x in wb_reads])
    results["white_balance"] = wb_ok
    log(f"  WHITE BALANCE settable: {'YES' if wb_ok else 'INCONCLUSIVE (backend may not expose readback)'}")

    # ---------------- DEAD PIXEL HINT ----------------
    log("\n=== Dead/stuck pixel hint (from baseline) ===")
    if base is not None:
        g = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(g, (5, 5), 0)
        diff = cv2.absdiff(g, blur)
        hot = int((diff > 60).sum())
        log(f"  isolated high-contrast pixels: {hot}  "
            f"({'clean' if hot < 50 else 'inspect the frames -- could be dust or dead pixels'})")

    cap.release()

    # ---------------- VERDICT ----------------
    log("\n" + "=" * 48)
    log("SUMMARY")
    log("=" * 48)
    for k in ("resolution", "focus", "exposure", "white_balance"):
        v = results.get(k)
        log(f"  {k:<15}: {'PASS' if v else 'CHECK'}")
    core = results.get("focus") and results.get("exposure") and results.get("resolution")
    log("-" * 48)
    if core:
        log("  OVERALL: Camera responds to manual UVC controls over OpenCV.")
        log("           This is what your ArUco pipeline needs. GOOD BUY.")
    else:
        log("  OVERALL: One or more manual controls did NOT respond.")
        log("           Review the per-test lines above before buying.")
    log("\n  Open the images in ./frames to eyeball sharpness, glare,")
    log("  colour, and dead pixels.")

if __name__ == "__main__":
    main()
