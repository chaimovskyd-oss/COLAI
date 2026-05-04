from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from smart_image_editor.core.adjustment_stack import Adjustment, TimelineEntry
from smart_image_editor.ui.i18n import Translator, translate_widget_tree


class HistoryPanel(QFrame):
    undo_requested = Signal()
    redo_requested = Signal()
    reset_all_requested = Signal()
    adjustment_enabled_changed = Signal(str, bool)
    adjustment_reset_requested = Signal(str)
    adjustment_delete_requested = Signal(str)
    adjustment_focus_requested = Signal(str)
    adjustment_hovered = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("Panel")
        self.active_items: dict[str, QListWidgetItem] = {}
        self.translator = Translator()

        layout = QVBoxLayout(self)
        title = QLabel("History")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        top = QHBoxLayout()
        self.undo_btn = QPushButton("Undo")
        self.redo_btn = QPushButton("Redo")
        self.reset_btn = QPushButton("Reset All")
        for button, signal in [
            (self.undo_btn, self.undo_requested),
            (self.redo_btn, self.redo_requested),
            (self.reset_btn, self.reset_all_requested),
        ]:
            button.setObjectName("MiniButton")
            button.clicked.connect(signal.emit)
            top.addWidget(button)
        layout.addLayout(top)

        active_label = QLabel("Active Adjustments")
        active_label.setObjectName("SectionTitle")
        layout.addWidget(active_label)
        self.active_list = QListWidget()
        self.active_list.setMouseTracking(True)
        self.active_list.itemClicked.connect(self._focus_item)
        self.active_list.itemEntered.connect(self._hover_item)
        layout.addWidget(self.active_list, 2)

        timeline_label = QLabel("Timeline")
        timeline_label.setObjectName("SectionTitle")
        layout.addWidget(timeline_label)
        self.timeline_list = QListWidget()
        layout.addWidget(self.timeline_list, 3)

    def refresh_language(self, translator: Translator) -> None:
        self.translator = translator
        translate_widget_tree(self, translator)

    def refresh(self, adjustments: list[Adjustment], timeline: list[TimelineEntry], can_undo: bool, can_redo: bool) -> None:
        self.undo_btn.setEnabled(can_undo)
        self.redo_btn.setEnabled(can_redo)
        self.active_list.clear()
        self.active_items.clear()
        for adjustment in adjustments:
            self._add_adjustment(adjustment)
        if not adjustments:
            item = QListWidgetItem(self.translator.text("No active adjustments"))
            item.setFlags(Qt.NoItemFlags)
            self.active_list.addItem(item)

        self.timeline_list.clear()
        for entry in timeline:
            item = QListWidgetItem(self._timeline_text(entry))
            self.timeline_list.addItem(item)
        if not timeline:
            item = QListWidgetItem(self.translator.text("No actions yet"))
            item.setFlags(Qt.NoItemFlags)
            self.timeline_list.addItem(item)

    def _add_adjustment(self, adjustment: Adjustment) -> None:
        item = QListWidgetItem()
        item.setData(Qt.UserRole, adjustment.id)
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(6, 4, 6, 4)
        checkbox = QCheckBox()
        checkbox.setChecked(adjustment.enabled)
        checkbox.toggled.connect(lambda enabled, key=adjustment.id: self.adjustment_enabled_changed.emit(key, enabled))
        label = QLabel(self.translator.text(adjustment.label))
        label.setMinimumWidth(110)
        value = QLabel(self._format_value(adjustment.value))
        value.setObjectName("SliderValue")
        reset = QPushButton(self.translator.text("Reset"))
        reset.setObjectName("MiniButton")
        reset.clicked.connect(lambda checked=False, key=adjustment.id: self.adjustment_reset_requested.emit(key))
        delete = QPushButton(self.translator.text("Delete"))
        delete.setObjectName("MiniButton")
        delete.clicked.connect(lambda checked=False, key=adjustment.id: self.adjustment_delete_requested.emit(key))
        row.addWidget(checkbox)
        row.addWidget(label, 1)
        row.addWidget(value)
        row.addWidget(reset)
        row.addWidget(delete)
        self.active_list.addItem(item)
        item.setSizeHint(widget.sizeHint())
        self.active_list.setItemWidget(item, widget)
        self.active_items[adjustment.id] = item

    def _focus_item(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.UserRole)
        if key:
            self.adjustment_focus_requested.emit(key)

    def _hover_item(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.UserRole)
        if key:
            self.adjustment_hovered.emit(key)

    def _format_value(self, value: Any) -> str:
        if isinstance(value, float):
            return f"{value:+.2f}"
        if isinstance(value, bool):
            return self.translator.text("on" if value else "off")
        if isinstance(value, int):
            return f"{value:+d}"
        if isinstance(value, dict):
            return self.translator.text("custom")
        if value is None:
            return "-"
        return str(value)

    def _timeline_text(self, entry: TimelineEntry) -> str:
        if entry.tool:
            return f"{entry.action}: {self._format_value(entry.value)}"
        return entry.action
