from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

import numpy as np
from PIL import Image

from app.models.project import COLOR_EQUALIZER_NODE_COUNT, ColorEqualizerState


CHANNELS = ('hue', 'saturation', 'brightness')
DEFAULT_MODE = 'saturation'
CURVE_SAMPLE_COUNT = 2048
MAX_HUE_SHIFT_DEG = 18.0
MAX_SATURATION_EFFECT = 0.52
MAX_BRIGHTNESS_EFFECT = 0.22
SATURATION_WEIGHT_START = 0.09
SATURATION_WEIGHT_END = 0.30
HIGHLIGHT_WEIGHT_START = 0.78
HIGHLIGHT_WEIGHT_END = 0.98
SKIN_HUE_CENTER = 24.0 / 360.0
SKIN_HUE_FEATHER = 34.0 / 360.0
SKIN_PROTECTION_STRENGTH = 0.42

COLOR_EQUALIZER_PRESETS: Dict[str, Dict[str, List[float]]] = {
    'Reduce Reds': {
        'hue': [0.0, -0.10, -0.08, 0.0, 0.0, 0.0, 0.0, 0.0],
        'saturation': [-0.28, -0.18, -0.06, 0.0, 0.0, 0.0, 0.0, -0.10],
        'brightness': [0.02, 0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 0.01],
    },
    'Boost Blues': {
        'hue': [0.0, 0.0, 0.0, 0.0, -0.03, -0.04, -0.02, 0.0],
        'saturation': [0.0, 0.0, 0.0, 0.0, 0.12, 0.24, 0.16, 0.02],
        'brightness': [0.0, 0.0, 0.0, 0.0, 0.02, 0.08, 0.04, 0.0],
    },
    'Natural Greens': {
        'hue': [0.0, 0.0, -0.02, -0.05, -0.02, 0.0, 0.0, 0.0],
        'saturation': [0.0, 0.0, 0.06, 0.14, 0.05, 0.0, 0.0, 0.0],
        'brightness': [0.0, 0.0, 0.02, 0.03, 0.01, 0.0, 0.0, 0.0],
    },
    'Soft Skin Fix': {
        'hue': [-0.02, -0.04, -0.02, 0.0, 0.0, 0.0, 0.0, -0.01],
        'saturation': [-0.16, -0.10, -0.02, 0.0, 0.0, 0.0, 0.0, -0.08],
        'brightness': [0.02, 0.03, 0.01, 0.0, 0.0, 0.0, 0.0, 0.01],
    },
    'Reset Safe': {
        'hue': [0.0] * COLOR_EQUALIZER_NODE_COUNT,
        'saturation': [0.0] * COLOR_EQUALIZER_NODE_COUNT,
        'brightness': [0.0] * COLOR_EQUALIZER_NODE_COUNT,
    },
}

_curve_cache: Dict[Tuple, Dict[str, np.ndarray]] = {}


def sanitize_color_equalizer_state(state: ColorEqualizerState | None) -> ColorEqualizerState:
    if state is None:
        return ColorEqualizerState()

    state.active_mode = state.active_mode if state.active_mode in CHANNELS else DEFAULT_MODE
    for attr in ('hue_values', 'saturation_values', 'brightness_values'):
        values = [float(v) for v in getattr(state, attr, [])[:COLOR_EQUALIZER_NODE_COUNT]]
        if len(values) < COLOR_EQUALIZER_NODE_COUNT:
            values.extend([0.0] * (COLOR_EQUALIZER_NODE_COUNT - len(values)))
        setattr(state, attr, [max(-1.0, min(1.0, v)) for v in values])
    return state


def has_meaningful_adjustment(state: ColorEqualizerState | None) -> bool:
    state = sanitize_color_equalizer_state(state)
    if not state.enabled:
        return False
    return any(
        any(abs(v) > 1e-4 for v in getattr(state, f'{channel}_values'))
        for channel in CHANNELS
    )


def reset_channel(state: ColorEqualizerState, mode: str) -> None:
    sanitize_color_equalizer_state(state)
    attr = f'{mode}_values'
    if hasattr(state, attr):
        setattr(state, attr, [0.0] * COLOR_EQUALIZER_NODE_COUNT)


def reset_all(state: ColorEqualizerState) -> None:
    sanitize_color_equalizer_state(state)
    for mode in CHANNELS:
        reset_channel(state, mode)


def apply_preset(state: ColorEqualizerState, preset_name: str) -> bool:
    sanitize_color_equalizer_state(state)
    preset = COLOR_EQUALIZER_PRESETS.get(preset_name)
    if preset is None:
        return False
    for mode in CHANNELS:
        setattr(state, f'{mode}_values', list(preset[mode]))
    state.enabled = preset_name != 'Reset Safe'
    return True


def channel_values(state: ColorEqualizerState) -> Dict[str, List[float]]:
    sanitize_color_equalizer_state(state)
    return {mode: list(getattr(state, f'{mode}_values')) for mode in CHANNELS}


def format_mode_value(mode: str, value: float) -> str:
    if mode == 'hue':
        return f'Hue {value * MAX_HUE_SHIFT_DEG:+.0f}'
    if mode == 'brightness':
        return f'Brightness {value * MAX_BRIGHTNESS_EFFECT * 100:+.0f}%'
    return f'Saturation {value * MAX_SATURATION_EFFECT * 100:+.0f}%'


def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / max(edge1 - edge0, 1e-6), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _soft_clip_signed(values: np.ndarray, limit: float = 0.92) -> np.ndarray:
    return limit * np.tanh(values / max(limit, 1e-6))


def _periodic_pchip_slopes(nodes: np.ndarray) -> np.ndarray:
    n = nodes.size
    delta = nodes[(np.arange(n) + 1) % n] - nodes
    slopes = np.zeros(n, dtype=np.float32)
    for idx in range(n):
        d_prev = delta[idx - 1]
        d_next = delta[idx]
        if abs(d_prev) < 1e-6 or abs(d_next) < 1e-6 or d_prev * d_next <= 0.0:
            slopes[idx] = 0.0
        else:
            slopes[idx] = (2.0 * d_prev * d_next) / (d_prev + d_next)
    return slopes


def _sample_periodic_curve(values: Iterable[float], positions: np.ndarray) -> np.ndarray:
    nodes = np.asarray(list(values), dtype=np.float32)
    if nodes.size != COLOR_EQUALIZER_NODE_COUNT:
        fixed = np.zeros(COLOR_EQUALIZER_NODE_COUNT, dtype=np.float32)
        fixed[: min(nodes.size, COLOR_EQUALIZER_NODE_COUNT)] = nodes[:COLOR_EQUALIZER_NODE_COUNT]
        nodes = fixed
    tangents = _periodic_pchip_slopes(nodes)
    scaled = np.mod(positions, 1.0) * nodes.size
    base = np.floor(scaled).astype(np.int32)
    t = (scaled - base).astype(np.float32)
    i0 = base % nodes.size
    i1 = (base + 1) % nodes.size
    y0 = nodes[i0]
    y1 = nodes[i1]
    m0 = tangents[i0]
    m1 = tangents[i1]
    t2 = t * t
    t3 = t2 * t
    h00 = 2.0 * t3 - 3.0 * t2 + 1.0
    h10 = t3 - 2.0 * t2 + t
    h01 = -2.0 * t3 + 3.0 * t2
    h11 = t3 - t2
    result = h00 * y0 + h10 * m0 + h01 * y1 + h11 * m1
    return _soft_clip_signed(result)


def _curve_cache_key(state: ColorEqualizerState) -> Tuple:
    return (
        tuple(round(v, 5) for v in state.hue_values),
        tuple(round(v, 5) for v in state.saturation_values),
        tuple(round(v, 5) for v in state.brightness_values),
    )


def _curve_luts_for_state(state: ColorEqualizerState) -> Dict[str, np.ndarray]:
    key = _curve_cache_key(state)
    cached = _curve_cache.get(key)
    if cached is not None:
        return cached
    positions = np.linspace(0.0, 1.0, CURVE_SAMPLE_COUNT, endpoint=False, dtype=np.float32)
    luts = {
        'hue': _sample_periodic_curve(state.hue_values, positions),
        'saturation': _sample_periodic_curve(state.saturation_values, positions),
        'brightness': _sample_periodic_curve(state.brightness_values, positions),
    }
    if len(_curve_cache) > 64:
        _curve_cache.clear()
    _curve_cache[key] = luts
    return luts


def _sample_curve_lut(curve: np.ndarray, positions: np.ndarray) -> np.ndarray:
    scaled = np.mod(positions, 1.0) * curve.size
    base = np.floor(scaled).astype(np.int32) % curve.size
    nxt = (base + 1) % curve.size
    frac = scaled - np.floor(scaled)
    return curve[base] * (1.0 - frac) + curve[nxt] * frac


def _rgb_to_hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    r = rgb[..., 0]
    g = rgb[..., 1]
    b = rgb[..., 2]
    maxc = np.max(rgb, axis=-1)
    minc = np.min(rgb, axis=-1)
    delta = maxc - minc
    s = np.where(maxc > 1e-6, delta / np.maximum(maxc, 1e-6), 0.0)
    h = np.zeros_like(maxc, dtype=np.float32)

    mask = delta > 1e-6
    r_mask = mask & (maxc == r)
    g_mask = mask & (maxc == g)
    b_mask = mask & (maxc == b)
    h[r_mask] = np.mod((g[r_mask] - b[r_mask]) / delta[r_mask], 6.0)
    h[g_mask] = ((b[g_mask] - r[g_mask]) / delta[g_mask]) + 2.0
    h[b_mask] = ((r[b_mask] - g[b_mask]) / delta[b_mask]) + 4.0
    h = (h / 6.0) % 1.0
    return h.astype(np.float32), s.astype(np.float32), maxc.astype(np.float32)


def _hsv_to_rgb(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    h6 = (np.mod(h, 1.0) * 6.0).astype(np.float32)
    i = np.floor(h6).astype(np.int32)
    f = h6 - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))

    out = np.zeros(h.shape + (3,), dtype=np.float32)
    idx = i % 6
    mappings = (
        (v, t, p),
        (q, v, p),
        (p, v, t),
        (p, q, v),
        (t, p, v),
        (v, p, q),
    )
    for bucket, comps in enumerate(mappings):
        mask = idx == bucket
        if np.any(mask):
            out[mask, 0] = comps[0][mask]
            out[mask, 1] = comps[1][mask]
            out[mask, 2] = comps[2][mask]
    return out


def _circular_hue_weight(h: np.ndarray, center: float, feather: float) -> np.ndarray:
    dist = np.abs(((h - center + 0.5) % 1.0) - 0.5)
    return 1.0 - _smoothstep(feather * 0.55, feather, dist)


def apply_color_equalizer(img: Image.Image, state: ColorEqualizerState | None) -> Image.Image:
    state = sanitize_color_equalizer_state(state)
    if not has_meaningful_adjustment(state):
        return img

    alpha = img.getchannel('A') if img.mode == 'RGBA' else None
    rgb = np.asarray(img.convert('RGB'), dtype=np.float32) / 255.0
    h, s, v = _rgb_to_hsv(rgb)
    luts = _curve_luts_for_state(state)

    chroma_weight = _smoothstep(SATURATION_WEIGHT_START, SATURATION_WEIGHT_END, s)
    chroma_weight = np.power(chroma_weight, 1.15, dtype=np.float32)
    highlight_weight = 1.0 - _smoothstep(HIGHLIGHT_WEIGHT_START, HIGHLIGHT_WEIGHT_END, v)
    effect_weight = chroma_weight * highlight_weight

    skin_weight = _circular_hue_weight(h, SKIN_HUE_CENTER, SKIN_HUE_FEATHER)
    skin_midtone_weight = _smoothstep(0.18, 0.70, s) * (1.0 - _smoothstep(0.80, 0.98, v))
    skin_protection = 1.0 - skin_weight * skin_midtone_weight * SKIN_PROTECTION_STRENGTH

    hue_curve = _sample_curve_lut(luts['hue'], h)
    sat_curve = _sample_curve_lut(luts['saturation'], h)
    bright_curve = _sample_curve_lut(luts['brightness'], h)

    hue_weight = effect_weight * skin_protection
    sat_weight = effect_weight * skin_protection
    bright_weight = effect_weight * (0.90 + 0.10 * skin_protection)

    h = (h + hue_curve * hue_weight * (MAX_HUE_SHIFT_DEG / 360.0)) % 1.0
    s = np.clip(s * (1.0 + sat_curve * sat_weight * MAX_SATURATION_EFFECT), 0.0, 1.0)
    v = np.clip(v + bright_curve * bright_weight * MAX_BRIGHTNESS_EFFECT, 0.0, 1.0)

    out = np.clip(_hsv_to_rgb(h, s, v), 0.0, 1.0)
    result = Image.fromarray((out * 255.0).astype(np.uint8), 'RGB')
    if alpha is not None:
        result.putalpha(alpha)
    return result
