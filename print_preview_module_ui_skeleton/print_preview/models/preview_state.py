from dataclasses import dataclass, field

from print_preview.models.print_metrics import PrintMetrics
from print_preview.models.print_settings import PrintSettings


@dataclass(frozen=True)
class PagePreviewState:
    page: object | None
    metrics: PrintMetrics
    page_index: int = 0


@dataclass(frozen=True)
class PreviewState:
    page: object | None
    pages: list[PagePreviewState]
    settings: PrintSettings
    metrics: PrintMetrics
    printer: object | None
    adapter: object
    printer_name: str | None
    has_valid_printer: bool
    can_print: bool
    scale_limited_by_printer: bool

    # Multi-page navigation
    page_index: int = 0
    page_count: int = 1

    # Warnings from host app (quality checks, printer issues, etc.)
    warnings: list[str] = field(default_factory=list)

    # Live analysis derived from the rendered preview page.
    ink_coverage_percent: float = 0.0
    ink_level: str = "Low"
