"""얼굴 랜드마크 (A4/A5 공통 기반). MediaPipe FaceLandmarker(Tasks API) 사용. 미설치 시 None 반환.
부위 폴리곤은 treatments.yaml 의 mask_region 키로 조회.

⚠ 옛 `mp.solutions.face_mesh` 는 mediapipe 1.x 에 **없다**(2026-09-08 실측: 설치본 1.0.1 의
  최상위 속성은 Image·ImageFormat·tasks 셋뿐). 그대로 두면 셀카 배치가 검수 첫 단계에서
  AttributeError 로 죽는다 — 생성 2콜을 다 쓰고 나서 죽으므로 돈이 나간 뒤에 실패한다.
  Tasks API 는 모델 파일(.task)이 따로 필요해서 없으면 한 번 내려받는다.
"""
import os
import threading
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task")
# 모델은 코드가 아니라 캐시다 — 리포에 커밋하지 말고 여기(홈 캐시)에 둔다.
MODEL_PATH = Path(os.getenv("BNA_FACE_LANDMARKER",
                            Path.home() / ".cache" / "bna" / "face_landmarker.task"))
_det = None
_lock = threading.Lock()   # 배치가 워커 풀로 도는데 create_from_options 를 동시에 부르면 안 된다

# MediaPipe FaceMesh 468 인덱스 기준 부위 폴리곤 (초안, 스파이크에서 시각 확인 후 조정)
REGIONS = {
    "nasolabial":     [129, 203, 206, 216, 212, 57, 186, 92, 165, 167, 164, 393, 391, 322, 410, 287, 432, 436, 426, 423, 358, 327, 326, 2, 97, 98],
    "cheeks":         [116, 117, 118, 119, 120, 100, 142, 203, 206, 216, 212, 214, 210, 169, 135, 138, 215, 177, 137, 227, 34, 143, 111, 345, 346, 347, 348, 349, 329, 371, 423, 426, 436, 432, 434, 430, 394, 364, 367, 435, 401, 366, 447, 264, 372, 340],
    "cheeks_nose":    "cheeks+nose",
    "nose":           [168, 6, 197, 195, 5, 4, 1, 19, 94, 2, 326, 327, 294, 278, 344, 440, 275, 4, 45, 220, 115, 48, 64, 98, 97],
    "philtrum":       [2, 97, 98, 164, 167, 165, 92, 186, 57, 0, 267, 393, 391, 322, 410, 287, 326, 327],
    "jawline_midface":[234, 93, 132, 58, 172, 136, 150, 149, 176, 148, 152, 377, 400, 378, 379, 365, 397, 288, 361, 323, 454, 356, 389, 251, 284, 332, 297, 338, 10, 109, 67, 103, 54, 21, 162, 127],
    "full_face_skin": [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109],
    # 목: 얼굴 랜드마크에 목이 없다. 턱선(왼→오른)을 얼굴 높이의 NECK_DROP 만큼 아래로 내린 사다리꼴 (목주름 필러용, 2026-09-09)
    "neck":           "derived:jaw_down",
}
JAW_LINE = [132, 58, 172, 136, 150, 149, 176, 148, 152, 377, 400, 378, 379, 365, 397, 288, 361]
NECK_DROP = 0.55          # 턱선에서 아래로 내릴 길이 (얼굴 높이 = 이마 10 ↔ 턱 152 거리 대비)


def neck_polygon(pts: np.ndarray) -> list:
    """턱선을 따라 내려간 목 영역 폴리곤. 위변 = 턱선, 아래변 = 턱선을 **얼굴 축 방향**으로 평행이동.

    ⚠ 이미지 아래(+y)로 내리면 머리가 기울어진 셀카에서 밴드가 목을 벗어난다 —
      2026-09-09 티모 실측(합성 모형): 기울기 10도 IoU 78% · 20도 62% · 30도 48%.
      셀카는 기울기 10~30도가 흔하다. 얼굴 축(이마 10 → 턱 152)을 쓰면 기울기와 무관하다."""
    top_pt = np.asarray(pts[10], dtype=float); chin = np.asarray(pts[152], dtype=float)
    axis = chin - top_pt
    face_h = float(np.linalg.norm(axis))
    if face_h <= 0:                      # 랜드마크가 겹쳐 축이 없으면 예전처럼 아래로 (죽지는 않게)
        axis = np.array([0.0, 1.0]); face_h = 1.0
    step = axis / face_h * (face_h * NECK_DROP)
    top = [tuple(map(float, pts[i])) for i in JAW_LINE]
    bottom = [(x + float(step[0]), y + float(step[1])) for x, y in reversed(top)]
    return top + bottom
LEFT_EYE, RIGHT_EYE, NOSE_TIP, MOUTH_L, MOUTH_R = 33, 263, 1, 61, 291


def _model():
    """FaceLandmarker 를 한 번만 만들어 재사용한다. 미설치·모델 확보 실패면 None."""
    global _det
    if _det is not None:
        return _det
    with _lock:
        if _det is not None:
            return _det
        try:
            from mediapipe.tasks import python as mpp
            from mediapipe.tasks.python import vision
        except ImportError:
            return None
        try:
            if not MODEL_PATH.exists():
                MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
                tmp = MODEL_PATH.with_suffix(".part")      # 중간에 끊긴 파일이 '있는 모델'로 남지 않게
                urllib.request.urlretrieve(MODEL_URL, tmp)
                tmp.replace(MODEL_PATH)
            _det = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                base_options=mpp.BaseOptions(model_asset_path=str(MODEL_PATH)),
                num_faces=1, output_face_blendshapes=False))
        except Exception:
            return None      # 랜드마크는 보조 축이다 — 없다고 배치를 죽이지 않는다(상위가 None 을 다룬다)
    return _det


def detect(img: Image.Image):
    """(N,2) 픽셀 좌표 배열 또는 None(미검출/미설치)."""
    try:
        import mediapipe as mp
    except ImportError:
        return None
    det = _model()
    if det is None:
        return None
    rgb = img.convert("RGB")
    w, h = rgb.size
    res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(rgb)))
    if not res.face_landmarks:
        return None
    return np.array([[p.x * w, p.y * h] for p in res.face_landmarks[0]])


def region_mask(img: Image.Image, pts: np.ndarray, region: str, feather: int = 12) -> Image.Image:
    """시술 부위 마스크 (L 모드, 흰색=편집 허용). 경계는 feather 로 부드럽게."""
    from PIL import ImageFilter
    mask = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(mask)
    keys = ["cheeks", "nose"] if region == "cheeks_nose" else [region]
    for k in keys:
        poly = neck_polygon(pts) if k == "neck" else [tuple(pts[i]) for i in REGIONS[k]]
        d.polygon(poly, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(feather))


def composite_outside_mask(before: Image.Image, after: Image.Image, mask: Image.Image) -> Image.Image:
    """마스크 밖은 Before 원본 픽셀로 강제 복원 (임상 동일 조건 픽셀 보장)."""
    return Image.composite(after.convert("RGB"), before.convert("RGB"), mask)


def key_points(pts: np.ndarray) -> dict:
    return {"eye_l": pts[LEFT_EYE], "eye_r": pts[RIGHT_EYE], "nose": pts[NOSE_TIP],
            "mouth_l": pts[MOUTH_L], "mouth_r": pts[MOUTH_R]}
