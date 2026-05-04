from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QToolButton


class PrintPreviewTopBar(QFrame):
    """Top bar with compact menus wired to existing preview functionality."""

    export_requested = Signal()
    print_requested = Signal()
    close_requested = Signal()
    zoom_in_requested = Signal()
    zoom_out_requested = Signal()
    reset_zoom_requested = Signal()
    toggle_guides_requested = Signal()
    printer_settings_requested = Signal()
    about_requested = Signal()

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setObjectName("TopBar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(10)

        title = QLabel("Print Preview Studio")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)
        layout.addSpacing(18)

        self.file_menu_button = self._build_menu_button("File", self._build_file_menu())
        self.view_menu_button = self._build_menu_button("View", self._build_view_menu())
        self.print_menu_button = self._build_menu_button("Print", self._build_print_menu())
        self.help_menu_button = self._build_menu_button("Help", self._build_help_menu())

        for button in (
            self.file_menu_button,
            self.view_menu_button,
            self.print_menu_button,
            self.help_menu_button,
        ):
            button.setMinimumHeight(36)
            button.setMinimumWidth(72)
            layout.addWidget(button)

        layout.addStretch()

        self.btn_printer_settings = QPushButton("Printer Driver Settings...")
        self.btn_printer_settings.setObjectName("PrimaryButton")
        self.btn_printer_settings.setMinimumHeight(36)
        self.btn_printer_settings.clicked.connect(self.printer_settings_requested)
        layout.addWidget(self.btn_printer_settings)

    def _build_menu_button(self, text: str, menu: QMenu) -> QToolButton:
        button = QToolButton(self)
        button.setText(text)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setMenu(menu)
        return button

    def _build_file_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Export", self.export_requested.emit)
        menu.addAction("Print", self.print_requested.emit)
        menu.addSeparator()
        menu.addAction("Close", self.close_requested.emit)
        return menu

    def _build_view_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Zoom In", self.zoom_in_requested.emit)
        menu.addAction("Zoom Out", self.zoom_out_requested.emit)
        menu.addAction("Reset Zoom", self.reset_zoom_requested.emit)
        menu.addSeparator()
        menu.addAction("Toggle Guides", self.toggle_guides_requested.emit)
        return menu

    def _build_print_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Printer Driver Settings", self.printer_settings_requested.emit)
        menu.addAction("Print", self.print_requested.emit)
        return menu

    def _build_help_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("About", self.about_requested.emit)
        return menu
