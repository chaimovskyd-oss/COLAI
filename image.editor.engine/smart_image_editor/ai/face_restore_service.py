from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from smart_image_editor.ai.compat import install_torchvision_functional_tensor_shim
from smart_image_editor.ai.face_detection_service import face_mask
from smart_image_editor.ai.model_registry import GFPGAN_V14, ensure_model


@lru_cache(maxsize=1)
def _gfpganer():
    model_path = ensure_model(GFPGAN_V14, auto_download=True)
    if model_path is None:
        return None
    try:
        install_torchvision_functional_tensor_shim()
        import torch
        from gfpgan import GFPGANer

        return GFPGANer(
            model_path=str(model_path),
            upscale=1,
            arch="clean",
            channel_multiplier=2,
            bg_upsampler=None,
            device="cuda" if torch.cuda.is_available() else "cpu",
        )
    except Exception:
        return None


def restore_faces(image: Image.Image, strength: int = 100) -> Image.Image:
    if strength <= 0:
        return image
    restorer = _gfpganer()
    if restorer is not None:
        try:
            arr = np.asarray(image.convert("RGB"))
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            _cropped, _restored, output = restorer.enhance(
                bgr,
                has_aligned=False,
                only_center_face=False,
                paste_back=True,
                weight=max(0.0, min(1.0, strength / 100.0)),
            )
            rgb = cv2.cvtColor(output, cv2.COLOR_BGR2RGB)
            return Image.fromarray(rgb)
        except Exception:
            pass
    return fallback_face_restore(image, strength)


def fallback_face_restore(image: Image.Image, strength: int = 100) -> Image.Image:
    mask = face_mask(image)[..., None]
    if mask.max() <= 0:
        return image
    amount = max(0.0, min(1.0, strength / 100.0))
    smooth = image.filter(ImageFilter.GaussianBlur(radius=0.5 + amount))
    sharp = ImageEnhance.Sharpness(smooth).enhance(1 + amount * 1.2)
    bright = ImageEnhance.Brightness(sharp).enhance(1 + amount * 0.08)
    base = np.asarray(image.convert("RGB")).astype(np.float32)
    restored = np.asarray(bright.convert("RGB")).astype(np.float32)
    blend = mask * amount
    out = base * (1 - blend) + restored * blend
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def has_gfpgan() -> bool:
    return _gfpganer() is not None
