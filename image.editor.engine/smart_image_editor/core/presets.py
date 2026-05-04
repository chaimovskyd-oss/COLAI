import json
from pathlib import Path
from typing import Any, Dict, List

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "presets.json"


class PresetService:
    def __init__(self, path: Path = DATA_PATH):
        self.path = path

    def load_presets(self) -> List[Dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def get_by_name(self, name: str) -> Dict | None:
        for preset in self.load_presets():
            if preset.get("name") == name:
                return preset
        return None


def blend_preset_params(defaults: Dict[str, Any], preset_params: Dict[str, Any], intensity: int) -> Dict[str, Any]:
    amount = max(0.0, min(1.0, intensity / 100.0))
    blended: Dict[str, Any] = {}
    for key, value in preset_params.items():
        base = defaults.get(key)
        if isinstance(value, (int, float)) and isinstance(base, (int, float)):
            blended[key] = base + (value - base) * amount
            if isinstance(value, int) and not isinstance(value, bool):
                blended[key] = int(round(blended[key]))
        elif isinstance(value, dict):
            blended[key] = _blend_nested_dict(base if isinstance(base, dict) else {}, value, amount)
        elif isinstance(value, bool):
            blended[key] = value if amount >= 0.5 else bool(base)
        else:
            blended[key] = value if amount > 0 else base
    return blended


def _blend_nested_dict(base: Dict[str, Any], target: Dict[str, Any], amount: float) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in target.items():
        base_value = base.get(key, {})
        if isinstance(value, dict):
            result[key] = _blend_nested_dict(base_value if isinstance(base_value, dict) else {}, value, amount)
        elif isinstance(value, (int, float)) and isinstance(base_value, (int, float)):
            result[key] = base_value + (value - base_value) * amount
            if isinstance(value, int) and not isinstance(value, bool):
                result[key] = int(round(result[key]))
        else:
            result[key] = value if amount > 0 else base_value
    return result
