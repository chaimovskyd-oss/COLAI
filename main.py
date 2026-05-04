from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow

# ---------------------------------------------------------------------------
# Dark theme — applied globally before any widget is created
# ---------------------------------------------------------------------------
_DARK_QSS = """
/* ── Base ─────────────────────────────────────────────────────────────── */
QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 12px;
}

/* ── Main window & central ───────────────────────────────────────────── */
QMainWindow, QDialog {
    background-color: #1a1a1a;
}

/* ── Scroll areas ────────────────────────────────────────────────────── */
QScrollArea {
    border: none;
    background-color: #1e1e1e;
}
QScrollArea > QWidget > QWidget {
    background-color: #1e1e1e;
}

/* ── Scrollbars ──────────────────────────────────────────────────────── */
QScrollBar:vertical {
    background: #1e1e1e;
    width: 7px;
    margin: 0;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #444;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #5a5a5a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #1e1e1e;
    height: 7px;
    margin: 0;
    border-radius: 3px;
}
QScrollBar::handle:horizontal {
    background: #444;
    border-radius: 3px;
    min-width: 20px;
}
QScrollBar::handle:horizontal:hover { background: #5a5a5a; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ── Buttons (default / secondary) ──────────────────────────────────── */
QPushButton {
    background-color: #2d2d2d;
    color: #d0d0d0;
    border: 1px solid #3d3d3d;
    border-radius: 6px;
    padding: 5px 12px;
    min-height: 24px;
}
QPushButton:hover {
    background-color: #363636;
    border-color: #505050;
    color: #f0f0f0;
}
QPushButton:pressed {
    background-color: #252525;
    border-color: #3a3a3a;
}
QPushButton:checked {
    background-color: #1a4a72;
    border-color: #4a9eff;
    color: #ffffff;
}
QPushButton:disabled {
    background-color: #252525;
    color: #555;
    border-color: #2d2d2d;
}

/* ── Inputs ──────────────────────────────────────────────────────────── */
QLineEdit, QTextEdit, QDoubleSpinBox, QSpinBox, QComboBox, QFontComboBox {
    background-color: #2a2a2a;
    color: #e0e0e0;
    border: 1px solid #3a3a3a;
    border-radius: 5px;
    padding: 3px 6px;
    selection-background-color: #1a4a72;
    selection-color: #ffffff;
    min-height: 22px;
}
QLineEdit:focus, QTextEdit:focus,
QDoubleSpinBox:focus, QSpinBox:focus,
QComboBox:focus, QFontComboBox:focus {
    border-color: #4a9eff;
}

/* ── SpinBox arrows ──────────────────────────────────────────────────── */
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background: #333;
    border: none;
    width: 16px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background: #444;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: none; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: none; }

/* ── ComboBox ────────────────────────────────────────────────────────── */
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #252525;
    color: #e0e0e0;
    border: 1px solid #3a3a3a;
    selection-background-color: #1a4a72;
    outline: none;
}

/* ── Sliders ─────────────────────────────────────────────────────────── */
QSlider::groove:horizontal {
    background: #333;
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #4a9eff;
    border: none;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover { background: #6ab0ff; }
QSlider::sub-page:horizontal {
    background: #1a4a72;
    border-radius: 2px;
}

/* ── Checkboxes ──────────────────────────────────────────────────────── */
QCheckBox {
    spacing: 6px;
    color: #d0d0d0;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border-radius: 4px;
    border: 1px solid #3a3a3a;
    background: #2a2a2a;
}
QCheckBox::indicator:checked {
    background: #4a9eff;
    border-color: #4a9eff;
}
QCheckBox::indicator:hover {
    border-color: #4a9eff;
}

/* ── Group boxes ─────────────────────────────────────────────────────── */
QGroupBox {
    color: #aaa;
    border: 1px solid #333;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 6px;
    font-weight: bold;
    font-size: 11px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 10px;
    color: #888;
}

/* ── List widgets ────────────────────────────────────────────────────── */
QListWidget {
    background-color: #222;
    border: 1px solid #333;
    border-radius: 6px;
    outline: none;
}
QListWidget::item {
    border-radius: 4px;
    padding: 2px;
    color: #d0d0d0;
}
QListWidget::item:selected {
    background-color: #1a4a72;
    color: #ffffff;
}
QListWidget::item:hover:!selected {
    background-color: #2d2d2d;
}

/* ── Menu bar & menus ────────────────────────────────────────────────── */
QMenuBar {
    background-color: #1a1a1a;
    color: #d0d0d0;
    border-bottom: 1px solid #2d2d2d;
}
QMenuBar::item:selected {
    background-color: #2d2d2d;
    border-radius: 4px;
}
QMenu {
    background-color: #252525;
    color: #d0d0d0;
    border: 1px solid #3a3a3a;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item:selected {
    background-color: #1a4a72;
    color: #ffffff;
    border-radius: 4px;
}
QMenu::separator {
    height: 1px;
    background: #3a3a3a;
    margin: 3px 0;
}

/* ── Status bar ──────────────────────────────────────────────────────── */
QStatusBar {
    background-color: #1a1a1a;
    color: #777;
    border-top: 1px solid #2d2d2d;
}

/* ── Tooltips ────────────────────────────────────────────────────────── */
QToolTip {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #4a9eff;
    border-radius: 4px;
    padding: 4px 6px;
}

/* ── Form labels ─────────────────────────────────────────────────────── */
QLabel {
    color: #c0c0c0;
    background: transparent;
}

/* ── Progress dialog ─────────────────────────────────────────────────── */
QProgressDialog {
    background-color: #252525;
}
QProgressBar {
    background: #2a2a2a;
    border: 1px solid #3a3a3a;
    border-radius: 4px;
    text-align: center;
    color: #e0e0e0;
}
QProgressBar::chunk {
    background: #4a9eff;
    border-radius: 3px;
}
"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName('Smart Collage Maker MVP')
    app.setStyleSheet(_DARK_QSS)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
