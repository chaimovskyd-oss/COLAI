from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Tuple

from PIL import Image

MAX_FADE_PX = 70
MAX_OVERLAP_PX = 80

SOFT_FADE_MIN_ZOOM = 1.05

_VALID_EDGE_STYLES = {'hard', 'soft_fade', 'torn_paper'}
_VALID_FADE_MODES = {'soft_edge', 'overlap_fade'}
_VALID_FADE_SIDES = {
    'all', 'left', 'right', 'top', 'bottom', 'horizontal', 'vertical', 'auto_neighbors'
}
_VALID_FADE_CURVES = {'linear', 'smooth', 'ease_out'}


def normalize_edge_style(value: str) -> str:
    value = str(value or 'hard').strip().lower()
    return value if value in _VALID_EDGE_STYLES else 'hard'


def normalize_fade_mode(value: str) -> str:
    value = str(value or 'soft_edge').strip().lower()
    return value if value in _VALID_FADE_MODES else 'soft_edge'


def normalize_fade_sides(value: str) -> str:
    value = str(value or 'all').strip().lower()
    return value if value in _VALID_FADE_SIDES else 'all'


def normalize_fade_curve(value: str) -> str:
    value = str(value or 'smooth').strip().lower()
    return value if value in _VALID_FADE_CURVES else 'smooth'


def clamp_fade_amount(amount: int | float, cell_w: int, cell_h: int) -> int:
    amount = int(round(float(amount or 0)))
    if amount <= 0:
        return 0
    shorter_side = max(1, min(int(cell_w), int(cell_h)))
    relative_limit = max(1, int(round(shorter_side * 0.18)))
    return max(0, min(MAX_FADE_PX, relative_limit, amount))


def clamp_overlap_amount(amount: int | float, cell_w: int, cell_h: int) -> int:
    amount = int(round(float(amount or 0)))
    if amount <= 0:
        return 0
    shorter_side = max(1, min(int(cell_w), int(cell_h)))
    relative_limit = max(1, int(round(shorter_side * 0.20)))
    return max(0, min(MAX_OVERLAP_PX, relative_limit, amount))


def _padding_from_sides(amount: int, fade_sides: str) -> Tuple[int, int, int, int]:
    sides = normalize_fade_sides(fade_sides)
    if amount <= 0:
        return (0, 0, 0, 0)
    if sides == 'left':
        return (amount, 0, 0, 0)
    if sides == 'right':
        return (0, 0, amount, 0)
    if sides == 'top':
        return (0, amount, 0, 0)
    if sides == 'bottom':
        return (0, 0, 0, amount)
    if sides == 'horizontal':
        return (amount, 0, amount, 0)
    if sides == 'vertical':
        return (0, amount, 0, amount)
    return (amount, amount, amount, amount)


def resolve_softness_padding(
    edge_style: str,
    amount: int | float,
    fade_sides: str,
    cell_w: int,
    cell_h: int,
) -> Tuple[int, int, int, int]:
    if normalize_edge_style(edge_style) != 'soft_fade':
        return (0, 0, 0, 0)
    clamped = clamp_fade_amount(amount, cell_w, cell_h)
    return _padding_from_sides(clamped, fade_sides)


def resolve_overlap_padding(
    edge_style: str,
    mode: str,
    overlap_amount: int | float,
    overlap_sides: str,
    cell_w: int,
    cell_h: int,
    *,
    auto_neighbor_sides: Iterable[str] | None = None,
) -> Tuple[int, int, int, int]:
    if normalize_edge_style(edge_style) != 'soft_fade':
        return (0, 0, 0, 0)
    if normalize_fade_mode(mode) != 'overlap_fade':
        return (0, 0, 0, 0)
    clamped = clamp_overlap_amount(overlap_amount, cell_w, cell_h)
    if clamped <= 0:
        return (0, 0, 0, 0)
    sides = normalize_fade_sides(overlap_sides)
    if sides != 'auto_neighbors':
        return _padding_from_sides(clamped, sides)

    auto = {str(side).lower() for side in (auto_neighbor_sides or [])}
    return (
        clamped if 'left' in auto else 0,
        clamped if 'top' in auto else 0,
        clamped if 'right' in auto else 0,
        clamped if 'bottom' in auto else 0,
    )


def resolve_render_padding(
    edge_style: str,
    mode: str,
    softness_amount: int | float,
    overlap_amount: int | float,
    overlap_sides: str,
    cell_w: int,
    cell_h: int,
    *,
    auto_neighbor_sides: Iterable[str] | None = None,
) -> Tuple[int, int, int, int]:
    if normalize_fade_mode(mode) == 'overlap_fade':
        return resolve_overlap_padding(
            edge_style,
            mode,
            overlap_amount,
            overlap_sides,
            cell_w,
            cell_h,
            auto_neighbor_sides=auto_neighbor_sides,
        )
    return resolve_softness_padding(edge_style, softness_amount, overlap_sides, cell_w, cell_h)


def detect_neighbor_sides(
    cells,
    cell_index: int,
    *,
    max_gap: float,
) -> set[str]:
    if cells is None or cell_index < 0 or cell_index >= len(cells):
        return set()
    cell = cells[cell_index]
    left = cell.x
    top = cell.y
    right = cell.x + cell.w
    bottom = cell.y + cell.h
    sides: set[str] = set()
    for idx, other in enumerate(cells):
        if idx == cell_index:
            continue
        o_left = other.x
        o_top = other.y
        o_right = other.x + other.w
        o_bottom = other.y + other.h
        vertical_overlap = min(bottom, o_bottom) - max(top, o_top)
        horizontal_overlap = min(right, o_right) - max(left, o_left)
        if vertical_overlap > 1:
            if 0 <= o_left - right <= max_gap:
                sides.add('right')
            if 0 <= left - o_right <= max_gap:
                sides.add('left')
        if horizontal_overlap > 1:
            if 0 <= o_top - bottom <= max_gap:
                sides.add('bottom')
            if 0 <= top - o_bottom <= max_gap:
                sides.add('top')
    return sides


def expand_crop_box_for_padding(
    crop_box: Tuple[int, int, int, int],
    target_size: Tuple[int, int],
    padding: Tuple[int, int, int, int],
) -> Tuple[int, int, int, int]:
    left, top, right, bottom = padding
    crop_l, crop_t, crop_r, crop_b = crop_box
    target_w = max(1, int(target_size[0]))
    target_h = max(1, int(target_size[1]))
    crop_w = max(1, crop_r - crop_l)
    crop_h = max(1, crop_b - crop_t)
    scale_x = crop_w / float(target_w)
    scale_y = crop_h / float(target_h)
    return (
        int(round(crop_l - left * scale_x)),
        int(round(crop_t - top * scale_y)),
        int(round(crop_r + right * scale_x)),
        int(round(crop_b + bottom * scale_y)),
    )


@lru_cache(maxsize=256)
def _soft_fade_mask_cached(
    cell_w: int,
    cell_h: int,
    left: int,
    top: int,
    right: int,
    bottom: int,
    curve: str,
) -> bytes:
    total_w = cell_w + left + right
    total_h = cell_h + top + bottom
    try:
        import numpy as np

        y, x = np.ogrid[:total_h, :total_w]
        comps = []
        if left > 0:
            comps.append(np.clip((left - x) / float(left), 0.0, 1.0))
        if right > 0:
            right_edge = left + cell_w - 1
            comps.append(np.clip((x - right_edge) / float(right), 0.0, 1.0))
        if top > 0:
            comps.append(np.clip((top - y) / float(top), 0.0, 1.0))
        if bottom > 0:
            bottom_edge = top + cell_h - 1
            comps.append(np.clip((y - bottom_edge) / float(bottom), 0.0, 1.0))

        if not comps:
            alpha = np.ones((total_h, total_w), dtype=np.float32)
        elif len(comps) == 1:
            alpha = 1.0 - _curve_array(comps[0], curve)
        else:
            dist = np.zeros((total_h, total_w), dtype=np.float32)
            for comp in comps:
                dist += comp * comp
            alpha = 1.0 - _curve_array(np.clip(np.sqrt(dist), 0.0, 1.0), curve)

        alpha[top:top + cell_h, left:left + cell_w] = 1.0
        return (np.clip(alpha, 0.0, 1.0) * 255.0).astype('uint8').tobytes()
    except Exception:
        data = bytearray(total_w * total_h)
        for py in range(total_h):
            for px in range(total_w):
                nx = 0.0
                ny = 0.0
                if left > 0 and px < left:
                    nx = max(nx, (left - px) / float(left))
                if right > 0 and px >= left + cell_w:
                    nx = max(nx, (px - (left + cell_w - 1)) / float(right))
                if top > 0 and py < top:
                    ny = max(ny, (top - py) / float(top))
                if bottom > 0 and py >= top + cell_h:
                    ny = max(ny, (py - (top + cell_h - 1)) / float(bottom))
                dist = min(1.0, (nx * nx + ny * ny) ** 0.5 if nx and ny else max(nx, ny))
                alpha = 1.0 - _curve_scalar(dist, curve)
                if left <= px < left + cell_w and top <= py < top + cell_h:
                    alpha = 1.0
                data[py * total_w + px] = int(max(0.0, min(255.0, alpha * 255.0)))
        return bytes(data)


def build_soft_fade_mask(
    cell_w: int,
    cell_h: int,
    padding: Tuple[int, int, int, int],
    curve: str,
) -> Image.Image:
    left, top, right, bottom = [max(0, int(v)) for v in padding]
    total_w = cell_w + left + right
    total_h = cell_h + top + bottom
    raw = _soft_fade_mask_cached(
        int(cell_w), int(cell_h), left, top, right, bottom, normalize_fade_curve(curve)
    )
    return Image.frombytes('L', (total_w, total_h), raw)


def _curve_array(dist, curve: str):
    if curve == 'linear':
        return dist
    if curve == 'ease_out':
        return 1.0 - (1.0 - dist) ** 3
    return dist * dist * (3.0 - 2.0 * dist)


def _curve_scalar(dist: float, curve: str) -> float:
    if curve == 'linear':
        return dist
    if curve == 'ease_out':
        return 1.0 - (1.0 - dist) ** 3
    return dist * dist * (3.0 - 2.0 * dist)
