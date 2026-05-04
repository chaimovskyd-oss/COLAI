from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class HistogramStats:
    red: list[int]
    green: list[int]
    blue: list[int]
    luminance: list[int]
    shadow_clip_percent: float
    highlight_clip_percent: float


def calculate_histogram(image: Image.Image, bins: int = 256) -> HistogramStats:
    arr = np.asarray(image.convert("RGB"))
    red = np.histogram(arr[:, :, 0], bins=bins, range=(0, 255))[0]
    green = np.histogram(arr[:, :, 1], bins=bins, range=(0, 255))[0]
    blue = np.histogram(arr[:, :, 2], bins=bins, range=(0, 255))[0]
    lum = (arr[:, :, 0] * 0.2126 + arr[:, :, 1] * 0.7152 + arr[:, :, 2] * 0.0722).astype(np.uint8)
    luminance = np.histogram(lum, bins=bins, range=(0, 255))[0]
    total = max(1, lum.size)
    shadow_clip = float((lum <= 2).sum() / total * 100)
    highlight_clip = float((lum >= 253).sum() / total * 100)
    return HistogramStats(
        red=red.astype(int).tolist(),
        green=green.astype(int).tolist(),
        blue=blue.astype(int).tolist(),
        luminance=luminance.astype(int).tolist(),
        shadow_clip_percent=shadow_clip,
        highlight_clip_percent=highlight_clip,
    )


def suggest_auto_levels(image: Image.Image) -> dict:
    arr = np.asarray(image.convert("RGB")).astype(np.float32)
    lum = arr.mean(axis=2)
    low, high = np.percentile(lum, [1.0, 99.0])
    if high <= low:
        return {}
    contrast = int(np.clip((180.0 / (high - low) - 1) * 55, -20, 35))
    brightness = int(np.clip((128.0 - (low + high) / 2) / 2.2, -35, 35))
    return {"brightness": brightness, "contrast": contrast}


def suggest_auto_contrast(image: Image.Image) -> dict:
    arr = np.asarray(image.convert("RGB")).astype(np.float32)
    spread = np.percentile(arr, 95) - np.percentile(arr, 5)
    contrast = int(np.clip((150.0 - spread) / 3.5, -15, 35))
    return {"contrast": contrast}
