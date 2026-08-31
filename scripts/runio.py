#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Backward-compatible wrapper for sprite_studio.spec.runio."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sprite_studio.spec.runio as _impl

globals().update({name: value for name, value in vars(_impl).items() if name not in {"__name__", "__package__", "__loader__", "__spec__"}})
