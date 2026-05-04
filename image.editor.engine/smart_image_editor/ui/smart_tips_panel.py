from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QListWidget, QPushButton, QTextEdit, QVBoxLayout

from smart_image_editor.core.photo_tips import PhotoTipsService
from smart_image_editor.ui.i18n import Translator, translate_widget_tree


class SmartTipsPanel(QFrame):
    apply_fix_requested = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setObjectName("Panel")
        self.service = PhotoTipsService()
        self.current_tip = None
        self.translator = Translator()

        layout = QVBoxLayout(self)
        title = QLabel("Smart Photo Tips")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        self.category_combo = QComboBox()
        self._load_categories()
        self.category_combo.currentIndexChanged.connect(self._load_current_category)
        layout.addWidget(self.category_combo)

        self.tip_list = QListWidget()
        self.tip_list.currentRowChanged.connect(self._show_selected_tip)
        layout.addWidget(self.tip_list, 1)

        self.details = QTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 2)

        self.apply_btn = QPushButton("Apply Suggested Fix")
        self.apply_btn.clicked.connect(self._apply_current)
        self.apply_btn.setEnabled(False)
        layout.addWidget(self.apply_btn)

        if self.category_combo.count():
            self._load_current_category()

    def refresh_language(self, translator: Translator) -> None:
        self.translator = translator
        translate_widget_tree(self, translator)
        current_category = self.category_combo.currentText()
        current_category = self.category_combo.currentData() or current_category
        current_row = self.tip_list.currentRow()
        self._load_categories(current_category)
        self._load_category(current_category)
        if current_row >= 0:
            self.tip_list.setCurrentRow(min(current_row, self.tip_list.count() - 1))
        self._show_selected_tip(self.tip_list.currentRow())

    def _load_categories(self, current_category: str | None = None) -> None:
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        for category in self.service.get_categories():
            self.category_combo.addItem(self.translator.text(category), category)
        self.category_combo.blockSignals(False)
        if current_category:
            index = self.category_combo.findData(current_category)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)

    def _load_current_category(self, *_args) -> None:
        category = self.category_combo.currentData() or self.category_combo.currentText()
        self._load_category(category)

    def _load_category(self, category: str):
        self.tip_list.clear()
        self.tips = self.service.get_tips_by_category(category)
        for tip in self.tips:
            self.tip_list.addItem(self.translator.text(tip["title"]))
        if self.tips:
            self.tip_list.setCurrentRow(0)
        else:
            self.current_tip = None
            self.details.clear()
            self.apply_btn.setEnabled(False)

    def _show_selected_tip(self, row: int):
        if row < 0 or row >= len(getattr(self, "tips", [])):
            return
        self.current_tip = self.tips[row]
        tip = self.current_tip
        tr = self.translator.text
        html = [f"<h2>{tr(tip['title'])}</h2>"]
        if tip.get("problem"):
            html.append(f"<h3>{tr('Problem')}</h3><p>{tr(tip['problem'])}</p>")
        html.append(f"<h3>{tr('How to identify')}</h3><ul>")
        for item in tip.get("symptoms", []):
            html.append(f"<li>{item}</li>")
        html.append(f"</ul><h3>{tr('Recommended correction order')}</h3><ol>")
        for step in tip.get("recommended_steps", []):
            html.append(f"<li><b>{step['tool']}</b>: {step['action']} <i>({step.get('suggested_range', '')})</i></li>")
        html.append(f"</ol><h3>{tr('Warnings')}</h3><ul>")
        for warning in tip.get("warnings", []):
            html.append(f"<li>{warning}</li>")
        html.append("</ul>")
        self.details.setHtml("".join(html))
        auto_fix = tip.get("future_auto_fix", {})
        self.apply_btn.setEnabled(bool(auto_fix.get("enabled") and auto_fix.get("params")))

    def _apply_current(self):
        if not self.current_tip:
            return
        auto_fix = self.current_tip.get("future_auto_fix", {})
        if not auto_fix.get("enabled"):
            return
        params = auto_fix.get("params", {})
        if params:
            self.apply_fix_requested.emit(params)
