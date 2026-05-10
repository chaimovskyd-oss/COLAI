"""
cell_dividers.py — Draggable shared-edge detection for flat CellRect layouts.

Works for any layout that is stored as a plain list of CellRect objects (i.e.
templates and algorithmic layouts that have no LayoutTree backing).

Public API
----------
compute_cell_dividers(cells)  ->  List[CellDivider]
hit_cell_divider(dividers, cx, cy)  ->  Optional[CellDivider]
apply_divider_drag(cells, orig_cells, fingerprint, total_delta)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, List, Optional, Tuple

# canvas-pixel tolerances / thresholds
_TOL: float = 4.0    # shared-edge detection tolerance (px)
_HIT: float = 10.0   # hit-test radius for mouse (canvas px)
_MIN: float = 60.0   # minimum cell dimension (canvas px)


@dataclass
class CellDivider:
    """One draggable border between two groups of cells."""
    orientation: str   # 'V' = vertical line (drag left/right)  |  'H' = horizontal line (drag up/down)
    position: float    # canvas px: x for V, y for H
    start: float       # line extent start (y for V, x for H)
    end: float         # line extent end
    before: List[int]  # indices of cells whose right/bottom edge sits at `position`
    after: List[int]   # indices of cells whose left/top   edge sits at `position`

    @property
    def fingerprint(self) -> Tuple[str, FrozenSet[int], FrozenSet[int]]:
        """Stable identity across recomputation — orientation + cell-index sets."""
        return (self.orientation, frozenset(self.before), frozenset(self.after))


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def compute_cell_dividers(
    cells: "List",  # List[CellRect] — avoid circular import at module level
    tol: float = _TOL,
) -> List[CellDivider]:
    """
    Detect all draggable shared edges between cells.

    A divider is created wherever a right/bottom edge of one cell aligns (within
    `tol` canvas pixels) with the left/top edge of another cell AND the two cells
    actually overlap along the perpendicular axis.
    """
    if not cells:
        return []

    dividers: List[CellDivider] = []

    # ── Vertical dividers (vertical line, drag left / right) ────────────────
    right_map: dict[int, List[int]] = {}   # rounded right-edge → [cell indices]
    left_map:  dict[int, List[int]] = {}   # rounded left-edge  → [cell indices]
    for i, c in enumerate(cells):
        right_map.setdefault(int(round(c.x + c.w)), []).append(i)
        left_map.setdefault(int(round(c.x)),         []).append(i)

    for rx, before in right_map.items():
        after: List[int] = []
        for lx, lcs in left_map.items():
            if abs(lx - rx) > tol:
                continue
            for bi in before:
                b_top, b_bot = cells[bi].y, cells[bi].y + cells[bi].h
                for li in lcs:
                    if li in after:
                        continue
                    a_top, a_bot = cells[li].y, cells[li].y + cells[li].h
                    # cells must share a vertical segment (overlap in Y)
                    if b_bot > a_top + tol and a_bot > b_top + tol:
                        after.append(li)
        if not after:
            continue
        all_idx = before + after
        y_start = min(cells[i].y          for i in all_idx)
        y_end   = max(cells[i].y + cells[i].h for i in all_idx)
        dividers.append(CellDivider(
            orientation='V',
            position=float(rx),
            start=y_start,
            end=y_end,
            before=list(before),
            after=list(after),
        ))

    # ── Horizontal dividers (horizontal line, drag up / down) ───────────────
    bottom_map: dict[int, List[int]] = {}
    top_map:    dict[int, List[int]] = {}
    for i, c in enumerate(cells):
        bottom_map.setdefault(int(round(c.y + c.h)), []).append(i)
        top_map.setdefault(int(round(c.y)),           []).append(i)

    for by, before in bottom_map.items():
        after = []
        for ty, tcs in top_map.items():
            if abs(ty - by) > tol:
                continue
            for bi in before:
                b_left, b_right = cells[bi].x, cells[bi].x + cells[bi].w
                for ti in tcs:
                    if ti in after:
                        continue
                    a_left, a_right = cells[ti].x, cells[ti].x + cells[ti].w
                    # cells must share a horizontal segment (overlap in X)
                    if b_right > a_left + tol and a_right > b_left + tol:
                        after.append(ti)
        if not after:
            continue
        all_idx = before + after
        x_start = min(cells[i].x          for i in all_idx)
        x_end   = max(cells[i].x + cells[i].w for i in all_idx)
        dividers.append(CellDivider(
            orientation='H',
            position=float(by),
            start=x_start,
            end=x_end,
            before=list(before),
            after=list(after),
        ))

    return dividers


# ---------------------------------------------------------------------------
# Hit testing
# ---------------------------------------------------------------------------

def hit_cell_divider(
    dividers: List[CellDivider],
    cx: float,
    cy: float,
    hit_radius: float = _HIT,
) -> Optional[CellDivider]:
    """Return the first divider whose hit zone contains canvas point (cx, cy)."""
    for div in dividers:
        if div.orientation == 'V':
            if (abs(cx - div.position) <= hit_radius
                    and div.start - hit_radius <= cy <= div.end + hit_radius):
                return div
        else:  # 'H'
            if (abs(cy - div.position) <= hit_radius
                    and div.start - hit_radius <= cx <= div.end + hit_radius):
                return div
    return None


def find_divider_by_fingerprint(
    dividers: List[CellDivider],
    fp: Tuple[str, FrozenSet[int], FrozenSet[int]],
) -> Optional[CellDivider]:
    """Look up a divider by its fingerprint (orientation + cell-index sets)."""
    orientation, before_set, after_set = fp
    for div in dividers:
        if (div.orientation == orientation
                and frozenset(div.before) == before_set
                and frozenset(div.after) == after_set):
            return div
    return None


# ---------------------------------------------------------------------------
# Drag application
# ---------------------------------------------------------------------------

def apply_divider_drag(
    cells: "List",          # List[CellRect] — modified in-place
    orig_cells: "List",     # List[CellRect] — read-only snapshot at drag start
    fingerprint: Tuple[str, FrozenSet[int], FrozenSet[int]],
    total_delta: float,
    min_size: float = _MIN,
) -> None:
    """
    Move the divider identified by `fingerprint` by `total_delta` canvas pixels.

    Works from `orig_cells` (the cell geometry at drag-start) so that repeated
    calls with increasing `total_delta` values produce stable, drift-free results.

    Canvas boundary constraint: cells are never pushed outside [0, canvas_size].
    Cell minimum size is enforced via `min_size`.
    """
    orientation, before_set, after_set = fingerprint
    before = [i for i in sorted(before_set) if i < len(cells)]
    after  = [i for i in sorted(after_set)  if i < len(cells)]

    if not before or not after:
        return

    if orientation == 'V':
        # Clamp: "before" cells can only shrink as much as their width allows
        max_shrink_before = min(orig_cells[i].w - min_size for i in before)
        # "after"  cells can only shrink as much as their width allows
        max_shrink_after  = min(orig_cells[i].w - min_size for i in after)
        d = max(-max_shrink_before, min(max_shrink_after, total_delta))
        # Restore original geometry then apply delta for all affected cells
        for i in before:
            cells[i].x = orig_cells[i].x
            cells[i].y = orig_cells[i].y
            cells[i].w = orig_cells[i].w + d
            cells[i].h = orig_cells[i].h
        for i in after:
            cells[i].x = orig_cells[i].x + d
            cells[i].y = orig_cells[i].y
            cells[i].w = orig_cells[i].w - d
            cells[i].h = orig_cells[i].h

    else:  # 'H'
        max_shrink_before = min(orig_cells[i].h - min_size for i in before)
        max_shrink_after  = min(orig_cells[i].h - min_size for i in after)
        d = max(-max_shrink_before, min(max_shrink_after, total_delta))
        for i in before:
            cells[i].x = orig_cells[i].x
            cells[i].y = orig_cells[i].y
            cells[i].w = orig_cells[i].w
            cells[i].h = orig_cells[i].h + d
        for i in after:
            cells[i].x = orig_cells[i].x
            cells[i].y = orig_cells[i].y + d
            cells[i].w = orig_cells[i].w
            cells[i].h = orig_cells[i].h - d
