#!/usr/bin/env python
# =============================================================
#  select_recordings.py  --  scan Bengali-Loop / DL Sprint 4.0
#  diarization label CSVs and flag which recordings are worth
#  downloading in full: exactly N speakers (default 3), long
#  enough for a clip, and dense with speaker turns. For each
#  qualifying recording it suggests a clip window that contains
#  all N speakers, so you can fetch just those few audio files
#  (or cut them in a Kaggle notebook) instead of the 15 GB.
#
#  Works on either layout:
#    - one combined CSV with a recording/file id column, or
#    - one CSV per recording (the filename is the id).
#  Columns are auto-detected (start / end / speaker / id).
#
#  Usage:
#     python select_recordings.py <labels.csv | labels_dir>
#     python select_recordings.py data/train --speakers 3 --win 90
# =============================================================

import argparse, csv, glob, json, os, re
from collections import defaultdict


def find_col(fields, patterns):
    for p in patterns:
        for f in fields:
            if re.search(p, f, re.I):
                return f
    return None


def load_csv(path, recs):
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        fields = r.fieldnames or []
        sc = find_col(fields, [r"^start", r"start", r"onset", r"begin"])
        ec = find_col(fields, [r"^end", r"end", r"offset", r"stop"])
        pc = find_col(fields, [r"speaker", r"\bspk", r"^label$"])
        rc = find_col(fields, [r"file", r"record", r"audio", r"uri",
                               r"utt", r"clip", r"\bname", r"\bid$"])
        if not (sc and ec and pc):
            return None
        base = os.path.splitext(os.path.basename(path))[0]
        for row in r:
            try:
                s, e = float(row[sc]), float(row[ec])
            except (TypeError, ValueError, KeyError):
                continue
            spk = str(row[pc]).strip()
            rid = str(row[rc]).strip() if rc and row.get(rc) else base
            recs[rid].append((s, e, spk))
        return (sc, ec, pc, rc)


def analyze(segs):
    segs = sorted(segs)
    spks = sorted(set(s[2] for s in segs))
    t0 = min(s for s, _, _ in segs)
    t1 = max(e for _, e, _ in segs)
    dur = t1 - t0
    changes = sum(1 for i in range(1, len(segs)) if segs[i][2] != segs[i - 1][2])
    overlaps = sum(1 for i in range(1, len(segs)) if segs[i][0] < segs[i - 1][1] - 1e-6)
    return {"n_speakers": len(spks), "speakers": spks, "t0": t0, "duration": dur,
            "n_segments": len(segs), "turns": changes,
            "turns_per_min": changes / (dur / 60) if dur > 0 else 0,
            "mean_seg_s": sum(e - s for s, e, _ in segs) / len(segs),
            "overlaps": overlaps}


def best_window(segs, win, need):
    """Best clip window (by turn count) containing >= need speakers."""
    segs = sorted(segs)
    t1 = max(e for _, e, _ in segs)
    best = None
    for st, _, _ in segs:
        en = st + win
        if en > t1:
            break
        inwin = [g for g in segs if g[0] < en and g[1] > st]
        if len(set(g[2] for g in inwin)) >= need:
            turns = sum(1 for i in range(1, len(inwin)) if inwin[i][2] != inwin[i - 1][2])
            if best is None or turns > best[1]:
                best = (round(st, 2), turns, len(inwin))
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="a labels CSV or a directory of CSVs")
    ap.add_argument("--speakers", type=int, default=3)
    ap.add_argument("--win", type=float, default=90.0, help="target clip seconds")
    ap.add_argument("--out", default="selection.json")
    args = ap.parse_args()

    files = ([args.path] if os.path.isfile(args.path)
             else sorted(glob.glob(os.path.join(args.path, "**", "*.csv"), recursive=True)))
    if not files:
        print("no CSV files found at", args.path); return

    recs = defaultdict(list)
    schema = None
    for fp in files:
        got = load_csv(fp, recs)
        schema = schema or got
    if not recs:
        print("could not parse start/end/speaker columns; check the CSV headers")
        return
    print(f"parsed {len(files)} CSV(s), {len(recs)} recording(s); "
          f"columns detected: start/end/speaker/id = {schema}\n")

    rows = []
    for rid, segs in recs.items():
        a = analyze(segs)
        a["recording"] = rid
        a["window"] = (best_window(segs, args.win, args.speakers)
                       if a["duration"] >= args.win else None)
        rows.append(a)

    qual = [a for a in rows
            if a["n_speakers"] == args.speakers and a["window"] is not None]
    qual.sort(key=lambda a: a["turns_per_min"], reverse=True)

    print(f"{'recording':<26}{'spk':>4}{'dur(s)':>8}{'segs':>6}"
          f"{'turns/min':>10}{'ovl':>5}  clip@start(turns)")
    print("-" * 82)
    for a in qual:
        w = a["window"]
        print(f"{a['recording'][:25]:<26}{a['n_speakers']:>4}{a['duration']:>8.0f}"
              f"{a['n_segments']:>6}{a['turns_per_min']:>10.1f}{a['overlaps']:>5}"
              f"  {w[0]:.1f}s ({w[1]} turns)")
    print(f"\n{len(qual)} recording(s) match exactly {args.speakers} speakers "
          f"with a {args.win:.0f}s clip window.")
    if not qual:
        skip = sorted(rows, key=lambda a: abs(a["n_speakers"] - args.speakers))[:5]
        print("closest by speaker count:",
              [(a["recording"][:16], a["n_speakers"]) for a in skip])

    sel = [{"recording": a["recording"], "n_speakers": a["n_speakers"],
            "duration_s": round(a["duration"], 1), "turns_per_min": round(a["turns_per_min"], 1),
            "clip_start_s": a["window"][0], "clip_len_s": args.win} for a in qual]
    json.dump(sel, open(args.out, "w"), indent=2)
    print(f"-> wrote {args.out} ({len(sel)} candidates) for the importer/notebook")


if __name__ == "__main__":
    main()
