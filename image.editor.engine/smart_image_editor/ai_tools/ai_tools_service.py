"""AI Tools Service — central dispatcher for artistic and AI-based effects.

Each entry in EFFECT_REGISTRY describes one effect.  The `apply` callable
receives (image, params_dict) and returns a PIL Image.  If `apply` is None
the effect is a placeholder ("coming soon").

The top-level function `apply_ai_tools_effect` is what the adjustment
pipeline calls.  It reads `ai_tools_params["active_effect"]`, dispatches to
the right handler, and blends the result with the original using the
`strength` value.

Adding a new effect
───────────────────
1. Create a module under  ai_tools/effects/  or  ai_tools/ai/
2. Implement  apply_<name>(image, params) -> Image.Image
3. Register it in EFFECT_REGISTRY below — that's it.
"""

from __future__ import annotations

import hashlib
from typing import Callable

import numpy as np
from PIL import Image

from smart_image_editor.ai_tools.effects.cartoon import apply_cartoon
from smart_image_editor.ai_tools.effects.coloring_page import apply_coloring_page
from smart_image_editor.ai_tools.effects.posterize import apply_posterize
from smart_image_editor.ai_tools.effects.sketch import apply_sketch


# ---------------------------------------------------------------------------
# Registry type
# ---------------------------------------------------------------------------

EffectApplyFn = Callable[[Image.Image, dict], Image.Image]


class EffectSpec:
    __slots__ = ("label", "icon", "category", "apply", "uses_edge_thickness", "description")

    def __init__(
        self,
        label: str,
        icon: str,
        category: str,
        apply: EffectApplyFn | None,
        uses_edge_thickness: bool = False,
        description: str = "",
    ):
        self.label = label
        self.icon = icon
        self.category = category
        self.apply = apply
        self.uses_edge_thickness = uses_edge_thickness
        self.description = description


# ---------------------------------------------------------------------------
# Lazy loader for AnimeGAN (avoids importing onnxruntime at startup)
# ---------------------------------------------------------------------------

def _lazy_animegan(image: Image.Image, params: dict) -> Image.Image:
    from smart_image_editor.ai_tools.ai.animegan import apply_animegan
    return apply_animegan(image, params)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

EFFECT_REGISTRY: dict[str, EffectSpec] = {
    # ── Artistic Effects (non-AI) ────────────────────────────────────────────
    "cartoon": EffectSpec(
        label="Cartoon",
        icon="🎨",
        category="artistic",
        apply=apply_cartoon,
        uses_edge_thickness=True,
        description="Smooth colours with bold outlines",
    ),
    "sketch": EffectSpec(
        label="Sketch",
        icon="✏️",
        category="artistic",
        apply=apply_sketch,
        uses_edge_thickness=True,
        description="Pencil drawing on white paper",
    ),
    "coloring_page": EffectSpec(
        label="Coloring Page",
        icon="📄",
        category="artistic",
        apply=apply_coloring_page,
        uses_edge_thickness=True,
        description="Clean black outlines for hand-colouring",
    ),
    "posterize": EffectSpec(
        label="Posterize",
        icon="🎭",
        category="artistic",
        apply=apply_posterize,
        uses_edge_thickness=False,
        description="Reduce colour levels for a poster look",
    ),
    # ── AI Styles ────────────────────────────────────────────────────────────
    "anime": EffectSpec(
        label="Anime Style",
        icon="🌸",
        category="ai",
        apply=_lazy_animegan,
        uses_edge_thickness=False,
        description="AnimeGAN neural style transfer",
    ),
    "soft_cartoon": EffectSpec(
        label="Soft Cartoon",
        icon="✨",
        category="ai",
        apply=None,          # placeholder — coming soon
        uses_edge_thickness=False,
        description="Coming soon",
    ),
    "comic": EffectSpec(
        label="Comic Style",
        icon="💬",
        category="ai",
        apply=None,          # placeholder — coming soon
        uses_edge_thickness=False,
        description="Coming soon",
    ),
}


# ---------------------------------------------------------------------------
# Default params
# ---------------------------------------------------------------------------

def default_ai_tools_params() -> dict:
    return {
        "active_effect": "",
        "strength": 70,
        "detail": 60,
        "edge_thickness": 40,
    }


# ---------------------------------------------------------------------------
# Preview cache (keyed by effect id + image hash + params)
# ---------------------------------------------------------------------------

_PREVIEW_CACHE: dict[str, Image.Image] = {}
_PREVIEW_CACHE_MAX = 12


def _cache_key(effect_id: str, image: Image.Image, params: dict) -> str:
    img_hash = hashlib.sha1(image.tobytes()).hexdigest()[:16]
    params_str = str(sorted(params.items()))
    params_hash = hashlib.sha1(params_str.encode()).hexdigest()[:12]
    return f"{effect_id}:{img_hash}:{params_hash}"


def _cache_get(key: str) -> Image.Image | None:
    return _PREVIEW_CACHE.get(key)


def _cache_put(key: str, image: Image.Image) -> None:
    if len(_PREVIEW_CACHE) >= _PREVIEW_CACHE_MAX:
        oldest = next(iter(_PREVIEW_CACHE))
        del _PREVIEW_CACHE[oldest]
    _PREVIEW_CACHE[key] = image


def clear_ai_tools_cache() -> None:
    _PREVIEW_CACHE.clear()


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def apply_ai_tools_effect(image: Image.Image, ai_tools_params: dict) -> Image.Image:
    """Apply the active AI Tools effect and blend with original by strength.

    Called by adjustment_pipeline.apply_adjustments() at the final stage.
    Returns *image* unchanged if no effect is active or strength is 0.
    Raises RuntimeError if a model-dependent effect has no model installed.
    """
    active = ai_tools_params.get("active_effect", "")
    if not active:
        return image

    spec = EFFECT_REGISTRY.get(active)
    if spec is None or spec.apply is None:
        return image

    strength = max(0, min(100, int(ai_tools_params.get("strength", 70)))) / 100.0
    if strength == 0:
        return image

    params = {
        "detail": int(ai_tools_params.get("detail", 60)),
        "edge_thickness": int(ai_tools_params.get("edge_thickness", 40)),
    }

    key = _cache_key(active, image, {**params, "s": int(strength * 100)})
    result = _cache_get(key)

    if result is None:
        result = spec.apply(image, params)  # may raise RuntimeError for AI effects
        _cache_put(key, result)

    if strength < 1.0:
        orig = np.asarray(image.convert("RGB")).astype(np.float32)
        fx = np.asarray(result.convert("RGB")).astype(np.float32)
        blended = (orig * (1.0 - strength) + fx * strength).clip(0, 255).astype(np.uint8)
        return Image.fromarray(blended)

    return result


def generate_effect_preview(
    image: Image.Image,
    effect_id: str,
    ai_tools_params: dict,
) -> Image.Image:
    """Generate a full-strength preview of *effect_id* for the hover overlay.

    Does not apply strength blending so the effect is always clearly visible.
    Raises RuntimeError if a model-dependent effect is unavailable.
    """
    spec = EFFECT_REGISTRY.get(effect_id)
    if spec is None or spec.apply is None:
        return image

    params = {
        "detail": int(ai_tools_params.get("detail", 60)),
        "edge_thickness": int(ai_tools_params.get("edge_thickness", 40)),
    }

    key = _cache_key(f"hover:{effect_id}", image, params)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    result = spec.apply(image, params)  # may raise RuntimeError
    _cache_put(key, result)
    return result
