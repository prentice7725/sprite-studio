# PIXELIZE M1 SPEC

Status: implemented draft  
Scope: high-resolution illustration -> deterministic logical pixel master  
Initial surface: Static workspace  

## 1. Goal

Pixelize converts one high-resolution illustration into a game-oriented logical-resolution pixel master. It is not a smooth resize filter and does not try to imitate a named artist. The output must have a declared logical resolution, a bounded palette, deterministic color mapping, crisp alpha, and reusable profile metadata.

The primary use case is the front half of this production path:

```text
illustration
  -> Pixelize master
  -> image/video animation
  -> frame extraction
  -> reapply Pixel Profile (post-M1)
  -> Refine / QA / Export
```

## 2. M1 inputs

- PNG/JPEG/WEBP accepted by Pillow through the existing import path.
- logical longest edge: `64 | 96 | 128 | 192`
- palette: `auto | 16 | 24 | 32 | 48`
- dither: `none | ordered-low | ordered`
- background alpha: `keep | cleanup`
- outline: `preserve | auto`

The logical longest edge preserves the source aspect ratio. A 320x240 image with `size=96` therefore produces 96x72 logical pixels.

## 3. M1 outputs

Per asset under `<static-project>/pixelized/`:

```text
<asset>.png
<asset>.preview-4x.png
<asset>.palette.json
<asset>.pixel-profile.json
<asset>.pixelize-report.json
```

`<asset>.png` is the canonical logical-resolution master. The 4x preview uses nearest-neighbor scaling only.

## 4. Processing contract

```text
source RGBA
  -> alpha normalization
  -> deterministic shared Oklab palette
  -> palette map in source space
  -> dominant-cell sampling onto explicit logical grid
  -> optional ordered dither
  -> output/profile/palette/report
```

### 4.1 No average-color downsampling

Pixelize never uses average RGB as the logical pixel decision. Average downsampling invents fringe colors between outlines and fills and produces the familiar "small smooth illustration" look. M1 first maps source pixels onto the final palette and then chooses an existing dominant palette color for each logical cell.

### 4.2 Palette

The project reuses Sprite Studio's shared deterministic Oklab palette builder. Fixed palette requests are capped by the source's actual color diversity. `auto` resolves deterministically to 16/24/32/48 based on source color complexity.

### 4.3 Outline preservation

`preserve` may choose an existing dark palette color instead of the modal fill only when that dark color already occupies at least a meaningful share of the source cell. It never invents a new outline color. `auto` uses the normal dominant-cell decision only.

### 4.4 Alpha

`cleanup` converts an existing alpha mask to binary alpha using the declared threshold. M1 does **not** infer a subject mask from a fully opaque background. A fully opaque input with `cleanup` emits a warning rather than pretending segmentation succeeded.

### 4.5 Dither

Dither is off by default. M1 exposes only position-stable ordered dithering for animation friendliness. Error-diffusion dithering is deliberately not exposed in Pixelize M1.

## 5. Pixel Profile

The profile is designed to become the reusable contract for later extracted video frames.

Example:

```json
{
  "target_size": 128,
  "palette_size": 32,
  "dither": "none",
  "background": "cleanup",
  "outline": "preserve",
  "alpha_threshold": 128,
  "palette_mode": "fixed",
  "resolved_palette_size": 32,
  "color_space": "oklab",
  "downsample_mode": "dominant-cell",
  "alpha_mode": "binary"
}
```

Post-M1 frame canonicalization should reuse the saved palette entries rather than rebuilding a palette per frame. That is the contract that prevents color flicker across video-derived animation frames.

## 6. API

`POST /api/static/{project_id}/pixelize`

Request:

```json
{
  "asset": "hero",
  "size": 128,
  "palette": 32,
  "dither": "none",
  "background": "cleanup",
  "outline": "preserve"
}
```

Response includes URLs for the master PNG, 4x preview, palette, profile, report, resolved logical size, resolved palette and warnings.

## 7. CLI

M1 standalone entrypoint:

```bash
$SPRITE_STUDIO_ROOT/.venv/bin/python -m sprite_studio.pixelize input.png \
  --out-dir out/pixelize \
  --size 128 \
  --palette 32 \
  --dither none \
  --background cleanup \
  --outline preserve
```

## 8. Non-goals

M1 does not include:

- opaque-background semantic segmentation
- video generation
- ffmpeg frame extraction
- batch frame Pixel Profile replay
- temporal palette QA
- face/hand/weapon semantic correction
- manual pixel editor

## 9. M1 success criteria

- deterministic output for identical input/options
- output alpha is crisp when cleanup is requested
- output colors are members of the generated palette
- aspect ratio is retained
- palette/profile/report are persisted beside the master
- Static workspace can run Pixelize and compare source/result
- existing Static Refine/QA/Export behavior is untouched
