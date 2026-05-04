from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Signal, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from smart_image_editor.core.dynamic_hsl import DYNAMIC_HSL_COLORS
from smart_image_editor.core.image_state import DEFAULT_PARAMS
from smart_image_editor.ui.i18n import Translator, translate_widget_tree


PRINT_MODES = [
    "None",
    "General Print Safe",
    "Canvas Print Boost",
    "Sublimation Boost",
    "Glossy Photo Paper",
    "Matte Photo Paper",
    "Mitsubishi D80 Correction",
]

HSL_COLORS = ["red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta"]

_DHSL_CHIP_COLORS = {
    "red": "#e05555",
    "orange": "#e08040",
    "yellow": "#c8b820",
    "green": "#50b860",
    "aqua": "#40c0c0",
    "blue": "#4080d0",
    "purple": "#9060c0",
    "magenta": "#c050a0",
}

_DHSL_CHANNEL_DEFAULTS = {
    "hue_shift": 0,
    "saturation": 0,
    "luminance": 0,
    "range_width": 35,
    "softness": 25,
}

CATEGORY_COLORS = {
    "Quick": "#9b7cff",
    "Light": "#ffcf5c",
    "Color": "#69f0d5",
    "Portrait": "#ff6b9d",
    "Effects": "#7aa7ff",
    "Print": "#ff9f5c",
    "Advanced": "#aeb3c7",
}

_AI_TOOLS_COLOR = "#e87a3e"


@dataclass(frozen=True)
class CategorySpec:
    name: str
    icon: str
    description: str


CATEGORIES = [
    CategorySpec("Quick", "🪄", "Fast fixes, recent tools and one-click corrections."),
    CategorySpec("Light", "💡", "Shape exposure, shadow detail and tonal depth."),
    CategorySpec("Color", "🎨", "Adjust color temperature, saturation and HSL channels."),
    CategorySpec("Portrait", "👤", "Face, skin and subject-aware AI controls."),
    CategorySpec("Effects", "✨", "Blur, vignette, grain and visual focus tools."),
    CategorySpec("Print", "🖨️", "Print-safe corrections and output compensation."),
    CategorySpec("Advanced", "⚙️", "Detail, noise reduction and deeper controls."),
]


class SliderRow(QFrame):
    changed = Signal(str, int)
    reset_requested = Signal(str)
    hovered = Signal(str)
    unhovered = Signal(str)
    slider_pressed = Signal(str)

    def __init__(self, key: str, title: str, min_value: int, max_value: int, default: int = 0):
        super().__init__()
        self.key = key
        self.title = title
        self.default = default
        self.setObjectName("SliderRow")
        self.value_label = QLabel(str(default))
        self.value_label.setObjectName("SliderValue")
        title_label = QLabel(title)
        title_label.setObjectName("SliderTitle")
        reset_btn = QPushButton("Reset")
        reset_btn.setObjectName("MiniButton")
        reset_btn.clicked.connect(lambda: self.reset_requested.emit(self.key))
        self.slider = QSlider(Qt.Horizontal)
        self.setToolTip("Shows which parts of the image this color slider affects." if key.startswith("hsl.") else "")
        self.slider.setRange(min_value, max_value)
        self.slider.setValue(default)
        self.slider.valueChanged.connect(self._on_change)
        self.slider.sliderPressed.connect(lambda: self.slider_pressed.emit(self.key))
        self.slider.sliderReleased.connect(self._sync_label)
        self.slider.mouseDoubleClickEvent = self._double_click_reset

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(title_label)
        top.addStretch()
        top.addWidget(self.value_label)
        top.addWidget(reset_btn)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.addLayout(top)
        layout.addWidget(self.slider)

    def set_value(self, value: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(int(value))
        self.slider.blockSignals(False)
        self.value_label.setText(str(int(value)))

    def set_highlighted(self, highlighted: bool, color: str = "#69f0d5") -> None:
        self.setProperty("highlighted", highlighted)
        self.setStyleSheet(
            f"QFrame#SliderRow {{ border: 1px solid {color}; background: rgba(255,255,255,0.07); border-radius: 8px; }}"
            if highlighted
            else ""
        )

    def _on_change(self, value: int):
        self.value_label.setText(str(value))
        self.changed.emit(self.key, value)

    def _sync_label(self):
        self.value_label.setText(str(self.slider.value()))

    def _double_click_reset(self, event):
        self.reset_requested.emit(self.key)

    def enterEvent(self, event):
        self.hovered.emit(self.key)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.unhovered.emit(self.key)
        super().leaveEvent(event)


class CollapsibleSection(QFrame):
    opened = Signal(str)

    def __init__(self, title: str, color: str):
        super().__init__()
        self.title = title
        self.color = color
        self.translator = Translator()
        self.setObjectName("ToolSection")
        self.toggle = QToolButton()
        self.toggle.setObjectName("SectionToggle")
        self.toggle.setText(f"▶ {title}")
        self.toggle.setCheckable(True)
        self.toggle.setText(f"▶ {title}")
        self.toggle.clicked.connect(self._toggle_clicked)

        self.content = QWidget()
        self.content.setObjectName("SectionContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 6, 0, 4)
        self.content_layout.setSpacing(8)
        self.content.setMaximumHeight(0)
        self.content.setVisible(False)

        self.animation = QPropertyAnimation(self.content, b"maximumHeight", self)
        self.animation.setDuration(150)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toggle)
        layout.addWidget(self.content)

    def addWidget(self, widget: QWidget) -> None:
        self.content_layout.addWidget(widget)

    def set_open(self, open_: bool, animated: bool = True) -> None:
        self.toggle.blockSignals(True)
        self.toggle.setChecked(open_)
        self.toggle.blockSignals(False)
        self.toggle.setText(f"▼ {self.title}" if open_ else f"▶ {self.title}")
        self.toggle.setText(f"{'▼' if open_ else '▶'} {self.translator.text(self.title)}")
        self.toggle.setStyleSheet(
            f"QToolButton#SectionToggle {{ color: {self.color}; border-left: 3px solid {self.color}; }}"
            if open_
            else ""
        )
        target = self.content_layout.sizeHint().height() + 12 if open_ else 0
        self.content.setVisible(True)
        if animated:
            self.animation.stop()
            self.animation.setStartValue(self.content.maximumHeight())
            self.animation.setEndValue(target)
            self.animation.finished.connect(lambda: self.content.setVisible(open_))
            self.animation.start()
        else:
            self.content.setMaximumHeight(target)
            self.content.setVisible(open_)

    def _toggle_clicked(self):
        self.opened.emit(self.title)

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator
        self.toggle.setText(f"{'▼' if self.toggle.isChecked() else '▶'} {self.translator.text(self.title)}")


class CategoryPage(QWidget):
    def __init__(self, spec: CategorySpec):
        super().__init__()
        self.spec = spec
        self.color = CATEGORY_COLORS[spec.name]
        self.sections: dict[str, CollapsibleSection] = {}
        self.open_section: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QFrame()
        header.setObjectName("ToolPageHeader")
        header_layout = QVBoxLayout(header)
        title = QLabel(f"{spec.icon} {spec.name}")
        title.setObjectName("ToolPageTitle")
        description = QLabel(spec.description)
        description.setObjectName("ToolPageDescription")
        description.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(description)
        layout.addWidget(header)

        self.action_row = QHBoxLayout()
        self.action_row.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.action_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("ToolScroll")
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(8)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)

    def add_action(self, label: str, callback) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("MiniButton")
        button.clicked.connect(callback)
        self.action_row.addWidget(button)
        return button

    def add_section(self, title: str) -> CollapsibleSection:
        section = CollapsibleSection(title, self.color)
        section.opened.connect(self.open_only)
        self.sections[title] = section
        self.content_layout.addWidget(section)
        if self.open_section is None:
            self.open_section = title
            section.set_open(True, animated=False)
        return section

    def finish(self) -> None:
        self.action_row.addStretch()
        self.content_layout.addStretch()

    def open_only(self, title: str) -> None:
        self.open_section = title
        for name, section in self.sections.items():
            section.set_open(name == title)


class AdjustmentPanel(QFrame):
    param_changed = Signal(str, object)
    reset_param_requested = Signal(str)
    reset_section_requested = Signal(str)
    auto_levels_requested = Signal()
    auto_contrast_requested = Signal()
    auto_enhance_requested = Signal()
    smart_auto_fix_requested = Signal()
    detect_faces_requested = Signal()
    hsl_preview_requested = Signal(str)
    hsl_preview_hide_requested = Signal()
    dynamic_hsl_preview_requested = Signal(str)
    target_color_pick_requested = Signal(str)
    target_color_preview_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("Panel")
        self.rows: dict[str, SliderRow] = {}
        self.checkboxes: dict[str, QCheckBox] = {}
        self.control_locations: dict[str, tuple[str, str]] = {}
        self.recent_controls: list[str] = []
        self.highlighted_control: str | None = None
        self.category_buttons: dict[str, QToolButton] = {}
        self.pages: dict[str, CategoryPage] = {}
        self.translator = Translator()
        self.dhsl_advanced_rows: list[SliderRow] = []
        self._dhsl_section: CollapsibleSection | None = None
        self._ai_tools_page: QWidget | None = None
        self.ai_tools_btn: QToolButton | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)
        outer.addLayout(self._build_nav())

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self._build_pages()
        self.open_category("Quick")

    def retranslate(self, translator: Translator) -> None:
        self.translator = translator
        for page in self.pages.values():
            for section in page.sections.values():
                section.set_translator(translator)
        translate_widget_tree(self, translator)
        self._refresh_recent()

    def open_category(self, name: str) -> None:
        if name not in self.pages:
            return
        page = self.pages[name]
        self.stack.setCurrentWidget(page)
        color = CATEGORY_COLORS[name]
        for category, button in self.category_buttons.items():
            active = category == name
            button.setChecked(active)
            button.setStyleSheet(self._category_button_style(CATEGORY_COLORS[category], active))
        if self.ai_tools_btn is not None:
            self.ai_tools_btn.setChecked(False)
            self.ai_tools_btn.setStyleSheet(self._category_button_style(_AI_TOOLS_COLOR, False))
        self._fade_current_page()
        self._refresh_recent()

    def set_ai_tools_panel(self, panel: QWidget) -> None:
        self._ai_tools_page = panel
        self.stack.addWidget(panel)

    def open_ai_tools(self) -> None:
        if self._ai_tools_page is None:
            return
        self.stack.setCurrentWidget(self._ai_tools_page)
        for category, button in self.category_buttons.items():
            button.setChecked(False)
            button.setStyleSheet(self._category_button_style(CATEGORY_COLORS[category], False))
        if self.ai_tools_btn is not None:
            self.ai_tools_btn.setChecked(True)
            self.ai_tools_btn.setStyleSheet(self._category_button_style(_AI_TOOLS_COLOR, True))

    def toggle_ai_tools(self) -> None:
        if self._ai_tools_page is not None and self.stack.currentWidget() is self._ai_tools_page:
            self.open_category("Quick")
        else:
            self.open_ai_tools()

    def highlight_control(self, control_name: str) -> None:
        key = self._normalize_control_name(control_name)
        if key == "hsl":
            self.open_category("Color")
            self.pages["Color"].open_only("HSL")
            return
        if key == "dynamic_hsl":
            self.open_category("Color")
            self.pages["Color"].open_only("Dynamic HSL")
            return
        if key not in self.rows and key not in self.checkboxes and key != "print_mode":
            return
        location = self.control_locations.get(key)
        if location:
            category, section = location
            self.open_category(category)
            self.pages[category].open_only(section)
        self._clear_highlight()
        color = CATEGORY_COLORS.get(location[0], "#69f0d5") if location else "#69f0d5"
        target = self.rows.get(key) or self.checkboxes.get(key)
        if target:
            if isinstance(target, SliderRow):
                target.set_highlighted(True, color)
            else:
                target.setStyleSheet(f"QCheckBox {{ color: {color}; font-weight: 700; }}")
            self.highlighted_control = key

    def sync_from_params(self, params: dict) -> None:
        for key, row in self.rows.items():
            if key.startswith("hsl."):
                _, color, channel = key.split(".", 2)
                value = (params.get("hsl") or {}).get(color, {}).get(channel, 0)
            elif key.startswith("dhsl."):
                _, color, channel = key.split(".", 2)
                value = (params.get("dynamic_hsl") or {}).get(color, {}).get(
                    channel, _DHSL_CHANNEL_DEFAULTS.get(channel, 0)
                )
            elif key.startswith("target."):
                _, channel = key.split(".", 1)
                value = (params.get("target_color") or {}).get(channel, row.default)
            else:
                value = params.get(key, DEFAULT_PARAMS.get(key, row.default))
            if key == "exposure":
                value = int(round(float(value) * 100))
            row.set_value(int(value))
        for key, checkbox in self.checkboxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(params.get(key, False)))
            checkbox.blockSignals(False)
        self.print_mode.blockSignals(True)
        self.print_mode.setCurrentText(str(params.get("print_mode", "None")))
        self.print_mode.blockSignals(False)

    def _build_nav(self) -> QHBoxLayout:
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(4)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for spec in CATEGORIES:
            button = QToolButton()
            button.setObjectName("CategoryButton")
            button.setToolTip(f"{spec.name}: {spec.description}")
            button.setText(spec.icon)
            button.setCheckable(True)
            button.setFixedSize(38, 38)
            button.clicked.connect(lambda checked=False, name=spec.name: self.open_category(name))
            self.nav_group.addButton(button)
            self.category_buttons[spec.name] = button
            nav.addWidget(button)
        self.ai_tools_btn = QToolButton()
        self.ai_tools_btn.setObjectName("CategoryButton")
        self.ai_tools_btn.setToolTip("AI Tools: Artistic effects and AI style transfer.")
        self.ai_tools_btn.setText("🤖")
        self.ai_tools_btn.setCheckable(True)
        self.ai_tools_btn.setFixedSize(38, 38)
        self.ai_tools_btn.setStyleSheet(self._category_button_style(_AI_TOOLS_COLOR, False))
        self.ai_tools_btn.clicked.connect(self._on_ai_tools_btn_clicked)
        nav.addWidget(self.ai_tools_btn)
        nav.addStretch()
        return nav

    def _on_ai_tools_btn_clicked(self) -> None:
        if self._ai_tools_page is not None and self.stack.currentWidget() is self._ai_tools_page:
            self.open_category("Quick")
        else:
            self.open_ai_tools()

    def _build_pages(self) -> None:
        self._add_quick_page()
        self._add_light_page()
        self._add_color_page()
        self._add_portrait_page()
        self._add_effects_page()
        self._add_print_page()
        self._add_advanced_page()

    def _make_page(self, name: str) -> CategoryPage:
        spec = next(item for item in CATEGORIES if item.name == name)
        page = CategoryPage(spec)
        self.pages[name] = page
        self.stack.addWidget(page)
        return page

    def _add_quick_page(self) -> None:
        page = self._make_page("Quick")
        page.add_action("Auto Enhance", self.auto_enhance_requested.emit)
        page.add_action("Smart Auto", self.smart_auto_fix_requested.emit)
        page.add_action("Reset", lambda: self.reset_section_requested.emit("Quick Fixes"))
        recent = page.add_section("Recently Used")
        self.recent_container = QWidget()
        self.recent_layout = QVBoxLayout(self.recent_container)
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        recent.addWidget(self.recent_container)
        fixes = page.add_section("Quick Fixes")
        self._add_slider(fixes, "Quick", "Quick Fixes", "exposure", "Exposure x100", -200, 200, 0)
        self._add_slider(fixes, "Quick", "Quick Fixes", "brightness", "Brightness", -100, 100, 0)
        self._add_slider(fixes, "Quick", "Quick Fixes", "contrast", "Contrast", -100, 100, 0)
        page.finish()

    def _add_light_page(self) -> None:
        page = self._make_page("Light")
        page.add_action("Auto Levels", self.auto_levels_requested.emit)
        page.add_action("Auto Contrast", self.auto_contrast_requested.emit)
        page.add_action("Reset", lambda: self.reset_section_requested.emit("Tone"))
        tone = page.add_section("Tone")
        for spec in [
            ("highlights", "Highlights", -100, 100, 0),
            ("shadows", "Shadows", -100, 100, 0),
            ("whites", "Whites", -100, 100, 0),
            ("blacks", "Blacks", -100, 100, 0),
            ("gamma", "Gamma", -100, 100, 0),
        ]:
            self._add_slider(tone, "Light", "Tone", *spec)
        page.finish()

    def _add_color_page(self) -> None:
        page = self._make_page("Color")
        page.add_action("Auto Color", self.auto_enhance_requested.emit)
        page.add_action("Reset", lambda: self.reset_section_requested.emit("Basic Color"))
        basic = page.add_section("Basic Color")
        for spec in [
            ("temperature", "Temperature", -100, 100, 0),
            ("tint", "Tint", -50, 50, 0),
            ("vibrance", "Vibrance", -100, 100, 0),
            ("saturation", "Saturation", -100, 100, 0),
        ]:
            self._add_slider(basic, "Color", "Basic Color", *spec)
        bw = QCheckBox("Black and White")
        bw.toggled.connect(lambda checked: self.param_changed.emit("black_white", checked))
        self.checkboxes["black_white"] = bw
        self.control_locations["black_white"] = ("Color", "Basic Color")
        basic.addWidget(bw)

        hsl = page.add_section("HSL")
        for spec in self._hsl_sliders():
            self._add_slider(hsl, "Color", "HSL", *spec)

        self._dhsl_section = page.add_section("Dynamic HSL")
        self._build_dynamic_hsl_section(self._dhsl_section)

        lut = page.add_section("LUT")
        self._add_slider(lut, "Color", "LUT", "lut_amount", "LUT Amount", 0, 100, 0)
        target = page.add_section("Target Color")
        target_buttons = QHBoxLayout()
        target_button_widget = QWidget()
        target_button_widget.setLayout(target_buttons)
        for label, mode in [("Pick Color", "replace"), ("+ Add Sample", "include"), ("- Remove Sample", "exclude")]:
            button = QPushButton(label)
            button.setObjectName("MiniButton")
            button.clicked.connect(lambda checked=False, pick_mode=mode: self.target_color_pick_requested.emit(pick_mode))
            target_buttons.addWidget(button)
        target.addWidget(target_button_widget)
        for spec in [
            ("target.range_width", "Range Width", 5, 90, 35),
            ("target.softness", "Softness", 1, 60, 20),
            ("target.hue_shift", "Hue Shift", -100, 100, 0),
            ("target.saturation", "Saturation", -100, 100, 0),
            ("target.luminance", "Luminance", -100, 100, 0),
        ]:
            self._add_slider(target, "Color", "Target Color", *spec)
        page.finish()

    def _add_portrait_page(self) -> None:
        page = self._make_page("Portrait")
        page.add_action("Detect Faces", self.detect_faces_requested.emit)
        page.add_action("Smart Auto", self.smart_auto_fix_requested.emit)
        face = page.add_section("Face")
        for spec in [
            ("ai_face_brighten", "Face Brighten", 0, 100, 0),
            ("ai_face_restore", "Face Restore", 0, 100, 0),
            ("ai_skin_tone_protection", "Skin Tone Protection", 0, 100, 0),
            ("print_reduce_red_skin", "Reduce Red Skin", 0, 100, 0),
        ]:
            self._add_slider(face, "Portrait", "Face", *spec)
        subject = page.add_section("Subject")
        self._add_slider(subject, "Portrait", "Subject", "ai_subject_enhance", "Subject Enhance", 0, 100, 0)
        page.finish()

    def _add_effects_page(self) -> None:
        page = self._make_page("Effects")
        page.add_action("Reset", lambda: self.reset_section_requested.emit("Blur"))
        blur = page.add_section("Blur")
        for spec in [
            ("gaussian_blur", "Gaussian Blur", 0, 50, 0),
            ("motion_blur", "Motion Blur", 0, 100, 0),
            ("motion_angle", "Motion Angle", -180, 180, 0),
            ("radial_blur", "Radial Blur", 0, 100, 0),
            ("ai_background_blur", "Background Blur", 0, 100, 0),
            ("ai_background_darkening", "Darken Background", 0, 100, 0),
        ]:
            self._add_slider(blur, "Effects", "Blur", *spec)
        finish = page.add_section("Finish")
        for spec in [
            ("vignette_amount", "Vignette", -100, 100, 0),
            ("vignette_feather", "Vignette Feather", 0, 100, 65),
            ("vignette_midpoint", "Vignette Midpoint", 0, 100, 50),
            ("grain_amount", "Grain", 0, 100, 0),
            ("grain_size", "Grain Size", 1, 60, 18),
        ]:
            self._add_slider(finish, "Effects", "Finish", *spec)
        page.finish()

    def _add_print_page(self) -> None:
        page = self._make_page("Print")
        page.add_action("Print Safe", lambda: self.param_changed.emit("print_mode", "General Print Safe"))
        page.add_action("Reset", lambda: self.reset_section_requested.emit("Print Setup"))
        setup = page.add_section("Print Setup")
        self.print_mode = QComboBox()
        self.print_mode.addItems(PRINT_MODES)
        self.print_mode.currentTextChanged.connect(lambda value: self.param_changed.emit("print_mode", value))
        self.control_locations["print_mode"] = ("Print", "Print Setup")
        setup.addWidget(QLabel("Print Mode"))
        setup.addWidget(self.print_mode)
        for spec in [
            ("print_boost_shadows", "Boost Shadows", 0, 100, 0),
            ("print_protect_highlights", "Protect Highlights", 0, 100, 0),
            ("print_safe_sharpness", "Print Sharpness", 0, 60, 0),
        ]:
            self._add_slider(setup, "Print", "Print Setup", *spec)
        page.finish()

    def _add_advanced_page(self) -> None:
        page = self._make_page("Advanced")
        page.add_action("Reset Detail", lambda: self.reset_section_requested.emit("Detail"))
        detail = page.add_section("Detail")
        for spec in [
            ("sharpness", "Sharpness", 0, 100, 0),
            ("noise_reduction", "Noise Reduction", 0, 100, 0),
            ("color_noise_reduction", "Color Noise", 0, 100, 0),
            ("texture", "Texture", -100, 100, 0),
            ("clarity", "Clarity", -100, 100, 0),
        ]:
            self._add_slider(detail, "Advanced", "Detail", *spec)
        upscale = page.add_section("Upscale")
        for spec in [
            ("ai_upscale_factor", "Upscale Factor", 0, 4, 0),
            ("ai_upscale_strength", "Upscale Strength", 0, 100, 100),
        ]:
            self._add_slider(upscale, "Advanced", "Upscale", *spec)
        page.finish()

    def _add_slider(
        self,
        section: CollapsibleSection,
        category: str,
        section_name: str,
        key: str,
        title: str,
        min_value: int,
        max_value: int,
        default: int,
    ) -> None:
        row = SliderRow(key, title, min_value, max_value, default)
        row.changed.connect(self._emit_param)
        row.changed.connect(lambda changed_key, _value: self._record_recent(changed_key))
        row.hovered.connect(self._handle_slider_hover)
        row.unhovered.connect(self._handle_slider_unhover)
        row.slider_pressed.connect(self._handle_slider_pressed)
        row.reset_requested.connect(self.reset_param_requested.emit)
        self.rows[key] = row
        self.control_locations[key] = (category, section_name)
        section.addWidget(row)

    def _build_dynamic_hsl_section(self, section: CollapsibleSection) -> None:
        """Populate the Dynamic HSL collapsible section with per-channel controls."""
        adv_toggle = QPushButton("Show Range & Softness ▼")
        adv_toggle.setObjectName("MiniButton")
        adv_toggle.setCheckable(True)
        adv_toggle.toggled.connect(self._toggle_dhsl_advanced)
        section.addWidget(adv_toggle)

        for color in DYNAMIC_HSL_COLORS:
            chip_row = QWidget()
            chip_layout = QHBoxLayout(chip_row)
            chip_layout.setContentsMargins(8, 6, 8, 0)
            chip_layout.setSpacing(6)
            chip = QLabel()
            chip.setFixedSize(12, 12)
            chip.setStyleSheet(
                f"background: {_DHSL_CHIP_COLORS[color]};"
                "border-radius: 6px;"
            )
            chip_label = QLabel(color.capitalize())
            chip_label.setObjectName("SliderTitle")
            chip_layout.addWidget(chip)
            chip_layout.addWidget(chip_label)
            chip_layout.addStretch()
            section.addWidget(chip_row)

            self._add_slider(section, "Color", "Dynamic HSL", f"dhsl.{color}.hue_shift", "Hue", -100, 100, 0)
            self._add_slider(section, "Color", "Dynamic HSL", f"dhsl.{color}.saturation", "Saturation", -100, 100, 0)
            self._add_slider(section, "Color", "Dynamic HSL", f"dhsl.{color}.luminance", "Luminance", -100, 100, 0)

            rw_key = f"dhsl.{color}.range_width"
            sf_key = f"dhsl.{color}.softness"
            self._add_slider(section, "Color", "Dynamic HSL", rw_key, "Range Width", 15, 80, 35)
            self._add_slider(section, "Color", "Dynamic HSL", sf_key, "Softness", 0, 60, 25)
            self.rows[rw_key].setVisible(False)
            self.rows[sf_key].setVisible(False)
            self.dhsl_advanced_rows.extend([self.rows[rw_key], self.rows[sf_key]])

    def _toggle_dhsl_advanced(self, checked: bool) -> None:
        sender = self.sender()
        if sender:
            sender.setText("Hide Range & Softness ▲" if checked else "Show Range & Softness ▼")
        for row in self.dhsl_advanced_rows:
            row.setVisible(checked)
        if self._dhsl_section is not None:
            self._dhsl_section.set_open(True, animated=False)

    def _hsl_sliders(self) -> list[tuple[str, str, int, int, int]]:
        sliders: list[tuple[str, str, int, int, int]] = []
        for color in HSL_COLORS:
            label = color.capitalize()
            sliders.extend(
                [
                    (f"hsl.{color}.hue", f"{label} Hue", -100, 100, 0),
                    (f"hsl.{color}.saturation", f"{label} Saturation", -100, 100, 0),
                    (f"hsl.{color}.luminance", f"{label} Luminance", -100, 100, 0),
                ]
            )
        return sliders

    def _emit_param(self, key: str, value: int):
        if key == "exposure":
            self.param_changed.emit(key, value / 100.0)
        elif key.startswith("hsl."):
            _, color, channel = key.split(".", 2)
            self.param_changed.emit("hsl", {"color": color, "channel": channel, "value": value})
        elif key.startswith("dhsl."):
            _, color, channel = key.split(".", 2)
            self.param_changed.emit("dynamic_hsl", {"color": color, "channel": channel, "value": value})
        elif key.startswith("target."):
            _, channel = key.split(".", 1)
            self.param_changed.emit("target_color", {"channel": channel, "value": value})
            self.target_color_preview_requested.emit()
        else:
            self.param_changed.emit(key, value)

    def _handle_slider_hover(self, key: str) -> None:
        if key.startswith("hsl."):
            _prefix, color, _channel = key.split(".", 2)
            self.hsl_preview_requested.emit(color)
        elif key.startswith("dhsl."):
            _, color, _channel = key.split(".", 2)
            self.dynamic_hsl_preview_requested.emit(color)
        elif key.startswith("target."):
            self.target_color_preview_requested.emit()

    def _handle_slider_unhover(self, key: str) -> None:
        if key.startswith(("hsl.", "dhsl.", "target.")):
            self.hsl_preview_hide_requested.emit()

    def _handle_slider_pressed(self, key: str) -> None:
        if key.startswith(("hsl.", "dhsl.", "target.")):
            self.hsl_preview_hide_requested.emit()

    def _record_recent(self, key: str) -> None:
        if key in self.recent_controls:
            self.recent_controls.remove(key)
        self.recent_controls.insert(0, key)
        self.recent_controls = self.recent_controls[:3]
        self._refresh_recent()

    def _refresh_recent(self) -> None:
        if not hasattr(self, "recent_layout"):
            return
        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        if not self.recent_controls:
            label = QLabel(self.translator.text("No recent tools yet"))
            label.setObjectName("ToolPageDescription")
            self.recent_layout.addWidget(label)
            return
        for key in self.recent_controls:
            row = self.rows.get(key)
            button = QPushButton(self.translator.text(row.title if row else key))
            button.setObjectName("RecentButton")
            button.clicked.connect(lambda checked=False, control=key: self.highlight_control(control))
            self.recent_layout.addWidget(button)

    def _clear_highlight(self) -> None:
        if not self.highlighted_control:
            return
        row = self.rows.get(self.highlighted_control)
        if row:
            row.set_highlighted(False)
        checkbox = self.checkboxes.get(self.highlighted_control)
        if checkbox:
            checkbox.setStyleSheet("")
        self.highlighted_control = None

    def _normalize_control_name(self, control_name: str) -> str:
        normalized = control_name.strip().lower().replace(" ", "_")
        aliases = {
            "exposure": "exposure",
            "brightness": "brightness",
            "contrast": "contrast",
            "vibrance": "vibrance",
            "saturation": "saturation",
            "temperature": "temperature",
            "tint": "tint",
            "shadows": "shadows",
            "highlights": "highlights",
            "face_brighten": "ai_face_brighten",
            "face_restore": "ai_face_restore",
            "background_blur": "ai_background_blur",
            "upscale": "ai_upscale_factor",
            "lut": "lut_amount",
            "target_color": "target.range_width",
            "range_width": "target.range_width",
            "reduce_red_skin": "print_reduce_red_skin",
            "print_mode": "print_mode",
            "dynamic_hsl": "dhsl.red.hue_shift",
        }
        return aliases.get(normalized, normalized)

    def _fade_current_page(self) -> None:
        self.hsl_preview_hide_requested.emit()
        page = self.stack.currentWidget()
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", page)
        animation.setDuration(120)
        animation.setStartValue(0.65)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.finished.connect(lambda: page.setGraphicsEffect(None))
        page._fade_animation = animation
        animation.start()

    def _category_button_style(self, color: str, active: bool) -> str:
        if active:
            return (
                "QToolButton#CategoryButton {"
                f"background: {color}; color: #151729; border: 1px solid {color};"
                "border-radius: 10px; font-size: 19px; font-weight: 800;"
                "}"
            )
        return (
            "QToolButton#CategoryButton {"
            "background: #1d1e38; color: #f4f0ff; border: 1px solid #414274;"
            "border-radius: 10px; font-size: 18px;"
            "}"
            "QToolButton#CategoryButton:hover {"
            f"border: 1px solid {color}; background: #30325c;"
            "}"
        )
