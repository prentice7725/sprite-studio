# SPDX-License-Identifier: MIT
"""Oklab colour metric — the one distance space both modes agree on.

ASSET_STUDIO_MODE_SPLIT_SPEC_v0.2 §5.5 makes this a contract, not a taste
call: representative-colour selection, thin-feature continuity, palette
compatibility and repair colour choice all have to measure "how different are
these two colours" the same way. Mixing an Oklab palette build with an RGB
continuity test is how a protected sword tip gets a colour the palette never
contains — the two stages disagree about what "close" means.

sRGB byte in, Oklab float out (Björn Ottosson's transform). Everything is
vectorised over a trailing size-3 axis so a whole frame costs one call.
"""

from __future__ import annotations

import numpy as np


_LMS_FROM_LINEAR = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ]
)
_OKLAB_FROM_LMS = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ]
)
_LMS_FROM_OKLAB = np.array(
    [
        [1.0, 0.3963377774, 0.2158037573],
        [1.0, -0.1055613458, -0.0638541728],
        [1.0, -0.0894841775, -1.2914855480],
    ]
)
_LINEAR_FROM_LMS = np.array(
    [
        [4.0767416621, -3.3077115913, 0.2309699292],
        [-1.2684380046, 2.6097574011, -0.3413193965],
        [-0.0041960863, -0.7034186147, 1.7076147010],
    ]
)


def srgb_to_linear(srgb: np.ndarray) -> np.ndarray:
    """sRGB in [0, 1] to linear light. Vectorised, no per-pixel branching."""
    srgb = np.asarray(srgb, dtype=np.float64)
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(linear: np.ndarray) -> np.ndarray:
    linear = np.asarray(linear, dtype=np.float64)
    return np.where(linear <= 0.0031308, linear * 12.92, 1.055 * np.clip(linear, 0.0, None) ** (1 / 2.4) - 0.055)


def rgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    """(..., 3) sRGB bytes (0-255) or floats (0-1) to (..., 3) Oklab.

    Byte input is detected by dtype, not by value range: a float array that
    happens to hold only 0.0 and 1.0 is still a 0-1 array, and guessing from the
    max would silently rescale a two-colour frame.
    """
    array = np.asarray(rgb)
    scaled = array.astype(np.float64) / 255.0 if array.dtype.kind in "ui" else array.astype(np.float64)
    linear = srgb_to_linear(scaled)
    lms = linear @ _LMS_FROM_LINEAR.T
    # cbrt, not **(1/3): the latter returns nan for the slightly-negative values
    # that a wide-gamut-ish rounding error can produce.
    return np.cbrt(lms) @ _OKLAB_FROM_LMS.T


def oklab_to_rgb(oklab: np.ndarray, *, as_bytes: bool = True) -> np.ndarray:
    lms_root = np.asarray(oklab, dtype=np.float64) @ _LMS_FROM_OKLAB.T
    linear = lms_root**3 @ _LINEAR_FROM_LMS.T
    srgb = np.clip(linear_to_srgb(linear), 0.0, 1.0)
    if not as_bytes:
        return srgb
    return np.clip(np.rint(srgb * 255.0), 0, 255).astype(np.uint8)


def delta_e(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Oklab euclidean distance, broadcast over everything but the last axis."""
    diff = np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)
    return np.sqrt(np.sum(diff * diff, axis=-1))


def rgb_delta_e(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Perceptual distance between sRGB colours without leaving byte space at the call site."""
    return delta_e(rgb_to_oklab(a), rgb_to_oklab(b))


def nearest_index(colors_oklab: np.ndarray, palette_oklab: np.ndarray) -> np.ndarray:
    """Index of the closest palette entry for each colour. (N,3) and (K,3) in, (N,) out."""
    colors = np.asarray(colors_oklab, dtype=np.float64).reshape(-1, 3)
    palette = np.asarray(palette_oklab, dtype=np.float64).reshape(-1, 3)
    if palette.size == 0:
        raise ValueError("palette must contain at least one colour")
    distances = np.sum((colors[:, None, :] - palette[None, :, :]) ** 2, axis=2)
    return np.argmin(distances, axis=1)
