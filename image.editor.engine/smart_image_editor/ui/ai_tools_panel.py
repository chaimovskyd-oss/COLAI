"""AI Tools Panel — dock-widget UI for artistic and AI-based effects.

Sections
────────
  Artistic Effects   Cartoon · Sketch · Coloring Page · Posterize
  AI Styles          Anime Style · Soft Cartoon (soon) · Comic (soon)
  Controls           Strength · Detail · Edge Thickness  + Apply / Clear

Signals emitted
───────────────
  param_changed(key, value)          → editor_window.update_param
  effect_apply_requested(effect_id)  → makes the effect live (non-destructive)
  effect_clear_requested()           → clears active effect
  effect_preview_requested(effect_id)  → show hover overlay
  effect_preview_clear_requested()     → hide overlay
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from smart_image_editor.ai_tools.ai_tools_service import EFFECT_REGISTRY, default_ai_tools_params


# ---------------------------------------------------------------------------
# Effect card widget
# ---------------------------------------------------------------------------

class EffectCard(QToolButton):
    """Checkable button that represents one effect in the grid."""

    hovered = Signal(str)
    unhovered = Signal(str)

    def __init__(self, effect_id: str, label: str, icon: str, placeholder: bool = False):
        super().__init__()
        self.effect_id = effect_id
        self.placeholder = placeholder
        self.setCheckable(not placeholder)
        self.setObjectName("EffectCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(54)
        self.setMinimumWidth(90)

        if placeholder:
            self.setText(f"{icon}\n{label}\n·soon·")
            self.setEnabled(False)
            self.setToolTip("Coming soon")
        else:
            self.setText(f"{icon}\n{label}")
            self.setToolTip(EFFECT_REGISTRY[effect_id].description)

        self.setStyleSheet(self._style(False))

    def set_active(self, active: bool) -> None:
        self.setChecked(active and not self.placeholder)
        self.setStyleSheet(self._style(active and not self.placeholder))

    def enterEvent(self, event):
        if not self.placeholder:
            self.hovered.emit(self.effect_id)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.placeholder:
            self.unhovered.emit(self.effect_id)
        super().leaveEvent(event)

    @staticmethod
    def _style(active: bool) -> str:
        if active:
            return (
                "QToolButton#EffectCard {"
                "background: #7c5cff; color: #ffffff;"
                "border: 2px solid #9d7cff;"
                "border-radius: 10px; font-size: 12px; font-weight: 700;"
                "}"
            )
        return (
            "QToolButton#EffectCard {"
            "background: #2a2b52; color: #c8c4e8;"
            "border: 1px solid #414274;"
            "border-radius: 10px; font-size: 12px;"
            "}"
            "QToolButton#EffectCard:hover {"
            "background: #35376a; border: 1px solid #7c5cff; color: #f4f0ff;"
            "}"
            "QToolButton#EffectCard:disabled {"
            "background: #20213b; color: #575784; border: 1px dashed #35376a;"
            "}"
        )


# ---------------------------------------------------------------------------
# Compact slider row
# ---------------------------------------------------------------------------

class ControlSlider(QFrame):
    changed = Signal(str, int)   # field, value

    def __init__(self, field: str, label: str, default: int = 0):
        super().__init__()
        self.field = field
        self.setObjectName("SliderRow")

        title = QLabel(label)
        title.setObjectName("SliderTitle")
        self._value_label = QLabel(str(default))
        self._value_label.setObjectName("SliderValue")
        self._value_label.setFixedWidth(28)
        self._value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 100)
        self._slider.setValue(default)
        self._slider.valueChanged.connect(self._on_change)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self._value_label)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 6)
        layout.addLayout(top)
        layout.addWidget(self._slider)

    def set_value(self, v: int) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(int(v))
        self._slider.blockSignals(False)
        self._value_label.setText(str(int(v)))

    def _on_change(self, v: int) -> None:
        self._value_label.setText(str(v))
        self.changed.emit(self.field, v)


# ---------------------------------------------------------------------------
# Section header
# ---------------------------------------------------------------------------

def _make_section_label(text: str, color: str = "#7c5cff") -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"QLabel {{ color: {color}; font-weight: 700; font-size: 12px;"
        "border-left: 3px solid " + color + "; padding-left: 6px; margin-top: 8px; }}"
    )
    return lbl


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class AiToolsPanel(QWidget):
    """The full AI Tools side panel embedded in a QDockWidget."""

    param_changed = Signal(str, object)
    effect_apply_requested = Signal(str)
    effect_clear_requested = Signal()
    effect_preview_requested = Signal(str)
    effect_preview_clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AiToolsPanel")
        self.setMinimumWidth(260)

        self._params: dict = default_ai_tools_params()
        self._cards: dict[str, EffectCard] = {}
        self._card_group = QButtonGroup(self)
        self._card_group.setExclusive(False)   # we handle exclusivity manually

        self._edge_slider: ControlSlider | None = None

        self._build_ui()

    # ── Public API ────────────────────────────────────────────────────────────

    def sync_from_params(self, params: dict) -> None:
        """Called by EditorWindow after undo/redo/preset to realign UI."""
        ai = params.get("ai_tools") or default_ai_tools_params()
        self._params = dict(ai)
        active = ai.get("active_effect", "")

        for eid, card in self._cards.items():
            card.set_active(eid == active)

        self._strength_slider.set_value(int(ai.get("strength", 70)))
        self._detail_slider.set_value(int(ai.get("detail", 60)))
        if self._edge_slider:
            self._edge_slider.set_value(int(ai.get("edge_thickness", 40)))

        self._update_edge_visibility(active)
        self._update_apply_btn(active)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setObjectName("ToolScroll")

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.setSpacing(4)

        # ── Artistic Effects ─────────────────────────────────────────────────
        content_layout.addWidget(_make_section_label("Artistic Effects", "#69f0d5"))
        content_layout.addWidget(self._build_effect_grid(
            [eid for eid, s in EFFECT_REGISTRY.items() if s.category == "artistic"]
        ))

        # ── AI Styles ────────────────────────────────────────────────────────
        content_layout.addWidget(_make_section_label("AI Styles", "#ff6b9d"))
        content_layout.addWidget(self._build_effect_grid(
            [eid for eid, s in EFFECT_REGISTRY.items() if s.category == "ai"]
        ))

        # ── Controls ─────────────────────────────────────────────────────────
        content_layout.addWidget(_make_section_label("Controls", "#ffcf5c"))

        self._strength_slider = ControlSlider("strength", "Strength", default=70)
        self._detail_slider = ControlSlider("detail", "Detail", default=60)
        self._edge_slider = ControlSlider("edge_thickness", "Edge Thickness", default=40)

        for sl in (self._strength_slider, self._detail_slider, self._edge_slider):
            sl.changed.connect(self._on_control_changed)
            content_layout.addWidget(sl)

        # ── Action buttons ───────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(8, 8, 8, 4)

        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setToolTip("Make this effect active (non-destructive)")
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        self._apply_btn.setEnabled(False)

        self._clear_btn = QPushButton("Clear Effect")
        self._clear_btn.setObjectName("MiniButton")
        self._clear_btn.setToolTip("Remove the active effect")
        self._clear_btn.clicked.connect(self._on_clear_clicked)

        btn_row.addWidget(self._apply_btn)
        btn_row.addWidget(self._clear_btn)
        content_layout.addLayout(btn_row)
        content_layout.addStretch()

        scroll_area.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll_area)

    def _build_effect_grid(self, effect_ids: list[str]) -> QWidget:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(4, 2, 4, 4)
        grid.setSpacing(6)

        col_count = 2
        for i, eid in enumerate(effect_ids):
            spec = EFFECT_REGISTRY[eid]
            card = EffectCard(
                eid,
                spec.label,
                spec.icon,
                placeholder=(spec.apply is None),
            )
            card.hovered.connect(self.effect_preview_requested)
            card.unhovered.connect(lambda _: self.effect_preview_clear_requested.emit())
            card.clicked.connect(lambda checked=False, e=eid: self._on_card_clicked(e))
            self._cards[eid] = card
            self._card_group.addButton(card)
            grid.addWidget(card, i // col_count, i % col_count)

        return container

    # ── Slots ────────────────────────────────────────────────────────────────

    def _on_card_clicked(self, effect_id: str) -> None:
        current = self._params.get("active_effect", "")
        # Toggle off if already active
        new_active = "" if current == effect_id else effect_id

        for eid, card in self._cards.items():
            card.set_active(eid == new_active)

        self._params["active_effect"] = new_active
        self._update_edge_visibility(new_active)
        self._update_apply_btn(new_active)
        self._emit_params()
        self.effect_apply_requested.emit(new_active)

    def _on_control_changed(self, field: str, value: int) -> None:
        self._params[field] = value
        self._emit_params()

    def _on_apply_clicked(self) -> None:
        active = self._params.get("active_effect", "")
        if active:
            self.effect_apply_requested.emit(active)

    def _on_clear_clicked(self) -> None:
        for card in self._cards.values():
            card.set_active(False)
        self._params["active_effect"] = ""
        self._update_edge_visibility("")
        self._update_apply_btn("")
        self._emit_params()
        self.effect_clear_requested.emit()

    def _emit_params(self) -> None:
        self.param_changed.emit("ai_tools", dict(self._params))

    def _update_edge_visibility(self, active_id: str) -> None:
        if self._edge_slider is None:
            return
        spec = EFFECT_REGISTRY.get(active_id)
        self._edge_slider.setVisible(spec is not None and spec.uses_edge_thickness)

    def _update_apply_btn(self, active_id: str) -> None:
        self._apply_btn.setEnabled(bool(active_id))
