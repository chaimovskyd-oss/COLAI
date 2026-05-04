"""Cartoon artistic effect.

Pipeline:
  1. Bilateral filter — smooths colors while preserving edges
  2. Optional color quantization — flattens tone bands
  3. Canny edge detection on original
  4. Combine smoothed image with black edges
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def apply_cartoon(image: Image.Image, params: dict) -> Image.Image:
    """Return a cartoon-stylised version of *image*.

    params:
        detail        0–100  Higher = more texture/detail preserved in smooth areas
        edge_thickness 0–100  Controls edge boldness and dilation
        color_levels  2–16   Number of quantisation levels (default 8, None = off)
    """
    arr = np.asarray(image.convert("RGB"))

    detail = int(params.get("detail", 60))
    edge_thickness = int(params.get("edge_thickness", 40))
    color_levels = int(params.get("color_levels", 8))

    # ── 1. Bilateral smooth ───────────────────────────────────────────────────
    # More detail → less aggressive smoothing (smaller d, tighter sigma)
    d = max(5, 15 - int(detail / 10))              # 5–15
    sigma_color = 25 + (100 - detail) * 0.75       # 25–100
    sigma_space = 15 + (100 - detail) * 0.35       # 15–50
    smoothed = cv2.bilateralFilter(arr, d, sigma_color, sigma_space)

    # ── 2. Colour quantisation ────────────────────────────────────────────────
    if 2 <= color_levels < 16:
        step = 256.0 / color_levels
        smoothed = (np.floor(smoothed.astype(np.float32) / step) * step).clip(0, 255).astype(np.uint8)

    # ── 3. Edge detection on original ────────────────────────────────────────
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    # Adaptive thresholds: finer control means higher low threshold
    low_t = max(15, int(60 - detail * 0.4))
    high_t = max(60, int(160 - detail * 0.8))
    edges = cv2.Canny(gray, low_t, high_t)

    # Dilate to thicken edges according to edge_thickness
    if edge_thickness > 0:
        ksize = max(1, int(edge_thickness / 30))        # 1–3 px radius
        kernel = np.ones((ksize * 2 + 1, ksize * 2 + 1), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)

    # ── 4. Burn edges into smoothed image ────────────────────────────────────
    # edge_strength from edge_thickness: how opaque the black outline is
    edge_opacity = 0.4 + edge_thickness * 0.006   # 0.40–1.0
    edge_mask = (edges.astype(np.float32) / 255.0 * edge_opacity)[..., None]
    result = (smoothed.astype(np.float32) * (1.0 - edge_mask)).clip(0, 255).astype(np.uint8)

    return Image.fromarray(result)
