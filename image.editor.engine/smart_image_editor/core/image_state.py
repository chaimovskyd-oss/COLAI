from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from smart_image_editor.ai_tools.ai_tools_service import default_ai_tools_params
from smart_image_editor.core.adjustment_stack import Adjustment, AdjustmentStack, TimelineEntry
from smart_image_editor.core.dynamic_hsl import default_dynamic_hsl
from smart_image_editor.core.target_color import default_target_color


DEFAULT_PARAMS: Dict[str, Any] = {
    "crop": None,
    "rotation": 0,
    "flip_horizontal": False,
    "flip_vertical": False,
    "straighten": 0.0,
    "exposure": 0.0,
    "brightness": 0,
    "contrast": 0,
    "highlights": 0,
    "shadows": 0,
    "whites": 0,
    "blacks": 0,
    "gamma": 0,
    "temperature": 0,
    "tint": 0,
    "saturation": 0,
    "vibrance": 0,
    "black_white": False,
    "hsl": {},
    "sharpness": 0,
    "sharpen_radius": 1.0,
    "noise_reduction": 0,
    "color_noise_reduction": 0,
    "texture": 0,
    "clarity": 0,
    "vignette_amount": 0,
    "vignette_feather": 65,
    "vignette_midpoint": 50,
    "vignette_roundness": 0,
    "gaussian_blur": 0,
    "motion_blur": 0,
    "motion_angle": 0,
    "radial_blur": 0,
    "grain_amount": 0,
    "grain_size": 18,
    "print_mode": "None",
    "print_boost_shadows": 0,
    "print_reduce_red_skin": 0,
    "print_protect_highlights": 0,
    "print_safe_sharpness": 0,
    "ai_background_blur": 0,
    "ai_background_darkening": 0,
    "ai_subject_enhance": 0,
    "ai_face_brighten": 0,
    "ai_skin_tone_protection": 0,
    "ai_face_restore": 0,
    "ai_upscale_factor": 0,
    "ai_upscale_strength": 100,
    "lut_path": "",
    "lut_amount": 0,
    "target_color": default_target_color(),
    "dynamic_hsl": default_dynamic_hsl(),
    "ai_tools": default_ai_tools_params(),
}


@dataclass
class ImageState:
    source_path: Optional[Path] = None
    original_size: Optional[tuple[int, int]] = None
    edit_params: Dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PARAMS))
    active_preset: Optional[str] = None
    adjustment_stack: AdjustmentStack = field(default_factory=lambda: AdjustmentStack(DEFAULT_PARAMS))
    last_export_path: Optional[Path] = None

    def set_source(self, path: str | Path, original_size: Optional[tuple[int, int]] = None) -> None:
        self.source_path = Path(path)
        self.original_size = original_size
        self.reset_params()

    def update_param(self, key: str, value: Any) -> None:
        self.adjustment_stack.set_value(key, value)
        self._sync_edit_params()

    def reset_params(self) -> None:
        self.adjustment_stack = AdjustmentStack(DEFAULT_PARAMS)
        self.edit_params = dict(DEFAULT_PARAMS)
        self.active_preset = None

    def reset_all_adjustments(self) -> None:
        self.adjustment_stack.reset_all()
        self.active_preset = None
        self._sync_edit_params()

    def apply_params(self, params: Dict[str, Any], preset_name: Optional[str] = None) -> None:
        if not params:
            return
        self.adjustment_stack.apply_params(params, action=f"Applied {preset_name}" if preset_name else "Applied Params")
        self.active_preset = preset_name
        self._sync_edit_params()

    def reset_param(self, key: str) -> None:
        if key not in DEFAULT_PARAMS:
            return
        self.adjustment_stack.reset_value(key)
        self._sync_edit_params()

    def set_adjustment_enabled(self, key: str, enabled: bool) -> None:
        self.adjustment_stack.set_enabled(key, enabled)
        self._sync_edit_params()

    def remove_adjustment(self, key: str) -> None:
        self.adjustment_stack.remove(key)
        self._sync_edit_params()

    def active_adjustments(self) -> list[Adjustment]:
        return self.adjustment_stack.active_adjustments()

    def timeline_entries(self) -> list[TimelineEntry]:
        return self.adjustment_stack.timeline_entries()

    def can_undo(self) -> bool:
        return self.adjustment_stack.can_undo()

    def can_redo(self) -> bool:
        return self.adjustment_stack.can_redo()

    def undo(self) -> None:
        if self.adjustment_stack.undo():
            self._sync_edit_params()

    def redo(self) -> None:
        if self.adjustment_stack.redo():
            self._sync_edit_params()

    def _sync_edit_params(self) -> None:
        self.edit_params = self.adjustment_stack.params_with_defaults()
