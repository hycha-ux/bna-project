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
    # 눈꺼풀·눈가 필러 (2026-09-11). 눈 주위 한 바퀴 = 눈썹 아래 ~ 눈밑 고랑(애교살 아래)까지.
    # 좌우가 따로 있어야 한다 — 한 폴리곤으로 이으면 미간이 통째로 편집 허용이 된다.
    # ⚠ 초안이다(다른 부위와 같다). 마스크는 임상 모드 합성·구조 검수에 쓰이므로
    #   좁으면 효과가 잘리고 넓으면 눈 자체가 바뀐다 — 첫 실회차 컷으로 눈 확인이 필요하다.
    "periorbital_l":  [70, 63, 105, 66, 107, 55, 193, 245, 128, 121, 120, 119, 118, 117, 111, 143, 156],
    "periorbital_r":  [300, 293, 334, 296, 336, 285, 417, 465, 357, 350, 349, 348, 347, 346, 340, 372, 383],
    "eye_area":       "periorbital_l+periorbital_r",
    # 마리오네트(입꼬리 → 턱 쪽 세로 주름) — 팔자 필러와 한 시술이다 (2026-09-17 연서님 "마리오네트 부위도 함께").
    #   실사진(강남언니 온볼라썸 #1·#117·#118)의 태그가 전부 '팔자주름필러 + 마리오네트필러'이고, 직후 패치도
    #   입꼬리 높이 바깥 볼(192/416 근처)에 앉는다 — 종전 nasolabial 폴리곤은 입꼬리(57/287)에서 끝나 셀카 모드에선
    #   마리오네트 변화와 패치가 composite_outside_mask 로 **지워졌다**. 안쪽 변은 아랫입술 바로 밑 선(43·106·182)이라
    #   입술은 빠지고, 바깥 변은 턱선(172·136·150…)까지. 턱 끝 가운데(152)는 뺐다.
    #   좌우가 따로다 — 하나로 이으면 턱 가운데가 편집 허용이 된다. 폴리곤은 레퍼런스 2장(정면·3/4)에 그려 확인했다.
    "marionette_l":   [57, 43, 106, 182, 201, 208, 171, 148, 176, 149, 150, 136, 172, 192, 214, 212],
    "marionette_r":   [287, 273, 335, 406, 421, 428, 396, 377, 400, 378, 379, 365, 397, 416, 434, 432],
    "nasolabial_marionette": "nasolabial+marionette_l+marionette_r",
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

# ── 직후 컷 투명 패치 자리 (2026-09-18 성연서님 "마리오네트 패치는 턱 라인, 팔자 패치는 입 쪽으로 살짝 — 약 2px") ──
#   말(프롬프트)로는 자리를 못 박는다: 모델은 사진 안에서 cm 를 못 재 09-17~18 두 회차 내내 패치가 볼·턱 가운데로 흩어졌다.
#   그래서 자리는 **얼굴 점에서 계산**하고, 그 원 안에만 그리게 한다(마스크 편집 + 원 밖 복원).
#   단위 = 얼굴 폭 W(234↔454). "out"=입꼬리에서 같은 쪽 얼굴 바깥으로, "up"=턱→이마 축(기울어진 셀카도 따라간다).
#   기준값 = 09-18 회차(2fae) 직후 컷 2장에서 모델이 그린 패치 중심을 잰 값 — 연서님이 "팔자는 비슷"이라 한 자리다:
#     팔자 끝 A ≈ out 0.10~0.15 · up +0.08 / 옆 B ≈ out 0.15~0.21 · up −0.04~+0.02 / 마리오네트 ≈ out 0.08 · up −0.17(턱 가운데 볼 → 틀림)
#   "2px" 은 사진 크기마다 뜻이 달라 얼굴 폭 비율(NASO_PULL)로 옮겼다 — 1024px 사진 얼굴 폭 ~550px 에서 0.015 ≈ 8px(원본),
#   슬랙 미리보기(가로 ~400px)에선 ~3px. 더/덜은 이 숫자 하나만 바꾼다.
PATCH_SPOTS = {
    "naso_end":  (0.125, 0.075),     # 팔자 아래 끝 (입꼬리 조금 위·바깥)
    "naso_side": (0.200, -0.020),    # 그 바로 바깥·조금 아래 볼 (A 와 지름 1.2배 이상 떨어지게 — 3/4 컷에서 겹쳤다)
}
NASO_PULL = 0.015          # 팔자 두 패치를 입꼬리 쪽으로 당기는 양 (얼굴 폭 비율) — 연서님 "입과 살짝만 가까이"
MARIO_DIR = (0.35, -1.0)   # 마리오네트 패치: 입꼬리에서 (바깥, 위) 방향으로 내려가 턱선과 만나는 점
MARIO_OUT = 0.5            # 턱선(MediaPipe 윤곽)에서 **바깥**으로 내미는 양 (패치 반지름 배수) — 원 절반이 턱 밑으로 넘어간다.
                           #   09-18 밤 연서님 (v25 두 회차 ↔ 실사진 #117·#118 대조): 종전 MARIO_INSET 0.35(안으로 들임)는
                           #   목표 원이 턱선보다 홍채 1.5개쯤 위(볼 중간)에 잡혔다 — MediaPipe 윤곽이 실제 턱 끝보다 안쪽인데
                           #   거기서 한 번 더 들여 두 번 올라간 셈. 실사진 패치는 턱선 모서리에 걸쳐 정면에선 거의 안 보인다.
MARIO_REQ_TURN = 0.25      # 마리오네트 자리를 '반드시'로 보는 건 가까운 쪽 턱 밑이 보이는 각도(3/4)에서만 — 돌아간 정도가 이 이상.
                           #   정면에선 턱선 모서리 패치가 안 보이는 게 정상이라 '있어도 되는 자리'(없어도 감점 없음)로 둔다.
SIDE_MIN_RATIO = 0.30      # 코끝→양쪽 얼굴 끝 거리 비가 이보다 작으면 그쪽은 돌아가 안 보인다 → 패치 안 붙임
SQUASH_NEAR = 0.35         # 가까운 쪽 볼 타원 눌림 계수 (turn=0.6 이면 가로 0.79배)
SQUASH_FAR = 0.9           # 먼 쪽 볼 (turn=0.3 이면 0.73배)
FAR_SIDE_RATIO = 0.75     # 이보다 짧은 쪽 = 카메라에서 돌아간 쪽(마리오네트 턱선 패치도 윤곽 검사)
FACE_RING_MIN = 8          # 패치 테두리 12점 중 얼굴 윤곽 안이어야 하는 개수 (아래 patch_spots 주석)
MOUTH_IRIS = 0.265         # 눈 점(468~477)이 화면 밖이거나 없을 때 홍채 지름 = 입 너비(61↔291) × 이 값.
                           #   09-18 밤 실측: 눈이 화면 안인 기존 팔자 컷 218장 중앙값 0.265 (p10 0.228 · p90 0.315).
                           #   종전(얼굴 폭 × 0.088, 또는 화면 밖 눈 점 그대로)은 코 아래 크롭에서 MediaPipe 가 지어낸 눈으로
                           #   자를 만들어 c4 한국 30대 컷이 '자리 오차'로 떨어졌다(09-18 c4 교훈).
_SIDE = {"R": dict(corner=291, edge=454, iris=(474, 476)),     # 사진 속 오른쪽이 아니라 얼굴 점 번호 기준 한쪽
         "L": dict(corner=61, edge=234, iris=(469, 471))}


def _inside(poly: list, q) -> bool:
    """점이 다각형 안인가 (광선 교차). 의존성 없이 — 셀카 배치 PC 마다 설치본이 다르다(09-15 insightface 교훈)."""
    x, y = q; n = len(poly); inside = False
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _jaw_hit(pts: np.ndarray, origin: np.ndarray, d: np.ndarray):
    """origin 에서 d 방향 반직선이 턱선(JAW_LINE 꺾은선)과 처음 만나는 점. 없으면 None."""
    best = None
    for a, b in zip(JAW_LINE, JAW_LINE[1:]):
        p, q = np.asarray(pts[a], float), np.asarray(pts[b], float)
        m = np.array([d, p - q]).T
        if abs(np.linalg.det(m)) < 1e-9:
            continue
        t, s = np.linalg.solve(m, p - origin)
        if t > 0 and 0 <= s <= 1 and (best is None or t < best[0]):
            best = (t, origin + t * d)
    return None if best is None else best[1]


def iris_diam(pts: np.ndarray, size=None) -> tuple:
    """(홍채 지름 px, 자 출처 'iris'|'mouth'). 눈 점(468~477)이 전부 화면 안일 때만 홍채를 쓴다.
    size=(w, h) 를 안 주면 화면 안 검사를 못 하므로 종전대로 홍채(점이 있으면)."""
    pts = np.asarray(pts, float)
    if len(pts) >= 478:
        eye = pts[468:478]
        inframe = size is None or bool(((eye[:, 0] >= 0) & (eye[:, 0] < size[0]) &
                                         (eye[:, 1] >= 0) & (eye[:, 1] < size[1])).all())
        if inframe:     # 먼 쪽 눈은 옆으로 눌려 작게 잡힌다 → 큰 쪽
            return max(float(np.linalg.norm(pts[a] - pts[b])) for s in _SIDE.values() for a, b in [s["iris"]]), "iris"
    return float(np.linalg.norm(pts[MOUTH_R] - pts[MOUTH_L])) * MOUTH_IRIS, "mouth"


def patch_spots(pts: np.ndarray, strict: bool = True, size=None) -> list:
    """직후 컷 패치 자리 [{side, name, x, y, r, need, scale}] (픽셀). 한쪽에 셋: 팔자 끝·그 옆·마리오네트 끝(턱선 모서리).

    크기 = 그 사람 홍채 지름(사진마다 얼굴 따라 커지고 작아진다 — 09-17 '두 명 패치 크기가 똑같다' 교정의 연장).
      눈이 화면 밖이면 입 너비로 잰다(iris_diam) — size=(w,h) 를 줘야 화면 밖을 가린다.
    need=False = '있어도 되는 자리'(없어도 감점 없음) — 정면·먼 쪽의 마리오네트(턱선 모서리는 정면에서 거의 안 보인다).
    돌아가 안 보이는 쪽(SIDE_MIN_RATIO 미만)은 빈다 — 얼굴 가장자리에 걸친 패치는 합성 티가 난다."""
    pts = np.asarray(pts, float)
    W = float(np.linalg.norm(pts[454] - pts[234]))
    up = pts[10] - pts[152]; up /= np.linalg.norm(up)
    across = pts[454] - pts[234]; across /= np.linalg.norm(across)
    reach = {k: float(np.linalg.norm(pts[s["edge"]] - pts[NOSE_TIP])) for k, s in _SIDE.items()}
    diam, scale = iris_diam(pts, size)
    r = diam / 2
    # 타원 (2026-09-18 빌디 제안 "3/4 컷은 옆으로 눌린 타원이 자연스럽다") — 볼은 얼굴이 돌아간 만큼 가로로 눌려 보인다.
    #   sx = 얼굴 가로축(across) 방향 배율, ang = 그 축의 기울기(도). 돌아간 정도 = 양쪽 코끝→얼굴 끝 거리의 비.
    #   가까운 쪽 볼은 카메라를 비스듬히 보므로 조금(SQUASH_NEAR), 먼 쪽은 많이 눌린다. 정면이면 둘 다 ≈1.
    turn = 1 - min(reach.values()) / max(reach.values())
    ang = float(np.degrees(np.arctan2(across[1], across[0])))
    near = max(reach, key=reach.get)
    def _squash(side):
        k = SQUASH_NEAR if side == near else SQUASH_FAR
        return {"sx": float(max(0.45, 1 - k * turn)), "ang": ang}
    out = []
    for side, s in _SIDE.items():
        if reach[side] < SIDE_MIN_RATIO * max(reach.values()):
            continue
        o = across if side == "R" else -across
        c = pts[s["corner"]]
        for name, (ox, oy) in PATCH_SPOTS.items():
            p = c + ((ox - NASO_PULL) * o + oy * up) * W
            out.append({"side": side, "name": name, "x": float(p[0]), "y": float(p[1]), "r": r, "need": True,
                        "scale": scale, **_squash(side)})
        d = MARIO_DIR[0] * o + MARIO_DIR[1] * up; d /= np.linalg.norm(d)
        hit = _jaw_hit(pts, c, d)
        if hit is not None:
            p = hit + d * r * MARIO_OUT            # 턱선에서 바깥(턱 밑)으로 반지름×OUT — 원 절반이 턱 밑으로 넘어간다
            out.append({"side": side, "name": "mario_end", "x": float(p[0]), "y": float(p[1]), "r": r,
                        "need": side == near and turn >= MARIO_REQ_TURN, "scale": scale, **_squash(side)})
    # 얼굴 윤곽 밖으로 걸치는 자리는 뺀다 (09-18 눈 확인: 옆으로 살짝 돈 정면 컷에서 먼 쪽 '옆' 패치가 배경에 떴다).
    #   윤곽 = full_face_skin 폴리곤. 중심만 보면 반쪽 패치가 허공에 뜬다.
    if not strict:
        # 윤곽 검사 없이 전부 — 위치 게이트(patchgate)의 '있어도 되는 자리' 원. 먼 쪽 볼은 프롬프트가 셋을 다 그리는데
        #   윤곽 검사가 둘을 빼므로, 그 둘을 '원 밖 패치'로 세면 먼 쪽이 보이는 컷은 늘 떨어진다(09-18 게이트 첫 점검).
        return out
    face = [tuple(map(float, pts[i])) for i in REGIONS["full_face_skin"]]
    #   ⚠ '원 전체가 안'으로 하면 턱선 패치가 전부 빠진다 — 이 윤곽의 아래 변이 곧 턱선이라 마리오네트 자리는 걸치는 게 맞다.
    #     그래서 중심은 안 + 테두리 12점 중 FACE_RING_MIN 이상이 안(MediaPipe 턱선은 보이는 턱 끝보다 살짝 안쪽이다).
    #     마리오네트 자리는 턱선에서 재어 들인 점이라 중심만 본다(테두리를 세면 턱선에 걸친 게 정상인데 빠진다 — 09-18 실측).
    #     단 **돌아간 쪽**(코끝→얼굴 끝 거리가 가까운 쪽의 FAR_SIDE_RATIO 미만)은 마리오네트도 테두리를 센다 —
    #     09-18 확대 확인: 옆으로 살짝 돈 정면 컷의 먼 쪽 턱선 패치가 보이는 턱 윤곽 밖(목·배경)으로 반쯤 나갔다.
    #     09-18 밤: 마리오네트 중심이 턱선 **바깥**(MARIO_OUT)으로 나가 윤곽 중심 검사를 통째로 건너뛴다(돌아간 쪽은 뺀다).
    far = {k for k, v in reach.items() if v < FAR_SIDE_RATIO * max(reach.values())}
    out = [s for s in out if (s["name"] == "mario_end" and s["side"] not in far) or _inside(face, (s["x"], s["y"])) and (sum(
        _inside(face, (s["x"] + s["r"] * np.cos(a), s["y"] + s["r"] * np.sin(a)))
        for a in np.linspace(0, 2 * np.pi, 12, endpoint=False)) >= FACE_RING_MIN)]
    return out


def spots_mask(size, spots: list, grow: float = 1.35, feather: int = 3) -> Image.Image:
    """패치 자리 원 마스크 (L, 흰색=편집 허용). grow = 패치보다 조금 넓게 열어 모델이 가장자리를 그릴 틈을 준다."""
    from PIL import ImageFilter
    import cv2
    a = np.zeros((size[1], size[0]), np.uint8)
    for s in spots:
        rr = s["r"] * grow
        cv2.ellipse(a, (int(round(s["x"])), int(round(s["y"]))), (max(1, int(rr * s.get("sx", 1.0))), int(rr)),
                    s.get("ang", 0.0), 0, 360, 255, -1)       # 타원: 가로축=얼굴 across 방향 × sx
    m = Image.fromarray(a)
    return m.filter(ImageFilter.GaussianBlur(feather)) if feather else m


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
    # 합성 부위("a+b")는 표에서 읽는다 — 여기에 시술 이름을 하드코딩하면 부위를 하나 늘릴 때마다
    # 이 줄을 같이 고쳐야 하고, 안 고치면 KeyError 가 아니라 **엉뚱한 한 부위만** 칠해진다.
    spec = REGIONS[region]
    keys = spec.split("+") if isinstance(spec, str) and "+" in spec else [region]
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
