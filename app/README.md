# App — shared-core diarization-correction study

The Phase 1 shared core: one backend state model + one renderer, driven by
the GUI now and the ArUco tracker later. Stdlib Python only (no pip installs)
plus wavesurfer.js vendored under `static/vendor/`.

## Run (from this `app/` folder)

The system Python has the deps; conda `(base)` does not, so:

```bash
conda deactivate
```

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
- [ ] Tangible condition: point the ArUco tracker (`../rig/`) at `/api/op`
      with `source:"aruco"` — same schema, no backend change
- [ ] Real Bengali-Loop audio in place of synthetic clips
- [ ] Counterbalanced multi-clip session runner
