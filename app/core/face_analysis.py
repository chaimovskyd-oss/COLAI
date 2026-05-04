"""app/core/face_analysis.py — Face scoring, group-aware ROI, and crop evaluation.

Pipeline (detect → rank → ROI → pan → warn):

    1. score_faces(detections)         rank detected faces by importance
    2. classify_image_mode(faces)      PORTRAIT / DUO / GROUP / CROWD / NONE
    3. compute_roi(faces)              normalized bbox covering important faces
    4. roi_to_pan(roi, ...)            convert ROI center to pan_x / pan_y
    5. evaluate_crop(faces, box, ...)  tiered crop warnings per face

Accepts RichFaceDetection objects (from face_detector.detect_faces_detailed)
or plain legacy (cx, cy, w, h) tuples via from_face_regions().

Design principles:
  - No single point of failure: every function returns a safe default on error
  - All thresholds tunable via named constants at the top
  - No heavy dependencies — pure geometry + heuristics
  - Compatible with the existing FaceRegion tuple format
  - Leave room for future: stronger detector, ML scoring, saliency fusion
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Tunable constants — edit these to change scoring / warning behaviour
# ---------------------------------------------------------------------------

# Composite importance score weights (should sum to 1.0)
WEIGHT_SIZE        = 0.40  # absolute face area (normalized)
WEIGHT_CONFIDENCE  = 0.20  # detector confidence score
WEIGHT_CENTRALITY  = 0.25  # closeness to image center
WEIGHT_REL_SIZE    = 0.15  # face size relative to the largest face

# Face importance thresholds  [0..1]
IMPORTANCE_MAJOR   = 0.45  # faces at or above this are "important"
IMPORTANCE_MINOR   = 0.20  # faces below this are background (ignored in warnings)

# Absolute size floor — faces whose normalized area (w*h) is below this are
# treated as minor regardless of score (e.g. tiny crowd/background faces).
# 0.003 ≈ a face that is ~5.5 % of the image width & height.
MIN_AREA_MAJOR     = 0.003

# Image-mode classification thresholds
GROUP_MIN_FACES    = 3     # >= N non-minor faces → GROUP
CROWD_MIN_FACES    = 6     # >= N                → CROWD

# ROI padding — expressed as a fraction of the tight ROI's own dimension
PAD_PORTRAIT_TOP    = 0.35   # generous headroom above the face
PAD_PORTRAIT_BOTTOM = 0.10
PAD_PORTRAIT_SIDE   = 0.20
PAD_DUO             = 0.18   # uniform padding for couples
PAD_GROUP           = 0.12   # tighter uniform padding for groups/crowds

# Crop warning thresholds — fraction of face bounding-box that is inside crop
WARN_MILD_BELOW     = 0.92   # < 92 % visible → mild
WARN_STRONG_BELOW   = 0.65   # < 65 % visible → strong
WARN_CRITICAL_BELOW = 0.40   # < 40 % visible → critical

# Critical keypoint names (MediaPipe order 0-5):
# right_eye, left_eye, nose_tip, mouth_center, right_ear, left_ear
CRITICAL_KEYPOINTS  = frozenset({'right_eye', 'left_eye', 'nose_tip'})

# Assumed confidence when detector does not provide one
DEFAULT_CONFIDENCE  = 0.75


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RichFaceDetection:
    """Face detection result — richer counterpart to the legacy FaceRegion tuple.

    All coordinates are normalized to [0..1] relative to image dimensions.
    When created from legacy tuples (via from_face_regions), confidence is
    set to DEFAULT_CONFIDENCE and keypoints is an empty dict.
    """
    cx: float                                        # center x
    cy: float                                        # center y
    w:  float                                        # bounding-box width
    h:  float                                        # bounding-box height
    confidence: float = DEFAULT_CONFIDENCE
    keypoints: Dict[str, Tuple[float, float]] = field(default_factory=dict)

    # ── Derived geometry ──────────────────────────────────────────────────

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def left(self) -> float:
        return max(0.0, self.cx - self.w / 2.0)

    @property
    def top(self) -> float:
        return max(0.0, self.cy - self.h / 2.0)

    @property
    def right(self) -> float:
        return min(1.0, self.cx + self.w / 2.0)

    @property
    def bottom(self) -> float:
        return min(1.0, self.cy + self.h / 2.0)

    def as_tuple(self) -> Tuple[float, float, float, float]:
        """Convert back to the legacy (cx, cy, w, h) FaceRegion tuple."""
        return (self.cx, self.cy, self.w, self.h)


@dataclass
class FaceInfo:
    """A detected face annotated with a composite importance score."""
    detection:        RichFaceDetection
    importance:       float   # composite [0..1], higher = more important
    size_score:       float
    confidence_score: float
    centrality_score: float
    rel_size_score:   float

    # ── Classification helpers ────────────────────────────────────────────

    @property
    def is_major(self) -> bool:
        return (self.importance >= IMPORTANCE_MAJOR
                and self.detection.area >= MIN_AREA_MAJOR)

    @property
    def is_minor(self) -> bool:
        return (self.importance < IMPORTANCE_MINOR
                or self.detection.area < MIN_AREA_MAJOR)

    # ── Geometry delegates (pass-through to detection) ────────────────────

    @property
    def cx(self)       -> float: return self.detection.cx
    @property
    def cy(self)       -> float: return self.detection.cy
    @property
    def w(self)        -> float: return self.detection.w
    @property
    def h(self)        -> float: return self.detection.h
    @property
    def area(self)     -> float: return self.detection.area
    @property
    def keypoints(self) -> Dict[str, Tuple[float, float]]:
        return self.detection.keypoints


class ImageMode(Enum):
    NONE     = "none"      # no usable faces found
    PORTRAIT = "portrait"  # single dominant face
    DUO      = "duo"       # two important faces (couple / pair)
    GROUP    = "group"     # 3–5 faces (small family / group)
    CROWD    = "crowd"     # 6 + faces


@dataclass
class CropWarning:
    """Warning that a specific face is being cut by the current crop box."""
    severity:      str          # 'mild' | 'strong' | 'critical'
    face:          FaceInfo
    overlap_pct:   float        # fraction of face bbox inside crop [0..1]
    keypoints_cut: List[str]    # landmark names that fell outside the crop
    message:       str          # human-readable one-liner


@dataclass
class CropEvaluation:
    """Full evaluation of a crop rectangle against all detected faces."""
    warnings:     List[CropWarning]  = field(default_factory=list)
    mode:         ImageMode          = ImageMode.NONE
    scored_faces: List[FaceInfo]     = field(default_factory=list)
    roi:          Optional[Tuple[float, float, float, float]] = None  # norm (L,T,R,B)

    # ── Derived properties for UI consumption ────────────────────────────

    @property
    def worst_severity(self) -> Optional[str]:
        if not self.warnings:
            return None
        _order = {'critical': 3, 'strong': 2, 'mild': 1}
        return max(self.warnings, key=lambda w: _order.get(w.severity, 0)).severity

    @property
    def all_major_preserved(self) -> bool:
        """True when no major face has a strong or critical warning."""
        return not any(
            w.severity in ('strong', 'critical') and w.face.is_major
            for w in self.warnings
        )

    @property
    def summary_message(self) -> str:
        """Compact summary suitable for a one-line UI label."""
        if not self.warnings:
            return ''
        crits   = sum(1 for w in self.warnings if w.severity == 'critical')
        strongs = sum(1 for w in self.warnings if w.severity == 'strong')
        milds   = sum(1 for w in self.warnings if w.severity == 'mild')
        parts: List[str] = []
        if crits:   parts.append(f'🚫 Face badly cut ({crits})')
        if strongs: parts.append(f'⚠ Face cut ({strongs})')
        if milds:   parts.append(f'ℹ Face edge ({milds})')
        return '  '.join(parts)

    @property
    def badge_severity(self) -> Optional[str]:
        """Severity to show on the thumbnail badge (None = no badge needed)."""
        return self.worst_severity


# ---------------------------------------------------------------------------
# Conversion helper
# ---------------------------------------------------------------------------

def from_face_regions(
    regions: 'List[Tuple[float, float, float, float]]',
) -> List[RichFaceDetection]:
    """Convert legacy (cx, cy, w, h) FaceRegion tuples → RichFaceDetection.

    No confidence or keypoints available; uses DEFAULT_CONFIDENCE and empty
    keypoints dict.  Scoring still works — just with less precision.
    """
    return [RichFaceDetection(cx=cx, cy=cy, w=w, h=h)
            for cx, cy, w, h in regions]


# ---------------------------------------------------------------------------
# 1. Scoring
# ---------------------------------------------------------------------------

def score_faces(detections: List[RichFaceDetection]) -> List[FaceInfo]:
    """Score and rank detected faces by composite importance.

    Sub-scores:
        size_score       — absolute face area, normalized against a reference
        confidence_score — raw detector confidence (0.75 default when absent)
        centrality_score — 1 − (distance from image center / max distance)
        rel_size_score   — face area ÷ largest face area in this image

    Results are sorted descending by importance (most important first).
    """
    if not detections:
        return []

    max_area = max(d.area for d in detections) or 1e-9
    max_dist = math.sqrt(0.5 ** 2 + 0.5 ** 2)   # ≈ 0.707

    scored: List[FaceInfo] = []
    for det in detections:
        # 1. Size — clamp at 1.0; reference is the largest face (or MIN_AREA_MAJOR)
        ref_area  = max(MIN_AREA_MAJOR, max_area)
        size_s    = min(det.area / ref_area, 1.0)

        # 2. Confidence
        conf_s    = float(max(0.0, min(det.confidence, 1.0)))

        # 3. Centrality
        dist      = math.sqrt((det.cx - 0.5) ** 2 + (det.cy - 0.5) ** 2)
        central_s = max(0.0, 1.0 - dist / max_dist)

        # 4. Relative size vs largest face in image
        rel_s     = det.area / max_area

        importance = min(max(
            WEIGHT_SIZE        * size_s   +
            WEIGHT_CONFIDENCE  * conf_s   +
            WEIGHT_CENTRALITY  * central_s +
            WEIGHT_REL_SIZE    * rel_s,
            0.0), 1.0)

        scored.append(FaceInfo(
            detection        = det,
            importance       = importance,
            size_score       = size_s,
            confidence_score = conf_s,
            centrality_score = central_s,
            rel_size_score   = rel_s,
        ))

    scored.sort(key=lambda f: -f.importance)
    return scored


# ---------------------------------------------------------------------------
# 2. Image-mode classification
# ---------------------------------------------------------------------------

def classify_image_mode(scored_faces: List[FaceInfo]) -> ImageMode:
    """Classify the image based on the number of non-minor faces."""
    non_minor = [f for f in scored_faces if not f.is_minor]
    n = len(non_minor)
    if n == 0:
        return ImageMode.NONE
    if n >= CROWD_MIN_FACES:
        return ImageMode.CROWD
    if n >= GROUP_MIN_FACES:
        return ImageMode.GROUP
    if n == 2:
        return ImageMode.DUO
    return ImageMode.PORTRAIT


# ---------------------------------------------------------------------------
# 3. Region-of-interest computation
# ---------------------------------------------------------------------------

def compute_roi(
    scored_faces: List[FaceInfo],
    *,
    mode: Optional[ImageMode] = None,
) -> Optional[Tuple[float, float, float, float]]:
    """Compute a normalized (left, top, right, bottom) region of interest.

    Selection priority:
        1. All major faces  (importance >= IMPORTANCE_MAJOR)
        2. All non-minor faces  (fallback when no major)
        3. The single most important face  (final fallback)

    Padding is applied according to image mode so the crop has natural
    headroom (portrait) or preserves the whole group (group / crowd).

    Returns None only if scored_faces is empty.
    """
    if not scored_faces:
        return None

    if mode is None:
        mode = classify_image_mode(scored_faces)

    # Choose which faces define the ROI
    candidates = [f for f in scored_faces if f.is_major]
    if not candidates:
        candidates = [f for f in scored_faces if not f.is_minor]
    if not candidates:
        candidates = scored_faces[:1]

    # Tight bounding box of selected faces
    l = min(f.detection.left   for f in candidates)
    t = min(f.detection.top    for f in candidates)
    r = max(f.detection.right  for f in candidates)
    b = max(f.detection.bottom for f in candidates)
    roi_w = max(r - l, 1e-6)
    roi_h = max(b - t, 1e-6)

    # Mode-specific padding
    if mode == ImageMode.PORTRAIT:
        pl = roi_w * PAD_PORTRAIT_SIDE
        pr = roi_w * PAD_PORTRAIT_SIDE
        pt = roi_h * PAD_PORTRAIT_TOP
        pb = roi_h * PAD_PORTRAIT_BOTTOM
    elif mode == ImageMode.DUO:
        pl = pr = roi_w * PAD_DUO
        pt = pb = roi_h * PAD_DUO
    else:   # GROUP, CROWD
        pl = pr = roi_w * PAD_GROUP
        pt = pb = roi_h * PAD_GROUP

    return (
        max(0.0, l - pl),
        max(0.0, t - pt),
        min(1.0, r + pr),
        min(1.0, b + pb),
    )


# ---------------------------------------------------------------------------
# 4. ROI → pan conversion
# ---------------------------------------------------------------------------

def roi_to_pan(
    roi:         Tuple[float, float, float, float],
    img_size:    Tuple[int, int],
    target_size: Tuple[int, int],
    zoom:        float = 1.0,
) -> Tuple[float, float]:
    """Convert a normalized ROI to (pan_x, pan_y) crop values [0..1].

    Centers the crop window on the ROI center.  Always clamped to [0..1]
    so it is safe to use with the standard rectangular crop pipeline.
    """
    l, t, r, b = roi
    roi_cx = (l + r) / 2.0
    roi_cy = (t + b) / 2.0

    img_w, img_h     = img_size
    target_w, target_h = target_size
    target_ratio     = target_w / max(1, target_h)
    img_ratio        = img_w   / max(1, img_h)

    if img_ratio > target_ratio:
        base_w, base_h = int(round(img_h * target_ratio)), img_h
    else:
        base_w, base_h = img_w, int(round(img_w / target_ratio))

    zoom = max(1.0, min(zoom, 5.0))
    cw   = max(1, int(round(base_w / zoom)))
    ch   = max(1, int(round(base_h / zoom)))
    max_x = max(0, img_w - cw)
    max_y = max(0, img_h - ch)

    desired_left = roi_cx * img_w - cw / 2.0
    desired_top  = roi_cy * img_h - ch / 2.0

    pan_x = float(desired_left / max_x) if max_x > 0 else 0.5
    pan_y = float(desired_top  / max_y) if max_y > 0 else 0.5

    return (
        float(min(max(pan_x, 0.0), 1.0)),
        float(min(max(pan_y, 0.0), 1.0)),
    )


# ---------------------------------------------------------------------------
# 5. Crop evaluation  (detect → warn pipeline output)
# ---------------------------------------------------------------------------

def evaluate_crop(
    scored_faces: List[FaceInfo],
    crop_box:     Tuple[int, int, int, int],   # pixel coords (L, T, R, B)
    img_size:     Tuple[int, int],
) -> CropEvaluation:
    """Check how well *crop_box* preserves each non-minor face.

    Warning severity logic:
        critical — face is major AND (eyes/nose cut OR < WARN_CRITICAL_BELOW visible)
        strong   — face is major AND < WARN_STRONG_BELOW visible
                   OR face is non-minor AND < WARN_STRONG_BELOW visible
        mild     — face is < WARN_MILD_BELOW visible (any non-minor face)

    When keypoints are available (from detect_faces_detailed), critical
    warnings are also triggered when eyes or nose fall outside the crop box,
    even if the bounding-box overlap looks acceptable.
    """
    mode = classify_image_mode(scored_faces)
    roi  = compute_roi(scored_faces, mode=mode) if scored_faces else None

    if not scored_faces:
        return CropEvaluation(mode=mode, roi=roi)

    img_w, img_h       = img_size
    c_l, c_t, c_r, c_b = crop_box
    warnings: List[CropWarning] = []

    for face in scored_faces:
        if face.is_minor:
            continue   # skip background / tiny faces

        det = face.detection

        # Face bounding box in pixels
        fx_l = det.left   * img_w
        fx_t = det.top    * img_h
        fx_r = det.right  * img_w
        fx_b = det.bottom * img_h
        face_area = max(1.0, (fx_r - fx_l) * (fx_b - fx_t))

        # Intersection area with crop box
        ix_l = max(fx_l, c_l);  ix_t = max(fx_t, c_t)
        ix_r = min(fx_r, c_r);  ix_b = min(fx_b, c_b)
        if ix_r > ix_l and ix_b > ix_t:
            overlap_pct = (ix_r - ix_l) * (ix_b - ix_t) / face_area
        else:
            overlap_pct = 0.0

        # Keypoint check (only when data is available)
        keypoints_cut: List[str] = []
        if det.keypoints:
            for kp_name, (kpx, kpy) in det.keypoints.items():
                if not (c_l <= kpx * img_w <= c_r and c_t <= kpy * img_h <= c_b):
                    keypoints_cut.append(kp_name)

        has_critical_kp_loss = bool(set(keypoints_cut) & CRITICAL_KEYPOINTS)

        # Severity decision
        if (has_critical_kp_loss and face.is_major) or \
           (face.is_major and overlap_pct < WARN_CRITICAL_BELOW):
            severity = 'critical'
        elif overlap_pct < WARN_STRONG_BELOW:
            severity = 'strong' if face.is_major else 'mild'
        elif overlap_pct < WARN_MILD_BELOW:
            severity = 'mild'
        else:
            continue   # face well-preserved — no warning needed

        # Build human-readable message
        if has_critical_kp_loss and det.keypoints:
            cut_names = ', '.join(
                k.replace('_', ' ')
                for k in keypoints_cut if k in CRITICAL_KEYPOINTS
            )
            msg = f'Crop cuts {cut_names}'
        else:
            msg = f'{int(overlap_pct * 100)}% of face visible in crop'

        warnings.append(CropWarning(
            severity      = severity,
            face          = face,
            overlap_pct   = overlap_pct,
            keypoints_cut = keypoints_cut,
            message       = msg,
        ))

    return CropEvaluation(
        warnings     = warnings,
        mode         = mode,
        scored_faces = scored_faces,
        roi          = roi,
    )


# ---------------------------------------------------------------------------
# Convenience: full pipeline in one call
# ---------------------------------------------------------------------------

def smart_crop_pan(
    detections:  List[RichFaceDetection],
    img_size:    Tuple[int, int],
    target_size: Tuple[int, int],
    zoom:        float = 1.0,
) -> Tuple[float, float]:
    """Group-aware crop pan: score → ROI → pan_x/pan_y.

    Returns (0.5, 0.5) when no faces are provided.
    """
    if not detections:
        return 0.5, 0.5
    scored = score_faces(detections)
    roi    = compute_roi(scored)
    if roi:
        return roi_to_pan(roi, img_size, target_size, zoom)
    return 0.5, 0.5
