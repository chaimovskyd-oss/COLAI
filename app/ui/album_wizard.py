"""AlbumWizard — the full-screen dedicated Album Builder mode.

Layout (fills the entire main window when active):
  ┌──────────────────────────────────────────────────────────────────┐
  │  [← חזור לקולאז']    🎞 בנאי אלבום    [📄 PDF]  [🖨 הדפסה]    │  top bar
  ├────────────┬──────────────────────────────────────┬─────────────┤
  │            │                                      │             │
  │  תמונות    │        CANVAS (CollageCanvas)        │  הגדרות    │
  │  (150px)   │                                      │  (260px)    │
  │            │  → placeholder before generation      │             │
  │ [+ ייבוא]  │  → page view after generation         │  צפיפות    │
  │            │                                      │  גודל      │
  │  list of   │                                      │  DPI        │
  │  thumbnails│                                      │  גיבורים   │
  │            │                                      │             │
  │ [🗑 הסר]   │                                      │ [▶ צור]    │
  ├────────────┴──────────────────────────────────────┴─────────────┤
  │  [◀] [ דף 1 ][ דף 2 ][ דף 3 ]...                  [▶]  2/8   │  page tabs
  └──────────────────────────────────────────────────────────────────┘

Signals:
  exit_requested()   — user clicked "חזור לקולאז'"
"""
from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QIcon, QPixmap, QColor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.album_builder.models import AlbumSettings
from app.album_builder.session import AlbumSession


# ─── shared style constants ───────────────────────────────────────────────────

_BG = '#111820'
_BG2 = '#161e2a'
_BORDER = '#2a3a50'
_TXT = '#c0d0e8'
_TXT2 = '#7aafe0'

_BTN = (
    'QPushButton{background:rgba(255,255,255,18);color:#cdd6ef;'
    'border:1px solid rgba(255,255,255,22);border-radius:4px;'
    'font-size:11px;padding:3px 10px;}'
    'QPushButton:hover{background:rgba(255,255,255,34);}'
    'QPushButton:pressed{background:rgba(80,160,255,160);}'
    'QPushButton:disabled{color:#445;border-color:#2a3040;}'
)
_BTN_PRIMARY = (
    'QPushButton{background:#1a5faa;color:#fff;border:1px solid #4a9eff;'
    'border-radius:5px;font-size:13px;font-weight:bold;padding:6px 22px;}'
    'QPushButton:hover{background:#2070c0;}'
    'QPushButton:pressed{background:#0d4080;}'
    'QPushButton:disabled{background:#1a2a3a;color:#445;border-color:#2a3a50;}'
)
_COMBO = (
    'QComboBox{background:#1e2a38;color:#c0d0e8;border:1px solid #2a3a50;'
    'border-radius:4px;padding:2px 6px;font-size:11px;}'
    'QComboBox::drop-down{border:none;}'
    'QComboBox QAbstractItemView{background:#1e2a38;color:#c0d0e8;'
    'selection-background-color:#2a4a70;border:1px solid #2a3a50;}'
)
_LABEL = f'color:{_TXT2};font-size:11px;'
_SECTION = f'color:#fff;font-size:12px;font-weight:bold;'


# ─── Image list panel ─────────────────────────────────────────────────────────

class _ImageListPanel(QWidget):
    """Left panel: thumbnail list + import/remove controls."""

    images_changed = Signal()   # any add/remove

    _THUMB = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(160)
        self.setStyleSheet(f'background:{_BG2}; border-right:1px solid {_BORDER};')
        self._build()

    def _build(self) -> None:
        vlay = QVBoxLayout(self)
        vlay.setContentsMargins(6, 8, 6, 8)
        vlay.setSpacing(6)

        hdr = QLabel('תמונות')
        hdr.setStyleSheet(_SECTION)
        hdr.setAlignment(Qt.AlignCenter)
        vlay.addWidget(hdr)

        self._count_lbl = QLabel('0 תמונות')
        self._count_lbl.setStyleSheet(f'color:{_TXT2}; font-size:10px;')
        self._count_lbl.setAlignment(Qt.AlignCenter)
        vlay.addWidget(self._count_lbl)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.IconMode)
        self._list.setIconSize(QSize(self._THUMB, self._THUMB))
        self._list.setMovement(QListWidget.Static)
        self._list.setResizeMode(QListWidget.Adjust)
        self._list.setSpacing(4)
        self._list.setStyleSheet(
            f'QListWidget{{background:{_BG};border:none;color:{_TXT};}}'
            f'QListWidget::item{{border-radius:4px;}}'
            f'QListWidget::item:selected{{background:#1a3a5c;}}'
        )
        vlay.addWidget(self._list, 1)

        import_btn = QPushButton('+ ייבוא תמונות')
        import_btn.setStyleSheet(_BTN_PRIMARY.replace('font-size:13px', 'font-size:11px')
                                              .replace('padding:6px 22px', 'padding:4px 8px'))
        import_btn.clicked.connect(self._import)
        vlay.addWidget(import_btn)

        remove_btn = QPushButton('🗑  הסר נבחרות')
        remove_btn.setStyleSheet(_BTN)
        remove_btn.clicked.connect(self._remove_selected)
        vlay.addWidget(remove_btn)

        clear_btn = QPushButton('✕  נקה הכל')
        clear_btn.setStyleSheet(_BTN)
        clear_btn.clicked.connect(self._clear)
        vlay.addWidget(clear_btn)

    # ── public ────────────────────────────────────────────────────────────────

    def paths(self) -> List[str]:
        return [self._list.item(i).data(Qt.UserRole) for i in range(self._list.count())]

    def add_paths(self, paths: List[str]) -> None:
        seen = set(self.paths())
        added = 0
        for p in paths:
            if p in seen:
                continue
            seen.add(p)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, p)
            icon = self._make_thumb(p)
            item.setIcon(icon)
            item.setToolTip(os.path.basename(p))
            self._list.addItem(item)
            added += 1
        if added:
            self._update_count()
            self.images_changed.emit()

    # ── private ───────────────────────────────────────────────────────────────

    def _import(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, 'בחר תמונות', '',
            'Images (*.jpg *.jpeg *.png *.webp *.bmp *.tiff *.tif)',
        )
        if files:
            self.add_paths(files)

    def _remove_selected(self) -> None:
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))
        self._update_count()
        self.images_changed.emit()

    def _clear(self) -> None:
        self._list.clear()
        self._update_count()
        self.images_changed.emit()

    def _update_count(self) -> None:
        n = self._list.count()
        self._count_lbl.setText(f'{n} תמונות')

    def _make_thumb(self, path: str) -> QIcon:
        try:
            pix = QPixmap(path)
            if pix.isNull():
                raise ValueError('null pixmap')
            pix = pix.scaled(
                self._THUMB, self._THUMB,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            # Centre-crop to square
            pw, ph = pix.width(), pix.height()
            ox = (pw - self._THUMB) // 2
            oy = (ph - self._THUMB) // 2
            pix = pix.copy(ox, oy, self._THUMB, self._THUMB)
            return QIcon(pix)
        except Exception:
            pix = QPixmap(self._THUMB, self._THUMB)
            pix.fill(QColor('#1e2a38'))
            return QIcon(pix)


# ─── Settings panel ───────────────────────────────────────────────────────────

class _SettingsPanel(QWidget):
    generate_clicked = Signal(AlbumSettings)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(260)
        self.setStyleSheet(f'background:{_BG2}; border-left:1px solid {_BORDER};')
        self._build()

    def _build(self) -> None:
        vlay = QVBoxLayout(self)
        vlay.setContentsMargins(12, 12, 12, 12)
        vlay.setSpacing(14)

        # Title
        hdr = QLabel('הגדרות אלבום')
        hdr.setStyleSheet(_SECTION)
        vlay.addWidget(hdr)

        # Canvas size
        size_grp = self._group('גודל דף')
        f = QFormLayout(size_grp)
        f.setSpacing(6)
        self._size_combo = QComboBox()
        self._size_combo.addItems([
            'A4 לאורך (21×29.7 ס"מ)',
            'A4 לרוחב (29.7×21 ס"מ)',
            'A3 לאורך (29.7×42 ס"מ)',
            'ריבוע 20×20 ס"מ',
            'ריבוע 30×30 ס"מ',
        ])
        self._size_combo.setCurrentIndex(0)
        self._size_combo.setStyleSheet(_COMBO)
        f.addRow(QLabel('פורמט', styleSheet=_LABEL), self._size_combo)

        self._dpi_combo = QComboBox()
        self._dpi_combo.addItems(['150 DPI (מהיר)', '300 DPI (סטנדרט)', '600 DPI (איכות גבוהה)'])
        self._dpi_combo.setCurrentIndex(1)
        self._dpi_combo.setStyleSheet(_COMBO)
        f.addRow(QLabel('רזולוציה', styleSheet=_LABEL), self._dpi_combo)
        vlay.addWidget(size_grp)

        # Layout density + page count
        density_grp = self._group('פריסה')
        f2 = QFormLayout(density_grp)
        f2.setSpacing(6)

        self._density_combo = QComboBox()
        self._density_combo.addItems([
            'מעורב — גיבורים + סיפור + צפוף',
            'מרווח (1-3 לדף)',
            'מאוזן (4-6 לדף)',
            'צפוף (6-9 לדף)',
        ])
        self._density_combo.setCurrentIndex(0)
        self._density_combo.setStyleSheet(_COMBO)
        f2.addRow(QLabel('סגנון', styleSheet=_LABEL), self._density_combo)

        pages_row = QHBoxLayout()
        self._pages_spin = QSpinBox()
        self._pages_spin.setRange(0, 200)
        self._pages_spin.setValue(0)
        self._pages_spin.setSpecialValueText('אוטומטי')
        self._pages_spin.setStyleSheet(
            'QSpinBox{background:#1e2a38;color:#c0d0e8;border:1px solid #2a3a50;'
            'border-radius:4px;padding:2px 4px;font-size:11px;}'
        )
        pages_row.addWidget(self._pages_spin)
        pages_lbl = QLabel('עמודים')
        pages_lbl.setStyleSheet(_LABEL)
        pages_row.addWidget(pages_lbl)
        pages_row.addStretch(1)
        f2.addRow(QLabel('כמות', styleSheet=_LABEL), pages_row)

        self._hero_chk = QCheckBox('עמודי גיבורים (1-2 תמונות)')
        self._hero_chk.setChecked(True)
        self._hero_chk.setStyleSheet(f'color:{_TXT2}; font-size:11px;')
        f2.addRow('', self._hero_chk)
        vlay.addWidget(density_grp)

        # Margins & spacing
        layout_grp = self._group('שוליים ומרווחים')
        f3 = QFormLayout(layout_grp)
        f3.setSpacing(6)

        self._margin_spin = QSpinBox()
        self._margin_spin.setRange(0, 40)
        self._margin_spin.setValue(5)
        self._margin_spin.setSuffix(' מ"מ')
        self._margin_spin.setStyleSheet(
            'QSpinBox{background:#1e2a38;color:#c0d0e8;border:1px solid #2a3a50;'
            'border-radius:4px;padding:2px 4px;font-size:11px;}'
        )
        f3.addRow(QLabel('שוליים', styleSheet=_LABEL), self._margin_spin)

        self._spacing_spin = QSpinBox()
        self._spacing_spin.setRange(0, 20)
        self._spacing_spin.setValue(2)
        self._spacing_spin.setSuffix(' מ"מ')
        self._spacing_spin.setStyleSheet(
            'QSpinBox{background:#1e2a38;color:#c0d0e8;border:1px solid #2a3a50;'
            'border-radius:4px;padding:2px 4px;font-size:11px;}'
        )
        f3.addRow(QLabel('מרווח בין תמונות', styleSheet=_LABEL), self._spacing_spin)
        vlay.addWidget(layout_grp)

        vlay.addStretch(1)

        # Stats
        self._stats_lbl = QLabel('')
        self._stats_lbl.setStyleSheet(f'color:{_TXT2}; font-size:10px;')
        self._stats_lbl.setWordWrap(True)
        vlay.addWidget(self._stats_lbl)

        # Generate button
        self._gen_btn = QPushButton('▶  צור אלבום')
        self._gen_btn.setStyleSheet(_BTN_PRIMARY)
        self._gen_btn.setFixedHeight(38)
        self._gen_btn.setEnabled(False)
        self._gen_btn.clicked.connect(self._on_generate)
        vlay.addWidget(self._gen_btn)

        # "Open in main editor" — shown after generation
        self._open_main_btn = QPushButton('✅  ערוך בעורך הראשי')
        self._open_main_btn.setStyleSheet(
            'QPushButton{background:#0d4a1f;color:#5ef08a;border:1px solid #1a9040;'
            'border-radius:5px;font-size:12px;font-weight:bold;padding:6px 12px;}'
            'QPushButton:hover{background:#1a6030;}'
        )
        self._open_main_btn.setFixedHeight(38)
        self._open_main_btn.hide()
        vlay.addWidget(self._open_main_btn)

    def _group(self, title: str) -> QGroupBox:
        g = QGroupBox(title)
        g.setStyleSheet(
            f'QGroupBox{{color:{_TXT2};font-size:11px;border:1px solid {_BORDER};'
            f'border-radius:5px;margin-top:6px;padding-top:4px;}}'
            f'QGroupBox::title{{subcontrol-origin:margin;left:8px;}}'
        )
        return g

    def set_image_count(self, n: int) -> None:
        self._gen_btn.setEnabled(n > 0)
        target = self._pages_spin.value()
        if n == 0:
            self._stats_lbl.setText('יש לייבא תמונות תחילה.')
        elif target > 0:
            avg = n / target
            self._stats_lbl.setText(
                f'{n} תמונות ← {target} עמודים\n(ממוצע {avg:.1f} לעמוד)'
            )
        else:
            self._stats_lbl.setText(f'{n} תמונות — כמות עמודים אוטומטית')

    def set_generating(self, on: bool) -> None:
        self._gen_btn.setEnabled(not on)
        self._open_main_btn.setEnabled(not on)
        self._gen_btn.setText('מעבד…' if on else '▶  צור אלבום')

    def show_open_main_button(self, callback) -> None:
        self._open_main_btn.show()
        try:
            self._open_main_btn.clicked.disconnect()
        except Exception:
            pass
        self._open_main_btn.clicked.connect(callback)

    def album_settings(self) -> AlbumSettings:
        density_map = {0: 'mixed', 1: 'airy', 2: 'balanced', 3: 'dense'}
        density = density_map.get(self._density_combo.currentIndex(), 'mixed')
        return AlbumSettings(
            density=density,
            hero_pages=self._hero_chk.isChecked(),
            target_pages=self._pages_spin.value(),
            margin_mm=float(self._margin_spin.value()),
            spacing_mm=float(self._spacing_spin.value()),
        )

    def apply_to_settings(self, settings) -> None:
        """Write chosen page size, DPI, margins and spacing into a ProjectSettings object."""
        sizes = [
            (21.0, 29.7), (29.7, 21.0), (29.7, 42.0),
            (20.0, 20.0), (30.0, 30.0),
        ]
        dpis = [150, 300, 600]
        w, h = sizes[self._size_combo.currentIndex()]
        settings.width_cm = w
        settings.height_cm = h
        settings.dpi = dpis[self._dpi_combo.currentIndex()]
        settings.margin_mm = float(self._margin_spin.value())
        settings.spacing_mm = float(self._spacing_spin.value())

    def _on_generate(self) -> None:
        self.generate_clicked.emit(self.album_settings())


# ─── Progress banner ──────────────────────────────────────────────────────────

class _ProgressBanner(QWidget):
    cancel_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setStyleSheet(f'background:#0d2137; border-top:2px solid #4a9eff;')
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(12)

        icon = QLabel('📚')
        icon.setStyleSheet('font-size:18px; background:transparent;')
        icon.setFixedWidth(26)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        texts.setContentsMargins(0, 0, 0, 0)
        self._stage = QLabel('מכין…')
        self._stage.setStyleSheet('color:#fff;font-weight:bold;font-size:12px;background:transparent;')
        self._detail = QLabel('')
        self._detail.setStyleSheet('color:#7aafe0;font-size:10px;background:transparent;')
        texts.addWidget(self._stage)
        texts.addWidget(self._detail)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedWidth(200)
        self._bar.setFixedHeight(8)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet(
            'QProgressBar{background:#1a3a5c;border-radius:4px;border:none;}'
            'QProgressBar::chunk{'
            'background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #4a9eff,stop:1 #00d4ff);'
            'border-radius:4px;}'
        )

        cancel = QPushButton('ביטול')
        cancel.setFixedHeight(22)
        cancel.setStyleSheet(
            'QPushButton{background:#3a1a1a;color:#ff6b6b;border:1px solid #6b2020;'
            'border-radius:4px;padding:2px 10px;font-size:11px;}'
            'QPushButton:hover{background:#5a2020;}'
        )
        cancel.clicked.connect(self.cancel_clicked)

        row.addWidget(icon)
        row.addLayout(texts, 1)
        row.addWidget(self._bar, 0, Qt.AlignVCenter)
        row.addWidget(cancel, 0, Qt.AlignVCenter)

    def update(self, stage: str, detail: str, pct: int) -> None:
        self._stage.setText(stage)
        self._detail.setText(detail)
        self._bar.setValue(max(0, min(100, pct)))


# ─── Page tab bar ─────────────────────────────────────────────────────────────

class _PageTabBar(QWidget):
    page_selected = Signal(int)

    _TAB_NORMAL = (
        'QPushButton{background:#1e2a38;color:#8eaac8;'
        'border:1px solid #2a3a50;border-bottom:none;'
        'padding:3px 14px;font-size:11px;border-radius:4px 4px 0 0;}'
        'QPushButton:hover{background:#253346;}'
    )
    _TAB_ACTIVE = (
        'QPushButton{background:#0d2137;color:#fff;font-weight:bold;'
        'border:1px solid #4a9eff;border-bottom:2px solid #0d2137;'
        'padding:3px 14px;font-size:11px;border-radius:4px 4px 0 0;}'
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setStyleSheet(f'background:#0d1420;border-top:1px solid {_BORDER};')
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 0)
        row.setSpacing(3)

        self._prev = QPushButton('◀')
        self._prev.setFixedSize(22, 22)
        self._prev.setStyleSheet(_BTN)
        self._prev.clicked.connect(lambda: self._step(-1))
        row.addWidget(self._prev)

        scroll = QScrollArea()
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedHeight(30)
        scroll.setStyleSheet('background:transparent;')
        self._container = QWidget()
        self._container.setStyleSheet('background:transparent;')
        self._row = QHBoxLayout(self._container)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(2)
        self._row.addStretch(1)
        scroll.setWidget(self._container)
        row.addWidget(scroll, 1)

        self._next = QPushButton('▶')
        self._next.setFixedSize(22, 22)
        self._next.setStyleSheet(_BTN)
        self._next.clicked.connect(lambda: self._step(1))
        row.addWidget(self._next)

        self._info = QLabel('—')
        self._info.setFixedWidth(55)
        self._info.setAlignment(Qt.AlignCenter)
        self._info.setStyleSheet(f'color:#6080a0;font-size:10px;')
        row.addWidget(self._info)

        self._tabs: list[QPushButton] = []
        self._current = 0

    def rebuild(self, n_pages: int) -> None:
        for btn in self._tabs:
            self._row.removeWidget(btn)
            btn.deleteLater()
        self._tabs.clear()
        stretch = self._row.takeAt(self._row.count() - 1)
        for i in range(n_pages):
            btn = QPushButton(f'דף {i + 1}')
            btn.setFixedHeight(24)
            btn.setStyleSheet(self._TAB_ACTIVE if i == self._current else self._TAB_NORMAL)
            btn.clicked.connect(lambda _, ix=i: self._select(ix))
            self._row.addWidget(btn)
            self._tabs.append(btn)
        self._row.addStretch(1)
        self._refresh_info(n_pages)
        self._refresh_nav(n_pages)

    def select(self, idx: int) -> None:
        self._select(idx, emit=False)

    def _select(self, idx: int, emit: bool = True) -> None:
        n = len(self._tabs)
        if n == 0:
            return
        idx = max(0, min(idx, n - 1))
        self._current = idx
        for i, btn in enumerate(self._tabs):
            btn.setStyleSheet(self._TAB_ACTIVE if i == idx else self._TAB_NORMAL)
        self._refresh_info(n)
        self._refresh_nav(n)
        if emit:
            self.page_selected.emit(idx)

    def _step(self, delta: int) -> None:
        self._select(self._current + delta)

    def _refresh_info(self, n: int) -> None:
        self._info.setText(f'{self._current + 1} / {n}' if n else '—')

    def _refresh_nav(self, n: int) -> None:
        self._prev.setEnabled(self._current > 0)
        self._next.setEnabled(self._current < n - 1)


# ─── Main wizard widget ───────────────────────────────────────────────────────

class AlbumWizard(QWidget):
    """Full-screen Album Builder. Shown via QStackedWidget in MainWindow."""

    exit_requested = Signal()
    open_in_main   = Signal(object)   # AlbumSession — open in main editor

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session = AlbumSession()
        self._worker = None
        self.setStyleSheet(f'background:{_BG};')
        self._build()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        # Three-column body
        body = QWidget()
        body_row = QHBoxLayout(body)
        body_row.setContentsMargins(0, 0, 0, 0)
        body_row.setSpacing(0)

        self._img_panel = _ImageListPanel()
        self._img_panel.images_changed.connect(self._on_images_changed)
        body_row.addWidget(self._img_panel)

        body_row.addWidget(self._build_canvas_area(), 1)

        self._settings_panel = _SettingsPanel()
        self._settings_panel.generate_clicked.connect(self._on_generate)
        body_row.addWidget(self._settings_panel)
        root.addWidget(body, 1)

        self._progress = _ProgressBanner()
        self._progress.cancel_clicked.connect(self._cancel)
        self._progress.hide()
        root.addWidget(self._progress)

        self._tab_bar = _PageTabBar()
        self._tab_bar.page_selected.connect(self._show_page)
        root.addWidget(self._tab_bar)

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet(f'background:#0a1520;border-bottom:1px solid {_BORDER};')
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(10)

        back = QPushButton('← חזור לקולאז\'')
        back.setStyleSheet(_BTN)
        back.setFixedHeight(26)
        back.clicked.connect(self.exit_requested)
        row.addWidget(back)

        title = QLabel('🎞  בנאי אלבום')
        title.setStyleSheet('color:#ffffff;font-size:14px;font-weight:bold;')
        row.addWidget(title, 1, Qt.AlignCenter)

        self._export_btn = QPushButton('📄  ייצוא PDF')
        self._export_btn.setStyleSheet(_BTN)
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export_pdf)
        row.addWidget(self._export_btn)

        return bar

    def _build_canvas_area(self) -> QWidget:
        """Centre area: shows a placeholder before generation, CollageCanvas after."""
        from PySide6.QtWidgets import QStackedWidget
        from app.ui.canvas import CollageCanvas

        self._canvas_stack = QStackedWidget()

        # Index 0: placeholder
        placeholder = QWidget()
        placeholder.setStyleSheet(f'background:{_BG};')
        ph_lay = QVBoxLayout(placeholder)
        ph_lay.setAlignment(Qt.AlignCenter)
        icon = QLabel('🎞')
        icon.setStyleSheet('font-size:56px;')
        icon.setAlignment(Qt.AlignCenter)
        msg = QLabel('ייבא תמונות ולחץ\n"▶  צור אלבום"')
        msg.setStyleSheet(f'color:{_TXT2};font-size:16px;')
        msg.setAlignment(Qt.AlignCenter)
        ph_lay.addWidget(icon)
        ph_lay.addWidget(msg)
        self._canvas_stack.addWidget(placeholder)        # index 0

        # Index 1: live canvas
        self._canvas = CollageCanvas()
        self._canvas_stack.addWidget(self._canvas)       # index 1

        return self._canvas_stack

    # ── signals / handlers ───────────────────────────────────────────────────

    def _on_images_changed(self) -> None:
        paths = self._img_panel.paths()
        n = len(paths)
        self._settings_panel.set_image_count(n)
        # Rebuild session image_states from current paths
        self._session.image_states = [self._make_image_state(p) for p in paths]
        # Keep album in sync (invalidate if images changed)
        if self._session.album_state is not None:
            self._session.album_state = None
            self._canvas_stack.setCurrentIndex(0)
            self._tab_bar.rebuild(0)
            self._export_btn.setEnabled(False)

    def _on_generate(self, settings: AlbumSettings) -> None:
        n = len(self._session.image_states)
        if n == 0:
            QMessageBox.warning(self, 'אלבום', 'יש לייבא תמונות תחילה.')
            return

        # Apply size/DPI from settings panel into session
        self._settings_panel.apply_to_settings(self._session.make_settings())

        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(1000)

        from app.album_builder.workers import AlbumBuilderWorker
        # Build a temporary ProjectState from session for the worker
        project = self._session.make_preview_project()
        project.images = list(self._session.image_states)

        self._worker = AlbumBuilderWorker(project, settings, self)
        self._worker.stage.connect(self._on_stage)
        self._worker.album_ready.connect(self._on_album_ready)
        self._worker.failed.connect(self._on_failed)

        self._settings_panel.set_generating(True)
        self._progress.show()
        self._worker.start()

    def _on_stage(self, stage: str, current: int, total: int) -> None:
        pct = int(100 * current / max(1, total)) if total else 0
        detail = f'{current} / {total}' if total else ''
        self._progress.update(stage, detail, pct)

    def _on_album_ready(self, album) -> None:
        self._session.album_state = album
        self._settings_panel.set_generating(False)
        self._progress.hide()
        self._export_btn.setEnabled(True)
        n = album.page_count
        self._tab_bar.rebuild(n)
        if n > 0:
            self._canvas_stack.setCurrentIndex(1)
            self._show_page(0)
        # Show "open in main editor" button
        self._settings_panel.show_open_main_button(self._open_in_main)

    def _on_failed(self, msg: str) -> None:
        self._settings_panel.set_generating(False)
        self._progress.hide()
        QMessageBox.critical(self, 'שגיאה', f'בניית האלבום נכשלה:\n{msg}')

    def _cancel(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
        self._settings_panel.set_generating(False)
        self._progress.hide()

    def _show_page(self, idx: int) -> None:
        self._session.current_page_index = idx
        page_project = self._session.make_page_project(idx)
        if page_project is None:
            return
        self._canvas.project = page_project
        self._canvas.refresh_preview()
        self._tab_bar.select(idx)

    def _export_pdf(self) -> None:
        if not self._session.is_generated:
            QMessageBox.warning(self, 'ייצוא', 'יש ליצור אלבום תחילה.')
            return

        path, _ = QFileDialog.getSaveFileName(
            self, 'שמור PDF', 'album.pdf', 'PDF Files (*.pdf)'
        )
        if not path:
            return

        from app.core.exporter import export_album

        # Build a project-like object the exporter can use
        proxy = self._session.make_preview_project()
        proxy.album_state = self._session.album_state

        n = self._session.page_count
        def _cb(cur, total):
            pct = int(100 * cur / max(1, total))
            self._progress.update('מייצא PDF…', f'{cur} / {total}', pct)

        self._progress.show()
        try:
            export_album(proxy, path, progress_cb=_cb)
            self._progress.hide()
            QMessageBox.information(self, 'ייצוא הסתיים', f'האלבום נשמר:\n{path}')
        except Exception as exc:
            self._progress.hide()
            QMessageBox.critical(self, 'שגיאה בייצוא', str(exc))

    def _open_in_main(self) -> None:
        """Emit open_in_main signal — MainWindow will take over from here."""
        self.open_in_main.emit(self._session)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _make_image_state(path: str):
        from app.models.project import ImageState
        state = ImageState(path=path)
        return state
