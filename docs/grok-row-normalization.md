# Grok row normalization

Grok Imagine can obey a four-subject sprite-row prompt while returning a wide
16:9 canvas. `sprite-studio normalize-grok-row` is the explicit deterministic
adapter for that result. It removes the declared chroma background, finds the
expected subject spans, removes boundary debris, fits one subject into each
cell, and writes the component-row strip expected by `sprite-studio extract`.

It does not call an image model and it does not silently change `gen` output.
The report records whether segmentation was forced, the source spans, leading
overhang trims, and dropped satellite components.

## Usage

```powershell
sprite-studio normalize-grok-row `
  --input runs/sword/raw/side/idle.png `
  --out runs/sword/raw/side/idle.normalized.png `
  --chroma-key green `
  --count 4 `
  --cell-width 256 `
  --cell-height 256 `
  --safe-margin 24 `
  --report runs/sword/raw/side/idle.normalized.report.json
```

The default output is transparent RGBA and is directly consumable by the
component-row extractor. Use `--background chroma` when a green/magenta
background is useful for visual inspection or a downstream tool requires an
opaque keyed image.

After checking the normalized PNG and report, adopt it as the run's canonical
raw state and extract normally:

```powershell
Copy-Item runs/sword/raw/side/idle.normalized.png runs/sword/raw/side/idle.png -Force
sprite-studio extract --run-dir runs/sword --states side_idle
```

For the convenient integrated path, pass the explicit normalization flag
directly to extraction:

```powershell
sprite-studio extract --run-dir runs/sword --states side_idle --normalize-grok-row
```

This normalizes the selected raw state in place, writes a
`<state>.normalize.report.json` sidecar, and then runs the normal extractor.
The flag is opt-in so ordinary extraction never changes a raw source silently.
It also skips rows whose raw image already has the expected `frame_count × cell`
dimensions, so it is safe to leave enabled for a mixed run.

The adapter defaults to four `256×256` cells, a 24-pixel safe margin, nearest
resampling for pixel-art preservation, foot-centroid horizontal alignment, and
bottom alignment. These can be overridden for other subject counts or cell
contracts.
