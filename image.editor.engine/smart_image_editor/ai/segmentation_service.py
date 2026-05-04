from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np
from PIL import Image


try:
    import mediapipe as mp
except Exception:  # pragma: no cover - optional runtime dependency
    mp = None


@lru_cache(maxsize=1)
def _selfie_segmenter():
    if mp is None or not hasattr(mp, "solutions") or not hasattr(mp.solutions, "selfie_segmentation"):
        return None
    try:
        return mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=1)
    except Exception:
        return None


def person_mask(image: Image.Image, threshold: float = 0.35) -> np.ndarray:
    """Return a soft subject mask in the range 0..1.

    MediaPipe is used when available. The fallback is a central soft ellipse,
    intentionally conservative so AI effects remain usable without a model.
    """
    rgb = np.asarray(image.convert("RGB"))
    segmenter = _selfie_segmenter()
    if segmenter is not None:
        result = segmenter.process(rgb)
        if result.segmentation_mask is not None:
            mask = result.segmentation_mask.astype(np.float32)
            mask = np.clip((mask - threshold) / max(0.001, 1.0 - threshold), 0, 1)
            return _feather(mask)
    return _fallback_subject_mask(rgb.shape[1], rgb.shape[0])


def has_mediapipe_segmentation() -> bool:
    return _selfie_segmenter() is not None


def _feather(mask: np.ndarray) -> np.ndarray:
    mask = cv2.GaussianBlur(mask, (0, 0), 5)
    return np.clip(mask, 0, 1).astype(np.float32)


def _fallback_subject_mask(width: int, height: int) -> np.ndarray:
    y, x = np.ogrid[:height, :width]
    cx, cy = width / 2, height * 0.48
    rx, ry = width * 0.28, height * 0.42
    dist = ((x - cx) / max(1, rx)) ** 2 + ((y - cy) / max(1, ry)) ** 2
    mask = np.clip(1.25 - dist, 0, 1)
    return _feather(mask.astype(np.float32))
