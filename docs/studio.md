# Sprite Gen Studio

Sprite Gen Studio is the visual operator layer. It keeps the existing
sprite-studio engine as the source of truth and exposes a FastAPI backend
(`studio/api/`) coupled with a React/Vite web interface (`web/`).

## Start

### Option 1: Built Single-Origin Server (Recommended)

```powershell
pip install -e ".[studio]"
cd web
npm run build
cd ..
python -m studio.api.main --port 8765
```

Open `http://127.0.0.1:8765`. FastAPI serves the production React application and handles all API routes.

### Option 2: Frontend Development Mode

In Terminal 1 (FastAPI API server):
```powershell
python -m studio.api.main --port 8765
```

In Terminal 2 (Vite Dev Server):
```powershell
cd web
npm run dev
```

Open `http://127.0.0.1:5173`.

## Phase 1 workflow

1. In **PROJECT**, choose a preset, upload the base image, select directions and
   states, then create a run.
2. In **GENERATE**, inspect the generated prompt, save an optional override, and
   generate one state through the selected provider.
3. If the provider returns a wide free-layout canvas, click **AUTO NORMALIZE**.
   The canonical raw row is updated in place and a normalization report is kept
   beside it.
4. Click **EXTRACT** to produce frames and show the operator-friendly QA result.
5. Click **FRAME REFINE** to derive a refined frame set. It applies one shared
   scale, baseline, grid, palette, and pivot decision for the selected state and
   writes it below `frames/<direction>/<state>/refined/` without overwriting the
   canonical extracted frames.
6. **REVIEW** shows extracted and refined frames. Run **ANIMATION QA** to check
   baseline jitter, scale/weapon jumps, duplicate frames, and handedness flips.
   **OPEN CURATION** launches the existing non-destructive curation UI for the run.
7. **MATRIX** shows run progress, and **EXPORT** composes the current engine atlas.
   **EXPORT RUNTIME 48×48** then creates a nearest-neighbor runtime atlas and a
   runtime manifest without changing the working-size atlas.
8. **RUN BATCH** queues selected state rows and executes generation, optional
   normalization, one shared extraction pass, refine, and animation QA in order.
   **REFRESH BATCH** reads the persisted queue status after the provider finishes.
9. **REVIEW** also shows generation attempt history and engine-owned candidate
   takes (`reroll`, `tween`, and other declared takes) without rewriting them.
   Select an approved frame and use **PIN REVIEW FRAME AS ANCHOR**; the engine's
   directional-anchor resolver validates ownership, generation revision, and frame
   existence before saving the curation pin. **CLEAR ANCHOR PIN** restores the
   anchor-row sequence head.
10. Attack prompts use the preset's declared action text and automatically add a
    handedness continuity clause. The validator warns when a custom attack
    override removes that clause; post-extract Animation QA remains the visual
    evidence gate.

The direct CLI remains available for debugging. The Studio backend uses the
same Python modules (`prepare`, `gen`, `normalize-grok-row`, `extract`, and
`compose-atlas`) rather than copying their implementation.

## Data contracts

- Presets: `studio/data/presets/*.json`
- Translations: `studio/data/i18n/*.json`
- Run metadata: `<run>/studio/studio.json`
- Prompt overrides: `<run>/studio/prompts/<state>.override.txt`
- Generation logs: `<run>/studio-logs/`
- Batch queue: `<run>/studio/batch-queue.json`
- Generation history: `<run>/studio/history/<state>/attempt-*.json`
- Animation QA: `<run>/studio/qa/<state>.animation.json`
- Direction anchors: `<run>/curation.json` and derived `references/anchors/`

Phase 2 currently adds animation continuity QA, the existing curation surface,
and fixed-size runtime export. Batch queue, take history, and anchor editing
remain follow-up work.

## Asset Studio mode split (v0.2)

Studio is now split into **Sprite Mode** and **Static Mode** over a shared core,
per `ASSET_STUDIO_MODE_SPLIT_SPEC_v0.2`. The workflow above is Sprite Mode; it is
unchanged apart from the Refine stage, which now runs the v0.2 engine (shared
animation lattice, bounded phase correction, continuous cell weighting, Oklab
colour metric, thin-feature preservation).

- Full design and rationale: [`docs/asset-studio-modes.md`](asset-studio-modes.md)
- Mode is chosen at the top of the Studio; each mode shows only its own options.
- Static Mode projects (backgrounds, tiles, props, still scenes) live under
  `<project>/static/project.json` and are driven by `studio/backend/static_service.py`.
- Refine thresholds are data: `studio/data/config/{sprite,static}_refine.json`,
  overridable per project through the `refine` block.
- A run pinned to `refine.engine = "v1"` keeps the original `FrameRefiner`
  output byte-for-byte.

Additional data contracts:

- Static presets: `studio/data/presets/static/*.json`
- Static prompt profiles: `studio/data/prompts/profiles/static/*.json`
- Refine settings: `studio/data/config/*.json`
- Sprite refine report: `<run>/frames/<direction>/<state>/refined/refine.report.json`
- Static refine report: `<project>/refined/<asset>.report.json`
- Benchmark: `python -m studio.benchmark --out runs/benchmark/baseline.json`
