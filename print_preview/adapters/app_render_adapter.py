"""Bridge the reusable Print Preview module to Smart Collage Maker."""

from __future__ import annotations

import copy
import logging
from pathlib import Path

from PIL import Image

from app.core.exporter import render_project
from app.models.project import ProjectState
from print_preview.adapters.render_adapter import RenderAdapter
from print_preview.rendering.color_preset_processor import apply_print_color_preset

_log = logging.getLogger(__name__)


class _PreviewImageInfo:
    """Minimal image metadata shape expected by QualityAnalysisService."""

    def __init__(self, path: str, face_data: dict | None = None):
        self.path = path
        self.filename = Path(path).name
        self.image_id = path
        self.face_data = face_data or {}
        try:
            with Image.open(path) as img:
                self.original_width_px = img.width
                self.original_height_px = img.height
        except Exception:
            self.original_width_px = 0
            self.original_height_px = 0


class _PreviewPageItem:
    """Minimal page item metadata shape expected by QualityAnalysisService."""

    def __init__(self, image_id: str, target_width_mm: float, target_height_mm: float):
        self.image_id = image_id
        self.target_width_mm = target_width_mm
        self.target_height_mm = target_height_mm
        self.fit_mode = "fill"


class CollagePreviewPage:
    """Read-only wrapper around a collage project for the preview module."""

    def __init__(self, project: ProjectState, page_id: str = "collage"):
        self.project = project
        self.page_id = page_id

    @property
    def width_mm(self) -> float:
        return float(self.project.settings.width_cm) * 10.0

    @property
    def height_mm(self) -> float:
        return float(self.project.settings.height_cm) * 10.0

    @property
    def items(self) -> list[_PreviewPageItem]:
        layout = self.project.selected_layout
        if not layout:
            return []

        canvas_w, canvas_h = self.project.settings.canvas_px
        width_mm = self.width_mm
        height_mm = self.height_mm
        items: list[_PreviewPageItem] = []
        for cell in layout.cells:
            if cell.image_index is None or cell.image_index >= len(self.project.images):
                continue
            image = self.project.images[cell.image_index]
            items.append(
                _PreviewPageItem(
                    image_id=image.path,
                    target_width_mm=max(0.01, float(cell.w) / max(1, canvas_w) * width_mm),
                    target_height_mm=max(0.01, float(cell.h) / max(1, canvas_h) * height_mm),
                )
            )
        return items


class AppRenderAdapter(RenderAdapter):
    """Render Smart Collage Maker projects for the reusable print preview UI."""

    def __init__(self, pages: list[CollagePreviewPage] | None = None):
        self.pages = list(pages or [])
        self.images_by_id: dict[str, _PreviewImageInfo] = {}
        for page in self.pages:
            self._index_page_images(page)

    @classmethod
    def from_project(cls, project: ProjectState) -> "AppRenderAdapter":
        return cls([CollagePreviewPage(project)])

    @classmethod
    def from_state(cls, state) -> "AppRenderAdapter":
        project = getattr(state, "project", state)
        return cls.from_project(project)

    def set_pages(self, pages: list[CollagePreviewPage]) -> None:
        self.pages = list(pages)
        self.images_by_id = {}
        for page in self.pages:
            self._index_page_images(page)

    def render_preview_page(self, page, scale: float, settings=None):
        dpi = min(180, max(96, int(getattr(settings, "dpi", 150) or 150)))
        return self._render(page, dpi=dpi, scale=scale, settings=settings, apply_icc=False)

    def render_export_page(self, page, dpi: int, scale: float = 1.0, settings=None):
        return self._render(
            page,
            dpi=max(72, int(dpi or 300)),
            scale=scale,
            settings=settings,
            apply_icc=True,
        )

    def get_design_page_size_mm(self, page) -> tuple[float, float]:
        return float(page.width_mm), float(page.height_mm)

    def _render(self, page, dpi: int, scale: float, settings=None, apply_icc: bool = False):
        try:
            project = self._scaled_project(page.project, dpi=dpi, scale=scale)
            image = render_project(project, include_bleed=False)

            if settings is not None and getattr(settings, "print_color_preset_enabled", False):
                image = apply_print_color_preset(
                    image,
                    getattr(settings, "print_color_preset_values", {}) or {},
                )

            if apply_icc and settings is not None and getattr(settings, "enable_color_management", False):
                from print_preview.services.icc_service import ICCService

                image, warning = ICCService().apply_transform(image, settings)
                if warning:
                    _log.warning("ICC transform: %s", warning)

            return image
        except Exception as exc:
            _log.error("Print preview render failed: %s", exc, exc_info=True)
            return None

    def _scaled_project(self, project: ProjectState, dpi: int, scale: float) -> ProjectState:
        scale = max(0.01, float(scale or 1.0))
        result = copy.deepcopy(project)

        old_w, old_h = project.settings.canvas_px
        result.settings.dpi = int(dpi)
        result.settings.width_cm = float(project.settings.width_cm) * scale
        result.settings.height_cm = float(project.settings.height_cm) * scale
        new_w, new_h = result.settings.canvas_px

        sx = new_w / max(1, old_w)
        sy = new_h / max(1, old_h)
        layout = result.selected_layout
        if layout:
            for cell in layout.cells:
                cell.x *= sx
                cell.y *= sy
                cell.w *= sx
                cell.h *= sy
        return result

    def _index_page_images(self, page: CollagePreviewPage) -> None:
        for image in page.project.images:
            face_data = None
            analysis = getattr(image, "analysis", None)
            if analysis and getattr(analysis, "faces", None):
                faces = []
                for face in analysis.faces:
                    center = getattr(face, "center", (0.5, 0.5))
                    faces.append({"center_x": center[0], "center_y": center[1]})
                face_data = {"faces": faces}
            self.images_by_id[image.path] = _PreviewImageInfo(image.path, face_data)
