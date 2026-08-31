# SPDX-License-Identifier: Apache-2.0
"""Static QA - one image judged in space, not over time."""

from .static_qa import StaticQaResult, run_static_qa

__all__ = ["StaticQaResult", "run_static_qa"]
