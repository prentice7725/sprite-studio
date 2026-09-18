#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the Phase 2A executor with method-aware AI preflight."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import pixel_master_benchmark_v2_execute as executor


_original_preflight = executor._preflight_ai_inputs


def _preflight_ai_inputs(context, ai_root):
    if not any(method_id in context.methods for method_id in ("C1", "C2")):
        return
    return _original_preflight(context, ai_root)


executor._preflight_ai_inputs = _preflight_ai_inputs


if __name__ == "__main__":
    raise SystemExit(executor.main())
