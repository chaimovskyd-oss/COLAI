from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from smart_image_editor.ai.segmentation_service import person_mask


def apply_background_blur(image: Image.Image, amount: int, darken: int = 0) -> Image.Image:
    if amount <= 0 and darken <= 0:
        return image
    mask = person_mask(image)[..., None]
    arr = np.asarray(image.convert("RGB")).astype(np.float32)
    radius = max(1, amount / 3.0)
    blurred = np.asarray(image.filter(ImageFilter.GaussianBlur(radius=radius))).astype(np.float32)
    if darken > 0:
        blurred *= max(0.2, 1.0 - darken / 140.0)
    out = arr * mask + blurred * (1 - mask)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def enhance_subject(image: Image.Image, amount: int) -> Image.Image:
    if amount <= 0:
        return image
    mask = person_mask(image)[..., None]
    arr = np.asarray(image.convert("RGB")).astype(np.float32)
    enhanced = ImageEnhance.Contrast(image).enhance(1 + amount / 180.0)
    enhanced = ImageEnhance.Sharpness(enhanced).enhance(1 + amount / 120.0)
    enhanced_arr = np.asarray(enhanced).astype(np.float32)
    out = arr * (1 - mask) + enhanced_arr * mask
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def subject_coverage(image: Image.Image) -> float:
    mask = person_mask(image)
    return float(mask.mean())
