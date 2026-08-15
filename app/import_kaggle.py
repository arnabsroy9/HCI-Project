#!/usr/bin/env python
# =============================================================
#  import_kaggle.py  --  turn downloaded Bengali-Loop recordings
#  into project stimuli. For each recording in the selector's
#  selection.json that has a local audio file, it cuts the chosen
#  window, builds contiguous 3-speaker ground-truth segments,
#  injects controlled errors, and writes stimuli/<clip>/ in the
#  existing contract (audio.wav + hypothesis/answer_key/meta).
#
#  The window is forced to a contiguous partition (small silence
#  gaps absorbed into the preceding turn) so it matches the app's
#  shared-boundary model; the audio itself is untouched.
#
#  Usage (from app/):
#     python import_kaggle.py --limit 5
#     python import_kaggle.py --clip-len 60 --confusion 4 --boundary 4
# =============================================================

import argparse, json, os, sys, wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from select_recordings import parse_time                     # HH:MM:SS -> s
import make_stimulus as ms                                   # inject(), SPEAKERS

BASE = os.path.dirname(os.path.abspath(__file__))
MIN_SEG = ms.MIN_SEG


def read_segs(csv_path):
    import csv, re
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f); fl = r.fieldnames or []
        def col(pats):
            for p in pats:
                for c in fl:
                    if re.search(p, c, re.I):
                        return c
        sc = col([r"^start", r"start"]); ec = col([r"^end", r"end"])
        pc = col([r"speaker", r"\bspk", r"^label$"])
        out = []
        for row in r:
            try:
                out.append((parse_time(row[sc]), parse_time(row[ec]), str(row[pc]).strip()))
            except (TypeError, ValueError, KeyError):
                pass
    return sorted(out)


def cut_wav(src, dst, t0, length):
    w = wave.open(src, "rb")
    fr, nch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
    w.setpos(int(t0 * fr))
    frames = w.readframes(int(length * fr))
    w.close()
    o = wave.open(dst, "wb")
    o.setnchannels(nch); o.setsampwidth(sw); o.setframerate(fr)
    o.writeframes(frames); o.close()
    return len(frames) // (sw * nch) / fr


def window_segments(segs, t0, win):
    """Contiguous, window-relative, speakers relabeled S1/S2/S3."""
    w = sorted((max(s, t0) - t0, min(e, t0 + win) - t0, spk)
               for s, e, spk in segs if s < t0 + win and e > t0)
    order = {}
    for _, _, spk in w:
        order.setdefault(spk, f"S{len(order) + 1}")
    out, prev = [], 0.0
    for s, e, spk in w:
        s = prev
        if e <= s + MIN_SEG:
            continue
        out.append({"start": round(s, 3), "end": round(e, 3), "speaker": order[spk]})
        prev = e
    for i, seg in enumerate(out):
        seg["id"] = i
    if out:
        out[-1]["end"] = round(min(win, out[-1]["end"]), 3)
    return out, sorted(set(order.values()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", default=os.path.join(BASE, "..", "data", "selection.json"))
    ap.add_argument("--annotation", default=os.path.join(BASE, "..", "data", "annotation"))
    ap.add_argument("--audio", default=os.path.join(BASE, "..", "data", "audio"))
    ap.add_argument("--out", default=os.path.join(BASE, "stimuli"))
    ap.add_argument("--clip-len", type=float, default=60.0)
    ap.add_argument("--confusion", type=int, default=4)
    ap.add_argument("--boundary", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--limit", type=int, default=99)
    args = ap.parse_args()

    sel = json.load(open(args.selection))
    made = 0
    for entry in sel:
        rid = entry["recording"]
        wav = os.path.join(args.audio, rid + ".wav")
        csv_path = os.path.join(args.annotation, rid + ".csv")
        if not (os.path.exists(wav) and os.path.exists(csv_path)):
            continue
        if made >= args.limit:
            break
        t0 = entry["clip_start_s"]
        gt, speakers = window_segments(read_segs(csv_path), t0, args.clip_len)
        if len(speakers) != 3:
            print(f"  skip {rid}: window has {len(speakers)} speakers, not 3")
            continue
        if len(gt) < args.boundary + 2:
            print(f"  skip {rid}: only {len(gt)} segments")
            continue
        import random
        hyp, errors = ms.inject(gt, args.confusion, args.boundary,
                                random.Random(args.seed + made))
        clip = rid
        d = os.path.join(args.out, clip); os.makedirs(d, exist_ok=True)
        dur = cut_wav(wav, os.path.join(d, "audio.wav"), t0, args.clip_len)
        json.dump({"clip": clip, "duration": round(dur, 3), "sample_rate": 16000,
                   "speakers": speakers, "segments": hyp},
                  open(os.path.join(d, "hypothesis.json"), "w"), indent=2)
        json.dump({"clip": clip, "segments": gt, "injected_errors": errors},
                  open(os.path.join(d, "answer_key.json"), "w"), indent=2)
        json.dump({"clip": clip, "source": rid, "window_start_s": round(t0, 2),
                   "duration": round(dur, 3), "n_speakers": 3, "n_segments": len(gt)},
                  open(os.path.join(d, "meta.json"), "w"), indent=2)
        made += 1
        print(f"  {clip}: @ {t0:.1f}s, {len(gt)} segments, "
              f"{args.confusion} confusion + {args.boundary} boundary errors")
    print(f"\nbuilt {made} real-audio stimulus clip(s) in {args.out}")


if __name__ == "__main__":
    main()
