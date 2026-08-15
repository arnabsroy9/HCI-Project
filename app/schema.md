# Shared-core contract

Both conditions (GUI mouse, and later the ArUco tracker) emit the **same
operations** to the same backend. The conditions differ only in input source,
which is the design in the proposal's Section 5.4. The operation log is the
dataset.

## Operations (POST /api/op)

```json
{"op": "reassign",      "segment": 12, "speaker": "S2", "source": "mouse"}
{"op": "move_boundary", "boundary": 9, "t": 29.261,     "source": "aruco"}
```

- `reassign` — set segment `segment` to `speaker`. Fixes a speaker-confusion error.
- `move_boundary` — move internal boundary `boundary` (between segment `i` and
  `i+1`) to time `t` seconds. The server links the shared edge
  (`seg[i].end == seg[i+1].start`) and clamps to keep both segments ≥ 0.4 s.
- `source` — free text tag recorded in the log (`mouse`, `aruco`, ...).

Boundary indices run `0 .. n-2`; the clip's outer edges (t=0 and t=duration)
are not movable.

## State model

A segment is `{id, start, end, speaker}`; segments are time-ordered and
contiguous. The backend holds one mutable list and a version counter.

## Log format (logs/&lt;participant&gt;_&lt;condition&gt;_&lt;clip&gt;_&lt;ts&gt;.jsonl)

One JSON object per line. Every record carries wall-clock and elapsed time:

```json
{"t_iso":"...","t_epoch":...,"elapsed_s":16.4,"event":"op","source":"mouse","op":{...}}
```

Events: `session_start`, `op`, `session_finish` (with the scored summary).

## Stimulus contract (stimuli/&lt;clip&gt;/)

- `hypothesis.json` — `{duration, sample_rate, speakers, segments}` (errors baked in).
- `answer_key.json` — ground-truth `segments` + `injected_errors`
  (`confusion`: segment_id, correct_speaker; `boundary`: boundary_index, correct_t).
- `audio.wav` — the clip. Synthetic now; swap in real Bengali-Loop audio later
  without changing anything else.

## HTTP endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | GUI condition page |
| POST | `/api/session/start` | `{participant, condition, clip}` → fresh trial |
| POST | `/api/op` | apply + log one operation |
| GET | `/api/state` | current segments + version |
| POST | `/api/session/finish` | score vs answer key, write summary |
| POST | `/api/protocol/start` | `{participant, group?}` → build counterbalanced plan, start trial 1 |
| GET | `/api/protocol/current` | current trial (index, phase, condition, clip, segments) |
| POST | `/api/protocol/next` | score current trial, record it, advance (or finish session) |

`session/*` drives a single standalone trial; `protocol/*` sequences the full
counterbalanced session (training + measured trials, both conditions).
