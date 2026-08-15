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
      `source:"aruco"` (dwell-based commit); validated via `--sim` without the
      camera, ready to swap in the live C920 once mounted
- [ ] Real Bengali-Loop audio in place of synthetic clips
- [ ] Counterbalanced multi-clip session runner

## Tangible condition (from `rig/`)

```bash
# 1. start a tangible session
curl -X POST http://localhost:8000/api/session/start \
     -d '{"participant":"p01","condition":"tangible","clip":"clipA"}'
# 2a. live camera (needs the mounted C920):
..\.venv\Scripts\python.exe rig\tangible_input.py --duration 60
# 2b. or a scripted dry-run without hardware:
..\.venv\Scripts\python.exe rig\tangible_input.py --sim rig\demo_sim.json --duration 60
# 3. finish & score, then analyze as above.
```
