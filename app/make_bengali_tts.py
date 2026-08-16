#!/usr/bin/env python
# =============================================================
#  make_bengali_tts.py  --  build a *synthetic-but-Bengali*
#  diarization-correction stimulus for the TRAINING block.
#
#  Same contract as make_stimulus.py (hypothesis.json /
#  answer_key.json / meta.json, 16 kHz mono), but the audio is
#  real Bengali speech from Microsoft Edge neural TTS instead of
#  tones -- so the practice clip matches the measured audio
#  domain (Bengali) while staying neutral, controlled, and
#  copyright-clean. The turn structure and error injection are
#  reused verbatim from make_stimulus, so scoring is identical.
#
#  Needs network ONCE to synthesize; the resulting audio.wav is
#  local afterwards. Deps: edge-tts, soundfile, scipy (see
#  requirements.txt).
#
#  Usage:
#     python make_bengali_tts.py --clip clipBnT --duration 60 --seed 7
# =============================================================

import argparse, asyncio, io, json, os, random, wave
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from make_stimulus import inject, SPEAKERS, SR

# Three neutral Bengali voices for S1/S2/S3, chosen + pitch-shifted to be well
# separated by fundamental frequency (F0 ~120 / 160 / 240 Hz, min gap ~40 Hz)
# so listeners clearly hear THREE distinct speakers -- essential for the H1
# identity task. Shifts are kept light so the voices stay natural (a large
# downshift sounds robotic). (voice, pitch, rate) per speaker.
VOICES = {"S1": ("bn-IN-BashkarNeural",  "-25Hz", "+0%"),   # male,        India
          "S2": ("bn-BD-NabanitaNeural", "-45Hz", "+0%"),   # low female,  Bangladesh
          "S3": ("bn-IN-TanishaaNeural", "+0Hz",  "+0%")}   # high female, India

# A bank of neutral everyday conversations among three friends, each on a
# different topic so no participant hears the same content twice. Written as
# real turn-taking (questions, answers, backchannels) so each plays like a
# conversation, not a list of sentences. The turn ORDER becomes the ground-truth
# diarization; no two adjacent turns share a speaker. No names, no emotion, no
# sensitive content. Keyed by clip name.
DIALOGUES = {
    # ----- training clip (meeting up, tea, a book, the park) -----
    "clipBnT": [
        ("S1", "আরে, কেমন আছো? অনেক দিন পর দেখা।"),
        ("S2", "হ্যাঁ, ভালো আছি। তুমি কেমন আছো?"),
        ("S1", "এইতো চলছে। আজকে আবহাওয়াটা বেশ সুন্দর, তাই না?"),
        ("S3", "হ্যাঁ, সকাল থেকেই আকাশটা একদম পরিষ্কার।"),
        ("S2", "চলো না, আমরা একটু বাইরে হাঁটতে যাই।"),
        ("S1", "ভালো বলেছো। চা খেয়ে বের হলে কেমন হয়?"),
        ("S3", "দারুণ হবে। সামনের দোকানের চা কিন্তু বেশ ভালো।"),
        ("S2", "আচ্ছা, তাহলে ওখানেই একটু বসি।"),
        ("S1", "তুমি কি সেই বইটা পড়া শেষ করেছো?"),
        ("S2", "না, এখনো অর্ধেকটা বাকি আছে।"),
        ("S3", "কোন বইটার কথা বলছো তোমরা?"),
        ("S1", "ওই গল্পের বইটা, যেটা গত সপ্তাহে কিনেছিলাম।"),
        ("S2", "ওহ, ওটা তো সত্যিই খুব সুন্দর।"),
        ("S3", "আমাকেও একটু পড়তে দিও কিন্তু।"),
        ("S1", "অবশ্যই, কালকে তোমার জন্য নিয়ে আসবো।"),
        ("S2", "আজকে বিকেলে তোমরা কি ফ্রি আছো?"),
        ("S3", "হ্যাঁ, বিকেলের দিকে আমার সময় আছে।"),
        ("S1", "তাহলে আমরা পার্কে গিয়ে একটু বসতে পারি।"),
        ("S2", "খুব ভালো হবে। ওখানে অনেক গাছপালা আছে।"),
        ("S3", "আর সন্ধ্যায় আকাশটাও খুব সুন্দর লাগে।"),
        ("S1", "ঠিক বলেছো। চলো তাহলে ওটাই ঠিক রইলো।"),
        ("S2", "আচ্ছা, আমি একটু পরে ফোন দেবো তোমাদের।"),
        ("S3", "ঠিক আছে, আমি অপেক্ষা করবো।"),
        ("S1", "তাহলে এখন উঠি, একটু কাজ আছে।"),
        ("S2", "আচ্ছা, পরে দেখা হবে তাহলে।"),
        ("S3", "হ্যাঁ, ভালো থেকো তোমরা।"),
        ("S1", "তোমরাও ভালো থেকো, বিকেলে দেখা হচ্ছে।"),
    ],
    # ----- measured A (a study group before exams) -----
    "clipBnA": [
        ("S1", "তোমাদের ক্লাস কি আজকে শেষ হয়ে গেছে?"),
        ("S2", "হ্যাঁ, একটু আগেই শেষ হলো।"),
        ("S3", "আমার কিন্তু আরেকটা ক্লাস বাকি আছে।"),
        ("S1", "আচ্ছা, তাহলে আমরা পরে একসাথে বসি।"),
        ("S2", "চলো না, একসাথে একটু পড়াশোনা করি।"),
        ("S3", "ভালো বুদ্ধি। লাইব্রেরিতে গেলে কেমন হয়?"),
        ("S1", "হ্যাঁ, ওখানে বেশ শান্ত পরিবেশ।"),
        ("S2", "তোমার কাছে কি নোটগুলো আছে?"),
        ("S1", "হ্যাঁ, সব নোট আমার কাছেই আছে।"),
        ("S3", "তাহলে তো আমাদের খুব সুবিধা হবে।"),
        ("S2", "আগামী সপ্তাহে কিন্তু পরীক্ষা।"),
        ("S1", "জানি, তাই একটু আগে থেকেই প্রস্তুতি নিচ্ছি।"),
        ("S3", "আমরা ভাগ করে পড়লে তাড়াতাড়ি হবে।"),
        ("S2", "ঠিক বলেছো, প্রতিটা অধ্যায় ভাগ করে নিই।"),
        ("S1", "আমি প্রথম দুটো অধ্যায় নিচ্ছি।"),
        ("S3", "আমি তাহলে পরের দুটো দেখবো।"),
        ("S2", "বাকিটা আমি দেখে নেবো।"),
        ("S1", "দারুণ, তাহলে কালকে মিলিয়ে নেবো।"),
        ("S3", "হ্যাঁ, সকাল দশটায় দেখা হবে।"),
        ("S2", "আচ্ছা, আমি সময় মতো চলে আসবো।"),
        ("S1", "কেউ কিন্তু দেরি কোরো না।"),
        ("S3", "না না, আমি ঠিক সময়ে আসবো।"),
        ("S2", "তাহলে আজকের মতো এখানেই শেষ করি।"),
        ("S1", "হ্যাঁ, বাড়ি গিয়ে একটু বিশ্রাম নাও।"),
        ("S3", "তোমরাও ভালো থেকো।"),
    ],
    # ----- measured B (planning dinner + a market run) -----
    "clipBnB": [
        ("S1", "আজকে রাতে কী রান্না করা যায় বলো তো?"),
        ("S2", "খিচুড়ি করলে কেমন হয়?"),
        ("S3", "দারুণ হবে, বৃষ্টির দিনে খিচুড়ি জমে যায়।"),
        ("S1", "তাহলে বাজার থেকে কিছু জিনিস আনতে হবে।"),
        ("S2", "চাল আর ডাল কি বাড়িতে আছে?"),
        ("S1", "ডাল আছে, কিন্তু চাল প্রায় শেষ।"),
        ("S3", "আমি বাজার থেকে চাল নিয়ে আসছি।"),
        ("S2", "সাথে কিছু সবজিও নিয়ে এসো।"),
        ("S1", "আলু আর পেঁয়াজ কিন্তু লাগবে।"),
        ("S3", "ঠিক আছে, আমি সব লিখে নিচ্ছি।"),
        ("S2", "আর একটু আদা রসুন এনো।"),
        ("S1", "হ্যাঁ, ওগুলো ছাড়া তো স্বাদ হবে না।"),
        ("S3", "বাজারটা কি এখন খোলা আছে?"),
        ("S2", "হ্যাঁ, সন্ধ্যা পর্যন্ত খোলা থাকে।"),
        ("S1", "তাহলে দেরি না করে বেরিয়ে পড়ো।"),
        ("S3", "যাচ্ছি, আধা ঘণ্টার মধ্যে ফিরবো।"),
        ("S2", "আমি ততক্ষণে রান্নাঘর গুছিয়ে রাখি।"),
        ("S1", "আমি হাঁড়িটা ধুয়ে রাখছি।"),
        ("S3", "ফেরার পথে কিছু লাগলে ফোন কোরো।"),
        ("S2", "আচ্ছা, মনে করে দুধও নিয়ে এসো।"),
        ("S1", "দুধ দিয়ে পরে একটু পায়েস হবে।"),
        ("S3", "বাহ, তাহলে তো জমে যাবে।"),
        ("S2", "হ্যাঁ, সবাই মিলে খাওয়া হবে।"),
        ("S1", "তাড়াতাড়ি ফেরো, খিদে পেয়েছে।"),
    ],
    # ----- measured C (planning a trip to the hills) -----
    "clipBnC": [
        ("S1", "ছুটিতে তোমরা কি কোথাও যাচ্ছো?"),
        ("S2", "ভাবছি এবার পাহাড়ের দিকে যাবো।"),
        ("S3", "পাহাড় তো এই সময় খুব সুন্দর থাকে।"),
        ("S1", "ট্রেনের টিকিট কি কেটেছো?"),
        ("S2", "না, এখনো কাটা হয়নি।"),
        ("S3", "আগে থেকে কেটে রাখাই ভালো।"),
        ("S1", "হ্যাঁ, নাহলে পরে আর পাওয়া যায় না।"),
        ("S2", "অনলাইনে কি টিকিট পাওয়া যাবে?"),
        ("S1", "হ্যাঁ, ঘরে বসেই কেটে নেওয়া যায়।"),
        ("S3", "আমি তাহলে আজকেই কেটে ফেলি।"),
        ("S2", "ক'দিনের জন্য যাচ্ছি আমরা?"),
        ("S1", "চার পাঁচ দিন হলে ভালো হয়।"),
        ("S3", "থাকার জায়গা কি ঠিক করেছো?"),
        ("S2", "একটা ছোট হোটেল দেখে রেখেছি।"),
        ("S1", "দামটা কেমন, খুব বেশি নয় তো?"),
        ("S3", "না, মোটামুটি সাধ্যের মধ্যেই।"),
        ("S2", "ব্যাগ কিন্তু হালকা রাখবে।"),
        ("S1", "হ্যাঁ, বেশি জিনিস নিলে বয়ে বেড়ানো কষ্ট।"),
        ("S3", "গরম কাপড় নিতে কিন্তু ভুলো না।"),
        ("S2", "ওখানে রাতের দিকে বেশ ঠান্ডা।"),
        ("S1", "ক্যামেরাটাও সাথে নিয়ো।"),
        ("S3", "অবশ্যই, অনেক ছবি তুলবো।"),
        ("S2", "তাহলে সব ঠিকঠাক, আমরা তৈরি।"),
    ],
    # ----- measured D (planning to watch a film) -----
    "clipBnD": [
        ("S1", "গত সপ্তাহে যে সিনেমাটা এলো, দেখেছো?"),
        ("S2", "না, এখনো দেখা হয়নি।"),
        ("S3", "আমি দেখেছি, বেশ ভালো ছিল।"),
        ("S1", "গল্পটা নাকি খুব সুন্দর।"),
        ("S3", "হ্যাঁ, আর গানগুলোও দারুণ।"),
        ("S2", "তাহলে তো দেখতেই হয়।"),
        ("S1", "চলো না, এই শনিবার একসাথে যাই।"),
        ("S3", "ভালো বলেছো, বিকেলের শো দেখা যাক।"),
        ("S2", "টিকিট কি আগে কাটতে হবে?"),
        ("S1", "হ্যাঁ, ভিড় হলে পরে পাওয়া কঠিন।"),
        ("S3", "আমি অনলাইনে কেটে রাখছি।"),
        ("S2", "কয়টার শো দেখবো আমরা?"),
        ("S1", "বিকেল পাঁচটার শো হলে ভালো।"),
        ("S3", "ঠিক আছে, পাঁচটাই রাখলাম।"),
        ("S2", "সিনেমার পরে কোথাও খাওয়া যাবে?"),
        ("S1", "হ্যাঁ, কাছেই ভালো একটা রেস্তোরাঁ আছে।"),
        ("S3", "ওখানকার খাবার কিন্তু বেশ ভালো।"),
        ("S2", "তাহলে তো পুরো বিকেলটাই জমে যাবে।"),
        ("S1", "সবাই ঠিক সময়ে চলে এসো।"),
        ("S3", "হ্যাঁ, দেরি করলে শো মিস হয়ে যাবে।"),
        ("S2", "আমি একটু আগেই পৌঁছে যাবো।"),
        ("S1", "দারুণ, তাহলে শনিবার দেখা হচ্ছে।"),
        ("S3", "হ্যাঁ, অপেক্ষায় থাকলাম।"),
    ],
}

EDGE_S = 0.02         # 20 ms fade at each turn edge (anti-click)


async def _synth(text, spec, sem):
    """Return one utterance as float32 mono at SR (resampled from TTS 24 kHz).
    `spec` is (voice, pitch, rate) so each speaker gets its own timbre + pitch."""
    voice, pitch, rate = spec
    async with sem:
        buf = bytearray()
        com = __import__("edge_tts").Communicate(text, voice, pitch=pitch, rate=rate)
        async for ch in com.stream():
            if ch["type"] == "audio":
                buf += ch["data"]
    data, sr = sf.read(io.BytesIO(bytes(buf)), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != SR:
        from math import gcd
        g = gcd(int(sr), SR)
        data = resample_poly(data, SR // g, int(sr) // g).astype(np.float32)
    return data


async def _synth_lines(dialogue):
    """Synthesize each dialogue line in its speaker's voice, concurrently."""
    sem = asyncio.Semaphore(6)
    clips = await asyncio.gather(
        *[_synth(text, VOICES[spk], sem) for spk, text in dialogue])
    return clips


def _trim(sig, pad_s=0.06, thresh=0.015):
    """Trim leading/trailing dead air the TTS leaves, so turns come back
    quickly (keeps a short pad). Silence *inside* a line is left alone."""
    amp = np.abs(sig)
    loud = np.where(amp > thresh * (amp.max() + 1e-9))[0]
    if len(loud) == 0:
        return sig
    pad = int(pad_s * SR)
    a = max(0, loud[0] - pad)
    b = min(len(sig), loud[-1] + pad)
    return sig[a:b]


def _fade(sig):
    e = int(EDGE_S * SR)
    if len(sig) > 2 * e:
        sig = sig.copy()
        sig[:e] *= np.linspace(0, 1, e, dtype=np.float32)
        sig[-e:] *= np.linspace(1, 0, e, dtype=np.float32)
    return sig


def assemble(dialogue, clips, duration, seed):
    """Lay the spoken turns end to end (with short natural gaps) and derive the
    ground-truth segments from where each turn actually lands. Returns
    (audio float32, ground-truth segments) trimmed to exactly `duration`."""
    rng = random.Random(seed)
    total = int(duration * SR)
    audio = np.zeros(total, np.float32)
    segs, t, sid = [], 0.0, 0
    for (spk, _text), clip in zip(dialogue, clips):
        a = int(t * SR)
        if a >= total:
            break
        clip = _fade(_trim(clip))
        b = min(a + len(clip), total)
        audio[a:b] += clip[:b - a]
        gap = rng.uniform(0.12, 0.30)                 # brief between-turn pause
        end = t + len(clip) / SR + gap                # gap trails inside the turn
        segs.append({"id": sid, "start": round(t, 3), "end": round(end, 3),
                     "speaker": spk})
        t, sid = end, sid + 1
        if t >= duration:
            break
    segs[-1]["end"] = round(duration, 3)              # snap last edge to axis end
    audio /= (np.max(np.abs(audio)) + 1e-9)
    return audio, segs


def write_wav(audio, path):
    pcm = (audio * 0.9 * 32767).astype(np.int16)
    with wave.open(path, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="clipBnT", choices=sorted(DIALOGUES),
                    help="which conversation to render")
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--confusion", type=int, default=4)
    ap.add_argument("--boundary", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    dialogue = DIALOGUES[args.clip]
    rng = random.Random(args.seed)
    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "stimuli", args.clip)
    os.makedirs(outdir, exist_ok=True)

    print(f"synthesizing {len(dialogue)} Bengali conversation turns...")
    clips = asyncio.run(_synth_lines(dialogue))
    audio, gt = assemble(dialogue, clips, args.duration, args.seed)
    write_wav(audio, os.path.join(outdir, "audio.wav"))
    hyp, errors = inject(gt, args.confusion, args.boundary, rng)  # same errors

    with open(os.path.join(outdir, "hypothesis.json"), "w") as f:
        json.dump({"clip": args.clip, "duration": args.duration,
                   "sample_rate": SR, "speakers": SPEAKERS,
                   "segments": hyp}, f, indent=2)
    with open(os.path.join(outdir, "answer_key.json"), "w") as f:
        json.dump({"clip": args.clip, "segments": gt,
                   "injected_errors": errors}, f, indent=2)
    with open(os.path.join(outdir, "meta.json"), "w") as f:
        json.dump({"clip": args.clip, "duration": args.duration,
                   "n_speakers": len(SPEAKERS), "audio": "bengali_edge_tts",
                   "voices": VOICES,
                   "n_confusion": sum(e["type"] == "confusion" for e in errors),
                   "n_boundary": sum(e["type"] == "boundary" for e in errors),
                   "n_segments": len(gt), "seed": args.seed}, f, indent=2)

    print(f"clip '{args.clip}': {len(gt)} segments, "
          f"{sum(e['type']=='confusion' for e in errors)} confusion + "
          f"{sum(e['type']=='boundary' for e in errors)} boundary errors")
    print(f"  -> {outdir}")


if __name__ == "__main__":
    main()
