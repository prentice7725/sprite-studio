# Repair pipeline

Studio treats pixel reconstruction and local defect repair as separate stages:

```text
Generate → Normalize → Extract → Refine → Repair Analyze
→ Deterministic Repair → Temporal Repair → Animation QA → Curation → Export
```

`Refine` owns grid, alpha and shared palette reconstruction. `Repair` may only
make bounded local changes with colors already present in that shared palette.
It never overwrites extracted or refined frames.

## Outputs

For a taxonomy state such as `side_attack`, Studio writes:

```text
frames/side/attack/refined/frame-N.png
frames/side/attack/repair/repair.proposals.json
frames/side/attack/repair/proposals/frame-N.png
frames/side/attack/repair/repair.log.json
frames/side/attack/repair/diff/frame-N.png
frames/side/attack/repair/ai-micro-fix/<job-id>/before.png
frames/side/attack/repair/ai-micro-fix/<job-id>/mask.png
frames/side/attack/repair/ai-micro-fix/<job-id>/request.json
frames/side/attack/repaired/frame-N.png
```

The proposal file records every detected candidate. The repair log records
every applied pixel change, its engine, rule and confidence. The log pins both
the refined input bytes and repaired output bytes. Animation QA ignores stale
derived output, while an already adopted Curation/Export source fails loudly
until the operator repairs and adopts again.

## Safety policy

The default data policy is `studio/data/repair/default.json`. A Studio run may
override it through `studio/studio.json` at `config.repair`. Thresholds, search
radius, protected normalized regions and silhouette-growth limits are data,
not algorithm constants.

Unattended repair currently supports:

- enclosed 1–3 logical-pixel holes, with same-color four-neighbor repair as the
  high-confidence case;
- one-logical-pixel gaps between matching outline runs;
- disconnected one-pixel components;
- one/two-cell breaks in a directionally continued thin line, with an empty
  cross-section guard for weapon shafts, strings, plumes, horns and tails;
- a missing logical pixel present in both neighboring frames after a bounded
  ±3-cell alignment search.

The default face region is protected. Attack, hit and down states lower
temporal confidence, so temporal majority cannot silently rewrite motion.
Palette violations, unmasked AI edits and excessive silhouette growth fail or
remain unapplied.

## Studio workflow

In REVIEW:

1. Run **REPAIR ANALYZE** to create overlays without changing a frame.
2. Run **APPLY SAFE** for candidates at or above configured thresholds.
3. Accept or reject selected candidates when operator judgment is needed.
4. For an unresolved exception, select candidates and run **PREPARE AI MICRO
   FIX**. Edit `before.png` only where `mask.png` is white, then import the
   result PNG. The importer rejects dimension changes, soft alpha, colors
   outside the shared palette and any changed unmasked pixel.
5. Run Animation QA; it automatically prefers current repaired frames.
6. Click **ADOPT FOR CURATION/EXPORT**. This writes an explicit, revision-pinned
   `source_variant: repaired` decision into `curation.json`. Every compose, GIF,
   PNG export, layer compose and anchor consumer then resolves the same source.
7. Continue human curation and export normally. **USE CANONICAL FRAMES** removes
   the adoption; **UNDO REPAIR** first reverts adoption and then removes only
   derived repair artifacts.

AI Micro Fix remains provider-neutral and optional. Studio exports a complete
job package rather than assuming a particular image service supports exact
masks. Any external or future built-in provider must return through the same
mask, binary-alpha and shared-palette validator before its result can enter the
repaired set.
