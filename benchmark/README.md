# Pixelize Phase 1 benchmark

This directory contains the Phase 1 comparison requested by `PIXELIZE_BENCHMARK_PLAN.md`:

- `A1_current_m1_1`: current M1.1 pipeline;
- `A2_box`: subject geometry first, BOX resize, palette after resize;
- `A3_lanczos`: subject geometry first, LANCZOS resize, palette after resize.

The checked-in runner is `tools/pixelize_benchmark.py`. It creates ten deterministic synthetic proxy sources when the real compact source set is not available. These proxies are deliberately labelled in the report; they are for operation-order screening and do not replace human evaluation of production art.

Run from the repository root:

```powershell
python tools/pixelize_benchmark.py --bootstrap-synthetic --force
```

The runner writes:

- `sources/`: D01–D10 synthetic proxy inputs;
- `outputs/`: result PNG, 4x/8x previews, subject crop, palette JSON, pixelize report, metadata, and metrics per case;
- `sheets/`: focus contact sheets by source and method;
- `reports/`: machine-readable JSON, flat CSV scores, human rubric CSV, and `benchmark_summary.md`.

A matching case is skipped on later runs. Use `--force` after changing the engine or matrix. Narrow runs are useful during development, for example `--sources D01 --sizes 96 --no-sheets`.

The generated summary is the source of truth for the run-specific result and states the human-review status separately from the objective heuristic.