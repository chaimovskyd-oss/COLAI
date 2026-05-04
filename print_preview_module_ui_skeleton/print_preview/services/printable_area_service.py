from print_preview.models.print_metrics import PrintMetrics


class PrintableAreaService:
    """Derives printable area and margin data from a QPrinter or from defaults."""

    def calculate_from_printer(self, printer=None) -> PrintMetrics:
        """Return PrintMetrics populated from printer capabilities.

        Falls back to A4 / 10 mm margins when no printer is provided or
        when the printer object cannot supply page-layout information.
        """
        metrics = PrintMetrics()
        if printer is None:
            return metrics

        try:
            # Qt6 / PySide6: page layout is the authoritative source
            from PySide6.QtGui import QPageLayout

            layout = printer.pageLayout()
            unit = QPageLayout.Unit.Millimeter

            full_rect = layout.fullRect(unit)       # entire paper
            paint_rect = layout.paintRect(unit)     # printable area
            margins = layout.margins(unit)           # QMarginsF in mm

            paper_w = full_rect.width()
            paper_h = full_rect.height()

            if paper_w > 1 and paper_h > 1:
                metrics.paper_width_mm = paper_w
                metrics.paper_height_mm = paper_h
                metrics.printable_width_mm = max(1.0, paint_rect.width())
                metrics.printable_height_mm = max(1.0, paint_rect.height())
                metrics.margin_top_mm = max(0.0, margins.top())
                metrics.margin_bottom_mm = max(0.0, margins.bottom())
                metrics.margin_left_mm = max(0.0, margins.left())
                metrics.margin_right_mm = max(0.0, margins.right())

        except Exception:
            # Return defaults — never crash the preview over printer API quirks
            pass

        return metrics

    # ── Utility helpers ─────────────────────────────────────────

    def get_available_printers(self) -> list[str]:
        """Return display names of all printers available on this machine."""
        try:
            from PySide6.QtPrintSupport import QPrinterInfo
            return [info.printerName() for info in QPrinterInfo.availablePrinters()]
        except Exception:
            return []

    def get_default_printer_name(self) -> str:
        try:
            from PySide6.QtPrintSupport import QPrinterInfo
            return QPrinterInfo.defaultPrinter().printerName()
        except Exception:
            return ""
