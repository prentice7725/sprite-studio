# SPDX-License-Identifier: Apache-2.0
"""Object cutout and scene layer separation."""

from .cutout import Layer, compose_layers, cutout_object, split_layers

__all__ = ["Layer", "compose_layers", "cutout_object", "split_layers"]
