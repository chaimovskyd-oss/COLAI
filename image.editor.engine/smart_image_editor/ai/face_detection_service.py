from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image


try:
    import mediapipe as mp
except Exception:  # pragma: no cover - optional runtime dependency
    mp = None


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
    if mp is None or not hasattr(mp, "solutions") or not hasattr(mp.solutions, "face_detection"):
        return None
    try:
        return mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.45)
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
    detector = _face_detector()
    if detector is not None:
        result = detector.process(rgb)
        faces: list[FaceBox] = []
        for detection in result.detections or []:
            box = detection.location_data.relative_bounding_box
            x = max(0, int(box.xmin * width))
            y = max(0, int(box.ymin * height))
            w = min(width - x, int(box.width * width))
            h = min(height - y, int(box.height * height))
            faces.append(FaceBox(x=x, y=y, width=w, height=h, score=float(detection.score[0])))
        return faces

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
    return _face_detector() is not None
