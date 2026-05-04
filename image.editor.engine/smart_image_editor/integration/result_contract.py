from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class EditorResult:
    accepted: bool
    source_path: Optional[Path] = None
    exported_path: Optional[Path] = None
    edited_preview_path: Optional[Path] = None
    edit_params: Dict[str, Any] | None = None
    preset_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "source_path": str(self.source_path) if self.source_path else None,
            "exported_path": str(self.exported_path) if self.exported_path else None,
            "edited_preview_path": str(self.edited_preview_path) if self.edited_preview_path else None,
            "edit_params": self.edit_params or {},
            "preset_name": self.preset_name,
        }
