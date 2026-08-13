#!/usr/bin/env python
# =============================================================
#  analyze.py  --  turn operation logs into analysis-ready
#  tables. Replays each trial's log against its answer key to
#  recover, per injected error: whether it was corrected, the
#  residual (boundary), and the CORRECTION TIME (elapsed at the
#  op that first fixed it).
#
#  Emits two CSVs:
#    errors.csv  -- one row per injected error per trial.
#                   This is the GLMM unit (Section 5.8):
#                   corrected ~ modality * error_type + (1|participant) + (1|clip)
#    trials.csv  -- one row per trial (aggregates).
#
#  Usage:  python analyze.py            # scans ./logs
# =============================================================

import csv, glob, json, os

BASE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(BASE, "logs")
STIMULI = os.path.join(BASE, "stimuli")
MIN_SEG = 0.4
BOUND_TOL = 0.15


def apply_op(segs, op):
    if op["op"] == "reassign":
        segs[int(op["segment"])]["speaker"] = op["speaker"]
    elif op["op"] == "move_boundary":
        i = int(op["boundary"]); t = float(op["t"])
        lo = segs[i]["start"] + MIN_SEG
        hi = segs[i + 1]["end"] - MIN_SEG
        t = round(min(max(t, lo), hi), 3)
        segs[i]["end"] = t; segs[i + 1]["start"] = t


def err_corrected(segs, e):
    if e["type"] == "confusion":
        return segs[e["segment_id"]]["speaker"] == e["correct_speaker"], None
    cur = segs[e["boundary_index"]]["end"]
    r = abs(cur - e["correct_t"])
    return r <= BOUND_TOL, round(r, 3)


def replay(jsonl):
    """Return (meta, [error rows]) for one trial log, or None if unusable."""
    lines = [json.loads(l) for l in open(jsonl) if l.strip()]
    start = next((r for r in lines if r.get("event") == "session_start"), None)
    if not start:
        return None
    clip = start["clip"]
    hyp = json.load(open(os.path.join(STIMULI, clip, "hypothesis.json")))
    key = json.load(open(os.path.join(STIMULI, clip, "answer_key.json")))
    segs = [dict(s) for s in hyp["segments"]]
    errors = key["injected_errors"]
    fixed_at = {}                       # error index -> elapsed at first correction

    for r in lines:
        if r.get("event") != "op":
            continue
        apply_op(segs, r["op"])
        for j, e in enumerate(errors):
            if j in fixed_at:
                continue
            ok, _ = err_corrected(segs, e)
            if ok:
                fixed_at[j] = r["elapsed_s"]

    meta = {"participant": start["participant"], "condition": start["condition"],
            "clip": clip, "log": os.path.basename(jsonl)}
    rows = []
    for j, e in enumerate(errors):
        ok, resid = err_corrected(segs, e)
        rows.append({**meta, "error_id": j, "error_type": e["type"],
                     "corrected": int(ok),
                     "residual_s": resid if e["type"] == "boundary" else "",
                     "correction_time_s": fixed_at.get(j, "")})
    return meta, rows


def main():
    logs = sorted(glob.glob(os.path.join(LOGS, "*.jsonl")))
    if not logs:
        print("no logs found in", LOGS); return

    all_rows, trials = [], []
    for jl in logs:
        res = replay(jl)
        if not res:
            continue
        meta, rows = res
        all_rows.extend(rows)
        conf = [r for r in rows if r["error_type"] == "confusion"]
        bnd = [r for r in rows if r["error_type"] == "boundary"]
        resids = [r["residual_s"] for r in bnd if r["corrected"]]
        trials.append({**meta,
                       "conf_acc": round(sum(r["corrected"] for r in conf) / len(conf), 3) if conf else "",
                       "bnd_acc": round(sum(r["corrected"] for r in bnd) / len(bnd), 3) if bnd else "",
                       "bnd_mean_residual_s": round(sum(resids) / len(resids), 3) if resids else ""})

    with open(os.path.join(BASE, "errors.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader(); w.writerows(all_rows)
    with open(os.path.join(BASE, "trials.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(trials[0].keys()))
        w.writeheader(); w.writerows(trials)

    print(f"{len(trials)} trial(s), {len(all_rows)} error rows")
    print("  -> errors.csv (GLMM unit), trials.csv\n")
    # quick aggregate by condition x error_type
    print(f"{'condition':<10}{'error_type':<12}{'n':>4}{'corrected':>11}{'accuracy':>10}")
    agg = {}
    for r in all_rows:
        k = (r["condition"], r["error_type"])
        agg.setdefault(k, []).append(r["corrected"])
    for (cond, et), v in sorted(agg.items()):
        print(f"{cond:<10}{et:<12}{len(v):>4}{sum(v):>11}{sum(v)/len(v):>10.3f}")


if __name__ == "__main__":
    main()
