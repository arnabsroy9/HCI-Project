# Tokens on a Timeline

**Tangible correction of automatic speaker diarization for low-resource speech annotation.**

An HCI study comparing two interfaces for the same task — fixing the mistakes an
automatic speaker-diarization system makes about *who is speaking, and when* — a
**graphical interface** (mouse) versus a **tangible interface** (physical ArUco
tokens moved on a printed timeline, tracked by an overhead webcam). Both drive
the **same backend operation model and the same on-screen renderer**, so the
only thing that differs between conditions is the input modality. The target is
a **double dissociation**: per-speaker tokens should help *identity* correction
(H1), while direct manipulation should help *boundary* correction (H2).

This repository holds the manuscript, the physical rig assets, the stimulus
generators, and the shared-core study application used to run participants.

---

## What a session looks like

Each participant fixes short (60 s), 3-speaker clips in which a few labels have
been deliberately corrupted (a mix of **confusion** errors — a segment given to
the wrong speaker — and **boundary** errors — a segment edge moved off its true
time). They correct them against a hidden answer key, in **both** conditions:

- **Mouse:** click a segment to relabel it; drag an edge to move a boundary.
- **Tokens:** rest a speaker token (S1/S2/S3) on a segment to relabel it; place
  the boundary handle to grab and slide the nearer edge. A webcam over the
  printed sheet reads the tokens.

Playback (listen / scrub) is on the on-screen player with the **mouse in both
conditions** — its time is logged and subtracted, so the input device is
irrelevant to the measure. The op log *is* the dataset; `analyze.py` turns it
into per-error and per-trial tables.

---

## Repository layout

```
app/            shared-core study app (stdlib server + browser front-end)
  server.py         backend: one segment-state model, op log, scoring, camera mgmt
  static/           the browser UI (wavesurfer.js vendored) — GUI + tangible display
  make_stimulus.py    synthetic tone stimulus generator (+ answer key, error injection)
  make_bengali_tts.py neutral Bengali conversation clips via Edge neural TTS
  select_recordings.py / import_kaggle.py   real Bengali-Loop clip pipeline (optional)
  analyze.py        op logs -> errors.csv (GLMM unit) + trials.csv
  schema.md         the shared operation + log + stimulus contract
  stimuli/<clip>/   hypothesis.json + answer_key.json + meta.json (+ audio.wav, gitignored)
rig/            printed rig assets + the ArUco tracker
  generate_sheets.py  A3 timeline (folded into bands) + token PDFs + geometry JSON
  tangible_input.py   C920 -> ArUco -> homography -> shared ops (the tracker)
  live_detect.py      camera detection helpers + live preview
  camera_check.py     pre-session go/no-go readiness check
  timeline_a3.pdf / tokens.pdf / transport_zones.json   generated assets
proposal-v2/    manuscript (.tex + .bib + figures + built PDF)
webcam-test/    C920 verification scripts
```

---

## The printed sheet

The 60 s timeline is **folded across 3 band rows** (0–20 / 20–40 / 40–60 s) so
each second gets ~3× the width of a single 60 s axis — finer, more precise token
placement (≈ 55 ms per mm vs 167 ms; comfortably inside the 0.15 s "corrected"
tolerance). A token's **row picks the time band, its x picks the time within
it**; global time = `band.t0 + (x − band.x0) / band.mm_per_s`. Speakers are
carried by the **tokens** (id + colour), not the rows.

Markers are `DICT_4X4_50`: ids 0–3 = corner fiducials (homography reference),
10–12 = speaker tokens S1–S3, 20 = boundary handle B1. Print the A3 at **100% /
Actual size** and measure the 50 mm scale bar to confirm.

---

## Stimuli

The measured comparison runs on **synthetic Bengali conversation clips** —
neutral scripted 3-speaker dialogues rendered with Microsoft Edge neural TTS
(three pitch-separated voices, ~120 / 160 / 240 Hz). Because the audio is
generated, the ground truth is exact and difficulty is matched across the two
clip sets by construction; the controlled variable (the injected errors) is
synthetic regardless of audio source.

```bash
.\.venv\Scripts\python.exe app\make_bengali_tts.py --clip clipBnA --seed 11   # needs network once
```

The synthetic clips ship complete — their `audio.wav` **is committed** (they're
generated, not licensed), so a clone runs the study out of the box. The real
Bengali-Loop corpus is supported (`select_recordings.py` → `import_kaggle.py`)
but its audio is **licensed and gitignored**; the study as configured is fully
synthetic. `make_bengali_tts.py` is only needed to add or regenerate clips.

---

## Protocol

Within-subject, counterbalanced across **4 groups** (`app/stimuli/protocol.json`):

| Group | 1st block | 2nd block | Mouse clips | Tokens clips |
|-------|-----------|-----------|-------------|--------------|
| 0 | Mouse | Tokens | clipBnA, clipBnB | clipBnC, clipBnD |
| 1 | Tokens | Mouse | clipBnA, clipBnB | clipBnC, clipBnD |
| 2 | Mouse | Tokens | clipBnC, clipBnD | clipBnA, clipBnB |
| 3 | Tokens | Mouse | clipBnC, clipBnD | clipBnA, clipBnB |

Each condition block = **1 practice** trial (novelty control, excluded from
analysis) + **2 recorded** trials → 6 trials per participant. The group
balances **condition order** and **which clip set goes to which condition**, so
neither confounds the mouse-vs-tokens comparison. Assign groups in rotation
(p01→0, p02→1, … 2 per group for N = 8).

---

## Setup (repo-local venv, no global/conda installs)

From the repository root:

```bash
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Everything installs inside `.venv/` (gitignored); `requirements.txt` is the
source of truth, so a fresh clone just re-runs those two lines. The `app/`
backend and analyzer are pure stdlib; numpy / OpenCV / reportlab / soundfile /
scipy / edge-tts are needed by the stimulus and rig scripts.

---

## Running a study session

Everything happens in the **browser** — the operator never needs a second
terminal.

1. **Start the server** (once):
   ```bash
   .\.venv\Scripts\python.exe app\server.py
   ```
2. **Aim the overhead C920.** Open the live preview and adjust the stand/sheet
   until all four corner markers are outlined (ESC to quit, `s` saves a frame):
   ```bash
   .\.venv\Scripts\python.exe rig\live_detect.py --live --index 1
   ```
   Then run the readiness check before each participant:
   ```bash
   .\.venv\Scripts\python.exe rig\camera_check.py
   ```
   It confirms 1080p (a jostled USB silently drops to 640×480), 4/4 corner
   fiducials, adequate lighting, and per-token band/time; add
   `--expect S1=10,S3=50,B1=15` to verify placement accuracy on ticks. Exit 0 =
   ready.
3. Open <http://localhost:8000>, enter the participant id, set the **group**,
   press **Begin session**, and work through the 6 trials (**Done — next**
   advances). For a **tangible** trial the server **auto-launches the tracker**
   with the right clip duration and shows a live camera dot; corrections are
   tokens-only (mouse corrections are rejected), playback is the mouse. **Ctrl+Z**
   undoes the last correction in either condition. A live cue highlights the
   segment/edge each token is pointing at.
4. Per-participant results and per-trial op logs are written to `app/logs/`.
5. Turn logs into analysis tables:
   ```bash
   .\.venv\Scripts\python.exe app\analyze.py     # -> errors.csv, trials.csv
   ```

Regenerate the sheet + tokens (e.g. to reprint or change band count):

```bash
.\.venv\Scripts\python.exe rig\generate_sheets.py --duration 60 --speakers 3 --bands 3
```

More detail: [app/README.md](app/README.md) and [rig/README.md](rig/README.md).

---

## Not in the repository (by design)

- `.venv/` — recreated from `requirements.txt`.
- `app/logs/` — **participant data**, kept private/local.
- `app/stimuli/train_*/`, `test_*/` — licensed real Bengali-Loop clips (audio
  excluded). Synthetic `clip*/audio.wav` **is** committed so the study runs
  as-is.
- Rig captures / previews (`rig/camera_check.png`, `*_preview.png`, `detect/`).

---

## Status

Rig, stimuli, and the shared-core app are built and validated end-to-end on the
overhead C920 (≈ 58 ms mean placement error, inside the 0.15 s tolerance). The
protocol is fully synthetic and counterbalanced; data collection is N = 8.
