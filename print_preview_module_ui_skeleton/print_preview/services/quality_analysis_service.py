from __future__ import annotations

import math

from print_preview.services.placement_service import PlacementService


class QualityAnalysisService:
    """Dynamic preview-quality analysis based on the current print state."""

    MIN_DPI_WARNING = 180.0
    MIN_DPI_CRITICAL = 120.0
    UPSCALE_WARNING = 1.15
    ASPECT_MISMATCH_WARNING = 1.8

    @classmethod
    def analyze_page(cls, page, images_by_id: dict, metrics, settings) -> list[str]:
        if page is None:
            return []

        warnings: list[str] = []

        if PlacementService.is_clipped(metrics, settings):
            warnings.append("Output placement clips outside the printable area.")

        page_items = getattr(page, "items", None)
        if callable(page_items):
            page_items = []
        if page_items is None and isinstance(page, dict):
            page_items = page.get("items", [])

        for index, item in enumerate(page_items or [], start=1):
            image = images_by_id.get(getattr(item, "image_id", "")) if images_by_id else None
            label = cls._item_label(index, item, image)
            if image is None:
                warnings.append(f"{label}: source image is missing.")
                continue

            effective_w_mm = max(0.01, float(getattr(item, "target_width_mm", 0.0) or 0.0) * float(getattr(metrics, "scale", 1.0) or 1.0))
            effective_h_mm = max(0.01, float(getattr(item, "target_height_mm", 0.0) or 0.0) * float(getattr(metrics, "scale", 1.0) or 1.0))

            dpi_x = float(getattr(image, "original_width_px", 0) or 0) / (effective_w_mm / 25.4)
            dpi_y = float(getattr(image, "original_height_px", 0) or 0) / (effective_h_mm / 25.4)
            effective_dpi = min(dpi_x, dpi_y) if dpi_x > 0 and dpi_y > 0 else 0.0
            if 0 < effective_dpi < cls.MIN_DPI_CRITICAL:
                warnings.append(f"{label}: critical resolution {effective_dpi:.0f} DPI at current print size.")
            elif 0 < effective_dpi < cls.MIN_DPI_WARNING:
                warnings.append(f"{label}: low resolution {effective_dpi:.0f} DPI at current print size.")

            source_mm_x = float(getattr(image, "original_width_px", 0) or 0) / 300.0 * 25.4
            source_mm_y = float(getattr(image, "original_height_px", 0) or 0) / 300.0 * 25.4
            upscale_ratio = max(
                effective_w_mm / max(0.01, source_mm_x),
                effective_h_mm / max(0.01, source_mm_y),
            )
            if upscale_ratio > cls.UPSCALE_WARNING:
                warnings.append(f"{label}: enlarged beyond source size ({upscale_ratio:.2f}x).")

            img_ratio = (float(getattr(image, "original_width_px", 0) or 1) / max(1.0, float(getattr(image, "original_height_px", 0) or 1)))
            cell_ratio = effective_w_mm / effective_h_mm
            ratio_gap = max(img_ratio / max(0.01, cell_ratio), cell_ratio / max(0.01, img_ratio))
            if ratio_gap >= cls.ASPECT_MISMATCH_WARNING and str(getattr(item, "fit_mode", "fill")) in ("fill", "smart_fill"):
                warnings.append(f"{label}: strong aspect mismatch may cause aggressive cropping.")

            if getattr(image, "face_data", None):
                for face in image.face_data.get("faces", []):
                    cx = float(face.get("center_x", 0.5))
                    cy = float(face.get("center_y", 0.5))
                    if cx < 0.12 or cx > 0.88 or cy < 0.12 or cy > 0.88:
                        warnings.append(f"{label}: detected face is close to an edge and may be cut.")
                        break

        return warnings[:8]

    @staticmethod
    def _item_label(index: int, item, image) -> str:
        filename = getattr(image, "filename", "") if image is not None else ""
        if filename:
            return filename
        image_id = getattr(item, "image_id", "") or f"Item {index}"
        return str(image_id)
