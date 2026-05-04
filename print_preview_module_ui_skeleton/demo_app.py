from PySide6.QtWidgets import QApplication
from print_preview.adapters.render_adapter import RenderAdapter
from print_preview.controller.print_preview_controller import PrintPreviewController
from print_preview.ui.main_window import PrintPreviewWindow
import sys

class DemoRenderAdapter(RenderAdapter):
    def render_preview_page(self, page, scale: float, settings=None):
        return None

    def render_export_page(self, page, dpi: int, scale: float = 1.0, settings=None):
        return None

    def get_design_page_size_mm(self, page):
        return page.get("width_mm", 210), page.get("height_mm", 297)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    adapter = DemoRenderAdapter()
    controller = PrintPreviewController(adapter)
    controller.set_page({"name": "A4 Portrait", "width_mm": 210, "height_mm": 297})
    window = PrintPreviewWindow(controller)
    window.show()
    sys.exit(app.exec())
