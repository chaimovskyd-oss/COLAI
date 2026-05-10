"""AlbumSession — a self-contained album-building context.

Completely independent of the main ProjectState / collage workflow.
The wizard creates and owns an AlbumSession; nothing bleeds into the
regular collage when the user exits the wizard.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from app.models.project import ImageState, ProjectSettings, ProjectState

from .models import AlbumSettings, AlbumState


def normalize_album_page_layout(layout, settings: 'ProjectSettings') -> None:
    """Scale stale album-page cell coordinates to the current page canvas.

    Album pages can be generated in one canvas/DPI context and then opened in
    another. When that happens the cells may occupy only a corner of the page.
    This keeps the existing composition but fits it back into the usable page
    area.
    """
    if layout is None or not getattr(layout, 'cells', None):
        return
    try:
        canvas_w, canvas_h = settings.canvas_px
        margin = float(getattr(settings, 'margin_px', 0))
        cells = layout.cells
        left = min(float(c.x) for c in cells)
        top = min(float(c.y) for c in cells)
        right = max(float(c.x) + float(c.w) for c in cells)
        bottom = max(float(c.y) + float(c.h) for c in cells)
        bw = max(1.0, right - left)
        bh = max(1.0, bottom - top)
        target_left = margin
        target_top = margin
        target_w = max(1.0, float(canvas_w) - 2.0 * margin)
        target_h = max(1.0, float(canvas_h) - 2.0 * margin)
        if (
            target_w * 0.72 <= bw <= target_w * 1.20
            and target_h * 0.72 <= bh <= target_h * 1.20
        ):
            return
        sx = target_w / bw
        sy = target_h / bh
        for cell in cells:
            cell.x = target_left + (float(cell.x) - left) * sx
            cell.y = target_top + (float(cell.y) - top) * sy
            cell.w = max(1.0, float(cell.w) * sx)
            cell.h = max(1.0, float(cell.h) * sy)
        orig = getattr(layout, 'original_cells', None)
        if orig:
            for cell in orig:
                cell.x = target_left + (float(cell.x) - left) * sx
                cell.y = target_top + (float(cell.y) - top) * sy
                cell.w = max(1.0, float(cell.w) * sx)
                cell.h = max(1.0, float(cell.h) * sy)
    except Exception:
        return


@dataclass
class AlbumSession:
    """Standalone context for the Album Wizard."""

    # Images loaded exclusively for this session
    image_states: List['ImageState'] = field(default_factory=list)

    # Generated result — None until the user clicks "צור אלבום"
    album_state: Optional[AlbumState] = None

    # Canvas / export settings (copy of defaults, editable in the wizard)
    settings: Optional['ProjectSettings'] = None

    # Which page is currently shown in the wizard canvas
    current_page_index: int = 0

    def make_settings(self) -> 'ProjectSettings':
        """Return wizard settings, creating defaults if needed."""
        if self.settings is None:
            from app.models.project import ProjectSettings
            self.settings = ProjectSettings()
        return self.settings

    def make_page_project(self, page_idx: int) -> Optional['ProjectState']:
        """Build a temporary ProjectState for one page (for canvas rendering)."""
        album = self.album_state
        if album is None or page_idx >= album.page_count:
            return None

        page = album.pages[page_idx]
        from app.models.project import ProjectState
        pv = ProjectState.__new__(ProjectState)
        pv.settings = self.make_settings()
        pv.images = [self.image_states[i] for i in page.image_indices]
        normalize_album_page_layout(page.layout, pv.settings)
        pv.selected_layout = page.layout
        pv.suggestions = [page.layout] if page.layout else []
        from app.models.project import TextOverlay
        pv.text_overlay = TextOverlay()
        # Restore per-page overlays and elements (preserved across page switches)
        pv.text_overlays = list(page.text_overlays)
        pv.elements = list(page.elements)
        pv.album_state = None
        return pv

    def make_preview_project(self) -> 'ProjectState':
        """ProjectState for the 'before generation' preview (all images, no layout)."""
        from app.models.project import ProjectState
        pv = ProjectState.__new__(ProjectState)
        pv.settings = self.make_settings()
        pv.images = list(self.image_states)
        pv.selected_layout = None
        pv.suggestions = []
        from app.models.project import TextOverlay
        pv.text_overlay = TextOverlay()
        pv.text_overlays = []
        pv.elements = []
        pv.album_state = None
        return pv

    # ── convenience ─────────────────────────────────────────────────────────

    @property
    def image_count(self) -> int:
        return len(self.image_states)

    @property
    def page_count(self) -> int:
        return self.album_state.page_count if self.album_state else 0

    @property
    def is_generated(self) -> bool:
        return self.album_state is not None and self.album_state.generated
