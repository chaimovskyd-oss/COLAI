from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image


try:
    from insightface.app import FaceAnalysis as _FaceAnalysis
    _INSIGHTFACE_AVAILABLE = True
except ImportError:  # pragma: no cover - optional runtime dependency
    _FaceAnalysis = None
    _INSIGHTFACE_AVAILABLE = False


@dataclass(frozen=True)
class FaceBox:
    x: int
    y: int
    width: int
    height: int
    score: float

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


@lru_cache(maxsize=1)
def _face_detector():
    if not _INSIGHTFACE_AVAILABLE:
        return None
    try:
        try:
            import onnxruntime as _ort
            providers = (
                ['CUDAExecutionProvider']
                if 'CUDAExecutionProvider' in _ort.get_available_providers()
                else ['CPUExecutionProvider']
            )
        except Exception:
            providers = ['CPUExecutionProvider']
        ctx_id = 0 if providers[0] == 'CUDAExecutionProvider' else -1
        app = _FaceAnalysis(name='buffalo_l', root='./models', providers=providers)
        app.prepare(ctx_id=ctx_id, det_size=(640, 640))
        return app
    except Exception:
        return None


@lru_cache(maxsize=1)
def _haar_detector():
    path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(path)
    return None if detector.empty() else detector


def detect_faces(image: Image.Image) -> list[FaceBox]:
    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    image_area = max(1, width * height)

    app = _face_detector()
    if app is not None:
        try:
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            raw = app.get(bgr)
            faces: list[FaceBox] = []
            for face in raw:
                score = float(face.det_score)
                if score < 0.6:
                    continue
                x1, y1, x2, y2 = (float(v) for v in face.bbox)
                face_area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
                if face_area / image_area < 0.02:
                    continue
                x = max(0, int(x1))
                y = max(0, int(y1))
                w = min(width - x, int(x2 - x1))
                h = min(height - y, int(y2 - y1))
                if w > 0 and h > 0:
                    faces.append(FaceBox(x=x, y=y, width=w, height=h, score=score))
            return faces
        except Exception:
            pass

    # Haar cascade fallback
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    haar = _haar_detector()
    if haar is None:
        return []
    found = haar.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(32, 32))
    return [FaceBox(int(x), int(y), int(w), int(h), 0.5) for x, y, w, h in found]


def face_mask(image: Image.Image, padding: float = 0.35) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    mask = np.zeros((height, width), dtype=np.float32)
    for face in detect_faces(image):
        pad_x = int(face.width * padding)
        pad_y = int(face.height * padding)
        x1 = max(0, face.x - pad_x)
        y1 = max(0, face.y - pad_y)
        x2 = min(width, face.x + face.width + pad_x)
        y2 = min(height, face.y + face.height + pad_y)
        center = ((x1 + x2) // 2, (y1 + y2) // 2)
        axes = (max(1, (x2 - x1) // 2), max(1, (y2 - y1) // 2))
        cv2.ellipse(mask, center, axes, 0, 0, 360, 1.0, -1)
    if mask.max() > 0:
        mask = cv2.GaussianBlur(mask, (0, 0), 9)
    return np.clip(mask, 0, 1)


def has_mediapipe_face_detection() -> bool:
    """Kept for backward compatibility — returns True when InsightFace is available."""
    return _face_detector() is not None
