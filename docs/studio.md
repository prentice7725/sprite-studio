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

## React workspace workflow

1. In **PROJECT**, choose a data-backed preset, upload the optional base image,
   select directions and animations, then create an asset. The preset supplies
   cell sizes, mirrors, locks, generation profile, and state specs.
2. Select the asset and animation from the shared Asset Library, then open
   **WORKSPACE**. Generate, Refine, Repair, QA, and Export are tools in that
   workspace; they keep the active asset/state selection instead of asking for a
   new state on every page.
   The persistent canvas viewer supports checker/grid toggles and integer zoom;
   the frame timeline supports thumbnail scrubbing, play/loop, and keyboard
   navigation. Repair also exposes generation variants and declared revisions.
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
8. Open **Jobs** from the top bar to queue selected state rows. The global drawer
   executes generation, optional normalization, one shared extraction pass,
   refine, and animation QA while the active asset workspace remains available.
   The persisted queue and WebSocket status remain backend-owned.
11. Static projects use the static preset catalog. Tileable projects expose a
    3×3 wrap context after seam check/repair; non-tileable projects use the same
    canvas viewer without inventing tile controls.
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

## Generation strategy workflow

The Workspace exposes the server-owned strategy enum `AUTO`, `ROW_FAST`, and
`KEYPOSE_SEQUENTIAL`. `AUTO` resolves through
`studio/data/config/generation_strategy.json`; the resolved decision and phase
list are persisted as `<run>/studio/motion-plans/<state>.json`.

For sequential work, generate key poses first, explicitly approve at least two,
then generate bidirectional inbetweens. These images stay in the sequential
manifest until the operator is ready to promote them into a downstream
production pipeline; a failed row-quality gate can point to the same sequential
plan without silently replacing the row result.

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

The current React workflow includes animation continuity QA, the existing
curation surface, fixed-size runtime export, and the global Jobs drawer. Batch
state remains persisted in `<run>/studio/batch-queue.json`; take history and
anchor editing continue to use the existing engine-owned records.

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
