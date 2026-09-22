# Phase 2B Smoke Failure Triage

## Initial smoke failures

The first R00/R03/R06 smoke produced 9 baseline `PASS`, 4 `PASS_LOGICAL_MASTER`, and 2 `FAIL_LOGICAL_MASTER` results. The two failures were analyzed before rerun.

| Source | Method | Semantic gate | PSE | Logical validator | Final status | Root cause |
|---|---|---|---|---|---|---|
| R03 | D1 | `PASS_SEMANTIC_SOURCE` | `PASS_PSE` | `FAIL_LOGICAL_MASTER` | `FAIL_LOGICAL_MASTER` | `IMPLEMENTATION_BUG` — PSE output itself had subject height 128, but gentle cleanup re-ran border-background inference on the already-cropped logical image and removed 157 border-connected subject pixels. The final subject height became 126. |
| R06 | D1 | `WARN_PAINTERLY` | `PASS_PSE` | `FAIL_LOGICAL_MASTER` | `FAIL_LOGICAL_MASTER` | `PSE_PROJECTION` — the semantic source retained unusually color-rich detail and the PSE coverage projection dropped the first two logical subject rows, producing subject height 126. No validator or threshold was relaxed. |

## Code fix

Only confirmed implementation bugs were changed:

- Added `remove_background` to `AiPixelMasterCleanupOptions`.
- PSE-owned logical masters now call gentle cleanup with `remove_background=False` and `geometry_resize=False`.
- PSE-owned logical masters also skip generic isolated-pixel deletion; the logical validator remains responsible for rejecting isolated noise.
- PSE background detection now combines sparse transparency with border-connected chroma detection. A single transparent pixel no longer prevents removal of an opaque magenta border while preserving internal magenta details.
- Added regression tests for PSE logical edge preservation, edge singletons, and sparse transparency plus border chroma.

No threshold relaxation, resize rescue, palette-limit relaxation, forbidden resampling, forced acceptance, or automatic human score was added.

## Smoke reruns

The same R00/R03/R06 smoke was rerun after each confirmed bug fix. Provider outputs were regenerated; Full R00–R08 was not run.

The first post-fix rerun exposed two additional visual-QC facts: a sparse-transparent/opaque-magenta D1 output that the original PSE background detector mishandled, and a D2/R00 valid top-edge singleton removed by generic cleanup. Both were fixed without changing validator policy.

These later findings are recorded separately from the initial two failure rows above: the initial D1/R06 failure was a 126px PSE projection result, while the later opaque-magenta case was a distinct background-detection bug in a newly generated provider output.

- D1: `PASS 3/3`, `FAIL 0/3`
- D2: `PASS 3/3`, `FAIL 0/3`
- Total: `PASS=9`, `PASS_LOGICAL_MASTER=6`
- All six D1/D2 results have subject height 128, binary alpha, and palette within the configured limit.
- Final logical QC found zero opaque magenta pixels in all six D1/D2 logical masters.
- `human_scores.csv` remains blank.

## Decision

`GO` for the Phase 2B Full R00–R08 benchmark: the post-fix smoke gate is 6/6 validated logical masters.

This is a gate decision only. It does not declare D1 or D2 a visual winner; human review remains pending.
