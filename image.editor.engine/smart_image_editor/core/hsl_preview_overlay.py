from __future__ import annotations

import hashlib

import cv2
import numpy as np
from PIL import Image


HUE_CENTERS = {
    "red": 0,
    "orange": 30,
    "yellow": 60,
    "green": 120,
    "aqua": 180,
    "blue": 220,
    "purple": 270,
    "magenta": 310,
}

OVERLAY_COLORS = {
    "red": (255, 90, 110),
    "orange": (255, 160, 80),
    "yellow": (255, 220, 90),
    "green": (105, 220, 130),
    "aqua": (90, 230, 220),
    "blue": (100, 160, 255),
    "purple": (170, 120, 255),
    "magenta": (255, 100, 190),
}


def create_hsl_color_mask(
    image: Image.Image,
    color_name: str,
    *,
    hue_width: float = 32.0,
    saturation_threshold: float = 0.15,
    mask_feather: float = 5.0,
    feather: bool = True,
) -> np.ndarray:
    color = color_name.lower()
    if color not in HUE_CENTERS:
        return np.zeros((image.height, image.width), dtype=np.float32)
    arr = np.asarray(image.convert("RGB"))
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV).astype(np.float32)
    hue = hsv[:, :, 0] * 2.0
    saturation = hsv[:, :, 1] / 255.0
    value = hsv[:, :, 2] / 255.0
    center = HUE_CENTERS[color]
    hue_distance = np.abs(((hue - center + 180) % 360) - 180)
    hue_mask = np.clip(1.0 - hue_distance / hue_width, 0, 1)
    sat_mask = np.clip((saturation - saturation_threshold) / max(0.001, 1 - saturation_threshold), 0, 1)
    dark_allowance = np.where(saturation > 0.45, 0.18, 0.28)
    value_mask = np.clip((value - dark_allowance) / 0.45, 0, 1)
    mask = hue_mask * sat_mask * value_mask
    if feather:
        mask = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), mask_feather)
    return np.clip(mask, 0, 1).astype(np.float32)


def create_hsl_affected_overlay(
    image: Image.Image,
    color_name: str,
    *,
    isolation_strength: int = 100,
    affected_boost: int = 10,
    mask_feather: float = 5.0,
) -> Image.Image:
    cache_key = (_image_cache_key(image), color_name.lower(), float(mask_feather))
    mask = _MASK_CACHE.get(cache_key)
    if mask is None:
        mask = create_hsl_color_mask(image, color_name, mask_feather=mask_feather)
        _MASK_CACHE[cache_key] = mask
    arr = np.asarray(image.convert("RGB")).astype(np.float32)
    gray = np.asarray(image.convert("L").convert("RGB")).astype(np.float32)
    isolation = max(0.0, min(1.0, isolation_strength / 100.0))
    outside = arr * (1 - isolation) + gray * isolation
    highlighted = _boost_saturation(arr, affected_boost)
    blend = mask[..., None]
    out = outside * (1 - blend) + highlighted * blend
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def clear_hsl_preview_cache() -> None:
    _MASK_CACHE.clear()


def _image_cache_key(image: Image.Image) -> str:
    digest = hashlib.sha1(image.tobytes()).hexdigest()
    return f"{image.size[0]}x{image.size[1]}:{digest}"


_MASK_CACHE: dict[tuple[str, str, float], np.ndarray] = {}


def _boost_saturation(arr: np.ndarray, amount: int) -> np.ndarray:
    if amount <= 0:
        return arr
    gray = arr.mean(axis=2, keepdims=True)
    factor = 1 + min(30, amount) / 100.0
    return np.clip(gray + (arr - gray) * factor, 0, 255)
