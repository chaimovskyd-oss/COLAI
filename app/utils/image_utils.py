from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPixmap

from app.utils.cell_edge_render import build_soft_fade_mask, normalize_edge_style
from app.utils.color_equalizer_processor import apply_color_equalizer, has_meaningful_adjustment

if TYPE_CHECKING:
    from app.models.project import ImageState, ProjectSettings, TextOverlay

# ---------------------------------------------------------------------------
# Background creation
# ---------------------------------------------------------------------------

def make_background_pil(w: int, h: int, settings) -> 'Image.Image':
    """Create a background PIL image according to settings.background_type.

    Gradient uses numpy for fast vectorised computation (avoids pixel-by-pixel loop).
    """
    bg_type = getattr(settings, 'background_type', 'solid')

    if bg_type == 'gradient':
        c1 = getattr(settings, 'background_gradient', ((255, 255, 255), (200, 200, 200)))[0]
        c2 = getattr(settings, 'background_gradient', ((255, 255, 255), (200, 200, 200)))[1]
        angle = getattr(settings, 'background_gradient_angle', 90.0)
        import math, numpy as np
        rad = math.radians(angle)
        sin_a, cos_a = math.sin(rad), math.cos(rad)
        # Build normalised t [0..1] for each pixel using broadcasting
        xs = np.linspace(0, 1, w, dtype=np.float32)
        ys = np.linspace(0, 1, h, dtype=np.float32)
        t = np.outer(ys * cos_a, np.ones(w)) + np.outer(np.ones(h), xs * sin_a)
        denom = abs(sin_a) + abs(cos_a)
        if denom > 0:
            t = t / denom
        t = np.clip(t, 0.0, 1.0)[:, :, np.newaxis]   # (h, w, 1)
        arr_c1 = np.array(c1, dtype=np.float32)
        arr_c2 = np.array(c2, dtype=np.float32)
        arr = (arr_c1 * (1 - t) + arr_c2 * t).astype(np.uint8)
        return Image.fromarray(arr, 'RGB')

    elif bg_type == 'image':
        bg_path = getattr(settings, 'background_image_path', '')
        if bg_path:
            try:
                bg = Image.open(bg_path).convert('RGB')
                bg = ImageOps.fit(bg, (w, h))
                return bg
            except Exception:
                pass

    return Image.new('RGB', (w, h), settings.background_rgb)


# ---------------------------------------------------------------------------
# Preview image cache  (path → (PIL image, mtime))
# ---------------------------------------------------------------------------

MAX_CACHE_DIM = 1800
_CACHE_MAX = 80
_preview_cache: Dict[str, Tuple[Image.Image, float]] = {}


def _get_cached_preview(path: str) -> Image.Image:
    """Return EXIF-corrected RGB image from cache. Returns a copy."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    if path in _preview_cache:
        img, saved_mtime = _preview_cache[path]
        if saved_mtime == mtime:
            return img.copy()
    if len(_preview_cache) >= _CACHE_MAX:
        del _preview_cache[next(iter(_preview_cache))]
    with Image.open(path) as raw:
        img = ImageOps.exif_transpose(raw).convert('RGB')
        img.thumbnail((MAX_CACHE_DIM, MAX_CACHE_DIM), Image.Resampling.LANCZOS)
        img = img.copy()
    _preview_cache[path] = (img, mtime)
    return img.copy()


def get_preview_image(path: str, rotation: int = 0) -> Image.Image:
    """Cached preview with clockwise rotation applied (0/90/180/270)."""
    img = _get_cached_preview(path)
    if rotation and rotation % 360 != 0:
        img = img.rotate(-rotation, expand=True)  # PIL rotate is CCW → negate for CW
    return img


def invalidate_cache(path: Optional[str] = None) -> None:
    if path is None:
        _preview_cache.clear()
    else:
        _preview_cache.pop(path, None)


# ---------------------------------------------------------------------------
# Qt conversion
# ---------------------------------------------------------------------------

def pil_to_qpixmap(image: Image.Image) -> QPixmap:
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    data = image.tobytes('raw', 'RGBA')
    qimage = QImage(data, image.width, image.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimage.copy())


# ---------------------------------------------------------------------------
# Crop helpers
# ---------------------------------------------------------------------------

def fit_crop_box(
    img_size: Tuple[int, int],
    target_size: Tuple[int, int],
    pan_x: float,
    pan_y: float,
    zoom: float,
    *,
    clamp: bool = True,
) -> Tuple[int, int, int, int]:
    """Compute a (left, top, right, bottom) crop box for *img_size* that fills
    *target_size* at the given *zoom* level, with the image panned to
    (*pan_x*, *pan_y*) in [0, 1] normalised coordinates.

    clamp=True  (default, rectangular cells)
        The box is always fully inside the source image — PIL's .crop() can
        be called directly without any padding.

    clamp=False  (shaped cells)
        The box may extend beyond the source image boundaries so the user can
        position any subject into the visible masked region.  The only hard
        constraint is that at least one source pixel must remain inside the
        box.  Use crop_with_bg() to perform the actual crop in this mode.
    """
    img_w, img_h = img_size
    target_w, target_h = target_size
    target_ratio = target_w / max(1, target_h)
    img_ratio = img_w / max(1, img_h)
    if img_ratio > target_ratio:
        base_w = int(round(img_h * target_ratio))
        base_h = img_h
    else:
        base_w = img_w
        base_h = int(round(img_w / target_ratio))
    zoom = max(1.0, min(zoom, 5.0))
    cw = max(1, int(round(base_w / zoom)))
    ch = max(1, int(round(base_h / zoom)))
    max_x = max(0, img_w - cw)
    max_y = max(0, img_h - ch)
    if clamp:
        left = int(round(max_x * min(max(pan_x, 0.0), 1.0)))
        top  = int(round(max_y * min(max(pan_y, 0.0), 1.0)))
        return left, top, min(img_w, left + cw), min(img_h, top + ch)
    else:
        # Allow box to extend outside source image; guarantee ≥1 px overlap.
        left = int(round(max_x * pan_x))
        top  = int(round(max_y * pan_y))
        left = max(-(cw - 1), min(img_w - 1, left))
        top  = max(-(ch - 1), min(img_h - 1, top))
        return left, top, left + cw, top + ch


def crop_with_bg(
    img: 'Image.Image',
    box: Tuple[int, int, int, int],
    bg_rgb: Tuple[int, int, int],
) -> 'Image.Image':
    """Crop *img* to *box*, padding any out-of-bounds area with *bg_rgb*.

    When the box is fully inside the image this is identical to img.crop(box).
    For shaped collage cells the box may extend outside the source image;
    those areas are filled with the canvas background colour rather than
    PIL's default fill of pure black.
    """
    left, top, right, bottom = box
    if left >= 0 and top >= 0 and right <= img.width and bottom <= img.height:
        return img.crop(box)
    cw = right - left
    ch = bottom - top
    result = Image.new(img.mode, (cw, ch), bg_rgb)
    # Intersection of crop box with image bounds
    x0 = max(0, left);  y0 = max(0, top)
    x1 = min(img.width, right);  y1 = min(img.height, bottom)
    if x0 < x1 and y0 < y1:
        result.paste(img.crop((x0, y0, x1, y1)), (x0 - left, y0 - top))
    return result


def shaped_pan_bounds(
    img_size: Tuple[int, int],
    target_size: Tuple[int, int],
    zoom: float,
) -> Tuple[float, float, float, float]:
    """Return (pan_x_min, pan_x_max, pan_y_min, pan_y_max) for a shaped cell.

    These are the widest pan values that still keep ≥1 source pixel inside the
    crop box.  Use these to clamp pan_x / pan_y in the interactive drag handler
    so values never drift to infinity while still allowing full freedom of
    movement within the source image (and a little beyond).
    """
    img_w, img_h = img_size
    target_w, target_h = target_size
    target_ratio = target_w / max(1, target_h)
    img_ratio = img_w / max(1, img_h)
    if img_ratio > target_ratio:
        base_w = int(round(img_h * target_ratio))
        base_h = img_h
    else:
        base_w = img_w
        base_h = int(round(img_w / target_ratio))
    zoom = max(1.0, min(zoom, 5.0))
    cw = max(1, int(round(base_w / zoom)))
    ch = max(1, int(round(base_h / zoom)))
    max_x = max(0, img_w - cw)
    max_y = max(0, img_h - ch)
    if max_x > 0:
        px_min = -(cw - 1) / max_x
        px_max =  (img_w - 1) / max_x
    else:
        px_min, px_max = 0.0, 1.0
    if max_y > 0:
        py_min = -(ch - 1) / max_y
        py_max =  (img_h - 1) / max_y
    else:
        py_min, py_max = 0.0, 1.0
    return px_min, px_max, py_min, py_max


def smart_pan_from_faces(
    faces: 'List',
    img_size: Tuple[int, int],
    target_size: Tuple[int, int],
    zoom: float = 1.0,
) -> Tuple[float, float]:
    """Compute (pan_x, pan_y) that places important faces inside the crop window.

    Uses group-aware ROI logic (via face_analysis) when available so that
    groups / couples are preserved as a whole rather than centred on a single
    face.  Falls back to simple centroid arithmetic on any error.
    """
    if not faces:
        return 0.5, 0.5
    try:
        from app.core.face_analysis import from_face_regions, smart_crop_pan
        rich = from_face_regions(faces)
        return smart_crop_pan(rich, img_size, target_size, zoom)
    except Exception:
        pass
    # Fallback: original centroid approach
    img_w, img_h = img_size
    target_w, target_h = target_size
    ratio  = target_w / max(1, target_h)
    ir     = img_w / max(1, img_h)
    crop_w = int(round(img_h * ratio)) if ir > ratio else img_w
    crop_h = img_h if ir > ratio else int(round(img_w / ratio))
    max_x  = max(1, img_w - crop_w)
    max_y  = max(1, img_h - crop_h)
    avg_cx = sum(f[0] for f in faces) / len(faces)
    avg_cy = sum(f[1] for f in faces) / len(faces)
    pan_x  = float(min(max((avg_cx * img_w - crop_w / 2.0) / max_x, 0.0), 1.0))
    pan_y  = float(min(max((avg_cy * img_h - crop_h / 2.0) / max_y, 0.0), 1.0))
    return pan_x, pan_y


def evaluate_crop_for_state(
    state: 'ImageState',
    cell_w: int,
    cell_h: int,
) -> 'CropEvaluation':
    """Evaluate current crop quality for a specific cell size.

    Returns a CropEvaluation with tiered warnings.
    Returns an empty CropEvaluation (no warnings) if no face data or on error.
    """
    from app.core.face_analysis import (
        from_face_regions, score_faces, evaluate_crop, CropEvaluation,
    )
    if not state.face_regions:
        return CropEvaluation()
    try:
        img      = get_preview_image(state.path, state.rotation)
        crop_box = fit_crop_box(
            img.size, (cell_w, cell_h), state.pan_x, state.pan_y, state.zoom,
        )
        rich     = from_face_regions(state.face_regions)
        scored   = score_faces(rich)
        return evaluate_crop(scored, crop_box, img.size)
    except Exception:
        return CropEvaluation()


def make_debug_overlay_lines(
    analysis,
    crop_box: Tuple[int, int, int, int],
    img_size: Tuple[int, int],
    target_size: Tuple[int, int],
) -> List[Tuple[str, Tuple[int, int, int, int], Tuple[int, int, int]]]:
    """Map analysis boxes into rendered-cell coordinates for debug drawing."""
    if analysis is None:
        return []
    img_w, img_h = img_size
    crop_l, crop_t, crop_r, crop_b = crop_box
    crop_w = max(1, crop_r - crop_l)
    crop_h = max(1, crop_b - crop_t)
    target_w, target_h = target_size
    lines: List[Tuple[str, Tuple[int, int, int, int], Tuple[int, int, int]]] = []

    def project_box(box, color, label):
        if box is None:
            return
        left = int(round(((box.left * img_w) - crop_l) / crop_w * target_w))
        top = int(round(((box.top * img_h) - crop_t) / crop_h * target_h))
        right = int(round(((box.right * img_w) - crop_l) / crop_w * target_w))
        bottom = int(round(((box.bottom * img_h) - crop_t) / crop_h * target_h))
        lines.append((label, (left, top, right, bottom), color))

    for face in getattr(analysis, 'faces', []):
        project_box(face.bbox, (50, 230, 120), 'face')
    for person in getattr(analysis, 'persons', []):
        project_box(person.bbox, (70, 140, 255), 'person')

    safe = getattr(analysis, 'safe_regions', None)
    if safe:
        project_box(safe.face_safe_region, (255, 210, 0), 'face-safe')
        project_box(safe.person_safe_region, (255, 140, 0), 'person-safe')
        project_box(safe.combined_safe_region, (255, 60, 60), 'combined')
    lines.append(('crop', (0, 0, target_w - 1, target_h - 1), (255, 255, 255)))
    return lines


# ---------------------------------------------------------------------------
# Adjustments
# ---------------------------------------------------------------------------

def _apply_exposure(img: Image.Image, ev: float) -> Image.Image:
    """Apply exposure adjustment in EV stops (positive = brighter)."""
    if ev == 0.0:
        return img
    factor = 2.0 ** ev
    import numpy as np
    arr = np.array(img, dtype=np.float32)
    arr = np.clip(arr * factor, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, img.mode)


def _apply_levels(img: Image.Image,
                  levels_r: Tuple[int, int],
                  levels_g: Tuple[int, int],
                  levels_b: Tuple[int, int]) -> Image.Image:
    """Apply per-channel black/white point levels stretch."""
    if levels_r == (0, 255) and levels_g == (0, 255) and levels_b == (0, 255):
        return img
    import numpy as np
    arr = np.array(img.convert('RGB'), dtype=np.float32)
    for ch, (lo, hi) in enumerate([levels_r, levels_g, levels_b]):
        span = max(hi - lo, 1)
        arr[:, :, ch] = np.clip((arr[:, :, ch] - lo) * 255.0 / span, 0, 255)
    result = Image.fromarray(arr.astype(np.uint8), 'RGB')
    if img.mode == 'RGBA':
        result.putalpha(img.getchannel('A'))
    return result


def _apply_clahe(img: Image.Image, clip: float) -> Image.Image:
    """Apply CLAHE local contrast enhancement (YCbCr L channel)."""
    try:
        import cv2
        import numpy as np
        rgb = np.array(img.convert('RGB'))
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8))
        lab[:, :, 0] = clahe.apply(lab[:, :, 0])
        rgb_out = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
        result = Image.fromarray(rgb_out, 'RGB')
    except ImportError:
        # Numpy fallback: equalise Y channel in YCbCr
        import numpy as np
        ycbcr = img.convert('YCbCr')
        arr = np.array(ycbcr, dtype=np.uint8)
        y = arr[:, :, 0].astype(np.float32)
        # Simple global stretch (no tiling, but avoids cv2 dep)
        lo, hi = np.percentile(y, 1), np.percentile(y, 99)
        span = max(hi - lo, 1)
        y = np.clip((y - lo) * 255.0 / span, 0, 255)
        arr[:, :, 0] = y.astype(np.uint8)
        result = Image.fromarray(arr, 'YCbCr').convert('RGB')
    if img.mode == 'RGBA':
        result.putalpha(img.getchannel('A'))
    return result


def _apply_vignette(img: Image.Image, strength: float) -> Image.Image:
    """Apply a soft radial vignette effect around the image edges."""
    if strength <= 0.0:
        return img
    import numpy as np
    rgb = np.array(img.convert('RGB'), dtype=np.float32) / 255.0
    h, w = rgb.shape[:2]
    xs = np.linspace(-1.0, 1.0, w, dtype=np.float32)[None, :]
    ys = np.linspace(-1.0, 1.0, h, dtype=np.float32)[:, None]
    dist = np.sqrt(xs * xs + ys * ys)
    radius = 0.7
    falloff = np.clip((dist - radius) / (1.0 - radius), 0.0, 1.0)
    mask = 1.0 - strength * (falloff ** 2)
    mask = np.clip(mask, 0.0, 1.0)[..., None]
    out = np.clip(rgb * mask, 0.0, 1.0)
    result = Image.fromarray((out * 255.0).astype(np.uint8), 'RGB')
    if img.mode == 'RGBA':
        result.putalpha(img.getchannel('A'))
    return result


def auto_adjust_levels(img: Image.Image) -> Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]]:
    """Compute per-channel black/white points using 1st/99th percentile.

    Returns (levels_r, levels_g, levels_b) ready to store in ImageState.
    """
    import numpy as np
    arr = np.array(img.convert('RGB'))
    result = []
    for ch in range(3):
        lo = int(np.percentile(arr[:, :, ch], 1))
        hi = int(np.percentile(arr[:, :, ch], 99))
        hi = max(hi, lo + 1)
        result.append((lo, hi))
    return tuple(result)   # type: ignore[return-value]


def apply_adjustments(img: Image.Image, state: 'ImageState') -> Image.Image:
    if state.is_bw:
        img = img.convert('L').convert('RGB')
    if state.brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(state.brightness)
    if state.contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(state.contrast)
    if state.saturation != 1.0 and not state.is_bw:
        img = ImageEnhance.Color(img).enhance(state.saturation)
    if state.sharpness != 1.0:
        img = ImageEnhance.Sharpness(img).enhance(state.sharpness)
    # Advanced adjustments
    if state.exposure_ev != 0.0:
        img = _apply_exposure(img, state.exposure_ev)
    levels_r = getattr(state, 'levels_r', (0, 255))
    levels_g = getattr(state, 'levels_g', (0, 255))
    levels_b = getattr(state, 'levels_b', (0, 255))
    if levels_r != (0, 255) or levels_g != (0, 255) or levels_b != (0, 255):
        img = _apply_levels(img, levels_r, levels_g, levels_b)
    if getattr(state, 'clahe_enabled', False):
        img = _apply_clahe(img, getattr(state, 'clahe_clip', 2.0))
    ce_state = getattr(state, 'color_equalizer', None)
    if not state.is_bw and has_meaningful_adjustment(ce_state):
        img = apply_color_equalizer(img, ce_state)
    vig = getattr(state, 'vignette_strength', 0.0)
    if vig != 0.0:
        img = _apply_vignette(img, vig)
    return img


def has_visible_adjustments(state: 'ImageState') -> bool:
    return any([
        abs(float(getattr(state, 'brightness', 1.0)) - 1.0) > 1e-4,
        abs(float(getattr(state, 'contrast', 1.0)) - 1.0) > 1e-4,
        abs(float(getattr(state, 'saturation', 1.0)) - 1.0) > 1e-4,
        abs(float(getattr(state, 'sharpness', 1.0)) - 1.0) > 1e-4,
        bool(getattr(state, 'is_bw', False)),
        abs(float(getattr(state, 'exposure_ev', 0.0))) > 1e-4,
        tuple(getattr(state, 'levels_r', (0, 255))) != (0, 255),
        tuple(getattr(state, 'levels_g', (0, 255))) != (0, 255),
        tuple(getattr(state, 'levels_b', (0, 255))) != (0, 255),
        bool(getattr(state, 'clahe_enabled', False)),
        abs(float(getattr(state, 'vignette_strength', 0.0))) > 1e-4,
        has_meaningful_adjustment(getattr(state, 'color_equalizer', None)),
    ])


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def render_image_to_size(
    path: str,
    target_size: Tuple[int, int],
    pan_x: float,
    pan_y: float,
    zoom: float,
    state: Optional['ImageState'] = None,
    use_cache: bool = False,
    *,
    clamp: bool = True,
    bg_rgb: Tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """Render *path* cropped and scaled to *target_size*.

    clamp=False / bg_rgb  — used for shaped collage cells.  The crop box may
    extend outside the source image; out-of-bounds areas are filled with
    *bg_rgb* (the canvas background colour).
    """
    rotation = state.rotation if state else 0
    if use_cache:
        img = get_preview_image(path, rotation)
        resample = Image.Resampling.BILINEAR
    else:
        with Image.open(path) as raw:
            img = ImageOps.exif_transpose(raw).convert('RGB')
        if rotation and rotation % 360 != 0:
            img = img.rotate(-rotation, expand=True)
        resample = Image.Resampling.LANCZOS
    crop_box = fit_crop_box(img.size, target_size, pan_x, pan_y, zoom, clamp=clamp)
    if clamp:
        result = img.crop(crop_box).resize(target_size, resample)
    else:
        result = crop_with_bg(img, crop_box, bg_rgb).resize(target_size, resample)
    if state is not None:
        result = apply_adjustments(result, state)
    return result


def render_image_contain_to_size(
    path: str,
    target_size: Tuple[int, int],
    state: Optional['ImageState'] = None,
    use_cache: bool = False,
    *,
    bg_rgb: Tuple[int, int, int] = (255, 255, 255),
    padding_px: int = 0,
    ignore_rotation: bool = False,
) -> Image.Image:
    """Render *path* scaled to fit *target_size* while preserving aspect ratio.

    The image is letterboxed (contain mode): it is scaled so that the entire
    image is visible, centred on a background-coloured canvas.  *padding_px*
    adds extra margin around the image inside the cell.
    """
    rotation = (state.rotation if (state and not ignore_rotation) else 0)
    if use_cache:
        img = get_preview_image(path, rotation)
        resample = Image.Resampling.BILINEAR
    else:
        with Image.open(path) as raw:
            img = ImageOps.exif_transpose(raw).convert('RGB')
        if rotation and rotation % 360 != 0:
            img = img.rotate(-rotation, expand=True)
        resample = Image.Resampling.LANCZOS

    if state is not None and not ignore_rotation:
        img = apply_adjustments(img, state)

    tw, th = target_size
    inner_w = max(1, tw - padding_px * 2)
    inner_h = max(1, th - padding_px * 2)
    iw, ih = img.size
    scale = min(inner_w / max(1, iw), inner_h / max(1, ih))
    new_w = max(1, int(round(iw * scale)))
    new_h = max(1, int(round(ih * scale)))
    resized = img.resize((new_w, new_h), resample)

    canvas = Image.new('RGB', (tw, th), bg_rgb)
    paste_x = (tw - new_w) // 2
    paste_y = (th - new_h) // 2
    canvas.paste(resized, (paste_x, paste_y))
    return canvas


def image_resolution_ok(path: str, cell_px: Tuple[int, int], dpi: int = 300) -> bool:
    try:
        with Image.open(path) as img:
            iw, ih = img.size
        return iw >= cell_px[0] * 0.5 and ih >= cell_px[1] * 0.5
    except Exception:
        return True


def make_thumb_icon_with_badge(path: str, thumb_w: int, thumb_h: int,
                                warn: bool = False,
                                analyzed: bool = False) -> 'QPixmap':
    """Return a thumbnail QPixmap with an optional red ⚠ badge overlay."""
    try:
        with Image.open(path) as raw:
            img = ImageOps.exif_transpose(raw).convert('RGB')
        img.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        pixmap = pil_to_qpixmap(img)
    except Exception:
        pixmap = QPixmap(thumb_w, thumb_h)
        pixmap.fill(QColor(200, 200, 200))

    if analyzed:
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        r = max(5, min(pixmap.width(), pixmap.height()) // 10)
        p.setBrush(QColor(45, 180, 95))
        p.setPen(QColor(255, 255, 255))
        p.drawEllipse(3, 3, r * 2, r * 2)
        p.end()

    if warn:
        from PySide6.QtCore import QRect as _QRect
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        r = min(pixmap.width(), pixmap.height()) // 4
        cx = pixmap.width() - r - 2
        cy = r + 2
        # Red circle
        p.setBrush(QColor(220, 40, 40))
        p.setPen(QColor(255, 255, 255))
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
        # Exclamation mark
        f = QFont('Arial', max(6, r - 2))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        p.drawText(_QRect(cx - r, cy - r, r * 2, r * 2),
                   Qt.AlignCenter, '!')
        p.end()

    return pixmap


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------

def mm_to_px(mm: float, dpi: int) -> int:
    return max(0, int(round(mm / 25.4 * dpi)))


def px_to_mm(px: float, dpi: int) -> float:
    return max(0.0, float(px) * 25.4 / max(1, dpi))


# ---------------------------------------------------------------------------
# Cell style rendering
# ---------------------------------------------------------------------------

def render_styled_cell(
    canvas: Image.Image,
    x: int, y: int, w: int, h: int,
    cell_img: Image.Image,
    corner_radius: int = 0,
    border_width: int = 0,
    border_color: Tuple[int, int, int] = (0, 0, 0),
    shadow_enabled: bool = False,
    shadow_offset: int = 6,
    shadow_blur: int = 8,
    shadow_opacity: int = 100,
    edge_style: str = 'hard',
    fade_padding: Tuple[int, int, int, int] = (0, 0, 0, 0),
    fade_curve: str = 'smooth',
    rotation_deg: float = 0.0,
    mask_seed: int = 0,
) -> Image.Image:
    """Composite a styled cell image onto canvas. Returns the (possibly RGBA) canvas."""
    edge_style = normalize_edge_style(edge_style)
    if edge_style == 'torn_paper' or abs(float(rotation_deg or 0.0)) > 0.01:
        return _render_layered_cell(
            canvas, x, y, w, h, cell_img,
            corner_radius=corner_radius,
            border_width=border_width,
            border_color=border_color,
            shadow_enabled=shadow_enabled or edge_style == 'torn_paper',
            shadow_offset=shadow_offset if shadow_offset > 0 else max(3, min(w, h) // 45),
            shadow_blur=shadow_blur if shadow_blur > 0 else max(4, min(w, h) // 35),
            shadow_opacity=shadow_opacity if shadow_opacity > 0 else 90,
            edge_style=edge_style,
            rotation_deg=float(rotation_deg or 0.0),
            mask_seed=int(mask_seed or 0),
        )

    # 1. Shadow (drawn first, under the image)
    if shadow_enabled and shadow_offset > 0:
        pad = shadow_blur * 2
        sh_w, sh_h = w + pad, h + pad
        shadow_layer = Image.new('RGBA', (sh_w, sh_h), (0, 0, 0, 0))
        if cell_img.mode == 'RGBA':
            alpha = cell_img.split()[3]
            shadow_alpha = Image.new('L', (sh_w, sh_h), 0)
            shadow_alpha.paste(alpha, (shadow_blur, shadow_blur))
            if shadow_opacity < 255:
                shadow_alpha = shadow_alpha.point(
                    lambda v: int(v * max(0, min(255, shadow_opacity)) / 255)
                )
            shadow_layer.putalpha(shadow_alpha)
        else:
            sdraw = ImageDraw.Draw(shadow_layer)
            rect = [shadow_blur, shadow_blur, shadow_blur + w - 1, shadow_blur + h - 1]
            fill = (30, 30, 30, shadow_opacity)
            if corner_radius > 0:
                sdraw.rounded_rectangle(rect, radius=corner_radius, fill=fill)
            else:
                sdraw.rectangle(rect, fill=fill)
        if shadow_blur > 0:
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=max(1, shadow_blur // 2)))
        sx = x + shadow_offset - shadow_blur
        sy = y + shadow_offset - shadow_blur
        # Composite shadow onto canvas (need RGBA for alpha paste)
        if canvas.mode == 'RGB':
            canvas = canvas.convert('RGBA')
        shadow_alpha = shadow_layer.split()[3]
        shadow_rgb = shadow_layer.convert('RGB')
        # Clip paste to canvas bounds
        paste_x, paste_y = sx, sy
        crop_x0 = max(0, -paste_x)
        crop_y0 = max(0, -paste_y)
        crop_x1 = sh_w - max(0, (paste_x + sh_w) - canvas.width)
        crop_y1 = sh_h - max(0, (paste_y + sh_h) - canvas.height)
        if crop_x1 > crop_x0 and crop_y1 > crop_y0:
            shadow_rgb_crop = shadow_rgb.crop((crop_x0, crop_y0, crop_x1, crop_y1))
            shadow_alpha_crop = shadow_alpha.crop((crop_x0, crop_y0, crop_x1, crop_y1))
            canvas.paste(shadow_rgb_crop,
                         (max(0, paste_x), max(0, paste_y)),
                         shadow_alpha_crop)

    # 2. Image body
    if edge_style == 'soft_fade' and any(fade_padding):
        left, top, right, bottom = [max(0, int(v)) for v in fade_padding]
        if canvas.mode == 'RGB':
            canvas = canvas.convert('RGBA')
        cell_rgba = cell_img.convert('RGBA')
        mask = build_soft_fade_mask(w, h, (left, top, right, bottom), fade_curve)
        if cell_rgba.size != mask.size:
            cell_rgba = cell_rgba.resize(mask.size, Image.Resampling.BILINEAR)
        cell_rgba.putalpha(mask)
        canvas.paste(cell_rgba, (x - left, y - top), mask)
    elif corner_radius > 0:
        cell_rgba = cell_img.convert('RGBA')
        mask = Image.new('L', (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=corner_radius, fill=255)
        if canvas.mode == 'RGB':
            canvas = canvas.convert('RGBA')
        cell_rgba.putalpha(mask)
        canvas.paste(cell_rgba, (x, y), mask)
    elif cell_img.mode == 'RGBA':
        if canvas.mode == 'RGB':
            canvas = canvas.convert('RGBA')
        alpha = cell_img.split()[3]
        canvas.paste(cell_img, (x, y), alpha)
    else:
        canvas.paste(cell_img.convert('RGB'), (x, y))

    # 3. Border on top
    if border_width > 0:
        draw = ImageDraw.Draw(canvas)
        if corner_radius > 0:
            draw.rounded_rectangle(
                [x, y, x + w - 1, y + h - 1],
                radius=corner_radius, outline=border_color, width=border_width,
            )
        else:
            draw.rectangle([x, y, x + w - 1, y + h - 1], outline=border_color, width=border_width)

    return canvas


def _torn_paper_mask(w: int, h: int, seed: int = 0) -> Image.Image:
    import random as _random
    rnd = _random.Random(int(seed or 0) + w * 17 + h * 31)
    step = max(8, min(w, h) // 12)
    jitter = max(3, min(w, h) // 28)

    pts = []
    for x in range(0, w + 1, step):
        pts.append((x, rnd.randint(0, jitter)))
    for y in range(step, h + 1, step):
        pts.append((w - 1 - rnd.randint(0, jitter), y))
    for x in range(w - step, -1, -step):
        pts.append((x, h - 1 - rnd.randint(0, jitter)))
    for y in range(h - step, 0, -step):
        pts.append((rnd.randint(0, jitter), y))

    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(radius=0.35))


def _render_layered_cell(
    canvas: Image.Image,
    x: int, y: int, w: int, h: int,
    cell_img: Image.Image,
    corner_radius: int = 0,
    border_width: int = 0,
    border_color: Tuple[int, int, int] = (0, 0, 0),
    shadow_enabled: bool = True,
    shadow_offset: int = 6,
    shadow_blur: int = 8,
    shadow_opacity: int = 100,
    edge_style: str = 'hard',
    rotation_deg: float = 0.0,
    mask_seed: int = 0,
) -> Image.Image:
    pad = max(8, shadow_blur * 3 + abs(shadow_offset) + max(border_width, 0) + 4)
    layer = Image.new('RGBA', (w + pad * 2, h + pad * 2), (0, 0, 0, 0))

    if edge_style == 'torn_paper':
        mask = _torn_paper_mask(w, h, mask_seed)
    elif corner_radius > 0:
        mask = Image.new('L', (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=corner_radius, fill=255)
    else:
        mask = Image.new('L', (w, h), 255)

    if shadow_enabled:
        shadow = Image.new('RGBA', (w, h), (20, 20, 20, max(0, min(255, int(shadow_opacity)))))
        shadow.putalpha(mask)
        if shadow_blur > 0:
            shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(1, shadow_blur // 2)))
        layer.alpha_composite(shadow, (pad + shadow_offset, pad + shadow_offset))

    cell_rgba = cell_img.convert('RGBA')
    if cell_rgba.size != (w, h):
        cell_rgba = cell_rgba.resize((w, h), Image.Resampling.BILINEAR)
    cell_rgba.putalpha(mask)
    layer.alpha_composite(cell_rgba, (pad, pad))

    if border_width > 0 and edge_style != 'torn_paper':
        draw = ImageDraw.Draw(layer)
        rect = [pad, pad, pad + w - 1, pad + h - 1]
        if corner_radius > 0:
            draw.rounded_rectangle(rect, radius=corner_radius, outline=border_color, width=border_width)
        else:
            draw.rectangle(rect, outline=border_color, width=border_width)

    if abs(rotation_deg) > 0.01:
        layer = layer.rotate(-rotation_deg, expand=True, resample=Image.Resampling.BICUBIC)

    if canvas.mode == 'RGB':
        canvas = canvas.convert('RGBA')
    center_x = x + w / 2.0
    center_y = y + h / 2.0
    paste_x = int(round(center_x - layer.width / 2.0))
    paste_y = int(round(center_y - layer.height / 2.0))
    crop_x0 = max(0, -paste_x)
    crop_y0 = max(0, -paste_y)
    crop_x1 = layer.width - max(0, paste_x + layer.width - canvas.width)
    crop_y1 = layer.height - max(0, paste_y + layer.height - canvas.height)
    if crop_x1 > crop_x0 and crop_y1 > crop_y0:
        cropped = layer.crop((crop_x0, crop_y0, crop_x1, crop_y1))
        canvas.alpha_composite(cropped, (max(0, paste_x), max(0, paste_y)))
    return canvas


# ---------------------------------------------------------------------------
# Text overlay
# ---------------------------------------------------------------------------

_FONT_SEARCH_PATHS = [
    'C:/Windows/Fonts/arial.ttf',
    'C:/Windows/Fonts/calibri.ttf',
    'C:/Windows/Fonts/segoeui.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    '/System/Library/Fonts/Helvetica.ttc',
]


def _get_font(size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_SEARCH_PATHS:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=max(8, size_px))
            except Exception:
                pass
    return ImageFont.load_default()


def draw_text_overlay(
    canvas: Image.Image,
    overlay: 'TextOverlay',
    dpi: int,
) -> Image.Image:
    if not overlay.text.strip():
        return canvas
    font_size_px = mm_to_px(overlay.font_size_pt * 25.4 / 72, dpi)
    font = _get_font(font_size_px)
    draw = ImageDraw.Draw(canvas)
    # Measure text
    bbox = draw.textbbox((0, 0), overlay.text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    padding_px = mm_to_px(overlay.padding_mm, dpi)
    # Horizontal position
    if overlay.h_align == 'center':
        tx = (canvas.width - text_w) // 2
    elif overlay.h_align == 'right':
        tx = canvas.width - text_w - padding_px
    else:
        tx = padding_px
    # Vertical position
    if overlay.position == 'top':
        ty = padding_px
    elif overlay.position == 'bottom':
        ty = canvas.height - text_h - padding_px
    else:
        ty = (canvas.height - text_h) // 2
    # Optional background box
    if overlay.background_rgb is not None:
        draw.rectangle(
            [tx - 4, ty - 4, tx + text_w + 4, ty + text_h + 4],
            fill=overlay.background_rgb,
        )
    draw.text((tx, ty), overlay.text, fill=overlay.color_rgb, font=font)
    return canvas


# ---------------------------------------------------------------------------
# Qt-based text overlay (shared between canvas preview & high-res export)
# ---------------------------------------------------------------------------

def qpixmap_to_pil(pixmap: QPixmap) -> Image.Image:
    """Convert QPixmap → PIL Image (RGB)."""
    qimage = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
    width, height = qimage.width(), qimage.height()
    ptr = qimage.bits()
    import numpy as np  # already a project dependency
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((height, width, 4)).copy()
    return Image.fromarray(arr, 'RGBA').convert('RGB')


def render_text_overlay_qt(
    pixmap: QPixmap,
    overlay: 'TextOverlay',
    dpi: int,
    scale: float = 1.0,
) -> Tuple[QPixmap, Optional[Tuple[int, int, int, int]]]:
    """
    Render text overlay onto *pixmap* using Qt.
    Handles: RTL/Hebrew, system fonts, bold/italic, stroke, shadow, bg opacity.
    Returns (updated_pixmap, (x, y, w, h) bounding rect or None).
    """
    if not overlay.text.strip():
        return pixmap, None

    font_size_px = max(4, int(overlay.font_size_pt / 72.0 * dpi * scale))
    font = QFont(overlay.font_family)
    font.setPixelSize(font_size_px)
    font.setBold(getattr(overlay, 'font_bold', False))
    font.setItalic(getattr(overlay, 'font_italic', False))

    pw, ph = pixmap.width(), pixmap.height()
    fm = QFontMetrics(font)

    lines = overlay.text.split('\n')
    line_h = fm.height()
    text_w = max((fm.horizontalAdvance(ln) for ln in lines), default=10) + 24
    text_h = line_h * len(lines) + 10
    padding_px = max(4, int(getattr(overlay, 'padding_mm', 5.0) / 25.4 * dpi * scale))

    if overlay.pos_x_frac >= 0.0 and overlay.pos_y_frac >= 0.0:
        tx = int(overlay.pos_x_frac * pw) - text_w // 2
        ty = int(overlay.pos_y_frac * ph) - text_h // 2
    else:
        h_align = getattr(overlay, 'h_align', 'center')
        position = getattr(overlay, 'position', 'bottom')
        if h_align == 'right':
            tx = pw - text_w - padding_px
        elif h_align == 'center':
            tx = (pw - text_w) // 2
        else:
            tx = padding_px
        if position == 'bottom':
            ty = ph - text_h - padding_px
        elif position == 'top':
            ty = padding_px
        else:
            ty = (ph - text_h) // 2

    tx = max(0, min(tx, pw - text_w))
    ty = max(0, min(ty, ph - text_h))
    text_rect = QRect(tx, ty, text_w, text_h)

    # RTL detection and alignment
    has_rtl = any('\u0590' <= c <= '\u05FF' for c in overlay.text)
    h_align_str = getattr(overlay, 'h_align', 'center')
    if has_rtl or h_align_str == 'right':
        align_flag = Qt.AlignRight
    elif h_align_str == 'left':
        align_flag = Qt.AlignLeft
    else:
        align_flag = Qt.AlignHCenter
    draw_flags = int(Qt.AlignVCenter | align_flag | Qt.TextWordWrap)

    painter = QPainter(pixmap)
    painter.setFont(font)
    painter.setRenderHint(QPainter.TextAntialiasing, True)

    # Background box with opacity
    if overlay.background_rgb is not None:
        bg_color = QColor(*overlay.background_rgb)
        bg_opacity = getattr(overlay, 'background_opacity', 100)
        bg_color.setAlpha(int(bg_opacity * 255 / 100))
        painter.fillRect(QRect(tx - 4, ty - 2, text_w + 8, text_h + 4), bg_color)

    # Drop shadow
    if getattr(overlay, 'text_shadow', False):
        shadow_off = getattr(overlay, 'text_shadow_offset_px', 3)
        shadow_col = getattr(overlay, 'text_shadow_color_rgb', (80, 80, 80))
        shadow_color = QColor(*shadow_col)
        shadow_color.setAlpha(180)
        painter.setPen(shadow_color)
        painter.drawText(text_rect.translated(shadow_off, shadow_off), draw_flags, overlay.text)

    # Stroke (outline) – capped at 5 px for performance
    stroke_w = min(getattr(overlay, 'stroke_width_px', 0), 5)
    if stroke_w > 0:
        stroke_rgb = getattr(overlay, 'stroke_color_rgb', (0, 0, 0))
        painter.setPen(QColor(*stroke_rgb))
        sw2 = stroke_w * stroke_w
        for dx in range(-stroke_w, stroke_w + 1):
            for dy in range(-stroke_w, stroke_w + 1):
                if dx * dx + dy * dy <= sw2:
                    painter.drawText(text_rect.translated(dx, dy), draw_flags, overlay.text)

    # Main text
    painter.setPen(QColor(*overlay.color_rgb))
    painter.drawText(text_rect, draw_flags, overlay.text)
    painter.end()

    return pixmap, (tx, ty, text_w, text_h)


# ---------------------------------------------------------------------------
# Element overlay rendering
# ---------------------------------------------------------------------------

def render_element_qt(pixmap: 'QPixmap', element, canvas_w_px: int, canvas_h_px: int, scale: float):
    """
    Render an ElementOverlay onto a QPixmap. Returns (new_pixmap, bounding_rect_tuple_or_None).
    bounding_rect_tuple = (x, y, w, h) in pixmap coordinates (before rotation - axis-aligned bbox).
    """
    import math

    path = element.path
    if not path:
        return pixmap, None

    # Element size in canvas pixels, then scaled to preview pixmap
    el_w_canvas = element.width_frac * canvas_w_px
    # Load element to get aspect ratio
    suffix = path.rsplit('.', 1)[-1].lower() if '.' in path else ''
    el_pix = QPixmap()
    if suffix == 'svg':
        try:
            from PySide6.QtSvg import QSvgRenderer
            from PySide6.QtCore import QSize
            renderer = QSvgRenderer(path)
            d = renderer.defaultSize()
            aspect = d.height() / max(1, d.width())
            el_w_px = max(4, int(el_w_canvas * scale))
            el_h_px = max(4, int(el_w_px * aspect))
            el_pix = QPixmap(el_w_px, el_h_px)
            el_pix.fill(Qt.transparent)
            p2 = QPainter(el_pix)
            renderer.render(p2)
            p2.end()
        except Exception:
            return pixmap, None
    else:
        raw = QPixmap(path)
        if raw.isNull():
            return pixmap, None
        el_w_px = max(4, int(el_w_canvas * scale))
        el_h_px = max(4, int(el_w_px * raw.height() / max(1, raw.width())))
        el_pix = raw.scaled(el_w_px, el_h_px, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    # Position (center) in pixmap coordinates
    cx = int(element.pos_x_frac * pixmap.width())
    cy = int(element.pos_y_frac * pixmap.height())

    # Draw onto canvas with rotation and opacity
    result = QPixmap(pixmap.size())
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.drawPixmap(0, 0, pixmap)

    painter.setOpacity(max(0.0, min(1.0, element.opacity)))
    painter.translate(cx, cy)
    painter.rotate(element.rotation_deg)
    painter.drawPixmap(-el_pix.width() // 2, -el_pix.height() // 2, el_pix)
    painter.end()

    # Axis-aligned bounding rect in pixmap coords (approximate, ignoring rotation)
    bx = cx - el_pix.width() // 2
    by = cy - el_pix.height() // 2
    return result, (bx, by, el_pix.width(), el_pix.height())


# ---------------------------------------------------------------------------
# Shape mask compositing
# ---------------------------------------------------------------------------

def apply_shape_mask(
    canvas: 'Image.Image',
    shape: str,
    settings: 'ProjectSettings',
    scale: float = 1.0,
) -> 'Image.Image':
    """Composite canvas with shape mask — pixels outside shape become background colour."""
    if not shape:
        return canvas
    from app.core.shape_layouts import get_shape_mask
    w, h = canvas.size
    margin = max(int(settings.margin_px * scale), int(min(w, h) * 0.04))
    mask = get_shape_mask(shape, w, h, margin)
    bg = Image.new('RGB', (w, h), settings.background_rgb)
    if canvas.mode == 'RGBA':
        bg = bg.convert('RGBA')
        bg.paste(canvas, mask=mask)
        return bg
    bg.paste(canvas, mask=mask)
    return bg


# ---------------------------------------------------------------------------
# Per-cell shape masking (for template-defined slot shapes)
# ---------------------------------------------------------------------------

def make_cell_shape_mask(
    w: int, h: int,
    shape_type: str,
    shape_params: dict,
) -> 'Image.Image':
    """Return an L-mode PIL mask (white = visible, black = clipped) for the given shape.

    Supported shape_types: 'rectangle', 'rounded', 'circle', 'ellipse', 'polygon', 'heart',
    'ring_segment'.
    For 'rectangle' the mask is fully white (no clipping).
    """
    import math as _math
    mask = Image.new('L', (w, h), 0)
    draw = ImageDraw.Draw(mask)

    if shape_type == 'rectangle':
        draw.rectangle([0, 0, w - 1, h - 1], fill=255)

    elif shape_type == 'rounded':
        r = shape_params.get('corner_radius', 0.15)
        radius = max(1, int(r * min(w, h)))
        draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)

    elif shape_type in ('circle', 'ellipse'):
        # For circle, inscribe in the shorter dimension and centre it
        if shape_type == 'circle':
            d = min(w, h)
            x0, y0 = (w - d) // 2, (h - d) // 2
            x1, y1 = x0 + d - 1, y0 + d - 1
        else:
            x0, y0, x1, y1 = 0, 0, w - 1, h - 1
        draw.ellipse([x0, y0, x1, y1], fill=255)

    elif shape_type == 'polygon':
        sides = max(3, int(shape_params.get('sides', 6)))
        rot_deg = shape_params.get('rotation', 0.0)
        rot_rad = rot_deg * _math.pi / 180.0 - _math.pi / 2  # start at top
        cx, cy = w / 2.0, h / 2.0
        rx, ry = w / 2.0 - 1, h / 2.0 - 1
        pts = [
            (cx + rx * _math.cos(2 * _math.pi * i / sides + rot_rad),
             cy + ry * _math.sin(2 * _math.pi * i / sides + rot_rad))
            for i in range(sides)
        ]
        draw.polygon(pts, fill=255)

    elif shape_type == 'ring_segment':
        start = float(shape_params.get('start_angle', 0.0))
        end = float(shape_params.get('end_angle', 360.0))
        gap = max(0.0, float(shape_params.get('gap_angle', 0.0)))
        start += gap / 2.0
        end = max(start, end - gap / 2.0)
        cx = float(shape_params.get('center_x', w / 2.0))
        cy = float(shape_params.get('center_y', h / 2.0))
        outer_r = max(1.0, float(shape_params.get('outer_radius', min(w, h) / 2.0)))
        inner_r = max(0.0, float(shape_params.get('inner_radius', outer_r * 0.45)))
        draw.pieslice(
            [cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r],
            start=start,
            end=end,
            fill=255,
        )
        draw.ellipse(
            [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
            fill=0,
        )

    elif shape_type == 'heart':
        try:
            import numpy as _np
            n = 300
            t = _np.linspace(0, 2 * _math.pi, n)
            hx = 16 * _np.sin(t) ** 3
            hy = -(13 * _np.cos(t) - 5 * _np.cos(2 * t) - 2 * _np.cos(3 * t) - _np.cos(4 * t))
            hx = (hx - hx.min()) / max(1e-9, hx.max() - hx.min()) * (w - 2) + 1
            hy = (hy - hy.min()) / max(1e-9, hy.max() - hy.min()) * (h - 2) + 1
            pts = list(zip(hx.tolist(), hy.tolist()))
            draw.polygon(pts, fill=255)
        except ImportError:
            # numpy unavailable — fallback to ellipse
            draw.ellipse([0, 0, w - 1, h - 1], fill=255)

    elif shape_type == 'diagonal_polygon':
        # Vertices stored as v0x,v0y … vNx,vNy in [0..1] relative to cell bbox.
        n_verts = int(shape_params.get('v_count', 4))
        pts = [
            (shape_params.get(f'v{i}x', 0.0) * (w - 1),
             shape_params.get(f'v{i}y', 0.0) * (h - 1))
            for i in range(n_verts)
        ]
        if len(pts) >= 3:
            draw.polygon(pts, fill=255)
        else:
            draw.rectangle([0, 0, w - 1, h - 1], fill=255)

    else:
        # Unknown shape — treat as rectangle
        draw.rectangle([0, 0, w - 1, h - 1], fill=255)

    return mask


def apply_cell_shape(
    cell_img: 'Image.Image',
    shape_type: str,
    shape_params: dict,
    bg_rgb: 'Tuple[int, int, int]',
) -> 'Image.Image':
    """Clip *cell_img* to *shape_type*, filling pixels outside with *bg_rgb*.

    Returns an RGB image of the same size.  Call BEFORE render_styled_cell so
    that the global corner_radius can be set to 0 for shaped cells.
    """
    if not shape_type or shape_type == 'rectangle':
        return cell_img

    w, h = cell_img.size
    mask = make_cell_shape_mask(w, h, shape_type, shape_params)

    if shape_type in ('ring_segment', 'diagonal_polygon'):
        # Return RGBA so transparent (masked-out) areas don't overwrite
        # adjacent cells when composited onto the canvas.
        src = cell_img.convert('RGBA')
        src.putalpha(mask)
        return src

    # Composite: start with solid background, paste image through mask
    bg = Image.new('RGB', (w, h), bg_rgb)
    src = cell_img.convert('RGB')
    bg.paste(src, (0, 0), mask)
    return bg


# ---------------------------------------------------------------------------
# Face near edge detection
# ---------------------------------------------------------------------------

def face_near_cell_edge(
    state: 'ImageState',
    cell_w: int,
    cell_h: int,
    edge_fraction: float = 0.12,
) -> bool:
    """True when any detected face centre lands within edge_fraction of the crop boundary."""
    if not state.face_regions:
        return False
    try:
        img = get_preview_image(state.path, state.rotation)
        left, top, right, bottom = fit_crop_box(img.size, (cell_w, cell_h), state.pan_x, state.pan_y, state.zoom)
        cw, ch = right - left, bottom - top
        for cx, cy, fw, fh in state.face_regions:
            fpx = cx * img.width
            fpy = cy * img.height
            if left <= fpx <= right and top <= fpy <= bottom:
                ix = fpx - left
                iy = fpy - top
                if ix < cw * edge_fraction or ix > cw * (1 - edge_fraction):
                    return True
                if iy < ch * edge_fraction or iy > ch * (1 - edge_fraction):
                    return True
    except Exception:
        pass
    return False
