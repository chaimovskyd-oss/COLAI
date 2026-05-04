from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageOps

from app.core import face_detector
from app.models.project import (
    AnalysisBox,
    CropRisk,
    FaceDetectionData,
    ImageAnalysis,
    PersonDetectionData,
    SafeRegions,
)

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:  # pragma: no cover
    cv2 = None
    _CV2_AVAILABLE = False

try:
    from ultralytics import YOLO
    _YOLO_IMPORT_ERROR = ''
except Exception as exc:  # pragma: no cover
    YOLO = None
    _YOLO_IMPORT_ERROR = str(exc)


_YOLO_MODEL = None
_YOLO_MODEL_NAME = 'yolo11n.pt'
_ANALYSIS_MAX_DIM = 960
_FACE_PAD = 0.35
_PERSON_PAD_X = 0.10
_PERSON_PAD_TOP = 0.12
_PERSON_PAD_BOTTOM = 0.08
_EDGE_MARGIN = 0.08
_FACE_STRONG_CUTOFF = 0.82
_FACE_CRITICAL_CUTOFF = 0.60
_GROUP_FACE_REQUIRED = 0.94
_KEYPOINT_EDGE_MARGIN = 0.035
_PERSON_EDGE_REQUIRED = 0.88


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _make_box(left: float, top: float, right: float, bottom: float) -> AnalysisBox:
    return AnalysisBox(
        left=_clamp01(left),
        top=_clamp01(top),
        right=_clamp01(right),
        bottom=_clamp01(bottom),
    )


def _expand_box(box: AnalysisBox, pad_x: float, pad_top: float, pad_bottom: Optional[float] = None) -> AnalysisBox:
    if pad_bottom is None:
        pad_bottom = pad_top
    return _make_box(
        box.left - box.width * pad_x,
        box.top - box.height * pad_top,
        box.right + box.width * pad_x,
        box.bottom + box.height * pad_bottom,
    )


def _union_boxes(boxes: List[AnalysisBox]) -> Optional[AnalysisBox]:
    if not boxes:
        return None
    return _make_box(
        min(b.left for b in boxes),
        min(b.top for b in boxes),
        max(b.right for b in boxes),
        max(b.bottom for b in boxes),
    )


def _preview_image(path: str, rotation: int = 0, max_dim: int = _ANALYSIS_MAX_DIM) -> Image.Image:
    with Image.open(path) as raw:
        img = ImageOps.exif_transpose(raw).convert('RGB')
    if rotation and rotation % 360 != 0:
        img = img.rotate(-rotation, expand=True)
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    return img


def _image_cache_key(path: str, rotation: int) -> str:
    try:
        st = os.stat(path)
        src = f'{path}|{rotation}|{st.st_mtime_ns}|{st.st_size}'
    except OSError:
        src = f'{path}|{rotation}'
    return hashlib.sha1(src.encode('utf-8')).hexdigest()


def mediapipe_available() -> bool:
    return face_detector.mediapipe_available()


def retinaface_available() -> bool:
    return face_detector.retinaface_available()


def yolo_available() -> bool:
    return YOLO is not None and np is not None


def yolo_install_hint() -> str:
    if yolo_available():
        return ''
    return _YOLO_IMPORT_ERROR or 'ultralytics / numpy not installed'


def advanced_face_install_hint() -> str:
    if retinaface_available():
        return ''
    return 'Install retina-face for stronger group face detection'


def _get_yolo_model():
    global _YOLO_MODEL
    if _YOLO_MODEL is not None:
        return _YOLO_MODEL
    if not yolo_available():
        return None
    try:
        _YOLO_MODEL = YOLO(_YOLO_MODEL_NAME)
    except Exception:
        _YOLO_MODEL = None
    return _YOLO_MODEL


def _detect_people(img: Image.Image) -> List[PersonDetectionData]:
    model = _get_yolo_model()
    if model is None or np is None:
        return []
    try:
        arr = np.array(img)
        result = model.predict(arr, verbose=False, classes=[0], conf=0.25)[0]
    except Exception:
        return []

    persons: List[PersonDetectionData] = []
    iw, ih = img.size
    boxes = getattr(result, 'boxes', None)
    if boxes is None:
        return persons

    xyxy = boxes.xyxy.tolist() if getattr(boxes, 'xyxy', None) is not None else []
    confs = boxes.conf.tolist() if getattr(boxes, 'conf', None) is not None else []
    for idx, coords in enumerate(xyxy):
        if len(coords) != 4:
            continue
        left, top, right, bottom = coords
        bbox = _make_box(left / iw, top / ih, right / iw, bottom / ih)
        persons.append(PersonDetectionData(
            bbox=bbox,
            confidence=float(confs[idx]) if idx < len(confs) else 0.0,
            area_ratio=bbox.area,
            center=(bbox.cx, bbox.cy),
        ))
    return persons


def _detect_people_fallback(img: Image.Image) -> List[PersonDetectionData]:
    if not _CV2_AVAILABLE or np is None:
        return []
    try:
        arr = np.array(img.convert('RGB'))
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        ih, iw = bgr.shape[:2]
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        rects, weights = hog.detectMultiScale(
            bgr, winStride=(4, 4), padding=(8, 8), scale=1.03
        )
        persons: List[PersonDetectionData] = []
        for idx, (x, y, w, h) in enumerate(rects):
            bbox = _make_box(x / iw, y / ih, (x + w) / iw, (y + h) / ih)
            confidence = float(weights[idx]) if idx < len(weights) else 0.35
            if confidence < 0.22:
                continue
            if bbox.area < 0.02:
                continue
            persons.append(PersonDetectionData(
                bbox=bbox,
                confidence=confidence,
                area_ratio=bbox.area,
                center=(bbox.cx, bbox.cy),
            ))
        return persons
    except Exception:
        return []


def _detect_faces_from_preview(img: Image.Image) -> List[FaceDetectionData]:
    rich_faces = face_detector.detect_faces_detailed_from_image(img)
    return [
        FaceDetectionData(
            bbox=_make_box(det.left, det.top, det.right, det.bottom),
            confidence=float(det.confidence),
            area_ratio=float(det.area),
            center=(float(det.cx), float(det.cy)),
            keypoints=dict(det.keypoints),
        )
        for det in rich_faces
    ]


def _characterize_image(faces: List[FaceDetectionData], persons: List[PersonDetectionData]) -> Tuple[str, str]:
    if not faces and not persons:
        return 'no people', 'low'
    if len(faces) >= 3 or len(persons) >= 3:
        return 'group photo', 'very sensitive'
    if len(faces) >= 2 and max((f.area_ratio for f in faces), default=0.0) < 0.16:
        return 'group photo', 'very sensitive'
    if len(persons) >= 2 and len(faces) >= 1:
        return 'group photo', 'very sensitive'

    largest_face = max((f.area_ratio for f in faces), default=0.0)
    tallest_person = max(persons, key=lambda p: p.bbox.height, default=None)
    if largest_face >= 0.14:
        return 'close portrait', 'very sensitive'
    if tallest_person:
        if tallest_person.bbox.height >= 0.70:
            return 'full body', 'medium'
        if tallest_person.bbox.height >= 0.42:
            return 'half body', 'medium'
    if faces:
        return 'close portrait', 'very sensitive'
    return 'half body', 'medium'


def _build_safe_regions(faces: List[FaceDetectionData], persons: List[PersonDetectionData]) -> SafeRegions:
    face_boxes = [_expand_box(f.bbox, _FACE_PAD, _FACE_PAD * 1.1, _FACE_PAD * 0.7) for f in faces]
    person_boxes = [_expand_box(p.bbox, _PERSON_PAD_X, _PERSON_PAD_TOP, _PERSON_PAD_BOTTOM) for p in persons]
    face_safe = _union_boxes(face_boxes)
    person_safe = _union_boxes(person_boxes)
    combined = face_safe or person_safe
    if face_safe and person_safe:
        combined = _make_box(
            min(face_safe.left, person_safe.left),
            min(face_safe.top, person_safe.top),
            max(face_safe.right, person_safe.right),
            max(face_safe.bottom, person_safe.bottom),
        )
    return SafeRegions(
        face_safe_region=face_safe,
        person_safe_region=person_safe,
        combined_safe_region=combined,
    )


def analyze_image(
    path: str,
    rotation: int = 0,
    face_backend: str = 'auto',
) -> ImageAnalysis:
    preview = _preview_image(path, rotation=rotation)
    persons = _detect_people(preview)
    if not persons:
        persons = _detect_people_fallback(preview)
    person_boxes = [
        (p.bbox.left, p.bbox.top, p.bbox.right, p.bbox.bottom)
        for p in persons
    ]
    use_retina = face_backend in {'auto', 'retinaface'}
    if face_backend == 'mediapipe':
        rich_faces = face_detector.detect_faces_with_fallback_from_image(preview, person_boxes=person_boxes)
    else:
        rich_faces = face_detector.detect_faces_advanced_from_image(
            preview,
            prefer_retina=use_retina,
            person_boxes=person_boxes,
        )
    faces = [
        FaceDetectionData(
            bbox=_make_box(det.left, det.top, det.right, det.bottom),
            confidence=float(det.confidence),
            area_ratio=float(det.area),
            center=(float(det.cx), float(det.cy)),
            keypoints=dict(det.keypoints),
        )
        for det in rich_faces
    ]
    image_type, crop_tolerance = _characterize_image(faces, persons)
    safe_regions = _build_safe_regions(faces, persons)
    return ImageAnalysis(
        image_id=os.path.basename(path),
        source_path=path,
        image_size=preview.size,
        preview_size=preview.size,
        faces=faces,
        persons=persons,
        image_type=image_type,
        crop_tolerance=crop_tolerance,
        safe_regions=safe_regions,
        analyzed_at=_utc_now(),
        cache_key=_image_cache_key(path, rotation),
        detector_versions={
            'mediapipe': 'enabled' if mediapipe_available() else 'missing',
            'retinaface': 'enabled' if retinaface_available() else 'missing',
            'yolo11': _YOLO_MODEL_NAME if yolo_available() else 'missing',
            'face_backend': face_backend,
        },
        future_hooks={
            'pose_supported': bool(yolo_available()),
            'face_landmarks_supported': bool(mediapipe_available() or retinaface_available()),
            'segmentation_supported': False,
            'saliency_supported': False,
        },
    )


def analysis_to_face_regions(analysis: Optional[ImageAnalysis]) -> List[Tuple[float, float, float, float]]:
    if analysis is None:
        return []
    return [
        (f.bbox.cx, f.bbox.cy, f.bbox.width, f.bbox.height)
        for f in analysis.faces
    ]


def crop_box_from_pan(
    img_size: Tuple[int, int],
    target_size: Tuple[int, int],
    pan_x: float,
    pan_y: float,
    zoom: float,
) -> AnalysisBox:
    from app.utils.image_utils import fit_crop_box

    left, top, right, bottom = fit_crop_box(img_size, target_size, pan_x, pan_y, zoom)
    iw, ih = img_size
    return _make_box(left / iw, top / ih, right / iw, bottom / ih)


def _box_center_to_pan(
    box: AnalysisBox,
    img_size: Tuple[int, int],
    target_size: Tuple[int, int],
    zoom: float,
) -> Tuple[float, float]:
    from app.core.face_analysis import roi_to_pan

    return roi_to_pan((box.left, box.top, box.right, box.bottom), img_size, target_size, zoom)


def _box_intersection_area(a: AnalysisBox, b: AnalysisBox) -> float:
    left = max(a.left, b.left)
    top = max(a.top, b.top)
    right = min(a.right, b.right)
    bottom = min(a.bottom, b.bottom)
    if right <= left or bottom <= top:
        return 0.0
    return (right - left) * (bottom - top)


def _visible_ratio(crop_box: AnalysisBox, protected: Optional[AnalysisBox]) -> float:
    if protected is None or protected.area <= 0.0:
        return 1.0
    return _box_intersection_area(crop_box, protected) / protected.area


def _contains_point(crop_box: AnalysisBox, point: Tuple[float, float], margin: float = 0.0) -> bool:
    x, y = point
    return (
        crop_box.left + margin <= x <= crop_box.right - margin
        and crop_box.top + margin <= y <= crop_box.bottom - margin
    )


def _face_visibility(face: FaceDetectionData, crop_box: AnalysisBox) -> float:
    return _visible_ratio(crop_box, face.bbox)


def _face_keypoint_loss(face: FaceDetectionData, crop_box: AnalysisBox) -> List[str]:
    keypoints_cut: List[str] = []
    for name, point in face.keypoints.items():
        if not _contains_point(crop_box, point, _KEYPOINT_EDGE_MARGIN):
            keypoints_cut.append(name)
    return keypoints_cut


def evaluate_crop_risks(
    analysis: Optional[ImageAnalysis],
    crop_box: AnalysisBox,
) -> List[CropRisk]:
    if analysis is None:
        return []

    warnings: List[CropRisk] = []
    face_safe = analysis.safe_regions.face_safe_region
    person_safe = analysis.safe_regions.person_safe_region

    if face_safe:
        face_visible = _visible_ratio(crop_box, face_safe)
        if face_visible < 0.75:
            warnings.append(CropRisk(
                warning_type='face_cut_off',
                message='A face may be cut off',
                severity='critical',
                suggestion='Try a larger cell or shift the crop.',
            ))
        elif face_visible < 0.92:
            warnings.append(CropRisk(
                warning_type='face_near_edge',
                message='A face is too close to the edge',
                severity='warning',
                suggestion='Shift the crop a little to keep more margin.',
            ))

    if analysis.image_type == 'group photo' and face_safe and _visible_ratio(crop_box, face_safe) < 0.97:
        warnings.append(CropRisk(
            warning_type='group_photo_crop_risk',
            message='Group photo may need a larger cell',
            severity='warning',
            suggestion='Try a wider or larger layout for this image.',
        ))

    if person_safe and _visible_ratio(crop_box, person_safe) < 0.82:
        warnings.append(CropRisk(
            warning_type='important_subject_cut_off',
            message='This crop may cut off part of a person',
            severity='warning',
            suggestion='Try a taller or wider layout for this image.',
        ))
    elif person_safe and _visible_ratio(crop_box, person_safe) < _PERSON_EDGE_REQUIRED:
        warnings.append(CropRisk(
            warning_type='important_subject_cut_off',
            message='Important subject is too close to the edge',
            severity='warning',
            suggestion='Shift the crop or use a roomier layout.',
        ))

    group_faces_at_risk = 0
    for face in analysis.faces:
        visibility = _face_visibility(face, crop_box)
        keypoints_cut = _face_keypoint_loss(face, crop_box)
        critical_features_cut = any(k in {'right_eye', 'left_eye', 'nose_tip', 'mouth_center'} for k in keypoints_cut)

        if visibility < _FACE_CRITICAL_CUTOFF or critical_features_cut:
            warnings.append(CropRisk(
                warning_type='face_cut_off',
                message='A face may be cut off',
                severity='critical',
                suggestion='Try a larger cell or shift the crop.',
            ))
            group_faces_at_risk += 1
            continue

        if visibility < _FACE_STRONG_CUTOFF:
            warnings.append(CropRisk(
                warning_type='face_cut_off',
                message='A face may be cut off',
                severity='warning',
                suggestion='Shift the crop or use a larger cell.',
            ))
            group_faces_at_risk += 1
            continue

        if not _contains_point(crop_box, face.center, _EDGE_MARGIN):
            warnings.append(CropRisk(
                warning_type='face_near_edge',
                message='A face is too close to the edge',
                severity='warning',
                suggestion='Shift the crop so the face has more breathing room.',
            ))
        if analysis.image_type == 'group photo' and visibility < _GROUP_FACE_REQUIRED:
            group_faces_at_risk += 1

    if analysis.image_type == 'group photo' and group_faces_at_risk > 0:
        warnings.append(CropRisk(
            warning_type='group_photo_crop_risk',
            message='Group photo may need a larger cell',
            severity='warning',
            suggestion='Try a larger or less aggressive layout for this image.',
        ))

    unique: Dict[Tuple[str, str], CropRisk] = {}
    for warning in warnings:
        unique[(warning.warning_type, warning.message)] = warning
    return list(unique.values())


def optimize_crop(
    analysis: Optional[ImageAnalysis],
    img_size: Tuple[int, int],
    target_size: Tuple[int, int],
    current_pan: Tuple[float, float],
    current_zoom: float = 1.0,
) -> Tuple[float, float, float, List[CropRisk]]:
    if analysis is None:
        return current_pan[0], current_pan[1], current_zoom, []

    anchors: List[Tuple[float, float]] = [current_pan]
    if analysis.safe_regions.face_safe_region:
        anchors.append(_box_center_to_pan(
            analysis.safe_regions.face_safe_region, img_size, target_size, current_zoom))
    if analysis.safe_regions.combined_safe_region:
        anchors.append(_box_center_to_pan(
            analysis.safe_regions.combined_safe_region, img_size, target_size, current_zoom))
    for face in analysis.faces:
        anchors.append(_box_center_to_pan(face.bbox, img_size, target_size, current_zoom))
    if analysis.persons:
        anchors.append(_box_center_to_pan(
            analysis.persons[0].bbox, img_size, target_size, current_zoom))

    zoom_candidates = [max(1.0, current_zoom), max(1.0, current_zoom * 0.94), max(1.0, current_zoom * 0.88)]
    best = None
    for zoom in zoom_candidates:
        for pan_x, pan_y in anchors:
            crop_box = crop_box_from_pan(img_size, target_size, pan_x, pan_y, zoom)
            face_score = _visible_ratio(crop_box, analysis.safe_regions.face_safe_region)
            person_score = _visible_ratio(crop_box, analysis.safe_regions.person_safe_region)
            combined_score = _visible_ratio(crop_box, analysis.safe_regions.combined_safe_region)
            min_face_visibility = min((_face_visibility(face, crop_box) for face in analysis.faces), default=1.0)
            avg_face_visibility = (
                sum(_face_visibility(face, crop_box) for face in analysis.faces) / max(1, len(analysis.faces))
            )
            balance_penalty = abs(crop_box.cx - 0.5) * 0.08 + abs(crop_box.cy - 0.5) * 0.05
            fill_score = min(1.0, zoom / max(1.0, current_zoom))
            score = (
                face_score * 0.42
                + combined_score * 0.18
                + person_score * 0.08
                + min_face_visibility * 0.22
                + avg_face_visibility * 0.08
                + fill_score * 0.02
                - balance_penalty
            )
            risks = evaluate_crop_risks(analysis, crop_box)
            severe_penalty = sum(0.28 for r in risks if r.severity == 'critical') + sum(0.12 for r in risks if r.severity == 'warning')
            score -= severe_penalty
            if best is None or score > best[0]:
                best = (score, pan_x, pan_y, zoom, risks)

    if best is None:
        return current_pan[0], current_pan[1], current_zoom, []
    return best[1], best[2], best[3], best[4]


def score_cell_fit(analysis: Optional[ImageAnalysis], cell_w: float, cell_h: float) -> float:
    if analysis is None:
        return 0.5
    ratio = cell_w / max(1.0, cell_h)
    score = 0.5
    if analysis.image_type == 'group photo':
        score += 0.25 if ratio >= 1.0 else -0.15
        score += min(0.20, (cell_w * cell_h) / max(1.0, 160000.0))
    elif analysis.image_type == 'full body':
        score += 0.18 if cell_h > cell_w else -0.10
    elif analysis.image_type == 'close portrait':
        score += 0.10 if ratio <= 1.2 else -0.05
    elif analysis.image_type == 'no people':
        score += 0.05

    if analysis.crop_tolerance == 'very sensitive':
        score += min(0.18, (cell_w * cell_h) / max(1.0, 220000.0))
    elif analysis.crop_tolerance == 'low':
        score += 0.04
    return score
