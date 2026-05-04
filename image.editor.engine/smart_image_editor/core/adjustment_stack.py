from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable

ADJUSTMENT_META: Dict[str, tuple[str, str]] = {
    "crop": ("Crop", "advanced"),
    "rotation": ("Rotation", "advanced"),
    "flip_horizontal": ("Flip Horizontal", "advanced"),
    "flip_vertical": ("Flip Vertical", "advanced"),
    "straighten": ("Straighten", "advanced"),
    "exposure": ("Exposure", "light"),
    "brightness": ("Brightness", "light"),
    "contrast": ("Contrast", "light"),
    "highlights": ("Highlights", "light"),
    "shadows": ("Shadows", "light"),
    "whites": ("Whites", "light"),
    "blacks": ("Blacks", "light"),
    "gamma": ("Gamma", "light"),
    "temperature": ("Temperature", "color"),
    "tint": ("Tint", "color"),
    "saturation": ("Saturation", "color"),
    "vibrance": ("Vibrance", "color"),
    "black_white": ("Black & White", "color"),
    "hsl": ("HSL", "color"),
    "sharpness": ("Sharpness", "advanced"),
    "sharpen_radius": ("Sharpen Radius", "advanced"),
    "noise_reduction": ("Noise Reduction", "advanced"),
    "color_noise_reduction": ("Color Noise Reduction", "advanced"),
    "texture": ("Texture", "advanced"),
    "clarity": ("Clarity", "advanced"),
    "vignette_amount": ("Vignette", "effects"),
    "vignette_feather": ("Vignette Feather", "effects"),
    "vignette_midpoint": ("Vignette Midpoint", "effects"),
    "vignette_roundness": ("Vignette Roundness", "effects"),
    "gaussian_blur": ("Gaussian Blur", "effects"),
    "motion_blur": ("Motion Blur", "effects"),
    "motion_angle": ("Motion Angle", "effects"),
    "radial_blur": ("Radial Blur", "effects"),
    "grain_amount": ("Grain", "effects"),
    "grain_size": ("Grain Size", "effects"),
    "print_mode": ("Print Mode", "print"),
    "print_boost_shadows": ("Boost Shadows for Print", "print"),
    "print_reduce_red_skin": ("Reduce Red Skin", "portrait"),
    "print_protect_highlights": ("Protect Highlights", "print"),
    "print_safe_sharpness": ("Print-safe Sharpness", "print"),
    "ai_background_blur": ("Background Blur", "effects"),
    "ai_background_darkening": ("Darken Background", "effects"),
    "ai_subject_enhance": ("Subject Enhance", "portrait"),
    "ai_face_brighten": ("Face Brighten", "portrait"),
    "ai_skin_tone_protection": ("Skin Tone Protection", "portrait"),
    "ai_face_restore": ("Face Restore", "portrait"),
    "ai_upscale_factor": ("Upscale Factor", "advanced"),
    "ai_upscale_strength": ("Upscale Strength", "advanced"),
    "lut_path": ("LUT Path", "color"),
    "lut_amount": ("LUT Amount", "color"),
    "target_color": ("Target Color", "color"),
}


@dataclass
class Adjustment:
    id: str
    label: str
    value: Any
    default: Any
    enabled: bool = True
    category: str = "advanced"
    timestamp: float = field(default_factory=time.time)

    @property
    def is_default(self) -> bool:
        return self.value == self.default

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "value": deepcopy(self.value),
            "default": deepcopy(self.default),
            "enabled": self.enabled,
            "category": self.category,
            "timestamp": self.timestamp,
        }


@dataclass
class TimelineEntry:
    action: str
    tool: str | None = None
    value: Any = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "tool": self.tool,
            "value": deepcopy(self.value),
            "timestamp": self.timestamp,
        }


class AdjustmentStack:
    def __init__(self, defaults: Dict[str, Any] | None = None):
        self.defaults = deepcopy(defaults or {})
        self.adjustments: Dict[str, Adjustment] = {}
        self.timeline: list[TimelineEntry] = []
        self.undo_stack: list[Dict[str, Dict[str, Any]]] = []
        self.redo_stack: list[Dict[str, Dict[str, Any]]] = []
        for key, default in self.defaults.items():
            self._ensure(key)

    def set_value(self, key: str, value: Any, *, action: str | None = None, record: bool = True) -> None:
        adj = self._ensure(key)
        if adj.value == value and adj.enabled:
            return
        if record:
            self._push_undo()
        adj.value = deepcopy(value)
        adj.enabled = True
        adj.timestamp = time.time()
        if record:
            self.redo_stack.clear()
            self.timeline.append(TimelineEntry(action or f"Changed {adj.label}", key, deepcopy(value)))

    def apply_params(self, params: Dict[str, Any], *, action: str = "Applied Params", record: bool = True) -> None:
        if not params:
            return
        if record:
            self._push_undo()
        for key, value in params.items():
            adj = self._ensure(key)
            adj.value = deepcopy(value)
            adj.enabled = True
            adj.timestamp = time.time()
        if record:
            self.redo_stack.clear()
            self.timeline.append(TimelineEntry(action, None, deepcopy(params)))

    def reset_value(self, key: str, *, record: bool = True) -> None:
        adj = self._ensure(key)
        if adj.value == adj.default and adj.enabled:
            return
        if record:
            self._push_undo()
        adj.value = deepcopy(adj.default)
        adj.enabled = True
        adj.timestamp = time.time()
        if record:
            self.redo_stack.clear()
            self.timeline.append(TimelineEntry(f"Reset {adj.label}", key, deepcopy(adj.default)))

    def set_enabled(self, key: str, enabled: bool, *, record: bool = True) -> None:
        adj = self._ensure(key)
        if adj.enabled == enabled:
            return
        if record:
            self._push_undo()
        adj.enabled = enabled
        adj.timestamp = time.time()
        if record:
            self.redo_stack.clear()
            self.timeline.append(TimelineEntry(("Enabled " if enabled else "Disabled ") + adj.label, key, enabled))

    def remove(self, key: str, *, record: bool = True) -> None:
        adj = self._ensure(key)
        if record:
            self._push_undo()
        adj.value = deepcopy(adj.default)
        adj.enabled = False
        adj.timestamp = time.time()
        if record:
            self.redo_stack.clear()
            self.timeline.append(TimelineEntry(f"Removed {adj.label}", key, None))

    def reset_all(self, *, record: bool = True) -> None:
        if record:
            self._push_undo()
        for adj in self.adjustments.values():
            adj.value = deepcopy(adj.default)
            adj.enabled = True
            adj.timestamp = time.time()
        if record:
            self.redo_stack.clear()
            self.timeline.append(TimelineEntry("Reset All", None, None))

    def active_params(self) -> Dict[str, Any]:
        return {
            key: deepcopy(adj.value)
            for key, adj in self.adjustments.items()
            if adj.enabled and adj.value != adj.default
        }

    def params_with_defaults(self) -> Dict[str, Any]:
        params = deepcopy(self.defaults)
        params.update(self.active_params())
        return params

    def active_adjustments(self) -> list[Adjustment]:
        return sorted(
            [adj for adj in self.adjustments.values() if not adj.is_default],
            key=lambda adj: adj.timestamp,
            reverse=True,
        )

    def timeline_entries(self) -> list[TimelineEntry]:
        return list(reversed(self.timeline[-100:]))

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.snapshot())
        self.restore(self.undo_stack.pop())
        self.timeline.append(TimelineEntry("Undo", None, None))
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.snapshot())
        self.restore(self.redo_stack.pop())
        self.timeline.append(TimelineEntry("Redo", None, None))
        return True

    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        return {key: adj.to_dict() for key, adj in self.adjustments.items()}

    def restore(self, snapshot: Dict[str, Dict[str, Any]]) -> None:
        self.adjustments = {}
        for key, data in snapshot.items():
            self.adjustments[key] = Adjustment(**deepcopy(data))
        for key in self.defaults:
            self._ensure(key)

    def _push_undo(self) -> None:
        self.undo_stack.append(self.snapshot())
        if len(self.undo_stack) > 100:
            self.undo_stack.pop(0)

    def _ensure(self, key: str) -> Adjustment:
        if key not in self.adjustments:
            default = deepcopy(self.defaults.get(key))
            label, category = ADJUSTMENT_META.get(key, (_label_from_key(key), "advanced"))
            self.adjustments[key] = Adjustment(key, label, default, default, True, category)
        return self.adjustments[key]


def _label_from_key(key: str) -> str:
    return key.replace("_", " ").title()
