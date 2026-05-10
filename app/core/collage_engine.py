from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Spotify code detection helper
# ---------------------------------------------------------------------------

def detect_spotify_code_image(images: "List[ImageState]") -> "Optional[ImageState]":
    """Return the first ImageState that looks like a Spotify scan code, or None.

    Heuristic: Spotify codes are wide (aspect ≥ 2:1), and the pixel content is
    mostly monochromatic (≤ 3 distinct hues when posterised to 8 colours).
    Falls back to accepting the image if PIL cannot open it.
    """
    from PIL import Image as _Image
    for state in images:
        try:
            with _Image.open(state.path) as img:
                w, h = img.size
                if h == 0:
                    continue
                aspect = w / h
                # Spotify codes are wider than tall (roughly 4:1 or 3:1)
                if aspect < 1.5:
                    continue
                if aspect >= 2.8:
                    return state
                # Quick colour test: convert to palette with 8 colours,
                # then check how many distinct non-white/non-black colours remain
                small = img.convert('RGB').resize((120, 30), _Image.BILINEAR)
                q = small.quantize(colors=8, method=_Image.Quantize.FASTOCTREE)
                palette = q.getpalette()[:8 * 3]
                hues = set()
                for i in range(8):
                    r, g, b = palette[i*3], palette[i*3+1], palette[i*3+2]
                    brightness = (r + g + b) / 3
                    if 20 < brightness < 220:   # skip near-black and near-white
                        hues.add((r >> 5, g >> 5, b >> 5))
                # Spotify codes have ≤ 2 mid-tone hues (the bar colour + background tint)
                if len(hues) <= 3:
                    return state
        except Exception:
            # If we can't open/analyse the image, accept it and let the user proceed
            return state
    return None

from PIL import Image

from app.core.smart_crop_service import score_cell_fit
from app.models.project import CellRect, ImageState, LayoutSuggestion, ProjectSettings
from app.core.diagonal_layouts import get_diagonal_layouts


# ---------------------------------------------------------------------------
# Core grid helper – used by every template
# ---------------------------------------------------------------------------

def _make_grid_cells(
    count: int,
    x_start: float,
    y_start: float,
    available_w: float,
    available_h: float,
    spacing: float,
    max_cols: int = 5,
) -> List[CellRect]:
    """Build a uniform grid of `count` cells inside a bounding box.

    The *last row* is always stretched to fill the full available width so
    there are no empty white areas even when the row is incomplete.
    All cells are guaranteed to stay within the bounding box.
    """
    if count <= 0:
        return []

    cols = min(count, max_cols)
    rows = (count + cols - 1) // cols

    cell_w = (available_w - spacing * (cols - 1)) / max(1, cols)
    cell_h = (available_h - spacing * (rows - 1)) / max(1, rows)

    cells: List[CellRect] = []
    for i in range(count):
        row = i // cols
        col = i % cols

        row_start = row * cols
        row_count = min(cols, count - row_start)  # cells in this row

        # Stretch last (partial) row to fill width
        if row_count < cols:
            w = (available_w - spacing * (row_count - 1)) / row_count
            x = x_start + (i - row_start) * (w + spacing)
        else:
            w = cell_w
            x = x_start + col * (cell_w + spacing)

        y = y_start + row * (cell_h + spacing)
        cells.append(CellRect(x, y, w, cell_h))

    return cells


def _assign_images(cells: List[CellRect], image_count: int) -> List[CellRect]:
    for idx, cell in enumerate(cells):
        cell.image_index = idx if idx < image_count else None
    return cells


def _image_cell_fit_score(cell: CellRect, image: ImageState) -> float:
    try:
        with Image.open(image.path) as img:
            img_ratio = img.width / max(1, img.height)
    except Exception:
        img_ratio = 1.0
    cell_ratio = cell.w / max(1.0, cell.h)
    bigger = max(img_ratio, cell_ratio)
    smaller = min(img_ratio, cell_ratio)
    base_score = smaller / bigger
    smart_score = score_cell_fit(getattr(image, 'analysis', None), cell.w, cell.h)
    area_bonus = min(1.0, (cell.w * cell.h) / 220000.0)
    return base_score * 0.58 + smart_score * 0.32 + area_bonus * 0.10


def _optimize_layout_assignments(layout: LayoutSuggestion, images: List[ImageState]) -> None:
    """Assign images to cells by best-fit instead of import order.

    This is intentionally lightweight and greedy: repeatedly choose the best
    remaining image-cell pair. It materially improves placement of group photos
    into larger / wider cells without redesigning the layout engine.
    """
    if not images or not layout.cells:
        return

    remaining_cells = list(range(len(layout.cells)))
    remaining_images = list(range(len(images)))

    for cell in layout.cells:
        cell.image_index = None

    while remaining_cells and remaining_images:
        best_pair: Optional[Tuple[float, int, int]] = None
        for cell_idx in remaining_cells:
            cell = layout.cells[cell_idx]
            for image_idx in remaining_images:
                fit = _image_cell_fit_score(cell, images[image_idx])
                if best_pair is None or fit > best_pair[0]:
                    best_pair = (fit, cell_idx, image_idx)
        if best_pair is None:
            break
        _, cell_idx, image_idx = best_pair
        layout.cells[cell_idx].image_index = image_idx
        remaining_cells.remove(cell_idx)
        remaining_images.remove(image_idx)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_layout(layout: LayoutSuggestion, images: List[ImageState]) -> float:
    """Score [0..1] – how well cell aspect ratios match source image ratios."""
    if not images or not layout.cells:
        return 0.0
    total = 0.0
    counted = 0
    for cell in layout.cells:
        if cell.image_index is None or cell.image_index >= len(images):
            continue
        total += _image_cell_fit_score(cell, images[cell.image_index])
        counted += 1
    return total / max(1, counted)


# ---------------------------------------------------------------------------
# Layout templates
# Each template MUST produce exactly `image_count` cells.
# All cells must fit within [margin, canvas_w - margin] × [margin, canvas_h - margin].
# ---------------------------------------------------------------------------

def _grid_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Universal grid – adapts to any image count."""
    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    # Choose column count to keep cells roughly square-ish
    if image_count <= 2:
        max_cols = image_count
    elif image_count <= 4:
        max_cols = 2
    elif image_count <= 9:
        max_cols = 3
    elif image_count <= 16:
        max_cols = 4
    else:
        max_cols = 5

    cells = _make_grid_cells(image_count, margin, margin, usable_w, usable_h, spacing, max_cols)
    return LayoutSuggestion(name='Grid', cells=_assign_images(cells, image_count))


def _hero_top_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Large hero at top; remaining images in a grid below."""
    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    if image_count == 1:
        cells = [CellRect(margin, margin, usable_w, usable_h)]
        return LayoutSuggestion(name='Hero Top', cells=_assign_images(cells, 1))

    hero_h = usable_h * 0.55
    below_h = usable_h - hero_h - spacing

    cells = [CellRect(float(margin), float(margin), usable_w, hero_h)]
    remaining = image_count - 1
    below_cells = _make_grid_cells(
        remaining, margin, margin + hero_h + spacing, usable_w, below_h, spacing, min(remaining, 4)
    )
    cells.extend(below_cells)
    return LayoutSuggestion(name='Hero Top', cells=_assign_images(cells, image_count))


def _hero_bottom_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Thumbnail row on top, large hero at bottom."""
    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    if image_count == 1:
        cells = [CellRect(margin, margin, usable_w, usable_h)]
        return LayoutSuggestion(name='Hero Bottom', cells=_assign_images(cells, 1))

    remaining = image_count - 1
    thumb_h = usable_h * 0.35
    hero_h = usable_h - thumb_h - spacing

    thumb_cells = _make_grid_cells(
        remaining, margin, margin, usable_w, thumb_h, spacing, min(remaining, 4)
    )
    hero_y = float(margin) + thumb_h + spacing
    hero_cell = CellRect(float(margin), hero_y, usable_w, hero_h)

    cells = list(thumb_cells) + [hero_cell]
    return LayoutSuggestion(name='Hero Bottom', cells=_assign_images(cells, image_count))


def _feature_left_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Wide feature cell on the left; grid of remaining on the right."""
    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    if image_count == 1:
        cells = [CellRect(margin, margin, usable_w, usable_h)]
        return LayoutSuggestion(name='Feature Left', cells=_assign_images(cells, 1))

    left_w = usable_w * 0.58
    right_w = usable_w - left_w - spacing

    left_cell = CellRect(float(margin), float(margin), left_w, usable_h)
    remaining = image_count - 1
    right_x = float(margin) + left_w + spacing
    right_cells = _make_grid_cells(remaining, right_x, margin, right_w, usable_h, spacing, 2)

    cells = [left_cell] + list(right_cells)
    return LayoutSuggestion(name='Feature Left', cells=_assign_images(cells, image_count))


def _mosaic_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Two asymmetric cells on top; remaining in a grid below."""
    if image_count <= 2:
        return _grid_layout(settings, image_count)

    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    top_h = usable_h * 0.48
    bottom_h = usable_h - top_h - spacing

    left_w = usable_w * 0.62
    right_w = usable_w - left_w - spacing

    top_cells = [
        CellRect(float(margin), float(margin), left_w, top_h),
        CellRect(float(margin) + left_w + spacing, float(margin), right_w, top_h),
    ]

    remaining = image_count - 2
    bottom_y = float(margin) + top_h + spacing
    bottom_cells = _make_grid_cells(remaining, margin, bottom_y, usable_w, bottom_h, spacing, min(remaining, 3))

    cells = top_cells + list(bottom_cells)
    return LayoutSuggestion(name='Mosaic', cells=_assign_images(cells, image_count))


def _strip_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """All images in a single horizontal strip (equal widths)."""
    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    # For very large counts, wrap into 2 rows so cells are not too narrow
    if image_count > 6:
        return LayoutSuggestion(
            name='Strip',
            cells=_assign_images(
                _make_grid_cells(image_count, margin, margin, usable_w, usable_h, spacing, image_count),
                image_count,
            ),
        )

    cells = _make_grid_cells(image_count, margin, margin, usable_w, usable_h, spacing, image_count)
    return LayoutSuggestion(name='Strip', cells=_assign_images(cells, image_count))


def _magazine_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Wide left feature (60 %), stacked grid on the right."""
    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    if image_count == 1:
        cells = [CellRect(margin, margin, usable_w, usable_h)]
        return LayoutSuggestion(name='Magazine', cells=_assign_images(cells, 1))

    left_w = usable_w * 0.60
    right_w = usable_w - left_w - spacing

    left_cell = CellRect(float(margin), float(margin), left_w, usable_h)
    remaining = image_count - 1
    right_x = float(margin) + left_w + spacing
    right_cells = _make_grid_cells(remaining, right_x, margin, right_w, usable_h, spacing, 2)

    cells = [left_cell] + list(right_cells)
    return LayoutSuggestion(name='Magazine', cells=_assign_images(cells, image_count))


# ---------------------------------------------------------------------------
# Extra layouts – asymmetric / multi-hero
# ---------------------------------------------------------------------------

def _dual_hero_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Two equal large heroes side-by-side on top; remaining in a grid below."""
    if image_count < 2:
        return _grid_layout(settings, image_count)
    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    if image_count == 2:
        hero_w = (usable_w - spacing) / 2
        cells = [
            CellRect(float(margin), float(margin), hero_w, usable_h),
            CellRect(float(margin) + hero_w + spacing, float(margin), hero_w, usable_h),
        ]
        return LayoutSuggestion(name='Dual Hero', cells=_assign_images(cells, 2))

    hero_h = usable_h * 0.55
    below_h = usable_h - hero_h - spacing
    hero_w = (usable_w - spacing) / 2

    cells = [
        CellRect(float(margin), float(margin), hero_w, hero_h),
        CellRect(float(margin) + hero_w + spacing, float(margin), hero_w, hero_h),
    ]
    remaining = image_count - 2
    below_y = float(margin) + hero_h + spacing
    cells.extend(_make_grid_cells(remaining, margin, below_y, usable_w, below_h, spacing,
                                   min(remaining, 4)))
    return LayoutSuggestion(name='Dual Hero', cells=_assign_images(cells, image_count))


def _triptych_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Three equal columns filling the full height; remaining in a row below."""
    if image_count < 3:
        return _grid_layout(settings, image_count)
    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    if image_count == 3:
        col_w = (usable_w - 2 * spacing) / 3
        cells = [
            CellRect(float(margin) + i * (col_w + spacing), float(margin), col_w, usable_h)
            for i in range(3)
        ]
        return LayoutSuggestion(name='Triptych', cells=_assign_images(cells, 3))

    tri_h = usable_h * 0.60
    below_h = usable_h - tri_h - spacing
    col_w = (usable_w - 2 * spacing) / 3
    cells = [
        CellRect(float(margin) + i * (col_w + spacing), float(margin), col_w, tri_h)
        for i in range(3)
    ]
    remaining = image_count - 3
    below_y = float(margin) + tri_h + spacing
    cells.extend(_make_grid_cells(remaining, margin, below_y, usable_w, below_h, spacing,
                                   min(remaining, 4)))
    return LayoutSuggestion(name='Triptych', cells=_assign_images(cells, image_count))


def _cascade_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Large hero top-left; medium cell top-right; small cells below right; strip below left."""
    if image_count < 3:
        return _grid_layout(settings, image_count)
    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    left_w = usable_w * 0.55
    right_w = usable_w - left_w - spacing
    top_h = usable_h * 0.60
    bottom_h = usable_h - top_h - spacing
    right_x = float(margin) + left_w + spacing

    # Hero (top-left)
    cells = [CellRect(float(margin), float(margin), left_w, top_h)]

    # Top-right: split into 1 or 2 stacked cells
    top_right_count = min(2, image_count - 1)
    cells.extend(_make_grid_cells(top_right_count, right_x, margin, right_w, top_h, spacing, 1))

    # Bottom row: remaining images
    placed = 1 + top_right_count
    remaining = image_count - placed
    if remaining > 0:
        bottom_y = float(margin) + top_h + spacing
        cells.extend(_make_grid_cells(remaining, margin, bottom_y, usable_w, bottom_h, spacing,
                                       min(remaining, 4)))

    return LayoutSuggestion(name='Cascade', cells=_assign_images(cells, image_count))


def _wide_banner_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Full-width banner at top (single image); grid fills the rest."""
    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    if image_count == 1:
        return LayoutSuggestion(
            name='Wide Banner',
            cells=_assign_images([CellRect(margin, margin, usable_w, usable_h)], 1),
        )

    banner_h = usable_h * 0.30
    below_h = usable_h - banner_h - spacing
    cells = [CellRect(float(margin), float(margin), usable_w, banner_h)]
    remaining = image_count - 1
    below_y = float(margin) + banner_h + spacing
    cells.extend(_make_grid_cells(remaining, margin, below_y, usable_w, below_h, spacing,
                                   min(remaining, 4)))
    return LayoutSuggestion(name='Wide Banner', cells=_assign_images(cells, image_count))


def _torn_paper_collage_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Layered torn-paper composition that starts at center and expands outward."""
    width, height = settings.canvas_px
    margin = float(settings.margin_px)
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)
    safe_pad = max(margin, min(width, height) * 0.055)
    left, top = safe_pad, safe_pad
    right, bottom = width - safe_pad, height - safe_pad
    safe_w, safe_h = max(1.0, right - left), max(1.0, bottom - top)
    cx, cy = width / 2.0, height / 2.0
    rnd = random.Random(9103 + image_count * 37 + int(width) * 3 + int(height))

    def rotated_fit(w: float, h: float) -> tuple[float, float, float]:
        rot = rnd.uniform(-6.0, 6.0)
        rad = abs(math.radians(rot))
        bound_w = abs(w * math.cos(rad)) + abs(h * math.sin(rad))
        bound_h = abs(w * math.sin(rad)) + abs(h * math.cos(rad))
        shrink = min(1.0, safe_w / max(1.0, bound_w), safe_h / max(1.0, bound_h))
        return w * shrink, h * shrink, rot

    def cell_at(center_x: float, center_y: float, w: float, h: float, z: int, idx: int) -> CellRect:
        w, h, rot = rotated_fit(w, h)
        x = max(left, min(right - w, center_x - w / 2.0))
        y = max(top, min(bottom - h, center_y - h / 2.0))
        cell = CellRect(x, y, w, h, image_index=idx)
        cell.rotation_deg = rot
        cell.z_index = z
        cell.edge_style = 'torn_paper'
        cell.mask_seed = 4200 + idx * 97 + image_count * 13
        return cell

    if image_count <= 0:
        return LayoutSuggestion(name='torn_paper_collage', cells=[])

    hero_w = min(safe_w * 0.58, usable_w * 0.68)
    hero_h = min(safe_h * 0.58, usable_h * 0.68)
    if width >= height:
        hero_w *= 1.08
        hero_h *= 0.92
    else:
        hero_w *= 0.92
        hero_h *= 1.08
    cells: List[CellRect] = [cell_at(cx, cy, hero_w, hero_h, 2, 0)]
    cells[0].rotation_deg = rnd.uniform(-2.5, 2.5)

    medium_w = hero_w * 0.56
    medium_h = hero_h * 0.56
    small_w = hero_w * 0.42
    small_h = hero_h * 0.42
    radius_x = hero_w * 0.48
    radius_y = hero_h * 0.46
    anchors = [
        (-0.92, -0.70), (0.92, -0.62), (-0.92, 0.68), (0.92, 0.72),
        (0.00, -1.08), (-1.08, 0.02), (1.08, 0.02), (0.00, 1.08),
        (-0.45, -1.04), (0.48, 1.05), (-1.04, -0.28), (1.04, 0.32),
    ]
    for idx in range(1, image_count):
        ax, ay = anchors[(idx - 1) % len(anchors)]
        size_group = 'medium' if idx <= min(3, image_count - 1) else 'small'
        base_w = medium_w if size_group == 'medium' else small_w
        base_h = medium_h if size_group == 'medium' else small_h
        jitter_x = rnd.uniform(-0.09, 0.09) * hero_w
        jitter_y = rnd.uniform(-0.09, 0.09) * hero_h
        px = cx + ax * radius_x + jitter_x
        py = cy + ay * radius_y + jitter_y
        scale = rnd.uniform(0.92, 1.08)
        cells.append(cell_at(px, py, base_w * scale, base_h * scale, 3 + idx, idx))

    return LayoutSuggestion(name='torn_paper_collage', cells=cells)


# ---------------------------------------------------------------------------
# New layouts – adaptive editorial / mosaic families
# ---------------------------------------------------------------------------

def _circle_ring_collage_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Circular ring collage with an empty centre for text, logo, QR, etc."""
    width, height = settings.canvas_px
    margin = float(settings.margin_px)
    safe_pad = max(margin, min(width, height) * 0.045)
    cx, cy = width / 2.0, height / 2.0
    outer_r = max(1.0, min(width, height) / 2.0 - safe_pad)
    if image_count <= 5:
        inner_ratio = 0.38
    elif image_count <= 12:
        inner_ratio = 0.42
    else:
        inner_ratio = 0.46
    inner_r = outer_r * inner_ratio
    # Larger gap makes the separation between segments clearly visible and equal
    gap_angle = 4.0 if image_count <= 5 else (3.0 if image_count <= 12 else 2.0)
    step = 360.0 / max(1, image_count)

    def angle_in_segment(angle: float, start: float, end: float) -> bool:
        while angle < start:
            angle += 360.0
        return start <= angle <= end

    def point_at(angle_deg: float, radius: float) -> tuple[float, float]:
        rad = math.radians(angle_deg)
        return cx + math.cos(rad) * radius, cy + math.sin(rad) * radius

    cells: List[CellRect] = []
    if image_count <= 0:
        return LayoutSuggestion(name='circle_ring_collage', cells=[])

    for idx in range(image_count):
        start = -90.0 + idx * step
        end = start + step
        visible_start = start + gap_angle / 2.0
        visible_end = end - gap_angle / 2.0
        sample_angles = [visible_start, visible_end]
        sample_angles.extend(visible_start + (visible_end - visible_start) * t / 10.0 for t in range(1, 10))
        for cardinal in (-90.0, 0.0, 90.0, 180.0, 270.0):
            if angle_in_segment(cardinal, visible_start, visible_end):
                sample_angles.append(cardinal)
        pts = []
        for ang in sample_angles:
            pts.append(point_at(ang, outer_r))
            pts.append(point_at(ang, inner_r))
        pad = max(4.0, float(settings.spacing_px) * 0.4)
        min_x = max(0.0, min(px for px, _py in pts) - pad)
        max_x = min(float(width), max(px for px, _py in pts) + pad)
        min_y = max(0.0, min(py for _px, py in pts) - pad)
        max_y = min(float(height), max(py for _px, py in pts) + pad)
        x = min_x
        y = min_y
        w = max(1.0, max_x - min_x)
        h = max(1.0, max_y - min_y)
        cell = CellRect(x, y, max(1.0, w), max(1.0, h), image_index=idx)
        cell.shape_type = 'ring_segment'
        cell.shape_params = {
            'start_angle': start,
            'end_angle': end,
            'gap_angle': gap_angle,
            'center_x': cx - x,
            'center_y': cy - y,
            'outer_radius': outer_r,
            'inner_radius': inner_r,
        }
        cell.z_index = 0  # all segments same level — RGBA mask handles clipping
        cell.mask_seed = 6100 + idx * 19 + image_count * 101
        cells.append(cell)

    return LayoutSuggestion(name='circle_ring_collage', cells=cells)


def _mosaic_spotlight_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """One dominant focal cell with adaptive support blocks around it."""
    if image_count <= 2:
        return _feature_left_layout(settings, image_count)

    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)
    landscape = usable_w >= usable_h

    cells: List[CellRect] = []
    if landscape:
        focus_w = usable_w * 0.58
        side_w = usable_w - focus_w - spacing
        top_h = usable_h * 0.52
        bottom_h = usable_h - top_h - spacing
        cells.append(CellRect(float(margin), float(margin), focus_w, usable_h))
        remaining = image_count - 1
        top_count = min(2, remaining)
        if top_count > 0:
            cells.extend(_make_grid_cells(top_count, margin + focus_w + spacing, margin,
                                          side_w, top_h, spacing, top_count))
            remaining -= top_count
        if remaining > 0:
            bottom_y = float(margin) + top_h + spacing
            cells.extend(_make_grid_cells(remaining, margin + focus_w + spacing, bottom_y,
                                          side_w, bottom_h, spacing, min(remaining, 3)))
    else:
        focus_h = usable_h * 0.57
        strip_h = usable_h - focus_h - spacing
        cells.append(CellRect(float(margin), float(margin), usable_w, focus_h))
        remaining = image_count - 1
        left_count = min(2, remaining)
        left_w = usable_w * 0.46
        right_w = usable_w - left_w - spacing
        if left_count > 0:
            cells.extend(_make_grid_cells(left_count, margin, margin + focus_h + spacing,
                                          left_w, strip_h, spacing, 1))
            remaining -= left_count
        if remaining > 0:
            right_x = float(margin) + left_w + spacing
            cells.extend(_make_grid_cells(remaining, right_x, margin + focus_h + spacing,
                                          right_w, strip_h, spacing, min(remaining, 2)))
    return LayoutSuggestion(name='Mosaic Spotlight', cells=_assign_images(cells, image_count))


def _film_strip_mix_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Editorial strip mix with uneven rows and a wider closing band."""
    if image_count <= 3:
        return _grid_layout(settings, image_count)

    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    top_h = usable_h * 0.36
    mid_h = usable_h * 0.29
    bottom_h = usable_h - top_h - mid_h - spacing * 2

    top_count = min(2, image_count)
    remaining = image_count - top_count
    bottom_count = 1 if remaining >= 2 else remaining
    mid_count = max(0, remaining - bottom_count)

    cells: List[CellRect] = []
    cells.extend(_make_grid_cells(top_count, margin, margin, usable_w, top_h, spacing, top_count))
    if mid_count > 0:
        mid_y = float(margin) + top_h + spacing
        mid_cols = min(3, max(1, mid_count))
        cells.extend(_make_grid_cells(mid_count, margin, mid_y, usable_w, mid_h, spacing, mid_cols))
    if bottom_count > 0:
        bottom_y = float(margin) + top_h + spacing + mid_h + spacing
        if bottom_count == 1:
            cells.append(CellRect(float(margin), bottom_y, usable_w, bottom_h))
        else:
            cells.extend(_make_grid_cells(bottom_count, margin, bottom_y, usable_w, bottom_h,
                                          spacing, min(bottom_count, 2)))
    return LayoutSuggestion(name='Film Strip Mix', cells=_assign_images(cells, image_count))


def _staircase_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Diagonal staircase: each step starts one band lower, extends to canvas bottom.

    Layout model (3 steps, 5 images example):
      ┌────┬────┬────┐
      │ 1  │fill│fill│  ← band 0: step 0 tall, fill cells above steps 1+2
      │    ├────┤    │
      │    │ 2  │fill│  ← band 1
      │    │    ├────┤
      │    │    │ 3  │  ← band 2
      └────┴────┴────┘

    Steps never overlap because each step_y is the cumulative height of all
    previous steps.  Fill areas are the rectangles above each step column.
    """
    if image_count <= 3:
        return _mosaic_layout(settings, image_count)

    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    # Adapt step count to image count
    step_count = 3
    if image_count >= 8:
        step_count = 4

    # Equal-width columns, equal-height bands
    col_w = (usable_w - spacing * (step_count - 1)) / step_count
    band_h = (usable_h - spacing * (step_count - 1)) / step_count

    # Build stair cells — no overlap: each step_y = cumulative previous band heights
    stair_cells: List[CellRect] = []
    y_tops: List[float] = []
    for idx in range(step_count):
        y_top = float(margin) + idx * (band_h + spacing)
        step_h = usable_h + float(margin) - y_top   # extends to canvas bottom
        x = float(margin) + idx * (col_w + spacing)
        stair_cells.append(CellRect(x, y_top, col_w, step_h))
        y_tops.append(y_top)

    cells: List[CellRect] = list(stair_cells)
    remaining = image_count - step_count

    if remaining > 0:
        # Fill areas: rectangles above each step (except step 0 which starts at top)
        fill_regions: List[tuple] = []
        for idx in range(1, step_count):
            fx = float(margin) + idx * (col_w + spacing)
            fy = float(margin)
            fw = col_w
            fh = y_tops[idx] - float(margin) - spacing
            if fw >= 24 and fh >= 24:
                fill_regions.append((fw * fh, fx, fy, fw, fh))

        fill_regions.sort(key=lambda t: -t[0])   # largest first

        if fill_regions:
            # Distribute remaining images proportionally to fill-area size
            total_area = sum(t[0] for t in fill_regions)
            counts = [max(1, round(t[0] / total_area * remaining)) for t in fill_regions]
            # Correct rounding drift
            while sum(counts) > remaining:
                counts[counts.index(max(counts))] -= 1
            while sum(counts) < remaining:
                counts[counts.index(min(counts))] += 1

            for n, (_, fx, fy, fw, fh) in zip(counts, fill_regions):
                if n > 0:
                    n_cols_fill = max(1, min(n, round(fw / max(1.0, fh))))
                    cells.extend(_make_grid_cells(n, fx, fy, fw, fh,
                                                  spacing, n_cols_fill))
        else:
            # Fallback if no fill area is large enough
            cells.extend(_make_grid_cells(remaining, margin, margin,
                                          usable_w, usable_h, spacing, 3))
            cells = cells[:image_count]

    return LayoutSuggestion(name='Staircase', cells=_assign_images(cells, image_count))


def _ring_focus_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Central focus image with adaptive cells wrapped around it."""
    if image_count <= 3:
        return _hero_top_layout(settings, image_count)

    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    center_w = usable_w * 0.50
    center_h = usable_h * 0.50
    center_x = float(margin) + (usable_w - center_w) / 2.0
    center_y = float(margin) + (usable_h - center_h) / 2.0

    cells: List[CellRect] = [CellRect(center_x, center_y, center_w, center_h)]
    remaining = image_count - 1
    top_count = min(max(1, remaining // 4 + (1 if remaining % 4 else 0)), remaining)
    remaining -= top_count
    right_count = min(max(1, remaining // 3 + (1 if remaining > 0 else 0)), remaining)
    remaining -= right_count
    bottom_count = min(max(1, remaining // 2 + (1 if remaining > 0 else 0)), remaining)
    remaining -= bottom_count
    left_count = remaining

    top_h = max(24.0, center_y - float(margin) - spacing)
    bottom_y = center_y + center_h + spacing
    bottom_h = max(24.0, float(margin) + usable_h - bottom_y)
    left_w = max(24.0, center_x - float(margin) - spacing)
    right_x = center_x + center_w + spacing
    right_w = max(24.0, float(margin) + usable_w - right_x)

    if top_count > 0:
        cells.extend(_make_grid_cells(top_count, margin, margin, usable_w, top_h, spacing,
                                      min(top_count, 4)))
    if right_count > 0:
        cells.extend(_make_grid_cells(right_count, right_x, center_y, right_w, center_h, spacing,
                                      1 if right_count <= 2 else 2))
    if bottom_count > 0:
        cells.extend(_make_grid_cells(bottom_count, margin, bottom_y, usable_w, bottom_h, spacing,
                                      min(bottom_count, 4)))
    if left_count > 0:
        cells.extend(_make_grid_cells(left_count, margin, center_y, left_w, center_h, spacing,
                                      1 if left_count <= 2 else 2))
    return LayoutSuggestion(name='Ring Focus', cells=_assign_images(cells[:image_count], image_count))


def _split_blocks_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Two or three adaptive blocks: one large zone and supporting mosaics."""
    if image_count <= 2:
        return _feature_left_layout(settings, image_count)

    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)
    landscape = usable_w >= usable_h

    cells: List[CellRect] = []
    if landscape:
        left_w = usable_w * 0.48
        right_w = usable_w - left_w - spacing
        cells.append(CellRect(float(margin), float(margin), left_w, usable_h))
        remaining = image_count - 1
        top_count = min(2, remaining)
        top_h = usable_h * 0.46
        if top_count > 0:
            cells.extend(_make_grid_cells(top_count, margin + left_w + spacing, margin,
                                          right_w, top_h, spacing, top_count))
            remaining -= top_count
        if remaining > 0:
            bottom_y = float(margin) + top_h + spacing
            bottom_h = usable_h - top_h - spacing
            cells.extend(_make_grid_cells(remaining, margin + left_w + spacing, bottom_y,
                                          right_w, bottom_h, spacing, min(remaining, 3)))
    else:
        top_h = usable_h * 0.44
        bottom_h = usable_h - top_h - spacing
        cells.append(CellRect(float(margin), float(margin), usable_w, top_h))
        remaining = image_count - 1
        left_count = min(2, remaining)
        left_w = usable_w * 0.50
        if left_count > 0:
            cells.extend(_make_grid_cells(left_count, margin, margin + top_h + spacing,
                                          left_w, bottom_h, spacing, 1 if left_count <= 2 else 2))
            remaining -= left_count
        if remaining > 0:
            right_x = float(margin) + left_w + spacing
            right_w = usable_w - left_w - spacing
            cells.extend(_make_grid_cells(remaining, right_x, margin + top_h + spacing,
                                          right_w, bottom_h, spacing, min(remaining, 2)))
    return LayoutSuggestion(name='Split Blocks', cells=_assign_images(cells, image_count))


def _offset_grid_layout(settings: ProjectSettings, image_count: int) -> LayoutSuggestion:
    """Grid-like layout with centered row offsets and mild size variation."""
    if image_count <= 4:
        return _grid_layout(settings, image_count)

    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    cols = 3 if image_count <= 9 else 4
    rows = (image_count + cols - 1) // cols
    row_h = (usable_h - spacing * (rows - 1)) / max(1, rows)
    remaining = image_count
    row_counts: List[int] = []
    for row in range(rows):
        rows_left = rows - row
        min_needed_here = max(1, remaining - (rows_left - 1) * cols)
        preferred = cols - (row % 2)
        row_count = max(min_needed_here, min(preferred, cols, remaining))
        row_counts.append(row_count)
        remaining -= row_count
    cells: List[CellRect] = []
    for row, row_count in enumerate(row_counts):
        row_w = (usable_w - spacing * (row_count - 1))
        cell_w = row_w / row_count
        offset = (usable_w - row_w) / 2.0
        y = float(margin) + row * (row_h + spacing)
        h = row_h * (0.96 if row % 2 else 1.0)
        for col in range(row_count):
            x = float(margin) + offset + col * (cell_w + spacing)
            w = cell_w * (1.04 if (row + col) % 3 == 0 else 0.98)
            if col == row_count - 1:
                w = float(margin) + usable_w - x
            cells.append(CellRect(x, y, max(1.0, w), h))
    return LayoutSuggestion(name='Offset Grid', cells=_assign_images(cells[:image_count], image_count))


# ---------------------------------------------------------------------------
# Custom grid (user-specified columns)
# ---------------------------------------------------------------------------

def custom_grid_layout(
    settings: ProjectSettings,
    image_count: int,
    cols: int,
    rows: int = 0,
) -> LayoutSuggestion:
    """Grid with user-specified columns (and optional rows).

    When rows > 0 the cells are distributed across exactly that many rows,
    leaving any overflow cells empty.  When rows == 0 rows are computed
    automatically to fit all images.
    """
    cols = max(1, cols)
    width, height = settings.canvas_px
    margin = settings.margin_px
    spacing = settings.spacing_px
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)

    if rows > 0:
        # Build a fixed rows×cols grid; fill as many cells as we have images
        rows = max(1, rows)
        cell_w = (usable_w - spacing * (cols - 1)) / max(1, cols)
        cell_h = (usable_h - spacing * (rows - 1)) / max(1, rows)
        cells: List[CellRect] = []
        for r in range(rows):
            for c in range(cols):
                cells.append(CellRect(
                    x=float(margin) + c * (cell_w + spacing),
                    y=float(margin) + r * (cell_h + spacing),
                    w=cell_w,
                    h=cell_h,
                ))
        # Assign images in order, leave remaining cells empty
        for idx, cell in enumerate(cells):
            cell.image_index = idx if idx < image_count else None
        # Trim to a count that satisfies the engine's assertion:
        # keep only as many cells as there are images (last cells may be empty)
        # We need exactly image_count cells with assigned indices.
        # Instead we pad with None cells up to image_count if capacity < image_count
        filled = [c for c in cells if c.image_index is not None]
        empty_needed = image_count - len(filled)
        if empty_needed > 0:
            # Not enough cells — add extra row
            extra_row_y = float(margin) + rows * (cell_h + spacing)
            extra = _make_grid_cells(empty_needed, margin, extra_row_y,
                                     usable_w, cell_h, spacing, min(empty_needed, cols))
            for idx, c in enumerate(extra):
                c.image_index = len(filled) + idx
            cells = cells + extra
        # Ensure exactly image_count assigned cells
        result_cells = [c for c in cells if c.image_index is not None and c.image_index < image_count]
        name = f'Custom {cols}×{rows}'
    else:
        result_cells = _make_grid_cells(image_count, margin, margin,
                                        usable_w, usable_h, spacing, cols)
        _assign_images(result_cells, image_count)
        name = f'Custom {cols}×'

    return LayoutSuggestion(name=name, cells=result_cells)


# ---------------------------------------------------------------------------
# Spotify code layouts
# ---------------------------------------------------------------------------

def _spotify_image_index(images: Optional[List[ImageState]]) -> Optional[int]:
    if not images:
        return None
    for idx, state in enumerate(images):
        if getattr(state, 'asset_type', 'photo') == 'spotify_code':
            return idx
    code_state = detect_spotify_code_image(images)
    if code_state is None:
        return None
    for idx, state in enumerate(images):
        if state is code_state:
            state.asset_type = 'spotify_code'
            return idx
    return None


def _spotify_code_cell(x: float, y: float, w: float, h: float, image_index: int) -> CellRect:
    cell = CellRect(x, y, max(1.0, w), max(1.0, h), image_index=image_index)
    cell.id = 'spotify_code'
    cell.slot_type = 'spotify_code'
    cell.asset_type = 'spotify_code'
    cell.fit_mode = 'contain'
    cell.locked = True
    cell.aspect_ratio = max(1.0, w / max(1.0, h))
    return cell


def _assign_spotify_photo_cells(cells: List[CellRect], image_count: int, spotify_idx: int) -> None:
    photo_indices = [idx for idx in range(image_count) if idx != spotify_idx]
    for cell, image_idx in zip(cells, photo_indices):
        cell.image_index = image_idx


def create_spotify_bottom_layout(
    settings: ProjectSettings,
    image_count: int,
    images: Optional[List[ImageState]] = None,
) -> LayoutSuggestion:
    """Photo collage with a scan-safe Spotify code strip at the bottom."""
    width, height = settings.canvas_px
    margin = float(settings.margin_px)
    spacing = float(settings.spacing_px)
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)
    spotify_idx = _spotify_image_index(images)
    if spotify_idx is None:
        spotify_idx = max(0, image_count - 1)
    photo_count = max(0, image_count - 1)

    code_h = min(usable_h * 0.20, max(1.0, usable_w / 4.2))
    code_w = min(usable_w, max(usable_w * 0.58, code_h * 4.4))
    code_x = margin + (usable_w - code_w) / 2.0
    code_y = margin + usable_h - code_h

    cells: List[CellRect] = []
    if photo_count:
        top_h = max(1.0, usable_h - code_h - spacing)
        photo_cells = _make_grid_cells(
            photo_count,
            margin,
            margin,
            usable_w,
            top_h,
            spacing,
            3 if photo_count <= 9 else 4,
        )
        _assign_spotify_photo_cells(photo_cells, image_count, spotify_idx)
        cells.extend(photo_cells)

    cells.append(_spotify_code_cell(code_x, code_y, code_w, code_h, spotify_idx))
    return LayoutSuggestion(name='Spotify Bottom', cells=cells)


def create_spotify_center_layout(
    settings: ProjectSettings,
    image_count: int,
    images: Optional[List[ImageState]] = None,
) -> LayoutSuggestion:
    """Photo collage split around a centered scan-safe Spotify code strip."""
    width, height = settings.canvas_px
    margin = float(settings.margin_px)
    spacing = float(settings.spacing_px)
    usable_w = float(width - 2 * margin)
    usable_h = float(height - 2 * margin)
    spotify_idx = _spotify_image_index(images)
    if spotify_idx is None:
        spotify_idx = max(0, image_count - 1)
    photo_count = max(0, image_count - 1)

    code_h = min(usable_h * 0.16, max(1.0, usable_w / 4.8))
    code_w = min(usable_w * 0.76, max(usable_w * 0.52, code_h * 4.4))
    code_x = margin + (usable_w - code_w) / 2.0
    code_y = margin + (usable_h - code_h) / 2.0

    cells: List[CellRect] = []
    if photo_count:
        top_count = (photo_count + 1) // 2
        bottom_count = photo_count - top_count
        top_h = max(1.0, code_y - margin - spacing)
        bottom_y = code_y + code_h + spacing
        bottom_h = max(1.0, margin + usable_h - bottom_y)
        top_cells = _make_grid_cells(top_count, margin, margin, usable_w, top_h, spacing, min(top_count, 4))
        bottom_cells = _make_grid_cells(bottom_count, margin, bottom_y, usable_w, bottom_h, spacing, min(bottom_count, 4))
        photo_cells = top_cells + bottom_cells
        _assign_spotify_photo_cells(photo_cells, image_count, spotify_idx)
        cells.extend(photo_cells)

    cells.append(_spotify_code_cell(code_x, code_y, code_w, code_h, spotify_idx))
    return LayoutSuggestion(name='Spotify Center', cells=cells)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_suggestions(
    settings: ProjectSettings,
    image_count: int,
    images: Optional[List[ImageState]] = None,
    custom_cols: int = 0,
) -> List[LayoutSuggestion]:
    """Return layout suggestions sorted by score (best first) when images are provided.

    Every returned layout contains exactly `image_count` cells and all cells
    are within the canvas bounds.
    """
    if image_count <= 0:
        return []

    candidates = [
        _grid_layout(settings, image_count),
        _hero_top_layout(settings, image_count),
        _hero_bottom_layout(settings, image_count),
        _feature_left_layout(settings, image_count),
        _mosaic_layout(settings, image_count),
        _mosaic_spotlight_layout(settings, image_count),
        _film_strip_mix_layout(settings, image_count),
        _staircase_layout(settings, image_count),
        _ring_focus_layout(settings, image_count),
        _split_blocks_layout(settings, image_count),
        _offset_grid_layout(settings, image_count),
        _strip_layout(settings, image_count),
        _magazine_layout(settings, image_count),
        _dual_hero_layout(settings, image_count),
        _triptych_layout(settings, image_count),
        _cascade_layout(settings, image_count),
        _wide_banner_layout(settings, image_count),
        _torn_paper_collage_layout(settings, image_count),
        _circle_ring_collage_layout(settings, image_count),
    ]

    spotify_idx = _spotify_image_index(images)
    if spotify_idx is not None:
        candidates.extend([
            create_spotify_bottom_layout(settings, image_count, images),
            create_spotify_center_layout(settings, image_count, images),
        ])

    # Diagonal / editorial layouts (best for 2–6 images)
    candidates.extend(get_diagonal_layouts(settings, image_count))

    if custom_cols > 0:
        candidates.append(custom_grid_layout(settings, image_count, custom_cols))

    # Remove layouts that collapsed to identical structures
    seen: set[tuple] = set()
    unique: List[LayoutSuggestion] = []
    for layout in candidates:
        key = (layout.name, tuple((round(c.x), round(c.y), round(c.w), round(c.h)) for c in layout.cells))
        if key not in seen:
            seen.add(key)
            unique.append(layout)

    # Verify all layouts contain exactly image_count cells
    for layout in unique:
        assert len(layout.cells) == image_count, (
            f'{layout.name} has {len(layout.cells)} cells for {image_count} images'
        )

    _SKIP_OPTIMIZE = {
        'torn_paper_collage', 'circle_ring_collage',
        'Spotify Bottom', 'Spotify Center',
        'Diagonal Split Left', 'Diagonal Split Right',
        'Diagonal Bands Left', 'Diagonal Bands Right',
        'Diagonal Hero Left', 'Diagonal Hero Right',
        'Hybrid Diagonal Top Left', 'Hybrid Diagonal Top Right',
        'Hybrid Hero Diagonal',
        'Geometric Triangle Split Left', 'Geometric Triangle Split Right',
        'Geometric Hero Bottom', 'Geometric Center Diamond',
        'Geometric Diagonal Mosaic',
    }
    if images:
        for layout in unique:
            if layout.name not in _SKIP_OPTIMIZE:
                _optimize_layout_assignments(layout, images)
            layout.score = _score_layout(layout, images)
        unique.sort(key=lambda s: s.score, reverse=True)

    return unique
