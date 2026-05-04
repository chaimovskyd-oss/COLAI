import copy
from dataclasses import fields

from PySide6.QtCore import QObject, Signal

from print_preview.models.preview_state import PagePreviewState, PreviewState
from print_preview.models.print_metrics import PrintMetrics
from print_preview.models.print_settings import PrintSettings
from print_preview.services.icc_service import ICCService
from print_preview.services.placement_service import PlacementService
from print_preview.services.printable_area_service import PrintableAreaService
from print_preview.services.quality_analysis_service import QualityAnalysisService
from print_preview.services.scale_service import ScaleService
from print_preview.services.windows_printer_driver_service import NativePrinterDriverSettingsResult


class PrintPreviewController(QObject):
    """Central controller for the print preview module.

    All business logic lives here; UI components only observe signals and
    call the public API — they never touch each other directly.
    """

    metrics_changed       = Signal(object)   # PrintMetrics
    settings_changed      = Signal(object)   # PrintSettings
    preview_state_changed = Signal(object)   # PreviewState
    print_requested       = Signal(object)   # PreviewState
    export_requested      = Signal(object)   # PreviewState
    printer_settings_requested = Signal()
    render_invalidated    = Signal()         # emitted when cached render must be discarded

    def __init__(self, adapter, parent=None):
        super().__init__(parent)
        self.adapter           = adapter
        self.settings          = PrintSettings()
        self.metrics           = PrintMetrics()
        self.scale_service     = ScaleService()
        self.printable_service = PrintableAreaService()

        # Page state
        self._pages: list          = []
        self._page_index: int      = 0
        self.current_page          = None

        # Printer state
        self.printer               = None
        self._has_valid_printer    = False

        # Preview display zoom (not the same as print scale)
        self._preview_zoom: float  = 1.0

        # Quality warnings pushed from the host app
        self._host_warnings: list[str] = []
        self._ink_coverage_percent: float = 0.0
        self._ink_level: str = "Low"

        # Shared ICC service (profile discovery cached at class level)
        self._icc = ICCService()
        self._suspend_auto_preset_load = False

    # ── Page management ───────────────────────────────────────────────────────

    def set_page(self, page) -> None:
        """Set a single page (no multi-page navigation)."""
        self._pages      = [page] if page is not None else []
        self._page_index = 0
        self.current_page = page
        self._recalculate()

    def set_pages(self, pages: list, index: int = 0) -> None:
        """Set the full page list and navigate to *index*.

        Call this from the host app to enable prev/next navigation.
        """
        self._pages      = list(pages)
        self._page_index = max(0, min(index, len(pages) - 1)) if pages else 0
        self.current_page = self._pages[self._page_index] if self._pages else None
        self._recalculate()

    def go_next_page(self) -> None:
        if self._page_index < len(self._pages) - 1:
            self._page_index += 1
            self.current_page = self._pages[self._page_index]
            self._recalculate()

    def go_previous_page(self) -> None:
        if self._page_index > 0:
            self._page_index -= 1
            self.current_page = self._pages[self._page_index]
            self._recalculate()

    @property
    def page_count(self) -> int:
        return len(self._pages)

    @property
    def current_page_number(self) -> int:
        return self._page_index + 1

    # ── Printer ───────────────────────────────────────────────────────────────

    def update_printer(self, printer=None) -> None:
        self.printer                  = printer
        self.settings.printer_name   = self._resolve_printer_name(printer)
        self._has_valid_printer       = bool(self.settings.printer_name)
        self.metrics                  = self.printable_service.calculate_from_printer(printer)
        if getattr(self.settings, "driver_paper_name", None):
            self.settings.paper_type = self.settings.driver_paper_name or ""
        if not self._suspend_auto_preset_load:
            self._auto_load_matching_preset()
        self._recalculate()

    def update_printer_by_name(self, name: str) -> None:
        self.settings.printer_name = name or None
        self.settings.native_devmode_bytes = b""
        try:
            from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
            for info in QPrinterInfo.availablePrinters():
                if info.printerName() == name:
                    self.update_printer(QPrinter(info))
                    return
        except Exception:
            pass
        # Printer not found — use A4 defaults
        self.printer            = None
        self._has_valid_printer = False
        self.metrics            = self.printable_service.calculate_from_printer(None)
        self._recalculate()

    # ── Scale ─────────────────────────────────────────────────────────────────

    def set_scale_mode(self, mode: str) -> None:
        self.settings.scale_mode = mode
        self._recalculate()

    def set_custom_scale(self, percent: float) -> None:
        self.settings.custom_scale = percent / 100.0
        self.settings.scale_mode   = "custom"
        self._recalculate()

    def set_alignment_mode(self, mode: str) -> None:
        self.settings.align_mode = mode
        self._emit_state()

    def set_alignment_offset(self, axis: str, value_mm: float) -> None:
        if axis == "x":
            self.settings.align_offset_x_mm = float(value_mm)
        elif axis == "y":
            self.settings.align_offset_y_mm = float(value_mm)
        self._emit_state()

    # ── Preview zoom (display only — does not affect print scale) ─────────────

    def set_preview_zoom(self, percent: int) -> None:
        self._preview_zoom = max(0.1, percent / 100.0)
        self._emit_state()

    def get_preview_zoom(self) -> float:
        return self._preview_zoom

    def step_preview_zoom(self, delta_percent: int) -> None:
        current = int(round(self._preview_zoom * 100.0))
        self.set_preview_zoom(current + int(delta_percent))

    def reset_preview_zoom(self) -> None:
        self.set_preview_zoom(100)

    # ── Guides ────────────────────────────────────────────────────────────────

    def set_guide(self, name: str, value: bool) -> None:
        if hasattr(self.settings, name):
            setattr(self.settings, name, value)
            self._emit_state()

    def toggle_preview_guides(self) -> None:
        self.settings.preview_guides_visible = not bool(
            getattr(self.settings, "preview_guides_visible", True)
        )
        self._emit_state()

    def set_guide_style(self, style: str) -> None:
        self.settings.guide_style = style
        self._emit_state()

    def set_guide_color(self, color: str) -> None:
        self.settings.guide_color = color
        self._emit_state()

    def set_bleed_mm(self, value_mm: float) -> None:
        self.settings.bleed_mm = max(0.0, float(value_mm))
        self._emit_state()

    def set_safe_area_mm(self, value_mm: float) -> None:
        self.settings.safe_area_mm = max(0.0, float(value_mm))
        self._emit_state()

    # ── Print Color Preset ────────────────────────────────────────────────────

    def set_preset(self, name: str, values: dict) -> None:
        """Apply a named or custom preset.  Triggers re-render and state emit."""
        self.settings.print_color_preset_name   = name
        self.settings.print_color_preset_values = dict(values) if values else {}
        self.settings.print_color_preset_enabled = bool(values)
        self.render_invalidated.emit()
        self._emit_state()

    def clear_preset(self) -> None:
        """Disable the active preset (select None)."""
        self.settings.print_color_preset_enabled = False
        self.settings.print_color_preset_name    = ""
        self.settings.print_color_preset_values  = {}
        self.render_invalidated.emit()
        self._emit_state()

    def get_preset_values(self) -> dict:
        """Return a copy of the currently active preset values dict."""
        return dict(self.settings.print_color_preset_values)

    # ── ICC / color management ────────────────────────────────────────────────

    def set_icc_setting(self, name: str, value) -> None:
        """Persist an ICC-related setting and trigger a preview re-render."""
        if hasattr(self.settings, name):
            setattr(self.settings, name, value)
            self.render_invalidated.emit()   # ICC changes affect the rendered pixels
            self._emit_state()

    # ── Preview refresh ───────────────────────────────────────────────────────

    def refresh_preview(self) -> None:
        """Force discard of the cached render and request a fresh repaint."""
        self.render_invalidated.emit()
        self._emit_state()

    # ── DPI / quality ─────────────────────────────────────────────────────────

    def set_dpi(self, dpi: int) -> None:
        self.settings.dpi = dpi
        self._recalculate()

    def set_mirror_output(self, enabled: bool) -> None:
        self.settings.mirror_output = bool(enabled)
        self.render_invalidated.emit()
        self._emit_state()

    # ── Quality warnings (pushed from host app) ───────────────────────────────

    def set_quality_warnings(self, warnings: list[str]) -> None:
        """Replace the host-supplied quality warnings and refresh the state."""
        self._host_warnings = list(warnings)
        self._emit_state()

    def push_quality_warning(self, message: str) -> None:
        """Append a single quality warning from the host app."""
        if message not in self._host_warnings:
            self._host_warnings.append(message)
            self._emit_state()

    def clear_quality_warnings(self) -> None:
        self._host_warnings = []
        self._emit_state()

    def update_render_analysis(self, ink_coverage_percent: float, ink_level: str) -> None:
        self._ink_coverage_percent = max(0.0, float(ink_coverage_percent or 0.0))
        self._ink_level = str(ink_level or "Low")
        self._emit_state()

    # ── Accessors ─────────────────────────────────────────────────────────────

    def get_metrics(self)  -> PrintMetrics:  return self.metrics
    def get_settings(self) -> PrintSettings: return self.settings
    def has_valid_printer(self) -> bool:     return self._has_valid_printer

    def apply_print_settings(self, settings_payload: dict) -> None:
        if not isinstance(settings_payload, dict):
            return

        field_names = {field.name for field in fields(PrintSettings)}
        printer_name = settings_payload.get("printer_name", self.settings.printer_name)
        self._suspend_auto_preset_load = True
        try:
            for name, value in settings_payload.items():
                if name not in field_names or name == "printer_name":
                    continue
                setattr(self.settings, name, copy.deepcopy(value))

            if printer_name != self.settings.printer_name:
                self.update_printer_by_name(printer_name or "")
            else:
                self._has_valid_printer = bool(self.settings.printer_name)
                self._recalculate()
        finally:
            self._suspend_auto_preset_load = False

        self.render_invalidated.emit()
        self._emit_state()

    def apply_driver_settings(self, driver_result: NativePrinterDriverSettingsResult, printer) -> None:
        self.settings.printer_name = driver_result.printer_name
        self.settings.native_devmode_bytes = driver_result.devmode_bytes
        self.settings.driver_orientation = driver_result.orientation
        self.settings.driver_paper_name = driver_result.paper_name
        self.settings.paper_type = driver_result.paper_name or self.settings.paper_type
        self.settings.driver_paper_width_mm = driver_result.paper_width_mm
        self.settings.driver_paper_height_mm = driver_result.paper_height_mm
        if driver_result.copies is not None:
            self.settings.driver_copies = driver_result.copies
        self.settings.driver_color_mode = driver_result.color_mode
        self.update_printer(printer)

    def get_current_preview_state(self) -> PreviewState:
        settings  = copy.deepcopy(self.settings)
        page_states = self._build_page_states()
        metrics = copy.deepcopy(
            page_states[self._page_index].metrics if page_states else self.metrics
        )
        # Shallow-copy page to avoid expensive deepcopy of image data;
        # the page is only read (not mutated) by the state consumers.
        page = self.current_page

        warnings: list[str] = list(self._host_warnings)
        warnings.extend(self._build_dynamic_warnings(metrics, settings))
        if not self._has_valid_printer:
            warnings.append("No valid printer configured. Open Printer Driver Settings before printing.")
        if self._is_scale_limited_by_printer(metrics, settings):
            warnings.append("Preview is scaled to fit the printer printable area.")
        if getattr(settings, "mirror_output", False):
            warnings.append("Ensure printer mirror setting is OFF when using software mirror.")

        # ICC warnings
        if settings.enable_color_management:
            if not self._icc.profile_exists(settings.output_profile):
                warnings.append(
                    f"ICC: Output profile '{settings.output_profile or '(none)'}' not found."
                )
            elif settings.soft_proof_preview:
                warnings.append("Soft Proof active — preview simulates printer output profile.")

        return PreviewState(
            page               = page,
            pages              = page_states,
            settings           = settings,
            metrics            = metrics,
            printer            = self.printer,
            adapter            = self.adapter,
            printer_name       = settings.printer_name,
            has_valid_printer  = self._has_valid_printer,
            can_print          = (page is not None and self._has_valid_printer),
            scale_limited_by_printer = self._is_scale_limited_by_printer(metrics, settings),
            page_index         = self._page_index,
            page_count         = self.page_count,
            warnings           = list(dict.fromkeys(warnings)),
            ink_coverage_percent = self._ink_coverage_percent,
            ink_level         = self._ink_level,
        )

    # ── Actions ───────────────────────────────────────────────────────────────

    def open_printer_settings(self) -> None:
        self.printer_settings_requested.emit()

    def request_print(self) -> None:
        state = self.get_current_preview_state()
        if not state.can_print:
            # Surface the warning via state signal so the UI can react
            self.preview_state_changed.emit(state)
            return
        self.print_requested.emit(state)

    def request_export(self) -> None:
        self.export_requested.emit(self.get_current_preview_state())

    # ── Internal ──────────────────────────────────────────────────────────────

    def _recalculate(self) -> None:
        if not self.current_page:
            self._emit_state()
            return

        design_w, design_h = self.adapter.get_design_page_size_mm(self.current_page)
        scale = self.scale_service.compute_scale(
            design_w, design_h,
            self.metrics.printable_width_mm,
            self.metrics.printable_height_mm,
            self.settings.scale_mode,
            self.settings.custom_scale,
        )
        self.metrics.scale            = scale
        self.metrics.output_width_mm  = design_w * scale
        self.metrics.output_height_mm = design_h * scale
        self._emit_state()

    def _build_page_states(self) -> list[PagePreviewState]:
        page_states: list[PagePreviewState] = []
        for page_index, page in enumerate(self._pages):
            design_w, design_h = self.adapter.get_design_page_size_mm(page)
            scale = self.scale_service.compute_scale(
                design_w,
                design_h,
                self.metrics.printable_width_mm,
                self.metrics.printable_height_mm,
                self.settings.scale_mode,
                self.settings.custom_scale,
            )
            metrics = copy.deepcopy(self.metrics)
            metrics.scale = scale
            metrics.output_width_mm = design_w * scale
            metrics.output_height_mm = design_h * scale
            page_states.append(
                PagePreviewState(
                    page=page,
                    metrics=metrics,
                    page_index=page_index,
                )
            )
        return page_states

    def _emit_state(self) -> None:
        self.metrics_changed.emit(self.metrics)
        self.settings_changed.emit(self.settings)
        self.preview_state_changed.emit(self.get_current_preview_state())

    def _resolve_printer_name(self, printer) -> str | None:
        if printer is None:
            return None
        try:
            name = printer.printerName()
        except Exception:
            name = ""
        return name or None

    def _is_scale_limited_by_printer(self, metrics: PrintMetrics, settings: PrintSettings) -> bool:
        if self.current_page is None:
            return False
        if settings.scale_mode not in ("fit_page", "fit_printable"):
            return False
        design_w, design_h = self.adapter.get_design_page_size_mm(self.current_page)
        restricted = (
            metrics.printable_width_mm  + 1e-6 < float(design_w)
            or metrics.printable_height_mm + 1e-6 < float(design_h)
        )
        return restricted and metrics.scale < 0.999

    def _build_dynamic_warnings(self, metrics: PrintMetrics, settings: PrintSettings) -> list[str]:
        images_by_id = getattr(self.adapter, "images_by_id", {}) or {}
        warnings = QualityAnalysisService.analyze_page(
            self.current_page,
            images_by_id,
            metrics,
            settings,
        )
        if PlacementService.is_clipped(metrics, settings):
            warnings.append("Current alignment causes clipping in the printable area.")
        return warnings

    def _auto_load_matching_preset(self) -> None:
        try:
            from print_preview.services.preset_service import PresetService

            match = PresetService.find_best_match(
                self.settings.printer_name,
                getattr(self.settings, "paper_type", "") or getattr(self.settings, "driver_paper_name", "") or "",
            )
        except Exception:
            match = None

        if not match:
            return
        preset_name, values = match
        if not values:
            return
        self.settings.print_color_preset_name = preset_name
        self.settings.print_color_preset_values = dict(values)
        self.settings.print_color_preset_enabled = True
