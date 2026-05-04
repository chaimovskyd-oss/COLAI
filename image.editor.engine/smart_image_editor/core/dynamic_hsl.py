"""Dynamic HSL / Soft Color Zones

Replaces the legacy hard-threshold HSL implementation.  Each named color zone
uses a smooth hue-distance falloff instead of a binary include/exclude range,
giving natural, overlap-free colour corrections without banding or hard edges.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


DYNAMIC_HSL_COLORS = ["red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta"]

HUE_CENTERS: dict[str, float] = {
    "red": 0.0,
    "orange": 30.0,
    "yellow": 60.0,
    "green": 120.0,
    "aqua": 180.0,
    "blue": 220.0,
    "purple": 270.0,
    "magenta": 310.0,
}

_CHANNEL_DEFAULTS: dict[str, int] = {
    "hue_shift": 0,
    "saturation": 0,
    "luminance": 0,
    "range_width": 35,
    "softness": 25,
}


def default_dynamic_hsl() -> dict:
    return {color: dict(_CHANNEL_DEFAULTS) for color in DYNAMIC_HSL_COLORS}


def channel_default(channel: str) -> int:
    return _CHANNEL_DEFAULTS.get(channel, 0)


# ---------------------------------------------------------------------------
# Core mask
# ---------------------------------------------------------------------------

def _compute_channel_mask(
    hue_deg: np.ndarray,
    sat_norm: np.ndarray,
    center_hue: float,
    range_width: float,
    softness: float,
) -> np.ndarray:
    """Return a float32 [0,1] mask for one colour zone.

    Pixels within *range_width* degrees of *center_hue* get weight 1.0.
    Weight falls off linearly to 0 over the next *softness* degrees.
    Very desaturated pixels are softly down-weighted to avoid grey-area
    contamination.
    """
    dist = np.abs(((hue_deg - center_hue + 180.0) % 360.0) - 180.0)
    inner = float(range_width)
    outer = inner + max(float(softness), 0.001)
    hue_weight = np.where(
        dist <= inner,
        1.0,
        np.where(dist <= outer, 1.0 - (dist - inner) / (outer - inner), 0.0),
    ).astype(np.float32)
    # Soft saturation guard — weight drops smoothly for near-grey pixels
    sat_weight = np.clip(sat_norm / 0.12, 0.0, 1.0).astype(np.float32)
    return hue_weight * sat_weight


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------

def apply_dynamic_hsl(image: Image.Image, dynamic_hsl_params: dict) -> Image.Image:
    """Apply all Dynamic HSL channel edits to *image* non-destructively."""
    if not dynamic_hsl_params:
        return image

    arr = np.asarray(image.convert("RGB"))
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV).astype(np.float32)
    # OpenCV HSV: H in [0,180], S and V in [0,255]
    hue_raw = hsv[:, :, 0]
    sat_raw = hsv[:, :, 1]
    val_raw = hsv[:, :, 2]

    for color in DYNAMIC_HSL_COLORS:
        values = dynamic_hsl_params.get(color) or {}
        hue_shift = float(values.get("hue_shift", 0))
        saturation = float(values.get("saturation", 0))
        luminance = float(values.get("luminance", 0))
        if not (hue_shift or saturation or luminance):
            continue

        range_width = float(values.get("range_width", _CHANNEL_DEFAULTS["range_width"]))
        softness = float(values.get("softness", _CHANNEL_DEFAULTS["softness"]))
        center = HUE_CENTERS[color]

        hue_deg = hue_raw * 2.0          # [0, 360)
        sat_norm = sat_raw / 255.0       # [0, 1]
        mask = _compute_channel_mask(hue_deg, sat_norm, center, range_width, softness)

        if hue_shift:
            # Each OpenCV hue unit == 2 degrees; positive shift rotates toward higher hues
            shift_units = hue_shift * 0.5
            hue_raw = (hue_raw + shift_units * mask) % 180.0
            hsv[:, :, 0] = hue_raw

        if saturation:
            factor = 1.0 + saturation / 100.0
            blend = 1.0 + (factor - 1.0) * mask
            sat_raw = np.clip(sat_raw * blend, 0.0, 255.0)
            hsv[:, :, 1] = sat_raw

        if luminance:
            factor = 1.0 + luminance / 100.0
            blend = 1.0 + (factor - 1.0) * mask
            val_raw = np.clip(val_raw * blend, 0.0, 255.0)
            hsv[:, :, 2] = val_raw

    out = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2RGB)
    return Image.fromarray(out)


# ---------------------------------------------------------------------------
# Isolation preview overlay
# ---------------------------------------------------------------------------

def create_dynamic_hsl_isolation_overlay(
    image: Image.Image,
    color_name: str,
    params: dict | None = None,
) -> Image.Image:
    """Preview overlay: affected pixels stay in colour, rest becomes greyscale.

    Uses the channel's current range_width/softness from *params* so the
    preview matches the actual processing exactly.  This is display-only and
    never written to export or history.
    """
    color = color_name.lower()
    if color not in HUE_CENTERS:
        return image

    channel_params = (params or {}).get(color) or {}
    range_width = float(channel_params.get("range_width", _CHANNEL_DEFAULTS["range_width"]))
    softness = float(channel_params.get("softness", _CHANNEL_DEFAULTS["softness"]))
    center = HUE_CENTERS[color]

    arr = np.asarray(image.convert("RGB"))
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV).astype(np.float32)
    hue_deg = hsv[:, :, 0] * 2.0
    sat_norm = hsv[:, :, 1] / 255.0

    mask = _compute_channel_mask(hue_deg, sat_norm, center, range_width, softness)
    # Slight spatial feather for a pleasant visual result
    mask = cv2.GaussianBlur(mask, (0, 0), 3.0)
    mask = np.clip(mask, 0.0, 1.0)[..., None]

    color_f = arr.astype(np.float32)
    gray_f = np.asarray(image.convert("L").convert("RGB")).astype(np.float32)
    out = gray_f * (1.0 - mask) + color_f * mask
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
