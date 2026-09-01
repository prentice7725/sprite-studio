# SPDX-License-Identifier: Apache-2.0
"""Content-addressed revision fingerprints for stale-artifact detection.

A filename never proves two things are the same generation — `frame-0.png`
before and after a re-refine is still `frame-0.png` (directive
`SPRITE_STUDIO_V02_FINAL_AUDIT_FIX_DIRECTIVE.md` §3). Anything that needs to
tell "this artifact still matches that other artifact" (Refine residuals
consumed by Repair, Repair logs consumed by AI micro-fix) hashes actual bytes
instead, plus whatever settings shaped those bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence


def content_revision(files: Sequence[Path], *, fingerprint: dict[str, Any] | None = None) -> str:
    """Stable short digest over a set of files' names + bytes.

    ``fingerprint`` folds in non-file state that also determines the output
    (refine settings, shared-lattice identity) — two byte-identical outputs
    produced under different settings must still count as different
    revisions if the settings are what a later re-run would change.
    """
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    if fingerprint:
        digest.update(json.dumps(fingerprint, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()[:24]
