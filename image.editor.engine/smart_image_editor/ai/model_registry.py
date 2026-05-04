from __future__ import annotations

from pathlib import Path
from urllib.request import urlretrieve


MODEL_DIR = Path(__file__).resolve().parents[1] / "models"

REALESRGAN_X4PLUS = {
    "name": "RealESRGAN_x4plus",
    "filename": "RealESRGAN_x4plus.pth",
    "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
}

GFPGAN_V14 = {
    "name": "GFPGANv1.4",
    "filename": "GFPGANv1.4.pth",
    "url": "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.4/GFPGANv1.4.pth",
}


def model_path(model: dict) -> Path:
    return MODEL_DIR / model["filename"]


def ensure_model(model: dict, *, auto_download: bool = True) -> Path | None:
    path = model_path(model)
    if path.exists():
        return path
    if not auto_download:
        return None
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        urlretrieve(model["url"], path)
    except Exception:
        if path.exists():
            path.unlink(missing_ok=True)
        return None
    return path if path.exists() else None


def available_models() -> dict[str, bool]:
    return {
        REALESRGAN_X4PLUS["name"]: model_path(REALESRGAN_X4PLUS).exists(),
        GFPGAN_V14["name"]: model_path(GFPGAN_V14).exists(),
    }
