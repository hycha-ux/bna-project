"""잡티·검버섯 개수 자 (2026-09-29 24차 연서님 "Before·After 갈색 잡티·검버섯 개수를 재서 원장에 기록만. 탈락 사유로는 걸지 말아줘").

왜: 22차 2202(60대 여 정면)에서 Before 의 갈색 잡티·검버섯이 After 에서 전부 사라져 '과하게 젊어진' 컷이 됐다.
    같은 컷이 반복되는지 숫자로 보려는 기록용 자다 — **검수·재시도에 쓰지 않는다**(문턱 없음).

잡티 = 얼굴 맨살에서 주변(큰 흐림)보다 **어둡고 더 누런/갈색** 쪽으로 기운 둥근 얼룩.
  · 크기: 지름 1.2~12mm (모공·솜털은 1mm 아래, 그늘·골은 길쭉하거나 더 크다). mm 는 눈꼬리 바깥 거리 90mm 로 환산(foldlift 와 같은 자).
  · 어둠: L 이 주변보다 DL_MIN 이상 낮다(OpenCV L 0~255).
  · 갈색: b(노랑) 가 주변 이상 — 그늘은 L 과 함께 b 도 내려가 여기서 빠진다. a(빨강)가 크게 오른 건 여드름·붉은 자국이라 뺀다.
  · 길쭉한 것(장축÷단축 > 3)은 골·주름 토막이라 뺀다.
  · 맨살 = 얼굴 윤곽 안쪽 − 윤곽 부위(눈·눈썹·입·입꼬리선·코 아래·헤어라인, texswap.feature_mask) — 두 겹 자와 같은 제외.
해상도 무관하게 하려고 얼굴 폭을 1024 기준으로 맞춰서 잰다(고해상도 2304 와 1024 컷의 값이 같은 자로 나온다).
검버섯(큰 것, 지름 4mm 이상)은 `large` 로 따로 센다.
"""
import numpy as np
from PIL import Image

from .qa import landmarks as L

EYE_MM = 90.0          # 눈꼬리 바깥(33↔263) 거리 — foldlift.ALA_EYE_MM 와 같은 자
D_MIN_MM, D_MAX_MM = 0.6, 12.0
BG_MM = 6.0            # 주변 = 이 폭의 흐림(잡티보다 넓고 볼 그늘 기울기보다 좁게)
EYE_PAD_MM = 6.0
LARGE_MM = 4.0
DL_MIN = 15.0          # 주변보다 이만큼 어두워야(L 0~255). 모공·잔주름은 이보다 옅다(2202 실측: 잡티 −20~−29, 눈꺼풀 주름 −5)
DB_MIN = 2.0           # b 가 주변보다 이만큼 이상 (그늘은 b 도 내려간다. 잡티 +2.5~4.7)
DA_MAX = 8.0           # a 가 이보다 더 오르면 붉은 자국(여드름·홍조)이라 뺀다
ELONG_MAX = 3.0
RED_MIN = 6.0          # 트러블 = a 가 주변보다 이만큼 넘게 붉다(OpenCV a 0~255)
WORK_W = 2048


def count(img: Image.Image, pts=None, region: str = None) -> dict:
    """{"measured", "n", "large", "area_pct"} — area_pct = 잡티 면적 ÷ 맨살 면적 × 100."""
    import cv2
    from . import texswap
    rgb = img.convert("RGB")
    if rgb.size[0] != WORK_W:
        rgb = rgb.resize((WORK_W, round(rgb.size[1] * WORK_W / rgb.size[0])), Image.LANCZOS)
        pts = None
    pts = L.detect(rgb) if pts is None else pts
    if pts is None:
        return {"measured": False}
    W, H = rgb.size
    mm = float(np.linalg.norm(pts[263][:2] - pts[33][:2])) / EYE_MM      # px per mm
    if mm <= 0:
        return {"measured": False}
    face = np.zeros((H, W), np.uint8)
    cv2.fillPoly(face, [pts[L.FACE_OVAL][:, :2].astype(np.int32)], 1)
    r = max(3, int(W * 0.02)) | 1
    face = cv2.erode(face, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))) > 0
    skin = face & ~texswap.feature_mask(rgb.size, pts, rgb)
    for idx in (texswap.EYE_L, texswap.EYE_R):                          # 눈꺼풀 주름·눈꼬리 그늘(잡티 아님) — 눈 둘레 EYE_PAD_MM 더 뺀다
        skin &= ~texswap._poly((H, W), pts, idx, int(EYE_PAD_MM * mm))
    # 팔자·마리오네트 골 띠는 뺀다 — 골 선 토막이 점으로 끊겨 잡티로 세졌다(2202 Before 실측). 이 자리는 골 수치가 따로 잰다.
    #   region="band"(25차 연서님 "띠 안 잡티·트러블 개수 Before/After") 면 거꾸로 띠 안만 잰다. 붉은 자국(트러블)은 `red` 로 따로 센다.
    from . import foldlift
    band = np.zeros(skin.shape, bool)
    for i in range(len(foldlift.SIDES)):
        band |= np.asarray(L.region_mask(rgb, pts, f"_fold_side{i}", feather=0)) >= 128
    skin = (skin & band) if region == "band" else (skin & ~band)
    if skin.sum() < (500 if region == "band" else 5000):
        return {"measured": False}
    lab = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2LAB).astype(np.float32)
    s = max(2.0, BG_MM * mm)
    wgt = cv2.GaussianBlur(skin.astype(np.float32), (0, 0), s) + 1e-6
    bg = [cv2.GaussianBlur(lab[:, :, c] * skin, (0, 0), s) / wgt for c in range(3)]
    dL, da, db = (lab[:, :, c] - bg[c] for c in range(3))
    sm = cv2.GaussianBlur                                                # 점 안 평균 대신 살짝 흐려 모공 잡음을 누른다
    k = max(0.8, 0.15 * mm)
    dL, da, db = sm(dL, (0, 0), k), sm(da, (0, 0), k), sm(db, (0, 0), k)
    cand = (skin & (dL < -DL_MIN) & (db > DB_MIN) & (da < DA_MAX)).astype(np.uint8)
    n, cc, st, _ = cv2.connectedComponentsWithStats(cand)
    a_min = np.pi * (D_MIN_MM * mm / 2) ** 2
    a_max = np.pi * (D_MAX_MM * mm / 2) ** 2
    a_big = np.pi * (LARGE_MM * mm / 2) ** 2
    cnt = big = 0
    area = 0
    for i in range(1, n):
        a = st[i, cv2.CC_STAT_AREA]
        if a < a_min or a > a_max:
            continue
        w_, h_ = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]
        if max(w_, h_) / max(1, min(w_, h_)) > ELONG_MAX:
            continue
        ys, xs = np.nonzero(cc == i)
        if len(xs) >= 5:
            ev = np.linalg.eigvalsh(np.cov(np.vstack([xs, ys])))
            if ev[0] > 0 and np.sqrt(ev[1] / ev[0]) > ELONG_MAX:
                continue
        cnt += 1; area += a
        big += a >= a_big
    # 트러블·붉은 자국(25차) = a 가 주변보다 RED_MIN 넘게 붉은 둥근 덩어리(같은 크기 범위). 갈색 잡티와 따로 센다.
    red = 0
    n2, cc2, st2, _ = cv2.connectedComponentsWithStats((skin & (da > RED_MIN)).astype(np.uint8))
    for i in range(1, n2):
        a = st2[i, cv2.CC_STAT_AREA]
        w_, h_ = st2[i, cv2.CC_STAT_WIDTH], st2[i, cv2.CC_STAT_HEIGHT]
        if a_min <= a <= a_max and max(w_, h_) / max(1, min(w_, h_)) <= ELONG_MAX:
            red += 1
    return {"measured": True, "n": int(cnt), "large": int(big), "red": int(red),
            "area_pct": round(100.0 * area / float(skin.sum()), 3)}
