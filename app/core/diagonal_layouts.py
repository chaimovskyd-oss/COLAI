"""app/core/diagonal_layouts.py — Diagonal & dynamic collage layout generators.

Divides the canvas into polygonal cells (parallelograms, trapezoids) using
diagonal cut lines.  The result feels editorial/magazine without sacrificing
image clarity — cells are large enough to read clearly and the slant is kept
gentle enough to avoid "geometric chaos".

Each cell uses shape_type='diagonal_polygon' with vertices stored as
relative [0..1] coords within the cell's bounding box:

    shape_params = {
        'v_count': 4.0,         # number of vertices (stored as float)
        'v0x': 0.0, 'v0y': 0.0,
        'v1x': 1.0, 'v1y': 0.0,
        ...
    }

This encoding is fully compatible with the existing Dict[str, float]
shape_params field and the JSON project-save pipeline.

Layout families
---------------
1. diagonal_bands_layout   — N vertical parallelogram bands (2–6 images)
2. diagonal_hero_layout    — large hero + supporting column (3–6 images)

Public entry point
------------------
get_diagonal_layouts(settings, image_count) → List[LayoutSuggestion]
"""
from __future__ import annotations

import math
from typing import List, Tuple

from app.models.project import CellRect, LayoutSuggestion, ProjectSettings

Pt = Tuple[float, float]
Poly = List[Pt]

MAX_DIAGONAL_IMAGES = 6   # pure diagonal bands / hero
MAX_HYBRID_IMAGES    = 15  # hybrid diagonal-zone + grid-zone
MAX_GEOMETRIC_IMAGES = 24  # geometric family softens into hybrid grids above 12


# ---------------------------------------------------------------------------
# Polygon helpers
# ---------------------------------------------------------------------------

def _centroid(pts: Poly) -> Pt:
    n = max(1, len(pts))
    return (sum(x for x, y in pts) / n, sum(y for x, y in pts) / n)


def _inset_polygon(pts: Poly, amount: float) -> Poly:
    """Shrink a convex polygon toward its centroid by ~amount pixels.

    Using centroid-direction inset rather than proper parallel-edge inset
    keeps the implementation robust for any convex polygon shape while
    still producing visually uniform gaps at typical spacing values.
    """
    if not pts or amount <= 0:
        return pts
    cx, cy = _centroid(pts)
    result: Poly = []
    for x, y in pts:
        dx, dy = x - cx, y - cy
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            result.append((x, y))
        else:
            shrink = min(amount, dist * 0.4)   # never collapse the polygon
            result.append((x - dx / dist * shrink, y - dy / dist * shrink))
    return result


def _clip_poly_to_rect(
    pts: Poly,
    x0: float, y0: float,
    x1: float, y1: float,
) -> Poly:
    """Clip a convex polygon to an axis-aligned rectangle.

    Uses the Sutherland-Hodgman algorithm.  Returns the clipped polygon
    (may have more vertices than the input due to edge intersections).
    """
    def _lerp(a: Pt, b: Pt, t: float) -> Pt:
        return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))

    def _ix(xc: float, a: Pt, b: Pt) -> Pt:
        denom = b[0] - a[0]
        t = (xc - a[0]) / denom if denom != 0.0 else 0.0
        return _lerp(a, b, t)

    def _iy(yc: float, a: Pt, b: Pt) -> Pt:
        denom = b[1] - a[1]
        t = (yc - a[1]) / denom if denom != 0.0 else 0.0
        return _lerp(a, b, t)

    def _clip_half(pts: Poly, inside, intersect) -> Poly:
        if not pts:
            return []
        out: Poly = []
        prev = pts[-1]
        for curr in pts:
            prev_in = inside(prev)
            curr_in = inside(curr)
            if curr_in:
                if not prev_in:
                    out.append(intersect(prev, curr))
                out.append(curr)
            elif prev_in:
                out.append(intersect(prev, curr))
            prev = curr
        return out

    pts = _clip_half(pts, lambda p: p[0] >= x0, lambda a, b: _ix(x0, a, b))
    pts = _clip_half(pts, lambda p: p[0] <= x1, lambda a, b: _ix(x1, a, b))
    pts = _clip_half(pts, lambda p: p[1] >= y0, lambda a, b: _iy(y0, a, b))
    pts = _clip_half(pts, lambda p: p[1] <= y1, lambda a, b: _iy(y1, a, b))
    return pts


def _poly_to_cell(pts: Poly) -> CellRect:
    """Convert canvas-absolute polygon vertices to a CellRect.

    The cell's x,y,w,h is the minimal bounding box.  Polygon vertices are
    stored as relative [0..1] coords inside that bounding box so the image
    cropper can still compute a meaningful aspect ratio from w/h.
    """
    if len(pts) < 3:
        x = pts[0][0] if pts else 0.0
        y = pts[0][1] if pts else 0.0
        cell = CellRect(x, y, 1.0, 1.0)
        return cell

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    bx, by = min(xs), min(ys)
    bw = max(max(xs) - bx, 1.0)
    bh = max(max(ys) - by, 1.0)

    params: dict = {'v_count': float(len(pts))}
    for i, (px, py) in enumerate(pts):
        params[f'v{i}x'] = round((px - bx) / bw, 6)
        params[f'v{i}y'] = round((py - by) / bh, 6)

    cell = CellRect(bx, by, bw, bh)
    cell.shape_type = 'diagonal_polygon'
    cell.shape_params = params
    return cell


def _canvas_bounds(settings: ProjectSettings) -> Tuple[float, float, float, float]:
    """Return (x0, y0, x1, y1) of the usable canvas area (inside margins)."""
    W, H = settings.canvas_px
    m = float(settings.margin_px)
    return m, m, float(W) - m, float(H) - m


def _fallback_cell(settings: ProjectSettings, idx: int) -> CellRect:
    x0, y0, x1, y1 = _canvas_bounds(settings)
    return CellRect(x0, y0, x1 - x0, y1 - y0, image_index=idx)


def _poly_area(pts: Poly) -> float:
    if len(pts) < 3:
        return 0.0
    total = 0.0
    for i, (x0, y0) in enumerate(pts):
        x1, y1 = pts[(i + 1) % len(pts)]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def _is_readable_poly(pts: Poly, settings: ProjectSettings) -> bool:
    """Reject cells that are too small, too narrow, or too needle-like."""
    if len(pts) < 3:
        return False
    x0, y0, x1, y1 = _canvas_bounds(settings)
    cW, cH = x1 - x0, y1 - y0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    bw = max(xs) - min(xs)
    bh = max(ys) - min(ys)
    min_dim = max(42.0, min(cW, cH) * 0.105)
    if bw < min_dim or bh < min_dim:
        return False
    ratio = max(bw / max(1.0, bh), bh / max(1.0, bw))
    if ratio > 4.8:
        return False
    area = _poly_area(pts)
    if area < cW * cH * 0.035:
        return False
    # Broad triangles are valid for the connected geometric templates; reject
    # only needle-like shapes whose visible area is too small for a photo.
    return area / max(1.0, bw * bh) >= 0.28


def _safe_poly_cell(pts: Poly, settings: ProjectSettings, image_index: int) -> CellRect:
    if _is_readable_poly(pts, settings):
        cell = _poly_to_cell(pts)
    else:
        cell = _fallback_cell(settings, image_index)
    cell.image_index = image_index
    return cell


def _geometric_slant(cW: float, image_count: int, strength: str = 'medium') -> float:
    base = {'gentle': 0.055, 'medium': 0.09, 'bold': 0.13}.get(strength, 0.09)
    if image_count >= 13:
        base *= 0.62
    elif image_count >= 9:
        base *= 0.78
    return cW * base


def _lerp_pt(a: Pt, b: Pt, t: float) -> Pt:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _polyline_point(points: Poly, t: float) -> Pt:
    """Return a point at fractional distance along a polyline."""
    if not points:
        return (0.0, 0.0)
    if len(points) == 1:
        return points[0]
    t = max(0.0, min(1.0, t))
    lengths: List[float] = []
    total = 0.0
    for a, b in zip(points, points[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        lengths.append(seg)
        total += seg
    if total <= 1e-6:
        return points[0]
    target = total * t
    walked = 0.0
    for idx, seg in enumerate(lengths):
        if walked + seg >= target:
            local = (target - walked) / max(1e-6, seg)
            return _lerp_pt(points[idx], points[idx + 1], local)
        walked += seg
    return points[-1]


def _split_between_polylines(inner: Poly, outer: Poly, count: int) -> List[Poly]:
    """Create connected strips between two guide polylines."""
    if count <= 0:
        return []
    if count == 1:
        return [list(outer) + list(reversed(inner))]
    strips: List[Poly] = []
    for i in range(count):
        t0 = i / count
        t1 = (i + 1) / count
        strips.append([
            _polyline_point(outer, t0),
            _polyline_point(outer, t1),
            _polyline_point(inner, t1),
            _polyline_point(inner, t0),
        ])
    return strips


def _balanced_counts(total: int, weights: List[float]) -> List[int]:
    """Distribute cells over skeleton regions without forcing tiny leftovers."""
    if total <= 0 or not weights:
        return [0 for _ in weights]
    counts = [0 for _ in weights]
    order = sorted(range(len(weights)), key=lambda i: weights[i], reverse=True)
    for i in range(min(total, len(weights))):
        counts[order[i]] = 1
    remaining = total - sum(counts)
    weight_sum = sum(max(0.01, w) for w in weights)
    fractions: List[Tuple[float, int]] = []
    for idx, w in enumerate(weights):
        exact = remaining * max(0.01, w) / weight_sum
        add = int(math.floor(exact))
        counts[idx] += add
        fractions.append((exact - add, idx))
    while sum(counts) < total:
        _, idx = max(fractions)
        counts[idx] += 1
        fractions = [(f - 1.0 if i == idx else f, i) for f, i in fractions]
    return counts


def _append_polys_as_cells(
    cells: List[CellRect],
    polys: List[Poly],
    settings: ProjectSettings,
    start_index: int,
) -> int:
    """Clip, inset, validate, and append polygon cells. Returns next image index."""
    x0, y0, x1, y1 = _canvas_bounds(settings)
    spacing = float(settings.spacing_px)
    image_index = start_index
    for poly in polys:
        clipped = _clip_poly_to_rect(poly, x0, y0, x1, y1)
        if len(clipped) >= 3:
            clipped = _inset_polygon(clipped, spacing / 2.0)
        cells.append(_safe_poly_cell(clipped, settings, image_index))
        image_index += 1
    return image_index


# ---------------------------------------------------------------------------
# Layout 1 — Diagonal Bands
# ---------------------------------------------------------------------------

def diagonal_bands_layout(
    settings: ProjectSettings,
    image_count: int,
    slant_factor: float = 0.13,
    right_leaning: bool = True,
) -> LayoutSuggestion:
    """N vertical parallelogram bands separated by diagonal dividing lines.

    The slant is centred on the canvas so that both the leftmost and
    rightmost bands get symmetric triangular clipping at the corners,
    giving the full set of bands a consistent leaning feel.

    slant_factor : slant as a fraction of canvas width
                   0.08 = gentle, 0.13 = moderate, 0.20 = bold
    right_leaning: True  → bands lean right (top-left→bottom-right)
                   False → bands lean left
    """
    base = 'Diagonal Split' if image_count == 2 else 'Diagonal Bands'
    direction = 'Right' if right_leaning else 'Left'
    name = f'{base} {direction}'
    if image_count <= 0:
        return LayoutSuggestion(name=name, cells=[])

    x0, y0, x1, y1 = _canvas_bounds(settings)
    cW, cH = x1 - x0, y1 - y0
    spacing = float(settings.spacing_px)
    n = image_count

    sign = 1.0 if right_leaning else -1.0
    slant = slant_factor * cW * sign
    half = slant / 2.0

    cells: List[CellRect] = []
    for i in range(n):
        tl = i / n
        tr = (i + 1) / n

        # Centre the lean: top points shift left by half, bottom shift right by half
        top_lx = x0 + tl * cW - half
        top_rx = x0 + tr * cW - half
        bot_lx = x0 + tl * cW + half
        bot_rx = x0 + tr * cW + half

        poly: Poly = [(top_lx, y0), (top_rx, y0), (bot_rx, y1), (bot_lx, y1)]
        poly = _clip_poly_to_rect(poly, x0, y0, x1, y1)
        if len(poly) >= 3:
            poly = _inset_polygon(poly, spacing / 2.0)
        if len(poly) < 3:
            cells.append(_fallback_cell(settings, i))
            continue

        cell = _poly_to_cell(poly)
        cell.image_index = i
        cells.append(cell)

    # Guarantee exactly image_count cells (safety guard for degenerate inputs)
    while len(cells) < image_count:
        cells.append(_fallback_cell(settings, len(cells)))
    return LayoutSuggestion(name=name, cells=cells[:image_count])


# ---------------------------------------------------------------------------
# Layout 2 — Diagonal Hero
# ---------------------------------------------------------------------------

def diagonal_hero_layout(
    settings: ProjectSettings,
    image_count: int,
    hero_side: str = 'left',
    slant_factor: float = 0.12,
) -> LayoutSuggestion:
    """Large hero cell with a diagonal edge; supporting cells in a side column.

    The hero occupies ~58 % of the canvas width.  Its shared edge with the
    column is a single diagonal line (not per-row), so adjacent cells
    appear to form a coherent diagonal composition.

    hero_side   : 'left' → hero on left, column on right (and vice versa)
    slant_factor: diagonal intensity as fraction of canvas width
    """
    side_label = 'Left' if hero_side == 'left' else 'Right'
    name = f'Diagonal Hero {side_label}'

    x0, y0, x1, y1 = _canvas_bounds(settings)
    cW, cH = x1 - x0, y1 - y0
    spacing = float(settings.spacing_px)

    if image_count <= 1:
        c = CellRect(x0, y0, cW, cH, image_index=0)
        return LayoutSuggestion(name=name, cells=[c])

    hero_frac = 0.58
    slant = slant_factor * cW
    n_col = image_count - 1

    cells: List[CellRect] = []

    if hero_side == 'left':
        # Diagonal goes from split_top (at top edge) to split_bot (at bottom edge),
        # where split_bot = split_top + slant (leans right).
        split_top = x0 + cW * hero_frac
        split_bot = split_top + slant

        # Hero: trapezoid filling left portion
        hero_poly: Poly = [
            (x0,        y0),
            (split_top, y0),
            (split_bot, y1),
            (x0,        y1),
        ]
        hero_poly = _clip_poly_to_rect(hero_poly, x0, y0, x1, y1)
        hero_poly = _inset_polygon(hero_poly, spacing / 2.0)
        hero_cell = _poly_to_cell(hero_poly)
        hero_cell.image_index = 0
        cells.append(hero_cell)

        # Right column: n_col cells stacked vertically, each a parallelogram
        # whose left edge follows the same diagonal as the hero's right edge.
        for j in range(n_col):
            t0 = j / n_col
            t1 = (j + 1) / n_col
            ry0 = y0 + t0 * cH
            ry1 = y0 + t1 * cH

            # Left edge of this cell interpolates along the hero diagonal
            rxl0 = split_top + t0 * slant + spacing
            rxl1 = split_top + t1 * slant + spacing

            poly: Poly = [
                (rxl0, ry0),
                (x1,   ry0),
                (x1,   ry1),
                (rxl1, ry1),
            ]
            poly = _clip_poly_to_rect(poly, x0, y0, x1, y1)
            if len(poly) >= 3:
                poly = _inset_polygon(poly, spacing / 2.0)
            if len(poly) < 3:
                cells.append(_fallback_cell(settings, j + 1))
                continue
            cell = _poly_to_cell(poly)
            cell.image_index = j + 1
            cells.append(cell)

    else:  # hero on right
        # Diagonal leans left: top of the split is at the right, bottom shifts left
        split_top = x0 + cW * (1.0 - hero_frac)
        split_bot = split_top - slant   # leans left → bottom is further left

        # Hero: right-side trapezoid
        hero_poly = [
            (split_top, y0),
            (x1,        y0),
            (x1,        y1),
            (split_bot, y1),
        ]
        hero_poly = _clip_poly_to_rect(hero_poly, x0, y0, x1, y1)
        hero_poly = _inset_polygon(hero_poly, spacing / 2.0)
        hero_cell = _poly_to_cell(hero_poly)
        hero_cell.image_index = 0
        cells.append(hero_cell)

        # Left column
        for j in range(n_col):
            t0 = j / n_col
            t1 = (j + 1) / n_col
            ry0 = y0 + t0 * cH
            ry1 = y0 + t1 * cH

            # Right edge follows the hero diagonal (leans left)
            rxr0 = split_top - t0 * slant - spacing
            rxr1 = split_top - t1 * slant - spacing

            poly = [
                (x0,   ry0),
                (rxr0, ry0),
                (rxr1, ry1),
                (x0,   ry1),
            ]
            poly = _clip_poly_to_rect(poly, x0, y0, x1, y1)
            if len(poly) >= 3:
                poly = _inset_polygon(poly, spacing / 2.0)
            if len(poly) < 3:
                cells.append(_fallback_cell(settings, j + 1))
                continue
            cell = _poly_to_cell(poly)
            cell.image_index = j + 1
            cells.append(cell)

    while len(cells) < image_count:
        cells.append(_fallback_cell(settings, len(cells)))
    return LayoutSuggestion(name=name, cells=cells[:image_count])


# ---------------------------------------------------------------------------
# Layout 3 — Hybrid: diagonal accent zone + rectangular grid zone
# ---------------------------------------------------------------------------

def _simple_grid_cells(
    x0: float, y0: float,
    w: float, h: float,
    count: int,
    spacing: float,
    max_cols: int = 5,
) -> List[CellRect]:
    """Uniform grid of `count` rectangular CellRects inside a bounding box.

    The last row is stretched to fill the full width so there are no
    trailing gaps — mirrors the behaviour of the engine's _make_grid_cells.
    """
    if count <= 0:
        return []
    cols = min(count, max_cols)
    rows = math.ceil(count / cols)
    cw = (w - spacing * (cols - 1)) / max(1, cols)
    ch = (h - spacing * (rows - 1)) / max(1, rows)
    cells: List[CellRect] = []
    for i in range(count):
        row, col = divmod(i, cols)
        row_start = row * cols
        row_count = min(cols, count - row_start)
        if row_count < cols:                       # last partial row → stretch
            this_w = (w - spacing * (row_count - 1)) / row_count
            this_x = x0 + (i - row_start) * (this_w + spacing)
        else:
            this_w = cw
            this_x = x0 + col * (cw + spacing)
        this_y = y0 + row * (ch + spacing)
        cells.append(CellRect(this_x, this_y, max(1.0, this_w), max(1.0, ch)))
    return cells


def _auto_n_diag(image_count: int) -> int:
    """How many cells to put in the diagonal accent zone for a hybrid layout."""
    return max(2, min(5, round(image_count * 0.33)))


def hybrid_top_diagonal_layout(
    settings: ProjectSettings,
    image_count: int,
    right_leaning: bool = True,
) -> LayoutSuggestion:
    """Top zone: N diagonal parallelogram bands. Bottom zone: standard grid.

    The diagonal accent occupies the top ~38–50 % of the canvas (scaled with
    the number of diagonal cells).  The remaining images fill a clean uniform
    grid below, separated by a full-width spacing gap.

    Works well for 4–15 images.
    """
    direction = 'Right' if right_leaning else 'Left'
    name = f'Hybrid Diagonal Top {direction}'

    x0, y0, x1, y1 = _canvas_bounds(settings)
    cW, cH = x1 - x0, y1 - y0
    spacing = float(settings.spacing_px)

    n_diag = _auto_n_diag(image_count)
    n_grid = image_count - n_diag
    # Top zone height grows slightly with more diagonal cells
    diag_frac = 0.30 + n_diag * 0.04   # 0.38 (n=2) … 0.50 (n=5)
    split_y   = y0 + cH * diag_frac
    grid_y0   = split_y + spacing

    sign  = 1.0 if right_leaning else -1.0
    slant = 0.13 * cW * sign
    half  = slant / 2.0

    cells: List[CellRect] = []

    # ── Diagonal accent zone (top) ─────────────────────────────────────────
    for i in range(n_diag):
        tl = i / n_diag
        tr = (i + 1) / n_diag
        top_lx = x0 + tl * cW - half
        top_rx = x0 + tr * cW - half
        bot_lx = x0 + tl * cW + half
        bot_rx = x0 + tr * cW + half

        poly: Poly = [(top_lx, y0), (top_rx, y0), (bot_rx, split_y), (bot_lx, split_y)]
        poly = _clip_poly_to_rect(poly, x0, y0, x1, split_y)
        if len(poly) >= 3:
            poly = _inset_polygon(poly, spacing / 2.0)
        if len(poly) < 3:
            cells.append(_fallback_cell(settings, i))
            continue
        cell = _poly_to_cell(poly)
        cell.image_index = i
        cells.append(cell)

    # ── Grid zone (bottom) ─────────────────────────────────────────────────
    grid_cells = _simple_grid_cells(
        x0, grid_y0, cW, y1 - grid_y0, n_grid, spacing,
        max_cols=min(n_grid, 5),
    )
    for j, c in enumerate(grid_cells):
        c.image_index = n_diag + j
    cells.extend(grid_cells)

    while len(cells) < image_count:
        cells.append(_fallback_cell(settings, len(cells)))
    return LayoutSuggestion(name=name, cells=cells[:image_count])


def hybrid_hero_diagonal_layout(
    settings: ProjectSettings,
    image_count: int,
) -> LayoutSuggestion:
    """Left: large diagonal-edged hero. Right: clean grid of remaining images.

    A single large editorial statement (diagonal trapezoid) anchors the left
    ~40 % of the canvas while a uniform grid efficiently fills the right side.
    Works well for 5–12 images.
    """
    name = 'Hybrid Hero Diagonal'

    x0, y0, x1, y1 = _canvas_bounds(settings)
    cW, cH = x1 - x0, y1 - y0
    spacing = float(settings.spacing_px)

    hero_frac = 0.40
    slant     = 0.10 * cW
    split_top = x0 + cW * hero_frac
    split_bot = split_top + slant

    # Hero: full-height trapezoid with diagonal right edge
    hero_poly: Poly = [(x0, y0), (split_top, y0), (split_bot, y1), (x0, y1)]
    hero_poly = _clip_poly_to_rect(hero_poly, x0, y0, x1, y1)
    hero_poly = _inset_polygon(hero_poly, spacing / 2.0)
    hero_cell = _poly_to_cell(hero_poly)
    hero_cell.image_index = 0

    # Right side: uniform grid for the remaining images
    n_right   = image_count - 1
    right_x0  = split_top + spacing
    right_w   = x1 - right_x0
    right_cells = _simple_grid_cells(
        right_x0, y0, right_w, cH, n_right, spacing,
        max_cols=min(n_right, 3),
    )
    for j, c in enumerate(right_cells):
        c.image_index = j + 1

    cells = [hero_cell] + right_cells
    while len(cells) < image_count:
        cells.append(_fallback_cell(settings, len(cells)))
    return LayoutSuggestion(name=name, cells=cells[:image_count])


# ---------------------------------------------------------------------------
# Geometric / diagonal template family
# ---------------------------------------------------------------------------

def geometric_triangle_split_layout(
    settings: ProjectSettings,
    image_count: int,
    strength: str = 'medium',
    hero_side: str = 'left',
) -> LayoutSuggestion:
    """Triangle split made from one shared diagonal guide line."""
    side_label = 'Left' if hero_side == 'left' else 'Right'
    name = f'Geometric Triangle Split {side_label}'
    x0, y0, x1, y1 = _canvas_bounds(settings)
    cW, cH = x1 - x0, y1 - y0
    spacing = float(settings.spacing_px)
    slant = _geometric_slant(cW, image_count, strength)

    if image_count <= 1:
        return LayoutSuggestion(name=name, cells=[_fallback_cell(settings, 0)])

    hero_frac = 0.66 if image_count <= 4 else 0.58 if image_count <= 8 else 0.50
    split_top = x0 + cW * hero_frac
    split_bot = split_top + slant
    if hero_side == 'right':
        split_top = x1 - cW * hero_frac
        split_bot = split_top - slant

    cells: List[CellRect] = []
    if hero_side == 'left':
        hero = [(x0, y0), (split_top, y0), (split_bot, y1), (x0, y1)]
        guide = [(split_top, y0), (split_bot, y1)]
        outside = [(x1, y0), (x1, y1)]
    else:
        hero = [(split_top, y0), (x1, y0), (x1, y1), (split_bot, y1)]
        guide = [(split_top, y0), (split_bot, y1)]
        outside = [(x0, y0), (x0, y1)]

    hero = _clip_poly_to_rect(hero, x0, y0, x1, y1)
    hero = _inset_polygon(hero, spacing / 2.0)
    cells.append(_safe_poly_cell(hero, settings, 0))

    remaining = image_count - 1
    if remaining <= 0:
        return LayoutSuggestion(name=name, cells=cells[:image_count])

    support_polys = _split_between_polylines(guide, outside, remaining)
    _append_polys_as_cells(cells, support_polys, settings, 1)

    while len(cells) < image_count:
        cells.append(_fallback_cell(settings, len(cells)))
    return LayoutSuggestion(name=name, cells=cells[:image_count])


def hero_geometric_bottom_layout(
    settings: ProjectSettings,
    image_count: int,
    strength: str = 'medium',
) -> LayoutSuggestion:
    """Dominant hero with lower cells split from the same diagonal baseline."""
    name = 'Geometric Hero Bottom'
    x0, y0, x1, y1 = _canvas_bounds(settings)
    cW, cH = x1 - x0, y1 - y0
    spacing = float(settings.spacing_px)
    slant = _geometric_slant(cW, image_count, strength)

    if image_count <= 1:
        return LayoutSuggestion(name=name, cells=[_fallback_cell(settings, 0)])

    hero_frac = 0.64 if image_count <= 4 else 0.56 if image_count <= 8 else 0.48
    split_y = y0 + cH * hero_frac
    peak_x = x0 + cW * (0.42 if image_count % 2 else 0.58)
    hero_poly: Poly = [
        (x0, y0),
        (x1, y0),
        (x1, split_y - slant * 0.32),
        (peak_x, split_y + slant * 0.34),
        (x0, split_y - slant * 0.10),
    ]
    hero_poly = _clip_poly_to_rect(hero_poly, x0, y0, x1, y1)
    hero_poly = _inset_polygon(hero_poly, spacing / 2.0)
    cells = [_safe_poly_cell(hero_poly, settings, 0)]

    remaining = image_count - 1
    if remaining <= 0:
        return LayoutSuggestion(name=name, cells=cells[:image_count])

    lower_top: Poly = [
        (x0, split_y - slant * 0.10),
        (peak_x, split_y + slant * 0.34),
        (x1, split_y - slant * 0.32),
    ]
    if remaining <= 6:
        lower_bottom: Poly = [(x0, y1), (x1, y1)]
        polys = _split_between_polylines(lower_top, lower_bottom, remaining)
        _append_polys_as_cells(cells, polys, settings, 1)
    else:
        first_count = max(3, min(5, remaining // 2))
        second_count = remaining - first_count
        mid_y = split_y + (y1 - split_y) * 0.53
        mid_line: Poly = [
            (x0, mid_y + slant * 0.24),
            (peak_x, mid_y - slant * 0.18),
            (x1, mid_y + slant * 0.10),
        ]
        first = _split_between_polylines(lower_top, mid_line, first_count)
        next_idx = _append_polys_as_cells(cells, first, settings, 1)
        second = _split_between_polylines(mid_line, [(x0, y1), (x1, y1)], second_count)
        _append_polys_as_cells(cells, second, settings, next_idx)

    while len(cells) < image_count:
        cells.append(_fallback_cell(settings, len(cells)))
    return LayoutSuggestion(name=name, cells=cells[:image_count])


def center_diamond_layout(
    settings: ProjectSettings,
    image_count: int,
    strength: str = 'medium',
) -> LayoutSuggestion:
    """Central diamond whose four diagonals continue into all surrounding cells."""
    name = 'Geometric Center Diamond'
    x0, y0, x1, y1 = _canvas_bounds(settings)
    cW, cH = x1 - x0, y1 - y0
    spacing = float(settings.spacing_px)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0

    if image_count <= 1:
        return LayoutSuggestion(name=name, cells=[_fallback_cell(settings, 0)])

    diamond_w = cW * (0.48 if image_count <= 5 else 0.42 if image_count <= 10 else 0.36)
    diamond_h = cH * (0.48 if image_count <= 5 else 0.42 if image_count <= 10 else 0.36)
    top = (cx, cy - diamond_h / 2.0)
    right = (cx + diamond_w / 2.0, cy)
    bottom = (cx, cy + diamond_h / 2.0)
    left = (cx - diamond_w / 2.0, cy)
    diamond: Poly = [
        top,
        right,
        bottom,
        left,
    ]
    diamond = _inset_polygon(diamond, spacing / 2.0)
    cells = [_safe_poly_cell(diamond, settings, 0)]

    remaining = image_count - 1
    regions: List[Tuple[Poly, Poly, float]] = [
        ([(left[0], left[1]), (top[0], top[1])], [(x0, cy), (x0, y0), (cx, y0)], 1.05),
        ([(top[0], top[1]), (right[0], right[1])], [(cx, y0), (x1, y0), (x1, cy)], 1.05),
        ([(right[0], right[1]), (bottom[0], bottom[1])], [(x1, cy), (x1, y1), (cx, y1)], 1.05),
        ([(bottom[0], bottom[1]), (left[0], left[1])], [(cx, y1), (x0, y1), (x0, cy)], 1.05),
    ]
    counts = _balanced_counts(remaining, [weight for _, _, weight in regions])
    image_index = 1
    for (inner, outer, _), count in zip(regions, counts):
        if count <= 0:
            continue
        polys = _split_between_polylines(inner, outer, count)
        image_index = _append_polys_as_cells(cells, polys, settings, image_index)

    while len(cells) < image_count:
        cells.append(_fallback_cell(settings, len(cells)))
    return LayoutSuggestion(name=name, cells=cells[:image_count])


def asymmetric_diagonal_mosaic_layout(
    settings: ProjectSettings,
    image_count: int,
    strength: str = 'medium',
) -> LayoutSuggestion:
    """Asymmetric mosaic generated from a small set of shared diagonal guides."""
    name = 'Geometric Diagonal Mosaic'
    x0, y0, x1, y1 = _canvas_bounds(settings)
    cW, cH = x1 - x0, y1 - y0
    spacing = float(settings.spacing_px)
    slant = _geometric_slant(cW, image_count, strength)

    if image_count <= 1:
        return LayoutSuggestion(name=name, cells=[_fallback_cell(settings, 0)])

    cells: List[CellRect] = []
    hero_w = cW * (0.58 if image_count <= 4 else 0.48 if image_count <= 8 else 0.42)
    top_h = cH * (0.62 if image_count <= 7 else 0.52)
    joint = (x0 + hero_w + slant * 0.55, y0 + top_h)
    hero_poly = [
        (x0, y0),
        (x0 + hero_w, y0),
        joint,
        (x0, y0 + top_h - slant * 0.25),
    ]
    hero_poly = _clip_poly_to_rect(hero_poly, x0, y0, x1, y1)
    hero_poly = _inset_polygon(hero_poly, spacing / 2.0)
    cells.append(_safe_poly_cell(hero_poly, settings, 0))

    remaining = image_count - 1
    if remaining <= 0:
        return LayoutSuggestion(name=name, cells=cells[:image_count])

    if remaining <= 4:
        regions = [
            ([(x0 + hero_w, y0), joint], [(x1, y0), (x1, y0 + top_h * 0.58)], 1.0),
            ([joint, (x0, y0 + top_h - slant * 0.25)], [(x1, y1), (x0, y1)], 1.25),
        ]
        counts = _balanced_counts(remaining, [w for _, _, w in regions])
        image_index = 1
        for (inner, outer, _), count in zip(regions, counts):
            image_index = _append_polys_as_cells(
                cells,
                _split_between_polylines(inner, outer, count),
                settings,
                image_index,
            )
    else:
        right_count = min(4, max(2, remaining // 3))
        bottom_count = remaining - right_count
        right_inner: Poly = [(x0 + hero_w, y0), joint]
        right_outer: Poly = [(x1, y0), (x1, y0 + top_h * 0.62), (x1 - slant * 0.25, top_h + y0)]
        next_idx = _append_polys_as_cells(
            cells,
            _split_between_polylines(right_inner, right_outer, right_count),
            settings,
            1,
        )
        if bottom_count > 0:
            bottom_inner: Poly = [(x0, y0 + top_h - slant * 0.25), joint, (x1 - slant * 0.25, y0 + top_h)]
            if bottom_count <= 5:
                bottom_outer: Poly = [(x0, y1), (x1, y1)]
                bottom_polys = _split_between_polylines(bottom_inner, bottom_outer, bottom_count)
                _append_polys_as_cells(cells, bottom_polys, settings, next_idx)
            else:
                first_count = 4
                second_count = bottom_count - first_count
                mid_y = y0 + top_h + (y1 - y0 - top_h) * 0.50
                mid: Poly = [(x0, mid_y + slant * 0.15), (x1, mid_y - slant * 0.12)]
                next_idx = _append_polys_as_cells(
                    cells,
                    _split_between_polylines(bottom_inner, mid, first_count),
                    settings,
                    next_idx,
                )
                _append_polys_as_cells(
                    cells,
                    _split_between_polylines(mid, [(x0, y1), (x1, y1)], second_count),
                    settings,
                    next_idx,
                )

    while len(cells) < image_count:
        cells.append(_fallback_cell(settings, len(cells)))
    return LayoutSuggestion(name=name, cells=cells[:image_count])


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_diagonal_layouts(
    settings: ProjectSettings,
    image_count: int,
) -> List[LayoutSuggestion]:
    """Return all applicable diagonal/hybrid layout candidates.

    Pure diagonal (2–6 images):
      • Diagonal Bands/Split Right & Left
      • Diagonal Hero Left & Right

    Hybrid diagonal-zone + grid (4–15 images):
      • Hybrid Diagonal Top Right & Left  (diagonal accent row + grid below)
      • Hybrid Hero Diagonal              (5+ images, diagonal hero + grid)
    """
    if image_count <= 1 or image_count > MAX_GEOMETRIC_IMAGES:
        return []

    layouts: List[LayoutSuggestion] = []

    # ── Pure diagonal (works best for small counts) ────────────────────────
    if image_count <= MAX_DIAGONAL_IMAGES:
        layouts.extend([
            diagonal_bands_layout(settings, image_count, slant_factor=0.13, right_leaning=True),
            diagonal_bands_layout(settings, image_count, slant_factor=0.13, right_leaning=False),
        ])
        if image_count >= 3:
            layouts.append(diagonal_hero_layout(settings, image_count, hero_side='left',  slant_factor=0.12))
            layouts.append(diagonal_hero_layout(settings, image_count, hero_side='right', slant_factor=0.12))

    # ── Hybrid diagonal-zone + grid (4–15 images) ─────────────────────────
    if 4 <= image_count <= MAX_HYBRID_IMAGES:
        layouts.extend([
            hybrid_top_diagonal_layout(settings, image_count, right_leaning=True),
            hybrid_top_diagonal_layout(settings, image_count, right_leaning=False),
        ])
        if image_count >= 5:
            layouts.append(hybrid_hero_diagonal_layout(settings, image_count))

    # Geometric / diagonal collage templates.
    layouts.extend([
        geometric_triangle_split_layout(settings, image_count, strength='medium', hero_side='left'),
        hero_geometric_bottom_layout(settings, image_count, strength='medium'),
        center_diamond_layout(settings, image_count, strength='medium'),
        asymmetric_diagonal_mosaic_layout(settings, image_count, strength='medium'),
    ])
    if image_count <= 8:
        layouts.append(
            geometric_triangle_split_layout(settings, image_count, strength='bold', hero_side='right')
        )

    return layouts
