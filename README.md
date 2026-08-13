# Tokens on a Timeline

Tangible correction of automatic speaker diarization for low-resource speech
annotation. This repository holds the manuscript, the physical rig assets, and
the shared-core study application.

```
proposal-v2/   manuscript (.tex) + references (.bib)
rig/           A3 timeline + ArUco token generator, C920 checks, live detection
app/           shared-core study app (backend state model + GUI condition)
webcam-test/   second-hand C920 verification scripts
```

## One-time setup (repo-local venv, no global/conda installs)

From the repository root:

```bash
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Everything installs inside `.venv/` in this repo and touches nothing else on
the machine. The `.venv/` folder is gitignored; `requirements.txt` is the
source of truth, so a fresh clone just re-runs the two lines above.

## Running things

Either call the venv Python directly:

```bash
.\.venv\Scripts\python.exe app\server.py
.\.venv\Scripts\python.exe rig\generate_sheets.py
```

…or activate the venv once per shell, then use `python` normally:

```bash
.\.venv\Scripts\Activate.ps1     # PowerShell; then `python ...`
```

(The `app/` backend and analyzer are pure stdlib; numpy / OpenCV / reportlab
are needed by `make_stimulus.py` and the `rig/` scripts.)

- Study app: see [app/README.md](app/README.md).
- Rig assets and camera checks: see [rig/README.md](rig/README.md).

## Status

- Manuscript: citation fixes, zoom-cap (fixed-scale) decision, and the
  boundary-handle disambiguation are written in.
- Rig: A3 timeline + tokens generated and validated end-to-end through the C920.
- App: Phase 1 shared core + GUI condition complete; tangible condition and
  real Bengali-Loop audio are the next steps.
