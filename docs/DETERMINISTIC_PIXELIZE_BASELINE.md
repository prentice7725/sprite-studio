# Deterministic Pixelize baseline

R7 benchmarks the image-to-sprite transformation path, not AI generation or
provider quality. The run reads the immutable R00–R08 Tier-B fixtures only
after SHA-256 verification with
`benchmark_v2/configs/tier_b_fixtures_r00_r08.json`.

The default suite has one 128-logical-height conversion for each frozen source,
plus a derived transparent-background case based on R01. That derived input
uses a deterministic dominant-border RGB distance key (`>20`) and is labelled
as derived in the manifest and CSV; it is not an original transparent source.
R08 remains a separately labelled realistic-anime hard case. No fixture source
is rewritten.

Run it into a new, empty output directory:

```powershell
py -3.11 -m tools.pixelize_baseline_benchmark --out runs/deterministic-pixelize-baseline
```

The output contains the source and prepared-source hashes, extracted subject,
logical master, exact 4× NEAREST preview, per-case contact sheets,
`logical_master_results.csv`, `run_manifest.json`, and a summary generated from
the runtime manifest. Existing non-empty output directories are never
overwritten. The `runs/` directory is ignored by Git.

The gate checks artifact validation and deterministic repeatability. A PASS is
not a visual-quality approval. Contact sheets show source, subject, the logical
master displayed at 4× NEAREST for inspection, and the saved preview. Human
score/note fields stay blank; there is no automatic visual winner.
