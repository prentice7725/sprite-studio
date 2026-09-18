#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compatibility CLI for the Phase 2A executor.

The executor's AI-input preflight is narrowed here for deterministic-only
development runs; selecting C1 or C2 still requires all pre-existing AI input
files and never falls back to a generated substitute.
"""

from __future__ import annotations

import sys

from tools import pixel_master_benchmark_v2_execute as executor


_original_preflight = executor._preflight_ai_inputs


def _preflight_ai_inputs(context, ai_root):
    if not any(method_id in context.methods for method_id in ("C1", "C2")):
        return
    return _original_preflight(context, ai_root)


executor._preflight_ai_inputs = _preflight_ai_inputs


if __name__ == "__main__":
    raise SystemExit(executor.main())
