"""AlbumBuilder: synchronous orchestration used by the worker thread.

Stages (each reports progress via callback):
  1. Analyse photos     — sharpness, brightness, orientation, face count
  2. Face detection     — reuse smart_crop_service cache
  3. Plan pages         — distribute images according to density settings
  4. Build layouts      — choose template per page
  5. Assign crops       — optimise pan/zoom per cell
  6. Done
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, List, Optional, Tuple

from .analysis import analyze_photo
from .models import AlbumPage, AlbumSettings, AlbumState
from .planning import plan_pages
from .placement import build_page_layout

if TYPE_CHECKING:
    from app.models.project import ProjectState

logger = logging.getLogger(__name__)

ProgressCb = Callable[[str, int, int], None]   # (stage_label, current, total)


def _noop(stage: str, cur: int, total: int) -> None:
    pass


class AlbumBuilder:
    """Builds an AlbumState from a ProjectState + AlbumSettings."""

    def __init__(self, project: 'ProjectState'):
        self.project = project

    def build(
        self,
        settings: AlbumSettings,
        progress_cb: ProgressCb = _noop,
    ) -> AlbumState:
        """Run the full pipeline and return the completed AlbumState."""
        project = self.project
        images = project.images
        n = len(images)

        album = AlbumState(settings=settings)

        # ── Stage 1: analyse photos ──────────────────────────────────────────
        metas = []
        progress_cb('מנתח תמונות…', 0, n)
        for i, state in enumerate(images):
            progress_cb('מנתח תמונות…', i + 1, n)
            meta = analyze_photo(state, existing_analysis=getattr(state, 'analysis', None))
            metas.append(meta)
        album.photo_metas = metas

        # ── Stage 2: face detection (trigger analysis cache if not yet run) ──
        progress_cb('מזהה פנים…', 0, n)
        for i, state in enumerate(images):
            progress_cb('מזהה פנים…', i + 1, n)
            if getattr(state, 'analysis', None) is None and getattr(state, 'analysis_status', '') != 'error':
                try:
                    from app.core.smart_crop_service import analyze_image
                    state.analysis = analyze_image(state.path, rotation=getattr(state, 'rotation', 0))
                    state.analysis_status = 'done'
                    metas[i].face_count = len(state.analysis.faces)
                    # Recompute importance now that we have face count
                    from .analysis import _importance
                    metas[i].importance = _importance(metas[i])
                except Exception as exc:
                    logger.warning('Face detection failed for %s: %s', state.path, exc)
                    state.analysis_status = 'error'

        # ── Stage 3: plan pages ──────────────────────────────────────────────
        progress_cb('בונה תכנית דפים…', 0, 1)
        pages = plan_pages(metas, settings)
        progress_cb('בונה תכנית דפים…', 1, 1)

        # ── Stages 4+5: build layouts + assign crops ─────────────────────────
        n_pages = len(pages)
        for page in pages:
            progress_cb('בוחר פריסות ומיישב תמונות…', page.page_index + 1, n_pages)
            try:
                page.layout = build_page_layout(page, project, metas)
            except Exception as exc:
                logger.warning('Page layout failed for page %d: %s', page.page_index, exc)

        album.pages = pages
        album.generated = True
        return album

    def get_page_project(self, album: AlbumState, page_idx: int) -> 'ProjectState':
        """Return a lightweight ProjectState that renders one album page.

        ImageState objects are shared by reference so edits (pan, zoom, etc.)
        propagate back to the master project automatically.
        """
        from app.models.project import ProjectState
        from app.album_builder.session import normalize_album_page_layout

        page = album.pages[page_idx]
        pv = ProjectState.__new__(ProjectState)
        pv.settings = self.project.settings
        pv.images = [self.project.images[i] for i in page.image_indices]
        normalize_album_page_layout(page.layout, pv.settings)
        pv.selected_layout = page.layout
        pv.suggestions = [page.layout] if page.layout else []
        pv.text_overlay = self.project.text_overlay.__class__()
        pv.text_overlays = list(getattr(page, 'text_overlays', []))
        pv.elements = list(getattr(page, 'elements', []))
        pv.album_state = None
        return pv
