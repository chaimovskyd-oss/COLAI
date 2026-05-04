from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider


class PrintPreviewBottomBar(QFrame):
    """Bottom bar: zoom slider, page navigation, state banner, and action buttons."""

    zoom_changed = Signal(int)
    print_clicked = Signal()
    export_clicked = Signal()
    save_print_settings_clicked = Signal()

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setObjectName("BottomBar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 12, 22, 12)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Zoom"))

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setMinimum(10)
        self.zoom_slider.setMaximum(300)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(170)
        layout.addWidget(self.zoom_slider)

        self.zoom_label = QLabel("100 %")
        self.zoom_label.setMinimumWidth(56)
        layout.addWidget(self.zoom_label)
        layout.addSpacing(8)

        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedWidth(40)
        self.btn_prev.setMinimumHeight(38)
        self.btn_prev.setToolTip("Previous page")
        layout.addWidget(self.btn_prev)

        self.page_label = QLabel("Page 1 / 1")
        self.page_label.setMinimumWidth(108)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.page_label)

        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedWidth(40)
        self.btn_next.setMinimumHeight(38)
        self.btn_next.setToolTip("Next page")
        layout.addWidget(self.btn_next)
        layout.addSpacing(10)

        self.state_label = QLabel("")
        self.state_label.setObjectName("PanelSubtle")
        self.state_label.setWordWrap(True)
        self.state_label.setMinimumWidth(210)
        layout.addWidget(self.state_label, 1)
        layout.addSpacing(8)

        self.btn_refresh = QPushButton("↻")
        self.btn_refresh.setFixedWidth(40)
        self.btn_refresh.setMinimumHeight(38)
        self.btn_refresh.setToolTip("Refresh preview (force re-render)")

        self.btn_save_settings = QPushButton("שמור הגדרות הדפסה")
        self.btn_save_settings.setObjectName("PrimaryButton")
        self.btn_save_settings.setMinimumHeight(38)
        self.btn_save_settings.setMinimumWidth(170)

        self.btn_export = QPushButton("Export")
        self.btn_export.setObjectName("WarnButton")
        self.btn_export.setMinimumHeight(38)
        self.btn_export.setMinimumWidth(92)

        self.btn_print = QPushButton("Print")
        self.btn_print.setObjectName("SuccessButton")
        self.btn_print.setMinimumHeight(38)
        self.btn_print.setMinimumWidth(92)

        for btn in (self.btn_refresh, self.btn_save_settings, self.btn_export, self.btn_print):
            layout.addWidget(btn)

        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        self.btn_refresh.clicked.connect(self._on_refresh_clicked)
        self.btn_save_settings.clicked.connect(self._on_save_print_settings_clicked)
        self.btn_print.clicked.connect(self._on_print_clicked)
        self.btn_export.clicked.connect(self._on_export_clicked)
        self.btn_prev.clicked.connect(self._on_prev_page)
        self.btn_next.clicked.connect(self._on_next_page)

        controller.preview_state_changed.connect(self._on_preview_state_changed)
        self._update_nav_buttons(page_index=0, page_count=1)

    def _on_refresh_clicked(self):
        self.controller.refresh_preview()

    def _on_zoom_changed(self, value: int):
        self.zoom_label.setText(f"{value} %")
        self.controller.set_preview_zoom(value)
        self.zoom_changed.emit(value)

    def _on_save_print_settings_clicked(self):
        self.save_print_settings_clicked.emit()

    def _on_print_clicked(self):
        self.controller.request_print()
        self.print_clicked.emit()

    def _on_export_clicked(self):
        self.controller.request_export()
        self.export_clicked.emit()

    def _on_prev_page(self):
        self.controller.go_previous_page()

    def _on_next_page(self):
        self.controller.go_next_page()

    def _on_preview_state_changed(self, state):
        if state.warnings:
            self.state_label.setText(" | ".join(state.warnings))
        else:
            self.state_label.setText("Print will use the exact preview settings shown here.")

        self.btn_print.setEnabled(state.can_print)

        idx = getattr(state, "page_index", 0)
        count = getattr(state, "page_count", 1)
        self.page_label.setText(f"Page {idx + 1} / {count}")
        self._update_nav_buttons(idx, count)

    def _update_nav_buttons(self, page_index: int, page_count: int):
        self.btn_prev.setEnabled(page_index > 0)
        self.btn_next.setEnabled(page_index < page_count - 1)

    def set_page_info(self, current: int, total: int):
        self.page_label.setText(f"Page {current} / {total}")

    def set_zoom_percent(self, value: int):
        clamped = max(self.zoom_slider.minimum(), min(self.zoom_slider.maximum(), int(value)))
        self.zoom_slider.setValue(clamped)

    def step_zoom_percent(self, delta: int):
        self.set_zoom_percent(self.zoom_slider.value() + int(delta))
