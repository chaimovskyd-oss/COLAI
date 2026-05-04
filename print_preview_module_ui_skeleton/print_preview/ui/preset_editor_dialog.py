"""Preset Editor and Manage Presets dialogs for the Print Color Preset system."""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from print_preview.services.preset_service import PresetService

_log = logging.getLogger(__name__)


# ── Parameter definitions ─────────────────────────────────────────────────────

_PARAMS = [
    # (key,                       label,           lo,    hi,   is_float)
    ("brightness",               "Brightness",    -100,  100,  False),
    ("contrast",                 "Contrast",      -100,  100,  False),
    ("exposure",                 "Exposure",      -100,  100,  False),
    ("saturation",               "Saturation",    -100,  100,  False),
    ("sharpness",                "Sharpness",     -100,  100,  False),
    ("gamma",                    "Gamma",          0.2,   4.0, True),
    ("r_level",                  "Red Level",     -100,  100,  False),
    ("g_level",                  "Green Level",   -100,  100,  False),
    ("b_level",                  "Blue Level",    -100,  100,  False),
    ("color_balance_shadows",    "CB Shadows",    -100,  100,  False),
    ("color_balance_midtones",   "CB Midtones",   -100,  100,  False),
    ("color_balance_highlights", "CB Highlights", -100,  100,  False),
]

# Integer scale factor stored internally for float sliders
_FLOAT_SCALE = 100


class _LabeledSlider(QWidget):
    """One parameter row: [slider ──────] value."""

    value_changed = Signal()

    def __init__(self, key: str, lo: float, hi: float, default: float, is_float: bool):
        super().__init__()
        self.key      = key
        self.is_float = is_float
        self._lo      = lo
        self._hi      = hi

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        if is_float:
            self._slider.setRange(int(lo * _FLOAT_SCALE), int(hi * _FLOAT_SCALE))
            self._slider.setValue(int(default * _FLOAT_SCALE))
        else:
            self._slider.setRange(int(lo), int(hi))
            self._slider.setValue(int(default))
        self._slider.setMinimumWidth(140)
        self._slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._val_lbl = QLabel(self._fmt(default))
        self._val_lbl.setObjectName("MetricValue")
        self._val_lbl.setMinimumWidth(44)
        self._val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        row.addWidget(self._slider, 1)
        row.addWidget(self._val_lbl)

        self._slider.valueChanged.connect(self._on_change)

    def _on_change(self, _raw: int):
        self._val_lbl.setText(self._fmt(self.get_value()))
        self.value_changed.emit()

    def _fmt(self, v: float) -> str:
        return f"{v:.2f}" if self.is_float else f"{int(v):+d}"

    def get_value(self) -> float:
        v = self._slider.value()
        return v / _FLOAT_SCALE if self.is_float else float(v)

    def set_value(self, v: float):
        iv = int(round(v * _FLOAT_SCALE)) if self.is_float else int(round(v))
        # Block signal during programmatic update to avoid spurious repaints
        was = self._slider.blockSignals(True)
        self._slider.setValue(iv)
        self._slider.blockSignals(was)
        self._val_lbl.setText(self._fmt(v))


# ── Main editor dialog ────────────────────────────────────────────────────────

class PresetEditorDialog(QDialog):
    """Slider-based editor for a single Print Color Preset.

    The dialog does NOT directly update the preview — it emits
    ``preview_values_changed(dict)`` on every slider move so the caller can
    call ``controller.set_preset("Custom", values)`` to get live preview
    feedback.  On Cancel the caller should restore the original preset values.
    """

    preview_values_changed = Signal(dict)

    def __init__(self, initial_values: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Print Color Preset")
        self.setMinimumWidth(500)
        self.setMinimumHeight(520)

        defaults = PresetService.default_values()
        current  = {**defaults, **(initial_values or {})}

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        # ── Hint ──────────────────────────────────────────────────────────────
        hint = QLabel("Adjust sliders — the main preview updates in real time.")
        hint.setObjectName("PanelSubtle")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # ── Sliders inside a scroll area ──────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body   = QWidget()
        form   = QFormLayout(body)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self._sliders: dict[str, _LabeledSlider] = {}
        for key, label, lo, hi, is_float in _PARAMS:
            default = current.get(key, 1.0 if is_float else 0)
            s = _LabeledSlider(key, lo, hi, default, is_float)
            s.value_changed.connect(self._on_any_change)
            form.addRow(label, s)
            self._sliders[key] = s

        # ── Reset button ──────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.clicked.connect(self._reset)
        btn_row.addWidget(btn_reset)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── OK / Cancel ───────────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_values(self) -> dict:
        """Return the current slider state as a values dict."""
        return {key: s.get_value() for key, s in self._sliders.items()}

    def set_values(self, values: dict):
        """Programmatically set all sliders (does not emit preview_values_changed)."""
        for key, s in self._sliders.items():
            if key in values:
                s.set_value(values[key])

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_any_change(self):
        self.preview_values_changed.emit(self.get_values())

    def _reset(self):
        defaults = PresetService.default_values()
        for key, s in self._sliders.items():
            s.set_value(defaults.get(key, 0))
        self.preview_values_changed.emit(self.get_values())


# ── Manage Presets dialog ─────────────────────────────────────────────────────

class ManagePresetsDialog(QDialog):
    """Lists all saved presets; allows deleting and renaming them."""

    presets_changed = Signal()   # emitted after any structural change

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Print Color Presets")
        self.setMinimumWidth(360)
        self.setMinimumHeight(300)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(16, 16, 16, 16)

        hint = QLabel("Saved presets.  Select a row to rename or delete it.")
        hint.setObjectName("PanelSubtle")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # Scroll area holds one row per preset
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        root.addWidget(self._scroll, 1)

        self._refresh_list()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _refresh_list(self):
        body   = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(6)
        layout.setContentsMargins(4, 4, 4, 4)

        names = PresetService.list_names()
        if not names:
            lbl = QLabel("No saved presets yet.")
            lbl.setObjectName("PanelSubtle")
            layout.addWidget(lbl)
        else:
            for name in names:
                row = QHBoxLayout()
                lbl = QLabel(name)
                lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                btn_rename = QPushButton("Rename")
                btn_rename.setFixedWidth(72)
                btn_delete = QPushButton("Delete")
                btn_delete.setFixedWidth(64)
                row.addWidget(lbl, 1)
                row.addWidget(btn_rename)
                row.addWidget(btn_delete)
                layout.addLayout(row)

                btn_rename.clicked.connect(lambda _, n=name: self._rename(n))
                btn_delete.clicked.connect(lambda _, n=name: self._delete(n))

        layout.addStretch()
        self._scroll.setWidget(body)

    def _rename(self, name: str):
        new_name, ok = QInputDialog.getText(
            self, "Rename Preset", "New name:", text=name
        )
        if ok and new_name.strip() and new_name.strip() != name:
            PresetService.rename(name, new_name.strip())
            self._refresh_list()
            self.presets_changed.emit()

    def _delete(self, name: str):
        if QMessageBox.question(
            self, "Delete Preset",
            f"Delete preset '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            PresetService.delete(name)
            self._refresh_list()
            self.presets_changed.emit()
