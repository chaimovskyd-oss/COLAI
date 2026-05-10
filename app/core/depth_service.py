"""Depth estimation service — DepthAnything V2 Small.

Powers three optional features:
  1. קרופ חכם    (Smart Crop)    — compute_smart_crop_pan()
  2. חפיפת עומק  (Depth Overlap) — composite_depth_overlap()
  3. שכבות עומק  (Depth Layers)  — apply_depth_layers()

Model is loaded once per session and released on demand.
Depth maps are cached in memory keyed by image path.

# TODO: migrate to model_manager when available
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"
_CACHE_DIR = "./models"

_depth_pipe = None                          # singleton pipeline
_DEPTH_MAP_CACHE: Dict[str, np.ndarray] = {}  # path → float32 [0..1]

try:
    import transformers as _tf
    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    _tf = None
    _TRANSFORMERS_AVAILABLE = False

try:
    import cv2 as _cv2
    _CV2_AVAILABLE = True
except ImportError:
    _cv2 = None
    _CV2_AVAILABLE = False


# ─── Model lifecycle ──────────────────────────────────────────────────────────

def depth_available() -> bool:
    return _TRANSFORMERS_AVAILABLE


def _get_depth_pipe():
    global _depth_pipe
    if _depth_pipe is not None:
        return _depth_pipe
    if not _TRANSFORMERS_AVAILABLE:
        return None
    try:
        device = -1
        try:
            import torch
            device = 0 if torch.cuda.is_available() else -1
        except ImportError:
            pass
        _depth_pipe = _tf.pipeline(
            "depth-estimation",
            model=_DEPTH_MODEL,
            device=device,
            cache_dir=_CACHE_DIR,
        )
        logger.info("DepthAnything V2 Small loaded (device=%s)", "GPU" if device == 0 else "CPU")
    except Exception as exc:
        logger.warning("DepthAnything failed to load: %s", exc)
        _depth_pipe = None
    return _depth_pipe


def release_depth_model() -> None:
    """Release model from memory. Call when session ends or user resets."""
    global _depth_pipe
    _depth_pipe = None
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    logger.info("DepthAnything released")


# ─── Depth map cache ──────────────────────────────────────────────────────────

def invalidate_depth_cache(path: Optional[str] = None) -> None:
    if path is None:
        _DEPTH_MAP_CACHE.clear()
    else:
        _DEPTH_MAP_CACHE.pop(path, None)


def get_cached_depth(cache_key: str) -> Optional[np.ndarray]:
    return _DEPTH_MAP_CACHE.get(cache_key)


def compute_depth_map(image: Image.Image, cache_key: str) -> Optional[np.ndarray]:
    """Run DepthAnything on image; return normalized float32 [0..1].

    Higher values = foreground (closer to camera).
    Result is cached by cache_key (use image file path).
    """
    if cache_key in _DEPTH_MAP_CACHE:
        return _DEPTH_MAP_CACHE[cache_key]

    pipe = _get_depth_pipe()
    if pipe is None:
        return None

    try:
        result = pipe(image)
        try:
            import torch
            with torch.no_grad():
                arr = result["predicted_depth"].squeeze().cpu().numpy().astype(np.float32)
        except Exception:
            arr = np.array(result["depth"], dtype=np.float32)

        d_min, d_max = float(arr.min()), float(arr.max())
        if d_max > d_min:
            arr = (arr - d_min) / (d_max - d_min)
        else:
            arr = np.zeros_like(arr)

        _DEPTH_MAP_CACHE[cache_key] = arr
        return arr

    except Exception as exc:
        if "out of memory" in str(exc).lower():
            logger.warning("DepthAnything CUDA OOM — retrying on CPU")
            try:
                import torch
                torch.cuda.empty_cache()
                global _depth_pipe
                _depth_pipe = None
                _depth_pipe = _tf.pipeline(
                    "depth-estimation",
                    model=_DEPTH_MODEL,
                    device=-1,
                    cache_dir=_CACHE_DIR,
                )
                return compute_depth_map(image, cache_key)
            except Exception:
                pass
        logger.warning("DepthAnything error: %s", exc)
        return None


def average_depth_score(depth_map: np.ndarray) -> float:
    """Mean normalized depth [0..1]. Higher = image is mostly foreground."""
    return float(depth_map.mean())


# ─── Feature 1: קרופ חכם (Smart Crop) ────────────────────────────────────────

def compute_smart_crop_pan(
    image: Image.Image,
    faces: list,
    depth_map: Optional[np.ndarray],
    pan_x: float = 0.5,
    pan_y: float = 0.5,
) -> Tuple[float, float]:
    """Return improved (pan_x, pan_y) fusing depth center + existing face data.

    Single face:    rule-of-thirds (38% from top), face 60% + depth 40%.
    Multiple faces: confidence-weighted face average, face 60% + depth 40%.
    No faces:       depth center of mass only.
    Falls back to current (pan_x, pan_y) if depth is unavailable.
    """
    if depth_map is None:
        return pan_x, pan_y

    iw, ih = image.size
    dh, dw = depth_map.shape[:2]

    if (dh, dw) != (ih, iw):
        depth_r = np.array(
            Image.fromarray((depth_map * 255).astype(np.uint8)).resize(
                (iw, ih), Image.Resampling.BILINEAR
            )
        ).astype(np.float32) / 255.0
    else:
        depth_r = depth_map

    # Depth center of mass (foreground = depth > 170/255)
    fg = (depth_r > (170 / 255)).astype(np.float32)
    total = float(fg.sum())
    if total > 0:
        ys, xs = np.mgrid[0:ih, 0:iw]
        dcx = float((fg * xs).sum() / total) / iw
        dcy = float((fg * ys).sum() / total) / ih
    else:
        dcx, dcy = 0.5, 0.5

    if not faces:
        return float(np.clip(dcx, 0, 1)), float(np.clip(dcy, 0, 1))

    if len(faces) == 1:
        face = faces[0]
        fcx = float(face.center[0])
        fcy = float(face.center[1])
        # Nudge vertically toward rule-of-thirds (38% from top)
        target_y = fcy * 0.7 + 0.38 * 0.3
        new_x = fcx * 0.6 + dcx * 0.4
        new_y = target_y * 0.6 + dcy * 0.4
    else:
        total_conf = sum(getattr(f, "confidence", 0.75) for f in faces)
        if total_conf > 0:
            fcx = sum(f.center[0] * getattr(f, "confidence", 0.75) for f in faces) / total_conf
            fcy = sum(f.center[1] * getattr(f, "confidence", 0.75) for f in faces) / total_conf
        else:
            fcx = sum(f.center[0] for f in faces) / len(faces)
            fcy = sum(f.center[1] for f in faces) / len(faces)
        new_x = fcx * 0.6 + dcx * 0.4
        new_y = fcy * 0.6 + dcy * 0.4

    return float(np.clip(new_x, 0.0, 1.0)), float(np.clip(new_y, 0.0, 1.0))


# ─── Feature 2: חפיפת עומק (Depth Overlap) ───────────────────────────────────
#
# גישה: שליטה ב-Z-order + הרחבה עדינה דרך מנגנון ה-fade הקיים.
# תאים עם ניקוד עומק גבוה (קדמי) מקבלים z_index גבוה יותר ורנדרינג מורחב
# מעט מעבר לגבולות התא — עם feather מלא על אזור ההרחבה.
# כך התא הקדמי נראה "לפנים" ללא כפילות ו-ghost כלל.


def compute_depth_z_boost(score: float) -> int:
    """Return additional z_index (0–5) for a cell based on its depth score.

    Cells with score > 0.5 (foreground) render on top of background cells.
    """
    if score <= 0.5:
        return 0
    return min(5, int((score - 0.5) * 10))


def compute_depth_expand_px(
    score: float,
    cell_min_dim: int,
    intensity: float = 0.5,
) -> int:
    """Return soft-expansion in pixels (0–3% of cell_min_dim) for foreground cells.

    The expansion is added to fade_padding and rendered with full feathering,
    so it creates a natural edge bleed — not a hard duplicate of the subject.
    Maximum 3% ensures it is subtle and never overwhelming.
    """
    if score <= 0.5:
        return 0
    # Scale: score 0.5→1.0 maps to 0%→3%, then modulated by intensity
    pct = (score - 0.5) * 0.06 * float(np.clip(intensity, 0.0, 1.0))
    return max(0, int(round(cell_min_dim * min(0.03, pct))))


# ─── Feature 3: שכבות עומק (Depth Layers) ────────────────────────────────────

def apply_depth_layers(
    image: Image.Image,
    depth_map: np.ndarray,
    intensity: float = 1.0,
) -> Image.Image:
    """Apply depth-aware visual finishing to a cell image.

    Foreground (score > 0.65): +5% brightness, +8% contrast.
    Midground  (0.35–0.65):    0.8 px Gaussian blur.
    Background (< 0.35):       1.8 px blur, −8% brightness, −10% saturation.

    intensity [0..1] scales all values proportionally.
    """
    score = average_depth_score(depth_map)
    intensity = float(np.clip(intensity, 0.0, 1.0))

    arr = np.asarray(image.convert("RGB"), dtype=np.float32)

    if score > 0.65:
        brightness = 1.0 + 0.05 * intensity
        contrast_boost = 0.08 * intensity
        mean = float(arr.mean())
        arr = (arr - mean) * (1.0 + contrast_boost) + mean
        arr *= brightness

    elif score >= 0.35:
        if _CV2_AVAILABLE and _cv2 is not None and intensity > 0.05:
            sigma = 0.8 * intensity
            arr = _cv2.GaussianBlur(
                np.clip(arr, 0, 255).astype(np.uint8), (0, 0), sigma
            ).astype(np.float32)

    else:
        if _CV2_AVAILABLE and _cv2 is not None and intensity > 0.05:
            sigma = 1.8 * intensity
            arr = _cv2.GaussianBlur(
                np.clip(arr, 0, 255).astype(np.uint8), (0, 0), sigma
            ).astype(np.float32)
        arr *= max(0.1, 1.0 - 0.08 * intensity)
        gray = arr.mean(axis=2, keepdims=True)
        arr = arr * (1.0 - 0.10 * intensity) + gray * (0.10 * intensity)

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
