from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from smart_image_editor.ai.face_detection_service import detect_faces, has_mediapipe_face_detection
from smart_image_editor.ai.segmentation_service import has_mediapipe_segmentation
from smart_image_editor.ai.smart_auto_fix_service import suggest_smart_auto_fix
from smart_image_editor.ai_tools.ai_tools_service import (
    clear_ai_tools_cache,
    default_ai_tools_params,
    generate_effect_preview,
)
from smart_image_editor.core.adjustment_pipeline import apply_adjustments, create_preview, load_image
from smart_image_editor.core.cache_manager import PreviewCache
from smart_image_editor.core.dynamic_hsl import (
    DYNAMIC_HSL_COLORS,
    create_dynamic_hsl_isolation_overlay,
    default_dynamic_hsl,
)
from smart_image_editor.core.export_service import export_image
from smart_image_editor.core.histogram import calculate_histogram, suggest_auto_contrast, suggest_auto_levels
from smart_image_editor.core.hsl_preview_overlay import clear_hsl_preview_cache, create_hsl_affected_overlay
from smart_image_editor.core.image_state import DEFAULT_PARAMS, ImageState
from smart_image_editor.core.presets import PresetService, blend_preset_params
from smart_image_editor.core.target_color import (
    clear_target_color_cache,
    create_target_color_isolation_overlay,
    default_target_color,
    sample_target_color,
    update_target_color_params,
)
from smart_image_editor.ui.adjustment_panel import AdjustmentPanel
from smart_image_editor.ui.ai_tools_panel import AiToolsPanel
from smart_image_editor.ui.history_panel import HistoryPanel
from smart_image_editor.ui.histogram_widget import HistogramWidget
from smart_image_editor.ui.i18n import LANG_EN, LANG_HE, Translator, translate_widget_tree
from smart_image_editor.ui.preview_canvas import PreviewCanvas
from smart_image_editor.ui.smart_tips_panel import SmartTipsPanel
from smart_image_editor.ui.theme import APP_QSS


SUPPORTED_OPEN_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
    ".heic",
    ".heif",
    ".dng",
    ".cr2",
    ".cr3",
    ".nef",
    ".arw",
    ".orf",
    ".raf",
    ".rw2",
}


SECTION_KEYS = {
    "Quick Fixes": ["exposure", "brightness", "contrast"],
    "Tone": ["highlights", "shadows", "whites", "blacks", "gamma"],
    "Basic Color": ["temperature", "tint", "saturation", "vibrance", "black_white"],
    "HSL": ["hsl"],
    "Dynamic HSL": ["dynamic_hsl"],
    "LUT": ["lut_path", "lut_amount"],
    "Target Color": ["target_color"],
    "Upscale": ["ai_upscale_factor", "ai_upscale_strength"],
    "Detail": ["sharpness", "noise_reduction", "color_noise_reduction", "texture", "clarity"],
    "Blur": [
        "gaussian_blur",
        "motion_blur",
        "motion_angle",
        "radial_blur",
        "ai_background_blur",
        "ai_background_darkening",
    ],
    "Finish": [
        "vignette_amount",
        "vignette_feather",
        "vignette_midpoint",
        "grain_amount",
        "grain_size",
    ],
    "Face": ["ai_face_brighten", "ai_face_restore", "ai_skin_tone_protection", "print_reduce_red_skin"],
    "Subject": ["ai_subject_enhance"],
    "Print Setup": ["print_mode", "print_boost_shadows", "print_protect_highlights", "print_safe_sharpness"],
    "AI Tools": ["ai_tools"],
}


COMPARE_MODES = [
    ("edited", "Edited"),
    ("before", "Before"),
    ("split", "Split"),
    ("side_by_side", "Side by Side"),
]


class EditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.translator = Translator()
        self.setWindowTitle("Smart Image Editor / Color Lab")
        self.resize(1480, 900)
        self.state = ImageState()
        self.original_image = None
        self.preview_base = None
        self.preset_service = PresetService()
        self.presets = self.preset_service.load_presets()
        self.preview_cache = PreviewCache(max_items=24)
        self.target_pick_mode: str | None = None
        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._apply_language()
        self._sync_ui_state()
        self._refresh_history_panel()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        top = QHBoxLayout()
        self.title_label = QLabel("Smart Image Editor")
        title = self.title_label
        title.setObjectName("TitleLabel")
        self.subtitle_label = QLabel("Color Lab | Print Safe | Embeddable Engine")
        subtitle = self.subtitle_label
        subtitle.setObjectName("SubtitleLabel")
        top.addWidget(title)
        top.addWidget(subtitle)
        top.addStretch()

        self.open_btn = QPushButton("Open")
        self.open_btn.clicked.connect(self.open_image)
        self.save_btn = QPushButton("Save Copy")
        self.save_btn.clicked.connect(self.save_copy)
        self.quick_save_btn = QPushButton("Quick Save")
        self.quick_save_btn.clicked.connect(self.quick_save_copy)
        self.undo_btn = QPushButton("Undo")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn = QPushButton("Redo")
        self.redo_btn.clicked.connect(self.redo)
        self.reset_btn = QPushButton("Reset All")
        self.reset_btn.clicked.connect(self.reset_all)
        for button in [self.open_btn, self.save_btn, self.quick_save_btn, self.undo_btn, self.redo_btn, self.reset_btn]:
            top.addWidget(button)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())
        self.preview = PreviewCanvas()
        self.preview.image_clicked.connect(self.handle_preview_click)
        splitter.addWidget(self.preview)
        self.adjustments = AdjustmentPanel()
        self.adjustments.param_changed.connect(self.update_param)
        self.adjustments.reset_param_requested.connect(self.reset_param)
        self.adjustments.reset_section_requested.connect(self.reset_section)
        self.adjustments.auto_enhance_requested.connect(self.auto_enhance)
        self.adjustments.auto_levels_requested.connect(self.auto_levels)
        self.adjustments.auto_contrast_requested.connect(self.auto_contrast)
        self.adjustments.smart_auto_fix_requested.connect(self.smart_auto_fix)
        self.adjustments.detect_faces_requested.connect(self.detect_faces)
        self.adjustments.hsl_preview_requested.connect(self.show_hsl_affected_preview)
        self.adjustments.hsl_preview_hide_requested.connect(self.hide_hsl_affected_preview)
        self.adjustments.dynamic_hsl_preview_requested.connect(self.show_dynamic_hsl_preview)
        self.adjustments.target_color_pick_requested.connect(self.start_target_color_pick)
        self.adjustments.target_color_preview_requested.connect(self.show_target_color_preview)
        self.ai_tools_panel = AiToolsPanel()
        self.ai_tools_panel.param_changed.connect(self.update_param)
        self.ai_tools_panel.effect_apply_requested.connect(self._on_ai_tools_effect_apply)
        self.ai_tools_panel.effect_clear_requested.connect(self._on_ai_tools_effect_clear)
        self.ai_tools_panel.effect_preview_requested.connect(self.show_ai_tools_preview)
        self.ai_tools_panel.effect_preview_clear_requested.connect(self.hide_hsl_affected_preview)

        self.adjustments.set_ai_tools_panel(self.ai_tools_panel)

        splitter.addWidget(self.adjustments)
        splitter.setSizes([330, 780, 370])
        layout.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        self.compare_mode = QComboBox()
        for mode, label in COMPARE_MODES:
            self.compare_mode.addItem(label, mode)
        self.compare_mode.currentIndexChanged.connect(self._on_compare_mode_changed)
        self.view_label = QLabel("View")
        bottom.addWidget(self.view_label)
        bottom.addWidget(self.compare_mode)
        self.zoom_label = QLabel("Mouse wheel: zoom")
        bottom.addWidget(self.zoom_label)
        bottom.addStretch()
        self.status_label = QLabel("No image loaded")
        bottom.addWidget(self.status_label)
        self.ai_status_label = QLabel(self._ai_status_text())
        bottom.addWidget(self.ai_status_label)
        layout.addLayout(bottom)

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        self.left_tabs = QTabWidget()
        tabs = self.left_tabs
        layout.addWidget(tabs)

        preset_tab = QWidget()
        preset_layout = QVBoxLayout(preset_tab)
        preset_layout.addWidget(QLabel("Presets"))
        self.preset_list = QListWidget()
        for preset in self.presets:
            self.preset_list.addItem(f"{preset.get('name')}  ({preset.get('category', 'General')})")
        self.preset_list.itemDoubleClicked.connect(self._apply_selected_preset)
        self.preset_list.currentRowChanged.connect(self._preview_preset_name)
        preset_layout.addWidget(QLabel("Preset Intensity"))
        self.preset_intensity = QSlider(Qt.Horizontal)
        self.preset_intensity.setRange(0, 100)
        self.preset_intensity.setValue(100)
        preset_layout.addWidget(self.preset_intensity)
        apply_btn = QPushButton("Apply Preset")
        apply_btn.clicked.connect(self._apply_selected_preset)
        preset_layout.addWidget(self.preset_list, 1)
        preset_layout.addWidget(apply_btn)
        tabs.addTab(preset_tab, "Presets")

        info_tab = QWidget()
        info_layout = QVBoxLayout(info_tab)
        self.histogram = HistogramWidget()
        self.clip_label = QLabel("Clipping: -")
        info_layout.addWidget(self.histogram)
        info_layout.addWidget(self.clip_label)
        info_layout.addStretch()
        tabs.addTab(info_tab, "Histogram")

        self.tips_panel = SmartTipsPanel()
        self.tips_panel.apply_fix_requested.connect(self.apply_tip_params)
        tabs.addTab(self.tips_panel, "Tips")

        self.history_panel = HistoryPanel()
        self.history_panel.undo_requested.connect(self.undo)
        self.history_panel.redo_requested.connect(self.redo)
        self.history_panel.reset_all_requested.connect(self.reset_all)
        self.history_panel.adjustment_enabled_changed.connect(self.set_adjustment_enabled)
        self.history_panel.adjustment_reset_requested.connect(self.reset_param)
        self.history_panel.adjustment_delete_requested.connect(self.delete_adjustment)
        self.history_panel.adjustment_focus_requested.connect(self.focus_adjustment)
        self.history_panel.adjustment_hovered.connect(self.focus_adjustment)
        tabs.addTab(self.history_panel, "History")
        return panel

    def _build_menu(self):
        self.menuBar().clear()
        file_menu = self.menuBar().addMenu(self.tr_ui("File"))
        open_action = file_menu.addAction(self.tr_ui("Open"), self.open_image)
        open_action.setShortcut(QKeySequence.Open)
        save_action = file_menu.addAction(self.tr_ui("Save Copy"), self.save_copy)
        save_action.setShortcut(QKeySequence.Save)
        quick_save_action = file_menu.addAction(self.tr_ui("Quick Save Copy"), self.quick_save_copy)
        quick_save_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        file_menu.addSeparator()
        file_menu.addAction(self.tr_ui("Exit"), self.close)

        edit_menu = self.menuBar().addMenu(self.tr_ui("Edit"))
        undo_action = edit_menu.addAction(self.tr_ui("Undo"), self.undo)
        undo_action.setShortcut(QKeySequence.Undo)
        redo_action = edit_menu.addAction(self.tr_ui("Redo"), self.redo)
        redo_action.setShortcut(QKeySequence.Redo)
        reset_action = edit_menu.addAction(self.tr_ui("Reset All"), self.reset_all)
        reset_action.setShortcut(QKeySequence("Ctrl+0"))

        view_menu = self.menuBar().addMenu(self.tr_ui("View"))
        view_menu.addAction(self.tr_ui("Edited"), lambda: self._set_compare_mode("edited")).setShortcut(QKeySequence("1"))
        view_menu.addAction(self.tr_ui("Before"), lambda: self._set_compare_mode("before")).setShortcut(QKeySequence("2"))
        view_menu.addAction(self.tr_ui("Split"), lambda: self._set_compare_mode("split")).setShortcut(QKeySequence("3"))
        view_menu.addAction(self.tr_ui("Side by Side"), lambda: self._set_compare_mode("side_by_side")).setShortcut(QKeySequence("4"))
        view_menu.addSeparator()
        language_menu = view_menu.addMenu(self.tr_ui("Language"))
        language_group = QActionGroup(self)
        language_group.setExclusive(True)
        english_action = QAction(self.tr_ui("English"), self, checkable=True)
        english_action.setChecked(self.translator.language == LANG_EN)
        english_action.triggered.connect(lambda: self.set_language(LANG_EN))
        hebrew_action = QAction(self.tr_ui("Hebrew"), self, checkable=True)
        hebrew_action.setChecked(self.translator.language == LANG_HE)
        hebrew_action.triggered.connect(lambda: self.set_language(LANG_HE))
        language_group.addAction(english_action)
        language_group.addAction(hebrew_action)
        language_menu.addAction(english_action)
        language_menu.addAction(hebrew_action)

        tips_menu = self.menuBar().addMenu(self.tr_ui("Tips / Improve Photo"))
        tips_menu.addAction(self.tr_ui("Open Tips Panel"), self.focus_tips_panel).setShortcut(QKeySequence("Ctrl+T"))

        ai_menu = self.menuBar().addMenu(self.tr_ui("AI Tools"))
        ai_menu.addAction(self.tr_ui("Smart Auto Fix"), self.smart_auto_fix).setShortcut(QKeySequence("Ctrl+Alt+A"))
        ai_menu.addAction(self.tr_ui("Detect Faces"), self.detect_faces).setShortcut(QKeySequence("Ctrl+Alt+F"))
        ai_menu.addAction(self.tr_ui("Import LUT"), self.import_lut).setShortcut(QKeySequence("Ctrl+Alt+L"))
        ai_menu.addSeparator()
        open_ai_panel = ai_menu.addAction(self.tr_ui("Toggle AI Tools Panel"), self.toggle_ai_tools_panel)
        open_ai_panel.setShortcut(QKeySequence("Ctrl+Alt+T"))
        open_ai_panel.setCheckable(True)
        ai_menu.addSeparator()
        ai_menu.addAction(self.tr_ui("Cartoon"), lambda: self._apply_ai_effect_from_menu("cartoon"))
        ai_menu.addAction(self.tr_ui("Sketch"), lambda: self._apply_ai_effect_from_menu("sketch"))
        ai_menu.addAction(self.tr_ui("Coloring Page"), lambda: self._apply_ai_effect_from_menu("coloring_page"))
        ai_menu.addAction(self.tr_ui("Posterize"), lambda: self._apply_ai_effect_from_menu("posterize"))
        ai_menu.addSeparator()
        ai_menu.addAction(self.tr_ui("Anime Style (AI)"), lambda: self._apply_ai_effect_from_menu("anime"))
        ai_menu.addAction(self.tr_ui("Clear AI Effect"), self._on_ai_tools_effect_clear)

        preset_menu = self.menuBar().addMenu(self.tr_ui("Presets"))
        for preset in self.presets:
            action = QAction(preset["name"], self)
            action.triggered.connect(lambda checked=False, p=preset: self.apply_preset(p))
            preset_menu.addAction(action)

    def _build_shortcuts(self):
        QShortcut(QKeySequence.Open, self, self.open_image)
        QShortcut(QKeySequence.Save, self, self.save_copy)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, self.quick_save_copy)
        QShortcut(QKeySequence.Undo, self, self.undo)
        QShortcut(QKeySequence.Redo, self, self.redo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self.redo)
        QShortcut(QKeySequence("Ctrl+0"), self, self.reset_all)
        QShortcut(QKeySequence("Space"), self, self.show_before_while_pressed)
        QShortcut(QKeySequence("Esc"), self, lambda: self._set_compare_mode("edited"))
        QShortcut(QKeySequence("1"), self, lambda: self._set_compare_mode("edited"))
        QShortcut(QKeySequence("2"), self, lambda: self._set_compare_mode("before"))
        QShortcut(QKeySequence("3"), self, lambda: self._set_compare_mode("split"))
        QShortcut(QKeySequence("4"), self, lambda: self._set_compare_mode("side_by_side"))
        QShortcut(QKeySequence("Ctrl+T"), self, self.focus_tips_panel)
        QShortcut(QKeySequence("Ctrl+Alt+A"), self, self.smart_auto_fix)
        QShortcut(QKeySequence("Ctrl+Alt+F"), self, self.detect_faces)
        QShortcut(QKeySequence("Ctrl+Alt+T"), self, self.toggle_ai_tools_panel)
        QShortcut(QKeySequence("Ctrl+Alt+L"), self, self.import_lut)

    def tr_ui(self, source: str) -> str:
        return self.translator.text(source)

    def set_language(self, language: str) -> None:
        self.translator.set_language(language)
        self._apply_language()

    def _apply_language(self) -> None:
        self.setWindowTitle(self.tr_ui("Smart Image Editor / Color Lab"))
        self.setLayoutDirection(Qt.RightToLeft if self.translator.is_rtl else Qt.LeftToRight)
        self._refresh_compare_mode_labels()
        self._refresh_left_tab_labels()
        translate_widget_tree(self, self.translator)
        if hasattr(self, "adjustments"):
            self.adjustments.retranslate(self.translator)
        self._build_menu()
        self._refresh_history_panel()
        if hasattr(self, "tips_panel"):
            self.tips_panel.refresh_language(self.translator)
        if hasattr(self, "history_panel"):
            self.history_panel.refresh_language(self.translator)

    def _refresh_compare_mode_labels(self) -> None:
        if not hasattr(self, "compare_mode"):
            return
        current = self.compare_mode.currentData() or "edited"
        self.compare_mode.blockSignals(True)
        self.compare_mode.clear()
        for mode, label in COMPARE_MODES:
            self.compare_mode.addItem(self.tr_ui(label), mode)
        self.compare_mode.blockSignals(False)
        self._set_compare_mode(current)

    def _refresh_left_tab_labels(self) -> None:
        if not hasattr(self, "left_tabs"):
            return
        for index, label in enumerate(["Presets", "Histogram", "Tips", "History"]):
            self.left_tabs.setTabText(index, self.tr_ui(label))

    def _set_compare_mode(self, mode: str) -> None:
        if not hasattr(self, "compare_mode"):
            return
        index = self.compare_mode.findData(mode)
        if index >= 0:
            self.compare_mode.setCurrentIndex(index)

    def _on_compare_mode_changed(self, _index: int) -> None:
        mode = self.compare_mode.currentData() or "edited"
        self.preview.set_before_after_mode(mode)

    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr_ui("Open image"),
            "",
            "Images (*.jpg *.jpeg *.png *.tif *.tiff *.webp *.heic *.heif *.dng *.cr2 *.cr3 *.nef *.arw *.orf *.raf *.rw2)",
        )
        if not path:
            return
        self.open_image_path(path)

    def open_image_path(self, path: str | Path):
        path = Path(path)
        if not path.exists():
            QMessageBox.warning(self, self.tr_ui("Image not found"), f"{self.tr_ui('Could not find')}:\n{path}")
            return
        try:
            self.original_image = load_image(str(path))
        except Exception as exc:
            QMessageBox.critical(self, self.tr_ui("Open failed"), str(exc))
            return
        self.state.set_source(path, self.original_image.size)
        self.preview_base = create_preview(self.original_image)
        self.preview_cache.clear()
        clear_hsl_preview_cache()
        clear_target_color_cache()
        clear_ai_tools_cache()
        self.hide_hsl_affected_preview()
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)

    def update_param(self, key: str, value):
        if self.original_image is None:
            return
        if key == "hsl" and isinstance(value, dict):
            hsl = dict(self.state.edit_params.get("hsl") or {})
            color_values = dict(hsl.get(value["color"], {}))
            color_values[value["channel"]] = value["value"]
            hsl[value["color"]] = color_values
            value = hsl
        elif key == "dynamic_hsl" and isinstance(value, dict) and "color" in value:
            current = self.state.edit_params.get("dynamic_hsl") or {}
            dhsl = {c: dict(current.get(c) or {}) for c in DYNAMIC_HSL_COLORS}
            dhsl[value["color"]][value["channel"]] = value["value"]
            value = dhsl
        elif key == "ai_tools" and isinstance(value, dict):
            # AiToolsPanel emits the full dict — store it directly
            pass
        elif key == "target_color" and isinstance(value, dict):
            target = default_target_color()
            target.update(self.state.edit_params.get("target_color") or {})
            target[value["channel"]] = value["value"]
            if target.get("samples"):
                target["enabled"] = True
            value = target
        self.state.update_param(key, value)
        self.refresh_preview()

    def reset_param(self, key: str):
        if self.original_image is None:
            return
        if key.startswith("hsl."):
            _, color, channel = key.split(".", 2)
            hsl = dict(self.state.edit_params.get("hsl") or {})
            color_values = dict(hsl.get(color, {}))
            color_values[channel] = 0
            hsl[color] = color_values
            self.state.update_param("hsl", hsl)
            self.refresh_preview()
            self.adjustments.sync_from_params(self.state.edit_params)
            return
        if key.startswith("dhsl."):
            _, color, channel = key.split(".", 2)
            _defaults = {"hue_shift": 0, "saturation": 0, "luminance": 0, "range_width": 35, "softness": 25}
            current = self.state.edit_params.get("dynamic_hsl") or {}
            dhsl = {c: dict(current.get(c) or {}) for c in DYNAMIC_HSL_COLORS}
            dhsl[color][channel] = _defaults.get(channel, 0)
            self.state.update_param("dynamic_hsl", dhsl)
            self.refresh_preview()
            self.adjustments.sync_from_params(self.state.edit_params)
            return
        if key.startswith("target."):
            _, channel = key.split(".", 1)
            target = default_target_color()
            target.update(self.state.edit_params.get("target_color") or {})
            target[channel] = default_target_color().get(channel)
            self.state.update_param("target_color", target)
            self.refresh_preview()
            self.adjustments.sync_from_params(self.state.edit_params)
            return
        self.state.reset_param(key)
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)

    def set_adjustment_enabled(self, key: str, enabled: bool):
        if self.original_image is None:
            return
        self.state.set_adjustment_enabled(key, enabled)
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)

    def import_lut(self):
        if self.original_image is None:
            QMessageBox.information(self, self.tr_ui("No image"), self.tr_ui("Open an image before importing a LUT."))
            return
        path, _ = QFileDialog.getOpenFileName(self, self.tr_ui("Import LUT"), "", "Cube LUT (*.cube)")
        if not path:
            return
        self.state.apply_params({"lut_path": path, "lut_amount": 100}, "LUT Import")
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)
        self.adjustments.highlight_control("lut")

    def delete_adjustment(self, key: str):
        if self.original_image is None:
            return
        self.state.remove_adjustment(key)
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)

    def focus_adjustment(self, key: str):
        self.adjustments.highlight_control(key)

    def reset_section(self, section: str):
        if self.original_image is None:
            return
        params = {key: DEFAULT_PARAMS[key] for key in SECTION_KEYS.get(section, []) if key in DEFAULT_PARAMS}
        self.state.apply_params(params)
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)

    def apply_preset(self, preset: dict):
        if self.original_image is None:
            QMessageBox.information(self, self.tr_ui("No image"), self.tr_ui("Open an image before applying a preset."))
            return
        intensity = self.preset_intensity.value() if hasattr(self, "preset_intensity") else 100
        params = blend_preset_params(DEFAULT_PARAMS, preset.get("params", {}), intensity)
        self.state.apply_params(params, f"{preset.get('name')} ({intensity}%)")
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)

    def apply_tip_params(self, params: dict):
        if self.original_image is None:
            QMessageBox.information(self, self.tr_ui("No image"), self.tr_ui("Open an image before applying a suggested fix."))
            return
        self.state.apply_params(params, "Smart Tip")
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)
        first_control = self._first_tip_control(params)
        if first_control:
            self.adjustments.highlight_control(first_control)

    def auto_enhance(self):
        if self.preview_base is None:
            return
        params = {"exposure": 0.12, "contrast": 8, "vibrance": 12, "sharpness": 8}
        params.update(suggest_auto_levels(self.preview_base))
        self.state.apply_params(params, "Auto Enhance")
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)

    def auto_levels(self):
        if self.preview_base is None:
            return
        self.state.apply_params(suggest_auto_levels(self.preview_base), "Auto Levels")
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)

    def auto_contrast(self):
        if self.preview_base is None:
            return
        self.state.apply_params(suggest_auto_contrast(self.preview_base), "Auto Contrast")
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)

    def smart_auto_fix(self):
        if self.preview_base is None:
            return
        params = suggest_smart_auto_fix(self.preview_base)
        self.state.apply_params(params, "Smart Auto Fix")
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)

    def detect_faces(self):
        if self.preview_base is None:
            return
        faces = detect_faces(self.preview_base)
        self.status_label.setText(f"{self.tr_ui('AI detected')} {len(faces)} {self.tr_ui('face(s)')}")

    def refresh_preview(self):
        if self.preview_base is None:
            return
        self.hide_hsl_affected_preview()
        key = self.preview_cache.make_key(self.state.source_path, self.state.edit_params, self.preview_base.size)
        image = self.preview_cache.get(key)
        if image is None:
            image = apply_adjustments(self.preview_base, self.state.edit_params)
            self.preview_cache.put(key, image)
        self.preview.set_image(image, self.preview_base)
        stats = calculate_histogram(image)
        self.histogram.set_histogram(stats)
        self.clip_label.setText(
            f"{self.tr_ui('Clipping')}: {self.tr_ui('shadows')} {stats.shadow_clip_percent:.2f}% | "
            f"{self.tr_ui('highlights')} {stats.highlight_clip_percent:.2f}%"
        )
        preset = self.state.active_preset or self.tr_ui("Custom")
        size = self.state.original_size or ("-", "-")
        self.status_label.setText(f"{preset} | {size[0]} x {size[1]} | {self.state.source_path}")
        self.ai_status_label.setText(self._ai_status_text())
        self._sync_ui_state()
        self._refresh_history_panel()
        self.ai_tools_panel.sync_from_params(self.state.edit_params)

    def show_hsl_affected_preview(self, color_name: str):
        if self.preview.current_image is None:
            return
        overlay = create_hsl_affected_overlay(self.preview.current_image, color_name)
        self.preview.set_overlay_image(overlay, f"{self.tr_ui('Previewing affected color')}: {self.tr_ui(color_name.capitalize())}")

    def show_dynamic_hsl_preview(self, color_name: str):
        if self.preview.current_image is None:
            return
        dhsl_params = self.state.edit_params.get("dynamic_hsl") or {}
        overlay = create_dynamic_hsl_isolation_overlay(self.preview.current_image, color_name, dhsl_params)
        self.preview.set_overlay_image(overlay, f"{self.tr_ui('Dynamic HSL')}: {self.tr_ui(color_name.capitalize())}")

    def show_target_color_preview(self):
        if self.preview.current_image is None:
            return
        target = self.state.edit_params.get("target_color") or {}
        if not target.get("samples"):
            return
        overlay = create_target_color_isolation_overlay(self.preview.current_image, target)
        self.preview.set_overlay_image(overlay, self.tr_ui("Previewing targeted color range"))

    def hide_hsl_affected_preview(self):
        if hasattr(self, "preview"):
            self.preview.clear_overlay()

    # ── AI Tools panel methods ────────────────────────────────────────────────

    def toggle_ai_tools_panel(self) -> None:
        self.adjustments.toggle_ai_tools()

    def show_ai_tools_preview(self, effect_id: str) -> None:
        """Show a hover-preview overlay for *effect_id* at full strength."""
        if self.preview.current_image is None or effect_id == "":
            return
        from smart_image_editor.ai_tools.ai_tools_service import EFFECT_REGISTRY
        ai_params = self.state.edit_params.get("ai_tools") or default_ai_tools_params()
        try:
            overlay = generate_effect_preview(self.preview.current_image, effect_id, ai_params)
        except RuntimeError as exc:
            self.status_label.setText(str(exc))
            return
        label = EFFECT_REGISTRY[effect_id].label if effect_id in EFFECT_REGISTRY else effect_id
        self.preview.set_overlay_image(overlay, f"Preview: {label}")

    def _on_ai_tools_effect_apply(self, effect_id: str) -> None:
        """Commit the active effect to edit_params and refresh."""
        if self.original_image is None:
            return
        current = dict(self.state.edit_params.get("ai_tools") or default_ai_tools_params())
        current["active_effect"] = effect_id
        self.state.update_param("ai_tools", current)
        self.refresh_preview()

    def _on_ai_tools_effect_clear(self) -> None:
        if self.original_image is None:
            return
        current = dict(self.state.edit_params.get("ai_tools") or default_ai_tools_params())
        current["active_effect"] = ""
        self.state.update_param("ai_tools", current)
        self.refresh_preview()

    def _apply_ai_effect_from_menu(self, effect_id: str) -> None:
        """Convenience: select an effect directly from the menu bar."""
        if self.original_image is None:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, self.tr_ui("No image"), self.tr_ui("Open an image before applying an effect."))
            return
        current = dict(self.state.edit_params.get("ai_tools") or default_ai_tools_params())
        current["active_effect"] = effect_id
        self.state.update_param("ai_tools", current)
        self.refresh_preview()
        self.adjustments.open_ai_tools()

    # ── Target color (existing) ───────────────────────────────────────────────

    def start_target_color_pick(self, mode: str):
        if self.preview.current_image is None:
            return
        self.target_pick_mode = mode
        self.setCursor(QCursor(Qt.CrossCursor))
        self.status_label.setText(self.tr_ui("Pick a target color from the preview"))

    def handle_preview_click(self, x: int, y: int):
        if not self.target_pick_mode or self.preview.current_image is None:
            return
        sample = sample_target_color(self.preview.current_image, x, y)
        current = self.state.edit_params.get("target_color") or default_target_color()
        if self.target_pick_mode == "replace":
            current = default_target_color()
            mode = "include"
        else:
            mode = self.target_pick_mode
        target = update_target_color_params(current, sample, mode=mode)
        self.target_pick_mode = None
        self.unsetCursor()
        self.state.update_param("target_color", target)
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)
        self.adjustments.highlight_control("target_color")
        self.show_target_color_preview()

    def reset_all(self):
        if self.original_image is None:
            return
        self.state.reset_all_adjustments()
        self.preview_cache.clear()
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)
        self._refresh_history_panel()

    def undo(self):
        self.state.undo()
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)
        self._refresh_history_panel()

    def redo(self):
        self.state.redo()
        self.refresh_preview()
        self.adjustments.sync_from_params(self.state.edit_params)

    def show_before_while_pressed(self):
        if self.original_image is None:
            return
        self._set_compare_mode("before" if self.compare_mode.currentData() != "before" else "edited")

    def focus_tips_panel(self):
        self.tips_panel.setFocus()
        self.status_label.setText(self.tr_ui("Tips panel focused"))

    def dragEnterEvent(self, event):
        if self._event_has_image_file(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._event_has_image_file(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in SUPPORTED_OPEN_SUFFIXES:
                self.open_image_path(path)
                event.acceptProposedAction()
                return
        event.ignore()

    def _event_has_image_file(self, event) -> bool:
        if not event.mimeData().hasUrls():
            return False
        return any(
            Path(url.toLocalFile()).suffix.lower() in SUPPORTED_OPEN_SUFFIXES
            for url in event.mimeData().urls()
        )

    def save_copy(self):
        if self.original_image is None:
            QMessageBox.information(self, self.tr_ui("No image"), self.tr_ui("No image to save."))
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr_ui("Save copy"),
            str(self._default_save_copy_path()),
            "JPEG (*.jpg);;PNG (*.png);;TIFF (*.tif);;WEBP (*.webp)",
        )
        if not path:
            return
        self._export_copy(Path(path), show_message=True)

    def quick_save_copy(self):
        if self.original_image is None:
            QMessageBox.information(self, self.tr_ui("No image"), self.tr_ui("No image to save."))
            return
        self._export_copy(self._next_available_save_copy_path(), show_message=True)

    def _export_copy(self, path: Path, *, show_message: bool):
        try:
            exported = export_image(self.original_image, self.state.edit_params, path)
        except Exception as exc:
            QMessageBox.critical(self, self.tr_ui("Export failed"), str(exc))
            return
        self.state.last_export_path = exported
        if show_message:
            QMessageBox.information(self, self.tr_ui("Saved"), f"{self.tr_ui('Saved successfully')}:\n{exported}")

    def _default_save_copy_path(self) -> Path:
        source = self.state.source_path
        if not source:
            return Path("edited_image+.jpg")
        suffix = source.suffix if source.suffix.lower() in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"} else ".jpg"
        return source.with_name(f"{source.stem}+{suffix}")

    def _next_available_save_copy_path(self) -> Path:
        base = self._default_save_copy_path()
        if not base.exists():
            return base
        for index in range(2, 1000):
            candidate = base.with_name(f"{base.stem}{index}{base.suffix}")
            if not candidate.exists():
                return candidate
        return base

    def _apply_selected_preset(self, *_args):
        row = self.preset_list.currentRow()
        if 0 <= row < len(self.presets):
            self.apply_preset(self.presets[row])

    def _preview_preset_name(self, row: int):
        if 0 <= row < len(self.presets):
            self.status_label.setText(f"{self.tr_ui('Preset selected')}: {self.presets[row].get('name')}")

    def _sync_ui_state(self):
        has_image = self.original_image is not None
        self.save_btn.setEnabled(has_image)
        self.quick_save_btn.setEnabled(has_image)
        self.undo_btn.setEnabled(has_image and self.state.can_undo())
        self.redo_btn.setEnabled(has_image and self.state.can_redo())
        self.reset_btn.setEnabled(has_image)

    def _refresh_history_panel(self):
        if not hasattr(self, "history_panel"):
            return
        self.history_panel.refresh(
            self.state.active_adjustments(),
            self.state.timeline_entries(),
            self.state.can_undo(),
            self.state.can_redo(),
        )

    def _ai_status_text(self) -> str:
        face = f"{self.tr_ui('Face')}: MediaPipe" if has_mediapipe_face_detection() else f"{self.tr_ui('Face')}: OpenCV"
        segment = f"{self.tr_ui('Segment')}: MediaPipe" if has_mediapipe_segmentation() else f"{self.tr_ui('Segment')}: {self.tr_ui('fallback')}"
        return f"{face} | {segment}"

    def _first_tip_control(self, params: dict) -> str | None:
        priority = [
            "vibrance",
            "saturation",
            "temperature",
            "tint",
            "exposure",
            "shadows",
            "highlights",
            "contrast",
            "ai_face_brighten",
            "ai_face_restore",
            "ai_background_blur",
            "ai_upscale_factor",
            "lut_amount",
            "print_reduce_red_skin",
            "print_mode",
        ]
        for key in priority:
            if key in params:
                return key
        hsl = params.get("hsl")
        if isinstance(hsl, dict):
            for color, values in hsl.items():
                if isinstance(values, dict):
                    for channel in values:
                        return f"hsl.{color}.{channel}"
        return next(iter(params), None) if params else None


def run_app():
    app = QApplication([])
    app.setStyleSheet(APP_QSS)
    window = EditorWindow()
    window.show()
    app.exec()
