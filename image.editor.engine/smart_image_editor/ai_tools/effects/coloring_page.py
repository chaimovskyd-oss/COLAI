"""Coloring Page effect.

Goal: clean black outlines on pure white background — suitable for printing
and hand-colouring.

Pipeline:
  1. Smooth with Gaussian blur (noise reduction)
  2. Canny edge detection
  3. Morphological cleanup to remove speckles
  4. Dilate edges to desired thickness
  5. Invert → black lines on white background
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def apply_coloring_page(image: Image.Image, params: dict) -> Image.Image:
    """Return a clean line-art version of *image*.

    params:
        detail         0–100  Higher = lower Canny thresholds → more detail lines
        edge_thickness 0–100  Controls line thickness after edge detection
    """
    detail = int(params.get("detail", 60))
    edge_thickness = int(params.get("edge_thickness", 40))

    gray = np.asarray(image.convert("L"))

    # ── 1. Pre-smooth to reduce noise ────────────────────────────────────────
    # Less detail → more blurring → fewer noise edges
    blur_sigma = max(0.5, 4.0 - detail * 0.03)     # ~4 at detail=0, ~1 at detail=100
    smoothed = cv2.GaussianBlur(gray, (0, 0), blur_sigma)

    # ── 2. Canny edge detection ───────────────────────────────────────────────
    # More detail → lower thresholds → capture finer edges
    low_t = max(5, 60 - int(detail * 0.55))         # 60→5
    high_t = max(20, 160 - int(detail * 1.4))       # 160→20
    edges = cv2.Canny(smoothed, low_t, high_t)

    # ── 3. Morphological cleanup — remove tiny speckles ──────────────────────
    clean_kernel = np.ones((3, 3), np.uint8)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, clean_kernel, iterations=1)

    # ── 4. Dilate to desired line thickness ───────────────────────────────────
    if edge_thickness > 0:
        ksize = max(1, int(edge_thickness / 25))    # 1–4 px radius
        thick_kernel = np.ones((ksize * 2 + 1, ksize * 2 + 1), np.uint8)
        edges = cv2.dilate(edges, thick_kernel, iterations=1)

    # ── 5. Invert: black lines on white ───────────────────────────────────────
    result = (255 - edges).astype(np.uint8)
    return Image.fromarray(result).convert("RGB")
