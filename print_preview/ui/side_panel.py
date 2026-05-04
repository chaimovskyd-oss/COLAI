from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from print_preview.services.icc_service import ICCService
from print_preview.profiles.profile_manager import PrintProfileManager
from print_preview.services.preset_service import PresetService
from print_preview.services.printable_area_service import PrintableAreaService
from print_preview.ui.section_card import SectionCard


_SCALE_MODE_MAP = {
    "100 %": "100",
    "Fit to Page": "fit_page",
    "Fit to Printable Area": "fit_printable",
    "Custom": "custom",
}
_ALIGN_MODE_MAP = {
    "Center": "center",
    "Top Left": "top_left",
    "Custom Offset": "custom",
}
_GUIDE_STYLES = ["Dashed", "Dotted", "Solid"]
_GUIDE_COLORS = ["Black", "Gray", "White", "Blue", "Red"]


class PrintPreviewSidePanel(QFrame):
    """Side panel with live print-preview controls."""

    printer_settings_clicked = Signal()

    _PRESET_NONE = "(None)"
    _PRESET_CUSTOM = "Custom"

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setObjectName("SidePanel")
        self.setMinimumWidth(330)
        self.setMaximumWidth(440)
        self._icc = ICCService()
        self._area_svc = PrintableAreaService()
        self._guide_checkboxes: dict[str, QCheckBox] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        layout.addWidget(self._build_profile_section())
        layout.addWidget(self._build_printer_section())
        layout.addWidget(self._build_page_section())
        layout.addWidget(self._build_scale_section())
        layout.addWidget(self._build_icc_section())
        layout.addWidget(self._build_guides_section())
        layout.addWidget(self._build_quality_section())
        layout.addStretch()

        controller.metrics_changed.connect(self._refresh_page_info)
        controller.metrics_changed.connect(self._refresh_scale_info)
        controller.preview_state_changed.connect(self._sync_from_preview_state)

    def _build_profile_section(self):
        card = SectionCard("Saved Print Settings", "בחר הגדרת הדפסה שמורה לכל מאפייני ההדפסה.")

        row = QHBoxLayout()
        row.setSpacing(10)
        self.profile_combo = QComboBox()
        self._rebuild_profile_combo()
        row.addWidget(self.profile_combo, 1)
        self.btn_profile_manage = QPushButton("Manage")
        self.btn_profile_manage.setMinimumWidth(78)
        self.btn_profile_manage.setMinimumHeight(36)
        row.addWidget(self.btn_profile_manage)
        card.layout.addLayout(row)

        self._profile_status = QLabel("")
        self._profile_status.setObjectName("PanelSubtle")
        self._profile_status.setWordWrap(True)
        card.layout.addWidget(self._profile_status)

        self.profile_combo.currentTextChanged.connect(self._on_profile_selected)
        self.btn_profile_manage.clicked.connect(self._on_profile_manage)
        return card

    def _build_printer_section(self):
        card = SectionCard("Printer", "Choose a printer and open its native driver settings.")
        row = QVBoxLayout()

        self.printer_combo = QComboBox()
        printers = self._area_svc.get_available_printers()
        default_printer = self._area_svc.get_default_printer_name()
        if printers:
            self.printer_combo.addItems(printers)
            if default_printer:
                self.printer_combo.setCurrentText(default_printer)
        else:
            self.printer_combo.addItem("No Printer Configured")
            self.printer_combo.setEnabled(False)

        btn_settings = QPushButton("Printer Driver Settings...")
        row.addWidget(self.printer_combo)
        row.addWidget(btn_settings)
        card.layout.addLayout(row)

        self._printer_status_label = QLabel("")
        self._printer_status_label.setObjectName("PanelSubtle")
        self._printer_status_label.setWordWrap(True)
        card.layout.addWidget(self._printer_status_label)

        self.printer_combo.currentTextChanged.connect(self.controller.update_printer_by_name)
        btn_settings.clicked.connect(self.printer_settings_clicked)
        btn_settings.clicked.connect(self.controller.open_printer_settings)
        btn_settings.setMinimumHeight(36)

        if printers:
            self.controller.update_printer_by_name(self.printer_combo.currentText())
        else:
            self.controller.update_printer_by_name("")
        return card

    def _build_page_section(self):
        card = SectionCard("Print Setup", "Live paper, printable-area, and page information.")
        form = QFormLayout()

        self._lbl_design_page = QLabel("-")
        self._lbl_paper = QLabel("-")
        self._lbl_printable = QLabel("-")
        self._lbl_margins = QLabel("-")
        for label, widget in (
            ("Design Page", self._lbl_design_page),
            ("Printer Paper", self._lbl_paper),
            ("Printable Area", self._lbl_printable),
            ("Printer Margins", self._lbl_margins),
        ):
            widget.setObjectName("MetricValue")
            form.addRow(label, widget)

        card.layout.addLayout(form)

        self.chk_mirror_output = QCheckBox("Mirror Output")
        self.chk_mirror_output.toggled.connect(self.controller.set_mirror_output)
        card.layout.addWidget(self.chk_mirror_output)

        self._mirror_warning_label = QLabel(
            "Ensure printer mirror setting is OFF when using software mirror."
        )
        self._mirror_warning_label.setObjectName("WarningBanner")
        self._mirror_warning_label.setWordWrap(True)
        self._mirror_warning_label.setVisible(False)
        card.layout.addWidget(self._mirror_warning_label)

        self._refresh_page_info()
        return card

    def _build_scale_section(self):
        card = SectionCard("Scale & Placement", "Print scale changes real output size. Alignment changes placement.")

        self.scale_combo = QComboBox()
        self.scale_combo.addItems(list(_SCALE_MODE_MAP.keys()))
        self.scale_combo.setCurrentText("Fit to Printable Area")
        card.layout.addWidget(self.scale_combo)

        form = QFormLayout()
        self.custom_scale_spin = QDoubleSpinBox()
        self.custom_scale_spin.setRange(1.0, 500.0)
        self.custom_scale_spin.setValue(100.0)
        self.custom_scale_spin.setDecimals(1)
        self.custom_scale_spin.setSuffix(" %")
        self.custom_scale_spin.setEnabled(False)

        self.align_combo = QComboBox()
        self.align_combo.addItems(list(_ALIGN_MODE_MAP.keys()))
        self.align_offset_x = QDoubleSpinBox()
        self.align_offset_y = QDoubleSpinBox()
        for spin in (self.align_offset_x, self.align_offset_y):
            spin.setRange(-500.0, 500.0)
            spin.setDecimals(1)
            spin.setSuffix(" mm")
            spin.setEnabled(False)

        self._lbl_printed_size = QLabel("-")
        self._lbl_printed_size.setObjectName("MetricValue")

        form.addRow("Scale Mode", self.scale_combo)
        form.addRow("Custom Scale", self.custom_scale_spin)
        form.addRow("Alignment", self.align_combo)
        form.addRow("Offset X", self.align_offset_x)
        form.addRow("Offset Y", self.align_offset_y)
        form.addRow("Printed Size", self._lbl_printed_size)
        card.layout.addLayout(form)

        self.scale_combo.currentTextChanged.connect(self._on_scale_mode_changed)
        self.custom_scale_spin.valueChanged.connect(self.controller.set_custom_scale)
        self.align_combo.currentTextChanged.connect(self._on_alignment_mode_changed)
        self.align_offset_x.valueChanged.connect(lambda value: self.controller.set_alignment_offset("x", value))
        self.align_offset_y.valueChanged.connect(lambda value: self.controller.set_alignment_offset("y", value))

        self._refresh_scale_info()
        return card

    def _build_icc_section(self):
        card = SectionCard("Color Management", "Print color preset is applied before ICC conversion.")

        preset_title = QLabel("Print Color Preset")
        preset_title.setObjectName("PanelTitle")
        card.layout.addWidget(preset_title)

        preset_hint = QLabel("Presets affect image content only, never the paper background.")
        preset_hint.setObjectName("PanelSubtle")
        preset_hint.setWordWrap(True)
        card.layout.addWidget(preset_hint)

        preset_row = QVBoxLayout()
        preset_row.setSpacing(10)
        self.preset_combo = QComboBox()
        self._rebuild_preset_combo()
        preset_row.addWidget(self.preset_combo)

        preset_buttons = QHBoxLayout()
        preset_buttons.setSpacing(10)
        self.btn_preset_edit = QPushButton("Edit")
        self.btn_preset_save_as = QPushButton("Save As")
        self.btn_preset_manage = QPushButton("Manage")
        for btn in (self.btn_preset_edit, self.btn_preset_save_as, self.btn_preset_manage):
            btn.setMinimumHeight(36)
            preset_buttons.addWidget(btn)
        preset_row.addLayout(preset_buttons)
        card.layout.addLayout(preset_row)

        self._preset_status = QLabel("")
        self._preset_status.setObjectName("PanelSubtle")
        self._preset_status.setWordWrap(True)
        card.layout.addWidget(self._preset_status)

        self.preset_combo.currentTextChanged.connect(self._on_preset_selected)
        self.btn_preset_edit.clicked.connect(self._on_preset_edit)
        self.btn_preset_save_as.clicked.connect(self._on_preset_save_as)
        self.btn_preset_manage.clicked.connect(self._on_preset_manage)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setObjectName("Separator")
        card.layout.addWidget(sep)

        icc_title = QLabel("ICC Color Management")
        icc_title.setObjectName("PanelTitle")
        card.layout.addWidget(icc_title)

        self.chk_icc = QCheckBox("Enable Color Management")
        card.layout.addWidget(self.chk_icc)

        self.icc_source = QComboBox()
        self.icc_source.addItems(self._icc.available_source_profiles())
        self.icc_output = QComboBox()
        self.icc_output.addItems(self._icc.available_output_profiles())
        self.icc_intent = QComboBox()
        self.icc_intent.addItems(self._icc.available_rendering_intents())

        form = QFormLayout()
        form.addRow("Source Profile", self.icc_source)
        form.addRow("Output Profile", self.icc_output)
        form.addRow("Rendering Intent", self.icc_intent)
        card.layout.addLayout(form)

        self.chk_soft_proof = QCheckBox("Soft Proof Preview")
        card.layout.addWidget(self.chk_soft_proof)

        self.chk_icc.toggled.connect(lambda value: self.controller.set_icc_setting("enable_color_management", value))
        self.icc_source.currentTextChanged.connect(lambda value: self.controller.set_icc_setting("source_profile", value))
        self.icc_output.currentTextChanged.connect(lambda value: self.controller.set_icc_setting("output_profile", value))
        self.icc_intent.currentTextChanged.connect(lambda value: self.controller.set_icc_setting("rendering_intent", value))
        self.chk_soft_proof.toggled.connect(lambda value: self.controller.set_icc_setting("soft_proof_preview", value))
        return card

    def _build_guides_section(self):
        card = SectionCard("Production Guides", "Bleed, safe area, and crop marks are calculated in mm.")
        guide_defs = (
            ("Show Image Border", "show_image_border", True),
            ("Show Cut Lines", "show_cut_lines", True),
            ("Print Cut Lines", "print_cut_lines", False),
            ("Show Safe Area", "show_safe_area", False),
            ("Show Bleed", "show_bleed", False),
        )
        for label, attr, default in guide_defs:
            chk = QCheckBox(label)
            chk.setChecked(default)
            chk.toggled.connect((lambda name: lambda value: self.controller.set_guide(name, value))(attr))
            card.layout.addWidget(chk)
            self._guide_checkboxes[attr] = chk

        form = QFormLayout()
        self.guide_style_combo = QComboBox()
        self.guide_style_combo.addItems(_GUIDE_STYLES)
        self.guide_color_combo = QComboBox()
        self.guide_color_combo.addItems(_GUIDE_COLORS)
        self.bleed_spin = QDoubleSpinBox()
        self.bleed_spin.setRange(0.0, 25.0)
        self.bleed_spin.setDecimals(1)
        self.bleed_spin.setSuffix(" mm")
        self.bleed_spin.setValue(3.0)
        self.safe_area_spin = QDoubleSpinBox()
        self.safe_area_spin.setRange(0.0, 25.0)
        self.safe_area_spin.setDecimals(1)
        self.safe_area_spin.setSuffix(" mm")
        self.safe_area_spin.setValue(3.0)
        form.addRow("Line Style", self.guide_style_combo)
        form.addRow("Line Color", self.guide_color_combo)
        form.addRow("Bleed", self.bleed_spin)
        form.addRow("Safe Area", self.safe_area_spin)
        card.layout.addLayout(form)

        self.guide_style_combo.currentTextChanged.connect(self.controller.set_guide_style)
        self.guide_color_combo.currentTextChanged.connect(self.controller.set_guide_color)
        self.bleed_spin.valueChanged.connect(self.controller.set_bleed_mm)
        self.safe_area_spin.valueChanged.connect(self.controller.set_safe_area_mm)
        return card

    def _build_quality_section(self):
        card = SectionCard("Quality / Warnings", "Warnings update dynamically from the current preview state.")
        self._quality_warnings: list[QLabel] = []
        for _ in range(8):
            lbl = QLabel("")
            lbl.setObjectName("PanelSubtle")
            lbl.setWordWrap(True)
            lbl.setVisible(False)
            card.layout.addWidget(lbl)
            self._quality_warnings.append(lbl)

        row = QHBoxLayout()
        btn_fix = QPushButton("Suggest Fix")
        btn_upscale = QPushButton("Run AI Upscale")
        btn_fix.setMinimumHeight(36)
        btn_upscale.setMinimumHeight(36)
        row.addWidget(btn_fix)
        row.addWidget(btn_upscale)
        card.layout.addLayout(row)
        return card

    def _rebuild_profile_combo(self):
        blocker = QSignalBlocker(self.profile_combo)
        self.profile_combo.clear()
        self.profile_combo.addItem("(No Profile)")
        for name in PrintProfileManager.list_names():
            self.profile_combo.addItem(name)
        del blocker

    def _on_profile_selected(self, text: str):
        if not text or text == "(No Profile)":
            return
        profile = PrintProfileManager.get_profile(text)
        if profile is None:
            self._profile_status.setText(f"Profile '{text}' could not be loaded.")
            return
        self.controller.apply_print_settings(profile.settings)
        self._profile_status.setText(f"Loaded profile '{profile.name}'.")

    def _save_profile_named(self, name: str):
        profile = PrintProfileManager.save_from_settings(name, self.controller.get_settings())
        self.controller.apply_print_settings({"active_print_profile_name": profile.name})
        self._rebuild_profile_combo()
        blocker = QSignalBlocker(self.profile_combo)
        self.profile_combo.setCurrentText(profile.name)
        del blocker
        self._profile_status.setText(f"Saved profile '{profile.name}'.")

    def _on_profile_save(self):
        current_name = self.profile_combo.currentText().strip()
        if not current_name or current_name == "(No Profile)":
            self._on_profile_save_as()
            return
        self._save_profile_named(current_name)

    def trigger_save_print_settings(self):
        self._on_profile_save_as()

    def _on_profile_save_as(self):
        suggested = self.controller.get_settings().active_print_profile_name or ""
        if not suggested or suggested == "(No Profile)":
            suggested = ""
        name, ok = QInputDialog.getText(self, "Save Print Profile", "Profile name:", text=suggested)
        if not ok or not name.strip():
            return
        self._save_profile_named(name.strip())

    def _on_profile_manage(self):
        names = PrintProfileManager.list_names()
        if not names:
            QMessageBox.information(self, "Manage Profiles", "No saved print profiles yet.")
            return
        name, ok = QInputDialog.getItem(self, "Delete Print Profile", "Profile:", names, editable=False)
        if not ok or not name:
            return
        PrintProfileManager.delete_profile(name)
        self._rebuild_profile_combo()
        if self.controller.get_settings().active_print_profile_name == name:
            self.controller.apply_print_settings({"active_print_profile_name": ""})
        self._profile_status.setText(f"Deleted profile '{name}'.")

    def _on_scale_mode_changed(self, text: str):
        mode = _SCALE_MODE_MAP.get(text, "fit_printable")
        self.custom_scale_spin.setEnabled(mode == "custom")
        self.controller.set_scale_mode(mode)

    def _on_alignment_mode_changed(self, text: str):
        mode = _ALIGN_MODE_MAP.get(text, "center")
        is_custom = mode == "custom"
        self.align_offset_x.setEnabled(is_custom)
        self.align_offset_y.setEnabled(is_custom)
        self.controller.set_alignment_mode(mode)

    def _refresh_page_info(self, metrics=None):
        if metrics is None:
            metrics = self.controller.get_metrics()
        page = self.controller.current_page
        if page:
            self._lbl_design_page.setText(f"{page.width_mm:.0f} x {page.height_mm:.0f} mm")
        self._lbl_paper.setText(f"{metrics.paper_width_mm:.0f} x {metrics.paper_height_mm:.0f} mm")
        self._lbl_printable.setText(f"{metrics.printable_width_mm:.0f} x {metrics.printable_height_mm:.0f} mm")
        self._lbl_margins.setText(
            f"T {metrics.margin_top_mm:.1f}  B {metrics.margin_bottom_mm:.1f}  "
            f"L {metrics.margin_left_mm:.1f}  R {metrics.margin_right_mm:.1f} mm"
        )

    def _refresh_scale_info(self, metrics=None):
        if metrics is None:
            metrics = self.controller.get_metrics()
        self._lbl_printed_size.setText(
            f"{metrics.output_width_mm:.1f} x {metrics.output_height_mm:.1f} mm"
            f"  ({metrics.scale * 100:.1f} %)"
        )

    def _rebuild_preset_combo(self):
        blocker = QSignalBlocker(self.preset_combo)
        self.preset_combo.clear()
        self.preset_combo.addItem(self._PRESET_NONE)
        self.preset_combo.addItem(self._PRESET_CUSTOM)
        for name in PresetService.list_names():
            self.preset_combo.addItem(name)
        del blocker

    def _on_preset_selected(self, text: str):
        if text == self._PRESET_NONE:
            self.controller.clear_preset()
            self._preset_status.setText("")
            return
        if text == self._PRESET_CUSTOM:
            current_values = self.controller.get_preset_values()
            if current_values:
                self.controller.set_preset("Custom", current_values)
                self._preset_status.setText("Custom adjustments active.")
            else:
                self.controller.clear_preset()
                self._preset_status.setText('No custom adjustments defined yet. Click "Edit" to create them.')
            return

        values = PresetService.get(text)
        if values:
            self.controller.set_preset(text, values)
            profile = PresetService.get_profile(text) or {}
            self._preset_status.setText(self._preset_status_text(text, profile))
        else:
            self._preset_status.setText(f"Preset '{text}' could not be loaded.")

    def _on_preset_edit(self):
        from print_preview.ui.preset_editor_dialog import PresetEditorDialog

        original_values = self.controller.get_preset_values()
        original_name = self.controller.settings.print_color_preset_name

        dlg = PresetEditorDialog(original_values or None, parent=self)
        dlg.preview_values_changed.connect(lambda values: self.controller.set_preset("Custom", values))

        if dlg.exec():
            new_values = dlg.get_values()
            self.controller.set_preset("Custom", new_values)
            blocker = QSignalBlocker(self.preset_combo)
            self.preset_combo.setCurrentText(self._PRESET_CUSTOM)
            del blocker
            self._preset_status.setText("Custom adjustments active.")
        else:
            if original_values:
                self.controller.set_preset(original_name or "Custom", original_values)
            else:
                self.controller.clear_preset()

    def _on_preset_save_as(self):
        current_values = self.controller.get_preset_values()
        if not current_values:
            QMessageBox.information(
                self,
                "Save Preset",
                'No active adjustments to save.\n\nClick "Edit" first to define values.',
            )
            return

        suggested = self.controller.settings.print_color_preset_name or ""
        if suggested in (self._PRESET_NONE, self._PRESET_CUSTOM, ""):
            suggested = ""

        name, ok = QInputDialog.getText(self, "Save Print Color Preset", "Preset name:", text=suggested)
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in (self._PRESET_NONE, self._PRESET_CUSTOM):
            QMessageBox.warning(self, "Save Preset", f'"{name}" is a reserved name.')
            return

        PresetService.save(
            name,
            current_values,
            printer_name=self.controller.settings.printer_name or "",
            paper_type=getattr(self.controller.settings, "paper_type", "") or getattr(self.controller.settings, "driver_paper_name", "") or "",
        )
        self.controller.set_preset(name, current_values)
        self._rebuild_preset_combo()
        blocker = QSignalBlocker(self.preset_combo)
        self.preset_combo.setCurrentText(name)
        del blocker
        profile = PresetService.get_profile(name) or {}
        self._preset_status.setText(self._preset_status_text(name, profile, prefix="Saved and applied"))

    def _on_preset_manage(self):
        from print_preview.ui.preset_editor_dialog import ManagePresetsDialog

        dlg = ManagePresetsDialog(parent=self)
        dlg.presets_changed.connect(self._on_presets_externally_changed)
        dlg.exec()

    def _on_presets_externally_changed(self):
        current_text = self.preset_combo.currentText()
        self._rebuild_preset_combo()
        if self.preset_combo.findText(current_text) == -1:
            self.preset_combo.setCurrentText(self._PRESET_NONE)
        else:
            blocker = QSignalBlocker(self.preset_combo)
            self.preset_combo.setCurrentText(current_text)
            del blocker

    def _preset_status_text(self, name: str, profile: dict, prefix: str = "Preset") -> str:
        scope_bits = []
        if profile.get("printer_name"):
            scope_bits.append(profile["printer_name"])
        if profile.get("paper_type"):
            scope_bits.append(profile["paper_type"])
        suffix = f" ({' / '.join(scope_bits)})" if scope_bits else ""
        return f"{prefix} '{name}' active{suffix}."

    def _sync_from_preview_state(self, state):
        status = (
            f"Using: {state.printer_name}"
            if state.has_valid_printer and state.printer_name
            else "No valid printer configured yet."
        )
        driver_bits: list[str] = []
        if getattr(state.settings, "driver_orientation", None):
            driver_bits.append(f"orientation: {state.settings.driver_orientation}")
        if getattr(state.settings, "driver_paper_name", None):
            driver_bits.append(f"paper: {state.settings.driver_paper_name}")
        if getattr(state.settings, "driver_color_mode", None):
            driver_bits.append(f"color: {state.settings.driver_color_mode}")
        if int(getattr(state.settings, "driver_copies", 1) or 1) > 1:
            driver_bits.append(f"copies: {state.settings.driver_copies}")
        if driver_bits:
            status += "\n" + " | ".join(driver_bits)
        self._printer_status_label.setText(status)

        active_profile_name = getattr(state.settings, "active_print_profile_name", "") or ""
        target_profile = active_profile_name if self.profile_combo.findText(active_profile_name) >= 0 else "(No Profile)"
        if self.profile_combo.currentText() != target_profile:
            blocker = QSignalBlocker(self.profile_combo)
            self.profile_combo.setCurrentText(target_profile)
            del blocker
        profile_text = f"Active profile: {active_profile_name}" if active_profile_name else "No saved print profile loaded."
        self._profile_status.setText(profile_text)
        mirror_value = bool(getattr(state.settings, "mirror_output", False))
        if self.chk_mirror_output.isChecked() != mirror_value:
            blocker = QSignalBlocker(self.chk_mirror_output)
            self.chk_mirror_output.setChecked(mirror_value)
            del blocker
        self._mirror_warning_label.setVisible(mirror_value)

        self.update_quality_warnings(state.warnings)

        if self.printer_combo.isEnabled() and state.printer_name and self.printer_combo.currentText() != state.printer_name:
            blocker = QSignalBlocker(self.printer_combo)
            self.printer_combo.setCurrentText(state.printer_name)
            del blocker

        combo_text = next((label for label, mode in _SCALE_MODE_MAP.items() if mode == state.settings.scale_mode), "Fit to Printable Area")
        if self.scale_combo.currentText() != combo_text:
            blocker = QSignalBlocker(self.scale_combo)
            self.scale_combo.setCurrentText(combo_text)
            del blocker

        custom_pct = state.settings.custom_scale * 100.0
        if abs(self.custom_scale_spin.value() - custom_pct) > 0.01:
            blocker = QSignalBlocker(self.custom_scale_spin)
            self.custom_scale_spin.setValue(custom_pct)
            del blocker
        self.custom_scale_spin.setEnabled(state.settings.scale_mode == "custom")

        align_text = next((label for label, mode in _ALIGN_MODE_MAP.items() if mode == state.settings.align_mode), "Center")
        if self.align_combo.currentText() != align_text:
            blocker = QSignalBlocker(self.align_combo)
            self.align_combo.setCurrentText(align_text)
            del blocker
        is_custom_align = state.settings.align_mode == "custom"
        for spin, value in (
            (self.align_offset_x, getattr(state.settings, "align_offset_x_mm", 0.0)),
            (self.align_offset_y, getattr(state.settings, "align_offset_y_mm", 0.0)),
        ):
            if abs(spin.value() - float(value)) > 0.01:
                blocker = QSignalBlocker(spin)
                spin.setValue(float(value))
                del blocker
            spin.setEnabled(is_custom_align)

        for attr, checkbox in self._guide_checkboxes.items():
            value = bool(getattr(state.settings, attr, checkbox.isChecked()))
            if checkbox.isChecked() != value:
                blocker = QSignalBlocker(checkbox)
                checkbox.setChecked(value)
                del blocker

        if self.guide_style_combo.currentText() != getattr(state.settings, "guide_style", "Dashed"):
            blocker = QSignalBlocker(self.guide_style_combo)
            self.guide_style_combo.setCurrentText(getattr(state.settings, "guide_style", "Dashed"))
            del blocker
        if self.guide_color_combo.currentText() != getattr(state.settings, "guide_color", "Gray"):
            blocker = QSignalBlocker(self.guide_color_combo)
            self.guide_color_combo.setCurrentText(getattr(state.settings, "guide_color", "Gray"))
            del blocker
        for spin, value in (
            (self.bleed_spin, getattr(state.settings, "bleed_mm", 3.0)),
            (self.safe_area_spin, getattr(state.settings, "safe_area_mm", 3.0)),
        ):
            if abs(spin.value() - float(value)) > 0.01:
                blocker = QSignalBlocker(spin)
                spin.setValue(float(value))
                del blocker

        if self.chk_icc.isChecked() != bool(getattr(state.settings, "enable_color_management", False)):
            blocker = QSignalBlocker(self.chk_icc)
            self.chk_icc.setChecked(bool(getattr(state.settings, "enable_color_management", False)))
            del blocker
        if self.chk_soft_proof.isChecked() != bool(getattr(state.settings, "soft_proof_preview", False)):
            blocker = QSignalBlocker(self.chk_soft_proof)
            self.chk_soft_proof.setChecked(bool(getattr(state.settings, "soft_proof_preview", False)))
            del blocker
        for combo, value in (
            (self.icc_source, getattr(state.settings, "source_profile", "")),
            (self.icc_output, getattr(state.settings, "output_profile", "")),
            (self.icc_intent, getattr(state.settings, "rendering_intent", "")),
        ):
            if value and combo.currentText() != value:
                blocker = QSignalBlocker(combo)
                if combo.findText(value) >= 0:
                    combo.setCurrentText(value)
                del blocker

        preset_name = getattr(state.settings, "print_color_preset_name", "")
        preset_on = getattr(state.settings, "print_color_preset_enabled", False)
        if not preset_on:
            target = self._PRESET_NONE
        elif preset_name in ("", self._PRESET_CUSTOM):
            target = self._PRESET_CUSTOM
        else:
            target = preset_name
        if self.preset_combo.currentText() != target:
            blocker = QSignalBlocker(self.preset_combo)
            if self.preset_combo.findText(target) >= 0:
                self.preset_combo.setCurrentText(target)
            del blocker
        if preset_on and target not in (self._PRESET_NONE, self._PRESET_CUSTOM):
            profile = PresetService.get_profile(target) or {}
            self._preset_status.setText(self._preset_status_text(target, profile))

    def update_quality_warnings(self, warnings: list[str]) -> None:
        for index, label in enumerate(self._quality_warnings):
            if index < len(warnings):
                label.setText(f"- {warnings[index]}")
                label.setVisible(True)
            else:
                label.setVisible(False)
