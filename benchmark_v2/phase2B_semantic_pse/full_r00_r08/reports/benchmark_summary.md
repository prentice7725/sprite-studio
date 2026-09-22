# Pixel Master Benchmark V2 — Phase 2B Full R00–R08

## Scope

- Sources: 9 (R00, R01, R02, R03, R04, R05, R06, R07, R08)
- Methods: 5 (A1, A2, B1, D1, D2)
- Compared artifact: validated logical master only
- Preview: 4× nearest-neighbor for every logical tile
- C1/C2 strict capability results remain in the Phase 2A appendix and are not mixed into this ranking.

## Execution result

- Logical comparisons: 9 sources × 5 methods = 45 method results
- Status: FAIL_LOGICAL_MASTER=1, PASS=27, PASS_LOGICAL_MASTER=17
- D1 logical master success: 9/9
- D2 logical master success: 8/9
- Failure code distribution: FAIL_LOGICAL_MASTER=1; subject-height-invalid=1 (D2/R06)
- Objective palette-size proxy: D2 (43.875)
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

## R08 hard case

R08 is recorded separately as the painterly/low-contrast hard case. No threshold or rescue policy was changed for it.

- D1: semantic=PASS_SEMANTIC_SOURCE; pse=PASS_PSE; logical=PASS_LOGICAL_MASTER; warnings=none
- D2: semantic=PASS_SEMANTIC_SOURCE; pse=PASS_PSE; logical=PASS_LOGICAL_MASTER; warnings=none
