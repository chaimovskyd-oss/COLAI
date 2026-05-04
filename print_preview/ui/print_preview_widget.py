import logging

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from print_preview.rendering.guides_renderer import GuidesRenderer
from print_preview.rendering.preview_renderer import PreviewRenderer
from print_preview.services.ink_estimation_service import InkEstimationService
from print_preview.services.placement_service import PlacementService

_log = logging.getLogger(__name__)


class PrintPreviewWidget(QWidget):
    """Canvas that paints the paper sheet, printable area, output placement, and content."""

    render_analysis_changed = Signal(float, str)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.guides = GuidesRenderer()
        self.renderer = PreviewRenderer(controller.adapter)
        self._last_render_error: str | None = None
        self._last_analysis_key = None

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(320, 400)

        controller.metrics_changed.connect(self._on_state_changed)
        controller.settings_changed.connect(self._on_state_changed)
        controller.preview_state_changed.connect(self._on_preview_state_changed)
        controller.render_invalidated.connect(self.renderer.invalidate_cache)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._title = QLabel("Print Preview")
        self._title.setObjectName("CanvasTitle")

        self._subtitle = QLabel(
            "White sheet = printer paper. Output size, placement, guides, and print all share the same state."
        )
        self._subtitle.setObjectName("CanvasSubtle")
        self._subtitle.setWordWrap(True)

        self.warning_label = QLabel("")
        self.warning_label.setObjectName("WarningBanner")
        self.warning_label.setWordWrap(True)
        self.warning_label.setVisible(False)

        layout.addWidget(self._title)
        layout.addWidget(self._subtitle)
        layout.addWidget(self.warning_label)
        layout.addStretch()

    def _on_state_changed(self, _payload=None):
        self.update()

    def _on_preview_state_changed(self, state):
        if state.warnings:
            self.warning_label.setText(" | ".join(state.warnings))
            self.warning_label.setVisible(True)
        else:
            self.warning_label.setVisible(False)
        self.update()

    def invalidate_render_cache(self):
        self.renderer.invalidate_cache()
        self._last_analysis_key = None
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        if not painter.isActive():
            return
        try:
            self._paint(painter)
        except Exception as exc:
            _log.error("paintEvent raised: %s", exc, exc_info=True)
            self._draw_error(painter, str(exc))
        finally:
            painter.end()

    def _paint(self, painter: QPainter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        header_h = self._header_height()
        full_rect = self.rect().adjusted(24, header_h, -24, -24)
        if full_rect.width() < 10 or full_rect.height() < 10:
            return

        painter.fillRect(full_rect, QColor("#181A1F"))

        metrics = self.controller.get_metrics()
        settings = self.controller.get_settings()
        zoom = self.controller.get_preview_zoom()
        preview_state = self.controller.get_current_preview_state()

        paper_ratio = metrics.paper_width_mm / metrics.paper_height_mm if metrics.paper_height_mm > 0 else 1.0
        max_w = full_rect.width() * 0.86 * zoom
        max_h = full_rect.height() * 0.86 * zoom
        draw_w = min(max_w, max_h * paper_ratio)
        draw_h = draw_w / paper_ratio if paper_ratio > 0 else max_h

        cx = full_rect.left() + full_rect.width() / 2
        cy = full_rect.top() + full_rect.height() / 2
        page_rect = QRectF(cx - draw_w / 2, cy - draw_h / 2, draw_w, draw_h)

        painter.setPen(QPen(QColor("#8B8D93"), 1))
        painter.setBrush(QColor("#FAFAF8"))
        painter.drawRect(page_rect)

        paper_w = metrics.paper_width_mm or 1.0
        paper_h = metrics.paper_height_mm or 1.0
        printable_rect = QRectF(
            page_rect.left() + page_rect.width() * (metrics.margin_left_mm / paper_w),
            page_rect.top() + page_rect.height() * (metrics.margin_top_mm / paper_h),
            page_rect.width() * (metrics.printable_width_mm / paper_w),
            page_rect.height() * (metrics.printable_height_mm / paper_h),
        )
        output_rect = self._output_rect_px(page_rect, metrics, settings)

        page = self.controller.current_page
        pixmap = None
        if page is not None:
            try:
                pixmap = self.renderer.render(page, metrics, settings)
            except Exception as exc:
                _log.error("renderer.render raised: %s", exc, exc_info=True)
                self._last_render_error = str(exc)
                pixmap = None
            else:
                self._last_render_error = None

        if pixmap is not None and not pixmap.isNull():
            painter.save()
            painter.setClipRect(printable_rect)
            if getattr(settings, "mirror_output", False):
                painter.translate(output_rect.center().x(), output_rect.center().y())
                painter.scale(-1.0, 1.0)
                painter.translate(-output_rect.center().x(), -output_rect.center().y())
            painter.drawPixmap(output_rect, pixmap, QRectF(pixmap.rect()))
            painter.restore()
            self._emit_render_analysis_if_needed(page, metrics)
        else:
            painter.setPen(QPen(QColor("#9CA3AF"), 1))
            painter.setBrush(QColor(156, 163, 175, 70))
            bw = printable_rect.width() * 0.42
            bh = printable_rect.height() * 0.28
            gap = printable_rect.width() * 0.04
            x1 = printable_rect.left() + printable_rect.width() * 0.06
            y1 = printable_rect.top() + printable_rect.height() * 0.14
            painter.drawRect(QRectF(x1, y1, bw, bh))
            painter.drawRect(QRectF(x1 + bw + gap, y1, bw, bh))
            painter.setPen(QColor("#6B7280"))
            msg_font = QFont()
            msg_font.setPointSize(9)
            painter.setFont(msg_font)
            if self._last_render_error:
                msg = f"Render error: {self._last_render_error[:80]}"
            elif page is None:
                msg = "No page loaded"
            else:
                msg = "Rendering..."
            painter.drawText(
                QRectF(printable_rect.left(), y1 + bh + 10, printable_rect.width(), 22),
                Qt.AlignmentFlag.AlignHCenter,
                msg,
            )

        badge_font = QFont()
        badge_font.setPointSize(8)
        badge_font.setBold(True)
        painter.setFont(badge_font)
        badge_rect = QRectF(page_rect.left() + 4, page_rect.top() + 4, page_rect.width() - 8, 16)

        if getattr(settings, "print_color_preset_enabled", False):
            preset_name = getattr(settings, "print_color_preset_name", "") or "Custom"
            painter.setPen(QColor("#A78BFA"))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignRight, preset_name)

        if getattr(settings, "enable_color_management", False):
            painter.setPen(QColor("#F59E0B" if getattr(settings, "soft_proof_preview", False) else "#60A5FA"))
            painter.drawText(
                badge_rect,
                Qt.AlignmentFlag.AlignLeft,
                "SOFT PROOF" if getattr(settings, "soft_proof_preview", False) else "ICC",
            )

        if getattr(settings, "mirror_output", False):
            painter.setPen(QColor("#FBBF24"))
            painter.drawText(
                QRectF(page_rect.left() + 4, page_rect.bottom() - 20, page_rect.width() - 8, 16),
                Qt.AlignmentFlag.AlignRight,
                "MIRRORED",
            )

        self.guides.draw_guides(painter, page_rect, printable_rect, output_rect, metrics, settings)

        painter.setPen(QColor("#D6D3CC"))
        info_font = QFont()
        info_font.setPointSize(10)
        info_font.setBold(True)
        painter.setFont(info_font)
        text = (
            f"Printed Size: {metrics.output_width_mm:.0f} x {metrics.output_height_mm:.0f} mm"
            f"  |  Scale: {metrics.scale * 100:.1f} %"
            f"  |  Page {preview_state.page_index + 1} / {preview_state.page_count}"
        )
        painter.drawText(
            QRectF(full_rect.left(), page_rect.bottom() + 10, full_rect.width(), 28),
            Qt.AlignmentFlag.AlignHCenter,
            text,
        )

    def _emit_render_analysis_if_needed(self, page, metrics):
        raw_pil = self.renderer.get_raw_pil()
        analysis_key = (id(page), round(metrics.scale, 4), getattr(raw_pil, "size", None))
        if analysis_key == self._last_analysis_key:
            return
        coverage_pct, level = InkEstimationService.estimate(raw_pil)
        self._last_analysis_key = analysis_key
        self.render_analysis_changed.emit(coverage_pct, level)

    def _output_rect_px(self, page_rect: QRectF, metrics, settings) -> QRectF:
        placement = PlacementService.compute_output_rect_mm(metrics, settings)
        paper_w = max(1.0, float(metrics.paper_width_mm or 1.0))
        paper_h = max(1.0, float(metrics.paper_height_mm or 1.0))
        return QRectF(
            page_rect.left() + page_rect.width() * (placement.x_mm / paper_w),
            page_rect.top() + page_rect.height() * (placement.y_mm / paper_h),
            page_rect.width() * (placement.width_mm / paper_w),
            page_rect.height() * (placement.height_mm / paper_h),
        )

    def _header_height(self) -> int:
        h = self._title.sizeHint().height()
        h += self._subtitle.sizeHint().height() + 6
        if self.warning_label.isVisible():
            h += self.warning_label.sizeHint().height() + 6
        return max(80, h + 16)

    def _draw_error(self, painter: QPainter, message: str) -> None:
        painter.fillRect(self.rect(), QColor("#1C1D21"))
        painter.setPen(QColor("#EF4444"))
        err_font = QFont()
        err_font.setPointSize(10)
        painter.setFont(err_font)
        painter.drawText(
            QRectF(self.rect()),
            Qt.AlignmentFlag.AlignCenter,
            f"Preview error:\n{message[:200]}",
        )
