# Pixel Master Benchmark V2 — Phase 2A Logical Rebenchmark

## Scope

- Sources: 3 (R00, R03, R06)
- Methods: 5 (A1, A2, B1, C1, C2)
- Compared artifact: validated logical master only
- Preview: 4× nearest-neighbor for every logical tile

## Execution result

- Logical comparisons: 3 sources × 5 methods = 15 method results
- Status: FAIL_LOGICAL_GRID=6, PASS=9
- Objective palette-size proxy: TIE — A1, A2, B1 (48.0)
- Objective palette-size proxy is not a visual-quality decision; no visual ranking is emitted.
- Human review: pending; `human_scores.csv` intentionally remains blank.

## Artifacts

- `logical/` — only accepted logical masters
- `transport/` and `intermediate/` — AI audit artifacts only
- `validation/` — logical-grid and provenance records
- `sheets/by_source/` and `sheets/by_method/` — logical-only contact sheets
- `sheets/ai_audit/` — transport/intermediate audit sheets
- `reports/logical_grid_results.csv` — validation and failure records
