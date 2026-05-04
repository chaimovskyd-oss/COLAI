"""Pencil Sketch artistic effect.

Pipeline:
  1. Convert to greyscale
  2. Invert
  3. Gaussian blur (controlled by detail)
  4. Divide-blend of original grey with blurred inverse → sketch
  5. Gamma curve to control line darkness (line_strength)
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def apply_sketch(image: Image.Image, params: dict) -> Image.Image:
    """Return a pencil-sketch version of *image*.

    params:
        detail       0–100  Higher = finer lines / more texture detail
        edge_thickness 0–100  Controls line darkness (acts as line_strength)
    """
    detail = int(params.get("detail", 60))
    line_strength = int(params.get("edge_thickness", 50))

    gray = np.asarray(image.convert("L")).astype(np.float32)

    # ── Blur radius: more detail → smaller blur ───────────────────────────────
    sigma = max(1.0, 25.0 - detail * 0.22)        # ~25 at detail=0, ~1 at detail=100
    inverted = 255.0 - gray
    blurred = cv2.GaussianBlur(inverted, (0, 0), sigma)

    # ── Dodge-blend: gray / (1 − blurred/255) ────────────────────────────────
    denom = 255.0 - blurred
    denom = np.where(denom < 1.0, 1.0, denom)
    sketch = np.clip(gray * 255.0 / denom, 0, 255)

    # ── Gamma curve to darken lines ───────────────────────────────────────────
    # Higher line_strength → lower exponent → darker greys become black faster
    gamma = max(0.3, 2.0 - line_strength * 0.016)  # 2.0→0.4 over 0–100
    sketch = np.power(sketch / 255.0, gamma) * 255.0

    result = sketch.clip(0, 255).astype(np.uint8)
    return Image.fromarray(result).convert("RGB")
