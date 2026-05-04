from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any

from PIL import Image


class PreviewCache:
    def __init__(self, max_items: int = 20):
        self.max_items = max(1, max_items)
        self._items: OrderedDict[str, Image.Image] = OrderedDict()

    def make_key(self, source_path: Path | None, params: dict[str, Any], preview_size: tuple[int, int] | None) -> str:
        payload = {
            "source": str(source_path) if source_path else None,
            "params": params,
            "preview_size": preview_size,
        }
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Image.Image | None:
        image = self._items.get(key)
        if image is None:
            return None
        self._items.move_to_end(key)
        return image.copy()

    def put(self, key: str, image: Image.Image) -> None:
        self._items[key] = image.copy()
        self._items.move_to_end(key)
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)
