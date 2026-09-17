# PIXELIZE M1 TEST PLAN

Status: implemented draft

## 1. Automated tests

### Engine determinism

Given identical input/options:

- logical dimensions are identical
- output PNG bytes are identical
- palette JSON is identical
- requested fixed palette is not exceeded

### Palette lock

Every opaque output RGB value must be present in the resolved palette.

### Alpha cleanup

With `background=cleanup`, output alpha values must be binary (`0` or `255`).

### API persistence

A Static project with a raw source must produce accessible project-relative URLs for:

- master PNG
- 4x preview
- palette JSON
- Pixel Profile
- report JSON

### Missing source

Pixelize must fail explicitly if `<project>/raw/<asset>.png` is missing.

## 2. CI gates

The existing CI should run the new Python tests through the normal pytest matrix and continue to run the React TypeScript/Vite build gate.

No new dependency is introduced in M1; the engine uses the repository's existing Pillow, NumPy, Oklab palette and ordered-dither implementations.

## 3. Manual visual benchmark

Automated correctness does not prove attractive pixel art. Before calling the algorithm quality-stable, assemble at least ten source illustrations covering:

1. clean anime/cel-shaded character
2. painterly character
3. dark outfit / dark outline
4. bright hair / pale skin
5. thin sword or spear
6. fine costume trim
7. transparent source
8. hard flat background
9. soft gradient background
10. small face at full-body scale

For each source, render:

- Pixelize 64 / 16 colors
- Pixelize 96 / 24 colors
- Pixelize 128 / 32 colors
- Pixelize 192 / 48 colors
- naive nearest baseline
- naive smooth-downsample baseline

Review at 1x logical size and 4x nearest zoom.

## 4. Visual acceptance checklist

### Silhouette

- no large contour collapse
- thin limbs/weapons remain readable when resolution permits
- transparent edge does not develop gray/color fringe

### Face/readability

- eye/hair/skin regions do not merge unnecessarily
- small dark features are not erased by majority fill

### Palette

- no invented anti-alias fringe colors
- no obvious near-duplicate palette waste
- major costume/hair/skin color families remain distinct

### Pixel character

The result should read as deliberate logical pixels, not as a smooth illustration that was merely shrunk.

### Outline preserve mode

Compare `preserve` against `auto`. `preserve` should improve useful dark contours without globally darkening textured regions.

### Dither

- `none` is the default reference
- `ordered-low` must not obscure silhouettes at target size
- `ordered` is acceptable for textured/static assets but should not become the recommended character default

## 5. M2 temporal tests

When video-frame support is added, reuse this M1 profile/palette and add tests for:

- identical fixed palette across all frames
- no stochastic dither
- palette-index flicker rate
- silhouette IoU / jump outliers
- baseline drift
- scale drift
- loop first/last-frame continuity

M2 must not build independent palettes per extracted frame.
