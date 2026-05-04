from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image


@lru_cache(maxsize=8)
def load_cube_lut(path: str) -> tuple[int, np.ndarray] | None:
    lut_path = Path(path)
    if not lut_path.exists():
        return None
    size = None
    values: list[list[float]] = []
    for raw_line in lut_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0].upper() == "LUT_3D_SIZE" and len(parts) >= 2:
            size = int(parts[1])
            continue
        if parts[0].upper() in {"TITLE", "DOMAIN_MIN", "DOMAIN_MAX"}:
            continue
        if len(parts) >= 3:
            try:
                values.append([float(parts[0]), float(parts[1]), float(parts[2])])
            except ValueError:
                continue
    if not size or len(values) < size**3:
        return None
    data = np.asarray(values[: size**3], dtype=np.float32).reshape((size, size, size, 3))
    return size, np.clip(data, 0, 1)


def apply_cube_lut(image: Image.Image, path: str, amount: int = 100) -> Image.Image:
    loaded = load_cube_lut(path)
    if loaded is None or amount <= 0:
        return image
    size, lut = loaded
    arr = np.asarray(image.convert("RGB")).astype(np.float32) / 255.0
    idx = np.clip(np.round(arr * (size - 1)).astype(np.int32), 0, size - 1)
    graded = lut[idx[:, :, 0], idx[:, :, 1], idx[:, :, 2]]
    blend = max(0.0, min(1.0, amount / 100.0))
    out = arr * (1 - blend) + graded * blend
    return Image.fromarray(np.clip(out * 255, 0, 255).astype(np.uint8))
