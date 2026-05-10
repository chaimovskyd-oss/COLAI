"""AlbumModePanel — the full Album Builder UI component.

Layout:
  ┌─────────────────────────────────────────────────────┐
  │  [⚙ הגדרות]  density ▾  [Hero ✓]  [▶ צור אלבום]   │  ← settings bar
  ├─────────────────────────────────────────────────────┤
  │                       CANVAS                         │  ← controlled by MainWindow
  ├─────────────────────────────────────────────────────┤
  │  [◀]  [ דף 1 ][ דף 2 ][ דף 3 ][ דף 4 ]...  [▶]  │  ← page tab bar
  └─────────────────────────────────────────────────────┘

Signals:
  generate_requested(AlbumSettings)  — user clicked "צור אלבום"
  cancel_requested()
  page_selected(page_index)          — user clicked a tab
  export_pdf_requested()
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.album_builder.models import AlbumSettings, AlbumState


# ─────────────────────────────────────────────────────────────────────────────
# Page tab button
# ─────────────────────────────────────────────────────────────────────────────

class _PageTab(QPushButton):
    """Single page tab button."""

    _STYLE_NORMAL = (
        'QPushButton{'
        '  background:#1e2a38; color:#8eaac8;'
        '  border:1px solid #2a3a50; border-bottom:none;'
        '  padding:4px 14px; font-size:11px;'
        '  border-radius:4px 4px 0 0;'
        '}'
        'QPushButton:hover{background:#253346; color:#c0d8f0;}'
    )
    _STYLE_ACTIVE = (
        'QPushButton{'
        '  background:#0d2137; color:#ffffff; font-weight:bold;'
        '  border:1px solid #4a9eff; border-bottom:2px solid #0d2137;'
        '  padding:4px 14px; font-size:11px;'
        '  border-radius:4px 4px 0 0;'
        '}'
    )

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setCheckable(True)
        self.setFixedHeight(28)
        self.setStyleSheet(self._STYLE_NORMAL)

    def set_active(self, active: bool) -> None:
        self.setChecked(active)
        self.setStyleSheet(self._STYLE_ACTIVE if active else self._STYLE_NORMAL)


# ─────────────────────────────────────────────────────────────────────────────
# Progress banner (matches _DepthToast style)
# ─────────────────────────────────────────────────────────────────────────────

class _AlbumProgressBanner(QWidget):
    cancel_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setStyleSheet('background:#0d2137; border-top:2px solid #4a9eff;')

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(12)

        icon = QLabel('📚')
        icon.setStyleSheet('font-size:18px; background:transparent;')
        icon.setFixedWidth(26)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.setContentsMargins(0, 0, 0, 0)
        self._stage_lbl = QLabel('מכין…')
        self._stage_lbl.setStyleSheet('color:#fff; font-weight:bold; font-size:12px; background:transparent;')
        self._detail_lbl = QLabel('')
        self._detail_lbl.setStyleSheet('color:#7aafe0; font-size:10px; background:transparent;')
        text_col.addWidget(self._stage_lbl)
        text_col.addWidget(self._detail_lbl)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedWidth(180)
        self._bar.setFixedHeight(8)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet(
            'QProgressBar{background:#1a3a5c;border-radius:4px;border:none;}'
            'QProgressBar::chunk{'
            '  background:qlineargradient(x1:0,y1:0,x2:1,y2:0,'
            '    stop:0 #4a9eff,stop:1 #00d4ff);'
            '  border-radius:4px;}'
        )

        _btn_style = (
            'QPushButton{background:#3a1a1a;color:#ff6b6b;border:1px solid #6b2020;'
            'border-radius:4px;padding:3px 10px;font-size:11px;}'
            'QPushButton:hover{background:#5a2020;}'
        )
        self._cancel_btn = QPushButton('ביטול')
        self._cancel_btn.setFixedHeight(22)
        self._cancel_btn.setStyleSheet(_btn_style)
        self._cancel_btn.clicked.connect(self.cancel_clicked)

        row.addWidget(icon)
        row.addLayout(text_col, 1)
        row.addWidget(self._bar, 0, Qt.AlignVCenter)
        row.addWidget(self._cancel_btn, 0, Qt.AlignVCenter)

    def update(self, stage: str, detail: str, pct: int) -> None:
        self._stage_lbl.setText(stage)
        self._detail_lbl.setText(detail)
        self._bar.setValue(max(0, min(100, pct)))


# ─────────────────────────────────────────────────────────────────────────────
# Main panel
# ─────────────────────────────────────────────────────────────────────────────

_BTN = (
    'QPushButton{background:rgba(255,255,255,18);color:#cdd6ef;'
    'border:1px solid rgba(255,255,255,22);border-radius:4px;'
    'font-size:11px;padding:2px 10px;}'
    'QPushButton:hover{background:rgba(255,255,255,34);}'
    'QPushButton:pressed{background:rgba(80,160,255,160);}'
    'QPushButton:disabled{color:#555;border-color:#333;}'
)
_BTN_PRIMARY = (
    'QPushButton{background:#1a5faa;color:#fff;border:1px solid #4a9eff;'
    'border-radius:4px;font-size:12px;font-weight:bold;padding:4px 18px;}'
    'QPushButton:hover{background:#2070c0;}'
    'QPushButton:pressed{background:#0d4080;}'
    'QPushButton:disabled{background:#1a2a3a;color:#555;border-color:#2a3a50;}'
)


class AlbumModePanel(QWidget):
    """Top settings bar + bottom page tab bar for Album Builder mode."""

    generate_requested = Signal(object)   # AlbumSettings
    cancel_requested = Signal()
    page_selected = Signal(int)           # page_index
    export_pdf_requested = Signal()
    regenerate_page_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._album_state: Optional[AlbumState] = None
        self._current_page = 0
        self._tab_buttons: list[_PageTab] = []
        self._build_ui()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        vlay = QVBoxLayout(self)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        vlay.addWidget(self._build_settings_bar())
        self._progress_banner = _AlbumProgressBanner()
        self._progress_banner.cancel_clicked.connect(self.cancel_requested)
        self._progress_banner.hide()
        vlay.addWidget(self._progress_banner)

        vlay.addWidget(self._build_tab_bar())

    def _build_settings_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(36)
        bar.setStyleSheet('background:#181f2a; border-bottom:1px solid #2a3a50;')
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(8)

        lbl = QLabel('🎞 מצב אלבום')
        lbl.setStyleSheet('color:#7aafe0; font-size:11px; font-weight:bold;')
        row.addWidget(lbl)
        row.addSpacing(8)

        density_lbl = QLabel('צפיפות:')
        density_lbl.setStyleSheet('color:#99a8c2; font-size:11px;')
        self._density_combo = QComboBox()
        self._density_combo.addItems(['מרווח', 'מאוזן', 'צפוף'])
        self._density_combo.setCurrentIndex(1)
        self._density_combo.setFixedWidth(80)
        self._density_combo.setStyleSheet(
            'QComboBox{background:#1e2a38;color:#c0d0e8;border:1px solid #2a3a50;'
            'border-radius:4px;padding:1px 6px;font-size:11px;}'
            'QComboBox::drop-down{border:none;}'
            'QComboBox QAbstractItemView{background:#1e2a38;color:#c0d0e8;'
            'selection-background-color:#2a4a70;}'
        )
        row.addWidget(density_lbl)
        row.addWidget(self._density_combo)

        self._hero_chk = QCheckBox('עמודי גיבורים')
        self._hero_chk.setChecked(True)
        self._hero_chk.setStyleSheet('color:#99a8c2; font-size:11px;')
        row.addWidget(self._hero_chk)

        row.addStretch(1)

        self._export_btn = QPushButton('📄 ייצוא PDF')
        self._export_btn.setStyleSheet(_BTN)
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self.export_pdf_requested)
        row.addWidget(self._export_btn)

        self._generate_btn = QPushButton('▶  צור אלבום')
        self._generate_btn.setStyleSheet(_BTN_PRIMARY)
        self._generate_btn.setFixedHeight(26)
        self._generate_btn.clicked.connect(self._on_generate_clicked)
        row.addWidget(self._generate_btn)

        return bar

    def _build_tab_bar(self) -> QWidget:
        wrap = QWidget()
        wrap.setFixedHeight(34)
        wrap.setStyleSheet('background:#0d1420; border-top:1px solid #2a3a50;')

        row = QHBoxLayout(wrap)
        row.setContentsMargins(6, 4, 6, 0)
        row.setSpacing(3)

        self._prev_btn = QPushButton('◀')
        self._prev_btn.setFixedSize(22, 22)
        self._prev_btn.setStyleSheet(_BTN)
        self._prev_btn.clicked.connect(self._on_prev_page)
        row.addWidget(self._prev_btn)

        # Scrollable tab area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedHeight(30)
        scroll.setStyleSheet('background:transparent;')

        self._tab_container = QWidget()
        self._tab_container.setStyleSheet('background:transparent;')
        self._tabs_row = QHBoxLayout(self._tab_container)
        self._tabs_row.setContentsMargins(0, 0, 0, 0)
        self._tabs_row.setSpacing(2)
        self._tabs_row.addStretch(1)

        scroll.setWidget(self._tab_container)
        row.addWidget(scroll, 1)

        self._next_btn = QPushButton('▶')
        self._next_btn.setFixedSize(22, 22)
        self._next_btn.setStyleSheet(_BTN)
        self._next_btn.clicked.connect(self._on_next_page)
        row.addWidget(self._next_btn)

        self._page_label = QLabel('—')
        self._page_label.setFixedWidth(60)
        self._page_label.setAlignment(Qt.AlignCenter)
        self._page_label.setStyleSheet('color:#6080a0; font-size:10px;')
        row.addWidget(self._page_label)

        self._update_nav_buttons()
        return wrap

    # ── public API ────────────────────────────────────────────────────────────

    def set_album(self, album: AlbumState) -> None:
        """Populate tabs after generation completes."""
        self._album_state = album
        self._current_page = 0
        self._rebuild_tabs()
        self._export_btn.setEnabled(True)
        self._generate_btn.setEnabled(True)
        self._generate_btn.setText('🔄  עדכן אלבום')
        self._progress_banner.hide()

    def set_generating(self, generating: bool) -> None:
        self._generate_btn.setEnabled(not generating)
        if generating:
            self._progress_banner.show()
            self._export_btn.setEnabled(False)
        else:
            self._progress_banner.hide()

    def update_progress(self, stage: str, current: int, total: int) -> None:
        pct = int(100 * current / max(1, total)) if total > 0 else 0
        detail = f'{current} / {total}' if total > 0 else ''
        self._progress_banner.update(stage, detail, pct)
        self._progress_banner.show()

    def current_page_index(self) -> int:
        return self._current_page

    def get_album_settings(self) -> AlbumSettings:
        density_map = {0: 'airy', 1: 'balanced', 2: 'dense'}
        density = density_map.get(self._density_combo.currentIndex(), 'balanced')
        return AlbumSettings(
            density=density,
            hero_pages=self._hero_chk.isChecked(),
        )

    # ── internal ──────────────────────────────────────────────────────────────

    def _rebuild_tabs(self) -> None:
        # Remove old tab buttons
        for btn in self._tab_buttons:
            self._tabs_row.removeWidget(btn)
            btn.deleteLater()
        self._tab_buttons.clear()

        if self._album_state is None:
            self._update_nav_buttons()
            return

        stretch = self._tabs_row.takeAt(self._tabs_row.count() - 1)
        for i, page in enumerate(self._album_state.pages):
            label = page.label or f'דף {i + 1}'
            btn = _PageTab(label)
            btn.set_active(i == self._current_page)
            idx = i
            btn.clicked.connect(lambda checked, ix=idx: self._select_page(ix))
            self._tabs_row.addWidget(btn)
            self._tab_buttons.append(btn)

        self._tabs_row.addStretch(1)
        self._update_page_label()
        self._update_nav_buttons()

    def _select_page(self, idx: int) -> None:
        if self._album_state is None:
            return
        idx = max(0, min(idx, self._album_state.page_count - 1))
        self._current_page = idx
        for i, btn in enumerate(self._tab_buttons):
            btn.set_active(i == idx)
        self._update_page_label()
        self._update_nav_buttons()
        self.page_selected.emit(idx)

    def _on_prev_page(self) -> None:
        self._select_page(self._current_page - 1)

    def _on_next_page(self) -> None:
        self._select_page(self._current_page + 1)

    def _on_generate_clicked(self) -> None:
        self.generate_requested.emit(self.get_album_settings())

    def _update_page_label(self) -> None:
        if self._album_state:
            self._page_label.setText(
                f'{self._current_page + 1} / {self._album_state.page_count}'
            )
        else:
            self._page_label.setText('—')

    def _update_nav_buttons(self) -> None:
        n = self._album_state.page_count if self._album_state else 0
        self._prev_btn.setEnabled(self._current_page > 0)
        self._next_btn.setEnabled(self._current_page < n - 1)
