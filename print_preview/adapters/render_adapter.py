class RenderAdapter:
    def render_preview_page(self, page, scale: float, settings=None):
        """Render page for preview using the supplied print scale."""
        raise NotImplementedError

    def render_export_page(self, page, dpi: int, scale: float = 1.0, settings=None):
        """Render page for export/print.

        *settings* is an optional PrintSettings object; when provided and
        ``enable_color_management`` is True the implementation should apply
        the ICC transform before returning the image.
        """
        raise NotImplementedError

    def get_design_page_size_mm(self, page):
        raise NotImplementedError
