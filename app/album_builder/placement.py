"""Smart image placement: choose layout + assign images to cells optimally.

Reuses existing collage_engine.generate_suggestions() and
smart_crop_service.optimize_crop() — no new inference required.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from app.models.project import ImageState, LayoutSuggestion, ProjectSettings, ProjectState

from .models import AlbumPage, PhotoMeta

logger = logging.getLogger(__name__)


def build_page_layout(
    page: AlbumPage,
    project: 'ProjectState',
    metas: List[PhotoMeta],
) -> 'LayoutSuggestion':
    """Choose the best layout for a page and assign images to cells.

    1. Collect the ImageState objects for this page
    2. Run generate_suggestions() to get ranked layouts
    3. Pick the top layout
    4. Run optimize_crop() for each cell (uses cached analysis)
    Returns a fully-assigned LayoutSuggestion.
    """
    from app.core.collage_engine import generate_suggestions
    from app.core.smart_crop_service import optimize_crop

    n = len(page.image_indices)
    if n == 0:
        from app.core.collage_engine import custom_grid_layout
        return custom_grid_layout(project.settings, 0, 1)

    page_images: List['ImageState'] = [project.images[i] for i in page.image_indices]

    # Pick layout — pass images so the engine can score by orientation fit.
    # Torn-paper and shaped (circle/heart) layouts are excluded from albums
    # because they work poorly at automated multi-page generation.
    _ALBUM_EXCLUDED_NAMES = {'torn', 'circle ring', 'circle', 'heart', 'shaped'}

    def _is_album_ok(s) -> bool:
        name_lower = s.name.lower()
        if any(exc in name_lower for exc in _ALBUM_EXCLUDED_NAMES):
            return False
        if getattr(s, 'shape', ''):       # has a canvas-level shape mask
            return False
        for cell in s.cells:
            if getattr(cell, 'edge_style', '') == 'torn_paper':
                return False
        return True

    try:
        suggestions = generate_suggestions(
            project.settings, n, images=page_images
        )
        suggestions = [s for s in suggestions if _is_album_ok(s)]
        layout = suggestions[0] if suggestions else _fallback_grid(project.settings, n)
    except Exception as exc:
        logger.warning('generate_suggestions failed on page %d: %s', page.page_index, exc)
        layout = _fallback_grid(project.settings, n)

    # Optimise crop for each cell using existing smart-crop analysis
    img_size_px = project.settings.canvas_px
    for cell in layout.cells:
        if getattr(cell, 'slot_type', 'photo') == 'spotify_code' or getattr(cell, 'fit_mode', 'fill') == 'contain':
            continue
        if cell.image_index is None or cell.image_index >= len(page_images):
            continue
        state = page_images[cell.image_index]
        analysis = getattr(state, 'analysis', None)
        if analysis is None:
            continue
        cell_w = max(1, int(round(cell.w)))
        cell_h = max(1, int(round(cell.h)))
        try:
            pan_x, pan_y, zoom, _ = optimize_crop(
                analysis,
                img_size_px,
                (cell_w, cell_h),
                (state.pan_x, state.pan_y),
                state.zoom,
            )
            state.pan_x = pan_x
            state.pan_y = pan_y
            state.zoom = zoom
        except Exception:
            pass

    return layout


def _fallback_grid(settings: 'ProjectSettings', n: int) -> 'LayoutSuggestion':
    from app.core.collage_engine import custom_grid_layout, _assign_images
    import math
    cols = max(1, min(3, round(math.sqrt(n))))
    layout = custom_grid_layout(settings, n, cols)
    layout.cells = _assign_images(layout.cells, n)
    return layout
