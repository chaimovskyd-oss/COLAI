"""
Bridge: Smart Image Editor (Color Lab) ↔ Collage MVP host app.

Adds the image.editor.engine package to sys.path using a path relative to
this file so no absolute user paths are hard-coded.

Public surface:
    open_smart_image_editor(image_path, initial_params, parent) -> dict
"""
from __future__ import annotations

import sys
import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Path bootstrap — find image.editor.engine relative to this bridge file.
# Layout:
#   collage_mvp/
#     app/integrations/smart_image_editor_bridge.py  ← __file__
#     image.editor.engine/                           ← engine root
# ---------------------------------------------------------------------------
_BRIDGE_DIR  = Path(__file__).resolve().parent          # app/integrations
_APP_DIR     = _BRIDGE_DIR.parent                       # app/
_HOST_ROOT   = _APP_DIR.parent                          # collage_mvp/
_ENGINE_ROOT = _HOST_ROOT / "image.editor.engine"       # collage_mvp/image.editor.engine

if _ENGINE_ROOT.exists() and str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

# Edited-image output directory (non-destructive: originals are never touched)
_OUTPUT_DIR = _HOST_ROOT / "edited_images"

_APPLY_STYLE = (
    "QPushButton {"
    "  background: #1a8c35;"
    "  color: white;"
    "  font-weight: bold;"
    "  font-size: 13px;"
    "  border-radius: 5px;"
    "  padding: 0 20px;"
    "}"
    "QPushButton:hover  { background: #22a843; }"
    "QPushButton:pressed { background: #156d28; }"
)

_CANCEL_STYLE = (
    "QPushButton {"
    "  background: #3a3a3a;"
    "  color: #bbb;"
    "  font-size: 12px;"
    "  border-radius: 5px;"
    "  padding: 0 16px;"
    "}"
    "QPushButton:hover { background: #505050; }"
)

# Top-bar Apply button is slightly more compact than the footer one
_APPLY_TOP_STYLE = (
    "QPushButton {"
    "  background: #1a8c35;"
    "  color: white;"
    "  font-weight: bold;"
    "  font-size: 12px;"
    "  border-radius: 4px;"
    "  padding: 0 14px;"
    "  min-height: 26px;"
    "}"
    "QPushButton:hover  { background: #22a843; }"
    "QPushButton:pressed { background: #156d28; }"
)


def _check_engine_available() -> Optional[str]:
    """Return an error message if the engine cannot be imported, else None."""
    if not _ENGINE_ROOT.exists():
        return (
            f"Smart Image Editor engine not found.\n"
            f"Expected folder: {_ENGINE_ROOT}"
        )
    try:
        import smart_image_editor  # noqa: F401
    except ImportError as exc:
        return f"Could not import Smart Image Editor engine:\n{exc}"
    return None


def _make_output_path(source_path: str | Path) -> Path:
    """Generate a timestamped, non-destructive output filename."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    src = Path(source_path)
    ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return _OUTPUT_DIR / f"{src.stem}_edited_{ts}.png"


# ---------------------------------------------------------------------------
# Embedded dialog wrapper around EditorWindow
# ---------------------------------------------------------------------------

class _ColorLabDialog:
    """
    Wraps EditorWindow inside a QDialog so it can be opened modally
    from the host app and return a result when the user accepts or cancels.

    Changes vs. initial version:
    - Dialog is 1240 × 800 (smaller, fits most screens)
    - "Apply & Return to Collage" button is injected into the editor's own
      top toolbar right after the existing "Save Copy" button (green, bold)
    - Footer row also has Apply + Cancel, clearly visible below the editor
    """

    def __init__(self, image_path: str, initial_params: Optional[dict], parent=None):
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QFrame,
        )
        from PySide6.QtCore import Qt
        from smart_image_editor.ui.editor_window import EditorWindow

        self._source_path = Path(image_path)
        self._accepted    = False
        self._result_path : Optional[Path] = None
        self._edit_params : dict = {}

        # --- QDialog container ---
        self._dialog = QDialog(parent)
        self._dialog.setWindowTitle("Color Lab — Smart Image Editor")
        self._dialog.setWindowModality(Qt.ApplicationModal)
        self._dialog.resize(1240, 800)       # ← slightly smaller than standalone

        # --- Embed the full EditorWindow ---
        self._editor = EditorWindow()
        if self._editor.menuBar():
            self._editor.menuBar().hide()

        # --- Inject Apply button into the editor's own top toolbar ---
        # The top bar is the first layout item of the central widget's QVBoxLayout.
        self._btn_apply_top = QPushButton("✔  Apply to Collage")
        self._btn_apply_top.setStyleSheet(_APPLY_TOP_STYLE)
        self._btn_apply_top.setToolTip("Export edited image and return it to the collage")
        self._btn_apply_top.clicked.connect(self._on_accept)
        self._inject_apply_into_topbar()

        # --- Footer: Apply + Cancel ---
        btn_apply_footer = QPushButton("✔  Apply & Return to Collage")
        btn_apply_footer.setFixedHeight(40)
        btn_apply_footer.setStyleSheet(_APPLY_STYLE)
        btn_apply_footer.setToolTip("Export edited image and return it to the collage")

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(40)
        btn_cancel.setStyleSheet(_CANCEL_STYLE)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("color: #555;")

        footer = QHBoxLayout()
        footer.setContentsMargins(12, 4, 12, 4)
        footer.addStretch()
        footer.addWidget(btn_cancel)
        footer.addWidget(btn_apply_footer)

        # --- Assemble dialog layout ---
        root_layout = QVBoxLayout(self._dialog)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._editor.centralWidget(), 1)
        root_layout.addWidget(sep)
        root_layout.addLayout(footer)

        btn_apply_footer.clicked.connect(self._on_accept)
        btn_cancel.clicked.connect(self._dialog.reject)

    def _inject_apply_into_topbar(self) -> None:
        """
        Insert the Apply button into the editor's top QHBoxLayout,
        right after the existing 'Save Copy' button.
        Falls back to appending if the layout structure is unexpected.
        """
        central = self._editor.centralWidget()
        if not central or not central.layout():
            return
        root_vbox = central.layout()           # QVBoxLayout of the editor
        first_item = root_vbox.itemAt(0)
        if not first_item:
            return
        top_layout = first_item.layout()        # QHBoxLayout — the top bar
        if not top_layout:
            return

        save_btn = getattr(self._editor, 'save_btn', None)
        inserted = False
        if save_btn:
            for i in range(top_layout.count()):
                item = top_layout.itemAt(i)
                if item and item.widget() is save_btn:
                    top_layout.insertWidget(i + 1, self._btn_apply_top)
                    inserted = True
                    break
        if not inserted:
            top_layout.addWidget(self._btn_apply_top)

    def _on_accept(self):
        from smart_image_editor.core.export_service import export_image

        if self._editor.original_image is None:
            self._accepted = False
            self._dialog.accept()
            return

        out_path = _make_output_path(self._source_path)
        try:
            exported = export_image(
                self._editor.original_image,
                self._editor.state.edit_params,
                out_path,
            )
            self._result_path = Path(exported)
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self._dialog, "Export failed", str(exc))
            return

        self._edit_params = dict(self._editor.state.edit_params)
        self._accepted    = True
        self._dialog.accept()

    def exec_and_get_result(self) -> dict:
        """Load the image, show the dialog modally, return result dict."""
        self._editor.open_image_path(str(self._source_path))
        self._dialog.exec()

        if self._accepted and self._result_path:
            return {
                "accepted":            True,
                "source_path":         str(self._source_path),
                "edited_preview_path": str(self._result_path),
                "exported_path":       str(self._result_path),
                "edit_params":         self._edit_params,
            }
        return {"accepted": False}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def open_smart_image_editor(
    image_path: str,
    initial_params: Optional[dict] = None,
    parent=None,
) -> dict:
    """
    Open the Smart Image Editor (Color Lab) modally for a single image.

    Returns:
        {
            "accepted": True,
            "source_path": str,
            "edited_preview_path": str,   # path to the exported PNG
            "exported_path": str,
            "edit_params": dict,
        }
        or {"accepted": False} if the user cancelled.

    Raises nothing — all errors are shown via QMessageBox inside the dialog.
    """
    err = _check_engine_available()
    if err:
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(parent, "Color Lab — not available", err)
        except Exception:
            print(f"[ColorLab bridge] {err}")
        return {"accepted": False}

    if not Path(image_path).exists():
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(parent, "Color Lab", f"Image file not found:\n{image_path}")
        except Exception:
            pass
        return {"accepted": False}

    try:
        dlg = _ColorLabDialog(image_path, initial_params, parent)
        return dlg.exec_and_get_result()
    except Exception as exc:
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                parent,
                "Color Lab — error",
                f"An error occurred while opening the editor:\n{exc}",
            )
        except Exception:
            print(f"[ColorLab bridge] {exc}")
        return {"accepted": False}
