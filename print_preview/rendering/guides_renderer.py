from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen


_STYLE_MAP = {
    "Dashed": Qt.PenStyle.DashLine,
    "Dotted": Qt.PenStyle.DotLine,
    "Solid": Qt.PenStyle.SolidLine,
}

_COLOR_MAP = {
    "Black": "#000000",
    "Gray": "#9CA3AF",
    "White": "#FFFFFF",
    "Blue": "#3B82F6",
    "Red": "#EF4444",
}


class GuidesRenderer:
    """Render preview and print guides from the same mm-based geometry."""

    def draw_guides(self, painter, page_rect: QRectF, printable_rect: QRectF, output_rect: QRectF, metrics, settings) -> None:
        if not getattr(settings, "preview_guides_visible", True):
            return

        guide_pen = QPen(QColor(_COLOR_MAP.get(getattr(settings, "guide_color", "Gray"), "#9CA3AF")))
        guide_pen.setStyle(_STYLE_MAP.get(getattr(settings, "guide_style", "Dashed"), Qt.PenStyle.DashLine))
        guide_pen.setWidth(1)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        painter.setPen(guide_pen)
        painter.drawRect(printable_rect)

        if getattr(settings, "show_bleed", False):
            painter.setPen(QPen(QColor("#EF4444"), 1, Qt.PenStyle.DashLine))
            painter.drawRect(self._expand_rect_mm(output_rect, metrics, page_rect, getattr(settings, "bleed_mm", 3.0)))

        if getattr(settings, "show_safe_area", False):
            painter.setPen(QPen(QColor("#22C55E"), 1, Qt.PenStyle.DashLine))
            painter.drawRect(self._shrink_rect_mm(output_rect, metrics, page_rect, getattr(settings, "safe_area_mm", 3.0)))

        if getattr(settings, "show_cut_lines", False):
            painter.setPen(QPen(QColor("#E5E7EB"), 1, Qt.PenStyle.SolidLine))
            self._draw_crop_marks(
                painter,
                output_rect,
                self._mm_to_px(metrics, page_rect, 6.0),
                self._mm_to_px(metrics, page_rect, 3.0),
            )

        if getattr(settings, "show_image_border", False):
            painter.setPen(QPen(QColor("#6B7280"), 1, Qt.PenStyle.SolidLine))
            painter.drawRect(output_rect)

    def draw_print_guides(self, painter, page_rect: QRectF, printable_rect: QRectF, output_rect: QRectF, metrics, settings) -> None:
        if not getattr(settings, "print_cut_lines", False):
            return

        painter.setPen(QPen(QColor("#333333"), 1, Qt.PenStyle.SolidLine))
        self._draw_crop_marks(
            painter,
            output_rect,
            self._mm_to_px(metrics, page_rect, 6.0),
            self._mm_to_px(metrics, page_rect, 3.0),
        )

    def _expand_rect_mm(self, rect: QRectF, metrics, page_rect: QRectF, amount_mm: float) -> QRectF:
        amount_px = self._mm_to_px(metrics, page_rect, amount_mm)
        return rect.adjusted(-amount_px, -amount_px, amount_px, amount_px)

    def _shrink_rect_mm(self, rect: QRectF, metrics, page_rect: QRectF, amount_mm: float) -> QRectF:
        amount_px = self._mm_to_px(metrics, page_rect, amount_mm)
        max_inset_x = max(0.0, rect.width() * 0.5 - 1.0)
        max_inset_y = max(0.0, rect.height() * 0.5 - 1.0)
        inset_x = min(amount_px, max_inset_x)
        inset_y = min(amount_px, max_inset_y)
        return rect.adjusted(inset_x, inset_y, -inset_x, -inset_y)

    def _mm_to_px(self, metrics, page_rect: QRectF, amount_mm: float) -> float:
        paper_w = max(1.0, float(getattr(metrics, "paper_width_mm", 1.0) or 1.0))
        return (float(amount_mm) / paper_w) * page_rect.width()

    def _draw_crop_marks(self, painter, rect: QRectF, mark_len_px: float, gap_px: float) -> None:
        left = rect.left()
        right = rect.right()
        top = rect.top()
        bottom = rect.bottom()

        segments = [
            (QPointF(left - gap_px - mark_len_px, top), QPointF(left - gap_px, top)),
            (QPointF(left, top - gap_px - mark_len_px), QPointF(left, top - gap_px)),
            (QPointF(right + gap_px, top), QPointF(right + gap_px + mark_len_px, top)),
            (QPointF(right, top - gap_px - mark_len_px), QPointF(right, top - gap_px)),
            (QPointF(left - gap_px - mark_len_px, bottom), QPointF(left - gap_px, bottom)),
            (QPointF(left, bottom + gap_px), QPointF(left, bottom + gap_px + mark_len_px)),
            (QPointF(right + gap_px, bottom), QPointF(right + gap_px + mark_len_px, bottom)),
            (QPointF(right, bottom + gap_px), QPointF(right, bottom + gap_px + mark_len_px)),
        ]
        for start, end in segments:
            painter.drawLine(start, end)
