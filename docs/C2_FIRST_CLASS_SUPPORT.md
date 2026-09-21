# C2 First-Class Support + AI Pixel Master Cleanup

## Scope

`reference_pixel_master_128` is the first-class C2 strategy for reference-guided AI pixel-style redraws. It is available from both the Quick workflow and the Static Pixelize API/UI, and is the default Quick Pixelize strategy.

The strategy is deliberately separate from the deterministic `preserve` path. Existing Preserve behavior remains unchanged; C2 uses an AI-aware cleanup pipeline that protects pixel clusters and avoids the destructive smoothing behavior of the shared legacy cleanup path.

## Reference and fallback policy

- C2 requires the source/reference image to exist.
- The target size is fixed at 128 logical pixels.
- The provider receives the frozen source reference in both generation stages.
- There is no deterministic or synthetic fallback when a C2 provider call or required reference is unavailable.
- Only a validator-approved logical post-cleanup master can be accepted; raw transport and intermediate files remain audit artifacts.
- Tier B benchmark fixtures remain immutable. Benchmark runs may consume only files already present under `benchmark_v2/sources/tier_b`; required `R00`–`R08` files must pass SHA-256 verification before each run.

## C2 pipeline

1. Generate an intermediate reference-guided AI redraw from the source reference.
2. Generate the raw C2 candidate using the same source reference plus the intermediate candidate.
3. Remove chroma/background pixels before subject cropping.
4. Crop to the surviving subject and normalize height with nearest-neighbor scaling.
5. Preserve palette clusters and apply binary alpha; only obvious isolated noise is eligible for removal.
6. Emit the post-cleanup Pixel Master artifact and audit metadata.

When validation or cleanup is uncertain, the raw transport candidate remains available for visual review but cannot be accepted. Color-rich or painterly-risk candidates receive an explicit warning instead of silent success.

## Artifacts

Each C2 run preserves:

- `intermediate/<stem>.png`
- `raw/<stem>.png`
- `post/<stem>.png`
- `post/<stem>.preview-4x.png`
- `post/<stem>.palette.json`
- `post/<stem>.profile.json`
- `report/<stem>.report.json`

The report records the strategy, source reference, provider provenance for both AI stages, cleanup decisions, subject bounds, logical size, palette, and accepted artifact.

## Validation

The milestone is covered by the AI cleanup, Quick C2 API, Static C2 API, existing Quick API, and frontend tests. Frontend production build and Vitest run are also part of the verification pass.
