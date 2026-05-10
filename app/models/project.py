from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


COLOR_EQUALIZER_NODE_COUNT = 8


FaceRegion = Tuple[float, float, float, float]   # cx, cy, w, h  – all in [0..1]


@dataclass
class AnalysisBox:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return max(0.0, self.right - self.left)

    @property
    def height(self) -> float:
        return max(0.0, self.bottom - self.top)

    @property
    def cx(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass
class FaceDetectionData:
    bbox: AnalysisBox
    confidence: float = 0.0
    area_ratio: float = 0.0
    center: Tuple[float, float] = (0.5, 0.5)
    keypoints: Dict[str, Tuple[float, float]] = field(default_factory=dict)


@dataclass
class PersonDetectionData:
    bbox: AnalysisBox
    confidence: float = 0.0
    area_ratio: float = 0.0
    center: Tuple[float, float] = (0.5, 0.5)


@dataclass
class SafeRegions:
    face_safe_region: Optional[AnalysisBox] = None
    person_safe_region: Optional[AnalysisBox] = None
    combined_safe_region: Optional[AnalysisBox] = None


@dataclass
class CropRisk:
    warning_type: str
    message: str
    severity: str = 'info'
    suggestion: str = ''


@dataclass
class ImageAnalysis:
    image_id: str = ''
    source_path: str = ''
    image_size: Tuple[int, int] = (0, 0)
    preview_size: Tuple[int, int] = (0, 0)
    faces: List[FaceDetectionData] = field(default_factory=list)
    persons: List[PersonDetectionData] = field(default_factory=list)
    image_type: str = 'no people'
    crop_tolerance: str = 'low'
    safe_regions: SafeRegions = field(default_factory=SafeRegions)
    warnings_metadata: List[CropRisk] = field(default_factory=list)
    analyzed_at: str = ''
    cache_key: str = ''
    detector_versions: Dict[str, str] = field(default_factory=dict)
    future_hooks: Dict[str, bool] = field(default_factory=lambda: {
        'pose_supported': False,
        'face_landmarks_supported': False,
        'segmentation_supported': False,
        'saliency_supported': False,
    })


@dataclass
class ColorEqualizerState:
    enabled: bool = False
    active_mode: str = 'saturation'   # hue | saturation | brightness
    hue_values: List[float] = field(default_factory=lambda: [0.0] * COLOR_EQUALIZER_NODE_COUNT)
    saturation_values: List[float] = field(default_factory=lambda: [0.0] * COLOR_EQUALIZER_NODE_COUNT)
    brightness_values: List[float] = field(default_factory=lambda: [0.0] * COLOR_EQUALIZER_NODE_COUNT)
    version: int = 1


@dataclass
class ImageState:
    path: str
    pan_x: float = 0.5
    pan_y: float = 0.5
    zoom: float = 1.0
    face_regions: List[FaceRegion] = field(default_factory=list)
    # Tone adjustments
    brightness: float = 1.0
    contrast: float = 1.0
    saturation: float = 1.0
    sharpness: float = 1.0
    is_bw: bool = False
    # Manual rotation (clockwise degrees: 0 / 90 / 180 / 270)
    rotation: int = 0
    # Advanced adjustments
    exposure_ev: float = 0.0                       # stops: -3.0 … +3.0
    levels_r: Tuple[int, int] = (0, 255)           # black / white point for R
    levels_g: Tuple[int, int] = (0, 255)
    levels_b: Tuple[int, int] = (0, 255)
    clahe_enabled: bool = False
    clahe_clip: float = 2.0                        # CLAHE clip limit
    vignette_strength: float = 0.0                 # 0.0 = off, 1.0 = strong edge darkening
    color_equalizer: ColorEqualizerState = field(default_factory=ColorEqualizerState)
    analysis: Optional[ImageAnalysis] = None
    analysis_status: str = 'pending'


@dataclass
class CellRect:
    x: float
    y: float
    w: float
    h: float
    image_index: Optional[int] = None
    # Text cell fields (when set, cell renders as text instead of image)
    cell_text: str = ''
    cell_text_color: Tuple[int, int, int] = (0, 0, 0)
    cell_text_font: str = 'Arial'
    cell_text_size_pt: float = 24.0
    cell_text_align: str = 'center'    # 'left'|'center'|'right'
    cell_bg_rgb: Optional[Tuple[int, int, int]] = None   # None = use canvas background
    # Per-cell shape (from template slots).  'rectangle' = no masking.
    shape_type: str = 'rectangle'
    shape_params: Dict[str, float] = field(default_factory=dict)
    # Optional edge rendering effect. Kept on the cell so all selection,
    # crop, transform, snapping, and export math still use the logical cell.
    edge_style: str = 'hard'              # 'hard' | 'soft_fade'
    fade_amount: int = 16                 # logical px before preview/export scaling clamp
    fade_sides: str = 'all'               # all|left|right|top|bottom|horizontal|vertical
    fade_curve: str = 'smooth'            # linear|smooth|ease_out
    rotation_deg: float = 0.0             # visual cell rotation for layered templates
    z_index: int = 0                      # draw order; larger values are painted above
    mask_seed: int = 0                    # deterministic per-cell procedural masks


@dataclass
class LayoutSuggestion:
    name: str
    cells: List[CellRect] = field(default_factory=list)
    score: float = 0.0
    shape: str = ''         # '' = normal grid | 'circle' | 'heart'
    # Dynamic / tree-based layout. When set, cells are regenerated from the
    # tree on every drag so the layout is fully interactive.
    tree: Optional[Any] = field(default=None, compare=False, repr=False)


@dataclass
class TextOverlay:
    text: str = ''
    font_family: str = 'Arial'
    font_size_pt: int = 36
    font_bold: bool = False
    font_italic: bool = False
    color_rgb: Tuple[int, int, int] = (0, 0, 0)
    position: str = 'bottom'          # 'top' | 'bottom' | 'center'
    h_align: str = 'center'           # 'left' | 'center' | 'right'
    padding_mm: float = 5.0
    background_rgb: Optional[Tuple[int, int, int]] = None   # None = transparent
    background_opacity: int = 100     # 0-100
    stroke_width_px: int = 0
    stroke_color_rgb: Tuple[int, int, int] = (0, 0, 0)
    text_shadow: bool = False
    text_shadow_offset_px: int = 3
    text_shadow_color_rgb: Tuple[int, int, int] = (80, 80, 80)
    # Drag position in normalised canvas coords [0..1]; -1 = use position/h_align fields
    pos_x_frac: float = -1.0
    pos_y_frac: float = -1.0


@dataclass
class ElementOverlay:
    """A free-placed decorative element (SVG/PNG/JPEG) on the canvas."""
    path: str = ''
    pos_x_frac: float = 0.5      # anchor center X as fraction of canvas
    pos_y_frac: float = 0.5      # anchor center Y
    width_frac: float = 0.20     # element width as fraction of canvas width
    rotation_deg: float = 0.0   # free rotation in degrees
    opacity: float = 1.0        # 0..1


@dataclass
class ProjectSettings:
    width_cm: float = 15.0
    height_cm: float = 10.0
    dpi: int = 300
    margin_mm: float = 5.0
    spacing_mm: float = 1.7
    background_rgb: Tuple[int, int, int] = (255, 255, 255)
    background_type: str = 'solid'   # 'solid' | 'gradient' | 'image'
    background_gradient: tuple = field(default_factory=lambda: ((230, 220, 190), (180, 140, 60)))
    background_gradient_angle: float = 90.0   # 0=left→right, 90=top→bottom, 45=diagonal
    background_image_path: str = ''
    # Cell style
    corner_radius_mm: float = 0.0
    border_width_mm: float = 0.0
    border_color_rgb: Tuple[int, int, int] = (0, 0, 0)
    shadow_enabled: bool = False
    shadow_offset_mm: float = 2.0
    shadow_blur_mm: float = 3.0
    shadow_opacity: int = 100           # 0-255
    soft_fade_enabled: bool = False
    soft_fade_amount_px: int = 16
    soft_fade_mode: str = 'soft_edge'   # soft_edge | overlap_fade
    soft_fade_sides: str = 'all'
    soft_fade_overlap_px: int = 28
    soft_fade_overlap_sides: str = 'auto_neighbors'
    soft_fade_curve: str = 'smooth'
    soft_fade_spacing_override_enabled: bool = False
    soft_fade_spacing_override_px: int = 20
    # Bleed & safe area (mm)
    bleed_mm: float = 0.0
    safe_area_mm: float = 0.0
    smart_crop_enabled: bool = True
    smart_crop_debug: bool = False
    analysis_mode: str = 'quick'          # 'quick' | 'scanned'
    advanced_face_backend: str = 'auto'   # 'auto' | 'retinaface' | 'mediapipe'
    # DepthAnything feature flags
    depth_overlap_enabled: bool = False
    depth_overlap_intensity: float = 0.5  # 0..1 (נמוך / בינוני / גבוה)
    depth_layers_enabled: bool = False
    depth_layers_intensity: float = 0.5   # 0..1 (עדין / בינוני / חזק)

    @property
    def canvas_px(self) -> Tuple[int, int]:
        w = max(1, int(round(self.width_cm / 2.54 * self.dpi)))
        h = max(1, int(round(self.height_cm / 2.54 * self.dpi)))
        return w, h

    @property
    def margin_px(self) -> int:
        return max(0, int(round(self.margin_mm / 25.4 * self.dpi)))

    @margin_px.setter
    def margin_px(self, value: float) -> None:
        self.margin_mm = max(0.0, float(value) * 25.4 / max(1, self.dpi))

    @property
    def spacing_px(self) -> int:
        return max(0, int(round(self.spacing_mm / 25.4 * self.dpi)))

    @spacing_px.setter
    def spacing_px(self, value: float) -> None:
        self.spacing_mm = max(0.0, float(value) * 25.4 / max(1, self.dpi))


@dataclass
class ProjectState:
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    images: List[ImageState] = field(default_factory=list)
    selected_layout: Optional[LayoutSuggestion] = None
    suggestions: List[LayoutSuggestion] = field(default_factory=list)
    # Draft overlay (currently being composed in the panel)
    text_overlay: TextOverlay = field(default_factory=TextOverlay)
    # Committed overlays (shown permanently on canvas)
    text_overlays: List[TextOverlay] = field(default_factory=list)
    elements: List[ElementOverlay] = field(default_factory=list)
    # Album Builder state — None when album mode is not active
    album_state: Optional[Any] = field(default=None, repr=False)  # AlbumState
