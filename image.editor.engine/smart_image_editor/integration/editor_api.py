from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from smart_image_editor.core.adjustment_pipeline import create_preview, load_image
from smart_image_editor.core.export_service import export_image, export_preview
from smart_image_editor.core.image_state import DEFAULT_PARAMS
from smart_image_editor.integration.result_contract import EditorResult


def process_image_edit(
    image_path: str | Path,
    edit_params: Optional[dict] = None,
    output_path: str | Path | None = None,
    *,
    preview_path: str | Path | None = None,
) -> EditorResult:
    source = Path(image_path)
    params = dict(DEFAULT_PARAMS)
    params.update(edit_params or {})
    image = load_image(str(source))

    exported = None
    if output_path:
        exported = export_image(image, params, output_path)

    preview = None
    if preview_path:
        preview_image = create_preview(image)
        preview = export_preview(preview_image, params, preview_path)

    return EditorResult(
        accepted=True,
        source_path=source,
        exported_path=exported,
        edited_preview_path=preview,
        edit_params=params,
    )


def open_image_editor(
    image_path: str | Path,
    initial_params: Optional[dict] = None,
    mode: str = "standalone_or_embedded",
    output_mode: str = "params_and_preview",
) -> EditorResult:
    """Integration entry point for host apps.

    The current embeddable path is headless and deterministic: host apps can
    pass params and receive an edited preview/result contract. A modal Qt
    embedded dialog can be added later without changing this contract.
    """
    source = Path(image_path)
    params = dict(DEFAULT_PARAMS)
    params.update(initial_params or {})
    preview_path = None
    if output_mode in {"params_and_preview", "preview"}:
        preview_path = Path(tempfile.gettempdir()) / f"{source.stem}_smart_preview.png"
    return process_image_edit(source, params, preview_path=preview_path)
