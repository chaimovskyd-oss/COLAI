"""Data models for the Smart Album Builder."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from app.models.project import LayoutSuggestion


@dataclass
class PhotoMeta:
    """Per-image analysis results, computed once before layout."""

    path: str
    width: int = 0
    height: int = 0
    orientation: str = 'landscape'     # 'landscape' | 'portrait' | 'square'
    sharpness: float = 0.5             # 0..1  (Laplacian variance, normalised)
    brightness: float = 0.5            # 0..1  (mean luminance)
    face_count: int = 0
    is_screenshot: bool = False
    importance: float = 0.5            # composite hero/secondary/weak score
    phash: str = ''                    # perceptual hash for near-duplicate detection


@dataclass
class AlbumPage:
    """One album page: image assignments + chosen layout + per-page overlays."""

    page_index: int
    image_indices: List[int] = field(default_factory=list)  # indices into session.image_states
    layout: Any = None                  # LayoutSuggestion set during placement
    locked: bool = False
    label: str = ''
    # Per-page content — serialised and restored with the album
    text_overlays: List[Any] = field(default_factory=list)
    elements: List[Any] = field(default_factory=list)


@dataclass
class AlbumSettings:
    """User-controlled album generation settings."""

    density: str = 'mixed'             # 'mixed' | 'airy' | 'balanced' | 'dense'
    min_per_page: int = 1
    max_per_page: int = 9
    hero_pages: bool = True             # dedicate pages to top-importance photos
    hero_threshold: float = 0.75        # importance score above which = hero
    title: str = 'האלבום שלי'
    target_pages: int = 0              # 0 = auto; >0 = user-chosen page count
    margin_mm: float = 5.0             # page margin in mm
    spacing_mm: float = 2.0            # inter-cell spacing in mm


# density preset limits
DENSITY_LIMITS = {
    'airy':     (2, 4),
    'balanced': (4, 7),
    'dense':    (6, 10),
}


@dataclass
class AlbumState:
    """Full album: list of pages + metadata."""

    pages: List[AlbumPage] = field(default_factory=list)
    current_page_index: int = 0
    settings: AlbumSettings = field(default_factory=AlbumSettings)
    photo_metas: List[PhotoMeta] = field(default_factory=list)
    generated: bool = False

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def current_page(self) -> Optional[AlbumPage]:
        if 0 <= self.current_page_index < len(self.pages):
            return self.pages[self.current_page_index]
        return None
