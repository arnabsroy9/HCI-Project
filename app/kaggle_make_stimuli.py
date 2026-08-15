# =============================================================
#  kaggle_make_stimuli.py  --  PASTE THIS INTO A KAGGLE NOTEBOOK
#  CELL (with the DL Sprint 4.0 *diarization* competition added
#  as Input). It reads the mounted data directly (no API download,
#  so the 403 never applies), selects 3-speaker turn-dense
#  recordings, cuts a clip from each, converts to this project's
#  stimulus contract (hypothesis/answer_key/audio + injected
#  errors), and zips the result.
#
#  Then: download /kaggle/working/bengali_stimuli.zip from the
#  notebook's Output panel and unzip it into  app/stimuli/  locally.
#  The real Bengali clips then play in both conditions unchanged.
# =============================================================
import csv, glob, json, os, random, re, zipfile
import numpy as np
import librosa, soundfile as sf

# ---- config ----
N_CLIPS   = 3        # how many clips to build
CLIP_LEN  = 60.0     # seconds (matches the rest of the project)
N_CONF    = 4        # injected speaker-confusion errors per clip
N_BOUND   = 4        # injected boundary errors per clip
SR        = 16000
MIN_SEG   = 0.4
SEED      = 1
OUT       = "/kaggle/working/stimuli"

rng = random.Random(SEED)

# ---- find the diarization annotations + audio under /kaggle/input ----
anns = sorted(glob.glob("/kaggle/input/**/train/annotation/*.csv", recursive=True))
assert anns, ("No train/annotation CSVs found. Add the DL Sprint 4.0 SPEAKER "
              "DIARIZATION competition as Input (not the transcription one).")
def audio_for(csv_path):
    p = csv_path.replace("/annotation/", "/audio/")[:-4] + ".wav"
    return p if os.path.exists(p) else None

def find_col(fields, pats):
    for pat in pats:
        for f in fields:
            if re.search(pat, f, re.I):
                return f

def _t(v):
    """Seconds from a float string or HH:MM:SS / MM:SS."""
    v = str(v).strip()
    if ":" in v:
        s = 0.0
        for p in v.split(":"):
            s = s * 60 + float(p)
        return s
    return float(v)

def read_segs(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f); fl = r.fieldnames or []
        sc = find_col(fl, [r"^start", r"start", r"onset", r"begin"])
        ec = find_col(fl, [r"^end", r"end", r"offset", r"stop"])
        pc = find_col(fl, [r"speaker", r"\bspk", r"^label$"])
        out = []
        for row in r:
            try:
                out.append((_t(row[sc]), _t(row[ec]), str(row[pc]).strip()))
            except (TypeError, ValueError, KeyError):
                pass
    return sorted(out)

def best_window(segs, win, need=3):
    t1 = max(e for _, e, _ in segs); best = None
    for st, _, _ in segs:
        if st + win > t1:
            break
        w = [g for g in segs if g[0] < st + win and g[1] > st]
        if len(set(g[2] for g in w)) == need:   # exactly N speakers in the window
            turns = sum(1 for i in range(1, len(w)) if w[i][2] != w[i-1][2])
            if best is None or turns > best[1]:
                best = (st, turns)
    return best

# ---- rank recordings: exactly 3 speakers with a valid window ----
cands = []
for a in anns:
    segs = read_segs(a); au = audio_for(a)
    if not segs or au is None:
        continue
    if max(e for _, e, _ in segs) - min(s for s, _, _ in segs) < CLIP_LEN:
        continue
    bw = best_window(segs, CLIP_LEN)   # a 60s window with exactly 3 speakers
    if bw:
        cands.append((bw[1], a, au, segs, bw[0]))   # (turns, csv, wav, segs, start)
cands.sort(reverse=True)
print(f"{len(cands)} three-speaker recording(s) usable; building {min(N_CLIPS,len(cands))} clip(s)")

# ---- build contiguous 3-speaker segments for a window ----
def window_segments(segs, t0, win):
    w = [(max(s, t0) - t0, min(e, t0 + win) - t0, spk)
         for s, e, spk in segs if s < t0 + win and e > t0]
    w = sorted([(s, e, spk) for s, e, spk in w if e - s > 0.05])
    # relabel the 3 speakers by first appearance -> S1,S2,S3
    order = {}
    for _, _, spk in w:
        order.setdefault(spk, f"S{len(order)+1}")
    # force a contiguous partition (absorb gaps/overlaps into a clean timeline)
    out, prev_end = [], 0.0
    for s, e, spk in w:
        s = prev_end
        if e <= s + MIN_SEG:
            continue
        out.append({"start": round(s, 3), "end": round(e, 3), "speaker": order[spk]})
        prev_end = e
    for i, seg in enumerate(out):
        seg["id"] = i
    out[-1]["end"] = round(min(win, out[-1]["end"]), 3)
    return out, sorted(set(order.values()))

def inject(segs, speakers):
    hyp = [dict(s) for s in segs]; errors = []
    for sid in rng.sample(range(len(hyp)), min(N_CONF, len(hyp))):
        cor = hyp[sid]["speaker"]
        wrong = rng.choice([s for s in speakers if s != cor])
        hyp[sid]["speaker"] = wrong
        errors.append({"type": "confusion", "segment_id": sid,
                       "correct_speaker": cor, "wrong_speaker": wrong})
    internal = list(range(len(hyp) - 1))
    for i in rng.sample(internal, min(N_BOUND, len(internal))):
        cor_t = hyp[i]["end"]
        lo = hyp[i]["start"] + MIN_SEG; hi = hyp[i+1]["end"] - MIN_SEG
        wrong_t = round(min(max(cor_t + rng.uniform(0.3, 1.2) * rng.choice([-1, 1]), lo), hi), 3)
        hyp[i]["end"] = wrong_t; hyp[i+1]["start"] = wrong_t
        errors.append({"type": "boundary", "boundary_index": i,
                       "correct_t": round(cor_t, 3), "wrong_t": wrong_t})
    return hyp, errors

os.makedirs(OUT, exist_ok=True)
for n, (turns, csv_path, wav, segs, t0) in enumerate(cands[:N_CLIPS], 1):
    clip = f"bl{n:02d}"
    d = os.path.join(OUT, clip); os.makedirs(d, exist_ok=True)
    y, _ = librosa.load(wav, sr=SR, mono=True, offset=t0, duration=CLIP_LEN)
    sf.write(os.path.join(d, "audio.wav"), y, SR, subtype="PCM_16")
    gt, speakers = window_segments(segs, t0, CLIP_LEN)
    hyp, errors = inject(gt, speakers)
    json.dump({"clip": clip, "duration": CLIP_LEN, "sample_rate": SR,
               "speakers": speakers, "segments": hyp},
              open(os.path.join(d, "hypothesis.json"), "w"), indent=2)
    json.dump({"clip": clip, "segments": gt, "injected_errors": errors},
              open(os.path.join(d, "answer_key.json"), "w"), indent=2)
    json.dump({"clip": clip, "source": os.path.basename(csv_path),
               "window_start_s": round(t0, 2), "duration": CLIP_LEN,
               "n_speakers": 3, "n_segments": len(gt)},
              open(os.path.join(d, "meta.json"), "w"), indent=2)
    print(f"  {clip}: from {os.path.basename(wav)} @ {t0:.1f}s, "
          f"{len(gt)} segments, {turns} turns")

zpath = "/kaggle/working/bengali_stimuli.zip"
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(OUT):
        for fn in files:
            fp = os.path.join(root, fn)
            z.write(fp, os.path.relpath(fp, OUT))
print(f"\nDone -> download {zpath} from the Output panel, unzip into app/stimuli/")
