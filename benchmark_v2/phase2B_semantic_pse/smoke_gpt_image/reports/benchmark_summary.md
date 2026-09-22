# Pixel Master Benchmark V2 — Phase 2B GPT Image smoke R00/R03/R06

## Scope

- Sources: 3 (R00, R03, R06)
- Methods: 5 (A1, A2, B1, D1, D2)
- Compared artifact: validated logical master only
- Preview: 4× nearest-neighbor for every logical tile
- C1/C2 strict capability results remain in the Phase 2A appendix and are not mixed into this ranking.

## Execution result

- Logical comparisons: 3 sources × 5 methods = 15 method results
- Status: PASS=9, PASS_LOGICAL_MASTER=6
- Objective palette-size proxy: D2 (36.333)
- Objective palette-size proxy is not a visual-quality decision; no visual ranking is emitted.
- Human review: pending; `human_scores.csv` intentionally remains blank.

## Artifacts

- `semantic/` and `intermediate/` — AI audit artifacts only
- `logical/` — accepted PSE logical masters only
- `validation/` — semantic quality, PSE, and logical-master records
- `sheets/by_source/` and `sheets/by_method/` — logical-only contact sheets
- `sheets/semantic_audit/` — semantic/intermediate audit sheets
- `reports/pse_metrics.csv` — PSE and semantic quality metrics
- `reports/logical_master_results.csv` — final logical master acceptance records

## GPT Image provider gate

- Semantic provider: OpenAI GPT Image via built-in `image_gen`; Grok was not used.
- D1/D2 order: GPT Image semantic output → PSE → logical master validator.
- Rescue policy: none; no LANCZOS, bilinear, BOX, threshold, or palette rescue.
- D1 logical masters: 3/3
- D2 logical masters: 3/3
- Recommendation: GO — all six D1/D2 smoke logical masters were accepted; full R00–R08 may proceed.
