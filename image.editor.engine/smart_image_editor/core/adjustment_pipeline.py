from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from smart_image_editor.ai.background_blur_service import apply_background_blur, enhance_subject
from smart_image_editor.ai.face_enhancement_service import brighten_faces, protect_skin_tones
from smart_image_editor.ai.face_restore_service import restore_faces
from smart_image_editor.ai.upscaler_service import upscale_image
from smart_image_editor.ai_tools.ai_tools_service import apply_ai_tools_effect
from smart_image_editor.core.dynamic_hsl import apply_dynamic_hsl
from smart_image_editor.core.lut import apply_cube_lut
from smart_image_editor.core.target_color import apply_target_color_adjustment

# Legacy hard-range HSL — disabled; use Dynamic HSL soft zones instead.
# Set to True only for debugging/comparison purposes.
ENABLE_LEGACY_HSL = True

HSL_RANGES = {
    "red": ((345, 360), (0, 15)),
    "orange": ((16, 45),),
    "yellow": ((46, 70),),
    "green": ((71, 165),),
    "aqua": ((166, 195),),
    "blue": ((196, 255),),
    "purple": ((256, 285),),
    "magenta": ((286, 344),),
}


def load_image(path: str) -> Image.Image:
    suffix = path.lower().rsplit(".", 1)[-1]
    if suffix in {"heic", "heif"}:
        try:
            from pillow_heif import register_heif_opener

            register_heif_opener()
        except Exception:
            pass
    if suffix in {"cr2", "cr3", "nef", "arw", "dng", "orf", "raf", "rw2"}:
        try:
            import rawpy

            with rawpy.imread(path) as raw:
                rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False, output_bps=8)
            return Image.fromarray(rgb).convert("RGB")
        except Exception:
            pass
    image = Image.open(path)
    image = ImageOps.exif_transpose(image)
    return image.convert("RGB")


def apply_adjustments(image: Image.Image, params: dict) -> Image.Image:
    """Basic non-destructive adjustment pipeline.

    This is intentionally conservative. Replace/upgrade each step over time
    using the spec's safe ranges and Darktable-inspired behavior where useful.
    """
    out = _apply_geometry(image.copy(), params)

    exposure = float(params.get("exposure", 0.0))
    if exposure:
        out = _exposure(out, exposure)

    brightness = int(params.get("brightness", 0))
    if brightness:
        out = _brightness_midtones(out, brightness)

    contrast = int(params.get("contrast", 0))
    if contrast:
        out = _contrast_curve(out, contrast)

    highlights = int(params.get("highlights", 0))
    shadows = int(params.get("shadows", 0))
    whites = int(params.get("whites", 0))
    blacks = int(params.get("blacks", 0))
    if highlights or shadows or whites or blacks:
        out = _apply_tone_ranges(out, highlights, shadows, whites, blacks)

    gamma = int(params.get("gamma", 0))
    if gamma:
        out = _gamma(out, gamma)

    saturation = int(params.get("saturation", 0))
    vibrance = int(params.get("vibrance", 0))
    if vibrance:
        out = _vibrance(out, vibrance)
    if saturation:
        out = ImageEnhance.Color(out).enhance(max(0, 1 + saturation / 100.0))

    temperature = int(params.get("temperature", 0))
    tint = int(params.get("tint", 0))
    if temperature or tint:
        out = _apply_white_balance_shift(out, temperature, tint)

    hsl = params.get("hsl") or {}
    if hsl and ENABLE_LEGACY_HSL:
        out = _apply_hsl(out, hsl)

    dynamic_hsl = params.get("dynamic_hsl") or {}
    if dynamic_hsl:
        out = apply_dynamic_hsl(out, dynamic_hsl)

    target_color = params.get("target_color") or {}
    if target_color:
        out = apply_target_color_adjustment(out, target_color)

    lut_path = params.get("lut_path")
    lut_amount = int(params.get("lut_amount", 0))
    if lut_path and lut_amount:
        out = apply_cube_lut(out, str(lut_path), lut_amount)

    if params.get("black_white"):
        out = ImageOps.grayscale(out).convert("RGB")

    clarity = int(params.get("clarity", 0))
    texture = int(params.get("texture", 0))
    if clarity or texture:
        out = _local_contrast(out, clarity, texture)

    noise = int(params.get("noise_reduction", 0))
    color_noise = int(params.get("color_noise_reduction", 0))
    if noise or color_noise:
        out = _denoise(out, noise, color_noise)

    skin_protect = int(params.get("ai_skin_tone_protection", 0))
    if skin_protect:
        out = protect_skin_tones(out, skin_protect)

    face_brighten = int(params.get("ai_face_brighten", 0))
    if face_brighten:
        out = brighten_faces(out, face_brighten)

    face_restore = int(params.get("ai_face_restore", 0))
    if face_restore:
        out = restore_faces(out, face_restore)

    subject_enhance = int(params.get("ai_subject_enhance", 0))
    if subject_enhance:
        out = enhance_subject(out, subject_enhance)

    ai_background_blur = int(params.get("ai_background_blur", 0))
    ai_background_darkening = int(params.get("ai_background_darkening", 0))
    if ai_background_blur or ai_background_darkening:
        out = apply_background_blur(out, ai_background_blur, ai_background_darkening)

    blur = int(params.get("gaussian_blur", 0))
    if blur > 0:
        out = out.filter(ImageFilter.GaussianBlur(radius=blur / 3.0))

    motion_blur = int(params.get("motion_blur", 0))
    if motion_blur > 0:
        out = _motion_blur(out, motion_blur, int(params.get("motion_angle", 0)))

    radial_blur = int(params.get("radial_blur", 0))
    if radial_blur > 0:
        out = _radial_blur(out, radial_blur)

    vignette_amount = int(params.get("vignette_amount", 0))
    if vignette_amount:
        out = _apply_vignette(
            out,
            vignette_amount,
            int(params.get("vignette_feather", 65)),
            int(params.get("vignette_midpoint", 50)),
            int(params.get("vignette_roundness", 0)),
        )

    grain = int(params.get("grain_amount", 0))
    if grain > 0:
        out = _grain(out, grain, int(params.get("grain_size", 18)))

    out = _apply_print_correction(out, params)

    sharpness = int(params.get("sharpness", 0)) + int(params.get("print_safe_sharpness", 0))
    if sharpness:
        out = _unsharp(out, sharpness, float(params.get("sharpen_radius", 1.0)))

    # AI Tools artistic/style effects — applied last so they process the fully
    # adjusted image.  Upscale runs after so the stylised result benefits from it.
    ai_tools = params.get("ai_tools") or {}
    if ai_tools.get("active_effect"):
        try:
            out = apply_ai_tools_effect(out, ai_tools)
        except RuntimeError:
            pass  # model unavailable — skip silently; UI surfaces the message

    upscale_factor = int(params.get("ai_upscale_factor", 0))
    upscale_strength = int(params.get("ai_upscale_strength", 100))
    if upscale_factor > 1:
        out = upscale_image(out, upscale_factor, upscale_strength)

    return out


def create_preview(image: Image.Image, max_size: int = 1400) -> Image.Image:
    preview = image.copy()
    preview.thumbnail((max_size, max_size), Image.LANCZOS)
    return preview


def _apply_geometry(image: Image.Image, params: dict) -> Image.Image:
    crop = params.get("crop")
    if crop:
        image = image.crop(tuple(crop))
    rotation = int(params.get("rotation", 0)) % 360
    if rotation:
        image = image.rotate(-rotation, expand=True, resample=Image.Resampling.BICUBIC)
    straighten = float(params.get("straighten", 0.0))
    if straighten:
        image = image.rotate(straighten, expand=True, resample=Image.Resampling.BICUBIC)
    if params.get("flip_horizontal"):
        image = ImageOps.mirror(image)
    if params.get("flip_vertical"):
        image = ImageOps.flip(image)
    return image


def _to_float(image: Image.Image) -> np.ndarray:
    return np.asarray(image).astype(np.float32) / 255.0


def _from_float(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(arr * 255, 0, 255).astype(np.uint8))


def _exposure(image: Image.Image, exposure: float) -> Image.Image:
    arr = _to_float(image)
    return _from_float(arr * (2.0 ** exposure))


def _brightness_midtones(image: Image.Image, brightness: int) -> Image.Image:
    arr = _to_float(image)
    lum = arr.mean(axis=2, keepdims=True)
    midtone_mask = np.clip(1 - np.abs(lum - 0.5) * 2, 0, 1)
    arr += midtone_mask * (brightness / 140.0)
    return _from_float(arr)


def _contrast_curve(image: Image.Image, contrast: int) -> Image.Image:
    arr = _to_float(image)
    strength = contrast / 100.0
    curved = 3 * arr**2 - 2 * arr**3
    if strength >= 0:
        arr = arr * (1 - strength) + curved * strength
    else:
        arr = arr * (1 + strength) + 0.5 * (-strength)
    return _from_float(arr)


def _apply_tone_ranges(image: Image.Image, highlights: int, shadows: int, whites: int, blacks: int) -> Image.Image:
    arr = _to_float(image)
    lum = arr.mean(axis=2, keepdims=True)
    shadow_mask = np.clip(1 - lum * 2.2, 0, 1) ** 1.4
    highlight_mask = np.clip((lum - 0.45) * 2.1, 0, 1) ** 1.4
    white_mask = np.clip((lum - 0.75) * 4.0, 0, 1)
    black_mask = np.clip((0.25 - lum) * 4.0, 0, 1)
    arr += shadow_mask * (shadows / 170.0)
    arr += highlight_mask * (highlights / 230.0)
    arr += white_mask * (whites / 180.0)
    arr += black_mask * (blacks / 180.0)
    return _from_float(arr)


def _gamma(image: Image.Image, gamma: int) -> Image.Image:
    arr = _to_float(image)
    exponent = np.clip(1.0 - gamma / 160.0, 0.25, 3.0)
    return _from_float(np.power(arr, exponent))


def _apply_white_balance_shift(image: Image.Image, temperature: int, tint: int) -> Image.Image:
    arr = _to_float(image)
    arr[:, :, 0] *= 1 + temperature / 300.0
    arr[:, :, 2] *= 1 - temperature / 300.0
    arr[:, :, 0] *= 1 + tint / 420.0
    arr[:, :, 1] *= 1 - tint / 420.0
    return _from_float(arr)


def _vibrance(image: Image.Image, vibrance: int) -> Image.Image:
    arr = _to_float(image)
    maxc = arr.max(axis=2, keepdims=True)
    minc = arr.min(axis=2, keepdims=True)
    sat = maxc - minc
    boost = (1 - sat) * (vibrance / 100.0)
    gray = arr.mean(axis=2, keepdims=True)
    return _from_float(gray + (arr - gray) * (1 + boost))


def _apply_hsl(image: Image.Image, hsl_params: dict) -> Image.Image:
    arr = np.asarray(image.convert("RGB"))
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV).astype(np.float32)
    hue_deg = hsv[:, :, 0] * 2.0
    for name, ranges in HSL_RANGES.items():
        values = hsl_params.get(name) or {}
        if not values:
            continue
        mask = np.zeros(hue_deg.shape, dtype=bool)
        for low, high in ranges:
            mask |= (hue_deg >= low) & (hue_deg <= high)
        hsv[:, :, 0][mask] = (hsv[:, :, 0][mask] + float(values.get("hue", 0)) * 0.9) % 180
        hsv[:, :, 1][mask] *= 1 + float(values.get("saturation", 0)) / 100.0
        hsv[:, :, 2][mask] *= 1 + float(values.get("luminance", 0)) / 100.0
    out = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2RGB)
    return Image.fromarray(out)


def _local_contrast(image: Image.Image, clarity: int, texture: int) -> Image.Image:
    arr = np.asarray(image).astype(np.float32)
    blur_radius = 7 if texture else 17
    blurred = cv2.GaussianBlur(arr, (0, 0), blur_radius)
    amount = clarity / 120.0 + texture / 180.0
    return Image.fromarray(np.clip(arr + (arr - blurred) * amount, 0, 255).astype(np.uint8))


def _denoise(image: Image.Image, luminance: int, color: int) -> Image.Image:
    arr = np.asarray(image)
    h = max(1, luminance // 3)
    h_color = max(1, color // 3)
    out = cv2.fastNlMeansDenoisingColored(arr, None, h, h_color, 7, 21)
    return Image.fromarray(out)


def _motion_blur(image: Image.Image, strength: int, angle: int) -> Image.Image:
    arr = np.asarray(image)
    size = max(3, int(strength / 4) * 2 + 1)
    kernel = np.zeros((size, size), dtype=np.float32)
    kernel[size // 2, :] = 1.0 / size
    matrix = cv2.getRotationMatrix2D((size / 2 - 0.5, size / 2 - 0.5), angle, 1)
    kernel = cv2.warpAffine(kernel, matrix, (size, size))
    out = cv2.filter2D(arr, -1, kernel)
    return Image.fromarray(out)


def _radial_blur(image: Image.Image, strength: int) -> Image.Image:
    arr = _to_float(image)
    blurred = np.asarray(image.filter(ImageFilter.GaussianBlur(radius=max(1, strength / 8)))).astype(np.float32) / 255.0
    h, w = arr.shape[:2]
    y, x = np.ogrid[:h, :w]
    dist = np.sqrt((x - w / 2) ** 2 + (y - h / 2) ** 2) / np.sqrt((w / 2) ** 2 + (h / 2) ** 2)
    mask = np.clip((dist - 0.18) * (strength / 25.0), 0, 1)[..., None]
    return _from_float(arr * (1 - mask) + blurred * mask)


def _apply_vignette(image: Image.Image, amount: int, feather: int, midpoint: int, roundness: int) -> Image.Image:
    arr = np.asarray(image).astype(np.float32)
    h, w = arr.shape[:2]
    y, x = np.ogrid[:h, :w]
    cx, cy = w / 2, h / 2
    round_factor = 1 + roundness / 100.0
    dist = np.sqrt(((x - cx) * round_factor) ** 2 + (y - cy) ** 2)
    max_dist = np.sqrt(cx ** 2 + cy ** 2)
    mask = np.clip((dist / max_dist - midpoint / 140.0) * 2.2, 0, 1)
    power = max(0.4, 2.2 - feather / 70.0)
    mask = mask ** power
    strength = amount / 100.0
    factor = 1 + mask[..., None] * strength
    return Image.fromarray(np.clip(arr * factor, 0, 255).astype(np.uint8))


def _grain(image: Image.Image, amount: int, size: int) -> Image.Image:
    arr = _to_float(image)
    rng = np.random.default_rng(12345)
    scale = max(1, size)
    small_shape = (max(1, arr.shape[0] // scale), max(1, arr.shape[1] // scale), 1)
    noise = rng.normal(0, amount / 420.0, small_shape).astype(np.float32)
    noise = cv2.resize(noise, (arr.shape[1], arr.shape[0]), interpolation=cv2.INTER_LINEAR)[..., None]
    return _from_float(arr + noise)


def _apply_print_correction(image: Image.Image, params: dict) -> Image.Image:
    mode = params.get("print_mode", "None")
    values = {
        "General Print Safe": {"shadows": 8, "highlights": -8, "saturation": 4},
        "Canvas Print Boost": {"shadows": 14, "contrast": -4, "saturation": 8},
        "Sublimation Boost": {"shadows": 10, "contrast": 7, "saturation": 12},
        "Glossy Photo Paper": {"contrast": 5, "saturation": 4},
        "Matte Photo Paper": {"shadows": 8, "contrast": 3, "saturation": 6},
        "Mitsubishi D80 Correction": {"shadows": 6, "saturation": 3, "temperature": -3},
    }.get(mode, {})
    manual = {
        "shadows": int(params.get("print_boost_shadows", 0)),
        "highlights": -int(params.get("print_protect_highlights", 0)),
    }
    combined = {k: values.get(k, 0) + manual.get(k, 0) for k in set(values) | set(manual)}
    if any(combined.values()):
        image = _apply_tone_ranges(image, combined.get("highlights", 0), combined.get("shadows", 0), 0, 0)
    if values.get("contrast"):
        image = _contrast_curve(image, values["contrast"])
    if values.get("saturation"):
        image = ImageEnhance.Color(image).enhance(1 + values["saturation"] / 100.0)
    if values.get("temperature"):
        image = _apply_white_balance_shift(image, values["temperature"], 0)
    reduce_red = int(params.get("print_reduce_red_skin", 0))
    if reduce_red:
        image = _reduce_red_skin(image, reduce_red)
    return image


def _reduce_red_skin(image: Image.Image, amount: int) -> Image.Image:
    arr = np.asarray(image.convert("RGB"))
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV).astype(np.float32)
    hue = hsv[:, :, 0] * 2
    skinish = ((hue < 35) | (hue > 345)) & (hsv[:, :, 1] > 35) & (hsv[:, :, 2] > 45)
    hsv[:, :, 1][skinish] *= 1 - amount / 180.0
    out = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2RGB)
    return Image.fromarray(out)


def _unsharp(image: Image.Image, amount: int, radius: float) -> Image.Image:
    arr = np.asarray(image).astype(np.float32)
    blurred = cv2.GaussianBlur(arr, (0, 0), max(0.3, radius))
    strength = np.clip(amount, -100, 100) / 100.0
    out = arr + (arr - blurred) * strength
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
