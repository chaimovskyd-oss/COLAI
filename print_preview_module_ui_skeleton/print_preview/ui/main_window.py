from pathlib import Path

from PIL import ImageOps

from PySide6.QtCore import QRectF
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from print_preview.rendering.guides_renderer import GuidesRenderer
from print_preview.services.placement_service import PlacementService
from print_preview.services.windows_printer_driver_service import WindowsPrinterDriverService
from print_preview.ui.bottom_bar import PrintPreviewBottomBar
from print_preview.ui.print_preview_widget import PrintPreviewWidget
from print_preview.ui.side_panel import PrintPreviewSidePanel
from print_preview.ui.styles import APP_STYLESHEET
from print_preview.ui.top_bar import PrintPreviewTopBar


class PrintPreviewWindow(QMainWindow):
    """Top-level window for the print preview module."""

    def __init__(self, controller, enable_default_print_fallback: bool = True):
        super().__init__()
        self.controller = controller
        self._enable_default_print_fallback = enable_default_print_fallback
        self._guides_renderer = GuidesRenderer()
        self._driver_service = WindowsPrinterDriverService()

        self.setWindowTitle("Print Preview Studio")
        self.setMinimumSize(1040, 700)
        self._apply_safe_initial_size()

        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        self.top_bar = PrintPreviewTopBar(controller)
        self.preview_widget = PrintPreviewWidget(controller)
        self.side_panel = PrintPreviewSidePanel(controller)
        self.bottom_bar = PrintPreviewBottomBar(controller)
        self.preview_widget.setMinimumWidth(420)
        self.side_panel.setMinimumWidth(330)
        self.top_bar.setFixedHeight(self.top_bar.sizeHint().height())
        self.bottom_bar.setFixedHeight(self.bottom_bar.sizeHint().height())

        center = QWidget()
        center_layout = QHBoxLayout(center)
        center_layout.setContentsMargins(8, 8, 8, 8)
        center_layout.setSpacing(14)
        center_layout.addWidget(self.preview_widget, 7)
        center_layout.addWidget(self.side_panel, 3)
        center.setMinimumHeight(0)

        center_scroll = QScrollArea()
        center_scroll.setWidgetResizable(True)
        center_scroll.setFrameShape(QFrame.Shape.NoFrame)
        center_scroll.setWidget(center)

        main_layout.addWidget(self.top_bar)
        main_layout.addWidget(center_scroll, 1)
        main_layout.addWidget(self.bottom_bar)
        main_layout.setStretch(0, 0)
        main_layout.setStretch(1, 1)
        main_layout.setStretch(2, 0)

        self.setStyleSheet(APP_STYLESHEET)

        self.statusBar().showMessage("Preview ready")

        controller.printer_settings_requested.connect(self._on_printer_settings_requested)
        controller.preview_state_changed.connect(self._update_status_bar)
        self.preview_widget.render_analysis_changed.connect(self.controller.update_render_analysis)
        if self._enable_default_print_fallback:
            controller.print_requested.connect(self._on_print_requested)
            controller.export_requested.connect(self._on_export_requested)

        self.top_bar.export_requested.connect(self.controller.request_export)
        self.top_bar.print_requested.connect(self.controller.request_print)
        self.top_bar.close_requested.connect(self.close)
        self.top_bar.zoom_in_requested.connect(self._zoom_in)
        self.top_bar.zoom_out_requested.connect(self._zoom_out)
        self.top_bar.reset_zoom_requested.connect(self._reset_zoom)
        self.top_bar.toggle_guides_requested.connect(self.controller.toggle_preview_guides)
        self.top_bar.printer_settings_requested.connect(self.controller.open_printer_settings)
        self.top_bar.about_requested.connect(self._show_about)
        self.bottom_bar.save_print_settings_clicked.connect(self.side_panel.trigger_save_print_settings)

        initial_state = self.controller.get_current_preview_state()
        self.preview_widget._on_preview_state_changed(initial_state)
        self.side_panel._sync_from_preview_state(initial_state)
        self.bottom_bar._on_preview_state_changed(initial_state)
        self._update_status_bar(initial_state)

    def showEvent(self, event):
        super().showEvent(event)
        self._keep_window_inside_available_area()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._keep_window_inside_available_area()

    def _available_geometry(self):
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def _apply_safe_initial_size(self):
        available = self._available_geometry()
        if available is None:
            self.resize(1400, 880)
            return
        target_width = min(1400, max(self.minimumWidth(), available.width() - 24))
        target_height = min(880, max(self.minimumHeight(), available.height() - 24))
        self.resize(target_width, target_height)

    def _keep_window_inside_available_area(self):
        available = self._available_geometry()
        if available is None:
            return

        margin = 10
        max_width = max(self.minimumWidth(), available.width() - (margin * 2))
        max_height = max(self.minimumHeight(), available.height() - (margin * 2))
        new_width = min(self.width(), max_width)
        new_height = min(self.height(), max_height)
        if new_width != self.width() or new_height != self.height():
            self.resize(new_width, new_height)

        frame = self.frameGeometry()
        min_x = available.left() + margin
        min_y = available.top() + margin
        max_x = available.right() - margin - frame.width() + 1
        max_y = available.bottom() - margin - frame.height() + 1
        new_x = max(min_x, min(frame.x(), max_x))
        new_y = max(min_y, min(frame.y(), max_y))
        if new_x != frame.x() or new_y != frame.y():
            self.move(new_x, new_y)

    def _on_printer_settings_requested(self):
        printer_name = self.controller.get_settings().printer_name
        if not printer_name:
            QMessageBox.warning(self, "Printer Driver Settings", "Select a valid printer before opening driver settings.")
            return
        if not self._driver_service.is_available():
            QMessageBox.warning(
                self,
                "Printer Driver Settings",
                "Native Windows printer driver preferences are only available on Windows.",
            )
            return

        try:
            driver_result = self._driver_service.open_driver_preferences(
                printer_name,
                parent_hwnd=int(self.winId()) if self.winId() else None,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Printer Driver Settings", str(exc))
            return

        if driver_result is None:
            return

        printer = self._driver_service.build_qprinter_from_result(driver_result)
        self.controller.apply_driver_settings(driver_result, printer)
        self.preview_widget.invalidate_render_cache()

    def _on_print_requested(self, preview_state):
        if not preview_state.can_print:
            QMessageBox.warning(self, "Print Unavailable", "No valid printer is configured for the current preview.")
            return
        self._render_preview_state_to_printer(preview_state)

    def _render_preview_state_to_printer(self, preview_state):
        from PySide6.QtGui import QImage, QPainter

        page_states = preview_state.pages or []
        if not page_states:
            QMessageBox.warning(self, "Print Failed", "No pages are available to print.")
            return

        printer = preview_state.printer
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.warning(self, "Print Failed", "Could not start the print job.")
            return

        try:
            for index, page_state in enumerate(page_states):
                rendered = preview_state.adapter.render_export_page(
                    page_state.page,
                    preview_state.settings.dpi,
                    scale=page_state.metrics.scale,
                    settings=preview_state.settings,
                )
                if rendered is None:
                    raise RuntimeError(f"Could not render page {index + 1} for printing.")
                if getattr(preview_state.settings, "mirror_output", False):
                    rendered = ImageOps.mirror(rendered)

                qimg = self._pil_to_qimage(rendered)
                if qimg is None:
                    raise RuntimeError(f"Could not prepare page {index + 1} for printing.")

                if index > 0:
                    printer.newPage()

                target_rect = self._compute_target_rect_px(printer, page_state.metrics, preview_state.settings)
                painter.drawImage(target_rect, qimg)
                self._guides_renderer.draw_print_guides(
                    painter,
                    self._paper_rect_px(printer),
                    self._printable_rect_px(printer),
                    target_rect,
                    page_state.metrics,
                    preview_state.settings,
                )
        except Exception as exc:
            QMessageBox.warning(self, "Print Failed", str(exc))
            return
        finally:
            painter.end()

        self.statusBar().showMessage(
            f"Sent {len(page_states)} page(s) to {preview_state.printer_name or 'printer'}"
        )
        QMessageBox.information(
            self,
            "Print Sent",
            f"The print job was sent successfully to {preview_state.printer_name or 'the selected printer'}.",
        )
        self.close()

    def _on_export_requested(self, preview_state):
        page_states = preview_state.pages or []
        if not page_states:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Preview",
            "",
            "PNG Image (*.png);;JPEG Image (*.jpg)",
        )
        if not path:
            return

        target = Path(path)
        fmt = "JPEG" if target.suffix.lower() in (".jpg", ".jpeg") else "PNG"

        try:
            for index, page_state in enumerate(page_states, start=1):
                result = preview_state.adapter.render_export_page(
                    page_state.page,
                    preview_state.settings.dpi,
                    scale=page_state.metrics.scale,
                    settings=preview_state.settings,
                )
                if result is None:
                    raise RuntimeError(f"Could not render page {index} for export.")
                if getattr(preview_state.settings, "mirror_output", False):
                    result = ImageOps.mirror(result)

                if len(page_states) == 1:
                    page_path = target
                else:
                    page_path = target.with_name(f"{target.stem}_page_{index:02d}{target.suffix}")
                result.save(str(page_path), format=fmt, dpi=(preview_state.settings.dpi, preview_state.settings.dpi))
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", str(exc))
            return

        self.statusBar().showMessage(f"Exported {len(page_states)} page(s)")

    def _compute_target_rect_px(self, printer, metrics, settings) -> QRectF:
        dpi = float(printer.resolution() or self.controller.get_settings().dpi or 300)
        px_per_mm = dpi / 25.4
        placement = PlacementService.compute_output_rect_mm(metrics, settings)
        return QRectF(
            placement.x_mm * px_per_mm,
            placement.y_mm * px_per_mm,
            max(1.0, placement.width_mm * px_per_mm),
            max(1.0, placement.height_mm * px_per_mm),
        )

    def _paper_rect_px(self, printer) -> QRectF:
        return QRectF(printer.pageLayout().fullRectPixels(printer.resolution()))

    def _printable_rect_px(self, printer) -> QRectF:
        return QRectF(printer.pageLayout().paintRectPixels(printer.resolution()))

    def _pil_to_qimage(self, image):
        from PySide6.QtGui import QImage

        try:
            rgba = image.convert("RGBA")
            data = bytes(rgba.tobytes("raw", "RGBA"))
            return QImage(
                data,
                rgba.width,
                rgba.height,
                rgba.width * 4,
                QImage.Format.Format_RGBA8888,
            ).copy()
        except Exception:
            return None

    def _update_status_bar(self, state):
        preset_name = state.settings.print_color_preset_name or "None"
        if not getattr(state.settings, "print_color_preset_enabled", False):
            preset_name = "None"
        icc_status = "ON" if getattr(state.settings, "enable_color_management", False) else "OFF"
        profile_name = getattr(state.settings, "output_profile", None) or "None"
        message = (
            f"Printer: {state.printer_name or 'None'}"
            f"  |  Scale: {state.metrics.scale * 100:.1f}%"
            f"  |  ICC: {icc_status}"
            f"  |  Profile: {profile_name}"
            f"  |  Preset: {preset_name}"
            f"  |  Page {state.page_index + 1}/{state.page_count}"
            f"  |  Ink: {state.ink_level} ({state.ink_coverage_percent:.1f}%)"
        )
        self.statusBar().showMessage(message)

    def _zoom_in(self):
        self.bottom_bar.step_zoom_percent(10)

    def _zoom_out(self):
        self.bottom_bar.step_zoom_percent(-10)

    def _reset_zoom(self):
        self.bottom_bar.set_zoom_percent(100)

    def _show_about(self):
        QMessageBox.information(
            self,
            "About Print Preview",
            "Print Preview Studio\nPreview, export, and print share the same state and page order.",
        )
