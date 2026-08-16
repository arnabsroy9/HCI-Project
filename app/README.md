# App — shared-core diarization-correction study

The Phase 1 shared core: one backend state model + one renderer, driven by
the GUI now and the ArUco tracker later. Stdlib Python only (no pip installs)
plus wavesurfer.js vendored under `static/vendor/`.

## Run (from this `app/` folder)

First do the one-time venv setup in the repo root (see [../README.md](../README.md)),
then activate it so `python` resolves to the repo venv:

```bash
..\.venv\Scripts\Activate.ps1
```

(Or prefix each command with `..\.venv\Scripts\python.exe` instead of activating.)

1. Build a sample stimulus (synthetic 3-speaker audio + injected errors):
   ```bash
   python make_stimulus.py --clip clipA --duration 60 --seed 1
   ```
2. Start the server:
   ```bash
   python server.py
   ```
3. Open <http://localhost:8000>, enter a participant id, press **Start trial**.
   - Click a segment to cycle its speaker (fix a confusion error).
   - Drag a segment edge to move a boundary.
   - Spacebar plays / pauses. There is no zoom (fixed whole-clip scale, matched
     across conditions by the Section 5.4 decision).
   - Press **Finish & score** to see accuracy and write the summary.
4. Turn logs into analysis tables:
   ```bash
   python analyze.py        # writes errors.csv (GLMM unit) + trials.csv
   ```

## Layout

```
make_stimulus.py   synthetic stimulus + answer key
server.py          stdlib backend: state, ops, logging, scoring
analyze.py         logs -> errors.csv / trials.csv
schema.md          the shared operation + log + stimulus contract
static/            GUI condition (wavesurfer.js vendored)
stimuli/<clip>/    audio.wav + hypothesis.json + answer_key.json
logs/              per-trial .jsonl + _summary.json  (the dataset)
```

## Status

- [x] Shared backend state model + operation log
- [x] GUI condition (wavesurfer.js): reassign, move_boundary, playback, scoring
- [x] Synthetic stimulus generator + answer key + error injection
- [x] Analysis: error-level table with per-error correction time
- [x] Tangible condition: `../rig/tangible_input.py` emits the same ops with
      `source:"aruco"` (dwell-based commit); validated live on the C920
- [x] Auto-managed camera: the server launches/stops the tracker per tangible
      trial (browser-only operation), shows a live camera dot from a tracker
      heartbeat, and guards ops by source so they can't land in the wrong
      condition's log
- [x] Counterbalanced multi-clip session runner (protocol): training block
      before each condition, order + clip-set counterbalanced across 4 groups,
      per-participant results file; GUI trials interactive, tangible trials a
      read-only display that polls while the tracker drives ops
- [x] Real Bengali-Loop audio: selector + importer done and validated
      end-to-end (download labels → pick 3-speaker windows → fetch a few audio
      files → `import_kaggle.py` cuts + converts to the stimulus contract).
      Real clips are gitignored (licensed); synthetic clips remain the default.
- [x] Synthetic Bengali conversation clips (`make_bengali_tts.py`): neutral
      scripted 3-speaker dialogues rendered with Edge neural TTS (3 distinct
      voices), same turn/error contract as `make_stimulus.py` but domain-matched
      (Bengali) and matched difficulty across sets. Used for training + the
      primary measured comparison; 1 real clip per set is kept as an
      ecological-validity check (see `stimuli/protocol.json`). Generate with
      `python make_bengali_tts.py --clip clipBnA --seed 11` (needs network once).

## Getting the real dataset (Bengali-Loop / DL Sprint 4.0)

The diarization corpus (24 rec, 22 h, CSV `start,end,speaker` labels) is
released via the Kaggle competition
`dl-sprint-4-0-bengali-speaker-diarization-challenge`. You do NOT need the
full ~15 GB — the study needs only a couple of 3-speaker recordings.

1. **Accept the competition rules** on Kaggle and put an API token at
   `~/.kaggle/kaggle.json` (both are account actions only you can do).
2. **List files, download only the label CSVs** (kilobytes):
   ```bash
   ..\.venv\Scripts\kaggle.exe competitions files -c dl-sprint-4-0-bengali-speaker-diarization-challenge
   ..\.venv\Scripts\kaggle.exe competitions download -c dl-sprint-4-0-bengali-speaker-diarization-challenge -f <labels.csv>
   ```
3. **Pick which recordings to fetch** — flags exactly-N-speaker, turn-dense
   recordings and suggests a clip window, so you fetch only 2-3 audio files:
   ```bash
   ..\.venv\Scripts\python.exe app\select_recordings.py <labels.csv> --speakers 3 --win 90
   ```
4. **Download just those audio files** with `-f` (paths look like
   `diarization/diarization/train/audio/train_009.wav`), e.g.:
   ```bash
   ..\.venv\Scripts\kaggle.exe competitions download -c dl-sprint-4-0-bengali-speaker-diarization-challenge -f diarization/diarization/train/audio/train_009.wav -p data\audio
   ```
5. **Convert to stimuli** — cuts each selected window and writes real clips
   into `stimuli/<recording>/` (gitignored):
   ```bash
   ..\.venv\Scripts\python.exe app\import_kaggle.py --clip-len 60
   ```
   Zero-local-download alternative: paste `app\kaggle_make_stimuli.py` into a
   Kaggle notebook cell and download the small output zip.

## Run a full participant session (browser only)

Start the server once, then **everything happens in the browser** — the
operator never touches a second terminal:

```bash
..\.venv\Scripts\python.exe app\server.py
```

Open <http://localhost:8000>, enter a participant id (optionally a group
0-3, else auto from the id), press **Begin session**, and work through the
trials; **Done — next** advances. The screen states the condition each trial
(mouse vs. tokens) and shows step-by-step instructions.

For a **tangible** trial the server **launches the camera tracker itself**
with the right clip duration and stops it when the trial ends. A live dot on
the trial screen shows the camera state:

- `◍ Starting camera…` — the C920 takes a few seconds to open (normal).
- `● Camera on — N tokens visible` — tracking; move the tokens.
- `⚠ Point the camera at the whole sheet` — fewer than 4 corner markers seen.

The camera is index 1 by default; override with `CAMERA_INDEX` (e.g.
`$env:CAMERA_INDEX=0` before starting the server). Tracker stdout goes to
`logs/tracker.log`.

The server also **guards input by source**: a tangible (`aruco`) op is
rejected during a GUI trial and a mouse op during a tangible trial (409), so
ops can never land in the wrong condition's log.

At the end a per-participant results file is written to `logs/` and the
measured-vs-training split is respected by `analyze.py`.

### Manual tracker (debugging only)

The auto-managed path above is the norm. To drive the tracker by hand — e.g.
a scripted dry-run without the camera — start a tangible trial, then:

```bash
..\.venv\Scripts\python.exe rig\tangible_input.py --sim rig\demo_sim.json --duration 60
```

Counterbalancing (group = order bit + clip-set bit):

```
group 0: gui{A,B} then tangible{C,D}      group 2: gui{C,D} then tangible{A,B}
group 1: tangible{C,D} then gui{A,B}      group 3: tangible{A,B} then gui{C,D}
```

## Standalone tangible trial (outside the protocol)

Usually you just run the protocol (above) and tangible trials manage their own
camera. To exercise a single tangible trial directly, POST a session with
`condition:"tangible"` — the server auto-starts the tracker for it, exactly as
in the protocol:

```bash
curl -X POST http://localhost:8000/api/session/start \
     -d '{"participant":"p01","condition":"tangible","clip":"clipA"}'
# camera starts automatically; correct with the tokens, then finish & score.
```
