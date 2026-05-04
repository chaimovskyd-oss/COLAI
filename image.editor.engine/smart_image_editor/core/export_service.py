from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from smart_image_editor.core.adjustment_pipeline import apply_adjustments


SUPPORTED_EXPORT_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


def export_image(
    source_image: Image.Image,
    params: dict[str, Any],
    output_path: str | Path,
    *,
    quality: int = 95,
    save_sidecar: bool = True,
) -> Path:
    path = Path(output_path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXPORT_SUFFIXES:
        raise ValueError(f"Unsupported export format: {path.suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)

    image = apply_adjustments(source_image, params)
    save_kwargs: dict[str, Any] = {}
    if suffix in {".jpg", ".jpeg", ".webp"}:
        save_kwargs["quality"] = quality
        save_kwargs["optimize"] = True
    image.save(path, **save_kwargs)

    if save_sidecar:
        sidecar = path.with_suffix(path.suffix + ".smartedit.json")
        sidecar.write_text(json.dumps(params, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def export_preview(image: Image.Image, params: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    apply_adjustments(image, params).save(path)
    return path
