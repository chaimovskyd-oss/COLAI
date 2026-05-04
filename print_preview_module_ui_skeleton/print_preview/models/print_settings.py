from dataclasses import dataclass, field


@dataclass
class PrintSettings:
    active_print_profile_name: str = ""

    # Printer
    printer_name: str | None = None
    mirror_output: bool = False
    driver_orientation: str | None = None
    driver_paper_name: str | None = None
    driver_paper_width_mm: float | None = None
    driver_paper_height_mm: float | None = None
    driver_copies: int = 1
    driver_color_mode: str | None = None
    native_devmode_bytes: bytes = b""

    # Scale
    scale_mode: str = "fit_printable"   # "100" | "fit_page" | "fit_printable" | "custom"
    custom_scale: float = 1.0
    align_mode: str = "center"
    align_offset_x_mm: float = 0.0
    align_offset_y_mm: float = 0.0
    paper_type: str = ""

    # Guides — visual in preview
    show_image_border: bool = True
    show_cut_lines: bool = True
    print_cut_lines: bool = False
    show_safe_area: bool = False
    show_bleed: bool = False
    preview_guides_visible: bool = True
    bleed_mm: float = 3.0
    safe_area_mm: float = 3.0

    # Guide appearance
    guide_style: str = "Dashed"     # "Dashed" | "Dotted" | "Solid"
    guide_color: str = "Gray"       # "Black" | "Gray" | "White" | "Blue" | "Red"

    # ── Print Color Preset (applied BEFORE ICC in the render pipeline) ────────
    # Selection:  ""  = None/disabled,  "Custom"  = custom values,
    #             any other string = a named saved preset.
    print_color_preset_enabled: bool = False
    print_color_preset_name:    str  = ""
    print_color_preset_values:  dict = field(default_factory=dict)

    # ── ICC / color management (applied AFTER Print Color Preset) ─────────────
    # Transforms applied by ICCService in PreviewRenderer (preview) and
    # AppRenderAdapter.render_export_page (print/export).
    enable_color_management: bool = False
    source_profile: str = "sRGB IEC61966-2.1"
    output_profile: str | None = None
    rendering_intent: str = "Perceptual"
    soft_proof_preview: bool = False

    # Output quality
    dpi: int = 300
