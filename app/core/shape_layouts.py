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
    inner_gap: int = 8,
) -> List[CellRect]:
    """Pack n_images rectangular cells inside the white area of mask.

    Tries many row-count configurations and for each one also tries an
    aspect-ratio-guided column distribution in addition to the width-proportional
    distribution.  The winner is picked by a combined score of fill-ratio (how
    much of the shape is covered) and aspect-ratio quality (cells close to 1:1
    score higher than thin slivers).
    """
    if n_images <= 0:
        return []

    w, h = mask.size
    mask_arr = np.array(mask)
    shape_area = float((mask_arr > 128).sum()) or 1.0

    best_score = -1.0
    best_cells: List[CellRect] = []

    # Try up to a generous number of rows so larger image counts can form
    # proper grids instead of thin vertical strips.
    max_rows = min(n_images, max(8, int(math.ceil(math.sqrt(n_images)) * 2)))

    for n_rows in range(1, max_rows + 1):
        row_h_f = (h - (n_rows - 1) * spacing) / n_rows
        if row_h_f < 20:
            break

        # Gather row spans (use 3 sample points, take widest)
        spans: List[Optional[Tuple[int, int]]] = []
        for r in range(n_rows):
            y_top = r * (row_h_f + spacing)
            best_span = None
            for frac in (0.25, 0.5, 0.75):
                sp = _row_span(mask_arr, int(y_top + row_h_f * frac), inner_gap)
                if sp and (best_span is None or
                           (sp[1] - sp[0]) > (best_span[1] - best_span[0])):
                    best_span = sp
            spans.append(best_span)

        if any(s is None for s in spans):
            continue

        widths = [float(s[1] - s[0]) for s in spans]  # type: ignore[index]
        if sum(widths) == 0:
            continue

        # Strategy 1: distribute proportionally to row widths (original)
        dist_prop = _distribute(n_images, widths)

        # Strategy 2: aspect-ratio-guided — each row gets roughly as many cells
        # as needed to produce ~1:1 cells (natural_n[r] ≈ row_width / row_height)
        natural_n = [max(1, round(wi / max(1.0, row_h_f))) for wi in widths]
        dist_ar = _distribute(n_images, [float(x) for x in natural_n])

        # Evaluate both distributions (skip duplicates)
        seen: set = set()
        for cells_per_row in (dist_prop, dist_ar):
            key = tuple(cells_per_row)
            if key in seen:
                continue
            seen.add(key)

            cells: List[CellRect] = []
            ok = True
            total_log_ar = 0.0

            for r, (n_here, span) in enumerate(zip(cells_per_row, spans)):
                if n_here <= 0:
                    continue
                y_top = r * (row_h_f + spacing)
                xl, xr = span  # type: ignore[misc]
                avail_w = xr - xl
                cell_w = (avail_w - (n_here - 1) * spacing) / n_here
                if cell_w < 8:
                    ok = False
                    break
                ar = cell_w / max(1.0, row_h_f)
                # log(ar): 0 for square, negative for portrait, positive for landscape
                total_log_ar += abs(math.log(max(0.05, ar)))
                for c in range(n_here):
                    x = xl + c * (cell_w + spacing)
                    cells.append(CellRect(
                        x=round(x), y=round(y_top),
                        w=max(1, round(cell_w)), h=max(1, round(row_h_f)),
                        image_index=len(cells),
                    ))

            if ok and len(cells) == n_images:
                cell_area = sum(c.w * c.h for c in cells)
                fill_score = cell_area / shape_area
                # Aspect-ratio quality: e^(-deviation) → 1.0 for square, decays for skewed
                avg_log_ar = total_log_ar / max(1, n_rows)
                ar_quality = math.exp(-avg_log_ar * 1.5)
                # Combined: weight fill and aspect ratio equally
                score = 0.5 * fill_score + 0.5 * ar_quality
                if score > best_score:
                    best_score = score
                    best_cells = cells

    return best_cells


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
