from __future__ import annotations

import numpy as np

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from app.models.project import COLOR_EQUALIZER_NODE_COUNT, ColorEqualizerState
from app.utils.color_equalizer_processor import (
    COLOR_EQUALIZER_PRESETS,
    _sample_periodic_curve,
    apply_preset,
    channel_values,
    format_mode_value,
    reset_all,
    reset_channel,
    sanitize_color_equalizer_state,
)


_BTN_QSS = """
    QPushButton {
        background: rgba(255,255,255,14); color: rgba(220,225,240,220);
        font-size: 10px; border: 1px solid rgba(255,255,255,26);
        border-radius: 6px; padding: 4px 9px;
    }
    QPushButton:hover { background: rgba(255,255,255,24); }
    QPushButton:pressed { background: rgba(80,160,255,120); border-color: #50a0ff; }
"""
_BTN_ACTIVE_QSS = """
    QPushButton {
        background: rgba(80,160,255,130); color: rgba(235,242,255,245);
        font-size: 10px; font-weight: bold; border: 1px solid #50a0ff;
        border-radius: 6px; padding: 4px 9px;
    }
"""
_LBL_QSS = "color: rgba(155,165,185,220); font-size: 10px;"
_COMBO_QSS = """
    QComboBox {
        background: rgba(255,255,255,12);
        color: rgba(225,230,240,235);
        border: 1px solid rgba(255,255,255,24);
        border-radius: 6px;
        padding: 3px 8px;
        font-size: 10px;
    }
    QComboBox QAbstractItemView {
        background: rgba(25,30,40,245);
        color: rgba(225,230,240,235);
        selection-background-color: rgba(80,160,255,150);
    }
"""


class ColorEqualizerGraph(QWidget):
    changed = Signal(float)
    dragStateChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = 'saturation'
        self._state: ColorEqualizerState | None = None
        self._drag_index = -1
        self._hover_index = -1
        self.setMinimumHeight(196)
        self.setMouseTracking(True)

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def load_state(self, state: ColorEqualizerState) -> None:
        self._state = state
        self.update()

    def _graph_rect(self) -> QRectF:
        return QRectF(self.rect().adjusted(12, 10, -12, -26))

    def _strip_rect(self) -> QRectF:
        return QRectF(self.rect().adjusted(12, self.height() - 18, -12, -8))

    def _mode_values(self) -> list[float]:
        if self._state is None:
            return [0.0] * COLOR_EQUALIZER_NODE_COUNT
        sanitize_color_equalizer_state(self._state)
        return list(getattr(self._state, f'{self._mode}_values'))

    def _point_pos(self, index: int, value: float) -> QPointF:
        rect = self._graph_rect()
        x = rect.left() + (rect.width() * index / max(1, COLOR_EQUALIZER_NODE_COUNT - 1))
        y = rect.center().y() - value * (rect.height() * 0.42)
        return QPointF(x, y)

    def _value_from_y(self, y: float) -> float:
        rect = self._graph_rect()
        value = (rect.center().y() - y) / max(1.0, rect.height() * 0.42)
        return max(-1.0, min(1.0, float(value)))

    def _nearest_index(self, pos: QPointF) -> int:
        nearest = -1
        nearest_dist = 18.0
        for idx, value in enumerate(self._mode_values()):
            pt = self._point_pos(idx, value)
            dist = (pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2
            if dist <= nearest_dist ** 2:
                nearest = idx
                nearest_dist = dist ** 0.5
        return nearest

    def _band_rect_for_index(self, index: int) -> QRectF:
        rect = self._graph_rect()
        band_w = rect.width() / max(1, COLOR_EQUALIZER_NODE_COUNT)
        center_x = rect.left() + (rect.width() * index / max(1, COLOR_EQUALIZER_NODE_COUNT - 1))
        return QRectF(center_x - band_w * 0.6, rect.top(), band_w * 1.2, rect.height())

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        graph_rect = self._graph_rect()
        strip_rect = self._strip_rect()
        values = self._mode_values()
        active_index = self._drag_index if self._drag_index >= 0 else self._hover_index

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 12))
        p.drawRoundedRect(graph_rect, 10, 10)

        if active_index >= 0:
            p.setBrush(QColor(80, 160, 255, 26))
            p.drawRoundedRect(self._band_rect_for_index(active_index), 8, 8)

        p.setPen(QPen(QColor(255, 255, 255, 24), 1))
        for step in range(1, 4):
            y = graph_rect.top() + graph_rect.height() * step / 4.0
            p.drawLine(graph_rect.left(), y, graph_rect.right(), y)

        zero_y = graph_rect.center().y()
        p.setPen(QPen(QColor(80, 160, 255, 120), 1.3))
        p.drawLine(graph_rect.left(), zero_y, graph_rect.right(), zero_y)

        path = QPainterPath()
        samples = 192
        for idx in range(samples + 1):
            frac = idx / samples
            sample_value = float(_sample_periodic_curve(values, np.array([frac], dtype=np.float32))[0])
            x = graph_rect.left() + graph_rect.width() * frac
            y = graph_rect.center().y() - sample_value * (graph_rect.height() * 0.42)
            if idx == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        p.setPen(QPen(QColor(135, 205, 255, 220), 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        node_colors = [
            QColor(235, 92, 88),
            QColor(239, 147, 72),
            QColor(235, 207, 77),
            QColor(117, 202, 94),
            QColor(86, 205, 205),
            QColor(80, 146, 255),
            QColor(152, 118, 255),
            QColor(219, 84, 193),
        ]
        for idx, value in enumerate(values):
            pt = self._point_pos(idx, value)
            is_active = idx == active_index
            p.setPen(QPen(QColor(255, 255, 255, 220 if is_active else 170), 1.4 if is_active else 1.2))
            p.setBrush(node_colors[idx % len(node_colors)])
            radius = 6.0 if is_active else 5.3
            p.drawEllipse(pt, radius, radius)

        grad = QLinearGradient(strip_rect.topLeft(), strip_rect.topRight())
        stops = [
            (0.00, QColor(235, 92, 88)),
            (0.14, QColor(239, 147, 72)),
            (0.28, QColor(235, 207, 77)),
            (0.42, QColor(117, 202, 94)),
            (0.56, QColor(86, 205, 205)),
            (0.70, QColor(80, 146, 255)),
            (0.84, QColor(152, 118, 255)),
            (1.00, QColor(219, 84, 193)),
        ]
        for stop, color in stops:
            grad.setColorAt(stop, color)
        p.setPen(QPen(QColor(255, 255, 255, 38), 1))
        p.setBrush(grad)
        p.drawRoundedRect(strip_rect, 5, 5)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton or self._state is None:
            return
        self._drag_index = self._nearest_index(event.position())
        if self._drag_index >= 0:
            self.dragStateChanged.emit(True)
            self._apply_drag(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        hover_index = self._nearest_index(event.position())
        if hover_index != self._hover_index and self._drag_index < 0:
            self._hover_index = hover_index
            self.update()
        if self._drag_index >= 0 and self._state is not None:
            self._apply_drag(event)
        else:
            self.setCursor(Qt.OpenHandCursor if hover_index >= 0 else Qt.ArrowCursor)

    def mouseReleaseEvent(self, _: QMouseEvent) -> None:
        if self._drag_index >= 0:
            self.dragStateChanged.emit(False)
        self._drag_index = -1
        self.setCursor(Qt.ArrowCursor)
        QToolTip.hideText()
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._state is None:
            return
        idx = self._nearest_index(event.position())
        if idx < 0:
            return
        values = getattr(self._state, f'{self._mode}_values')
        if abs(values[idx]) > 1e-4:
            values[idx] = 0.0
            QToolTip.showText(event.globalPosition().toPoint(), f'{format_mode_value(self._mode, 0.0)}', self)
            self.changed.emit(0.0)
            self.update()

    def leaveEvent(self, _) -> None:
        if self._drag_index < 0 and self._hover_index != -1:
            self._hover_index = -1
            self.update()

    def _apply_drag(self, event: QMouseEvent) -> None:
        if self._state is None or self._drag_index < 0:
            return
        values = getattr(self._state, f'{self._mode}_values')
        new_value = self._value_from_y(event.position().y())
        if abs(values[self._drag_index] - new_value) < 0.002:
            return
        values[self._drag_index] = new_value
        self._hover_index = self._drag_index
        QToolTip.showText(event.globalPosition().toPoint(), format_mode_value(self._mode, new_value), self)
        self.changed.emit(new_value)
        self.update()


class _HoldPreviewButton(QPushButton):
    pressedStateChanged = Signal(bool)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.pressedStateChanged.emit(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.pressedStateChanged.emit(False)
        super().mouseReleaseEvent(event)


class ColorEqualizerWidget(QWidget):
    changed = Signal()
    previewOriginalPressed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state: ColorEqualizerState | None = None
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        title = QLabel('Color Equalizer')
        title.setStyleSheet('color: rgba(220,225,240,240); font-size: 11px; font-weight: bold;')
        root.addWidget(title)

        modes_row = QHBoxLayout()
        modes_row.setSpacing(6)
        self.mode_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ('hue', 'Hue'),
            ('saturation', 'Saturation'),
            ('brightness', 'Brightness'),
        ):
            btn = QPushButton(label)
            btn.setStyleSheet(_BTN_QSS)
            btn.clicked.connect(lambda _, mode=key: self._set_mode(mode))
            self.mode_buttons[key] = btn
            modes_row.addWidget(btn)
        root.addLayout(modes_row)

        self.graph = ColorEqualizerGraph()
        self.graph.changed.connect(self._on_graph_changed)
        root.addWidget(self.graph)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        self.preset_combo = QComboBox()
        self.preset_combo.setStyleSheet(_COMBO_QSS)
        self.preset_combo.addItem('Quick Presets')
        for name in COLOR_EQUALIZER_PRESETS.keys():
            self.preset_combo.addItem(name)
        self.preset_apply_btn = QPushButton('Apply Preset')
        self.preset_apply_btn.setStyleSheet(_BTN_QSS)
        self.preset_apply_btn.clicked.connect(self._apply_selected_preset)
        preset_row.addWidget(self.preset_combo, 1)
        preset_row.addWidget(self.preset_apply_btn)
        root.addLayout(preset_row)

        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet(_LBL_QSS)
        root.addWidget(self.hint_label)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self.enable_btn = QPushButton('Effect Off')
        self.enable_btn.setCheckable(True)
        self.enable_btn.setStyleSheet(_BTN_QSS)
        self.enable_btn.clicked.connect(self._toggle_enabled)
        self.before_btn = _HoldPreviewButton('Hold Before')
        self.before_btn.setStyleSheet(_BTN_QSS)
        self.before_btn.pressedStateChanged.connect(self.previewOriginalPressed.emit)
        self.reset_mode_btn = QPushButton('Reset Current')
        self.reset_mode_btn.setStyleSheet(_BTN_QSS)
        self.reset_mode_btn.clicked.connect(self._reset_current)
        self.reset_all_btn = QPushButton('Reset All')
        self.reset_all_btn.setStyleSheet(_BTN_QSS)
        self.reset_all_btn.clicked.connect(self._reset_all)
        bottom.addWidget(self.enable_btn)
        bottom.addWidget(self.before_btn)
        bottom.addStretch()
        bottom.addWidget(self.reset_mode_btn)
        bottom.addWidget(self.reset_all_btn)
        root.addLayout(bottom)

        self._refresh_mode_ui()

    def load_state(self, state: ColorEqualizerState) -> None:
        self._loading = True
        self._state = sanitize_color_equalizer_state(state)
        self.graph.load_state(self._state)
        self._refresh_mode_ui()
        self._loading = False

    def _set_mode(self, mode: str) -> None:
        if self._state is None or self._state.active_mode == mode:
            return
        self._state.active_mode = mode
        self._refresh_mode_ui()
        self.changed.emit()

    def _toggle_enabled(self) -> None:
        if self._state is None or self._loading:
            return
        self._state.enabled = self.enable_btn.isChecked()
        self._refresh_mode_ui()
        self.changed.emit()

    def _apply_selected_preset(self) -> None:
        if self._state is None:
            return
        preset_name = self.preset_combo.currentText()
        if preset_name == 'Quick Presets':
            return
        if apply_preset(self._state, preset_name):
            self.graph.update()
            self._refresh_mode_ui()
            self.changed.emit()

    def _reset_current(self) -> None:
        if self._state is None:
            return
        reset_channel(self._state, self._state.active_mode)
        self.graph.update()
        self._refresh_mode_ui()
        self.changed.emit()

    def _reset_all(self) -> None:
        if self._state is None:
            return
        reset_all(self._state)
        self._state.enabled = False
        self.graph.update()
        self._refresh_mode_ui()
        self.changed.emit()

    def _on_graph_changed(self, _: float) -> None:
        if self._state is None or self._loading:
            return
        self._state.enabled = True
        self._refresh_mode_ui()
        self.changed.emit()

    def _refresh_mode_ui(self) -> None:
        state = sanitize_color_equalizer_state(self._state or ColorEqualizerState())
        self.graph.set_mode(state.active_mode)
        self.graph.load_state(state)

        descriptions = {
            'hue': 'Shift each hue family gently around the color wheel. Double-click a point to reset it.',
            'saturation': 'Boost or soften specific colors with safer protection for skin, neutrals and strong highlights.',
            'brightness': 'Lift or calm selected hue families while keeping circular transitions smooth.',
        }
        self.hint_label.setText(descriptions[state.active_mode])

        values = channel_values(state)
        for mode, btn in self.mode_buttons.items():
            btn.setStyleSheet(_BTN_ACTIVE_QSS if mode == state.active_mode else _BTN_QSS)
        self.enable_btn.setChecked(state.enabled)
        self.enable_btn.setText('Effect On' if state.enabled else 'Effect Off')
        self.enable_btn.setStyleSheet(_BTN_ACTIVE_QSS if state.enabled else _BTN_QSS)
        active_values = values[state.active_mode]
        has_mode_adjustment = any(abs(v) > 1e-4 for v in active_values)
        self.reset_mode_btn.setEnabled(has_mode_adjustment)
        has_any_adjustment = any(abs(v) > 1e-4 for channel in values.values() for v in channel)
        self.reset_all_btn.setEnabled(has_any_adjustment or state.enabled)
