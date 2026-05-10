"""Fast per-image analysis: sharpness, brightness, orientation, faces, importance.

Optimised for ~100 images:
- All metrics from a 256×256 thumbnail (one disk read per image)
- Face count reused from existing detection cache — no extra inference
- Screenshot detection via simple heuristic (uniform row variance)
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import TYPE_CHECKING, Optional

import numpy as np
from PIL import Image, ImageOps, ImageStat

from .models import PhotoMeta

if TYPE_CHECKING:
    from app.models.project import ImageState

logger = logging.getLogger(__name__)

_THUMB_SIZE = 256


def analyze_photo(
    state: 'ImageState',
    existing_analysis=None,     # ImageAnalysis if already computed
) -> PhotoMeta:
    """Return PhotoMeta for a single image. Fast — thumbnail only."""
    path = state.path
    meta = PhotoMeta(path=path)

    try:
        with Image.open(path) as raw:
            img = ImageOps.exif_transpose(raw).convert('RGB')

        meta.width, meta.height = img.size
        meta.orientation = _orientation(meta.width, meta.height)

        thumb = img.copy()
        thumb.thumbnail((_THUMB_SIZE, _THUMB_SIZE), Image.Resampling.BILINEAR)
        arr = np.array(thumb, dtype=np.uint8)

        meta.sharpness = _sharpness(arr)
        meta.brightness = _brightness(arr)
        meta.is_screenshot = _is_screenshot(arr, meta.width, meta.height)
        meta.phash = _phash(thumb)

        # Reuse already-detected faces rather than re-running inference
        if existing_analysis is not None and existing_analysis.faces:
            meta.face_count = len(existing_analysis.faces)
        elif existing_analysis is not None:
            meta.face_count = 0

        meta.importance = _importance(meta)

    except Exception as exc:
        logger.warning('analyze_photo failed for %s: %s', path, exc)

    return meta


# ─── metric helpers ──────────────────────────────────────────────────────────

def _orientation(w: int, h: int) -> str:
    ratio = w / max(1, h)
    if ratio > 1.15:
        return 'landscape'
    if ratio < 0.87:
        return 'portrait'
    return 'square'


def _sharpness(arr: np.ndarray) -> float:
    """Laplacian variance on grayscale thumbnail, normalised to [0..1]."""
    try:
        import cv2
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        lap = cv2.Laplacian(gray.astype(np.float32), cv2.CV_32F)
        var = float(lap.var())
        return float(min(1.0, var / 1200.0))
    except Exception:
        # Fallback: numpy gradient approximation
        gray = arr.mean(axis=2).astype(np.float32)
        gy = np.diff(gray, axis=0)
        gx = np.diff(gray, axis=1)
        var = float(gy.var() + gx.var())
        return float(min(1.0, var / 600.0))


def _brightness(arr: np.ndarray) -> float:
    """Mean luminance (0..1) using perceptual weights."""
    r = arr[:, :, 0].mean() * 0.299
    g = arr[:, :, 1].mean() * 0.587
    b = arr[:, :, 2].mean() * 0.114
    return float(min(1.0, (r + g + b) / 255.0))


def _is_screenshot(arr: np.ndarray, orig_w: int, orig_h: int) -> bool:
    """Heuristic: screenshots have very low variance in individual rows."""
    if orig_w < 640:
        return False
    gray = arr.mean(axis=2).astype(np.float32)
    row_var = float(gray.var(axis=1).mean())   # variance within each row
    return row_var < 12.0


def _phash(thumb: Image.Image) -> str:
    """8-byte perceptual hash using DCT-lite (average hash fallback)."""
    small = thumb.convert('L').resize((16, 16), Image.Resampling.BILINEAR)
    arr = np.array(small, dtype=np.float32)
    avg = arr.mean()
    bits = (arr > avg).flatten()
    hex_str = hashlib.md5(bits.tobytes()).hexdigest()[:16]
    return hex_str


def _importance(m: PhotoMeta) -> float:
    """Composite importance score [0..1] used for hero detection and placement."""
    score = 0.0

    # Sharpness is the strongest signal
    score += m.sharpness * 0.40

    # Faces make images more important (portraits are album heroes)
    face_bonus = min(0.35, m.face_count * 0.15)
    score += face_bonus

    # Penalise brightness extremes (too dark / blown out)
    bright_deviation = abs(m.brightness - 0.55) * 1.6
    score += max(0.0, 1.0 - bright_deviation) * 0.15

    # Orientation bonus: portraits tend to make strong hero images
    if m.orientation == 'portrait':
        score += 0.05

    # Screenshots and very blurry images are de-prioritised
    if m.is_screenshot:
        score *= 0.25
    elif m.sharpness < 0.08:
        score *= 0.50

    return float(max(0.0, min(1.0, score)))
