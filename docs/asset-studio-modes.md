# Asset Studio — Sprite Mode / Static Mode

Implementation of `ASSET_STUDIO_MODE_SPLIT_SPEC_v0.2`. One Studio, one shared
core, two production modes with their own Refine Engines.

```text
Asset Studio
├─ Shared Core      studio/shared/
├─ Sprite Mode      studio/sprite_mode/
└─ Static Mode      studio/static_mode/
```

The governing principle (§0): **share the core, split the pipeline, QA and
post-processing along the grain of what is being produced.** An animation row
and a background tile fail in different ways, so they get different algorithms —
but they measure colour, weight cells and score grids identically, because a
refine that disagrees with the palette build about "close" produces results no
later stage can reconcile.

## Why the two modes cannot share a Refine Engine

| | Sprite Mode | Static Mode |
|---|---|---|
| Unit of work | a row of frames | one image |
| Cell pitch | **locked across the state** (§5.2) | per image, free |
| Phase | **bounded** per frame (§5.3) | free |
| Thin features | protected, coverage relaxed (§5.6) | not applicable |
| Grid search | small images, exhaustive | **FFT-proposed**, coarse-to-fine (§8.2) |
| Dithering | **never** | optional, off by default (§8.4) |
| Seams | not applicable | checked, optionally repaired (§8.6) |
| QA asks | does it hold together *over time* | does it hold together *in space* |

## Shared Core — `studio/shared/`

| Module | Responsibility |
|---|---|
| `color/oklab.py` | the one distance space both modes measure in (§5.5) |
| `config/settings.py` | every threshold as data; unknown keys are errors (§3.2) |
| `grid/edges.py` | axis edge profiles, locked to the engine's own definition |
| `grid/search.py` | pitch/phase scan, integer tie-break |
| `grid/weighting.py` | continuous cell weighting curve (§5.4) |
| `grid/sampling.py` | weighted Oklab cell sampling — where a lattice becomes pixels |
| `palette/` | deterministic Oklab palette build and remap |
| `benchmark/` | synthetic degradation harness (§9) |
| `modes.py` | the mode registry; refuses anything undeclared |

### No hardcoded thresholds

Every number lives in `studio/data/config/<mode>_refine.json` and may be
overridden per project. Loading is strict: an unknown section, an unknown key,
or a malformed weighting curve raises rather than silently falling back to a
default nobody can see.

```jsonc
// studio/data/config/sprite_refine.json (excerpt)
"lattice":   { "scope": "state", "max_pitch": 48, "confidence_floor": 0.2 },
"phase":     { "correction": "bounded", "tolerance": 0.35 },
"weighting": { "anchors": [[0.0, 1.0], [0.5, 0.7], [0.8, 0.3], [1.0, 0.1]] },
"color":     { "metric": "oklab", "detail_bias": true }
```

A project's `refine` block layers over those, in either the spec's flat form or
a sectioned one:

```json
{ "refine": { "shared_lattice_scope": "state", "phase_correction": "bounded",
              "cell_weighting": "continuous", "color_metric": "oklab" } }
```

## Sprite Mode — `studio/sprite_mode/`

```text
Shared Lattice Estimate -> Bounded Phase Correction -> Continuous Cell Weighting
  -> Oklab Sampling -> Thin-feature Preservation -> Residual Handoff to Repair
```

* **Shared lattice** (`refine/lattice.py`) — cell pitch is estimated once from
  every frame's summed edge evidence and locked for the state (or the character,
  with `lattice.scope`). Per-frame estimation lands on 6.0 in one frame and 6.3
  in the next, and the dots visibly boil across the row.
* **Bounded phase** (`refine/phase.py`) — each frame gets its own phase, but only
  within `phase.tolerance` of the shared one. An unbounded search is a spatial
  warp; across a row it reads as the character sliding. A frame that wanted to
  leave the bound is held at it **and reported** (`phase_clamped_frames`).
* **Continuous weighting** (`shared/grid/weighting.py`) — the old hard core
  margin rounds to zero on small cells, which is exactly where thin features
  live. The falloff curve never multiplies by zero.
* **Thin-feature preservation** (`refine/thin_feature.py`) — marks source pixels
  belonging to structures at most `max_thickness` *cells* thick (measured in
  source pixels, so it scales with the lattice) and lets the sampler keep them on
  reduced coverage. It never paints, bridges, or moves anything; what it still
  loses is reported as a residual for the Repair layer.

Every frame of a state lands on **one logical canvas** by construction: cut lines
come from the shared lattice and are *shifted* by each frame's bounded offset, so
the cell count cannot vary across the row.

**Ordering matters**: the lattice snap happens *before* placement. Snapping the
raster the generator actually produced is what recovers true logical pixels;
placing first would grid-lock an already-resampled image.

## Static Mode — `studio/static_mode/`

```text
Large-image Grid Search -> FFT Candidate Proposal -> Oklab Palette Mapping
  -> Scene Cleanup -> Tile / Seam-aware Processing -> Static Repair
```

* **FFT proposes, the exact scorer disposes** (`refine/fft_candidates.py`). A
  periodogram names a few plausible cell sizes so a 1024² search does not score
  every pitch; it never picks the grid, because a periodogram reports a texture's
  repeat period just as happily as the pixel lattice. Note that a perfect impulse
  train gives every harmonic equal power — which is precisely why the proposal
  cannot be the decision.
* **Dithering is Static-only and off by default** (`refine/dither.py`). It lives
  under `static_mode/` so Sprite Mode cannot reach it: dither on a 48×48 unit
  reads as damage and destroys the flat regions a palette swap needs. Error
  diffuses in linear light; the nearest entry is chosen in Oklab.
* **Seams** (`tile/seam.py`) — wrap partners compared in Oklab, with alpha
  discontinuity counted as a seam (a colour-only metric scores an opaque edge
  meeting a transparent one as perfect). Repair is offered, never automatic.
* **Layers** (`layer/cutout.py`) — a split returns masks over the original
  pixels, so re-composing reproduces the input exactly; that round-trip is
  checked and recorded, not asserted.

## Projects and modes

`mode` is the field that splits the Studio. Each mode has its own contract, and
each refuses the other's:

| | Sprite | Static |
|---|---|---|
| Config | `StudioRunConfig` | `StaticProjectConfig` |
| Service | `backend/run_manager.py` | `backend/static_service.py` |
| Presets | `studio/data/presets/*.json` | `studio/data/presets/static/*.json` |
| Prompt | `core/prompt/assembler.py` | `static_mode/prompt/assembler.py` |
| Validator | `PromptValidator` | `StaticPromptValidator` |

The prompt validators are separate for a concrete reason: the sprite validator
requires "full body", "single character" and "not cropped" clauses. A ground
texture has no body, no character, and *must* be cropped at every edge — those
four checks are all correct by sprite rules and all wrong for a tile.

Runs created before the split carry no `mode` field and load as sprite runs;
that is a fact about history, not a guess, since nothing else existed.

Static project layout:

```text
<project>/
  static/project.json          declared config
  raw/<asset>.png              generated or imported source
  refined/<asset>.png          logical output (true resolution)
  refined/<asset>.report.json  refine report
  export/<asset>.png           delivery-size export (NEAREST only)
  qa/<asset>.json              static QA record
  qa/<asset>.cleanup.json      cleanup record
  qa/<asset>.seam.json         seam check / repair record
```

`CLEANUP` is a stage of its own rather than a refine toggle: re-running refine
to try a different speck threshold would re-run the grid search and re-decide
the lattice, which is not what an operator tuning cleanup is asking for.
`static_service.cleanup_asset` works on the already-refined logical output.

## Refine engine selection

`refine_service.refine_state` dispatches on the run's declared mode, and within
Sprite Mode on `refine.engine`:

* `v2` (default) — the engine described above.
* `v1` — the original `FrameRefiner`, kept so pre-split runs reproduce exactly.

## Benchmark — the gate for algorithm changes

```bash
python -m studio.benchmark --out runs/benchmark/baseline.json   # record
python -m studio.benchmark --baseline runs/benchmark/baseline.json  # compare
python -m studio.benchmark --list-degradations
```

Ground truth is degraded the way a generator degrades art — blur, subpixel
offset, anti-aliased resize, pseudo-pixel alias, chroma contamination, boundary
bleed, thin-feature loss — then refined and scored against the original.

Two properties make it a gate rather than a demo:

* **Deterministic** — fixed seeds, no RNG in the refine path. A score change
  means the algorithm changed.
* **Per-case comparison** — `compare_runs` names which cases moved and exits
  non-zero on any regression, so a change that lifts the mean while breaking
  three cases cannot pass as an improvement.

A degradation that damages nothing scores a perfect recovery and silently tests
nothing; `tests/shared/test_benchmark.py` locks each degradation against the
asset it models to keep that from recurring.

## UI

The mode selector at the top of the Studio decides which surface exists at all —
Sprite views and Static views are built separately in the React UI and FastAPI
endpoints so an option belonging to the other mode is never reachable (§12.4).

Sprite REFINE shows the shared lattice, cell-size confidence, per-frame phase
offsets (and which frames were held at the bound), thin-feature protection and
the palette summary. Static REFINE shows the FFT candidate list, the chosen
grid, palette/dither mode, seam report and tile wrap preview.

## Production Features & Integrations (v0.2 RC)

* **Character-Scoped Shared Lattice**: `lattice.scope == "character"` estimates a single shared lattice over all frames across states and locks it for consistent pixel pitch.
* **Sprite Refine Residual → Repair Handoff**: Thin-feature loss during refine is recorded as structured residuals and automatically consumed by `RepairPipeline` as high-priority repair candidates. The handoff is revision-safe — Refine stamps a content-hashed `output_revision` (refined frame bytes + settings/lattice fingerprint) into `refine.report.json`, and Repair recomputes that hash before trusting a residual; a mismatch (or a report predating this field) reports an explicit `stale` status instead of silently keeping or silently dropping the residual.
* **Static Provider Generation & Dither Presets**: Full provider generation pipeline with prompt assembler/validator for static assets, plus data-driven dither presets (`environment_soft`, `environment_crisp`, `scenery_diffuse`).
* **Multi-Metric Benchmark Gating**: Multi-metric evaluation and strict regression gates across silhouette, color, thin-feature, palette, edge, temporal, texture, and seam metrics, checked in CI against a committed baseline (`studio/data/benchmark/baseline.json`) via `python -m studio.benchmark --baseline ...` — a run with no `--baseline` only prints scores and gates nothing.
* **Batch Observability**: Real-time persistent batch queue tracking progress percentages, stages, elapsed time, and thread lifecycle. `batch-queue.json` is published via temp-file + atomic replace so a UI poll never observes a torn write, and a genuinely corrupt file reports an explicit `corrupt` status rather than a partial payload.
* **Strict Data Configuration**: Refine/QA/Benchmark settings are required-key, required-section, no-hidden-default dataclasses — a config missing a tuning value (or an entire section, e.g. Sprite's inert `dither`/`seam`) fails to load instead of silently filling in a code default. Benchmark's own cross-module policy constants (opaque-alpha threshold, palette-retained ΔE, texture-collapse ratio) are likewise a committed `metric_policy` section, not independent literals per metric function.

### Known gaps before `v0.2 Complete`

* **i18n visible-string sweep** — not started. UI labels, button text, tab titles and status/validation messages are still English/Korean literals in the UI modules rather than routed through locale resources.
* **Sprite UI pipeline-stage rail** — not started. The Sprite tabs are still organized as `PROJECT / GENERATE / REVIEW / MATRIX / EXPORT`, not the `GENERATED → NORMALIZED → EXTRACTED → REFINED → REPAIRED → QA → EXPORT` stage rail.

Until both are closed, this reads as **v0.2 RC** — the mechanisms above are production-wired and race/stale/hidden-default failures are caught by tests, but the spec isn't fully closed out.

