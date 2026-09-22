# SPDX-License-Identifier: Apache-2.0
"""Resolution contracts shared by the identity-preserving pixel pipeline."""

from __future__ import annotations

from typing import Final


AUTO_LOGICAL_HEIGHTS: Final[tuple[int, ...]] = (128, 160, 192, 256)
LOGICAL_HEIGHTS: Final[frozenset[int]] = frozenset(AUTO_LOGICAL_HEIGHTS)


def is_logical_height(value: int) -> bool:
    return value in LOGICAL_HEIGHTS


def require_logical_height(value: int, *, field_name: str = "target_height") -> int:
    value = int(value)
    if value not in LOGICAL_HEIGHTS:
        raise ValueError(f"{field_name} must be one of {AUTO_LOGICAL_HEIGHTS}, got {value}")
    return value


__all__ = ["AUTO_LOGICAL_HEIGHTS", "LOGICAL_HEIGHTS", "is_logical_height", "require_logical_height"]
