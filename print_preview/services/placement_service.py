from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlacementRectMM:
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float


class PlacementService:
    """Shared output placement math for preview, export, and print."""

    @staticmethod
    def compute_output_rect_mm(metrics, settings) -> PlacementRectMM:
        output_w = float(getattr(metrics, "output_width_mm", 0.0) or 0.0)
        output_h = float(getattr(metrics, "output_height_mm", 0.0) or 0.0)
        printable_w = float(getattr(metrics, "printable_width_mm", 0.0) or 0.0)
        printable_h = float(getattr(metrics, "printable_height_mm", 0.0) or 0.0)
        margin_left = float(getattr(metrics, "margin_left_mm", 0.0) or 0.0)
        margin_top = float(getattr(metrics, "margin_top_mm", 0.0) or 0.0)

        align_mode = str(getattr(settings, "align_mode", "center") or "center").lower()
        offset_x = float(getattr(settings, "align_offset_x_mm", 0.0) or 0.0)
        offset_y = float(getattr(settings, "align_offset_y_mm", 0.0) or 0.0)

        if align_mode == "top_left":
            x_mm = margin_left
            y_mm = margin_top
        elif align_mode == "custom":
            x_mm = margin_left + offset_x
            y_mm = margin_top + offset_y
        else:
            x_mm = margin_left + (printable_w - output_w) * 0.5
            y_mm = margin_top + (printable_h - output_h) * 0.5

        return PlacementRectMM(
            x_mm=x_mm,
            y_mm=y_mm,
            width_mm=max(0.0, output_w),
            height_mm=max(0.0, output_h),
        )

    @staticmethod
    def is_clipped(metrics, settings) -> bool:
        rect = PlacementService.compute_output_rect_mm(metrics, settings)
        printable_left = float(getattr(metrics, "margin_left_mm", 0.0) or 0.0)
        printable_top = float(getattr(metrics, "margin_top_mm", 0.0) or 0.0)
        printable_right = printable_left + float(getattr(metrics, "printable_width_mm", 0.0) or 0.0)
        printable_bottom = printable_top + float(getattr(metrics, "printable_height_mm", 0.0) or 0.0)
        return (
            rect.x_mm < printable_left - 1e-6
            or rect.y_mm < printable_top - 1e-6
            or rect.x_mm + rect.width_mm > printable_right + 1e-6
            or rect.y_mm + rect.height_mm > printable_bottom + 1e-6
        )
