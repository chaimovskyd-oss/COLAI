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
        pv.selected_layout = page.layout
        pv.suggestions = [page.layout] if page.layout else []
        from app.models.project import TextOverlay
        pv.text_overlay = TextOverlay()
        pv.text_overlays = []
        pv.elements = []
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
