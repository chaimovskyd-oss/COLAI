from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageFilter

from smart_image_editor.ai.compat import install_torchvision_functional_tensor_shim
from smart_image_editor.ai.model_registry import REALESRGAN_X4PLUS, ensure_model


@lru_cache(maxsize=1)
def _realesrganer():
    model_path = ensure_model(REALESRGAN_X4PLUS, auto_download=True)
    if model_path is None:
        return None
    try:
        install_torchvision_functional_tensor_shim()
        import torch
        from basicsr.archs.rrdbnet_arch import RRDBNet
        from realesrgan import RealESRGANer

        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
        return RealESRGANer(
            scale=4,
            model_path=str(model_path),
            model=model,
            tile=256,
            tile_pad=10,
            pre_pad=0,
            half=torch.cuda.is_available(),
            gpu_id=0 if torch.cuda.is_available() else None,
        )
    except Exception:
        return None


def upscale_image(image: Image.Image, scale: int = 2, strength: int = 100) -> Image.Image:
    if scale <= 1 or strength <= 0:
        return image
    scale = 4 if scale >= 4 else 2
    upsampler = _realesrganer()
    if upsampler is not None:
        try:
            arr = np.asarray(image.convert("RGB"))
            out, _ = upsampler.enhance(arr, outscale=scale)
            return Image.fromarray(out)
        except Exception:
            pass
    return fallback_upscale(image, scale)


def fallback_upscale(image: Image.Image, scale: int = 2) -> Image.Image:
    size = (image.width * scale, image.height * scale)
    upscaled = image.resize(size, Image.Resampling.LANCZOS)
    return upscaled.filter(ImageFilter.UnsharpMask(radius=1.2, percent=120, threshold=3))


def has_realesrgan() -> bool:
    return _realesrganer() is not None
