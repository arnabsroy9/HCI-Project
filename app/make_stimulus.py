#!/usr/bin/env python
# =============================================================
#  make_stimulus.py  --  build a sample diarization-correction
#  stimulus: synthetic 3-speaker audio + ground-truth turns +
#  an error-injected hypothesis + an answer key.
#
#  Replace the synthetic audio with a real Bengali-Loop clip
#  later; the JSON contract (hypothesis.json / answer_key.json)
#  stays the same, so nothing downstream changes.
#
#  Usage:
#     python make_stimulus.py --clip clipA --duration 60 --seed 1
# =============================================================

import argparse, json, os, wave, struct, random
import numpy as np

SR = 16000
SPEAKERS = ["S1", "S2", "S3"]
BASE_HZ = {"S1": 140.0, "S2": 190.0, "S3": 240.0}   # distinct "voices"
MIN_SEG = 0.4                                        # s, min segment length


def synth_segment(n, base_hz, rng):
    """A speech-ish tone over n samples: harmonics + syllable AM + noise."""
    t = np.arange(n) / SR
    sig = np.zeros(n)
    vibrato = 1.0 + 0.01 * np.sin(2 * np.pi * 5.0 * t)
    for h, amp in enumerate([1.0, 0.5, 0.33, 0.22, 0.15], start=1):
        sig += amp * np.sin(2 * np.pi * base_hz * h * t * vibrato)
    syl = 0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(3.5, 5.0) * t)   # syllables
    sig *= syl
    sig += 0.02 * rng.standard_normal(n)                              # breath noise
    edge = int(0.02 * SR)                                            # 20 ms fades
    if n > 2 * edge:
        sig[:edge] *= np.linspace(0, 1, edge)
        sig[-edge:] *= np.linspace(1, 0, edge)
    return sig


def build_turns(duration, rng):
    """Contiguous, alternating-speaker ground-truth segments."""
    segs, t, prev, sid = [], 0.0, None, 0
    while t < duration - MIN_SEG:
        dur = min(rng.uniform(1.2, 4.5), duration - t)
        spk = rng.choice([s for s in SPEAKERS if s != prev])
        segs.append({"id": sid, "start": round(t, 3),
                     "end": round(t + dur, 3), "speaker": spk})
        t += dur; prev = spk; sid += 1
    segs[-1]["end"] = round(duration, 3)
    return segs


def render_audio(segs, path):
    total = int(segs[-1]["end"] * SR)
    audio = np.zeros(total)
    rng = np.random.default_rng(0)
    for s in segs:
        a, b = int(s["start"] * SR), int(s["end"] * SR)
        audio[a:b] += synth_segment(b - a, BASE_HZ[s["speaker"]], rng)
    audio /= (np.max(np.abs(audio)) + 1e-9)
    audio = (audio * 0.9 * 32767).astype(np.int16)
    with wave.open(path, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(audio.tobytes())


def inject(segs, n_conf, n_bound, rng):
    """Return (hypothesis, injected_errors). Ground truth is left intact."""
    hyp = [dict(s) for s in segs]
    errors = []

    conf_ids = rng.sample(range(len(hyp)), min(n_conf, len(hyp)))
    for sid in conf_ids:
        correct = hyp[sid]["speaker"]
        wrong = rng.choice([s for s in SPEAKERS if s != correct])
        hyp[sid]["speaker"] = wrong
        errors.append({"type": "confusion", "segment_id": sid,
                       "correct_speaker": correct, "wrong_speaker": wrong})

    internal = list(range(len(hyp) - 1))            # boundary i = between i, i+1
    bound_ids = rng.sample(internal, min(n_bound, len(internal)))
    for i in bound_ids:
        correct_t = hyp[i]["end"]
        lo = hyp[i]["start"] + MIN_SEG
        hi = hyp[i + 1]["end"] - MIN_SEG
        delta = rng.uniform(0.3, 1.2) * rng.choice([-1, 1])
        wrong_t = round(min(max(correct_t + delta, lo), hi), 3)
        hyp[i]["end"] = wrong_t
        hyp[i + 1]["start"] = wrong_t
        errors.append({"type": "boundary", "boundary_index": i,
                       "correct_t": round(correct_t, 3), "wrong_t": wrong_t})
    return hyp, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="clipA")
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--confusion", type=int, default=4)
    ap.add_argument("--boundary", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "stimuli", args.clip)
    os.makedirs(outdir, exist_ok=True)

    gt = build_turns(args.duration, rng)
    render_audio(gt, os.path.join(outdir, "audio.wav"))
    hyp, errors = inject(gt, args.confusion, args.boundary, rng)

    with open(os.path.join(outdir, "hypothesis.json"), "w") as f:
        json.dump({"clip": args.clip, "duration": args.duration,
                   "sample_rate": SR, "speakers": SPEAKERS,
                   "segments": hyp}, f, indent=2)
    with open(os.path.join(outdir, "answer_key.json"), "w") as f:
        json.dump({"clip": args.clip, "segments": gt,
                   "injected_errors": errors}, f, indent=2)
    with open(os.path.join(outdir, "meta.json"), "w") as f:
        json.dump({"clip": args.clip, "duration": args.duration,
                   "n_speakers": len(SPEAKERS),
                   "n_confusion": sum(e["type"] == "confusion" for e in errors),
                   "n_boundary": sum(e["type"] == "boundary" for e in errors),
                   "n_segments": len(gt), "seed": args.seed}, f, indent=2)

    print(f"clip '{args.clip}': {len(gt)} segments, "
          f"{sum(e['type']=='confusion' for e in errors)} confusion + "
          f"{sum(e['type']=='boundary' for e in errors)} boundary errors")
    print(f"  -> {outdir}")


if __name__ == "__main__":
    main()
