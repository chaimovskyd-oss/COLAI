from __future__ import annotations

import numpy as np
from PIL import Image

from smart_image_editor.ai.background_blur_service import subject_coverage
from smart_image_editor.ai.face_detection_service import detect_faces


def suggest_smart_auto_fix(image: Image.Image) -> dict:
    arr = np.asarray(image.convert("RGB")).astype(np.float32)
    lum = arr.mean(axis=2)
    mean = float(lum.mean())
    p1, p99 = np.percentile(lum, [1, 99])
    spread = float(p99 - p1)
    params: dict = {}

    if mean < 92:
        params.update({"exposure": 0.28, "shadows": 24, "contrast": 6})
    elif mean > 180:
        params.update({"exposure": -0.22, "highlights": -32, "whites": -12})

    if spread < 95:
        params["contrast"] = max(int(params.get("contrast", 0)), 14)
        params["clarity"] = max(int(params.get("clarity", 0)), 6)

    hsv_sat_proxy = arr.max(axis=2) - arr.min(axis=2)
    if float(hsv_sat_proxy.mean()) < 28:
        params["vibrance"] = max(int(params.get("vibrance", 0)), 18)
    elif float(hsv_sat_proxy.mean()) > 82:
        params["saturation"] = min(int(params.get("saturation", 0)), -8)

    faces = detect_faces(image)
    if faces:
        face_lums = []
        for face in faces:
            crop = lum[face.y : face.y + face.height, face.x : face.x + face.width]
            if crop.size:
                face_lums.append(float(crop.mean()))
        if face_lums and min(face_lums) < 115:
            params["ai_face_brighten"] = max(int(params.get("ai_face_brighten", 0)), 24)
            params["shadows"] = max(int(params.get("shadows", 0)), 18)
        params["ai_skin_tone_protection"] = max(int(params.get("ai_skin_tone_protection", 0)), 12)

    coverage = subject_coverage(image)
    if 0.08 < coverage < 0.55 and faces:
        params["ai_subject_enhance"] = max(int(params.get("ai_subject_enhance", 0)), 12)

    if not params:
        params = {"vibrance": 8, "contrast": 5}
    return params
