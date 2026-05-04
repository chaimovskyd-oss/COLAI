from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageEnhance


DEFAULT_TARGET_COLOR: dict[str, Any] = {
    "enabled": False,
    "samples": [],
    "excluded_samples": [],
    "range_width": 35,
    "softness": 20,
    "hue_shift": 0,
    "saturation": 0,
    "luminance": 0,
}


def default_target_color() -> dict[str, Any]:
    return deepcopy(DEFAULT_TARGET_COLOR)


def sample_target_color(image: Image.Image, x: int, y: int, radius: int = 5) -> dict[str, float]:
    arr = np.asarray(image.convert("RGB"))
    height, width = arr.shape[:2]
    x1, x2 = max(0, x - radius), min(width, x + radius + 1)
    y1, y2 = max(0, y - radius), min(height, y + radius + 1)
    patch = arr[y1:y2, x1:x2]
    if patch.size == 0:
        patch = arr[max(0, min(height - 1, y)) : max(0, min(height - 1, y)) + 1, max(0, min(width - 1, x)) : max(0, min(width - 1, x)) + 1]
    hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV).astype(np.float32)
    sat = hsv[:, :, 1] / 255.0
    weights = np.clip(sat, 0.08, 1.0)
    hue_deg = hsv[:, :, 0] * 2.0
    radians = np.deg2rad(hue_deg)
    mean_sin = float((np.sin(radians) * weights).sum() / max(0.001, weights.sum()))
    mean_cos = float((np.cos(radians) * weights).sum() / max(0.001, weights.sum()))
    hue = (np.rad2deg(np.arctan2(mean_sin, mean_cos)) + 360.0) % 360.0
    return {
        "h": float(hue),
        "s": float(np.average(sat, weights=weights)),
        "l": float(np.average(hsv[:, :, 2] / 255.0, weights=weights)),
    }


def update_target_color_params(params: dict[str, Any] | None, sample: dict[str, float], mode: str = "include") -> dict[str, Any]:
    target = default_target_color()
    target.update(deepcopy(params or {}))
    target["enabled"] = True
    if mode == "exclude":
        target.setdefault("excluded_samples", []).append(sample)
    else:
        target.setdefault("samples", []).append(sample)
    return target


def create_target_color_mask(image: Image.Image, target_color: dict[str, Any] | None, *, feather: bool = True) -> np.ndarray:
    target = default_target_color()
    target.update(deepcopy(target_color or {}))
    samples = target.get("samples") or []
    if not target.get("enabled") or not samples:
        return np.zeros((image.height, image.width), dtype=np.float32)

    cache_key = (_image_cache_key(image), json.dumps(target, sort_keys=True, default=str), feather)
    cached = _MASK_CACHE.get(cache_key)
    if cached is not None:
        return cached.copy()

    arr = np.asarray(image.convert("RGB"))
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV).astype(np.float32)
    hue = hsv[:, :, 0] * 2.0
    sat = hsv[:, :, 1] / 255.0
    val = hsv[:, :, 2] / 255.0
    width = max(1.0, float(target.get("range_width", 35)))
    softness = max(1.0, float(target.get("softness", 20)))
    mask = np.zeros(hue.shape, dtype=np.float32)
    for sample in samples:
        mask = np.maximum(mask, _sample_mask(hue, sat, val, sample, width, softness))
    for sample in target.get("excluded_samples") or []:
        mask *= 1.0 - _sample_mask(hue, sat, val, sample, width, softness)
    if feather:
        mask = cv2.GaussianBlur(mask, (0, 0), 4)
    mask[mask < 0.12] = 0
    mask = np.clip(mask, 0, 1).astype(np.float32)
    _MASK_CACHE[cache_key] = mask.copy()
    return mask


def apply_target_color_adjustment(image: Image.Image, target_color: dict[str, Any] | None) -> Image.Image:
    target = default_target_color()
    target.update(deepcopy(target_color or {}))
    if not target.get("enabled") or not target.get("samples"):
        return image
    mask = create_target_color_mask(image, target)[..., None]
    if mask.max() <= 0:
        return image
    adjusted = _apply_hsv_adjustment(
        image,
        int(target.get("hue_shift", 0)),
        int(target.get("saturation", 0)),
        int(target.get("luminance", 0)),
    )
    base = np.asarray(image.convert("RGB")).astype(np.float32)
    adj = np.asarray(adjusted.convert("RGB")).astype(np.float32)
    out = base * (1 - mask) + adj * mask
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def create_target_color_isolation_overlay(image: Image.Image, target_color: dict[str, Any] | None) -> Image.Image:
    mask = create_target_color_mask(image, target_color)[..., None]
    arr = np.asarray(image.convert("RGB")).astype(np.float32)
    gray = np.asarray(image.convert("L").convert("RGB")).astype(np.float32)
    boosted = np.asarray(ImageEnhance.Color(image).enhance(1.10).convert("RGB")).astype(np.float32)
    out = gray * (1 - mask) + boosted * mask
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def clear_target_color_cache() -> None:
    _MASK_CACHE.clear()


def _sample_mask(hue: np.ndarray, sat: np.ndarray, val: np.ndarray, sample: dict[str, float], width: float, softness: float) -> np.ndarray:
    center = float(sample.get("h", 0.0))
    sample_sat = float(sample.get("s", 0.0))
    sample_val = float(sample.get("l", 0.0))
    hue_distance = np.abs(((hue - center + 180.0) % 360.0) - 180.0)
    hue_mask = _soft_band(hue_distance, width, softness)
    sat_width = max(0.16, 0.22 + width / 240.0)
    val_width = max(0.18, 0.24 + width / 240.0)
    sat_mask = _soft_band(np.abs(sat - sample_sat), sat_width, softness / 100.0)
    val_mask = _soft_band(np.abs(val - sample_val), val_width, softness / 100.0)
    neutral_guard = np.clip((sat - max(0.06, sample_sat * 0.20)) / 0.18, 0, 1)
    return hue_mask * sat_mask * val_mask * neutral_guard


def _soft_band(distance: np.ndarray, width: float, softness: float) -> np.ndarray:
    inner = max(0.0, width - softness)
    return np.clip(1.0 - (distance - inner) / max(0.001, softness), 0, 1)


def _apply_hsv_adjustment(image: Image.Image, hue_shift: int, saturation: int, luminance: int) -> Image.Image:
    arr = np.asarray(image.convert("RGB"))
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV).astype(np.float32)
    hsv[:, :, 0] = (hsv[:, :, 0] + hue_shift / 2.0) % 180
    hsv[:, :, 1] *= 1 + saturation / 100.0
    hsv[:, :, 2] *= 1 + luminance / 100.0
    out = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2RGB)
    return Image.fromarray(out)


def _image_cache_key(image: Image.Image) -> str:
    return f"{image.width}x{image.height}:{hashlib.sha1(image.tobytes()).hexdigest()}"


_MASK_CACHE: dict[tuple[str, str, bool], np.ndarray] = {}
