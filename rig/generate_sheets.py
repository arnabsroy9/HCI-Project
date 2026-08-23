#!/usr/bin/env python
# =============================================================
#  generate_sheets.py  --  print-ready assets for the
#  "Tokens on a Timeline" tangible diarization-correction rig.
#
#  Produces two vector PDFs at EXACT millimetre scale:
#    timeline_a3.pdf : A3-landscape generic timeline sheet with
#                      4 corner ArUco fiducials (homography ref) and
#                      the clip's timeline FOLDED across N band rows
#                      (e.g. 3 x 20 s) for finer placement resolution.
#                      A token's row picks the band, its x picks the
#                      time within it. Generic across clips -- segments
#                      live on screen, NOT on the paper.
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
def build_timeline(path, duration_s, n_bands):
    PW, PH = 420.0, 297.0                      # A3 landscape, mm
    c = canvas.Canvas(path, pagesize=landscape(A3))

    def X(x): return x * mm
    def Y(y): return (PH - y) * mm             # top-left -> pdf

    # --- corner fiducials ---
    m = 25.0                                   # marker size mm
    centers = [(25, 25), (PW - 25, 25), (PW - 25, PH - 25), (25, PH - 25)]
    for mid, (cx, cy) in zip(CORNER_IDS, centers):
        draw_marker(c, cx, cy, m, mid, PH)

    # --- N time-band rows ---
    # The single 60 s timeline is FOLDED across n_bands rows for finer
    # resolution (e.g. 3 rows of 20 s => 3x the mm/second of one 60 s axis).
    # A token's ROW selects the band, its x selects the time within that band;
    # global time = band.t0 + (x - x0)/band.mm_per_s. Speakers are still carried
    # by the tokens (id + colour), NOT by the rows.
    x0, x1 = 40.0, 400.0
    band_top, band_bot = 58.0, 206.0             # matches the printed sheet's bands
    bgap = 9.0
    band_h = ((band_bot - band_top) - bgap * (n_bands - 1)) / n_bands
    bs = duration_s / n_bands                   # seconds per band
    mmps_band = (x1 - x0) / bs                   # mm per second within a band
    mmps = (x1 - x0) / duration_s               # global mm/s (for the seek strip)
    bands = []
    for i in range(n_bands):
        top = band_top + i * (band_h + bgap)
        axis_y = top + band_h * 0.62
        t0, t1 = i * bs, (i + 1) * bs
        # faint 5 s gridlines down the band
        c.setStrokeColorRGB(0.72, 0.72, 0.72); c.setLineWidth(0.6)
        s = 0
        while s <= bs + 1e-6:
            if s % 5 == 0:
                x = x0 + s * mmps_band
                c.line(X(x), Y(top), X(x), Y(top + band_h))
            s += 1
        # placement rectangle
        c.setStrokeColorRGB(0.2, 0.2, 0.2); c.setLineWidth(1.4)
        c.rect(X(x0), Y(top + band_h), (x1 - x0) * mm, band_h * mm, stroke=1, fill=0)
        # band time axis + ticks (labelled with GLOBAL seconds)
        c.setStrokeColorRGB(0, 0, 0); c.setLineWidth(1.6)
        c.line(X(x0), Y(axis_y), X(x1), Y(axis_y))
        c.setFont("Helvetica-Bold", 8)
        s = 0
        while s <= bs + 1e-6:
            x = x0 + s * mmps_band
            major = (s % 5 == 0)
            c.setStrokeColorRGB(0, 0, 0); c.setLineWidth(1.4 if major else 0.7)
            tick = 3.5 if major else 1.8
            c.line(X(x), Y(axis_y), X(x), Y(axis_y - tick))
            if major:
                c.setFillColorRGB(0, 0, 0)
                c.drawCentredString(X(x), Y(axis_y - 7), f"{int(t0 + s)}s")
            s += 1
        # left label: the band's global time range
        c.setFillColorRGB(0, 0, 0); c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(X(x0 / 2 + 4), Y(top + band_h / 2 - 2),
                            f"{int(t0)}-{int(t1)}s")
        bands.append({"index": i, "t0": t0, "t1": t1, "x0": x0, "x1": x1,
                      "mm_per_s": round(mmps_band, 4),
                      "y0": round(top, 1), "y1": round(top + band_h, 1)})

    # --- how-to note (playback is on-screen with the mouse, both conditions) ---
    c.setFillColorRGB(0.25, 0.25, 0.25); c.setFont("Helvetica", 9)
    c.drawCentredString(X(PW / 2), Y(band_bot + 16),
                        "Speaker token on a chunk = set who is talking.   "
                        "Boundary handle = grab the nearer edge of that chunk and slide.   "
                        "Listen with the on-screen player.")

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
    return dict(x0=x0, x1=x1, mmps=mmps, bands=bands, corner_centers=centers,
                corner_ids=CORNER_IDS, marker_mm=m)

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

    # one flat list: speaker tokens + boundary handle(s) (playback is on-screen)
    items = [(f"S{i+1}", SPEAKER_ID0 + i, "speaker") for i in range(n_speakers)]
    items += [(f"B{j+1}", BOUNDARY_ID0 + j, "boundary") for j in range(n_handles)]

    kind_label = {"speaker": "SPEAKER", "boundary": "BOUNDARY HANDLE"}
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
    ap.add_argument("--bands", type=int, default=3,
                    help="fold the timeline across this many rows (resolution)")
    ap.add_argument("--handles", type=int, default=1,
                    help="boundary-handle tokens (ids 20+)")
    ap.add_argument("--outdir", default=".")
    args = ap.parse_args()

    import os, json
    os.makedirs(args.outdir, exist_ok=True)
    tl = os.path.join(args.outdir, "timeline_a3.pdf")
    tk = os.path.join(args.outdir, "tokens.pdf")
    zf = os.path.join(args.outdir, "transport_zones.json")

    meta = build_timeline(tl, args.duration, args.bands)
    build_tokens(tk, args.speakers, args.handles)
    json.dump({"x0_mm": meta["x0"], "mm_per_second": meta["mmps"],
               "duration_s": args.duration, "bands": meta["bands"]},
              open(zf, "w"), indent=2)

    print("Wrote:")
    print("  " + tl)
    print("  " + tk)
    print("  " + zf)
    print("\nMapping (the tracker reads bands from transport_zones.json):")
    print(f"  x0_mm         = {meta['x0']}")
    print(f"  seek mm/s     = {meta['mmps']:.4f}   (60 s seek strip)")
    print(f"  bands         = {len(meta['bands'])} x "
          f"{args.duration / len(meta['bands']):.0f}s  "
          f"@ {meta['bands'][0]['mm_per_s']:.2f} mm/s "
          f"({meta['mmps']:.2f} -> {meta['bands'][0]['mm_per_s']:.2f}, "
          f"{meta['bands'][0]['mm_per_s'] / meta['mmps']:.1f}x resolution)")
    for b in meta["bands"]:
        print(f"    band {b['index']}: t {b['t0']:.0f}-{b['t1']:.0f}s  "
              f"y {b['y0']}-{b['y1']} mm")
    print(f"  corner ids    = {meta['corner_ids']} (TL,TR,BR,BL)")

if __name__ == "__main__":
    main()
