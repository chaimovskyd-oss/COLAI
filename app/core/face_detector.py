from __future__ import annotations

from typing import List, Optional, Tuple

# (cx, cy, w, h) all in normalized [0..1] coordinates relative to image size
FaceRegion = Tuple[float, float, float, float]

# Re-export so callers can do: from app.core.face_detector import RichFaceDetection
from app.core.face_analysis import RichFaceDetection  # noqa: E402

_MP_KEYPOINT_NAMES = [
    'right_eye', 'left_eye', 'nose_tip',
    'mouth_center', 'right_ear', 'left_ear',
]

try:
    import mediapipe as mp
    import numpy as np
    _MP_AVAILABLE = True
except ImportError:
    _MP_AVAILABLE = False

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

try:
    from retinaface import RetinaFace as _RetinaFace
    _RETINAFACE_AVAILABLE = True
except Exception:
    _RetinaFace = None
    _RETINAFACE_AVAILABLE = False


def is_available() -> bool:
    return _MP_AVAILABLE or _CV2_AVAILABLE


def mediapipe_available() -> bool:
    return _MP_AVAILABLE


def retinaface_available() -> bool:
    return _RETINAFACE_AVAILABLE


def _iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(1e-6, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1e-6, (bx2 - bx1) * (by2 - by1))
    return inter / (area_a + area_b - inter)


def _dedupe_faces(faces: List[RichFaceDetection]) -> List[RichFaceDetection]:
    deduped: List[RichFaceDetection] = []
    for face in sorted(faces, key=lambda f: (f.confidence, f.w * f.h), reverse=True):
        rect = (face.cx - face.w / 2.0, face.cy - face.h / 2.0, face.cx + face.w / 2.0, face.cy + face.h / 2.0)
        if any(_iou(rect, (f.cx - f.w / 2.0, f.cy - f.h / 2.0, f.cx + f.w / 2.0, f.cy + f.h / 2.0)) > 0.35 for f in deduped):
            continue
        deduped.append(face)
    return deduped


def _opencv_face_fallback(image, person_boxes: Optional[List[Tuple[float, float, float, float]]] = None) -> List[RichFaceDetection]:
    if not _CV2_AVAILABLE:
        return []
    try:
        import numpy as np  # noqa: F811

        arr = np.array(image.convert('RGB'))
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        ih, iw = gray.shape[:2]

        frontal = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        profile = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_profileface.xml')

        detections: List[RichFaceDetection] = []

        min_face_px = max(42, int(min(iw, ih) * 0.045))

        def add_rect(x: int, y: int, w: int, h: int, conf: float) -> None:
            if w < min_face_px or h < min_face_px:
                return
            area_ratio = (w * h) / max(1.0, iw * ih)
            if area_ratio < 0.0015 or area_ratio > 0.18:
                return
            cx = (x + w / 2.0) / iw
            cy = (y + h / 2.0) / ih
            detections.append(RichFaceDetection(
                cx=float(min(max(cx, 0.0), 1.0)),
                cy=float(min(max(cy, 0.0), 1.0)),
                w=float(w / iw),
                h=float(h / ih),
                confidence=conf,
                keypoints={},
            ))

        rois = [(0, 0, iw, ih)]
        if person_boxes:
            rois = []
            for left, top, right, bottom in person_boxes:
                x0 = max(0, int((left - 0.22) * iw))
                y0 = max(0, int((top - 0.18) * ih))
                x1 = min(iw, int((right + 0.22) * iw))
                y1 = min(ih, int((bottom + 0.10) * ih))
                if x1 - x0 >= min_face_px and y1 - y0 >= min_face_px:
                    rois.append((x0, y0, x1, y1))
            if not rois:
                rois = [(0, 0, iw, ih)]

        for x0, y0, x1, y1 in rois:
            roi = gray[y0:y1, x0:x1]
            for x, y, w, h in frontal.detectMultiScale(
                roi, scaleFactor=1.06, minNeighbors=6, minSize=(min_face_px, min_face_px)
            ):
                add_rect(int(x0 + x), int(y0 + y), int(w), int(h), 0.52)

            for x, y, w, h in profile.detectMultiScale(
                roi, scaleFactor=1.06, minNeighbors=5, minSize=(min_face_px, min_face_px)
            ):
                add_rect(int(x0 + x), int(y0 + y), int(w), int(h), 0.40)

            mirrored = cv2.flip(roi, 1)
            for x, y, w, h in profile.detectMultiScale(
                mirrored, scaleFactor=1.06, minNeighbors=5, minSize=(min_face_px, min_face_px)
            ):
                x_real = (x1 - x0) - (x + w)
                add_rect(int(x0 + x_real), int(y0 + y), int(w), int(h), 0.40)

        return _dedupe_faces(detections)
    except Exception:
        return []


def detect_faces(image_path: str) -> List[FaceRegion]:
    """Detect faces in an image and return normalized (cx, cy, w, h) tuples."""
    if not _MP_AVAILABLE:
        return []
    try:
        from PIL import Image, ImageOps

        with Image.open(image_path) as img:
            img = ImageOps.exif_transpose(img).convert('RGB')
            rich = detect_faces_detailed_from_image(img)
        return [f.as_tuple() for f in rich]
    except Exception:
        return []


def faces_centroid(faces: List[FaceRegion]) -> Tuple[float, float]:
    """Return the average center of all faces as (cx, cy) in [0..1]."""
    if not faces:
        return 0.5, 0.5
    avg_cx = sum(f[0] for f in faces) / len(faces)
    avg_cy = sum(f[1] for f in faces) / len(faces)
    return float(min(max(avg_cx, 0.0), 1.0)), float(min(max(avg_cy, 0.0), 1.0))


def detect_faces_detailed(image_path: str) -> List[RichFaceDetection]:
    """Detect faces and return RichFaceDetection objects with confidence + keypoints."""
    if not _MP_AVAILABLE:
        return []
    try:
        from PIL import Image, ImageOps

        with Image.open(image_path) as img:
            img = ImageOps.exif_transpose(img).convert('RGB')
            return detect_faces_detailed_from_image(img)
    except Exception:
        return []


def detect_faces_detailed_from_image(image) -> List[RichFaceDetection]:
    """Detect faces from a PIL image / RGB array.

    This keeps the detector reusable for preview-sized smart-crop analysis.
    """
    faces: List[RichFaceDetection] = []
    if _MP_AVAILABLE:
        try:
            import mediapipe as mp  # noqa: F811
            import numpy as np  # noqa: F811

            arr = np.array(image)
            mp_fd = mp.solutions.face_detection

            for model_sel, min_conf in ((0, 0.3), (1, 0.3)):
                with mp_fd.FaceDetection(
                    model_selection=model_sel,
                    min_detection_confidence=min_conf,
                ) as detector:
                    results = detector.process(arr)
                if not results.detections:
                    continue

                for det in results.detections:
                    bb = det.location_data.relative_bounding_box
                    cx = bb.xmin + bb.width / 2.0
                    cy = bb.ymin + bb.height / 2.0
                    conf = float(det.score[0]) if det.score else 0.75

                    kps: dict = {}
                    for i, kp in enumerate(det.location_data.relative_keypoints):
                        if i < len(_MP_KEYPOINT_NAMES):
                            kps[_MP_KEYPOINT_NAMES[i]] = (
                                float(max(0.0, min(kp.x, 1.0))),
                                float(max(0.0, min(kp.y, 1.0))),
                            )

                    faces.append(RichFaceDetection(
                        cx=float(min(max(cx, 0.0), 1.0)),
                        cy=float(min(max(cy, 0.0), 1.0)),
                        w=float(bb.width),
                        h=float(bb.height),
                        confidence=conf,
                        keypoints=kps,
                    ))
                break
        except Exception:
            faces = []

    return _dedupe_faces(faces)


def detect_faces_retina_from_image(image) -> List[RichFaceDetection]:
    """Advanced face detection via RetinaFace when available."""
    if not _RETINAFACE_AVAILABLE:
        return []
    try:
        import numpy as np  # noqa: F811

        arr = np.array(image.convert('RGB'))
        if _CV2_AVAILABLE:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        result = _RetinaFace.detect_faces(arr)
        if not isinstance(result, dict):
            return []

        ih, iw = arr.shape[:2]
        faces: List[RichFaceDetection] = []
        for data in result.values():
            area = data.get('facial_area') or data.get('bbox')
            if not area or len(area) != 4:
                continue
            x1, y1, x2, y2 = area
            x1 = max(0.0, min(float(x1), float(iw)))
            y1 = max(0.0, min(float(y1), float(ih)))
            x2 = max(0.0, min(float(x2), float(iw)))
            y2 = max(0.0, min(float(y2), float(ih)))
            if x2 <= x1 or y2 <= y1:
                continue

            landmarks = data.get('landmarks', {})
            mouth_left = landmarks.get('mouth_left')
            mouth_right = landmarks.get('mouth_right')
            mouth_center = None
            if mouth_left and mouth_right:
                mouth_center = (
                    float((mouth_left[0] + mouth_right[0]) / 2.0 / iw),
                    float((mouth_left[1] + mouth_right[1]) / 2.0 / ih),
                )

            keypoints = {}
            if landmarks.get('left_eye'):
                keypoints['left_eye'] = (
                    float(landmarks['left_eye'][0] / iw),
                    float(landmarks['left_eye'][1] / ih),
                )
            if landmarks.get('right_eye'):
                keypoints['right_eye'] = (
                    float(landmarks['right_eye'][0] / iw),
                    float(landmarks['right_eye'][1] / ih),
                )
            if landmarks.get('nose'):
                keypoints['nose_tip'] = (
                    float(landmarks['nose'][0] / iw),
                    float(landmarks['nose'][1] / ih),
                )
            if mouth_center:
                keypoints['mouth_center'] = mouth_center

            conf = float(data.get('score', 0.85))
            faces.append(RichFaceDetection(
                cx=float(((x1 + x2) / 2.0) / iw),
                cy=float(((y1 + y2) / 2.0) / ih),
                w=float((x2 - x1) / iw),
                h=float((y2 - y1) / ih),
                confidence=conf,
                keypoints=keypoints,
            ))

        return _dedupe_faces(faces)
    except Exception:
        return []


def detect_faces_with_fallback_from_image(
    image,
    person_boxes: Optional[List[Tuple[float, float, float, float]]] = None,
) -> List[RichFaceDetection]:
    """MediaPipe first, then strict OpenCV fallback only when person hints exist."""
    faces = detect_faces_detailed_from_image(image)
    if faces or not person_boxes:
        return faces
    return _opencv_face_fallback(image, person_boxes=person_boxes)


def detect_faces_advanced_from_image(
    image,
    prefer_retina: bool = True,
    person_boxes: Optional[List[Tuple[float, float, float, float]]] = None,
) -> List[RichFaceDetection]:
    """Advanced face detection path for explicit scan mode."""
    if prefer_retina and retinaface_available():
        faces = detect_faces_retina_from_image(image)
        if faces:
            return faces
    return detect_faces_with_fallback_from_image(image, person_boxes=person_boxes)
