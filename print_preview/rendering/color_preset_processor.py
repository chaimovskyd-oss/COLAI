"""color_preset_processor — pure, non-destructive image adjustment for Print Color Presets.

Entry point:
    apply_print_color_preset(image: PIL.Image, values: dict) -> PIL.Image

Processing order (per the mandatory pipeline spec):
    raw image  →  [this module]  →  ICC transform  →  display / export

Parameter ranges
────────────────
    brightness, contrast, exposure, saturation, sharpness   int   -100 … +100
    gamma                                                    float  0.2 … 4.0
    r_level, g_level, b_level                               int   -100 … +100
    color_balance_shadows, _midtones, _highlights            int   -100 … +100
      positive = warmer (push R up, B down)
      negative = cooler (push B up, R down)
"""

import logging
from PIL import Image, ImageEnhance

_log = logging.getLogger(__name__)


def apply_print_color_preset(image: Image.Image, values: dict) -> Image.Image:
    """Return a new PIL Image with all preset adjustments applied.

    The original *image* is never modified.  On any failure the original is
    returned unchanged so the caller always gets a displayable result.
    """
    if not values:
        return image
    try:
        return _apply(image, values)
    except Exception as exc:
        _log.error("apply_print_color_preset failed: %s", exc, exc_info=True)
        return image


# ── Main adjustment chain ─────────────────────────────────────────────────────

def _apply(img: Image.Image, v: dict) -> Image.Image:
    # Preserve alpha through the pipeline
    mode = img.mode
    alpha = None
    if mode == "RGBA":
        alpha = img.split()[3]
        img   = img.convert("RGB")
    elif mode not in ("RGB", "L"):
        img   = img.convert("RGB")

    # 1. Exposure — EV-style multiplicative brightness (applied before perceptual ops)
    exposure = _geti(v, "exposure", 0)
    if exposure != 0:
        factor = 2.0 ** (exposure / 100.0)
        img = img.point(lambda x: min(255, max(0, int(x * factor))))

    # 2. Brightness — perceptual lightness scale
    brightness = _geti(v, "brightness", 0)
    if brightness != 0:
        img = ImageEnhance.Brightness(img).enhance(max(0.0, (100 + brightness) / 100.0))

    # 3. Contrast
    contrast = _geti(v, "contrast", 0)
    if contrast != 0:
        img = ImageEnhance.Contrast(img).enhance(max(0.0, (100 + contrast) / 100.0))

    # 4. Saturation
    saturation = _geti(v, "saturation", 0)
    if saturation != 0:
        img = ImageEnhance.Color(img).enhance(max(0.0, (100 + saturation) / 100.0))

    # 5. Sharpness (negative = blur, positive = sharpen, 0 = unchanged)
    sharpness = _geti(v, "sharpness", 0)
    if sharpness != 0:
        img = ImageEnhance.Sharpness(img).enhance(max(0.0, (100 + sharpness) / 100.0))

    # 6. Gamma — applied as power curve (gamma > 1 darkens, < 1 lightens)
    gamma = _getf(v, "gamma", 1.0)
    if abs(gamma - 1.0) > 0.01 and gamma > 0.0:
        inv   = 1.0 / gamma
        table = [min(255, int(((i / 255.0) ** inv) * 255 + 0.5)) for i in range(256)]
        img   = img.point(table * (3 if img.mode == "RGB" else 1))

    # 7. Per-channel RGB level shift (add a fixed offset to each channel)
    r_lv = _geti(v, "r_level", 0)
    g_lv = _geti(v, "g_level", 0)
    b_lv = _geti(v, "b_level", 0)
    if r_lv != 0 or g_lv != 0 or b_lv != 0:
        def _lut(pct: int) -> list:
            shift = int(pct * 255 / 100)
            return [max(0, min(255, i + shift)) for i in range(256)]
        r, g, b = img.split()
        r = r.point(_lut(r_lv))
        g = g.point(_lut(g_lv))
        b = b.point(_lut(b_lv))
        img = Image.merge("RGB", (r, g, b))

    # 8. Color balance — warm/cool tonal shift per luminance zone
    cb_s = _geti(v, "color_balance_shadows",    0)
    cb_m = _geti(v, "color_balance_midtones",   0)
    cb_h = _geti(v, "color_balance_highlights", 0)
    if cb_s != 0 or cb_m != 0 or cb_h != 0:
        img = _apply_color_balance(img, cb_s, cb_m, cb_h)

    # Restore alpha
    if alpha is not None:
        img = img.convert("RGBA")
        img.putalpha(alpha)

    return img


# ── Color balance ─────────────────────────────────────────────────────────────

def _apply_color_balance(img: Image.Image, shadows: int, midtones: int, highlights: int) -> Image.Image:
    """Tonal warm/cool shift split into shadow, midtone, and highlight zones.

    Uses numpy for per-pixel luminance weighting when available; falls back to
    a per-zone LUT approximation when numpy is absent.
    """
    try:
        import numpy as np
        return _color_balance_numpy(img, shadows, midtones, highlights)
    except ImportError:
        return _color_balance_pil(img, shadows, midtones, highlights)


def _color_balance_numpy(img: Image.Image, shadows: int, midtones: int, highlights: int) -> Image.Image:
    import numpy as np

    arr = np.asarray(img, dtype=np.float32)          # H×W×3
    lum = arr.mean(axis=2, keepdims=True)             # H×W×1 (proxy luminance)

    # Zone weights — overlapping soft boundaries for smooth transitions
    w_shadow = np.clip((85.0  - lum) / 85.0,  0.0, 1.0)
    w_high   = np.clip((lum - 170.0) / 85.0,  0.0, 1.0)
    w_mid    = np.clip(1.0 - w_shadow - w_high, 0.0, 1.0)

    MAX_SHIFT = 30.0  # maximum channel shift in pixel units

    def _zone_delta(weight, amount: int):
        if amount == 0:
            return np.zeros_like(arr)
        s = amount / 100.0 * MAX_SHIFT
        d = np.zeros_like(arr)
        d[:, :, 0] =  s          # R: up for warm / down for cool
        d[:, :, 2] = -s          # B: down for warm / up for cool
        return d * weight

    delta  = (_zone_delta(w_shadow, shadows)
              + _zone_delta(w_mid,    midtones)
              + _zone_delta(w_high,   highlights))
    result = np.clip(arr + delta, 0.0, 255.0).astype(np.uint8)
    return Image.fromarray(result, "RGB")


def _color_balance_pil(img: Image.Image, shadows: int, midtones: int, highlights: int) -> Image.Image:
    """Pure-PIL fallback: applies a separate LUT for each tonal zone.

    Each LUT maps the channel value to a warm/cool-shifted value weighted by
    a soft zone mask.  The luminance proxy is the channel value itself, which
    is an approximation but acceptable without numpy.
    """
    MAX_SHIFT = 30

    def _zone_lut(amount: int, zone_lo: int, zone_hi: int) -> tuple[list, list] | None:
        if amount == 0:
            return None
        r_lut, b_lut = [], []
        fade = 40  # ramp width in pixel units
        for i in range(256):
            if i < zone_lo:
                w = max(0.0, 1.0 - (zone_lo - i) / fade)
            elif i > zone_hi:
                w = max(0.0, 1.0 - (i - zone_hi)  / fade)
            else:
                w = 1.0
            shift = int(amount / 100.0 * MAX_SHIFT * w)
            r_lut.append(max(0, min(255, i + shift)))
            b_lut.append(max(0, min(255, i - shift)))
        return r_lut, b_lut

    r, g, b = img.split()
    for amount, lo, hi in [(shadows, 0, 85), (midtones, 85, 170), (highlights, 170, 255)]:
        lut = _zone_lut(amount, lo, hi)
        if lut:
            r = r.point(lut[0])
            b = b.point(lut[1])
    return Image.merge("RGB", (r, g, b))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _geti(d: dict, key: str, default: int) -> int:
    try:
        return int(d.get(key, default))
    except (TypeError, ValueError):
        return default


def _getf(d: dict, key: str, default: float) -> float:
    try:
        return float(d.get(key, default))
    except (TypeError, ValueError):
        return default
