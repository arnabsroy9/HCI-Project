#!/usr/bin/env python
# =============================================================
#  generate_sheets.py  --  print-ready assets for the
#  "Tokens on a Timeline" tangible diarization-correction rig.
#
#  Produces two vector PDFs at EXACT millimetre scale:
#    timeline_a3.pdf : A3-landscape generic timeline sheet with
#                      4 corner ArUco fiducials (homography ref),
#                      a linear time axis, and N speaker lanes.
#                      Generic across clips -- segments live on
#                      screen, NOT on the paper.
#    tokens.pdf      : one ArUco speaker token per speaker, on A4,
#                      with quiet zones and cut guides.
#
#  Marker scheme (all DICT_4X4_50):
#    IDs 0..3   -> corner fiducials (frame reference)
#    IDs 10..   -> speaker tokens (S1=10, S2=11, S3=12, ...)
#  Keeping the ranges disjoint lets the tracker separate the
#  fixed sheet-reference markers from the movable speaker tokens.
#
#  Print at 100% / "Actual size". Never "fit to page".
#
#  Usage:
#     python generate_sheets.py                 # 60s clip, 3 speakers
#     python generate_sheets.py --duration 90 --speakers 3
# =============================================================

import argparse
import cv2
import numpy as np
from reportlab.lib.pagesizes import A3, A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

ARUCO = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
CORNER_IDS = [0, 1, 2, 3]          # TL, TR, BR, BL
SPEAKER_ID0 = 10                   # S1=10, S2=11, ...
BOUNDARY_ID0 = 20                  # boundary-handle token(s): 20, 21, ...
PLAYBACK_ID0 = 30                  # playback token (STOP/PLAY/PAUSE + seek)

# ---------- ArUco -> vector grid ----------
def marker_grid(marker_id, cells=6, up=12):
    """Return a cells x cells bool array (True = black square).
    DICT_4X4_50 markers are 6x6 cells (4 data + 1 border ring)."""
    img = cv2.aruco.generateImageMarker(ARUCO, marker_id, cells * up)
    grid = np.zeros((cells, cells), dtype=bool)
    for r in range(cells):
        for c in range(cells):
            y = int((r + 0.5) * up)
            x = int((c + 0.5) * up)
            grid[r, c] = img[y, x] < 128
    return grid

def draw_marker(c, cx, cy_top, size, marker_id, page_h):
    """Draw marker centered at (cx, cy_top) in TOP-LEFT mm coords."""
    grid = marker_grid(marker_id)
    n = grid.shape[0]
    cell = size / n
    x_left = cx - size / 2.0
    y_top = cy_top - size / 2.0
    c.setFillColorRGB(0, 0, 0)
    for r in range(n):
        for col in range(n):
            if grid[r, col]:
                x = x_left + col * cell
                yt = y_top + r * cell
                # reportlab origin is bottom-left; convert:
                c.rect(x * mm, (page_h - (yt + cell)) * mm,
                       cell * mm, cell * mm, stroke=0, fill=1)

# ---------- timeline sheet ----------
def build_timeline(path, duration_s, n_speakers):
    PW, PH = 420.0, 297.0                      # A3 landscape, mm
    c = canvas.Canvas(path, pagesize=landscape(A3))

    def X(x): return x * mm
    def Y(y): return (PH - y) * mm             # top-left -> pdf

    # --- corner fiducials ---
    m = 25.0                                   # marker size mm
    centers = [(25, 25), (PW - 25, 25), (PW - 25, PH - 25), (25, PH - 25)]
    for mid, (cx, cy) in zip(CORNER_IDS, centers):
        draw_marker(c, cx, cy, m, mid, PH)

    # --- time axis ---
    x0, x1 = 40.0, 400.0                        # t=0 .. t=duration
    y_axis = 48.0
    mmps = (x1 - x0) / duration_s               # mm per second
    c.setStrokeColorRGB(0, 0, 0); c.setLineWidth(1.8)
    c.line(X(x0), Y(y_axis), X(x1), Y(y_axis))

    lane_top, lane_bot = 56.0, 206.0
    gap = 5.0
    lane_h = ((lane_bot - lane_top) - gap * (n_speakers - 1)) / n_speakers

    # major (5s) + minor (1s) ticks, gridlines, labels
    c.setFont("Helvetica-Bold", 9)
    s = 0
    while s <= duration_s + 1e-6:
        x = x0 + s * mmps
        major = (s % 5 == 0)
        c.setStrokeColorRGB(0, 0, 0); c.setLineWidth(1.5 if major else 0.8)
        tick = 3.5 if major else 1.8
        c.line(X(x), Y(y_axis), X(x), Y(y_axis - tick))
        if major:
            c.setFillColorRGB(0, 0, 0)
            c.drawCentredString(X(x), Y(y_axis - 7), f"{s}s")
            c.setStrokeColorRGB(0.7, 0.7, 0.7); c.setLineWidth(0.6)   # gridline
            c.line(X(x), Y(lane_top), X(x), Y(lane_bot))
        s += 1

    # --- speaker lanes ---
    for i in range(n_speakers):
        top = lane_top + i * (lane_h + gap)
        c.setStrokeColorRGB(0.2, 0.2, 0.2); c.setLineWidth(1.4)
        c.rect(X(x0), Y(top + lane_h), (x1 - x0) * mm, lane_h * mm,
               stroke=1, fill=0)
        c.setFillColorRGB(0, 0, 0); c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(X(x0 / 2 + 4), Y(top + lane_h / 2 + 2), f"S{i+1}")

    # --- seek strip (2nd timeline: place the playback token here to jump) ---
    seek_y0, seek_y1 = 214.0, 230.0
    seek_axis = (seek_y0 + seek_y1) / 2
    c.setStrokeColorRGB(0.2, 0.2, 0.2); c.setLineWidth(1.4)
    c.rect(X(x0), Y(seek_y1), (x1 - x0) * mm, (seek_y1 - seek_y0) * mm, stroke=1, fill=0)
    c.setStrokeColorRGB(0, 0, 0); c.setLineWidth(1.6)
    c.line(X(x0), Y(seek_axis), X(x1), Y(seek_axis))
    s = 0
    while s <= duration_s + 1e-6:
        x = x0 + s * mmps
        if s % 5 == 0:
            c.setLineWidth(1.4); c.line(X(x), Y(seek_axis), X(x), Y(seek_axis - 3))
            c.setFont("Helvetica", 7); c.drawCentredString(X(x), Y(seek_axis + 4.5), f"{s}s")
        s += 1
    c.setFillColorRGB(0, 0, 0); c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(X(x0 / 2 + 4), Y(seek_axis + 1), "SEEK")

    # --- transport boxes (playback token: STOP -> PLAY -> PAUSE) ---
    box_w, box_h, box_top, box_gap = 55.0, 26.0, 240.0, 12.0
    total = 3 * box_w + 2 * box_gap
    bx0 = PW / 2 - total / 2
    boxes = {}
    for idx, (name, key) in enumerate((("STOP", "stop"), ("PLAY", "play"),
                                       ("PAUSE", "pause"))):
        left = bx0 + idx * (box_w + box_gap)
        c.setStrokeColorRGB(0, 0, 0); c.setLineWidth(1.8)
        c.rect(X(left), Y(box_top + box_h), box_w * mm, box_h * mm, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(X(left + box_w / 2), Y(box_top + box_h / 2 + 2), name)
        boxes[key] = (round(left, 1), round(left + box_w, 1), box_top, box_top + box_h)
    c.setFont("Helvetica", 8)
    c.drawCentredString(X(PW / 2), Y(box_top - 3),
                        "Playback token: rest in STOP; slide to PLAY / PAUSE. "
                        "Place on the SEEK strip to jump.")

    # --- title (top center, clear of the corner fiducials' quiet zones) ---
    c.setFillColorRGB(0, 0, 0); c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(X(PW / 2), Y(16),
                        "Tokens on a Timeline  |  speaker-diarization correction")

    # --- scale-check bar (top, under the title) ---
    bxs, bys = 185.0, 30.0
    c.setStrokeColorRGB(0, 0, 0); c.setLineWidth(1.2)
    c.line(X(bxs), Y(bys), X(bxs + 50), Y(bys))
    for xx in (bxs, bxs + 50):
        c.line(X(xx), Y(bys - 2), X(xx), Y(bys + 2))
    c.setFont("Helvetica", 7)
    c.drawCentredString(X(bxs + 25), Y(bys + 4.5),
                        "50 mm  -  print at 100% / Actual size (measure to confirm)")

    c.showPage(); c.save()
    transport = {"seek": {"x0": x0, "x1": x1, "y0": seek_y0, "y1": seek_y1},
                 **{k: {"x0": v[0], "x1": v[1], "y0": v[2], "y1": v[3]}
                    for k, v in boxes.items()}}
    return dict(x0=x0, x1=x1, mmps=mmps, corner_centers=centers,
                corner_ids=CORNER_IDS, marker_mm=m, transport=transport)

# ---------- token sheet ----------
def build_tokens(path, n_speakers, n_handles=1):
    PW, PH = 210.0, 297.0                        # A4 portrait, mm
    c = canvas.Canvas(path, pagesize=A4)

    def X(x): return x * mm
    def Y(y): return (PH - y) * mm

    tok = 30.0                                   # marker size mm
    quiet = 6.0                                  # white quiet zone each side
    cut = tok + 2 * quiet                        # cut-guide square

    c.setFont("Helvetica-Bold", 14)
    c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(X(PW / 2), Y(16), "Tokens (cut out, glue to cubes)")
    c.setFont("Helvetica", 8)
    c.drawCentredString(X(PW / 2), Y(23),
                        "DICT_4X4_50 | Print at 100% / Actual size | matte paper, laminate matte")
    c.setFont("Helvetica", 8)
    c.drawCentredString(X(PW / 2), Y(29),
                        "Speaker token = drop in a segment to reassign it.  "
                        "Boundary token = snaps to nearest edge, slide to move it.")

    # one flat list: speaker tokens, boundary handle(s), playback token
    items = [(f"S{i+1}", SPEAKER_ID0 + i, "speaker") for i in range(n_speakers)]
    items += [(f"B{j+1}", BOUNDARY_ID0 + j, "boundary") for j in range(n_handles)]
    items += [("P1", PLAYBACK_ID0, "playback")]

    kind_label = {"speaker": "SPEAKER", "boundary": "BOUNDARY HANDLE",
                  "playback": "PLAYBACK"}
    top0 = 30.0
    step = cut + 8.0                              # fit 5 tokens on A4
    for i, (name, mid, kind) in enumerate(items):
        cy = top0 + cut / 2 + i * step
        # cut guide: solid for speakers, dashed for the special tokens
        if kind == "speaker":
            c.setStrokeColorRGB(0.55, 0.55, 0.55); c.setLineWidth(0.8); c.setDash()
        else:
            c.setStrokeColorRGB(0.3, 0.3, 0.3); c.setLineWidth(1.2); c.setDash(3, 2)
        c.rect(X(PW / 2 - cut / 2), Y(cy + cut / 2), cut * mm, cut * mm,
               stroke=1, fill=0)
        c.setDash()
        draw_marker(c, PW / 2, cy, tok, mid, PH)
        c.setFillColorRGB(0, 0, 0); c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(X(PW / 2), Y(cy + cut / 2 + 6),
                            f"{name}  (id {mid}, {tok:.0f} mm)  -- {kind_label[kind]}")

    c.showPage(); c.save()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--speakers", type=int, default=3)
    ap.add_argument("--handles", type=int, default=1,
                    help="boundary-handle tokens (ids 20+)")
    ap.add_argument("--outdir", default=".")
    args = ap.parse_args()

    import os, json
    os.makedirs(args.outdir, exist_ok=True)
    tl = os.path.join(args.outdir, "timeline_a3.pdf")
    tk = os.path.join(args.outdir, "tokens.pdf")
    zf = os.path.join(args.outdir, "transport_zones.json")

    meta = build_timeline(tl, args.duration, args.speakers)
    build_tokens(tk, args.speakers, args.handles)
    json.dump({"x0_mm": meta["x0"], "mm_per_second": meta["mmps"],
               "duration_s": args.duration, "zones": meta["transport"]},
              open(zf, "w"), indent=2)

    print("Wrote:")
    print("  " + tl)
    print("  " + tk)
    print("  " + zf)
    print("\nMapping constants (feed these to the tracker):")
    print(f"  x0_mm         = {meta['x0']}")
    print(f"  mm_per_second = {meta['mmps']:.4f}")
    print(f"  clip_seconds  = {args.duration}")
    print(f"  corner ids    = {meta['corner_ids']} (TL,TR,BR,BL)")
    print(f"  corner centers (mm, top-left) = {meta['corner_centers']}")

if __name__ == "__main__":
    main()
