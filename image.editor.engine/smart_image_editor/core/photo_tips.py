import json
from pathlib import Path
from typing import Dict, List, Optional

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "photo_tips.json"


class PhotoTipsService:
    def __init__(self, path: Path = DATA_PATH):
        self.path = path
        self._tips: List[Dict] = []

    def load_tips(self) -> List[Dict]:
        if not self._tips:
            self._tips = json.loads(self.path.read_text(encoding="utf-8-sig"))
        return self._tips

    def get_categories(self) -> List[str]:
        return sorted({tip["category"] for tip in self.load_tips()})

    def get_tips_by_category(self, category: str) -> List[Dict]:
        return [tip for tip in self.load_tips() if tip["category"] == category]

    def get_tip_by_id(self, tip_id: str) -> Optional[Dict]:
        return next((tip for tip in self.load_tips() if tip["id"] == tip_id), None)

    def get_suggested_params(self, tip_id: str) -> Dict:
        tip = self.get_tip_by_id(tip_id)
        if not tip:
            return {}
        return tip.get("future_auto_fix", {}).get("params", {})
