"""Posterize artistic effect.

Reduces the number of distinct colour levels per channel, creating a
flat, graphic-poster look.  Optionally preserves luminosity smoothness
via soft-step quantisation.
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def apply_posterize(image: Image.Image, params: dict) -> Image.Image:
    """Return a posterised version of *image*.

    params:
        detail  0–100  Maps to colour levels: detail=0 → 2 levels,
                       detail=100 → 12 levels (more detail = more levels)
    """
    detail = int(params.get("detail", 60))

    # Map detail (0–100) to levels (2–12)
    levels = max(2, min(12, 2 + int(detail / 10)))

    arr = np.asarray(image.convert("RGB")).astype(np.float32)

    # Hard quantisation: snap each channel to nearest multiple
    step = 255.0 / (levels - 1)
    result = (np.round(arr / step) * step).clip(0, 255).astype(np.uint8)

    return Image.fromarray(result)
