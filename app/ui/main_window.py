from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple
import concurrent.futures
import copy
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request

from PySide6.QtCore import Qt, QRect, QSize, Signal, QTimer, QFileSystemWatcher
from PySide6.QtGui import (
    QColor, QDragEnterEvent, QDropEvent, QIcon, QKeySequence,
    QPainter, QPen, QPixmap, QShortcut,
)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QInputDialog,
    QScrollArea,
    QScrollBar,
    QSlider,
    QStackedWidget,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QProgressDialog,
)

from app.i18n import tr, set_language, current_language, is_rtl
from app.core import face_detector
from app.core.collage_engine import generate_suggestions, custom_grid_layout
from app.core.exporter import export_project, render_project
from app.core.shape_layouts import generate_shaped_layout
from app.core.smart_crop_service import (
    analysis_to_face_regions,
    advanced_face_install_hint,
    analyze_image,
    evaluate_crop_risks,
    optimize_crop,
    crop_box_from_pan,
    retinaface_available,
    yolo_available,
    yolo_install_hint,
)
from app.core.project_io import save_project, load_project
from app.models.project import ImageState, LayoutSuggestion, ProjectState, TextOverlay
from app.ui.canvas import CollageCanvas
from app.utils.image_utils import (
    evaluate_crop_for_state,
    face_near_cell_edge,
    image_resolution_ok,
    invalidate_cache,
    make_thumb_icon_with_badge,
    mm_to_px,
    pil_to_qpixmap,
    smart_pan_from_faces,
)
from app.utils.color_equalizer_processor import reset_all as reset_color_equalizer
from print_preview.adapters.app_render_adapter import AppRenderAdapter, CollagePreviewPage
from print_preview.controller.print_preview_controller import PrintPreviewController
from print_preview.ui.main_window import PrintPreviewWindow


PRESETS_CM: Dict[str, Tuple[float, float]] = {
    '15 x 10 cm': (15.0, 10.0),
    'A4 Portrait': (21.0, 29.7),
    'A4 Landscape': (29.7, 21.0),
    'A3 Portrait': (29.7, 42.0),
    'A3 Landscape': (42.0, 29.7),
    '30 x 40 cm': (30.0, 40.0),
    '20 x 20 cm Square': (20.0, 20.0),
    '50 x 70 cm': (50.0, 70.0),
    '60 x 40 cm': (60.0, 40.0),
    'Custom': (15.0, 10.0),
}
USER_PRESETS_PATH = Path.home() / '.smart_collage_presets.json'
ELEMENTS_STATE_PATH = Path.home() / '.smart_collage_elements.json'
ELEMENTS_CACHE_DIR = Path.home() / '.smart_collage_elements_cache'
OPENMOJI_DATA_URL = 'https://raw.githubusercontent.com/hfg-gmuend/openmoji/master/data/openmoji.json'
OPENMOJI_SVG_URL = 'https://raw.githubusercontent.com/hfg-gmuend/openmoji/master/color/svg/{filename}'
THUMB_W, THUMB_H = 140, 88
IMG_THUMB_W, IMG_THUMB_H = 80, 60

EMOJI_SYNONYMS = {
    'happy': ['smile', 'smiling', 'grinning', 'joy', 'cheerful', 'laugh', 'beaming', 'party', 'partying'],
    'sad': ['cry', 'crying', 'tear', 'unhappy'],
    'love': ['heart', 'hearts', 'romance', 'couple'],
    'cat': ['cat', 'kitten', 'pet'],
    'dog': ['dog', 'puppy', 'pet'],
    'birthday': ['cake', 'balloon', 'party', 'gift'],
    'wedding': ['ring', 'bride', 'groom', 'love', 'heart'],
    'שמח': ['happy', 'smile'],
    'חתול': ['cat'],
    'לב': ['heart', 'love'],
    'יום הולדת': ['birthday', 'cake', 'balloon', 'gift'],
    'כלב': ['dog'],
    'פרח': ['flower'],
}


def _load_user_presets() -> Dict[str, Tuple[float, float]]:
    try:
        raw = json.loads(USER_PRESETS_PATH.read_text(encoding='utf-8'))
        result: Dict[str, Tuple[float, float]] = {}
        for item in raw:
            name = str(item.get('name', '')).strip()
            width = float(item.get('width_cm', 0))
            height = float(item.get('height_cm', 0))
            if name and width > 0 and height > 0:
                result[f'{name} ({width:g} x {height:g} cm)'] = (width, height)
        return result
    except Exception:
        return {}


def _save_user_presets(presets: Dict[str, Tuple[float, float]]) -> None:
    payload = [
        {'name': key.split(' (', 1)[0], 'width_cm': val[0], 'height_cm': val[1]}
        for key, val in presets.items()
        if key != 'Custom'
    ]
    USER_PRESETS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


PRESETS_CM.update(_load_user_presets())

SHORTCUTS_HELP = """\
Keyboard Shortcuts
ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€
Ctrl+P      Print collage
Ctrl+S      Export / Save
Ctrl+Z      Undo
Ctrl+Y      Redo
Ctrl+T      Focus text input
Delete      Remove selected element or selected image
Tab         Toggle Swap mode
+ / =       Brightness +5 %
-           Brightness -5 %
W           Contrast +5 %
S           Contrast -5 %
Arrow keys  Pan selected image (fine)

Canvas
ג”€ג”€ג”€ג”€ג”€ג”€
Scroll wheel    Zoom in/out selected cell
Drag            Pan image inside cell
Double-click    Edit text overlay inline (click on text)
Right-click     Replace / Remove image in cell
"""


# ---------------------------------------------------------------------------
# Collapsible section widget
# ---------------------------------------------------------------------------

class CollapsibleSection(QWidget):
    """A titled header button that shows/hides its body content."""

    def __init__(self, title: str, collapsed: bool = False, parent=None):
        super().__init__(parent)
        self._title = title
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 2)
        root.setSpacing(0)

        self._btn = QPushButton()
        self._btn.setCheckable(True)
        self._btn.setChecked(not collapsed)
        self._btn.setStyleSheet(
            'QPushButton {'
            '  text-align: left; padding: 5px 10px;'
            '  background: #252525; border: none;'
            '  border-bottom: 1px solid #333;'
            '  color: #c8c8c8; font-weight: bold; font-size: 12px;'
            '  border-radius: 0px;'
            '}'
            'QPushButton:checked { background: #2a2a2a; color: #e8e8e8; }'
            'QPushButton:hover { background: #2e2e2e; color: #ffffff; }'
        )
        self._btn.toggled.connect(self._on_toggle)
        root.addWidget(self._btn)

        self._body = QFrame()
        self._body.setFrameShape(QFrame.NoFrame)
        self._body.setStyleSheet(
            'QFrame { background: #222; border-left: 2px solid #333; }'
        )
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(10, 4, 10, 8)
        body_layout.setSpacing(4)
        self._body.setVisible(not collapsed)
        root.addWidget(self._body)

        self._update_label()

    def _on_toggle(self, checked: bool):
        self._body.setVisible(checked)
        self._update_label()

    def _update_label(self):
        arrow = 'ג–¼' if self._btn.isChecked() else 'ג–¶'
        self._btn.setText(f' {arrow}  {self._title}')

    def set_title(self, title: str) -> None:
        """Update the displayed title (for language switching)."""
        self._title = title
        self._update_label()

    def body_layout(self) -> QVBoxLayout:
        return self._body.layout()

    def add_form(self) -> QFormLayout:
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)
        self._body.layout().addLayout(form)
        return form

    def add_widget(self, w: QWidget):
        self._body.layout().addWidget(w)

    def add_layout(self, lay):
        self._body.layout().addLayout(lay)


# ---------------------------------------------------------------------------
# Image list with drag-drop thumbnails
# ---------------------------------------------------------------------------

class DropListWidget(QListWidget):
    filesDropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(IMG_THUMB_W, IMG_THUMB_H))
        self.setGridSize(QSize(IMG_THUMB_W + 10, IMG_THUMB_H + 24))
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setWordWrap(True)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()]
        if files:
            self.filesDropped.emit(files)
        e.acceptProposedAction()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr('Smart Collage Maker'))
        self.setAcceptDrops(True)   # whole-window drag-and-drop
        self.project = ProjectState()
        self._print_preview_windows: List[PrintPreviewWindow] = []
        self.history: List[tuple] = []
        self.history_index = -1
        self._history_suspended = 0
        self._layout_locked = False
        self._photoshop_watch_paths: Dict[str, float] = {}
        self._photoshop_refresh_timers: Dict[str, QTimer] = {}
        self._photoshop_poll_timer = QTimer(self)
        self._photoshop_poll_timer.setInterval(1500)
        self._photoshop_poll_timer.timeout.connect(self._poll_photoshop_watches)
        self._photoshop_fs_watcher = QFileSystemWatcher(self)
        self._photoshop_fs_watcher.fileChanged.connect(self._on_watched_image_changed)

        # i18n tracking ג€” populated during _build_menu_bar / _build_ui
        self._actions: Dict[str, object] = {}          # key ג†’ QAction
        self._sections: Dict[str, object] = {}         # key ג†’ CollapsibleSection
        self._form_labels: List[tuple] = []            # (QLabel, key)
        self._lang_action_group: List[tuple] = []      # [(lang_code, QAction), ...]

        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1520, screen.width() - 20), min(920, screen.height() - 50))

        self._build_menu_bar()
        self._build_ui()
        self._apply_spinbox_arrow_style()
        self._connect_signals()
        self._setup_shortcuts()
        self._apply_preset()
        self.canvas.set_project(self.project)
        self._reload_elem_library()   # pre-load heart SVG
        self._push_history()
        self.retranslate_ui()   # apply current language to all widgets

        if face_detector.is_available():
            if yolo_available():
                self.statusBar().showMessage('Smart crop ready (MediaPipe + YOLO11)')
            else:
                self.statusBar().showMessage('Face detection ready; YOLO11 person detection unavailable')
        else:
            self.statusBar().showMessage(
                tr('MediaPipe not installed ג€“ run: pip install mediapipe')
            )

    def _apply_spinbox_arrow_style(self, target: Optional[QWidget] = None) -> None:
        base_dir = Path(__file__).resolve().parent.parent
        up = (base_dir / 'assets' / 'spin_up.svg').as_posix()
        down = (base_dir / 'assets' / 'spin_down.svg').as_posix()
        style = f"""
        QSpinBox::up-button, QDoubleSpinBox::up-button,
        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            width: 18px;
            background: rgba(255,255,255,0.08);
            border-left: 1px solid rgba(255,255,255,0.18);
        }}
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
            image: url({up});
            width: 10px;
            height: 10px;
        }}
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
            image: url({down});
            width: 10px;
            height: 10px;
        }}
        """
        if target is None:
            self.setStyleSheet(self.styleSheet() + style)
        else:
            target.setStyleSheet(target.styleSheet() + style)

    # -------------------------------------------------------------------
    # Window-level drag & drop (accepts image files dropped anywhere)
    # -------------------------------------------------------------------

    _IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(
            Path(u.toLocalFile()).suffix.lower() in self._IMAGE_EXTS
            for u in event.mimeData().urls()
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        files = [u.toLocalFile() for u in event.mimeData().urls()
                 if Path(u.toLocalFile()).suffix.lower() in self._IMAGE_EXTS]
        if files:
            self.add_images(files)
        event.acceptProposedAction()

    # -------------------------------------------------------------------
    # Menu bar
    # -------------------------------------------------------------------

    def _build_menu_bar(self):
        mb = self.menuBar()
        a = self._actions   # shorthand

        # File
        self._file_menu = mb.addMenu('&File')
        a['new']      = self._file_menu.addAction('', self.new_project)
        a['open']     = self._file_menu.addAction('', self.open_project)
        a['save']     = self._file_menu.addAction('', self.save_project_as)
        self._file_menu.addSeparator()
        a['import']   = self._file_menu.addAction('', self.import_images)
        self._file_menu.addSeparator()
        a['template'] = self._file_menu.addAction('', self._open_template_creator)
        self._file_menu.addSeparator()
        a['export']   = self._file_menu.addAction('', self.export_file)
        a['print']    = self._file_menu.addAction('', self.open_print_preview)
        self._file_menu.addSeparator()
        a['quit']     = self._file_menu.addAction('', self.close)

        # Keyboard shortcuts for file menu
        a['new'].setShortcut(QKeySequence('Ctrl+N'))
        a['open'].setShortcut(QKeySequence('Ctrl+O'))
        a['save'].setShortcut(QKeySequence('Ctrl+Shift+S'))
        a['import'].setShortcut(QKeySequence('Ctrl+I'))
        a['export'].setShortcut(QKeySequence('Ctrl+S'))
        a['print'].setShortcut(QKeySequence('Ctrl+P'))
        a['quit'].setShortcut(QKeySequence('Ctrl+Q'))

        # Edit
        self._edit_menu = mb.addMenu('&Edit')
        self._undo_action = self._edit_menu.addAction('', self.undo)
        a['undo'] = self._undo_action
        self._redo_action = self._edit_menu.addAction('', self.redo)
        a['redo'] = self._redo_action
        self._edit_menu.addSeparator()
        a['gen']    = self._edit_menu.addAction('', self.generate_suggestions)
        a['soft_fade'] = self._edit_menu.addAction('', self._open_soft_fade_dialog)
        a['swap']   = self._edit_menu.addAction('', self._toggle_swap_shortcut)
        a['swap'].setShortcut(QKeySequence('Tab'))
        self._edit_menu.addSeparator()
        a['remove'] = self._edit_menu.addAction('', self._delete_key_handler)
        a['reset_all'] = self._edit_menu.addAction('', self.reset_all_images)

        # View
        self._view_menu = mb.addMenu('&View')
        a['shortcuts'] = self._view_menu.addAction('', self._show_help)
        a['shortcuts'].setShortcut(QKeySequence('F1'))
        self._view_menu.addSeparator()
        a['zoom_in']  = self._view_menu.addAction('', self._zoom_in)
        a['zoom_in'].setShortcut(QKeySequence('Ctrl+='))
        a['zoom_out'] = self._view_menu.addAction('', self._zoom_out)
        a['zoom_out'].setShortcut(QKeySequence('Ctrl+-'))
        a['fit']      = self._view_menu.addAction('', self._fit_to_screen)
        a['fit'].setShortcut(QKeySequence('Ctrl+0'))
        self._view_menu.addSeparator()
        a['smart_debug'] = self._view_menu.addAction('Smart crop debug overlay')
        a['smart_debug'].setCheckable(True)
        a['smart_debug'].triggered.connect(self._toggle_smart_crop_debug)

        # Language submenu
        self._lang_menu = self._view_menu.addMenu('')
        en_action = self._lang_menu.addAction('English', lambda: self._switch_language('en'))
        he_action = self._lang_menu.addAction('׳¢׳‘׳¨׳™׳×',   lambda: self._switch_language('he'))
        en_action.setCheckable(True); he_action.setCheckable(True)
        self._lang_action_group = [('en', en_action), ('he', he_action)]
        self._update_lang_checks()

        # Advanced collage
        self._advanced_menu = mb.addMenu('&Advanced Collage')
        a['custom_grid'] = self._advanced_menu.addAction('', self._open_custom_grid_dialog)
        self._shape_menu = self._advanced_menu.addMenu('')
        a['shape_circle'] = self._shape_menu.addAction('', lambda: self._generate_shaped('circle'))
        a['shape_heart'] = self._shape_menu.addAction('', lambda: self._generate_shaped('heart'))
        self._advanced_menu.addSeparator()
        a['dynamic_layout'] = self._advanced_menu.addAction('', self._create_dynamic_layout)

        # Actions
        self._actions_menu = mb.addMenu('&Actions')
        a['smart_arrange'] = self._actions_menu.addAction('', self.smart_arrange)
        a['refresh_images'] = self._actions_menu.addAction('רענן תמונות', self.refresh_images_from_disk)
        self._actions_menu.addSeparator()
        a['scan_selected'] = self._actions_menu.addAction('', self.scan_selected_images)
        a['scan_all'] = self._actions_menu.addAction('', self.scan_all_images)

        # Lock button — placed in the top-right corner of the menu bar
        self._lock_btn = QPushButton('🔓')
        self._lock_btn.setCheckable(True)
        self._lock_btn.setToolTip('נעל סידור — מנע שינוי אוטומטי של הסידור וסוג הקולאג׳')
        self._lock_btn.setStyleSheet(
            'QPushButton { background: transparent; color: #c0c0c0; font-size: 17px;'
            ' border: 1px solid transparent; border-radius: 4px; padding: 1px 10px; margin: 1px 4px; }'
            'QPushButton:checked { background: #1a4a70; color: #fff; border-color: #4a9eff; }'
            'QPushButton:hover { background: #2a2a2a; border-color: #555; }'
        )
        mb.setCornerWidget(self._lock_btn, Qt.TopRightCorner)
        self._lock_btn.toggled.connect(self._on_lock_toggled)

    # -------------------------------------------------------------------
    # UI
    # -------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)
        root.addWidget(self._build_left_panel())
        self.canvas = CollageCanvas()
        root.addWidget(self._build_canvas_frame(), 1)
        root.addWidget(self._build_right_panel())

        # Panels are created inside _build_right_panel (sidebar stack)

    # ג”€ג”€ Canvas frame (canvas + scrollbars + zoom bar) ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€
    def _build_canvas_frame(self) -> QWidget:
        """Wrap the canvas with H/V scrollbars and a zoom control bar."""
        frame = QWidget()
        frame.setContentsMargins(0, 0, 0, 0)
        vlay = QVBoxLayout(frame)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        # canvas + vertical scrollbar side-by-side
        canvas_row = QWidget()
        crow = QHBoxLayout(canvas_row)
        crow.setContentsMargins(0, 0, 0, 0)
        crow.setSpacing(0)
        crow.addWidget(self.canvas, 1)
        self._cvscroll = QScrollBar(Qt.Vertical)
        self._cvscroll.setFixedWidth(14)
        self._cvscroll.hide()
        crow.addWidget(self._cvscroll)
        vlay.addWidget(canvas_row, 1)

        # horizontal scrollbar
        self._chscroll = QScrollBar(Qt.Horizontal)
        self._chscroll.setFixedHeight(14)
        self._chscroll.hide()
        vlay.addWidget(self._chscroll)

        # zoom bar
        zoom_bar = QWidget()
        zoom_bar.setFixedHeight(30)
        zoom_bar.setStyleSheet('background: #262626;')
        zlay = QHBoxLayout(zoom_bar)
        zlay.setContentsMargins(8, 3, 8, 3)
        zlay.setSpacing(5)

        _zbtn = (
            'QPushButton { background:rgba(255,255,255,18); color:#cdd6ef;'
            ' border:1px solid rgba(255,255,255,22); border-radius:4px;'
            ' font-size:14px; font-weight:bold; padding:0; }'
            'QPushButton:hover  { background:rgba(255,255,255,34); }'
            'QPushButton:pressed{ background:rgba(80,160,255,160); }'
        )
        _zsl = (
            'QSlider::groove:horizontal{height:4px;background:rgba(255,255,255,28);border-radius:2px;}'
            'QSlider::handle:horizontal{width:12px;height:12px;margin:-4px 0;'
            'background:#50a0ff;border-radius:6px;}'
            'QSlider::sub-page:horizontal{background:#50a0ff;border-radius:2px;}'
        )

        self._czoom_out = QPushButton('גˆ’')
        self._czoom_out.setFixedSize(22, 22)
        self._czoom_out.setStyleSheet(_zbtn)
        self._czoom_out.setFocusPolicy(Qt.NoFocus)

        self._czoom_sl = QSlider(Qt.Horizontal)
        self._czoom_sl.setRange(10, 400)
        self._czoom_sl.setValue(100)
        self._czoom_sl.setStyleSheet(_zsl)
        self._czoom_sl.setFocusPolicy(Qt.NoFocus)

        self._czoom_in = QPushButton('+')
        self._czoom_in.setFixedSize(22, 22)
        self._czoom_in.setStyleSheet(_zbtn)
        self._czoom_in.setFocusPolicy(Qt.NoFocus)

        self._czoom_lbl = QLabel('100%')
        self._czoom_lbl.setFixedWidth(38)
        self._czoom_lbl.setAlignment(Qt.AlignCenter)
        self._czoom_lbl.setStyleSheet('color:#99a8c2; font-size:10px;')

        self.refresh_images_btn = QPushButton('רענן תמונות')
        self.refresh_images_btn.setFixedHeight(22)
        self.refresh_images_btn.setStyleSheet(_zbtn + 'QPushButton{font-size:11px; padding:0 8px;}')
        self.refresh_images_btn.setFocusPolicy(Qt.NoFocus)
        self.refresh_images_btn.setToolTip('Reload current image files from disk without changing the collage')

        self._czoom_reset = QPushButton('1:1')
        self._czoom_reset.setFixedSize(32, 22)
        self._czoom_reset.setStyleSheet(_zbtn)
        self._czoom_reset.setFocusPolicy(Qt.NoFocus)
        self._czoom_reset.setToolTip('Reset zoom to 100%  (Ctrl+0)')

        zlay.addWidget(self._czoom_out)
        zlay.addWidget(self._czoom_sl, 1)
        zlay.addWidget(self.refresh_images_btn)
        zlay.addWidget(self._czoom_in)
        zlay.addSpacing(6)
        zlay.addWidget(self._czoom_lbl)
        zlay.addWidget(self._czoom_reset)
        vlay.addWidget(zoom_bar)

        # wiring
        self._czoom_sl.valueChanged.connect(lambda v: self.canvas.zoom_to(v / 100.0))
        self._czoom_out.clicked.connect(self.canvas.zoom_out)
        self._czoom_in.clicked.connect(self.canvas.zoom_in)
        self._czoom_reset.clicked.connect(self.canvas.fit_to_screen)
        self.refresh_images_btn.clicked.connect(self.refresh_images_from_disk)
        self.canvas.displayZoomChanged.connect(self._on_canvas_zoom_changed)
        self.canvas.panChanged.connect(self._sync_canvas_scrollbars)
        self._chscroll.valueChanged.connect(self._on_canvas_hscroll)
        self._cvscroll.valueChanged.connect(self._on_canvas_vscroll)

        return frame

    # ג”€ג”€ Canvas navigation helpers ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€
    def _on_canvas_zoom_changed(self, zoom: float) -> None:
        pct = int(round(zoom * 100))
        self._czoom_sl.blockSignals(True)
        self._czoom_sl.setValue(pct)
        self._czoom_sl.blockSignals(False)
        self._czoom_lbl.setText(f'{pct}%')
        self._sync_canvas_scrollbars()

    def _sync_canvas_scrollbars(self) -> None:
        max_px, max_py, pan_x, pan_y = self.canvas.pan_bounds()
        self._chscroll.blockSignals(True)
        if max_px > 0:
            self._chscroll.setRange(0, 2 * max_px)
            self._chscroll.setValue(max_px - pan_x)
            self._chscroll.setPageStep(max(1, max_px // 4))
            self._chscroll.show()
        else:
            self._chscroll.hide()
        self._chscroll.blockSignals(False)
        self._cvscroll.blockSignals(True)
        if max_py > 0:
            self._cvscroll.setRange(0, 2 * max_py)
            self._cvscroll.setValue(max_py - pan_y)
            self._cvscroll.setPageStep(max(1, max_py // 4))
            self._cvscroll.show()
        else:
            self._cvscroll.hide()
        self._cvscroll.blockSignals(False)

    def _on_canvas_hscroll(self, value: int) -> None:
        max_px, _mpy, _px, pan_y = self.canvas.pan_bounds()
        self.canvas.set_pan(max_px - value, pan_y)

    def _on_canvas_vscroll(self, value: int) -> None:
        _mpx, max_py, pan_x, _py = self.canvas.pan_bounds()
        self.canvas.set_pan(pan_x, max_py - value)

    # ג”€ג”€ i18n helpers ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€
    def _reg_sec(self, key: str, collapsed: bool = False) -> 'CollapsibleSection':
        """Create a CollapsibleSection, store in self._sections, return it."""
        sec = CollapsibleSection(key, collapsed=collapsed)
        self._sections[key] = sec
        return sec

    def _reg_form_rows(self, form, keys: List[str]) -> None:
        """After form rows are added, store QLabel refs for all non-empty keys."""
        from PySide6.QtWidgets import QFormLayout as _FL
        for i, key in enumerate(keys):
            if not key:
                continue
            item = form.itemAt(i, _FL.LabelRole)
            if item and item.widget():
                self._form_labels.append((item.widget(), key))

    def _apply_button(self) -> QPushButton:
        btn = QPushButton('✓')
        btn.setFixedWidth(30)
        btn.setToolTip('Apply value')
        btn.setStyleSheet(
            'QPushButton { background:#1d7a4a; color:#fff; font-weight:bold;'
            ' border-radius:5px; border:none; padding:3px 0; }'
            'QPushButton:hover { background:#2ecc71; }'
            'QPushButton:pressed { background:#179a42; }'
        )
        return btn

    def _spin_apply_row(self, spin, handler) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(spin, 1)
        btn = self._apply_button()
        btn.clicked.connect(handler)
        row.addWidget(btn)
        return wrap

    # ג”€ג”€ Left panel ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€
    def _build_left_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(340)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setSpacing(3)
        layout.setContentsMargins(6, 6, 12, 6)

        # ג”€ג”€ Canvas ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€
        canvas_sec = self._reg_sec('Canvas', collapsed=False)
        f = canvas_sec.add_form()
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(PRESETS_CM.keys())
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(1, 200)
        self.width_spin.setSuffix(' cm')
        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(1, 200)
        self.height_spin.setSuffix(' cm')
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 600)
        self.dpi_spin.setValue(300)
        self.margin_spin = QDoubleSpinBox()
        self.margin_spin.setRange(0.0, 100.0)
        self.margin_spin.setDecimals(1)
        self.margin_spin.setSingleStep(0.5)
        self.margin_spin.setSuffix(' mm')
        self.margin_spin.setValue(5.0)
        self.spacing_spin = QDoubleSpinBox()
        self.spacing_spin.setRange(0.0, 50.0)
        self.spacing_spin.setDecimals(1)
        self.spacing_spin.setSingleStep(0.5)
        self.spacing_spin.setSuffix(' mm')
        self.spacing_spin.setValue(1.7)
        self.save_preset_btn = QPushButton('Save as preset')
        self.save_preset_btn.setStyleSheet(
            'QPushButton { background:#1d7a4a; color:#fff; font-weight:bold;'
            ' border-radius:6px; border:none; padding:5px 12px; }'
            'QPushButton:hover { background:#2ecc71; }'
            'QPushButton:pressed { background:#179a42; }'
        )
        self.zero_spacing_btn = QPushButton('Set margin & spacing to 0')
        self.bg_btn = QPushButton('Solid colourג€¦')
        bg_type_row = QHBoxLayout()
        self.bg_solid_radio = QPushButton('Solid')
        self.bg_gradient_radio = QPushButton('Gradient')
        self.bg_image_radio = QPushButton('Imageג€¦')
        for b in [self.bg_solid_radio, self.bg_gradient_radio, self.bg_image_radio]:
            b.setCheckable(True)
            bg_type_row.addWidget(b)
        self.bg_solid_radio.setChecked(True)

        self.bg_grad_c1_btn = QPushButton('Colour 1')
        self.bg_grad_c2_btn = QPushButton('Colour 2')
        self.bg_grad_gold_btn = QPushButton('ג¦ Gold')
        self.bg_grad_angle_spin = QSpinBox()
        self.bg_grad_angle_spin.setRange(0, 360)
        self.bg_grad_angle_spin.setValue(90)
        self.bg_grad_angle_spin.setSuffix('ֲ°')
        grad_row = QHBoxLayout()
        grad_row.addWidget(self.bg_grad_c1_btn)
        grad_row.addWidget(self.bg_grad_c2_btn)
        grad_row.addWidget(self.bg_grad_gold_btn)

        height_row = QHBoxLayout()
        height_row.addWidget(self._spin_apply_row(self.height_spin, self._update_settings))
        self.flip_orientation_btn = QPushButton('ג‡„')
        self.flip_orientation_btn.setFixedWidth(32)
        self.flip_orientation_btn.setToolTip('Flip orientation (swap width ג†” height)')
        height_row.addWidget(self.flip_orientation_btn)

        f.addRow('Preset', self.preset_combo)
        f.addRow('Width', self._spin_apply_row(self.width_spin, self._update_settings))
        f.addRow('Height', height_row)
        f.addRow('', self.save_preset_btn)
        f.addRow('DPI', self._spin_apply_row(self.dpi_spin, self._update_settings))
        f.addRow('', self.zero_spacing_btn)
        f.addRow('Margin', self._spin_apply_row(self.margin_spin, self._update_settings))
        f.addRow('Spacing', self._spin_apply_row(self.spacing_spin, self._update_settings))
        f.addRow('Background', bg_type_row)
        f.addRow('', self.bg_btn)
        f.addRow('Gradient', grad_row)
        f.addRow('Angle', self.bg_grad_angle_spin)
        self.smart_crop_check = QCheckBox('Smart crop protection')
        self.smart_crop_check.setChecked(True)
        self.smart_crop_debug_check = QCheckBox('Debug smart crop overlay')
        smart_wrap = QWidget()
        smart_lay = QVBoxLayout(smart_wrap)
        smart_lay.setContentsMargins(0, 0, 0, 0)
        smart_lay.addWidget(self.smart_crop_check)
        smart_lay.addWidget(self.smart_crop_debug_check)
        f.addRow('Smart Crop', smart_wrap)
        self._reg_form_rows(f, ['Preset','Width','Height','','DPI','','Margin','Spacing',
                                'Background','','Gradient','Angle','Smart Crop'])
        layout.addWidget(canvas_sec)

        # ג”€ג”€ Bleed & Safe Area ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€
        bleed_sec = self._reg_sec('Bleed & Safe Area', collapsed=True)
        f2 = bleed_sec.add_form()
        self.bleed_spin = QDoubleSpinBox()
        self.bleed_spin.setRange(0, 20)
        self.bleed_spin.setSuffix(' mm')
        self.safe_spin = QDoubleSpinBox()
        self.safe_spin.setRange(0, 20)
        self.safe_spin.setSuffix(' mm')
        f2.addRow('Bleed', self._spin_apply_row(self.bleed_spin, self._update_canvas_style))
        f2.addRow('Safe area', self._spin_apply_row(self.safe_spin, self._update_canvas_style))
        self._reg_form_rows(f2, ['Bleed', 'Safe area'])
        layout.addWidget(bleed_sec)

        # ג”€ג”€ Cell Style ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€
        cell_sec = self._reg_sec('Cell Style', collapsed=True)
        f3 = cell_sec.add_form()
        self.corner_spin = QDoubleSpinBox()
        self.corner_spin.setRange(0, 30)
        self.corner_spin.setSuffix(' mm')
        self.border_spin = QDoubleSpinBox()
        self.border_spin.setRange(0, 10)
        self.border_spin.setSuffix(' mm')
        self.border_color_btn = QPushButton('Border colourג€¦')
        self.shadow_check = QCheckBox('Drop shadow')
        self.shadow_offset_spin = QDoubleSpinBox()
        self.shadow_offset_spin.setRange(0, 20)
        self.shadow_offset_spin.setValue(2)
        self.shadow_offset_spin.setSuffix(' mm')
        self.shadow_opacity_spin = QSpinBox()
        self.shadow_opacity_spin.setRange(0, 255)
        self.shadow_opacity_spin.setValue(100)
        f3.addRow('Corner radius', self._spin_apply_row(self.corner_spin, self._update_canvas_style))
        f3.addRow('Border width', self._spin_apply_row(self.border_spin, self._update_canvas_style))
        f3.addRow('', self.border_color_btn)
        f3.addRow('', self.shadow_check)
        f3.addRow('Shadow offset', self._spin_apply_row(self.shadow_offset_spin, self._update_canvas_style))
        f3.addRow('Shadow opacity', self._spin_apply_row(self.shadow_opacity_spin, self._update_canvas_style))
        self._reg_form_rows(f3, ['Corner radius','Border width','','','Shadow offset','Shadow opacity'])
        layout.addWidget(cell_sec)

        # ג”€ג”€ Text / Caption ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€
        text_sec = self._reg_sec('Text / Caption', collapsed=True)
        f4 = text_sec.add_form()

        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText('Captionג€¦ (double-click on canvas to edit)')
        self.font_combo = QFontComboBox()
        self.font_combo.setMinimumWidth(180)
        self.font_combo.setEditable(False)

        bi_row = QHBoxLayout()
        self.bold_check = QCheckBox('Bold')
        self.italic_check = QCheckBox('Italic')
        bi_row.addWidget(self.bold_check)
        bi_row.addWidget(self.italic_check)

        self.text_size_spin = QSpinBox()
        self.text_size_spin.setRange(6, 200)
        self.text_size_spin.setValue(36)
        self.text_color_btn = QPushButton('Text colourג€¦')
        self.text_pos_combo = QComboBox()
        self.text_pos_combo.addItems(['bottom', 'top', 'center'])
        self.text_align_combo = QComboBox()
        self.text_align_combo.addItems(['center', 'left', 'right'])
        self.text_bg_check = QCheckBox('Background box')
        self.text_bg_opacity_spin = QSpinBox()
        self.text_bg_opacity_spin.setRange(0, 100)
        self.text_bg_opacity_spin.setValue(100)
        self.text_bg_opacity_spin.setSuffix(' %')

        stroke_row = QHBoxLayout()
        self.stroke_spin = QSpinBox()
        self.stroke_spin.setRange(0, 10)
        self.stroke_spin.setSuffix(' px')
        self.stroke_color_btn = QPushButton('Stroke colourג€¦')
        stroke_row.addWidget(self.stroke_spin)
        stroke_row.addWidget(self.stroke_color_btn)

        shadow_row = QHBoxLayout()
        self.text_shadow_check = QCheckBox('Shadow')
        self.text_shadow_off_spin = QSpinBox()
        self.text_shadow_off_spin.setRange(1, 20)
        self.text_shadow_off_spin.setValue(3)
        self.text_shadow_off_spin.setSuffix(' px')
        shadow_row.addWidget(self.text_shadow_check)
        shadow_row.addWidget(self.text_shadow_off_spin)

        self.text_center_btn = QPushButton('ג• Centre on canvas')
        self.text_apply_btn = QPushButton('ג Apply ג€” add to canvas')
        self.text_apply_btn.setStyleSheet(
            'QPushButton { background: #1d7a4a; color: #fff; font-weight: bold;'
            ' padding: 5px 12px; border-radius: 6px; border: none; }'
            'QPushButton:hover { background: #2ecc71; }'
            'QPushButton:pressed { background: #179a42; }'
        )

        f4.addRow('Text', self.text_edit)
        f4.addRow('Font', self.font_combo)
        f4.addRow('Style', bi_row)
        f4.addRow('Size (pt)', self.text_size_spin)
        f4.addRow('', self.text_color_btn)
        f4.addRow('Position', self.text_pos_combo)
        f4.addRow('Align', self.text_align_combo)
        f4.addRow('', self.text_bg_check)
        f4.addRow('Bg opacity', self.text_bg_opacity_spin)
        f4.addRow('Stroke', stroke_row)
        f4.addRow('Drop shadow', shadow_row)
        f4.addRow('', self.text_center_btn)
        f4.addRow('', self.text_apply_btn)
        self._reg_form_rows(f4, ['Text','Font','Style','Size (pt)','','Position','Align',
                                 '','Bg opacity','Stroke','Drop shadow','',''])
        layout.addWidget(text_sec)

        self.custom_cols_spin = QSpinBox()
        self.custom_cols_spin.setRange(1, 12)
        self.custom_cols_spin.setValue(3)
        self.custom_rows_spin = QSpinBox()
        self.custom_rows_spin.setRange(1, 12)
        self.custom_rows_spin.setValue(2)
        self.custom_grid_info = QLabel('')
        self.custom_grid_info.setWordWrap(True)
        self.custom_grid_info.setStyleSheet('color: #666; font-size: 10px;')
        self.custom_grid_apply_btn = QPushButton('Apply custom grid')
        shape_btn_row = QHBoxLayout()
        self.shape_circle_btn = QPushButton('ג—¯  Circle')
        self.shape_heart_btn  = QPushButton('ג™¡  Heart')
        self.shape_circle_btn.setStyleSheet(
            'QPushButton { font-size:15px; padding:6px 14px; border-radius:6px; }'
            'QPushButton:hover { background:#363636; }'
        )
        self.shape_heart_btn.setStyleSheet(
            'QPushButton { font-size:15px; padding:6px 14px; border-radius:6px; color:#e05555; }'
            'QPushButton:hover { background:#3a2020; color:#ff6b6b; }'
        )
        shape_btn_row.addWidget(self.shape_circle_btn)
        shape_btn_row.addWidget(self.shape_heart_btn)
        self._shape_info_label = QLabel(
            'Generates a shaped layout and adds it to Layout Suggestions.')
        self._shape_info_label.setWordWrap(True)
        self._shape_info_label.setStyleSheet('color:#666; font-size:10px;')

        self.dyn_create_btn = QPushButton('ג  Create Dynamic Layout')
        self.dyn_create_btn.setStyleSheet(
            'QPushButton { font-size:13px; padding:7px 14px; background:#1a5a90; color:#fff;'
            ' font-weight:bold; border-radius:6px; border:none; }'
            'QPushButton:hover { background:#4a9eff; }'
            'QPushButton:pressed { background:#124872; }'
        )
        self._dyn_info_label = QLabel(
            'Creates a fully resizable split-panel layout. '
            'Drag the white dividers to resize cells interactively.')
        self._dyn_info_label.setWordWrap(True)
        self._dyn_info_label.setStyleSheet('color:#666; font-size:10px;')

        # ג”€ג”€ Elements Library ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€
        elem_sec = self._reg_sec('Elements', collapsed=True)
        self.elem_tabs = QTabWidget()
        for tab_name in (
            'Local', 'Emojis', 'Icons / Line Art', 'Hearts / Love',
            'Frames', 'Backgrounds / Overlays', 'Recent / Favorites'
        ):
            self.elem_tabs.addTab(QWidget(), tab_name)
        elem_sec.add_widget(self.elem_tabs)

        elem_search_row = QHBoxLayout()
        self.elem_search_edit = QLineEdit()
        self.elem_search_edit.setPlaceholderText('Search elements')
        self.elem_search_btn = QPushButton('Search')
        self.elem_fav_btn = QPushButton('☆')
        self.elem_fav_btn.setToolTip('Add/remove favorite')
        self.elem_fav_btn.setFixedWidth(34)
        elem_search_row.addWidget(self.elem_search_edit, 1)
        elem_search_row.addWidget(self.elem_search_btn)
        elem_search_row.addWidget(self.elem_fav_btn)
        elem_sec.add_layout(elem_search_row)

        elem_hdr = QHBoxLayout()
        self.elem_folder_btn = QPushButton('נ“‚ Set folder')
        self.elem_add_btn = QPushButton('+ Add file')
        elem_hdr.addWidget(self.elem_folder_btn)
        elem_hdr.addWidget(self.elem_add_btn)
        elem_sec.add_layout(elem_hdr)

        self.elem_list = QListWidget()
        self.elem_list.setViewMode(QListWidget.IconMode)
        self.elem_list.setIconSize(QSize(60, 60))
        self.elem_list.setGridSize(QSize(74, 80))
        self.elem_list.setResizeMode(QListWidget.Adjust)
        self.elem_list.setMovement(QListWidget.Static)
        self.elem_list.setFixedHeight(210)
        elem_sec.add_widget(self.elem_list)

        elem_ctrl = QHBoxLayout()
        self.elem_place_btn = QPushButton('ג–¶ Place on canvas')
        self.elem_place_btn.setStyleSheet(
            'QPushButton { background:#1a5a90; color:#fff; font-weight:bold;'
            ' border-radius:6px; border:none; }'
            'QPushButton:hover { background:#4a9eff; }'
        )
        self.elem_remove_btn = QPushButton('ג• Remove')
        elem_ctrl.addWidget(self.elem_place_btn)
        elem_ctrl.addWidget(self.elem_remove_btn)
        elem_sec.add_layout(elem_ctrl)

        elem_size_form = QFormLayout()
        self.elem_size_spin = QSpinBox()
        self.elem_size_spin.setRange(1, 100)
        self.elem_size_spin.setValue(20)
        self.elem_size_spin.setSuffix(' %')
        self.elem_opacity_spin = QSpinBox()
        self.elem_opacity_spin.setRange(0, 100)
        self.elem_opacity_spin.setValue(100)
        self.elem_opacity_spin.setSuffix(' %')
        elem_size_form.addRow('Size', self.elem_size_spin)
        elem_size_form.addRow('Opacity', self.elem_opacity_spin)
        self._reg_form_rows(elem_size_form, ['Size', 'Opacity'])
        elem_sec.add_layout(elem_size_form)
        layout.addWidget(elem_sec)

        # Element catalog state; local placement still flows through _place_element.
        self._elem_library_paths: List[str] = []
        self._elem_library_items: List[dict] = []
        self._elem_folder: str = ''
        self._elem_recent: List[str] = []
        self._elem_favorites: set = set()
        self._elem_cache_dir = ELEMENTS_CACHE_DIR
        self._openmoji_cache_dir = ELEMENTS_CACHE_DIR / 'openmoji'
        self._openmoji_index: List[dict] = []
        self._openmoji_index_loaded = False
        self._elem_state_loaded = False

        # Top-menu actions still use these button instances for signal reuse,
        # but we keep them out of the crowded sidebar.
        self.scan_selected_btn = QPushButton('Scan selected photos')
        self.scan_all_btn = QPushButton('Scan all photos')
        self.generate_btn = QPushButton('ג³  Generate layouts')
        self.export_btn = QPushButton('ג¬‡  Exportג€¦  (Ctrl+S)')
        self.print_btn = QPushButton('נ–¨  Print  (Ctrl+P)')
        self.swap_btn = QPushButton('ג‡„  Swap mode  (Tab)')
        self.swap_btn.setCheckable(True)
        self.undo_btn = QPushButton('ג†©  Undo  (Ctrl+Z)')
        self.redo_btn = QPushButton('ג†×  Redo  (Ctrl+Y)')
        _primary_style = (
            'QPushButton { background:#1a5a90; color:#fff; font-weight:bold;'
            ' border-radius:6px; border:none; padding:6px 12px; }'
            'QPushButton:hover { background:#4a9eff; }'
            'QPushButton:pressed { background:#124872; }'
        )
        self.scan_selected_btn.setStyleSheet(_primary_style)
        self.scan_all_btn.setStyleSheet(_primary_style)
        self.generate_btn.setStyleSheet(_primary_style)
        self.export_btn.setStyleSheet(_primary_style)
        self.print_btn.setStyleSheet(_primary_style)

        # ג”€ג”€ Selected Cell ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€
        cell_ctrl_sec = self._reg_sec('Selected Cell', collapsed=False)
        f6 = cell_ctrl_sec.add_form()
        self.selected_label = QLabel('ג€”')
        self.selected_label.setWordWrap(True)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(100, 500)
        self.zoom_slider.setValue(100)

        rot_row = QHBoxLayout()
        self.rotate_cw_btn = QPushButton('ג†» 90ֲ°')
        self.rotate_ccw_btn = QPushButton('ג†÷ 90ֲ°')
        rot_row.addWidget(self.rotate_cw_btn)
        rot_row.addWidget(self.rotate_ccw_btn)

        self.reset_btn = QPushButton('Reset image')
        self.cell_text_edit = QLineEdit()
        self.cell_text_edit.setPlaceholderText('Text for this cellג€¦')
        self.cell_text_color_btn = QPushButton('Text colourג€¦')
        self.cell_text_size_spin = QSpinBox()
        self.cell_text_size_spin.setRange(6, 200)
        self.cell_text_size_spin.setValue(24)
        self.cell_text_apply_btn = QPushButton('Apply text to cell')
        self.cell_text_apply_btn.setStyleSheet(
            'QPushButton { background:#1d7a4a; color:#fff; font-weight:bold;'
            ' border-radius:6px; border:none; }'
            'QPushButton:hover { background:#2ecc71; }'
            'QPushButton:pressed { background:#179a42; }'
        )
        f6.addRow('Cell', self.selected_label)
        f6.addRow('Zoom', self.zoom_slider)
        f6.addRow('Rotate', rot_row)
        f6.addRow('', self.reset_btn)
        f6.addRow('Cell text', self.cell_text_edit)
        f6.addRow('', self.cell_text_color_btn)
        f6.addRow('Size pt', self.cell_text_size_spin)
        f6.addRow('', self.cell_text_apply_btn)
        self._reg_form_rows(f6, ['Cell','Zoom','Rotate','','Cell text','','Size pt',''])
        layout.addWidget(cell_ctrl_sec)

        # ג”€ג”€ Image Adjustments ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€
        adj_sec = self._reg_sec('Image Adjustments', collapsed=False)
        f7 = adj_sec.add_form()

        def slider(lo, hi, val):
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            s.setValue(val)
            return s

        self.brightness_slider = slider(20, 200, 100)
        self.contrast_slider = slider(20, 200, 100)
        self.saturation_slider = slider(0, 200, 100)
        self.sharpness_slider = slider(0, 200, 100)
        self.bw_check = QCheckBox('Black & White')
        self.reset_adj_btn = QPushButton('Reset adjustments')
        f7.addRow('Brightness', self.brightness_slider)
        f7.addRow('Contrast', self.contrast_slider)
        f7.addRow('Saturation', self.saturation_slider)
        f7.addRow('Sharpness', self.sharpness_slider)
        f7.addRow('', self.bw_check)
        f7.addRow('', self.reset_adj_btn)

        # Advanced ג€” Exposure & CLAHE
        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setRange(-3.0, 3.0)
        self.exposure_spin.setSingleStep(0.01)
        self.exposure_spin.setDecimals(2)
        self.exposure_spin.setValue(0.0)
        self.exposure_spin.setSuffix(' EV')

        self.clahe_check = QCheckBox('CLAHE contrast')
        clahe_clip_row = QHBoxLayout()
        self.clahe_clip_spin = QDoubleSpinBox()
        self.clahe_clip_spin.setRange(0.0, 8.0)
        self.clahe_clip_spin.setSingleStep(0.01)
        self.clahe_clip_spin.setDecimals(2)
        self.clahe_clip_spin.setValue(2.0)
        self.clahe_clip_spin.setPrefix('clip ')
        clahe_clip_row.addWidget(self.clahe_clip_spin)
        clahe_clip_row.addStretch()
        _clahe_clip_w = QWidget()
        _clahe_clip_w.setLayout(clahe_clip_row)

        f7.addRow('Exposure', self.exposure_spin)
        f7.addRow('', self.clahe_check)
        f7.addRow('', _clahe_clip_w)

        self._reg_form_rows(f7, ['Brightness','Contrast','Saturation','Sharpness','','',
                                  'Exposure','',''])
        layout.addWidget(adj_sec)

        # Warnings
        self.warnings_label = QLabel('')
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setStyleSheet('color:#e05555; font-size:11px;')
        layout.addWidget(self.warnings_label)
        layout.addStretch()

        scroll.setWidget(inner)
        return scroll

    # ג”€ג”€ Right panel ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€
    def _build_right_panel(self) -> QWidget:
        from app.ui.float_panel import ImageAdjustPanel, TextFloatPanel

        panel = QWidget()
        panel.setFixedWidth(340)
        layout = QVBoxLayout(panel)
        layout.setSpacing(4)

        self._images_group = g = QGroupBox('Images')
        gl = QVBoxLayout(g)
        row = QHBoxLayout()
        self.import_btn = QPushButton('Importג€¦')
        self.remove_btn = QPushButton('Remove')
        self.reset_all_btn = QPushButton('Reset all')
        row.addWidget(self.import_btn)
        row.addWidget(self.remove_btn)
        row.addWidget(self.reset_all_btn)
        gl.addLayout(row)
        self.image_list = DropListWidget()
        gl.addWidget(self.image_list)
        layout.addWidget(g, 1)

        # ג”€ג”€ Stacked area: Layout Suggestions ג†” Image panel ג†” Text panel ג”€ג”€
        self._layouts_group = g2 = QGroupBox('Layout Suggestions')
        g2l = QVBoxLayout(g2)
        self.layout_list = QListWidget()
        self.layout_list.setViewMode(QListWidget.IconMode)
        self.layout_list.setIconSize(QSize(THUMB_W, THUMB_H))
        self.layout_list.setSpacing(6)
        self.layout_list.setResizeMode(QListWidget.Adjust)
        self.layout_list.setMovement(QListWidget.Static)
        self.layout_list.setGridSize(QSize(THUMB_W + 16, THUMB_H + 32))
        self.layout_list.setMinimumHeight(220)
        self.layout_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.layout_list.customContextMenuRequested.connect(self._layout_context_menu)
        g2l.addWidget(self.layout_list)

        # Sidebar image-adjust panel (width=0 ג†’ fills container, no drag)
        self.image_panel = ImageAdjustPanel(width=0)
        # Sidebar text panel
        self.text_panel = TextFloatPanel(width=0)

        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(g2)               # index 0 ג€” layouts
        self._right_stack.addWidget(self.image_panel)  # index 1 ג€” image adjust
        self._right_stack.addWidget(self.text_panel)   # index 2 ג€” text edit
        layout.addWidget(self._right_stack, 1)
        return panel

    # -------------------------------------------------------------------
    # Signals
    # -------------------------------------------------------------------

    def _connect_signals(self):
        self.import_btn.clicked.connect(self.import_images)
        self.remove_btn.clicked.connect(self.remove_selected_image)
        self.reset_all_btn.clicked.connect(self.reset_all_images)
        self.image_list.filesDropped.connect(self.add_images)
        self.generate_btn.clicked.connect(self.generate_suggestions)
        self.scan_selected_btn.clicked.connect(self.scan_selected_images)
        self.scan_all_btn.clicked.connect(self.scan_all_images)
        self.layout_list.currentRowChanged.connect(self.select_layout)
        self.canvas.cellSelected.connect(self.on_cell_selected)
        self.canvas.swapPerformed.connect(self._on_swap_performed)
        self.canvas.cellPanChanged.connect(self._check_quality_warnings)
        self.canvas.replaceImageRequested.connect(self.replace_image_in_cell)
        self.canvas.removeImageFromCell.connect(self.remove_image_from_cell)
        self.canvas.editImageInColorLab.connect(self._open_color_lab)
        self.canvas.editImageInPhotoshop.connect(self._edit_cell_in_photoshop)
        self.canvas.textMoved.connect(self._on_text_moved)
        self.canvas.textContentChanged.connect(self._on_text_content_changed)
        self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        self.rotate_cw_btn.clicked.connect(lambda: self._rotate_selected(90))
        self.rotate_ccw_btn.clicked.connect(lambda: self._rotate_selected(-90))
        self.reset_btn.clicked.connect(self.reset_selected_image)
        for s in [self.brightness_slider, self.contrast_slider,
                  self.saturation_slider, self.sharpness_slider]:
            s.valueChanged.connect(self._on_adjustment_changed)
        self.bw_check.stateChanged.connect(self._on_adjustment_changed)
        self.exposure_spin.valueChanged.connect(self._on_adjustment_changed)
        self.clahe_check.stateChanged.connect(self._on_adjustment_changed)
        self.clahe_clip_spin.valueChanged.connect(self._on_adjustment_changed)
        self.reset_adj_btn.clicked.connect(self._reset_adjustments)
        self.preset_combo.currentIndexChanged.connect(self._apply_preset)
        self.save_preset_btn.clicked.connect(self._save_current_size_preset)
        self.zero_spacing_btn.clicked.connect(self._reset_margin_spacing_to_zero)
        self.smart_crop_check.stateChanged.connect(self._update_settings)
        self.smart_crop_debug_check.stateChanged.connect(self._update_settings)
        self.bg_btn.clicked.connect(self.pick_background)
        self.bg_solid_radio.clicked.connect(lambda: self._set_bg_type('solid'))
        self.bg_gradient_radio.clicked.connect(lambda: self._set_bg_type('gradient'))
        self.bg_image_radio.clicked.connect(self._pick_bg_image)
        self.bg_grad_c1_btn.clicked.connect(lambda: self._pick_grad_color(0))
        self.bg_grad_c2_btn.clicked.connect(lambda: self._pick_grad_color(1))
        self.bg_grad_gold_btn.clicked.connect(self._set_gold_gradient)
        self.bg_grad_angle_spin.valueChanged.connect(self._update_gradient_angle)
        self.flip_orientation_btn.clicked.connect(self._flip_orientation)
        self.border_color_btn.clicked.connect(self._pick_border_color)
        self.shadow_check.stateChanged.connect(self._update_canvas_style)
        self.text_edit.textChanged.connect(self._update_text_overlay)
        self.font_combo.currentFontChanged.connect(self._update_text_overlay)
        self.bold_check.stateChanged.connect(self._update_text_overlay)
        self.italic_check.stateChanged.connect(self._update_text_overlay)
        self.text_size_spin.valueChanged.connect(self._update_text_overlay)
        self.text_color_btn.clicked.connect(self._pick_text_color)
        self.text_pos_combo.currentTextChanged.connect(self._update_text_overlay)
        self.text_align_combo.currentTextChanged.connect(self._update_text_overlay)
        self.text_bg_check.stateChanged.connect(self._update_text_overlay)
        self.text_bg_opacity_spin.valueChanged.connect(self._update_text_overlay)
        self.stroke_spin.valueChanged.connect(self._update_text_overlay)
        self.stroke_color_btn.clicked.connect(self._pick_stroke_color)
        self.text_shadow_check.stateChanged.connect(self._update_text_overlay)
        self.text_shadow_off_spin.valueChanged.connect(self._update_text_overlay)
        self.text_center_btn.clicked.connect(self._center_text_overlay)
        self.text_apply_btn.clicked.connect(self._apply_text_overlay)
        self.canvas.textSelected.connect(self._on_text_selected)
        self.canvas.textRemoveRequested.connect(self._on_text_remove)
        self.text_edit.textChanged.connect(self._update_font_combo_for_script)
        self.custom_cols_spin.valueChanged.connect(self._update_custom_grid_preview)
        self.custom_rows_spin.valueChanged.connect(self._update_custom_grid_preview)
        self.custom_grid_apply_btn.clicked.connect(self._apply_custom_grid)
        self.cell_text_apply_btn.clicked.connect(self._apply_cell_text)
        self.cell_text_color_btn.clicked.connect(self._pick_cell_text_color)
        self.shape_circle_btn.clicked.connect(lambda: self._generate_shaped('circle'))
        self.shape_heart_btn.clicked.connect(lambda: self._generate_shaped('heart'))
        self.dyn_create_btn.clicked.connect(self._create_dynamic_layout)
        self.elem_folder_btn.clicked.connect(self._set_elem_folder)
        self.elem_add_btn.clicked.connect(self._add_elem_file)
        self.elem_tabs.currentChanged.connect(self._reload_elem_library)
        self.elem_search_btn.clicked.connect(self._reload_elem_library)
        self.elem_search_edit.returnPressed.connect(self._reload_elem_library)
        self.elem_fav_btn.clicked.connect(self._toggle_selected_element_favorite)
        self.elem_list.itemDoubleClicked.connect(lambda _item: self._place_element())
        self.elem_place_btn.clicked.connect(self._place_element)
        self.elem_remove_btn.clicked.connect(self._remove_selected_element)
        self.canvas.elementSelected.connect(self._on_element_selected)
        self.elem_size_spin.valueChanged.connect(self._update_selected_element)
        self.elem_opacity_spin.valueChanged.connect(self._update_selected_element)
        self.export_btn.clicked.connect(self.export_file)
        self.print_btn.clicked.connect(self.open_print_preview)
        self.swap_btn.toggled.connect(self._on_swap_mode_toggled)
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)

        # Sidebar panel signals
        self.image_panel.changed.connect(self._on_float_image_changed)
        self.image_panel.previewOriginalPressed.connect(self._on_preview_original_pressed)
        self.image_panel.closed.connect(lambda: self._right_stack.setCurrentIndex(0))
        self.text_panel.changed.connect(self.canvas.refresh_preview)
        self.text_panel.deleted.connect(self._on_text_remove)
        self.text_panel.closed.connect(lambda: self._right_stack.setCurrentIndex(0))

    def _setup_shortcuts(self):
        # Keep all shortcuts in a list so Python doesn't GC the objects
        # (PySide6 requires a live Python reference alongside the Qt parent ownership)
        self._shortcuts: list = []

        def sc(key, fn, ctx=Qt.ApplicationShortcut):
            s = QShortcut(QKeySequence(key), self)
            s.setContext(ctx)
            s.activated.connect(fn)
            self._shortcuts.append(s)

        sc('Ctrl+N', self.new_project)
        sc('Ctrl+O', self.open_project)
        sc('Ctrl+Shift+S', self.save_project_as)
        sc('Ctrl+Q', self.close)
        sc('Ctrl+P', self.print_collage)
        sc('Ctrl+S', self.export_file)
        sc('Ctrl+T', self._focus_text_input)
        sc('Ctrl+Z', self.undo)
        sc('Ctrl+Y', self.redo)
        sc('Ctrl+I', self.import_images)
        sc('Ctrl+Equal', self._zoom_in)
        sc('Ctrl++', self._zoom_in)
        sc('Ctrl+-', self._zoom_out)
        sc('Ctrl+0', self._fit_to_screen)
        sc('+', self._brightness_up)
        sc('=', self._brightness_up)
        sc('-', self._brightness_down)
        sc('W', self._contrast_up)
        sc('S', self._contrast_down)
        sc('Delete', self._delete_key_handler)
        sc('Tab', self._toggle_swap_shortcut)
        sc('Left', lambda: self._pan_selected(-0.02, 0))
        sc('Right', lambda: self._pan_selected(0.02, 0))
        sc('Up', lambda: self._pan_selected(0, -0.02))
        sc('Down', lambda: self._pan_selected(0, 0.02))

    def _no_text_focus(self) -> bool:
        from PySide6.QtWidgets import QAbstractSpinBox, QComboBox
        fw = QApplication.focusWidget()
        return not isinstance(fw, (QLineEdit, QAbstractSpinBox, QComboBox, QTextEdit))

    # -------------------------------------------------------------------
    # Settings
    # -------------------------------------------------------------------

    def _apply_preset(self):
        name = self.preset_combo.currentText()
        w, h = PRESETS_CM[name]
        for spin, val in [(self.width_spin, w), (self.height_spin, h)]:
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)
        self._update_settings()

    def _save_current_size_preset(self) -> None:
        width = round(self.width_spin.value(), 2)
        height = round(self.height_spin.value(), 2)
        name, ok = QInputDialog.getText(self, 'Save Canvas Preset', 'Preset name:')
        if not ok or not name.strip():
            return
        label = f'{name.strip()} ({width:g} x {height:g} cm)'
        PRESETS_CM[label] = (width, height)
        try:
            custom_only = {k: v for k, v in PRESETS_CM.items() if k not in {
                '15 x 10 cm', 'A4 Portrait', 'A4 Landscape', 'A3 Portrait',
                'A3 Landscape', '30 x 40 cm', '20 x 20 cm Square',
                '50 x 70 cm', '60 x 40 cm', 'Custom',
            }}
            _save_user_presets(custom_only)
        except Exception:
            pass
        self._reload_preset_combo(selected=label)

    def _reload_preset_combo(self, selected: Optional[str] = None) -> None:
        current = selected or self.preset_combo.currentText() or 'Custom'
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(PRESETS_CM.keys())
        idx = self.preset_combo.findText(current)
        self.preset_combo.setCurrentIndex(idx if idx >= 0 else self.preset_combo.findText('Custom'))
        self.preset_combo.blockSignals(False)

    def _reset_margin_spacing_to_zero(self) -> None:
        self.margin_spin.setValue(0)
        self.spacing_spin.setValue(0)
        self._update_settings()

    def _open_custom_grid_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle('Custom Grid')
        dlg.setModal(True)
        vbox = QVBoxLayout(dlg)
        form = QFormLayout()
        cols_spin = QSpinBox()
        cols_spin.setRange(1, 12)
        cols_spin.setValue(self.custom_cols_spin.value())
        rows_spin = QSpinBox()
        rows_spin.setRange(1, 12)
        rows_spin.setValue(self.custom_rows_spin.value())
        info = QLabel('')
        info.setWordWrap(True)
        info.setStyleSheet('color:#888;')
        form.addRow('Columns', cols_spin)
        form.addRow('Rows', rows_spin)
        vbox.addLayout(form)
        vbox.addWidget(info)

        def refresh_info():
            n = len(self.project.images)
            cols = cols_spin.value()
            rows = rows_spin.value()
            cells = cols * rows
            if n <= 0:
                info.setText('Import images first.')
            elif cells < n:
                info.setText(f'Grid has {cells} cells for {n} images. Extra images will be hidden.')
            elif cells > n:
                info.setText(f'Grid has {cells} cells for {n} images. Empty placeholders will remain.')
            else:
                info.setText(f'Grid matches imported images exactly ({n}).')

        cols_spin.valueChanged.connect(lambda _v: refresh_info())
        rows_spin.valueChanged.connect(lambda _v: refresh_info())
        refresh_info()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        vbox.addWidget(buttons)
        self._apply_spinbox_arrow_style(dlg)

        if dlg.exec() != QDialog.Accepted:
            return
        self.custom_cols_spin.setValue(cols_spin.value())
        self.custom_rows_spin.setValue(rows_spin.value())
        self._apply_custom_grid()

    def _update_settings(self):
        s = self.project.settings
        s.width_cm = self.width_spin.value()
        s.height_cm = self.height_spin.value()
        s.dpi = self.dpi_spin.value()
        s.margin_mm = self.margin_spin.value()
        s.spacing_mm = self.spacing_spin.value()
        s.smart_crop_enabled = self.smart_crop_check.isChecked()
        s.smart_crop_debug = self.smart_crop_debug_check.isChecked()
        if 'smart_debug' in self._actions:
            self._actions['smart_debug'].blockSignals(True)
            self._actions['smart_debug'].setChecked(s.smart_crop_debug)
            self._actions['smart_debug'].blockSignals(False)
        if self.project.images:
            if not self._refresh_special_layout():
                if self.project.selected_layout:
                    # Canvas change only: regenerate for new pixel dimensions but
                    # keep the same layout type selected and preserve image assignments.
                    self._regenerate_preserving_layout()
                else:
                    self._generate_layout_suggestions(
                        use_analysis=(self.project.settings.analysis_mode == 'scanned')
                    )
            self._check_quality_warnings()
        else:
            self.canvas.refresh_preview()

    # -------------------------------------------------------------------
    # Lock helpers
    # -------------------------------------------------------------------

    def _on_lock_toggled(self, locked: bool) -> None:
        self._layout_locked = locked
        self._lock_btn.setText('🔒' if locked else '🔓')
        msg = 'הסידור נעול — שינויי קנבס והוספת תמונות לא ישנו את הסידור' if locked else 'הסידור פתוח'
        self.statusBar().showMessage(msg, 3000)

    def _regenerate_preserving_layout(self) -> None:
        """Regenerate layout suggestions for updated canvas dimensions while keeping
        the currently-selected layout type and image assignments unchanged."""
        old = self.project.selected_layout
        old_name = old.name if old else None
        old_assignments = {i: c.image_index for i, c in enumerate(old.cells)} if old else {}

        use_analysis = self.project.settings.analysis_mode == 'scanned'
        layout_images = self.project.images if use_analysis else [
            ImageState(path=s.path, rotation=s.rotation, analysis_status=s.analysis_status)
            for s in self.project.images
        ]

        self.project.suggestions = generate_suggestions(
            self.project.settings, len(self.project.images), images=layout_images)
        self._append_user_template_layouts()

        canvas_px = self.project.settings.canvas_px
        self.layout_list.clear()
        for layout in self.project.suggestions:
            label = f'{layout.name}  {layout.score:.0%}' if layout.score > 0 else layout.name
            item = QListWidgetItem(label)
            item.setIcon(QIcon(self._layout_thumbnail(layout, canvas_px)))
            item.setTextAlignment(Qt.AlignCenter)
            self.layout_list.addItem(item)

        new_idx = next(
            (i for i, s in enumerate(self.project.suggestions) if s.name == old_name), None)

        if new_idx is None:
            if old is not None and old not in self.project.suggestions:
                self.project.suggestions.append(old)
                old_idx = len(self.project.suggestions) - 1
                item = QListWidgetItem(old_name or 'Current layout')
                item.setIcon(QIcon(self._layout_thumbnail(old, canvas_px)))
                item.setTextAlignment(Qt.AlignCenter)
                self.layout_list.addItem(item)
            else:
                old_idx = self.project.suggestions.index(old) if old in self.project.suggestions else -1
            self.project.selected_layout = old
            if old_idx >= 0:
                self.layout_list.blockSignals(True)
                self.layout_list.setCurrentRow(old_idx)
                self.layout_list.blockSignals(False)
            self.canvas.refresh_preview()
            return

        if self.project.suggestions:
            layout = self.project.suggestions[new_idx]
            # Restore image assignments from the old layout
            for i, img_idx in old_assignments.items():
                if i < len(layout.cells):
                    layout.cells[i].image_index = img_idx
            self.project.selected_layout = layout
            self.layout_list.blockSignals(True)
            self.layout_list.setCurrentRow(new_idx)
            self.layout_list.blockSignals(False)
            self.canvas.refresh_preview()

    def _assign_new_images_to_empty_cells(self) -> None:
        """When locked, assign newly-added images to empty cells in the current layout."""
        layout = self.project.selected_layout
        if not layout:
            return
        assigned = {c.image_index for c in layout.cells if c.image_index is not None}
        unassigned_images = [i for i in range(len(self.project.images)) if i not in assigned]
        for cell in layout.cells:
            if not unassigned_images:
                break
            if cell.image_index is None:
                cell.image_index = unassigned_images.pop(0)
        self._sync_dynamic_tree_from_cells()

    def _sync_dynamic_tree_from_cells(self) -> None:
        layout = self.project.selected_layout
        tree = getattr(layout, 'tree', None) if layout else None
        if tree is None:
            return
        try:
            from app.core.layout_tree_engine import collect_leaves
            leaves = collect_leaves(tree.root)
        except Exception:
            return
        for idx, leaf in enumerate(leaves):
            if idx < len(layout.cells):
                leaf.image_index = layout.cells[idx].image_index

    # -------------------------------------------------------------------

    def _update_canvas_style(self):
        s = self.project.settings
        s.bleed_mm = self.bleed_spin.value()
        s.safe_area_mm = self.safe_spin.value()
        s.corner_radius_mm = self.corner_spin.value()
        s.border_width_mm = self.border_spin.value()
        s.shadow_enabled = self.shadow_check.isChecked()
        s.shadow_offset_mm = self.shadow_offset_spin.value()
        s.shadow_opacity = self.shadow_opacity_spin.value()
        self.canvas.refresh_preview()

    def _soft_fade_recommendation(self, fade_amount: int, spacing_override_enabled: bool, spacing_override_px: int) -> str:
        if fade_amount <= 0:
            return 'Recommended: disable Soft Fade or set 12-16 px for a subtle blend.'
        if spacing_override_enabled:
            if spacing_override_px <= 4 and fade_amount >= 14:
                return 'Recommended combo: soft overlap. Good for blended collage edges.'
            if spacing_override_px >= 18 and fade_amount <= 12:
                return 'Recommended combo: gentle fade with visible spacing between cells.'
            return 'Tip: lower spacing override for more overlap, or raise it for cleaner separation.'
        return 'Tip: enable spacing override and try 0-8 px with fade 12-20 px for smoother transitions.'

    def _open_soft_fade_dialog(self) -> None:
        settings = self.project.settings
        dlg = QDialog(self)
        dlg.setWindowTitle('Soft Fade Transition')
        dlg.setModal(True)
        layout = QVBoxLayout(dlg)
        form = QFormLayout()

        enabled_chk = QCheckBox('Enable soft fade for all cells')
        enabled_chk.setChecked(getattr(settings, 'soft_fade_enabled', False))
        mode_combo = QComboBox()
        mode_combo.addItems(['Soft Edge', 'Overlap Fade'])
        mode_combo.setCurrentIndex(1 if getattr(settings, 'soft_fade_mode', 'soft_edge') == 'overlap_fade' else 0)
        amount_spin = QSpinBox()
        amount_spin.setRange(0, 70)
        amount_spin.setSuffix(' px')
        amount_spin.setValue(int(getattr(settings, 'soft_fade_amount_px', 16)))
        overlap_spin = QSpinBox()
        overlap_spin.setRange(0, 80)
        overlap_spin.setSuffix(' px')
        overlap_spin.setValue(int(getattr(settings, 'soft_fade_overlap_px', 28)))
        sides_combo = QComboBox()
        sides_combo.addItems(['All', 'Left', 'Right', 'Top', 'Bottom', 'Horizontal', 'Vertical'])
        sides_map = {'all': 0, 'left': 1, 'right': 2, 'top': 3, 'bottom': 4, 'horizontal': 5, 'vertical': 6}
        sides_combo.setCurrentIndex(sides_map.get(getattr(settings, 'soft_fade_sides', 'all'), 0))
        overlap_sides_combo = QComboBox()
        overlap_sides_combo.addItems([
            'Auto toward neighbors', 'All', 'Left', 'Right', 'Top', 'Bottom', 'Horizontal', 'Vertical'
        ])
        overlap_sides_map = {
            'auto_neighbors': 0, 'all': 1, 'left': 2, 'right': 3, 'top': 4,
            'bottom': 5, 'horizontal': 6, 'vertical': 7,
        }
        overlap_sides_combo.setCurrentIndex(
            overlap_sides_map.get(getattr(settings, 'soft_fade_overlap_sides', 'auto_neighbors'), 0)
        )
        curve_combo = QComboBox()
        curve_combo.addItems(['Smooth', 'Linear', 'Ease Out'])
        curve_map = {'smooth': 0, 'linear': 1, 'ease_out': 2}
        curve_combo.setCurrentIndex(curve_map.get(getattr(settings, 'soft_fade_curve', 'smooth'), 0))
        spacing_override_chk = QCheckBox('Override render spacing for all cells')
        spacing_override_chk.setChecked(getattr(settings, 'soft_fade_spacing_override_enabled', False))
        spacing_override_spin = QSpinBox()
        spacing_override_spin.setRange(0, 200)
        spacing_override_spin.setSuffix(' px')
        spacing_override_spin.setValue(int(getattr(settings, 'soft_fade_spacing_override_px', settings.spacing_px)))
        recommendation = QLabel()
        recommendation.setWordWrap(True)
        recommendation.setStyleSheet('color:#7aa7d9;')

        def refresh_recommendation(*_args):
            overlap_mode = mode_combo.currentIndex() == 1
            recommendation.setText(
                self._soft_fade_recommendation(
                    amount_spin.value(),
                    spacing_override_chk.isChecked(),
                    spacing_override_spin.value(),
                )
            )
            for widget in (mode_combo, amount_spin, sides_combo, overlap_spin, overlap_sides_combo, curve_combo):
                widget.setEnabled(enabled_chk.isChecked())
            amount_spin.setEnabled(enabled_chk.isChecked())
            sides_combo.setEnabled(enabled_chk.isChecked() and not overlap_mode)
            overlap_spin.setEnabled(enabled_chk.isChecked() and overlap_mode)
            overlap_sides_combo.setEnabled(enabled_chk.isChecked() and overlap_mode)
            spacing_override_spin.setEnabled(spacing_override_chk.isChecked())

        enabled_chk.stateChanged.connect(refresh_recommendation)
        mode_combo.currentIndexChanged.connect(refresh_recommendation)
        amount_spin.valueChanged.connect(refresh_recommendation)
        overlap_spin.valueChanged.connect(refresh_recommendation)
        spacing_override_chk.stateChanged.connect(refresh_recommendation)
        spacing_override_spin.valueChanged.connect(refresh_recommendation)

        form.addRow('', enabled_chk)
        form.addRow('Edge style', mode_combo)
        form.addRow('Softness', amount_spin)
        form.addRow('Soft edge sides', sides_combo)
        form.addRow('Overlap amount', overlap_spin)
        form.addRow('Overlap sides', overlap_sides_combo)
        form.addRow('Fade curve', curve_combo)
        form.addRow('', spacing_override_chk)
        form.addRow('Spacing override', spacing_override_spin)
        layout.addLayout(form)
        layout.addWidget(recommendation)

        tips = QLabel(
            'Suggestions:\n'
            'Soft Edge: softness 12-16 px for gentle blending.\n'
            'Overlap Fade: softness 14-20 px with overlap 20-40 px.\n'
            'Auto neighbors keeps overlap inside the collage instead of leaking outward.'
        )
        tips.setWordWrap(True)
        tips.setStyleSheet('color:#999;')
        layout.addWidget(tips)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        refresh_recommendation()

        if dlg.exec() != QDialog.Accepted:
            return

        settings.soft_fade_enabled = enabled_chk.isChecked()
        settings.soft_fade_amount_px = amount_spin.value()
        settings.soft_fade_mode = ['soft_edge', 'overlap_fade'][mode_combo.currentIndex()]
        settings.soft_fade_sides = ['all', 'left', 'right', 'top', 'bottom', 'horizontal', 'vertical'][
            sides_combo.currentIndex()
        ]
        settings.soft_fade_overlap_px = overlap_spin.value()
        settings.soft_fade_overlap_sides = [
            'auto_neighbors', 'all', 'left', 'right', 'top', 'bottom', 'horizontal', 'vertical'
        ][overlap_sides_combo.currentIndex()]
        settings.soft_fade_curve = ['smooth', 'linear', 'ease_out'][curve_combo.currentIndex()]
        settings.soft_fade_spacing_override_enabled = spacing_override_chk.isChecked()
        settings.soft_fade_spacing_override_px = spacing_override_spin.value()
        self.canvas.refresh_preview()
        self._push_history()

    def _pick_border_color(self):
        color = QColorDialog.getColor(QColor(*self.project.settings.border_color_rgb), self)
        if color.isValid():
            self.project.settings.border_color_rgb = (color.red(), color.green(), color.blue())
            self.canvas.refresh_preview()

    def _flip_orientation(self):
        w = self.width_spin.value()
        h = self.height_spin.value()
        self.width_spin.blockSignals(True)
        self.height_spin.blockSignals(True)
        self.width_spin.setValue(h)
        self.height_spin.setValue(w)
        self.width_spin.blockSignals(False)
        self.height_spin.blockSignals(False)
        self._update_settings()

    def _update_text_overlay(self):
        o = self.project.text_overlay
        o.text = self.text_edit.text()
        o.font_family = self.font_combo.currentFont().family()
        o.font_bold = self.bold_check.isChecked()
        o.font_italic = self.italic_check.isChecked()
        o.font_size_pt = self.text_size_spin.value()
        o.position = self.text_pos_combo.currentText()
        o.h_align = self.text_align_combo.currentText()
        o.background_rgb = self.project.settings.background_rgb if self.text_bg_check.isChecked() else None
        o.background_opacity = self.text_bg_opacity_spin.value()
        o.stroke_width_px = self.stroke_spin.value()
        o.text_shadow = self.text_shadow_check.isChecked()
        o.text_shadow_offset_px = self.text_shadow_off_spin.value()
        self.canvas.refresh_preview()

    def _pick_text_color(self):
        color = QColorDialog.getColor(QColor(*self.project.text_overlay.color_rgb), self)
        if color.isValid():
            self.project.text_overlay.color_rgb = (color.red(), color.green(), color.blue())
            self.canvas.refresh_preview()

    def _pick_stroke_color(self):
        color = QColorDialog.getColor(QColor(*self.project.text_overlay.stroke_color_rgb), self)
        if color.isValid():
            self.project.text_overlay.stroke_color_rgb = (color.red(), color.green(), color.blue())
            self.canvas.refresh_preview()

    def _center_text_overlay(self):
        o = self.project.text_overlay
        o.pos_x_frac = 0.5
        o.pos_y_frac = 0.5
        self.canvas.refresh_preview()

    def _apply_text_overlay(self):
        """Commit the current draft overlay to the canvas and reset the form."""
        from copy import deepcopy
        o = self.project.text_overlay
        if not o.text.strip():
            return
        self.project.text_overlays.append(deepcopy(o))
        # Reset draft
        self.project.text_overlay = type(o)()
        # Reset form fields (block signals)
        for w in [self.text_edit]:
            w.blockSignals(True); w.setText(''); w.blockSignals(False)
        self.canvas.refresh_preview()
        self._push_history()
        self.statusBar().showMessage(f'Text overlay added ({len(self.project.text_overlays)} total)')

    def _on_text_selected(self, idx: int):
        """Load a committed overlay into the form for editing + show sidebar panel."""
        if idx < 0 or idx >= len(self.project.text_overlays):
            return
        o = self.project.text_overlays[idx]
        self.text_edit.blockSignals(True); self.text_edit.setText(o.text); self.text_edit.blockSignals(False)
        self.text_size_spin.blockSignals(True); self.text_size_spin.setValue(o.font_size_pt); self.text_size_spin.blockSignals(False)
        self.statusBar().showMessage(f'Editing text overlay {idx+1} ג€” click Apply to update')
        self.text_panel.load_overlay(o, idx)
        self._right_stack.setCurrentIndex(2)

    def _on_text_remove(self, idx: int):
        if 0 <= idx < len(self.project.text_overlays):
            self.project.text_overlays.pop(idx)
            self._right_stack.setCurrentIndex(0)
            self.canvas.refresh_preview()
            self._push_history()

    def _update_font_combo_for_script(self, text: str):
        """Filter font combo to show Hebrew-supporting fonts first when text is Hebrew."""
        from PySide6.QtGui import QFontDatabase, QWritingSystem
        has_hebrew = any('\u0590' <= c <= '\u05FF' for c in text)
        self.font_combo.blockSignals(True)
        if has_hebrew:
            self.font_combo.setWritingSystem(QFontDatabase.Hebrew)
        else:
            self.font_combo.setWritingSystem(QFontDatabase.Any)
        self.font_combo.blockSignals(False)

    # -------------------------------------------------------------------
    # Shortcut handlers
    # -------------------------------------------------------------------

    def _show_help(self):
        QMessageBox.information(self, 'Shortcuts & Help', SHORTCUTS_HELP)

    def _zoom_in(self):
        self.canvas.zoom_in()

    def _zoom_out(self):
        self.canvas.zoom_out()

    def _fit_to_screen(self):
        self.canvas.fit_to_screen()

    def _delete_key_handler(self):
        if self._no_text_focus():
            if self._remove_selected_element():
                return
            self.remove_selected_image()

    def _focus_text_input(self):
        self.text_edit.setFocus()
        self.text_edit.selectAll()

    def _brightness_up(self):
        if not self._no_text_focus():
            return
        state = self._selected_state()
        if state:
            state.brightness = min(2.0, state.brightness + 0.05)
            self.brightness_slider.blockSignals(True)
            self.brightness_slider.setValue(int(state.brightness * 100))
            self.brightness_slider.blockSignals(False)
            self.canvas.refresh_preview()

    def _brightness_down(self):
        if not self._no_text_focus():
            return
        state = self._selected_state()
        if state:
            state.brightness = max(0.2, state.brightness - 0.05)
            self.brightness_slider.blockSignals(True)
            self.brightness_slider.setValue(int(state.brightness * 100))
            self.brightness_slider.blockSignals(False)
            self.canvas.refresh_preview()

    def _contrast_up(self):
        if not self._no_text_focus():
            return
        state = self._selected_state()
        if state:
            state.contrast = min(2.0, state.contrast + 0.05)
            self.contrast_slider.blockSignals(True)
            self.contrast_slider.setValue(int(state.contrast * 100))
            self.contrast_slider.blockSignals(False)
            self.canvas.refresh_preview()

    def _contrast_down(self):
        if not self._no_text_focus():
            return
        state = self._selected_state()
        if state:
            state.contrast = max(0.2, state.contrast - 0.05)
            self.contrast_slider.blockSignals(True)
            self.contrast_slider.setValue(int(state.contrast * 100))
            self.contrast_slider.blockSignals(False)
            self.canvas.refresh_preview()

    def _toggle_swap_shortcut(self):
        if not self._no_text_focus():
            return
        self.swap_btn.setChecked(not self.swap_btn.isChecked())

    def _on_swap_mode_toggled(self, enabled: bool) -> None:
        self.canvas.set_swap_mode(enabled)
        if enabled:
            self._right_stack.setCurrentIndex(0)

    def _pan_selected(self, dx: float, dy: float):
        if not self._no_text_focus():
            return
        state = self._selected_state()
        if state:
            state.pan_x = max(0.0, min(1.0, state.pan_x + dx))
            state.pan_y = max(0.0, min(1.0, state.pan_y + dy))
            self.canvas.refresh_preview()

    # -------------------------------------------------------------------
    # Images
    # -------------------------------------------------------------------

    def import_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, 'Select images', '', 'Images (*.png *.jpg *.jpeg *.bmp *.webp)')
        if files:
            self.add_images(files)

    def add_images(self, files: List[str]):
        valid = [f for f in files
                 if Path(f).suffix.lower() in {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}]
        if not valid:
            return
        self.project.settings.analysis_mode = 'quick'
        had_layout = self.project.selected_layout is not None
        for file in valid:
            state = ImageState(path=file, analysis_status='quick')
            self.project.images.append(state)
            item = QListWidgetItem(Path(file).stem[:18])
            item.setToolTip(self._analysis_tooltip(file, state))
            item.setIcon(self._make_thumb_icon(file, analyzed=False))
            self.image_list.addItem(item)
        if had_layout and self.project.selected_layout:
            self._assign_new_images_to_empty_cells()
            self.canvas.refresh_preview()
            self._check_quality_warnings()
        elif not self._refresh_special_layout():
            self.generate_suggestions()
        self._push_history()

    @staticmethod
    def _make_thumb_icon(path: str, warn: bool = False, analyzed: bool = False) -> QIcon:
        return QIcon(make_thumb_icon_with_badge(
            path, IMG_THUMB_W, IMG_THUMB_H, warn=warn, analyzed=analyzed))

    def remove_selected_image(self):
        selected_items = self.image_list.selectedItems()
        if not selected_items:
            return
        # Sort descending so we can pop by index without shifting
        rows = sorted(
            [self.image_list.row(it) for it in selected_items], reverse=True
        )
        with self._suspend_history():
            for row in rows:
                if 0 <= row < len(self.project.images):
                    invalidate_cache(self.project.images[row].path)
                    self.project.images.pop(row)
                    self.image_list.takeItem(row)
                    if self.project.selected_layout:
                        for cell in self.project.selected_layout.cells:
                            if cell.image_index is not None:
                                if cell.image_index == row:
                                    cell.image_index = None
                                elif cell.image_index > row:
                                    cell.image_index -= 1
            self._sync_dynamic_tree_from_cells()
            if self.project.images:
                self._check_quality_warnings()
                self.canvas.refresh_preview()
            else:
                self.project.selected_layout = None
                self.project.suggestions = []
                self.layout_list.clear()
                self.canvas.refresh_preview()
                self.warnings_label.setText('')
        self._push_history()

    def replace_image_in_cell(self, cell_index: int):
        if not self.project.selected_layout:
            return
        cell = self.project.selected_layout.cells[cell_index]
        files, _ = QFileDialog.getOpenFileNames(
            self, 'Select replacement image', '', 'Images (*.png *.jpg *.jpeg *.bmp *.webp)')
        if not files:
            return
        file = files[0]
        self.project.settings.analysis_mode = 'quick'
        new_state = ImageState(path=file, analysis_status='quick')
        if cell.image_index is not None and cell.image_index < len(self.project.images):
            invalidate_cache(self.project.images[cell.image_index].path)
            self.project.images[cell.image_index] = new_state
            item = self.image_list.item(cell.image_index)
            item.setText(Path(file).stem[:18])
            item.setToolTip(self._analysis_tooltip(file, new_state))
            item.setIcon(self._make_thumb_icon(file, analyzed=False))
        else:
            self.project.images.append(new_state)
            cell.image_index = len(self.project.images) - 1
            item = QListWidgetItem(Path(file).stem[:18])
            item.setToolTip(self._analysis_tooltip(file, new_state))
            item.setIcon(self._make_thumb_icon(file, analyzed=False))
            self.image_list.addItem(item)
        self._sync_dynamic_tree_from_cells()
        self.canvas.refresh_preview()
        self._push_history()

    def remove_image_from_cell(self, cell_index: int):
        if not self.project.selected_layout:
            return
        cell = self.project.selected_layout.cells[cell_index]
        if cell.image_index is None:
            return
        cell.image_index = None
        self._sync_dynamic_tree_from_cells()
        self.canvas.refresh_preview()
        self._push_history()

    def _open_color_lab(self, cell_index: int) -> None:
        """Open the Smart Image Editor (Color Lab) for the image in the given cell."""
        if not self.project.selected_layout:
            return
        cell = self.project.selected_layout.cells[cell_index]
        if cell.image_index is None or cell.image_index >= len(self.project.images):
            QMessageBox.information(self, 'Color Lab', 'Please select an image first.')
            return

        state = self.project.images[cell.image_index]
        image_path = state.path

        # Late import so startup is unaffected if the bridge/engine is missing
        from app.integrations.smart_image_editor_bridge import open_smart_image_editor
        result = open_smart_image_editor(image_path, parent=self)

        if not result.get('accepted'):
            return

        exported_path = result.get('exported_path') or result.get('edited_preview_path')
        if not exported_path:
            return

        # Replace the image entry with the edited copy (non-destructive)
        invalidate_cache(state.path)
        new_state = ImageState(
            path=exported_path,
            analysis_status='quick',
            # Carry over pan/zoom so the cell framing is preserved
            pan_x=state.pan_x,
            pan_y=state.pan_y,
            zoom=state.zoom,
            rotation=state.rotation,
        )
        self.project.images[cell.image_index] = new_state

        # Update the sidebar image list entry
        item = self.image_list.item(cell.image_index)
        if item:
            item.setText(Path(exported_path).stem[:18])
            item.setToolTip(exported_path)
            item.setIcon(self._make_thumb_icon(exported_path, analyzed=False))

        self.canvas.refresh_preview()
        self._push_history()
        self.statusBar().showMessage(f'Color Lab: edited image saved to {exported_path}')

    # -------------------------------------------------------------------
    # Photoshop external editing / pixel-only refresh
    # -------------------------------------------------------------------

    def _cell_image_state(self, cell_index: int) -> Optional[ImageState]:
        layout = self.project.selected_layout
        if not layout or cell_index < 0 or cell_index >= len(layout.cells):
            return None
        image_index = layout.cells[cell_index].image_index
        if image_index is None or image_index < 0 or image_index >= len(self.project.images):
            return None
        return self.project.images[image_index]

    def _configured_photoshop_path(self) -> Optional[str]:
        env_path = os.environ.get('PHOTOSHOP_EXE') or os.environ.get('ADOBE_PHOTOSHOP_EXE')
        if env_path and Path(env_path).exists():
            return env_path
        cfg = Path.home() / '.smart_collage_photoshop_path.txt'
        try:
            raw = cfg.read_text(encoding='utf-8').strip().strip('"')
            if raw and Path(raw).exists():
                return raw
        except Exception:
            pass
        return None

    def _find_photoshop_exe(self) -> Optional[str]:
        configured = self._configured_photoshop_path()
        if configured:
            return configured
        candidates: List[Path] = []
        for root in (
            Path(os.environ.get('ProgramFiles', r'C:\Program Files')),
            Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')),
        ):
            candidates.extend(root.glob(r'Adobe\Adobe Photoshop *\Photoshop.exe'))
            candidates.extend(root.glob(r'Adobe\Photoshop *\Photoshop.exe'))
        existing = [p for p in candidates if p.exists()]
        if existing:
            existing.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return str(existing[0])
        return None

    def _edit_cell_in_photoshop(self, cell_index: int) -> None:
        state = self._cell_image_state(cell_index)
        if state is None:
            return
        image_path = Path(state.path)
        if not image_path.exists():
            self.statusBar().showMessage('הקובץ לא נמצא, לא ניתן לפתוח בפוטושופ', 5000)
            return

        try:
            photoshop = self._find_photoshop_exe()
            if photoshop:
                subprocess.Popen([photoshop, str(image_path)], close_fds=True)
            else:
                os.startfile(str(image_path))  # type: ignore[attr-defined]
                self.statusBar().showMessage(
                    'Photoshop לא נמצא. הקובץ נפתח באפליקציית ברירת המחדל.', 6000)
            self._watch_photoshop_file(str(image_path))
        except Exception as exc:
            QMessageBox.information(
                self,
                'Photoshop',
                f'לא הצלחתי לפתוח את התמונה בפוטושופ.\n{exc}',
            )
            return

    def _watch_photoshop_file(self, path: str) -> None:
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            return
        self._photoshop_watch_paths[path] = mtime
        if path not in self._photoshop_fs_watcher.files():
            self._photoshop_fs_watcher.addPath(path)
        if not self._photoshop_poll_timer.isActive():
            self._photoshop_poll_timer.start()
        self.statusBar().showMessage('התמונה נפתחה לעריכה. אשמור על רענון אוטומטי.', 5000)

    def _on_watched_image_changed(self, path: str) -> None:
        if path in self._photoshop_watch_paths:
            self._queue_pixel_refresh(path)
            if Path(path).exists() and path not in self._photoshop_fs_watcher.files():
                self._photoshop_fs_watcher.addPath(path)

    def _poll_photoshop_watches(self) -> None:
        if not self._photoshop_watch_paths:
            self._photoshop_poll_timer.stop()
            return
        for path, last_mtime in list(self._photoshop_watch_paths.items()):
            if not self._path_is_in_project(path):
                self._photoshop_watch_paths.pop(path, None)
                if path in self._photoshop_fs_watcher.files():
                    self._photoshop_fs_watcher.removePath(path)
                continue
            try:
                current_mtime = Path(path).stat().st_mtime
            except OSError:
                self._photoshop_watch_paths.pop(path, None)
                if path in self._photoshop_fs_watcher.files():
                    self._photoshop_fs_watcher.removePath(path)
                self.statusBar().showMessage('קובץ התמונה לא נמצא, הרענון האוטומטי בוטל', 5000)
                continue
            if current_mtime > last_mtime:
                self._photoshop_watch_paths[path] = current_mtime
                self._queue_pixel_refresh(path)

    def _queue_pixel_refresh(self, path: str) -> None:
        timer = self._photoshop_refresh_timers.get(path)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda p=path: self._refresh_single_image_path(p, auto=True))
            self._photoshop_refresh_timers[path] = timer
        timer.start(750)

    def _path_is_in_project(self, path: str) -> bool:
        norm = os.path.normcase(os.path.abspath(path))
        return any(os.path.normcase(os.path.abspath(state.path)) == norm for state in self.project.images)

    def _refresh_single_image_path(self, path: str, auto: bool = False) -> bool:
        if not self._path_is_in_project(path):
            return False
        if not Path(path).exists():
            self.statusBar().showMessage('קובץ התמונה לא נמצא, לא ניתן לרענן', 5000)
            return False
        try:
            self._photoshop_watch_paths[path] = Path(path).stat().st_mtime
        except OSError:
            pass
        invalidate_cache(path)
        for idx, state in enumerate(self.project.images):
            if os.path.normcase(os.path.abspath(state.path)) == os.path.normcase(os.path.abspath(path)):
                item = self.image_list.item(idx)
                if item:
                    analyzed = getattr(state, 'analysis_status', 'quick') == 'scanned'
                    item.setIcon(self._make_thumb_icon(state.path, analyzed=analyzed))
                    item.setToolTip(self._analysis_tooltip(state.path, state))
        self.canvas.refresh_preview()
        self._check_quality_warnings()
        if auto:
            self.statusBar().showMessage('התמונה עודכנה ✔', 3500)
        return True

    def refresh_images_from_disk(self) -> None:
        refreshed = 0
        missing = 0
        seen: set[str] = set()
        for state in list(self.project.images):
            path = state.path
            norm = os.path.normcase(os.path.abspath(path))
            if norm in seen:
                continue
            seen.add(norm)
            if not Path(path).exists():
                missing += 1
                continue
            if self._refresh_single_image_path(path, auto=False):
                refreshed += 1
        if refreshed:
            self.statusBar().showMessage('התמונות עודכנו ✔', 3500)
        elif missing:
            self.statusBar().showMessage('חלק מקבצי התמונות לא נמצאו', 5000)
        else:
            self.statusBar().showMessage('אין תמונות לרענון', 3500)

    def _clear_external_image_watches(self) -> None:
        self._photoshop_watch_paths.clear()
        watched = self._photoshop_fs_watcher.files()
        if watched:
            self._photoshop_fs_watcher.removePaths(watched)
        for timer in self._photoshop_refresh_timers.values():
            timer.stop()
        self._photoshop_refresh_timers.clear()
        self._photoshop_poll_timer.stop()

    @staticmethod
    def _natural_size(path: str) -> Tuple[int, int]:
        try:
            from PIL import Image, ImageOps
            with Image.open(path) as img:
                return ImageOps.exif_transpose(img).size
        except Exception:
            return (1, 1)

    # -------------------------------------------------------------------
    # Layout
    # -------------------------------------------------------------------

    # -------------------------------------------------------------------
    # Special-layout refresh helpers
    # -------------------------------------------------------------------

    def _active_special_kind(self) -> str:
        """Return 'shape', 'dynamic', or '' for the currently selected layout."""
        lay = self.project.selected_layout
        if lay is None:
            return ''
        if getattr(lay, 'shape', ''):
            return 'shape'
        if getattr(lay, 'tree', None) is not None:
            return 'dynamic'
        return ''

    def _refresh_special_layout(self) -> bool:
        """Regenerate the active shaped/dynamic layout with current settings & image count.

        Returns True if a special layout was handled (caller should skip the
        regular generate_suggestions call).  Returns False if no special layout
        is active.
        """
        kind = self._active_special_kind()
        if not kind:
            return False

        if kind == 'shape':
            shape = self.project.selected_layout.shape  # type: ignore[union-attr]
            old_assignments = {
                i: c.image_index for i, c in enumerate(self.project.selected_layout.cells)
            }
            if not self.project.images:
                return True   # nothing to do, just stay quiet
            layout = generate_shaped_layout(
                shape, len(self.project.images), self.project.settings)
            if not layout.cells:
                # Shape packing failed for this image count ג€” fall back to normal
                return False
            # Replace old shaped entry in suggestions list and re-select
            self.project.suggestions = [
                s for s in self.project.suggestions
                if getattr(s, 'shape', '') != shape
            ]
            self.project.suggestions.append(layout)
            for i, img_idx in old_assignments.items():
                if i < len(layout.cells):
                    layout.cells[i].image_index = img_idx
            self.project.selected_layout = layout
            self._apply_face_pan_to_layout(layout)
            self._rebuild_layout_list(select=layout)
            self.canvas.refresh_preview()
            return True

        if kind == 'dynamic':
            if not self.project.images:
                return True
            from app.core.layout_tree_engine import (
                cells_from_tree, collect_leaves)
            old_tree = self.project.selected_layout.tree   # type: ignore[union-attr]
            old_assignments = [
                cell.image_index for cell in self.project.selected_layout.cells
            ]
            old_leaves = collect_leaves(old_tree.root) if old_tree else []
            for idx, img_idx in enumerate(old_assignments):
                if idx < len(old_leaves):
                    old_leaves[idx].image_index = img_idx
            cw, ch = self.project.settings.canvas_px
            cells = cells_from_tree(old_tree, cw, ch)  # type: ignore[arg-type]
            for idx, img_idx in enumerate(old_assignments):
                if idx < len(cells):
                    cells[idx].image_index = img_idx
            self.project.selected_layout.cells = cells
            self._sync_dynamic_tree_from_cells()
            self.canvas.refresh_preview()
            return True

        return False

    def _rebuild_layout_list(self, select=None) -> None:
        """Repopulate self.layout_list from self.project.suggestions.
        If *select* is given, set the current row to that layout's index.
        """
        canvas_px = self.project.settings.canvas_px
        self.layout_list.clear()
        for s in self.project.suggestions:
            lbl = f'{s.name}  {s.score:.0%}' if s.score > 0 else s.name
            it = QListWidgetItem(lbl)
            it.setIcon(QIcon(self._layout_thumbnail(s, canvas_px)))
            it.setTextAlignment(Qt.AlignCenter)
            self.layout_list.addItem(it)
        if select is not None and select in self.project.suggestions:
            idx = self.project.suggestions.index(select)
            self.layout_list.blockSignals(True)
            self.layout_list.setCurrentRow(idx)
            self.layout_list.blockSignals(False)

    def _layout_context_menu(self, pos) -> None:
        """Right-click menu on layout list ג€” allow deleting user-created layouts."""
        row = self.layout_list.indexAt(pos).row()
        if row < 0 or row >= len(self.project.suggestions):
            return
        layout = self.project.suggestions[row]
        # Only allow deletion of user-saved template layouts (have template_id)
        if not getattr(layout, 'template_id', ''):
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            'QMenu{background:#2a2a2a;color:#e0e0e0;border:1px solid #3d3d3d;}'
            'QMenu::item:selected{background:#3a3a3a;}'
        )
        del_action = menu.addAction('נ—‘  Delete Layout')
        action = menu.exec_(self.layout_list.mapToGlobal(pos))
        if action == del_action:
            was_selected = (self.project.selected_layout is layout)
            self.project.suggestions.pop(row)
            self._rebuild_layout_list()
            if was_selected and self.project.suggestions:
                new_row = min(row, len(self.project.suggestions) - 1)
                self.layout_list.setCurrentRow(new_row)
            elif not self.project.suggestions:
                self.project.selected_layout = None
                self.canvas.refresh_preview()
            self._push_history()

    def _generate_layout_suggestions(self, use_analysis: bool, select_best: bool = True) -> None:
        if not self.project.images:
            QMessageBox.information(self, 'No images', 'Import images first.')
            return

        if use_analysis:
            layout_images = self.project.images
            self.project.settings.analysis_mode = 'scanned'
        else:
            layout_images = [
                ImageState(path=state.path, rotation=state.rotation, analysis_status=state.analysis_status)
                for state in self.project.images
            ]
            self.project.settings.analysis_mode = 'quick'

        self.project.suggestions = generate_suggestions(
            self.project.settings,
            len(self.project.images),
            images=layout_images,
        )

        self._append_user_template_layouts()

        self.layout_list.clear()
        canvas_px = self.project.settings.canvas_px
        for layout in self.project.suggestions:
            label = f'{layout.name}  {layout.score:.0%}' if layout.score > 0 else layout.name
            item = QListWidgetItem(label)
            item.setIcon(QIcon(self._layout_thumbnail(layout, canvas_px)))
            item.setTextAlignment(Qt.AlignCenter)
            self.layout_list.addItem(item)
        if self.project.suggestions and select_best:
            self.layout_list.setCurrentRow(0)
            self._apply_face_pan_to_layout(self.project.suggestions[0])
        self._check_quality_warnings()

    def generate_suggestions(self):
        self._generate_layout_suggestions(use_analysis=False)

    def smart_arrange(self):
        self._generate_layout_suggestions(
            use_analysis=(self.project.settings.analysis_mode == 'scanned')
        )
        if self.project.selected_layout:
            self._apply_face_pan_to_layout(self.project.selected_layout)
            self.canvas.refresh_preview()
            self._push_history()
            self.statusBar().showMessage('סידור חכם הופעל')

    def scan_selected_images(self):
        rows = sorted({self.image_list.row(item) for item in self.image_list.selectedItems()})
        rows = [row for row in rows if 0 <= row < len(self.project.images)]
        if not rows:
            QMessageBox.information(self, 'No images selected', 'Select one or more images to scan.')
            return
        self._scan_images(rows)

    def scan_all_images(self):
        if not self.project.images:
            QMessageBox.information(self, 'No images', 'Import images first.')
            return
        self._scan_images(list(range(len(self.project.images))))

    def _scan_images(self, indices: List[int]) -> None:
        if not indices:
            return
        progress = QProgressDialog(f'Scanning {len(indices)} images...', None, 0, len(indices), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(250)
        backend = self.project.settings.advanced_face_backend

        for step, image_index in enumerate(indices, start=1):
            progress.setValue(step - 1)
            QApplication.processEvents()
            state = self.project.images[image_index]
            self._refresh_image_analysis(state, force=True, face_backend=backend)
            target = self._cell_target_for_image(image_index)
            state.pan_x, state.pan_y = self._auto_pan(state, target)
            item = self.image_list.item(image_index)
            if item:
                item.setToolTip(self._analysis_tooltip(state.path, state))
                item.setIcon(self._make_thumb_icon(state.path, analyzed=True))

        progress.setValue(len(indices))
        if self.project.selected_layout:
            self._apply_face_pan_to_layout(self.project.selected_layout)
        self._check_quality_warnings()
        self.canvas.refresh_preview()
        status = 'Advanced scan complete'
        if retinaface_available():
            status += ' (RetinaFace active)'
        else:
            status += f' ({advanced_face_install_hint()})'
        self.statusBar().showMessage(status, 5000)
        self._push_history()

    def _append_user_template_layouts(self) -> None:
        """Load templates saved in ~/Documents/SmartCollageTemplates and add them
        to project.suggestions as LayoutSuggestion objects so they appear in the
        layout panel alongside the auto-generated layouts."""
        import os
        from app.core.template_io import load_templates_from_dir
        from app.core.template_engine import template_to_layout

        templates_dir = os.path.join(
            os.path.expanduser('~'), 'Documents', 'SmartCollageTemplates'
        )
        if not os.path.isdir(templates_dir):
            return

        existing_ids = {
            getattr(s, 'template_id', '') for s in self.project.suggestions
        }
        canvas_px = self.project.settings.canvas_px
        n_images  = len(self.project.images)

        for tmpl in load_templates_from_dir(templates_dir):
            if getattr(tmpl, 'id', '') in existing_ids:
                continue  # already present (e.g. recently applied)
            layout = template_to_layout(tmpl, canvas_px)
            # Assign images in project order up to the number available
            for i, cell in enumerate(layout.cells):
                cell.image_index = i if i < n_images else None
            self.project.suggestions.append(layout)
            existing_ids.add(tmpl.id)

    def _update_custom_grid_preview(self):
        """Show info text and live-preview the custom grid when images are loaded."""
        cols = self.custom_cols_spin.value()
        rows = self.custom_rows_spin.value()
        n = len(self.project.images)
        capacity = cols * rows
        if n == 0:
            self.custom_grid_info.setText('Import images first.')
            return
        if capacity < n:
            self.custom_grid_info.setText(
                f'{cols}ֳ—{rows} = {capacity} cells ג€” too few for {n} images. '
                f'Increase rows or columns.'
            )
        else:
            extra = capacity - n
            self.custom_grid_info.setText(
                f'{cols}ֳ—{rows} = {capacity} cells for {n} images'
                + (f' ({extra} empty)' if extra else ' (perfect fit)')
            )

    def _apply_custom_grid(self):
        """Commit the custom grid: add it to suggestions and select it."""
        if not self.project.images:
            QMessageBox.information(self, 'No images', 'Import images first.')
            return
        cols = self.custom_cols_spin.value()
        rows = self.custom_rows_spin.value()
        n = len(self.project.images)
        layout = custom_grid_layout(self.project.settings, n, cols=cols, rows=rows)
        # Replace any previous custom grid suggestion, or append
        self.project.suggestions = [
            s for s in self.project.suggestions if not s.name.startswith('Custom')
        ]
        self.project.suggestions.append(layout)
        # Rebuild the layout list
        self.layout_list.clear()
        canvas_px = self.project.settings.canvas_px
        for sug in self.project.suggestions:
            label = f'{sug.name}  {sug.score:.0%}' if sug.score > 0 else sug.name
            item = QListWidgetItem(label)
            item.setIcon(QIcon(self._layout_thumbnail(sug, canvas_px)))
            item.setTextAlignment(Qt.AlignCenter)
            self.layout_list.addItem(item)
        # Select the custom layout and re-centre faces
        self.project.selected_layout = layout
        self._apply_face_pan_to_layout(layout)
        self.layout_list.blockSignals(True)
        self.layout_list.setCurrentRow(len(self.project.suggestions) - 1)
        self.layout_list.blockSignals(False)
        self.canvas.refresh_preview()
        self._push_history()
        self.statusBar().showMessage(f'Custom grid {cols}ֳ—{rows} applied.')

    def _generate_shaped(self, shape: str) -> None:
        if not self.project.images:
            QMessageBox.information(self, 'No images', 'Import images first.')
            return
        layout = generate_shaped_layout(shape, len(self.project.images), self.project.settings)
        if not layout.cells:
            QMessageBox.warning(self, 'Layout failed',
                                'Could not fit images inside the shape. Try fewer images.')
            return
        # Remove previous layout of same shape if it exists
        self.project.suggestions = [s for s in self.project.suggestions
                                     if getattr(s, 'shape', '') != shape]
        self.project.suggestions.append(layout)

        canvas_px = self.project.settings.canvas_px
        label = f'{layout.name}  {layout.score:.0%}'
        item = QListWidgetItem(label)
        item.setIcon(QIcon(self._layout_thumbnail(layout, canvas_px)))
        item.setTextAlignment(Qt.AlignCenter)

        # Rebuild layout list (simpler than incremental update)
        self.layout_list.clear()
        for s in self.project.suggestions:
            lbl = f'{s.name}  {s.score:.0%}' if s.score > 0 else s.name
            it = QListWidgetItem(lbl)
            it.setIcon(QIcon(self._layout_thumbnail(s, canvas_px)))
            it.setTextAlignment(Qt.AlignCenter)
            self.layout_list.addItem(it)

        # Select the new shaped layout
        new_idx = self.project.suggestions.index(layout)
        self.layout_list.setCurrentRow(new_idx)
        self.statusBar().showMessage(f'{layout.name} layout generated.')

    def _create_dynamic_layout(self) -> None:
        """Build a balanced binary-split tree layout and add it to suggestions."""
        if not self.project.images:
            QMessageBox.information(self, 'No images', 'Import images first.')
            return
        from app.core.layout_tree_engine import build_tree, cells_from_tree
        n = len(self.project.images)
        spacing = self.project.settings.spacing_px
        # build_tree assigns image_index 0..n-1 on leaves in DFS order
        tree = build_tree(n, spacing=spacing)
        cw, ch = self.project.settings.canvas_px
        cells = cells_from_tree(tree, cw, ch)

        layout = LayoutSuggestion(name='Dynamic', cells=cells, score=0.0)
        layout.shape = ''
        layout.tree = tree

        # Replace any previous dynamic layout so the list doesn't grow unbounded
        self.project.suggestions = [s for s in self.project.suggestions
                                     if getattr(s, 'tree', None) is None]
        self.project.suggestions.append(layout)

        canvas_px = self.project.settings.canvas_px
        self.layout_list.clear()
        for s in self.project.suggestions:
            lbl = f'{s.name}  {s.score:.0%}' if s.score > 0 else s.name
            it = QListWidgetItem(lbl)
            it.setIcon(QIcon(self._layout_thumbnail(s, canvas_px)))
            it.setTextAlignment(Qt.AlignCenter)
            self.layout_list.addItem(it)

        new_idx = self.project.suggestions.index(layout)
        self.layout_list.setCurrentRow(new_idx)
        self.statusBar().showMessage(
            f'Dynamic layout created for {n} image{"s" if n != 1 else ""}. '
            'Drag the white dividers to resize cells.')

    # -------------------------------------------------------------------
    # Template Creator
    # -------------------------------------------------------------------

    def _open_template_creator(self) -> None:
        """Open the Template Creator dialog (File ג†’ Template Creatorג€¦)."""
        from app.ui.template_creator import TemplateCreatorDialog
        from app.core.template_engine import apply_template_to_project

        dlg = TemplateCreatorDialog(parent=self)
        if dlg.exec() != TemplateCreatorDialog.Accepted:
            return   # user cancelled / closed without applying

        template = dlg.get_template()
        layout   = apply_template_to_project(template, self.project)

        # Auto-assign images in project order if any are loaded
        for i, cell in enumerate(layout.cells):
            cell.image_index = i if i < len(self.project.images) else None

        # Refresh the layout list and select the new entry
        self._rebuild_layout_list(select=layout)
        self.canvas.refresh_preview()
        self._check_quality_warnings()
        self._push_history()
        self.statusBar().showMessage(
            f'Template "{template.name}" applied ג€” {len(template.slots)} slot(s).')

    def _layout_thumbnail(self, layout, canvas_px: Tuple[int, int]) -> QPixmap:
        cw, ch = canvas_px
        sx, sy = THUMB_W / max(1, cw), THUMB_H / max(1, ch)
        pix = QPixmap(THUMB_W, THUMB_H)
        pix.fill(QColor(245, 245, 245))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)

        shape = getattr(layout, 'shape', '')
        colors = [QColor(c) for c in ('#b4c8e0', '#a0b8d8', '#8caed0', '#c8daea', '#96b8cc')]

        # For shaped layouts, draw a clipping mask so cells appear inside the shape
        if shape:
            from PySide6.QtGui import QPainterPath
            import math as _math
            path = QPainterPath()
            if shape == 'circle':
                r = min(THUMB_W, THUMB_H) / 2 - 4
                path.addEllipse(THUMB_W / 2 - r, THUMB_H / 2 - r, r * 2, r * 2)
            elif shape == 'heart':
                # Approximate heart with bezier curves for the thumbnail
                import numpy as _np
                n = 120
                ts = _np.linspace(0, 2 * _math.pi, n)
                hx = 16 * _np.sin(ts) ** 3
                hy = -(13 * _np.cos(ts) - 5 * _np.cos(2 * ts) - 2 * _np.cos(3 * ts) - _np.cos(4 * ts))
                pad = 4
                scl = min((THUMB_W - 2 * pad) / max(1, hx.max() - hx.min()),
                           (THUMB_H - 2 * pad) / max(1, hy.max() - hy.min()))
                ox = (THUMB_W - (hx.max() - hx.min()) * scl) / 2 - hx.min() * scl
                oy = (THUMB_H - (hy.max() - hy.min()) * scl) / 2 - hy.min() * scl
                pts = [(hx[i] * scl + ox, hy[i] * scl + oy) for i in range(n)]
                from PySide6.QtCore import QPointF
                path.moveTo(QPointF(*pts[0]))
                for pt in pts[1:]:
                    path.lineTo(QPointF(*pt))
                path.closeSubpath()
            p.setClipPath(path)
            # Fill the clipped region with light blue tint
            p.fillPath(path, QColor(220, 230, 245))

        p.setPen(QPen(QColor(120, 120, 120), 1))
        thumb_cells = sorted(
            enumerate(layout.cells),
            key=lambda item: (int(getattr(item[1], 'z_index', 0)), item[0]),
        )
        for i, cell in thumb_cells:
            x = max(0, int(cell.x * sx))
            y = max(0, int(cell.y * sy))
            w = max(1, int(cell.w * sx))
            h = max(1, int(cell.h * sy))
            rot = float(getattr(cell, 'rotation_deg', 0.0))
            if abs(rot) > 0.01:
                p.save()
                p.translate(x + w / 2, y + h / 2)
                p.rotate(rot)
                p.translate(-(x + w / 2), -(y + h / 2))
            p.fillRect(x, y, w, h, colors[i % len(colors)])
            p.drawRect(x, y, w - 1, h - 1)
            if abs(rot) > 0.01:
                p.restore()

        if shape:
            p.setClipping(False)
            p.setPen(QPen(QColor(80, 80, 80), 1))
            p.drawPath(path)

        # For tree layouts, overlay thin divider lines to hint interactivity
        tree = getattr(layout, 'tree', None)
        if tree is not None:
            from app.core.layout_tree_engine import compute_rects, collect_dividers
            compute_rects(tree, cw, ch)
            dividers = collect_dividers(tree.root)
            p.setPen(QPen(QColor(255, 255, 255, 200), 1))
            for split_node, (dx, dy, dw, dh) in dividers:
                if split_node.direction == 'H':
                    lx = int((dx + dw / 2) * sx)
                    p.drawLine(lx, int(dy * sy), lx, int((dy + dh) * sy))
                else:
                    ly = int((dy + dh / 2) * sy)
                    p.drawLine(int(dx * sx), ly, int((dx + dw) * sx), ly)

        p.end()
        return pix

    def _apply_face_pan_to_layout(self, layout) -> None:
        """Re-compute pan_x/pan_y for every image using the actual cell dimensions.

        Delegates to _auto_pan() which handles both the face-detected case and the
        portrait-in-landscape heuristic fallback when no faces were found.
        """
        if layout is None:
            return
        for cell in layout.cells:
            if cell.image_index is None or cell.image_index >= len(self.project.images):
                continue
            state = self.project.images[cell.image_index]
            target = (max(1, int(round(cell.w))), max(1, int(round(cell.h))))
            state.pan_x, state.pan_y = self._auto_pan(state, target)

    def select_layout(self, index: int):
        if index < 0 or index >= len(self.project.suggestions):
            return
        layout = self.project.suggestions[index]
        self.project.selected_layout = layout
        self._apply_face_pan_to_layout(layout)   # ג† re-centre faces for this layout's cells
        self.canvas.refresh_preview()
        self._check_quality_warnings()
        self._push_history()

    # -------------------------------------------------------------------
    # Cell / adjustment controls
    # -------------------------------------------------------------------

    def on_cell_selected(self, index: int):
        if not self.project.selected_layout or index < 0:
            self.selected_label.setText('ג€”')
            self._right_stack.setCurrentIndex(0)
            return
        cell = self.project.selected_layout.cells[index]
        label = f'Cell {index + 1}'
        cell_w_mm = cell.w * 25.4 / max(1, self.project.settings.dpi)
        cell_h_mm = cell.h * 25.4 / max(1, self.project.settings.dpi)
        label += f'\nSize: {cell_w_mm:.1f} × {cell_h_mm:.1f} mm'
        if max(cell_w_mm, cell_h_mm) >= 100.0:
            label += f'  ({cell_w_mm / 10.0:.2f} × {cell_h_mm / 10.0:.2f} cm)'
        if cell.image_index is not None and cell.image_index < len(self.project.images):
            state = self.project.images[cell.image_index]
            label += f'\n{Path(state.path).name}'
            if state.face_regions:
                label += f'  [{len(state.face_regions)} face]'
            if getattr(state, 'analysis', None):
                analysis = state.analysis
                label += f'\nFaces: {len(analysis.faces)}  People: {len(analysis.persons)}'
                label += f'\nType: {analysis.image_type}'
            else:
                label += '\nAnalysis: quick placement only'
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(int(state.zoom * 100))
            self.zoom_slider.blockSignals(False)
            self._load_adjustments(state)
            self.image_panel.load_state(state)
            self._right_stack.setCurrentIndex(1)
        else:
            self._right_stack.setCurrentIndex(0)
        self.selected_label.setText(label)

    def _load_adjustments(self, state: ImageState):
        for w in [self.brightness_slider, self.contrast_slider,
                  self.saturation_slider, self.sharpness_slider, self.bw_check,
                  self.exposure_spin, self.clahe_check, self.clahe_clip_spin]:
            w.blockSignals(True)
        self.brightness_slider.setValue(int(state.brightness * 100))
        self.contrast_slider.setValue(int(state.contrast * 100))
        self.saturation_slider.setValue(int(state.saturation * 100))
        self.sharpness_slider.setValue(int(state.sharpness * 100))
        self.bw_check.setChecked(state.is_bw)
        self.exposure_spin.setValue(getattr(state, 'exposure_ev', 0.0))
        self.clahe_check.setChecked(getattr(state, 'clahe_enabled', False))
        self.clahe_clip_spin.setValue(getattr(state, 'clahe_clip', 2.0))
        for w in [self.brightness_slider, self.contrast_slider,
                  self.saturation_slider, self.sharpness_slider, self.bw_check,
                  self.exposure_spin, self.clahe_check, self.clahe_clip_spin]:
            w.blockSignals(False)

    def on_zoom_changed(self, value: int):
        state = self._selected_state()
        if state:
            state.zoom = value / 100.0
            self.canvas.refresh_preview()

    def _rotate_selected(self, delta: int):
        state = self._selected_state()
        if state:
            state.rotation = (state.rotation + delta) % 360
            self.canvas.refresh_preview()
            self._push_history()

    def _on_adjustment_changed(self):
        state = self._selected_state()
        if state is None:
            return
        state.brightness = self.brightness_slider.value() / 100.0
        state.contrast = self.contrast_slider.value() / 100.0
        state.saturation = self.saturation_slider.value() / 100.0
        state.sharpness = self.sharpness_slider.value() / 100.0
        state.is_bw = self.bw_check.isChecked()
        state.exposure_ev = self.exposure_spin.value()
        state.clahe_enabled = self.clahe_check.isChecked()
        state.clahe_clip = self.clahe_clip_spin.value()
        self.canvas.refresh_preview()
        # Keep sidebar image panel in sync with sliders
        if self._right_stack.currentIndex() == 1:
            self.image_panel.load_state(state)

    def _on_float_image_changed(self) -> None:
        """Image panel changed state ג€” sync sidebar sliders and refresh canvas."""
        state = self._selected_state()
        if state:
            self._load_adjustments(state)
        self.canvas.refresh_preview()

    def _on_preview_original_pressed(self, pressed: bool) -> None:
        idx = self.canvas.selected_cell_index
        if pressed and idx >= 0:
            self.canvas.set_compare_preview(idx)
        else:
            self.canvas.clear_compare_preview()

    def _reset_adjustments(self):
        state = self._selected_state()
        if state is None:
            return
        state.brightness = state.contrast = state.saturation = state.sharpness = 1.0
        state.is_bw = False
        state.exposure_ev = 0.0
        state.clahe_enabled = False
        state.clahe_clip = 2.0
        state.levels_r = state.levels_g = state.levels_b = (0, 255)
        reset_color_equalizer(state.color_equalizer)
        state.color_equalizer.enabled = False
        for w in [self.brightness_slider, self.contrast_slider,
                  self.saturation_slider, self.sharpness_slider]:
            w.blockSignals(True)
            w.setValue(100)
            w.blockSignals(False)
        self.bw_check.blockSignals(True)
        self.bw_check.setChecked(False)
        self.bw_check.blockSignals(False)
        self.exposure_spin.blockSignals(True)
        self.exposure_spin.setValue(0.0)
        self.exposure_spin.blockSignals(False)
        self.clahe_check.blockSignals(True)
        self.clahe_check.setChecked(False)
        self.clahe_check.blockSignals(False)
        self.clahe_clip_spin.blockSignals(True)
        self.clahe_clip_spin.setValue(2.0)
        self.clahe_clip_spin.blockSignals(False)
        if self._right_stack.currentIndex() == 1:
            self.image_panel.load_state(state)
        self.canvas.refresh_preview()
        self._push_history()

    def _selected_state(self) -> Optional[ImageState]:
        if not self.project.selected_layout:
            return None
        idx = self.canvas.selected_cell_index
        if idx < 0 or idx >= len(self.project.selected_layout.cells):
            return None
        cell = self.project.selected_layout.cells[idx]
        if cell.image_index is None or cell.image_index >= len(self.project.images):
            return None
        return self.project.images[cell.image_index]

    # -------------------------------------------------------------------
    # Text overlay sync
    # -------------------------------------------------------------------

    def _on_text_moved(self):
        self._push_history()

    def _on_text_content_changed(self, text: str):
        self.text_edit.blockSignals(True)
        self.text_edit.setText(text)
        self.text_edit.blockSignals(False)
        self._push_history()

    # -------------------------------------------------------------------
    # Background
    # -------------------------------------------------------------------

    def pick_background(self):
        color = QColorDialog.getColor(QColor(*self.project.settings.background_rgb), self)
        if color.isValid():
            self.project.settings.background_rgb = (color.red(), color.green(), color.blue())
            self.canvas.refresh_preview()
            self._push_history()

    def _set_bg_type(self, bg_type: str):
        self.project.settings.background_type = bg_type
        for btn, t in [(self.bg_solid_radio, 'solid'),
                       (self.bg_gradient_radio, 'gradient'),
                       (self.bg_image_radio, 'image')]:
            btn.setChecked(t == bg_type)
        self.canvas.refresh_preview()

    def _pick_bg_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select background image', '',
            'Images (*.png *.jpg *.jpeg *.bmp *.webp)')
        if path:
            self.project.settings.background_type = 'image'
            self.project.settings.background_image_path = path
            for b in [self.bg_solid_radio, self.bg_gradient_radio, self.bg_image_radio]:
                b.setChecked(False)
            self.bg_image_radio.setChecked(True)
            self.canvas.refresh_preview()

    def _pick_grad_color(self, idx: int):
        current = self.project.settings.background_gradient[idx]
        color = QColorDialog.getColor(QColor(*current), self)
        if color.isValid():
            grad = list(self.project.settings.background_gradient)
            grad[idx] = (color.red(), color.green(), color.blue())
            self.project.settings.background_gradient = tuple(grad)
            self.project.settings.background_type = 'gradient'
            self.bg_gradient_radio.setChecked(True)
            self.canvas.refresh_preview()

    def _set_gold_gradient(self):
        self.project.settings.background_gradient = ((255, 223, 100), (180, 130, 20))
        self.project.settings.background_type = 'gradient'
        self.project.settings.background_gradient_angle = 135.0
        self.bg_gradient_radio.setChecked(True)
        self.bg_grad_angle_spin.blockSignals(True)
        self.bg_grad_angle_spin.setValue(135)
        self.bg_grad_angle_spin.blockSignals(False)
        self.canvas.refresh_preview()

    def _update_gradient_angle(self, value: int):
        self.project.settings.background_gradient_angle = float(value)
        if self.project.settings.background_type == 'gradient':
            self.canvas.refresh_preview()

    # -------------------------------------------------------------------
    # Text cell handlers
    # -------------------------------------------------------------------

    def _apply_cell_text(self):
        if not self.project.selected_layout:
            return
        idx = self.canvas.selected_cell_index
        if idx < 0 or idx >= len(self.project.selected_layout.cells):
            return
        cell = self.project.selected_layout.cells[idx]
        cell.cell_text = self.cell_text_edit.text()
        cell.cell_text_size_pt = float(self.cell_text_size_spin.value())
        if cell.cell_text:
            cell.image_index = None  # text cell has no image
        self.canvas.refresh_preview()
        self._push_history()

    def _pick_cell_text_color(self):
        if not self.project.selected_layout:
            return
        idx = self.canvas.selected_cell_index
        if idx < 0 or idx >= len(self.project.selected_layout.cells):
            return
        cell = self.project.selected_layout.cells[idx]
        color = QColorDialog.getColor(QColor(*cell.cell_text_color), self)
        if color.isValid():
            cell.cell_text_color = (color.red(), color.green(), color.blue())
            self.canvas.refresh_preview()

    # -------------------------------------------------------------------
    # Element library handlers
    # -------------------------------------------------------------------

    def _set_elem_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Select elements folder')
        if folder:
            self._elem_folder = folder
            self._save_elem_state()
            self._reload_elem_library()

    def _reload_elem_library(self):
        self._ensure_elem_state()
        self.elem_list.clear()
        self._elem_library_paths = []
        self._elem_library_items = []
        tab = self._current_elem_tab()
        query = self.elem_search_edit.text().strip()

        if tab == 'Local':
            self._load_local_elements(query)
        elif tab == 'Emojis':
            self._load_openmoji_elements(query or 'happy')
        elif tab == 'Icons / Line Art':
            self._load_iconify_elements(
                query or 'heart',
                'feather,heroicons,phosphor,lucide,material-symbols',
                source='Iconify',
                monochrome=True,
            )
        elif tab == 'Hearts / Love':
            love_query = query or 'heart'
            self._load_local_elements(love_query, keywords=['heart', 'love', 'romance', 'couple', 'flower', 'star'])
            self._load_iconify_elements(
                love_query,
                'feather,heroicons,phosphor,lucide,material-symbols,openmoji',
                source='Hearts',
                monochrome=True,
            )
        elif tab == 'Frames':
            self._load_asset_folder('frames', query)
        elif tab == 'Backgrounds / Overlays':
            self._load_asset_folder('backgrounds', query)
        else:
            self._load_recent_and_favorites(query)

        if self.elem_list.count() == 0:
            item = QListWidgetItem('No items')
            item.setFlags(Qt.NoItemFlags)
            item.setTextAlignment(Qt.AlignCenter)
            self.elem_list.addItem(item)

    def _current_elem_tab(self) -> str:
        return self.elem_tabs.tabText(self.elem_tabs.currentIndex()) if hasattr(self, 'elem_tabs') else 'Local'

    def _ensure_elem_state(self):
        if self._elem_state_loaded:
            return
        self._elem_state_loaded = True
        self._elem_cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            raw = json.loads(ELEMENTS_STATE_PATH.read_text(encoding='utf-8'))
            self._elem_folder = str(raw.get('folder', self._elem_folder or ''))
            self._elem_recent = [str(p) for p in raw.get('recent', []) if p]
            self._elem_favorites = {str(p) for p in raw.get('favorites', []) if p}
        except Exception:
            pass

    def _save_elem_state(self):
        try:
            payload = {
                'folder': self._elem_folder,
                'recent': self._elem_recent[:40],
                'favorites': sorted(self._elem_favorites),
            }
            ELEMENTS_STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass

    def _elements_assets_dir(self, name: str) -> Path:
        return Path(__file__).resolve().parents[1] / 'assets' / 'elements' / name

    def _iter_element_files(self, folder: Path) -> List[Path]:
        exts = {'.svg', '.png', '.jpg', '.jpeg'}
        if not folder.exists():
            return []
        return sorted([f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in exts])

    def _matches_element_query(self, path: str, query: str, keywords: Optional[List[str]] = None) -> bool:
        haystack = f'{Path(path).stem} {Path(path).parent.name}'.lower()
        terms = [t for t in re.split(r'[\s,]+', query.lower()) if t]
        if keywords:
            terms.extend(keywords)
        return not terms or any(term in haystack for term in terms)

    def _load_local_elements(self, query: str = '', keywords: Optional[List[str]] = None):
        app_heart = Path(__file__).resolve().parents[1] / 'assets' / 'heart.svg'
        candidates: List[Path] = []
        if app_heart.exists():
            candidates.append(app_heart)
        if self._elem_folder:
            candidates.extend(self._iter_element_files(Path(self._elem_folder)))
        for path in candidates:
            if self._matches_element_query(str(path), query, keywords):
                self._add_element_item(str(path), Path(path).stem, source='Local')

    def _load_asset_folder(self, folder_name: str, query: str = ''):
        folder = self._elements_assets_dir(folder_name)
        folder.mkdir(parents=True, exist_ok=True)
        for path in self._iter_element_files(folder):
            if self._matches_element_query(str(path), query):
                self._add_element_item(str(path), Path(path).stem, source=folder_name.title())

    def _load_recent_and_favorites(self, query: str = ''):
        seen = set()
        for path in list(self._elem_favorites) + self._elem_recent:
            if path in seen or not Path(path).exists():
                continue
            seen.add(path)
            if self._matches_element_query(path, query):
                label = f'★ {Path(path).stem}' if path in self._elem_favorites else Path(path).stem
                self._add_element_item(path, label, source='Favorite' if path in self._elem_favorites else 'Recent')

    def _openmoji_dirs(self) -> Tuple[Path, Path, Path]:
        local_root = self._elements_assets_dir('openmoji')
        svg_dir = self._openmoji_cache_dir / 'color' / 'svg'
        index_path = self._openmoji_cache_dir / 'openmoji_index.json'
        return local_root, svg_dir, index_path

    def _load_openmoji_elements(self, query: str):
        self._ensure_openmoji_index()
        results = self._search_openmoji(query)
        visible_results = results[:80]
        paths_by_unicode = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_map = {
                executor.submit(self._ensure_openmoji_svg, item): item
                for item in visible_results
            }
            for future in concurrent.futures.as_completed(future_map):
                item = future_map[future]
                try:
                    path = future.result()
                except Exception:
                    path = None
                if path:
                    paths_by_unicode[item.get('unicode')] = path
        for item in visible_results:
            path = paths_by_unicode.get(item.get('unicode'))
            if path:
                self._add_element_item(path, item.get('name') or item.get('filename', ''), source='OpenMoji')

    def _ensure_openmoji_index(self):
        if self._openmoji_index_loaded:
            return
        self._openmoji_index_loaded = True
        local_root, svg_dir, index_path = self._openmoji_dirs()
        self._openmoji_cache_dir.mkdir(parents=True, exist_ok=True)
        svg_dir.mkdir(parents=True, exist_ok=True)

        local_svg_files = {
            f.name.upper(): f
            for root in (local_root / 'color' / 'svg', local_root)
            for f in self._iter_element_files(root)
            if f.suffix.lower() == '.svg'
        }
        local_count = len(local_svg_files)

        try:
            cached = json.loads(index_path.read_text(encoding='utf-8'))
            if cached.get('local_file_count') == local_count and cached.get('items'):
                self._openmoji_index = cached.get('items', [])
                if 'metadata_count' not in cached:
                    try:
                        cached['metadata_count'] = len(self._openmoji_index)
                        index_path.write_text(json.dumps(cached, ensure_ascii=False, indent=2), encoding='utf-8')
                    except Exception:
                        pass
                self._log_openmoji_index(
                    'loaded from cache',
                    local_count,
                    int(cached.get('metadata_count', len(self._openmoji_index))),
                    len(self._openmoji_index),
                )
                return
        except Exception:
            pass

        metadata = self._load_openmoji_metadata(local_root)
        items = []
        seen_filenames = set()
        for raw in metadata:
            unicode_value = str(raw.get('hexcode') or raw.get('unicode') or '').upper().strip()
            if not unicode_value:
                continue
            filename = f'{unicode_value}.svg'
            local_path = str(local_svg_files.get(filename.upper(), svg_dir / filename))
            tags = self._as_text_list(raw.get('tags')) + self._as_text_list(raw.get('openmoji_tags'))
            annotation = str(raw.get('annotation') or '')
            subgroups = self._as_text_list(raw.get('subgroups'))
            category = str(raw.get('group') or raw.get('category') or '')
            item = {
                'unicode': unicode_value,
                'filename': filename,
                'name': annotation or unicode_value,
                'category': category,
                'subgroups': subgroups,
                'subgroup': ' '.join(subgroups),
                'tags': tags,
                'keywords': sorted(set(tags + self._keywords_from_text(annotation))),
                'annotation': annotation,
                'local_path': local_path,
            }
            item['search_text'] = self._openmoji_search_text(item)
            items.append(item)
            seen_filenames.add(filename.upper())

        for filename, path in local_svg_files.items():
            if filename not in seen_filenames:
                name = path.stem.replace('-', ' ').replace('_', ' ')
                item = {
                    'unicode': path.stem.upper(),
                    'filename': path.name,
                    'name': name,
                    'category': 'Local',
                    'subgroups': ['local'],
                    'subgroup': 'local',
                    'tags': [],
                    'keywords': self._keywords_from_text(name),
                    'annotation': name,
                    'local_path': str(path),
                }
                item['search_text'] = self._openmoji_search_text(item)
                items.append(item)

        self._openmoji_index = items
        payload = {'local_file_count': local_count, 'metadata_count': len(metadata), 'items': items}
        try:
            index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass
        self._log_openmoji_index('rebuilt', local_count, len(metadata), len(items))

    def _load_openmoji_metadata(self, local_root: Path) -> List[dict]:
        candidates = [
            local_root / 'data' / 'openmoji.json',
            local_root / 'openmoji.json',
            self._openmoji_cache_dir / 'openmoji.json',
        ]
        for path in candidates:
            if path.exists():
                try:
                    raw = json.loads(path.read_text(encoding='utf-8'))
                    return raw if isinstance(raw, list) else raw.get('data', [])
                except Exception:
                    pass
        try:
            request = urllib.request.Request(
                OPENMOJI_DATA_URL,
                headers={'User-Agent': 'SmartCollageMaker/1.0'},
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                raw_text = response.read().decode('utf-8')
            cache_path = self._openmoji_cache_dir / 'openmoji.json'
            cache_path.write_text(raw_text, encoding='utf-8')
            raw = json.loads(raw_text)
            return raw if isinstance(raw, list) else raw.get('data', [])
        except Exception as exc:
            self.statusBar().showMessage(f'OpenMoji metadata unavailable: {exc}')
            return []

    def _log_openmoji_index(self, mode: str, file_count: int, metadata_count: int, item_count: int):
        categories = sorted({str(item.get('category', '')) for item in self._openmoji_index if item.get('category')})
        message = (
            f'OpenMoji index {mode}: files={file_count}, metadata={metadata_count}, '
            f'items={item_count}, categories={len(categories)}'
        )
        print(message)
        self.statusBar().showMessage(message)

    def _search_openmoji(self, query: str) -> List[dict]:
        terms = self._expand_emoji_query(query)
        if not terms:
            terms = self._expand_emoji_query('happy')

        ranked = []
        for item in self._openmoji_index:
            text = item.get('search_text', '')
            name = self._normalize_search_term(str(item.get('name', '')))
            exact_score = sum(8 for term in terms if f' {term} ' in text)
            prefix_score = sum(4 for term in terms if re.search(rf'\b{re.escape(term)}', text))
            partial_score = sum(1 for term in terms if len(term) > 3 and term in text)
            name_score = sum(14 for term in terms if f' {term} ' in f' {name} ')
            score = exact_score + prefix_score + partial_score + name_score
            if score:
                if query.lower().strip() and query.lower().strip() in name:
                    score += 12
                ranked.append((score, item))

        if not ranked:
            raw_terms = [t for t in re.split(r'[\s,]+', query.lower().strip()) if t]
            for item in self._openmoji_index:
                text = item.get('search_text', '')
                if any(term in text for term in raw_terms):
                    ranked.append((1, item))

        ranked.sort(key=lambda pair: (-pair[0], int(pair[1].get('unicode', '0').split('-')[0], 16) if pair[1].get('unicode') else 0))
        return [item for _score, item in ranked]

    def _expand_emoji_query(self, query: str) -> List[str]:
        q = query.lower().strip()
        terms: List[str] = []
        query_tokens = set(t for t in re.split(r'[\s,]+', q) if t)
        for key, values in EMOJI_SYNONYMS.items():
            key_norm = key.lower()
            if (' ' in key_norm and key_norm in q) or key_norm in query_tokens:
                terms.extend([key] + values)
        terms.extend([t for t in re.split(r'[\s,]+', q) if t])
        expanded = list(terms)
        for term in terms:
            expanded.extend(EMOJI_SYNONYMS.get(term, []))
        return sorted({self._normalize_search_term(t) for t in expanded if self._normalize_search_term(t)})

    def _ensure_openmoji_svg(self, item: dict) -> Optional[str]:
        path = Path(str(item.get('local_path') or ''))
        if path.exists():
            return str(path)
        filename = str(item.get('filename') or '')
        if not filename:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            request = urllib.request.Request(
                OPENMOJI_SVG_URL.format(filename=urllib.parse.quote(filename)),
                headers={'User-Agent': 'SmartCollageMaker/1.0'},
            )
            with urllib.request.urlopen(request, timeout=12) as response:
                svg = response.read().decode('utf-8')
            if '<svg' not in svg.lower():
                return None
            path.write_text(svg, encoding='utf-8')
            return str(path)
        except Exception:
            return None

    def _openmoji_search_text(self, item: dict) -> str:
        parts = [
            item.get('unicode', ''),
            item.get('filename', ''),
            item.get('name', ''),
            item.get('category', ''),
            item.get('subgroup', ''),
            item.get('annotation', ''),
        ]
        parts.extend(item.get('subgroups') or [])
        parts.extend(item.get('tags') or [])
        parts.extend(item.get('keywords') or [])
        normalized = ' '.join(self._normalize_search_term(str(part)) for part in parts if part)
        return f' {normalized} '

    def _normalize_search_term(self, value: str) -> str:
        return re.sub(r'\s+', ' ', value.lower().replace('_', ' ').replace('-', ' ')).strip()

    def _keywords_from_text(self, value: str) -> List[str]:
        return [t for t in re.split(r'[^A-Za-z0-9א-ת]+', value.lower()) if len(t) > 1]

    def _as_text_list(self, value) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value if str(v).strip()]
        if isinstance(value, str):
            return [v.strip() for v in re.split(r'[,;|]+', value) if v.strip()]
        return [str(value)]

    def _load_iconify_elements(self, query: str, prefixes: str, source: str, monochrome: bool):
        try:
            params = urllib.parse.urlencode({
                'query': query,
                'limit': 32,
                'prefixes': prefixes,
            })
            request = urllib.request.Request(
                f'https://api.iconify.design/search?{params}',
                headers={'User-Agent': 'SmartCollageMaker/1.0'},
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                data = json.loads(response.read().decode('utf-8'))
        except Exception as exc:
            self.statusBar().showMessage(f'{source} search unavailable: {exc}')
            return

        icon_ids = data.get('icons', [])[:32]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            future_map = {
                executor.submit(self._cached_iconify_svg, icon_id, monochrome): icon_id
                for icon_id in icon_ids
            }
            for future in concurrent.futures.as_completed(future_map):
                icon_id = future_map[future]
                try:
                    path = future.result()
                except Exception:
                    path = None
                if path:
                    self._add_element_item(path, icon_id.split(':', 1)[-1], source=source, icon_id=icon_id)

    def _cached_iconify_svg(self, icon_id: str, monochrome: bool = True) -> Optional[str]:
        safe_name = re.sub(r'[^A-Za-z0-9_.-]+', '_', icon_id)
        suffix = '_line' if monochrome else '_color'
        path = self._elem_cache_dir / f'{safe_name}{suffix}.svg'
        if path.exists():
            return str(path)
        try:
            prefix, name = icon_id.split(':', 1)
            url = f'https://api.iconify.design/{urllib.parse.quote(prefix)}/{urllib.parse.quote(name)}.svg'
            if monochrome:
                url += '?color=%23161616'
            request = urllib.request.Request(url, headers={'User-Agent': 'SmartCollageMaker/1.0'})
            with urllib.request.urlopen(request, timeout=8) as response:
                svg = response.read().decode('utf-8')
            if '<svg' not in svg.lower():
                return None
            path.write_text(svg, encoding='utf-8')
            return str(path)
        except Exception:
            return None

    def _add_element_item(self, path: str, title: str, source: str = '', icon_id: str = ''):
        self._elem_library_paths.append(path)
        self._elem_library_items.append({'path': path, 'title': title, 'source': source, 'icon_id': icon_id})
        label = title[:18]
        if path in self._elem_favorites and not label.startswith('★'):
            label = f'★ {label[:16]}'
        item = QListWidgetItem(label)
        thumb = self._element_thumbnail(path)
        if thumb:
            item.setIcon(QIcon(thumb))
        item.setToolTip(f'{source}: {icon_id or path}' if source else path)
        item.setTextAlignment(Qt.AlignCenter)
        self.elem_list.addItem(item)

    def _element_thumbnail(self, path: str) -> Optional[QPixmap]:
        try:
            suffix = path.rsplit('.', 1)[-1].lower()
            if suffix == 'svg':
                from PySide6.QtSvg import QSvgRenderer
                renderer = QSvgRenderer(path)
                pix = QPixmap(60, 60)
                pix.fill(QColor(245, 245, 245))
                p = QPainter(pix)
                renderer.render(p)
                p.end()
                return pix
            else:
                pix = QPixmap(path)
                if not pix.isNull():
                    return pix.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception:
            pass
        return None

    def _add_elem_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select element', '', 'Elements (*.svg *.png *.jpg *.jpeg)')
        if path:
            self._add_element_item(path, Path(path).stem, source='Manual')

    def _place_element(self):
        row = self.elem_list.currentRow()
        if row < 0 or row >= len(self._elem_library_paths):
            if self._elem_library_paths:
                row = 0
            else:
                QMessageBox.information(self, 'No element', 'Select an element from the library first.')
                return
        from app.models.project import ElementOverlay
        el = ElementOverlay(
            path=self._elem_library_paths[row],
            pos_x_frac=0.5,
            pos_y_frac=0.5,
            width_frac=self.elem_size_spin.value() / 100.0,
            opacity=self.elem_opacity_spin.value() / 100.0,
        )
        self.project.elements.append(el)
        self._remember_element_use(self._elem_library_paths[row])
        self.canvas.refresh_preview()
        self._push_history()
        self.statusBar().showMessage(f'Element placed: {Path(self._elem_library_paths[row]).name}')

    def _remember_element_use(self, path: str):
        self._ensure_elem_state()
        self._elem_recent = [p for p in self._elem_recent if p != path]
        self._elem_recent.insert(0, path)
        self._elem_recent = self._elem_recent[:40]
        self._save_elem_state()

    def _toggle_selected_element_favorite(self):
        self._ensure_elem_state()
        row = self.elem_list.currentRow()
        if row < 0 or row >= len(self._elem_library_paths):
            return
        path = self._elem_library_paths[row]
        if path in self._elem_favorites:
            self._elem_favorites.remove(path)
            self.statusBar().showMessage('Removed from favorites')
        else:
            self._elem_favorites.add(path)
            self.statusBar().showMessage('Added to favorites')
        self._save_elem_state()
        self._reload_elem_library()

    def _remove_selected_element(self):
        idx = self.canvas._selected_element
        if 0 <= idx < len(self.project.elements):
            self.project.elements.pop(idx)
            self.canvas._selected_element = -1
            self.canvas.refresh_preview()
            self._push_history()
            return True
        return False

    def _on_element_selected(self, idx: int):
        if 0 <= idx < len(self.project.elements):
            el = self.project.elements[idx]
            self.elem_size_spin.blockSignals(True)
            self.elem_size_spin.setValue(int(el.width_frac * 100))
            self.elem_size_spin.blockSignals(False)
            self.elem_opacity_spin.blockSignals(True)
            self.elem_opacity_spin.setValue(int(el.opacity * 100))
            self.elem_opacity_spin.blockSignals(False)

    def _update_selected_element(self):
        idx = self.canvas._selected_element
        if 0 <= idx < len(self.project.elements):
            el = self.project.elements[idx]
            el.width_frac = self.elem_size_spin.value() / 100.0
            el.opacity = self.elem_opacity_spin.value() / 100.0
            self.canvas.refresh_preview()

    # -------------------------------------------------------------------
    # Project save / load / new
    # -------------------------------------------------------------------

    def new_project(self):
        if self.project.images:
            ans = QMessageBox.question(
                self, 'New Project',
                'Discard current project and start fresh?',
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return
        self.project = ProjectState()
        self.image_list.clear()
        self.layout_list.clear()
        self.warnings_label.setText('')
        self.canvas.set_project(self.project)
        self.history = []
        self.history_index = -1
        self._push_history()
        self.statusBar().showMessage('New project started.')

    def save_project_as(self):
        if not self.project.images and not self.project.selected_layout:
            QMessageBox.information(self, 'Nothing to save', 'Add images first.')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save Project', '', 'Collage Project (*.colproj);;JSON (*.json)')
        if not path:
            return
        try:
            save_project(self.project, path)
            self.statusBar().showMessage(f'Project saved: {path}')
        except Exception as exc:
            QMessageBox.critical(self, 'Save failed', str(exc))

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Open Project', '', 'Collage Project (*.colproj);;JSON (*.json)')
        if not path:
            return
        try:
            project = load_project(path)
        except Exception as exc:
            QMessageBox.critical(self, 'Open failed', str(exc))
            return

        self._clear_external_image_watches()
        self.project = project
        self.history = []
        self.history_index = -1

        # Rebuild image list
        self.image_list.clear()
        for state in project.images:
            item = QListWidgetItem(Path(state.path).stem[:14])
            item.setToolTip(state.path)
            item.setIcon(self._make_thumb_icon(state.path))
            self.image_list.addItem(item)

        # Rebuild layout list
        self.layout_list.clear()
        canvas_px = project.settings.canvas_px
        for layout in project.suggestions:
            label = f'{layout.name}  {layout.score:.0%}' if layout.score > 0 else layout.name
            item = QListWidgetItem(label)
            item.setIcon(QIcon(self._layout_thumbnail(layout, canvas_px)))
            item.setTextAlignment(Qt.AlignCenter)
            self.layout_list.addItem(item)

        # Sync settings UI
        self.width_spin.blockSignals(True)
        self.height_spin.blockSignals(True)
        self.dpi_spin.blockSignals(True)
        self.margin_spin.blockSignals(True)
        self.spacing_spin.blockSignals(True)
        self.width_spin.setValue(project.settings.width_cm)
        self.height_spin.setValue(project.settings.height_cm)
        self.dpi_spin.setValue(project.settings.dpi)
        self.margin_spin.setValue(project.settings.margin_mm)
        self.spacing_spin.setValue(project.settings.spacing_mm)
        self.smart_crop_check.setChecked(project.settings.smart_crop_enabled)
        self.smart_crop_debug_check.setChecked(project.settings.smart_crop_debug)
        self.width_spin.blockSignals(False)
        self.height_spin.blockSignals(False)
        self.dpi_spin.blockSignals(False)
        self.margin_spin.blockSignals(False)
        self.spacing_spin.blockSignals(False)

        # Sync text overlay UI
        o = project.text_overlay
        self.text_edit.blockSignals(True)
        self.text_edit.setText(o.text)
        self.text_edit.blockSignals(False)
        self.text_size_spin.blockSignals(True)
        self.text_size_spin.setValue(o.font_size_pt)
        self.text_size_spin.blockSignals(False)

        # Select the saved layout in the list
        if project.selected_layout and project.selected_layout in project.suggestions:
            idx = project.suggestions.index(project.selected_layout)
            self.layout_list.blockSignals(True)
            self.layout_list.setCurrentRow(idx)
            self.layout_list.blockSignals(False)

        # Re-apply face-aware pan so that faces are correctly centred for the
        # loaded layout's actual cell dimensions (signals were blocked above, so
        # select_layout was never triggered, and the saved pan values may have
        # been computed for a different canvas size or with a (1,1) placeholder).
        if project.selected_layout:
            self._apply_face_pan_to_layout(project.selected_layout)

        self.canvas.set_project(project)
        self._push_history()
        self._check_quality_warnings()
        self.statusBar().showMessage(f'Opened: {path}')

    # -------------------------------------------------------------------
    # Export / Print
    # -------------------------------------------------------------------

    def export_file(self):
        if not self.project.selected_layout:
            QMessageBox.information(self, 'No layout', 'Generate a layout first.')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export collage', '',
            'JPEG (*.jpg);;PNG (*.png);;PDF (*.pdf)')
        if not path:
            return
        try:
            export_project(self.project, path)
            QMessageBox.information(self, 'Exported', f'Saved to:\n{path}')
        except Exception as exc:
            QMessageBox.critical(self, 'Export failed', str(exc))

    def open_print_preview(self):
        if not self.project.selected_layout:
            QMessageBox.information(self, 'No layout', 'Generate a layout first.')
            return

        page = CollagePreviewPage(copy.deepcopy(self.project))
        adapter = AppRenderAdapter([page])
        controller = PrintPreviewController(adapter, self)
        controller.settings.dpi = int(self.project.settings.dpi)
        controller.settings.bleed_mm = float(getattr(self.project.settings, 'bleed_mm', 0.0) or 0.0)
        controller.settings.safe_area_mm = float(getattr(self.project.settings, 'safe_area_mm', 0.0) or 0.0)
        controller.set_pages([page], index=0)
        controller.set_quality_warnings(self._print_preview_quality_warnings())

        window = PrintPreviewWindow(controller)
        window.destroyed.connect(lambda _=None, w=window: self._forget_print_preview_window(w))
        self._print_preview_windows.append(window)
        window.show()
        window.raise_()
        window.activateWindow()

    def _print_preview_quality_warnings(self) -> List[str]:
        label = getattr(self, 'warnings_label', None)
        if label is None:
            return []
        return [line.strip() for line in label.text().splitlines() if line.strip()]

    def _forget_print_preview_window(self, window: PrintPreviewWindow) -> None:
        try:
            self._print_preview_windows.remove(window)
        except ValueError:
            pass

    def print_collage(self):
        if not self.project.selected_layout:
            QMessageBox.information(self, 'No layout', 'Generate a layout first.')
            return
        from PySide6.QtGui import QPageLayout
        printer = QPrinter(QPrinter.HighResolution)
        is_landscape = self.project.settings.width_cm > self.project.settings.height_cm
        orientation = (QPageLayout.Orientation.Landscape if is_landscape
                       else QPageLayout.Orientation.Portrait)
        page_layout = printer.pageLayout()
        page_layout.setOrientation(orientation)
        printer.setPageLayout(page_layout)
        dlg = QPrintDialog(printer, self)
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return
        try:
            pil_img = render_project(self.project)
            qpix = pil_to_qpixmap(pil_img)
            p = QPainter(printer)
            rect = p.viewport()
            scaled = qpix.size().scaled(rect.size(), Qt.KeepAspectRatio)
            x = (rect.width() - scaled.width()) // 2
            y = (rect.height() - scaled.height()) // 2
            p.drawPixmap(x, y, qpix.scaled(scaled, Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation))
            p.end()
        except Exception as exc:
            QMessageBox.critical(self, 'Print failed', str(exc))

    # -------------------------------------------------------------------
    # Reset
    # -------------------------------------------------------------------

    def _cell_target_for_image(self, image_index: int) -> tuple:
        """Return the (w_px, h_px) of the cell currently showing this image, or (1,1)."""
        if self.project.selected_layout:
            for cell in self.project.selected_layout.cells:
                if cell.image_index == image_index:
                    return (max(1, int(round(cell.w))), max(1, int(round(cell.h))))
        return (1, 1)

    def _auto_pan(self, state: 'ImageState', target: tuple) -> Tuple[float, float]:
        """Return the best (pan_x, pan_y) for *state* in a cell of size *target*.

        ג€¢ If the image has detected face data ג†’ exact face-centred pan.
        ג€¢ Otherwise ג†’ portrait-in-landscape heuristic (upper-quarter bias).
        ג€¢ Fallback ג†’ (0.5, 0.5) centre.
        """
        natural = self._natural_size(state.path)
        if self.project.settings.smart_crop_enabled and getattr(state, 'analysis', None):
            pan_x, pan_y, zoom, _risks = optimize_crop(
                state.analysis, natural, target, (state.pan_x, state.pan_y), state.zoom)
            state.zoom = zoom
            return pan_x, pan_y
        if state.face_regions:
            return smart_pan_from_faces(state.face_regions, natural, target)
        # Heuristic: portrait image in a wide landscape cell
        img_w, img_h = natural
        img_ratio = img_w / max(1, img_h)
        cell_ratio = target[0] / max(1, target[1])
        if img_ratio < 0.85 and cell_ratio > 1.15:
            crop_h = int(round(img_w / cell_ratio))
            max_y = max(1, img_h - crop_h)
            desired_top = img_h * 0.25 - crop_h / 2.0
            pan_y = float(min(max(desired_top / max_y, 0.0), 1.0))
            return 0.5, pan_y
        return 0.5, 0.5

    def reset_selected_image(self):
        state = self._selected_state()
        if state is None:
            return
        # Find which cell this image is in so we can use its actual aspect ratio
        idx = self.canvas.selected_cell_index
        cell_img_idx = None
        if self.project.selected_layout and 0 <= idx < len(self.project.selected_layout.cells):
            cell_img_idx = self.project.selected_layout.cells[idx].image_index
        img_idx = cell_img_idx if cell_img_idx is not None else \
            next((i for i, s in enumerate(self.project.images) if s is state), None)
        target = self._cell_target_for_image(img_idx) if img_idx is not None else (1, 1)
        pan_x, pan_y = self._auto_pan(state, target)
        state.pan_x, state.pan_y, state.zoom = pan_x, pan_y, 1.0
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(100)
        self.zoom_slider.blockSignals(False)
        self.canvas.refresh_preview()
        self._push_history()

    def reset_all_images(self):
        for img_idx, state in enumerate(self.project.images):
            target = self._cell_target_for_image(img_idx)
            pan_x, pan_y = self._auto_pan(state, target)
            state.pan_x, state.pan_y, state.zoom = pan_x, pan_y, 1.0
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(100)
        self.zoom_slider.blockSignals(False)
        self.canvas.refresh_preview()
        self._push_history()

    # -------------------------------------------------------------------
    # Swap
    # -------------------------------------------------------------------

    def _on_swap_performed(self):
        self.swap_btn.blockSignals(True)
        self.swap_btn.setChecked(False)
        self.swap_btn.blockSignals(False)
        self._push_history()

    # -------------------------------------------------------------------
    # Language / i18n
    # -------------------------------------------------------------------

    def _switch_language(self, lang: str) -> None:
        """Switch UI language and re-apply RTL/LTR layout direction."""
        from PySide6.QtCore import Qt
        set_language(lang)
        app = QApplication.instance()
        if is_rtl():
            app.setLayoutDirection(Qt.RightToLeft)
        else:
            app.setLayoutDirection(Qt.LeftToRight)
        self.retranslate_ui()
        self._update_lang_checks()

    def _update_lang_checks(self) -> None:
        lang = current_language()
        for code, action in self._lang_action_group:
            action.setChecked(code == lang)

    def retranslate_ui(self) -> None:
        """Update all stored widget texts to the current language."""
        a = self._actions

        # Window title
        self.setWindowTitle(tr('Smart Collage Maker'))

        # Menus
        self._file_menu.setTitle(tr('&File'))
        self._edit_menu.setTitle(tr('&Edit'))
        self._view_menu.setTitle(tr('&View'))
        self._advanced_menu.setTitle(tr('&Advanced Collage'))
        self._shape_menu.setTitle(tr('Shaped Collage'))
        self._actions_menu.setTitle(tr('&Actions'))
        self._lang_menu.setTitle(tr('Language'))

        # File menu actions
        _ks = '  (Ctrl+N)'
        a['new'].setText(tr('&New Project') + _ks)
        a['open'].setText(tr('&Open Projectג€¦') + '  (Ctrl+O)')
        a['save'].setText(tr('&Save Projectג€¦') + '  (Ctrl+Shift+S)')
        a['import'].setText(tr('&Import Imagesג€¦') + '  (Ctrl+I)')
        a['template'].setText(tr('&Template Creatorג€¦'))
        a['export'].setText(tr('&Exportג€¦') + '  (Ctrl+S)')
        a['print'].setText(tr('Print Previewג€¦') + '  (Ctrl+P)')
        a['quit'].setText(tr('&Quit') + '  (Ctrl+Q)')

        # Edit menu actions
        a['undo'].setText(tr('&Undo') + '  (Ctrl+Z)')
        a['redo'].setText(tr('&Redo') + '  (Ctrl+Y)')
        a['gen'].setText(tr('&Generate Layouts'))
        a['soft_fade'].setText(tr('Soft Fade Transition…'))
        a['swap'].setText(tr('&Swap Mode') + '  (Tab)')
        a['remove'].setText(tr('&Remove Selected Element/Image') + '  (Delete)')
        a['reset_all'].setText(tr('Reset &All Images'))

        # View menu actions
        a['shortcuts'].setText(tr('Keyboard &Shortcutsג€¦'))
        a['zoom_in'].setText(tr('Zoom &In') + '  (Ctrl+=)')
        a['zoom_out'].setText(tr('Zoom &Out') + '  (Ctrl+-)')
        a['fit'].setText(tr('&Fit to Screen') + '  (Ctrl+0)')
        a['custom_grid'].setText(tr('Custom Grid…'))
        a['shape_circle'].setText(tr('Circle'))
        a['shape_heart'].setText(tr('Heart'))
        a['dynamic_layout'].setText(tr('Dynamic Layout'))
        a['smart_arrange'].setText(tr('סידור חכם'))
        a['refresh_images'].setText(tr('רענן תמונות'))
        a['scan_selected'].setText(tr('Scan selected photos'))
        a['scan_all'].setText(tr('Scan all photos'))

        # Section titles
        for key, sec in self._sections.items():
            sec.set_title(tr(key))

        # Form labels
        for label_widget, key in self._form_labels:
            label_widget.setText(tr(key))

        # Right panel group boxes
        if hasattr(self, '_images_group'):
            self._images_group.setTitle(tr('Images'))
        if hasattr(self, '_layouts_group'):
            self._layouts_group.setTitle(tr('Layout Suggestions'))

        # Buttons that are stored as self.xxx
        _btn_map = [
            ('import_btn',           'Importג€¦'),
            ('remove_btn',           'Remove'),
            ('reset_all_btn',        'Reset all'),
            ('generate_btn',         'ג³  Generate layouts'),
            ('scan_selected_btn',    'Scan selected photos'),
            ('scan_all_btn',         'Scan all photos'),
            ('export_btn',           'ג¬‡  Exportג€¦'),
            ('print_btn',            'נ–¨  Print Preview'),
            ('refresh_images_btn',   'רענן תמונות'),
            ('swap_btn',             'ג‡„  Swap mode'),
            ('undo_btn',             'ג†©  Undo'),
            ('redo_btn',             'ג†×  Redo'),
            ('bg_btn',               'Solid colourג€¦'),
            ('save_preset_btn',      'Save as preset'),
            ('zero_spacing_btn',     'Set margin & spacing to 0'),
            ('bg_solid_radio',       'Solid'),
            ('bg_gradient_radio',    'Gradient'),
            ('bg_image_radio',       'Imageג€¦'),
            ('bg_grad_c1_btn',       'Colour 1'),
            ('bg_grad_c2_btn',       'Colour 2'),
            ('bg_grad_gold_btn',     'ג¦ Gold'),
            ('border_color_btn',     'Border colourג€¦'),
            ('shadow_check',         'Drop shadow'),
            ('text_color_btn',       'Text colourג€¦'),
            ('stroke_color_btn',     'Stroke colourג€¦'),
            ('text_center_btn',      'ג• Centre on canvas'),
            ('text_apply_btn',       'ג Apply ג€” add to canvas'),
            ('bold_check',           'Bold'),
            ('italic_check',         'Italic'),
            ('text_bg_check',         'Background box'),
            ('text_shadow_check',    'Shadow'),
            ('custom_grid_apply_btn','Apply custom grid'),
            ('shape_circle_btn',     'ג—¯  Circle'),
            ('shape_heart_btn',      'ג™¡  Heart'),
            ('dyn_create_btn',       'ג  Create Dynamic Layout'),
            ('elem_folder_btn',      'נ“‚ Set folder'),
            ('elem_add_btn',         '+ Add file'),
            ('elem_search_btn',      'Search'),
            ('elem_place_btn',       'ג–¶ Place on canvas'),
            ('elem_remove_btn',      'ג• Remove'),
            ('rotate_cw_btn',        'ג†» 90ֲ°'),
            ('rotate_ccw_btn',       'ג†÷ 90ֲ°'),
            ('reset_btn',            'Reset image'),
            ('cell_text_color_btn',  'Text colourג€¦'),
            ('cell_text_apply_btn',  'Apply text to cell'),
            ('bw_check',             'Black & White'),
            ('reset_adj_btn',        'Reset adjustments'),
            ('clahe_check',          'CLAHE contrast'),
        ]
        for attr, key in _btn_map:
            w = getattr(self, attr, None)
            if w is not None:
                w.setText(tr(key))

        # Floating panels
        if hasattr(self, 'image_panel'):
            self.image_panel.retranslate()
        if hasattr(self, 'text_panel'):
            self.text_panel.retranslate()

        # Info labels
        if hasattr(self, '_shape_info_label'):
            self._shape_info_label.setText(
                tr('Generates a shaped layout and adds it to Layout Suggestions.'))
        if hasattr(self, '_dyn_info_label'):
            self._dyn_info_label.setText(
                tr('Creates a fully resizable split-panel layout. '
                   'Drag the white dividers to resize cells interactively.'))

        # Placeholders
        if hasattr(self, 'text_edit'):
            self.text_edit.setPlaceholderText(
                tr('Captionג€¦ (double-click on canvas to edit)'))
        if hasattr(self, 'cell_text_edit'):
            self.cell_text_edit.setPlaceholderText(tr('Text for this cellג€¦'))

    def _analysis_tooltip(self, path: str, state: ImageState) -> str:
        analysis = getattr(state, 'analysis', None)
        lines = [path]
        if analysis:
            lines.append('Advanced scan ready')
            lines.append(f'Faces detected: {len(analysis.faces)}')
            lines.append(f'People detected: {len(analysis.persons)}')
            lines.append(f'Image type: {analysis.image_type}')
            lines.append(f'Crop tolerance: {analysis.crop_tolerance}')
            backend = analysis.detector_versions.get('face_backend', 'auto')
            lines.append(f'Face backend: {backend}')
        else:
            lines.append('Quick placement only')
            lines.append('Use Scan photos for people-aware placement and crop warnings.')
        return '\n'.join(lines)

    def _refresh_image_analysis(
        self,
        state: ImageState,
        force: bool = False,
        face_backend: Optional[str] = None,
    ) -> None:
        analysis = getattr(state, 'analysis', None)
        backend = face_backend or self.project.settings.advanced_face_backend
        needs_refresh = force or analysis is None or state.analysis_status != 'scanned'
        if analysis is not None and not needs_refresh:
            detector_versions = getattr(analysis, 'detector_versions', {})
            cache_key = getattr(analysis, 'cache_key', '')
            expected_cache_key = ''
            try:
                from app.core.smart_crop_service import _image_cache_key
                expected_cache_key = _image_cache_key(state.path, state.rotation)
            except Exception:
                expected_cache_key = cache_key
            if cache_key and expected_cache_key and cache_key != expected_cache_key:
                needs_refresh = True
            elif detector_versions.get('face_backend') != backend:
                needs_refresh = True
        if not needs_refresh:
            return
        new_analysis = analyze_image(state.path, rotation=state.rotation, face_backend=backend)
        new_analysis.detector_versions['opencv_face_fallback'] = 'available'
        new_analysis.detector_versions['opencv_people_fallback'] = 'available'
        state.analysis = new_analysis
        state.face_regions = analysis_to_face_regions(new_analysis)
        state.analysis_status = 'scanned'

    def _refresh_all_analysis(
        self,
        force: bool = False,
        indices: Optional[List[int]] = None,
        face_backend: Optional[str] = None,
    ) -> None:
        target_indices = indices if indices is not None else list(range(len(self.project.images)))
        for idx in target_indices:
            if 0 <= idx < len(self.project.images):
                self._refresh_image_analysis(self.project.images[idx], force=force, face_backend=face_backend)

    def _toggle_smart_crop_debug(self, enabled: bool) -> None:
        self.smart_crop_debug_check.blockSignals(True)
        self.smart_crop_debug_check.setChecked(enabled)
        self.smart_crop_debug_check.blockSignals(False)
        self.project.settings.smart_crop_debug = enabled
        self.canvas.refresh_preview()

    # -------------------------------------------------------------------
    # Quality warnings
    # -------------------------------------------------------------------

    def _check_quality_warnings(self):
        if not self.project.selected_layout:
            self.warnings_label.setText('')
            # Clear all tooltips
            for i in range(len(self.project.images)):
                item = self.image_list.item(i)
                if item:
                    item.setToolTip('')
            return
        settings = self.project.settings
        warnings: List[str] = []

        # Per-image tooltip messages and badge tracking
        image_tooltips: Dict[int, List[str]] = {}
        low_res_indices:  set = set()
        face_warn_indices: set = set()

        for cell in self.project.selected_layout.cells:
            if cell.image_index is None or cell.image_index >= len(self.project.images):
                continue
            state = self.project.images[cell.image_index]
            cw    = max(1, int(round(cell.w)))
            ch    = max(1, int(round(cell.h)))
            name  = Path(state.path).name
            idx   = cell.image_index
            analysis = getattr(state, 'analysis', None)

            # ג”€ג”€ Low-resolution check ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€
            if not image_resolution_ok(state.path, (cw, ch), settings.dpi):
                low_res_indices.add(idx)
                msg = f'ג  Low resolution ג€” may appear blurry when printed'
                warnings.append(f'ג  Low res: {name}')
                image_tooltips.setdefault(idx, []).append(msg)

            # ג”€ג”€ Face crop evaluation (checks only the VISIBLE cell area) ג”€ג”€
            if state.face_regions:
                crop_eval = evaluate_crop_for_state(state, cw, ch)
                sev = crop_eval.worst_severity
                if sev == 'critical':
                    face_warn_indices.add(idx)
                    face_msg = crop_eval.summary_message or 'Main face is cut off in this cell'
                    warnings.append(f'נ« Face cut: {name}')
                    image_tooltips.setdefault(idx, []).append(f'נ« {face_msg}')
                elif sev == 'strong':
                    face_warn_indices.add(idx)
                    face_msg = crop_eval.summary_message or 'Face partially cut off'
                    warnings.append(f'ג  Face cut: {name}')
                    image_tooltips.setdefault(idx, []).append(f'ג  {face_msg}')
                elif sev == 'mild':
                    face_warn_indices.add(idx)
                    face_msg = crop_eval.summary_message or 'Face close to edge'
                    warnings.append(f'ג„¹ Face near edge: {name}')
                    image_tooltips.setdefault(idx, []).append(f'ג„¹ {face_msg}')

        # ג”€ג”€ Update thumbnail badges and tooltips ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€ג”€
            if self.project.settings.smart_crop_enabled and analysis:
                crop_box = crop_box_from_pan(
                    self._natural_size(state.path), (cw, ch), state.pan_x, state.pan_y, state.zoom)
                for risk in evaluate_crop_risks(analysis, crop_box):
                    face_warn_indices.add(idx)
                    warnings.append(f'׳’ֲֲ  {risk.message}: {name}')
                    image_tooltips.setdefault(idx, []).append(f'׳’ֲֲ  {risk.message}')
                    if risk.suggestion:
                        image_tooltips.setdefault(idx, []).append(risk.suggestion)

        badge_indices = low_res_indices | face_warn_indices
        for img_idx, state in enumerate(self.project.images):
            item = self.image_list.item(img_idx)
            if item:
                item.setIcon(
                    self._make_thumb_icon(
                        state.path,
                        warn=(img_idx in badge_indices),
                        analyzed=(getattr(state, 'analysis', None) is not None),
                    )
                )
                tips = image_tooltips.get(img_idx, [])
                info_tip = self._analysis_tooltip(state.path, state)
                item.setToolTip('\n'.join([info_tip] + tips) if tips else info_tip)

        self.warnings_label.setText('\n'.join(warnings))

    # -------------------------------------------------------------------
    # Undo / Redo
    # -------------------------------------------------------------------

    def _snapshot(self):
        return copy.deepcopy(self.project)

    def _restore_snapshot(self, snap):
        self.project = copy.deepcopy(snap)
        self.canvas._selected_element = -1
        self.canvas.set_project(self.project)
        self._sync_ui_from_project()
        self.canvas.refresh_preview()

    def _sync_ui_from_project(self):
        project = self.project

        self.image_list.clear()
        for state in project.images:
            item = QListWidgetItem(Path(state.path).stem[:18])
            item.setToolTip(self._analysis_tooltip(state.path, state))
            item.setIcon(self._make_thumb_icon(
                state.path,
                analyzed=(getattr(state, 'analysis', None) is not None),
            ))
            self.image_list.addItem(item)

        self.layout_list.clear()
        canvas_px = project.settings.canvas_px
        for layout in project.suggestions:
            label = f'{layout.name}  {layout.score:.0%}' if layout.score > 0 else layout.name
            item = QListWidgetItem(label)
            item.setIcon(QIcon(self._layout_thumbnail(layout, canvas_px)))
            item.setTextAlignment(Qt.AlignCenter)
            self.layout_list.addItem(item)

        if project.selected_layout and project.selected_layout in project.suggestions:
            idx = project.suggestions.index(project.selected_layout)
            self.layout_list.blockSignals(True)
            self.layout_list.setCurrentRow(idx)
            self.layout_list.blockSignals(False)

        s = project.settings
        for spin, value in (
            (self.width_spin, s.width_cm),
            (self.height_spin, s.height_cm),
            (self.dpi_spin, s.dpi),
            (self.margin_spin, s.margin_mm),
            (self.spacing_spin, s.spacing_mm),
        ):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self.smart_crop_check.blockSignals(True)
        self.smart_crop_check.setChecked(s.smart_crop_enabled)
        self.smart_crop_check.blockSignals(False)
        self.smart_crop_debug_check.blockSignals(True)
        self.smart_crop_debug_check.setChecked(s.smart_crop_debug)
        self.smart_crop_debug_check.blockSignals(False)

        overlay = project.text_overlay
        self.text_edit.blockSignals(True)
        self.text_edit.setText(overlay.text)
        self.text_edit.blockSignals(False)
        self.text_size_spin.blockSignals(True)
        self.text_size_spin.setValue(overlay.font_size_pt)
        self.text_size_spin.blockSignals(False)

        self._check_quality_warnings()

    def _push_history(self):
        if self._history_suspended:
            return
        snap = self._snapshot()
        if self.history_index < len(self.history) - 1:
            self.history = self.history[: self.history_index + 1]
        self.history.append(snap)
        self.history_index = len(self.history) - 1

    class _HistorySuspend:
        def __init__(self, owner):
            self.owner = owner

        def __enter__(self):
            self.owner._history_suspended += 1
            return self

        def __exit__(self, exc_type, exc, tb):
            self.owner._history_suspended = max(0, self.owner._history_suspended - 1)
            return False

    def _suspend_history(self):
        return self._HistorySuspend(self)

    def undo(self):
        if self.history_index <= 0:
            return
        self.history_index -= 1
        self._restore_snapshot(self.history[self.history_index])

    def redo(self):
        if self.history_index >= len(self.history) - 1:
            return
        self.history_index += 1
        self._restore_snapshot(self.history[self.history_index])
