"""AnimeGAN style transfer via ONNX runtime.

Model path: smart_image_editor/models/animegan.onnx
Place a compatible AnimeGAN2 / AnimeGANv3 ONNX export there.
(The Shinkai_53.onnx file renamed to animegan.onnx works.)

Confirmed model contract (Shinkai_53 / TF-exported AnimeGAN2):
  Input : generator_input:0   float32  [1, H, W, 3]  NHWC  range [-1, 1]
  Output: .../Tanh:0          float32  [1, H, W, 3]  NHWC  range [-1, 1]
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# Default model location — resolved relative to this file:
#   ai_tools/ai/animegan.py  →  parents[3] = repo root
_DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parents[3]
    / "smart_image_editor" / "models" / "animegan.onnx"
)

_SESSION_CACHE: dict[str, object] = {}


def _load_session(model_path: str):
    if model_path in _SESSION_CACHE:
        return _SESSION_CACHE[model_path]
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError(
            "onnxruntime is not installed.\n"
            "Run:  pip install onnxruntime\n"
            "or:   pip install onnxruntime-gpu"
        ) from exc
    if not os.path.exists(model_path):
        raise RuntimeError(
            f"AnimeGAN model not found at:\n{model_path}\n\n"
            "Place animegan.onnx in smart_image_editor/models/\n"
            "(rename Shinkai_53.onnx → animegan.onnx)"
        )
    session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    _SESSION_CACHE[model_path] = session
    return session


def _pad_to_multiple(arr: np.ndarray, multiple: int = 32) -> tuple[np.ndarray, tuple[int, int]]:
    """Pad H and W up to the nearest multiple of *multiple*."""
    h, w = arr.shape[:2]
    ph = (-h) % multiple
    pw = (-w) % multiple
    if ph or pw:
        arr = cv2.copyMakeBorder(arr, 0, ph, 0, pw, cv2.BORDER_REFLECT)
    return arr, (h, w)


def apply_animegan(
    image: Image.Image,
    params: dict,
    model_path: str | None = None,
) -> Image.Image:
    """Apply AnimeGAN style transfer to *image*.

    Confirmed input layout: NHWC float32 [1, H, W, 3], range [-1, 1].
    Confirmed output layout: NHWC float32 [1, H, W, 3], range [-1, 1].
    Strength blending is handled by the service dispatcher, not here.
    """
    if model_path is None:
        model_path = str(_DEFAULT_MODEL_PATH)

    session = _load_session(model_path)

    arr = np.asarray(image.convert("RGB"))

    # Pad H and W to multiples of 32 (safe practice for strided convolutions)
    padded, (orig_h, orig_w) = _pad_to_multiple(arr, multiple=32)

    # Normalise [0, 255] → [-1, 1], keep NHWC by adding batch dim only
    x = (padded.astype(np.float32) / 127.5 - 1.0)[None]   # (1, H, W, 3)

    input_name = session.get_inputs()[0].name
    output = session.run(None, {input_name: x})[0]          # (1, H, W, 3)

    # Denormalise [-1, 1] → [0, 255], remove batch dim and any padding
    out = ((output[0] + 1.0) * 127.5).clip(0, 255).astype(np.uint8)
    out = out[:orig_h, :orig_w]                             # (orig_H, orig_W, 3)

    return Image.fromarray(out)
