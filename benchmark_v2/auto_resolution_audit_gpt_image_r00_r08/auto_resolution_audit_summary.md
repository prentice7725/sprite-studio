# Auto Resolution R00–R08 identity audit

D1/D2 semantic inputs use GPT Image only. No Grok fallback, resize rescue, threshold relaxation, or automatic visual winner declaration was used.
R08 is recorded separately as the hard case. Human scores remain blank pending direct review.

## Status counts

- FAIL_NOT_ABSTRACTED: 5
- IDENTITY_REVIEW_UNAVAILABLE: 3
- PASS_AUTO_RESOLUTION: 6
- SEMANTIC_REDRAW_LOSS: 4

## Selected logical heights

- D1: 128px: 1, 160px: 2, 192px: 1
- D2: 128px: 1, 160px: 1

## Manual gate assessment

Inspected the final logical-master-only `sheets/by_source/` for R00, R02, R05, R07, and hard-case R08; candidate sheets for R00 D1/D2, R02 D1, R05 D1, and R07 D1/D2; the R08 semantic audit; and the R08 IFM overlay. This was a qualitative gate sanity check only, not a human score.

- The selected resolutions looked plausible in the reviewed accepted cases: R00 at 128px, R02 D1 at 160px, R05 D1 at 192px, and R07 D1/D2 at 160px. Lower-resolution candidate losses visible in R02 D1 and R05 D1 are consistent with choosing the first passing resolution.
- The R08 IFM boxes broadly identify the intended face/hair, cloak, book, lantern, and watch. Both D1 and D2 semantic redraws were rejected for face/hair CENTER-side relation changes. The images remain broadly recognizable, so this is a conservative borderline case that should receive a focused coordinate/topology review; it is not evidence to relax the gate in this audit.
- D2/R05 and both R06 identity reviews are unavailable due to reviewer timeouts. They remain unavailable/fail-closed and are not treated as passes.
- Human scores remain blank; no automatic visual winner is declared.

## Full production recommendation

STOP. Reviewed accepted examples broadly agree with the gate, but the R08 side-relation borderline case and three unavailable identity reviews prevent a production GO. Do not tune thresholds or reinterpret unavailable reviews as passes from this audit. No human score or visual winner has been entered.
