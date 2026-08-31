# SPDX-License-Identifier: MIT
"""Scene cleanup and static repair."""

from .scene_cleanup import CleanupResult, cleanup_scene, fill_holes, harden_alpha, label_components, remove_orphans

__all__ = ["CleanupResult", "cleanup_scene", "fill_holes", "harden_alpha", "label_components", "remove_orphans"]
