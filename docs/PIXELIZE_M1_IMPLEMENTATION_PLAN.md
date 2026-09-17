# PIXELIZE M1 IMPLEMENTATION PLAN

Status: implemented draft  
Branch: `feature/pixelize-m1`  

## 1. Architecture

Pixelize is intentionally split into four layers.

```text
studio/static_mode/pixelize/engine.py
  deterministic image algorithm
        ↓
studio/backend/pixelize_service.py
  Static-project persistence adapter
        ↓
studio/api/routers/pixelize.py
  HTTP contract
        ↓
web/src/features/static/PixelizePanel.tsx
  operator controls + preview
```

A standalone CLI entrypoint lives at `sprite_studio/pixelize.py` and calls the same engine directly.

## 2. Why this is separate from Static Refine

Static Refine solves **grid recovery**: it receives an image that is already intended to contain pixel structure and tries to infer pitch/phase before snapping it.

Pixelize solves **grid creation**: it receives a smooth illustration and an explicit target logical resolution. There is no hidden lattice to discover, so target cells are declared by the operator.

The two paths share the same Oklab palette core and ordered-dither implementation, avoiding duplicate color logic.

## 3. Engine algorithm

1. Convert input to RGBA.
2. Normalize alpha according to the Pixelize profile.
3. Resolve fixed/auto palette count.
4. Build deterministic Oklab palette using shared palette code.
5. Map the high-resolution source onto that final palette.
6. Partition source pixels into explicit target logical cells.
7. Choose a dominant existing palette color per cell.
8. In outline-preserve mode, allow a sufficiently represented dark palette color to win a cell when it is clearly separated from the modal fill.
9. Apply optional ordered dithering on the logical output.
10. Persist master, preview, palette, profile and report.

## 4. Persistence layout

```text
<project>/
  raw/
    hero.png
  pixelized/
    hero.png
    hero.preview-4x.png
    hero.palette.json
    hero.pixel-profile.json
    hero.pixelize-report.json
  refined/
  qa/
  export/
```

Pixelize does not overwrite `raw/` or `refined/`. This keeps the new operation non-destructive and makes A/B review possible.

## 5. API integration

New endpoint:

`POST /api/static/{project_id}/pixelize`

The router is registered separately from the existing Static router to avoid making the already-large Static adapter larger during M1.

Static project asset serving already accepts project-relative nested paths, so `pixelized/*` output files use the existing asset route without a second file server.

## 6. Web integration

`PixelizePanel` is embedded inside the selected Static project's workbench. M1 UI exposes only decisions that materially affect the result:

- logical longest edge
- palette count / auto
- dither
- outline mode
- alpha cleanup

The result surface contains:

- original source
- 4x nearest-neighbor pixel preview
- resolved logical size
- palette strip
- warnings
- links to PNG/profile/palette JSON
- expandable report

## 7. CLI integration

During M1 validation the command is deliberately standalone:

```bash
$SPRITE_STUDIO_ROOT/.venv/bin/python -m sprite_studio.pixelize INPUT --out-dir OUTPUT
```

Once the algorithm has survived visual benchmark work, it can be added to the legacy `sprite-studio` command registry without changing the engine/API contract.

## 8. Follow-up sequence

### M1.1 — quality benchmark

Build a committed benchmark set containing illustrations with:

- strong dark outlines
- soft painterly edges
- transparent characters
- weapons/thin accessories
- detailed costume trim
- low-contrast shapes

Compare Pixelize against naive bicubic/BOX/nearest baselines at 64/96/128/192.

### M1.2 — master adoption

Add an explicit `Adopt as pixel master` action rather than silently replacing the raw or refined asset.

### M2 — video frame canonicalization

Add:

```text
video
  -> ffmpeg frame extraction
  -> load saved Pixel Profile + fixed palette
  -> frame batch pixelize
  -> temporal QA
  -> sprite sheet
```

The critical M2 rule is that frame batches reuse the master's palette. They must not rebuild a palette independently per frame.

### M2.1 — temporal QA

Measure:

- palette flicker
- silhouette jumps
- frame-to-frame outline instability
- baseline drift
- logical-scale drift

## 9. Risks

### Over-darkening from outline preservation

Mitigation: the dark color must already represent at least 25% of a source cell and must be materially darker than the modal fill. Benchmark this threshold before exposing tuning knobs.

### Auto palette over/under-allocation

M1 auto is deterministic and intentionally simple. Quality benchmark results should drive any future complexity heuristic.

### Opaque background cleanup expectations

M1 never claims semantic segmentation. Fully opaque inputs produce a warning when cleanup is selected.

### UI scope creep

Do not turn Pixelize M1 into a pixel editor. The first goal is deterministic conversion and reusable production metadata.
