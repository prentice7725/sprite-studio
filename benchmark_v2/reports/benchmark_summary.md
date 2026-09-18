# Pixel Master Benchmark V2 — Phase 2A Summary

## Scope

- Sources: 8 (Tier A: D01, D03, D06, D10; Tier B: R01, R03, R04, R06)
- Methods: A1, A2, B1, C1, C2
- Target: 128 logical pixels, Auto palette, Balanced detail
- States: raw and post
- Tier B policy: immutable existing files only; SHA-256 verified before run

## Execution result

- Completed artifacts: 80 (8 sources × 5 methods × 2 states)
- Objective post palette-size proxy winner: **A1 deterministic M1.1**
- Human review: pending; fill `human_scores.csv` before making a visual-quality promotion decision.

## Interpretation

Objective metrics are supporting signals only. The final Preserve and Pixel Master creation recommendations require the human rubric, especially identity, face readability, asymmetric feature preservation, cluster quality, and cleanup burden.

## Artifacts

- `raw/<method>/<source>.png` — direct method output
- `post/<method>/<source>.png` — shared normalization, palette, alpha, and isolated-pixel cleanup
- `reports/objective_scores.csv` / `.json` — machine-readable metrics
- `reports/human_scores.csv` — 1–5 review template
- `sheets/by_source/` and `sheets/by_method/` — contact sheets
