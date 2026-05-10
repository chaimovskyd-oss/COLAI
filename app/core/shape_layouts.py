"""Shaped collage layouts — circle, heart.

get_shape_mask(shape, w, h, margin) → PIL.Image (L-mode, white=inside)
generate_shaped_layout(shape, n_images, settings) → LayoutSuggestion
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple, Dict

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from app.models.project import CellRect, LayoutSuggestion, ProjectSettings


# ---------------------------------------------------------------------------
# Shape masks
# ---------------------------------------------------------------------------

def get_shape_mask(shape: str, w: int, h: int, margin: int = 0) -> Image.Image:
    if shape == 'circle':
        return _circle_mask(w, h, margin)
    if shape == 'heart':
        return _heart_mask(w, h, margin)
    return Image.new('L', (w, h), 255)


def _circle_mask(w: int, h: int, margin: int) -> Image.Image:
    mask = Image.new('L', (w, h), 0)
    draw = ImageDraw.Draw(mask)
    r = min(w, h) // 2 - margin
    cx, cy = w // 2, h // 2
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    return mask


def _heart_mask(w: int, h: int, margin: int) -> Image.Image:
    mask = Image.new('L', (w, h), 0)
    draw = ImageDraw.Draw(mask)
    n = 600
    ts = np.linspace(0, 2 * math.pi, n)
    px = 16 * np.sin(ts) ** 3
    py = -(13 * np.cos(ts) - 5 * np.cos(2 * ts) - 2 * np.cos(3 * ts) - np.cos(4 * ts))
    pad = margin
    min_x, max_x = px.min(), px.max()
    min_y, max_y = py.min(), py.max()
    scale = min((w - 2 * pad) / max(1, max_x - min_x),
                (h - 2 * pad) / max(1, max_y - min_y))
    ox = (w - (max_x - min_x) * scale) / 2 - min_x * scale
    oy = (h - (max_y - min_y) * scale) / 2 - min_y * scale
    pts = [(float(px[i] * scale + ox), float(py[i] * scale + oy)) for i in range(n)]
    draw.polygon(pts, fill=255)
    return mask


# ---------------------------------------------------------------------------
# Row-span helper
# ---------------------------------------------------------------------------

def _row_span(mask_arr: np.ndarray, y: int, inner_gap: int) -> Optional[Tuple[int, int]]:
    """Widest white span at row y, inset by inner_gap. Returns None if nothing."""
    y = max(0, min(mask_arr.shape[0] - 1, y))
    row = mask_arr[y, :]
    xs = np.where(row > 128)[0]
    if len(xs) == 0:
        return None
    xl = int(xs[0]) + inner_gap
    xr = int(xs[-1]) - inner_gap
    if xr <= xl + 10:
        return None
    return xl, xr


# ---------------------------------------------------------------------------
# Cell packing
# ---------------------------------------------------------------------------

def _distribute(total: int, weights: List[float]) -> List[int]:
    """Distribute total items proportionally to weights, sum always == total."""
    s = sum(weights)
    if s <= 0:
        base = total // len(weights)
        result = [base] * len(weights)
        for i in range(total - sum(result)):
            result[i] += 1
        return result
    raw = [w / s * total for w in weights]
    floored = [int(x) for x in raw]
    fracs = sorted(range(len(raw)), key=lambda i: -(raw[i] - floored[i]))
    for i in range(total - sum(floored)):
        floored[fracs[i]] += 1
    return floored


def pack_cells_in_shape(
    mask: Image.Image,
    n_images: int,
    spacing: int = 10,
    inner_gap: int = 8,  # kept for API compatibility
) -> List[CellRect]:
    """Pack n_images cells filling the shape's bounding box with a uniform grid.

    Creates a regular rows×cols grid inside the tight bounding box of the mask.
    The shape mask is applied *after* rendering (apply_shape_mask in the pipeline),
    so cells near the boundary are automatically clipped to the shape — eliminating
    empty gaps at the edges without any per-row width sampling.

    Picks the grid configuration whose cell aspect ratio is closest to 4:3.
    Centers the last row when it has fewer cells than the other rows.
    """
    if n_images <= 0:
        return []

    w, h = mask.size
    mask_arr = np.array(mask) > 128

    # Tight bounding box of the shape
    rows_any = np.any(mask_arr, axis=1)
    cols_any = np.any(mask_arr, axis=0)
    if not rows_any.any():
        return []
    y_min = int(np.argmax(rows_any))
    y_max = int(len(rows_any) - np.argmax(rows_any[::-1]) - 1)
    x_min = int(np.argmax(cols_any))
    x_max = int(len(cols_any) - np.argmax(cols_any[::-1]) - 1)

    bbox_w = float(x_max - x_min)
    bbox_h = float(y_max - y_min)
    if bbox_w <= 0 or bbox_h <= 0:
        return []

    # Target aspect ratio: 4:3 landscape (typical photo)
    target_ar = 4.0 / 3.0

    best_score = -1.0
    best_cfg = (1, n_images)

    for n_rows in range(1, n_images + 1):
        n_cols = math.ceil(n_images / n_rows)
        cw = (bbox_w - spacing * (n_cols - 1)) / n_cols
        ch = (bbox_h - spacing * (n_rows - 1)) / n_rows
        if cw < 20 or ch < 20:
            continue
        ar = cw / max(1.0, ch)
        # Penalise deviation from target on a log scale
        score = math.exp(-abs(math.log(ar / target_ar)) * 1.2)
        if score > best_score:
            best_score = score
            best_cfg = (n_rows, n_cols)

    n_rows, n_cols = best_cfg
    cw = (bbox_w - spacing * (n_cols - 1)) / n_cols
    ch = (bbox_h - spacing * (n_rows - 1)) / n_rows

    cells: List[CellRect] = []
    placed = 0
    for row in range(n_rows):
        if placed >= n_images:
            break
        cells_this_row = min(n_cols, n_images - placed)
        # Centre the last partial row horizontally inside the bounding box
        offset_x = (n_cols - cells_this_row) * (cw + spacing) / 2.0
        for col in range(cells_this_row):
            x = x_min + offset_x + col * (cw + spacing)
            y = y_min + row * (ch + spacing)
            cells.append(CellRect(
                x=round(x), y=round(y),
                w=max(1, round(cw)), h=max(1, round(ch)),
                image_index=placed,
            ))
            placed += 1

    return cells


# ---------------------------------------------------------------------------
# High-level generator
# ---------------------------------------------------------------------------

def generate_shaped_layout(
    shape: str,
    n_images: int,
    settings: ProjectSettings,
) -> LayoutSuggestion:
    """Return a LayoutSuggestion where images are packed inside the given shape."""
    cw, ch = settings.canvas_px
    margin = max(settings.margin_px, int(min(cw, ch) * 0.04))
    spacing = settings.spacing_px

    mask = get_shape_mask(shape, cw, ch, margin)
    cells = pack_cells_in_shape(mask, n_images, spacing=spacing, inner_gap=spacing)

    shape_area = float((np.array(mask) > 128).sum()) or 1.0
    cell_area = sum(c.w * c.h for c in cells)
    score = min(1.0, cell_area / shape_area) if cells else 0.0
    name = {'circle': 'Circle', 'heart': 'Heart \u2661'}.get(shape, shape.capitalize())

    layout = LayoutSuggestion(name=name, cells=cells, score=score)
    layout.shape = shape
    return layout
