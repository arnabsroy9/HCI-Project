#!/usr/bin/env python
# =============================================================
#  0_probe_indices.py  --  map camera indices to their max
#  resolution so we can tell the C920 apart from the built-in
#  laptop webcam. The C920 does true 1920x1080; most internal
#  laptop cams top out at 1280x720. Run this first.
# =============================================================
import cv2

print("OpenCV", cv2.__version__)
print(f"{'idx':>3}  {'opened':>6}  {'max WxH':>12}  {'fps':>5}")
print("-" * 34)
for i in range(6):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap.release()
        continue
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    ok, _ = cap.read()
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    tag = "  <- 1080p (likely the C920)" if (w >= 1920 and h >= 1080) else ""
    print(f"{i:>3}  {str(ok):>6}  {w:>5}x{h:<6}  {fps:>5.0f}{tag}")
    cap.release()
print("\nUse the 1080p index with:  python 2_check_c920.py --index N")
