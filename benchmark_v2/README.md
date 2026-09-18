# Pixel Master Benchmark V2 fixture policy

`benchmark_v2/sources/tier_b` is an immutable input set. The required `R01`–`R08`
files must already exist and must match the SHA-256 values in
`configs/tier_b_fixtures.json` before a V2 run starts.

The guard is `tools/tier_b_fixture_guard.py`:

```python
from tools.tier_b_fixture_guard import ai_reference_plan, verify_tier_b_fixtures

fixtures = verify_tier_b_fixtures(required_ids=["R01", "R03", "R04", "R06"])
references = ai_reference_plan(fixtures, ["R01", "R03", "R04", "R06"])
```

The guard has no bootstrap, redraw, synthesis, or replacement path. Missing or
modified fixtures are hard failures. `references[source_id]["C1"]` and
`references[source_id]["C2"]` intentionally point to the same frozen `Rxx` path.
