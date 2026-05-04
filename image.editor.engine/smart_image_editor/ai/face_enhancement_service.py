from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageEnhance

from smart_image_editor.ai.face_detection_service import face_mask


def brighten_faces(image: Image.Image, amount: int) -> Image.Image:
    if amount <= 0:
        return image
    mask = face_mask(image)[..., None]
    if mask.max() <= 0:
        return image
    arr = np.asarray(image.convert("RGB")).astype(np.float32)
    bright = ImageEnhance.Brightness(image).enhance(1 + amount / 160.0)
    bright = ImageEnhance.Contrast(bright).enhance(1 + amount / 260.0)
    bright_arr = np.asarray(bright).astype(np.float32)
    out = arr * (1 - mask) + bright_arr * mask
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def protect_skin_tones(image: Image.Image, amount: int) -> Image.Image:
    if amount <= 0:
        return image
    rgb = np.asarray(image.convert("RGB"))
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    hue = hsv[:, :, 0] * 2
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    skin = ((hue < 45) | (hue > 340)) & (sat > 25) & (sat < 210) & (val > 45)
    face = face_mask(image) > 0.05
    mask = skin | face
    hsv[:, :, 1][mask] *= 1 - amount / 280.0
    hsv[:, :, 2][mask] *= 1 + amount / 520.0
    out = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2RGB)
    return Image.fromarray(out)
