"""Bridge the Print Preview module to the main app's RenderEngine."""

import logging
import os
import sys

_log = logging.getLogger(__name__)
_PREVIEW_RESOLUTION_SCALE = 0.25

_HERE = os.path.dirname(__file__)
_APP_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

from print_preview.adapters.render_adapter import RenderAdapter


class AppRenderAdapter(RenderAdapter):
    """Wrap the main app RenderEngine for the reusable print preview module."""

    def __init__(self, images_by_id: dict, masks_by_id: dict | None = None, adjustments=None):
        self.images_by_id = images_by_id
        self.masks_by_id = masks_by_id or {}
        self.adjustments = adjustments

    @classmethod
    def from_state(cls, state) -> "AppRenderAdapter":
        adapter = cls({})
        adapter.update_from_state(state)
        return adapter

    def update_from_state(self, state) -> None:
        from core.models.mask_asset import MaskAsset

        project = state.project
        self.images_by_id = {img.image_id: img for img in project.image_library}

        masks: dict = {}
        for page in project.pages:
            for item in page.items:
                if not item.mask_id or item.mask_id in masks:
                    continue
                if item.mask_type in ("svg", "png") and item.mask_source_path:
                    masks[item.mask_id] = MaskAsset(
                        mask_id=item.mask_id,
                        mask_type=item.mask_type,
                        source_path=item.mask_source_path,
                        ignore_white=getattr(item, "mask_ignore_white", False),
                        white_threshold=getattr(item, "mask_white_threshold", 245),
                    )
                else:
                    masks[item.mask_id] = MaskAsset(
                        mask_id=item.mask_id,
                        mask_type="builtin",
                        builtin_shape=item.mask_id,
                    )
        self.masks_by_id = masks

        global_adj = project.global_adjustments or {}
        if global_adj:
            from core.models.adjustment_profile import AdjustmentProfile

            self.adjustments = AdjustmentProfile(
                **{k: v for k, v in global_adj.items() if k in AdjustmentProfile.__dataclass_fields__}
            )
        else:
            self.adjustments = None

    def render_preview_page(self, page, scale: float, settings=None):
        try:
            from core.engines.render_engine import RenderEngine

            _log.debug(
                "render_preview_page: page=%s images=%d print_scale=%.3f",
                getattr(page, "page_id", "?"),
                len(self.images_by_id),
                scale,
            )
            return RenderEngine.render_preview_page(
                page,
                self.images_by_id,
                preview_scale=_PREVIEW_RESOLUTION_SCALE,
                render_scale=scale,
                print_color_preset_values=(
                    getattr(settings, "print_color_preset_values", {})
                    if settings is not None and getattr(settings, "print_color_preset_enabled", False)
                    else None
                ),
                masks_by_id=self.masks_by_id or None,
                adjustments=self.adjustments,
                use_thumbnail=True,
            )
        except Exception as exc:
            _log.error("render_preview_page failed: %s", exc, exc_info=True)
            return None

    def render_export_page(self, page, dpi: int, scale: float = 1.0, settings=None):
        try:
            from core.engines.render_engine import RenderEngine

            image = RenderEngine.render_export_page(
                page,
                self.images_by_id,
                export_dpi=dpi,
                render_scale=scale,
                print_color_preset_values=(
                    getattr(settings, "print_color_preset_values", {})
                    if settings is not None and getattr(settings, "print_color_preset_enabled", False)
                    else None
                ),
                masks_by_id=self.masks_by_id or None,
                adjustments=self.adjustments,
            )
            if image is None:
                return None

            if settings is not None and getattr(settings, "enable_color_management", False):
                from print_preview.services.icc_service import ICCService

                icc = ICCService()
                image, warning = icc.apply_transform(image, settings)
                if warning:
                    _log.warning("Export ICC: %s", warning)

            return image
        except Exception as exc:
            _log.error("render_export_page failed: %s", exc, exc_info=True)
            return None

    def get_design_page_size_mm(self, page) -> tuple[float, float]:
        return float(page.width_mm), float(page.height_mm)
