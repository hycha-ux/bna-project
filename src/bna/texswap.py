"""모공은 Before 에서 가져오기 — After 의 잔결 층(모공·잔털·수염 결)을 Before 것으로 교체. 모델 밖, 비용 0.

2026-09-29 연서님 v57 검수: "15차 뒤에도 모공이 도장 찍은 듯 같은 크기·간격으로 반복 — 띠 밖(이마·콧등·윗볼)도
똑같아서, 재촬영이 얼굴 전체 모공을 다시 그리는 것. 문장으로는 안 잡힌다" → 제안 5단계 그대로:
  1. After 를 큰 층(밝기·그늘·팔자 효과 = 흐림)과 잔결 층(원본 − 흐림, 폭 w×FINE_SIGMA)으로 나눈다.
  2. 잔결 층은 Before 것을 얼굴 점(478개) 삼각망으로 After 모양에 맞춰 휘어서 교체한다(같은 사람 → 모공은 같은 자리).
  3. 팔자 띠 안은 Before 잔결을 약하게(BAND_W) 넣고, 골 선 선명도가 되살아나면 더 약하게 내린다(BAND_STEPS).
  4. 고개 차이가 크면(POSE_*) 이 단계를 건너뛰고 기록만 남긴다.
  5. 새 생성 없이 기존 After 에 덮는다 — 도구 = tools/texswap_apply.py.

⚠ 잔결 교체가 **구조 윤곽**(눈꺼풀·콧볼·입술선·점)에 닿으면 휘기 오차 2px 에도 두 겹 윤곽이 된다 → 두 사진 어느 쪽이든
  잔결이 피부 결의 STRUCT_K 배(표준편차)를 넘는 자리는 After 제 것을 둔다. 눈·눈썹·입술은 아예 뺀다.
"""
import numpy as np
from PIL import Image

from .qa import landmarks as L

FINE_SIGMA = 0.008        # 잔결 층 = 원본 − 가우스 흐림(w×이 값). 1024px 에서 8px. 첫 판 0.004(4px)는 지금 After 의
                          #   '그물 무늬'(칸 8~12px)가 큰 층에 남아 그대로 보였다(09-29 v57 0000 확대). 크면 골 선 토막이 딸려 온다
BAND_GROW = 0.03          # 팔자 띠를 이만큼(w×) 넓혀 약하게 넣는다 — 경계 페더가 골 선 자 안으로 들어오지 않게
BAND_W = 0.5              # 팔자 띠 안 Before 잔결 비중(첫 값). 나머지는 After 제 잔결
BAND_STEPS = (0.5, 0.3, 0.15, 0.0)   # 골 선이 되살아나면 이 순서로 약하게
EDGE_BACK_MAX = 3.0       # 골 선 선명도(Before 대비 %)가 지금 After 보다 이만큼(%p) 넘게 되살아나면 한 단계 약하게
STRUCT_K = 3.5            # 잔결 크기가 피부 결 표준편차의 이 배를 넘으면 구조(윤곽·점) — 교체 안 함
GAIN_MAX = 1.3            # 휘기(보간)로 깎인 잔결 세기 보정 상한
POSE_YAW_MAX = 0.08       # 고개 좌우 차(코끝 가로 위치 ÷ 눈 사이) 상한
POSE_RES_MAX = 0.05       # 닮음 정렬 뒤 얼굴 점 잔차(RMS ÷ 눈 사이) 상한 — 표정·각도 차가 크면 삼각망이 찢어진다

EYE_L = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
EYE_R = [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466]
BROW_L = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]
BROW_R = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]
LIPS = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]


def _lab(rgb: Image.Image) -> np.ndarray:
    import cv2
    return cv2.cvtColor(np.asarray(rgb.convert("RGB"), np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def _rgb(lab: np.ndarray) -> Image.Image:
    import cv2
    out = cv2.cvtColor(lab.astype(np.float32), cv2.COLOR_LAB2RGB)
    return Image.fromarray(np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8))


def split(lab: np.ndarray, w: int):
    """(큰 층, 잔결 층) — 세 채널 모두."""
    import cv2
    base = cv2.GaussianBlur(lab, (0, 0), max(1.0, w * FINE_SIGMA))
    return base, lab - base


def _ipd(pts):
    k = L.key_points(pts)
    return float(np.linalg.norm(k["eye_r"] - k["eye_l"]))


def pose_diff(pb: np.ndarray, pa: np.ndarray) -> dict:
    """고개 차이 — yaw(코끝 가로 위치 ÷ 눈 사이 차), res(닮음 정렬 뒤 점 잔차 RMS ÷ 눈 사이)."""
    import cv2
    def yaw(p):
        k = L.key_points(p)
        mid = (k["eye_l"] + k["eye_r"]) / 2
        return float((k["nose"][0] - mid[0]) / _ipd(p))
    M, _ = cv2.estimateAffinePartial2D(pb[:468].astype(np.float32), pa[:468].astype(np.float32))
    moved = pb[:468] @ M[:, :2].T + M[:, 2]
    res = float(np.sqrt(((moved - pa[:468]) ** 2).sum(1).mean()) / _ipd(pa))
    return {"yaw": round(abs(yaw(pb) - yaw(pa)), 4), "res": round(res, 4)}


def warp_maps(pb: np.ndarray, pa: np.ndarray, size) -> tuple:
    """After 좌표 → Before 좌표 지도(cv2.remap 용). 얼굴 점 삼각망 안은 삼각형별 아핀, 밖은 닮음 변환."""
    import cv2
    from scipy.spatial import Delaunay
    W, H = size
    gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    M, _ = cv2.estimateAffinePartial2D(pa[:468].astype(np.float32), pb[:468].astype(np.float32))
    mx = (M[0, 0] * gx + M[0, 1] * gy + M[0, 2]).astype(np.float32)
    my = (M[1, 0] * gx + M[1, 1] * gy + M[1, 2]).astype(np.float32)
    A, B = pa[:468].astype(np.float32), pb[:468].astype(np.float32)
    for t in Delaunay(A).simplices:
        ta, tb = A[t], B[t]
        x0, y0 = np.floor(ta.min(0)).astype(int); x1, y1 = np.ceil(ta.max(0)).astype(int) + 1
        x0, y0 = max(x0, 0), max(y0, 0); x1, y1 = min(x1, W), min(y1, H)
        if x1 <= x0 or y1 <= y0:
            continue
        m = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillConvexPoly(m, np.round(ta - [x0, y0]).astype(np.int32), 1)
        T = cv2.getAffineTransform(ta, tb)
        sx, sy = gx[y0:y1, x0:x1], gy[y0:y1, x0:x1]
        k = m > 0
        mx[y0:y1, x0:x1][k] = (T[0, 0] * sx + T[0, 1] * sy + T[0, 2])[k]
        my[y0:y1, x0:x1][k] = (T[1, 0] * sx + T[1, 1] * sy + T[1, 2])[k]
    return mx, my


def _poly(shape, pts, idx, grow=0):
    import cv2
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [cv2.convexHull(pts[idx].astype(np.int32))], 1)
    if grow:
        m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (grow | 1, grow | 1)))
    return m > 0


def face_weight(size, pa: np.ndarray) -> np.ndarray:
    """교체 허용 지도(0~1) = 얼굴 윤곽 안 − 눈·눈썹·입술(여유 포함), 경계 페더."""
    import cv2
    W, H = size
    face = np.zeros((H, W), np.uint8)
    cv2.fillPoly(face, [pa[L.FACE_OVAL].astype(np.int32)], 1)
    face = cv2.erode(face, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(W * 0.02) | 1,) * 2)) > 0
    g = int(W * 0.015)
    ex = _poly((H, W), pa, EYE_L, g) | _poly((H, W), pa, EYE_R, g) | _poly((H, W), pa, BROW_L, g) \
        | _poly((H, W), pa, BROW_R, g) | _poly((H, W), pa, LIPS, g)
    return cv2.GaussianBlur((face & ~ex).astype(np.float32), (0, 0), W * 0.006)


def band_map(after: Image.Image, pa: np.ndarray) -> np.ndarray:
    """팔자 띠(좌우 코 옆 + 다리 + 마리오네트, foldlift 와 같은 부위) 0~1."""
    from . import foldlift as FL   # noqa: F401  — _fold_side0/1 부위를 등록한다
    W = after.size[0]
    import cv2
    m = sum(np.asarray(L.region_mask(after, pa, f"_fold_side{i}", feather=1), np.float32) / 255.0 for i in (0, 1))
    # 띠 경계 페더가 띠 **안쪽**으로 먹어 들면 골 선 자(edge_ratio, 같은 부위)가 재는 가장자리에 Before 결이 반쯤 들어와
    # 선이 되살아났다(첫 시험: 띠 비중 0 에서도 +5~7%p) → 띠를 w×BAND_GROW 만큼 넓힌 뒤 바깥으로 페더
    r = int(W * BAND_GROW) | 1
    m = cv2.dilate((m > 0.5).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))).astype(np.float32)
    return np.clip(cv2.GaussianBlur(m, (0, 0), W * 0.008), 0, 1)


def swap(before: Image.Image, after: Image.Image, band_w: float = BAND_W, pb=None, pa=None, _cache: dict = None):
    """(새 After | None, 기록). 고개 차이가 크거나 얼굴 점을 못 찾으면 None + 사유(건너뜀)."""
    import cv2
    b, a = before.convert("RGB"), after.convert("RGB")
    if b.size != a.size:
        b = b.resize(a.size, Image.LANCZOS)
    pb = L.detect(b) if pb is None else pb
    pa = L.detect(a) if pa is None else pa
    if pb is None or pa is None:
        return None, {"applied": False, "skip": "no_face"}
    pose = pose_diff(pb, pa)
    rec = {"pose": pose}
    if pose["yaw"] > POSE_YAW_MAX or pose["res"] > POSE_RES_MAX:
        return None, {**rec, "applied": False, "skip": "pose"}
    W, H = a.size
    c = _cache if _cache is not None else {}
    if "fb" not in c:
        _, fb = split(_lab(b), W)
        mx, my = warp_maps(pb, pa, a.size)
        fbw = np.dstack([cv2.remap(np.ascontiguousarray(fb[:, :, i]), mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
                         for i in range(3)])
        base_a, fa = split(_lab(a), W)
        fw = face_weight(a.size, pa)
        skin = fw > 0.9
        # 보간으로 깎인 잔결 세기를 Before 원래 세기로(L 기준)
        fwb = face_weight(b.size, pb) > 0.9
        gain = float(np.clip(fb[:, :, 0][fwb].std() / max(fbw[:, :, 0][skin].std(), 1e-6), 1.0, GAIN_MAX))
        fbw = fbw * gain
        sd = max(float(fa[:, :, 0][skin].std()), float(fbw[:, :, 0][skin].std()), 1e-6)
        big = np.maximum(np.abs(fa[:, :, 0]), np.abs(fbw[:, :, 0])) / sd
        struct = cv2.GaussianBlur(np.clip(STRUCT_K + 1 - big, 0, 1).astype(np.float32), (0, 0), 1.5)
        c.update(fb=fb, fbw=fbw, base_a=base_a, fa=fa, fw=fw, struct=struct, band=band_map(a, pa), gain=gain,
                 sd_a=float(fa[:, :, 0][skin].std()), sd_b=float(fb[:, :, 0][fwb].std()))
    wmap = c["fw"] * c["struct"] * (1 - c["band"] * (1 - band_w))
    out = c["base_a"] + c["fa"] * (1 - wmap[..., None]) + c["fbw"] * wmap[..., None]
    rec.update(applied=True, band_w=band_w, gain=round(c["gain"], 3),
               fine_sd_after=round(c["sd_a"], 3), fine_sd_before=round(c["sd_b"], 3),
               struct_kept=round(float(1 - c["struct"][c["fw"] > 0.9].mean()), 4))
    return _rgb(out), rec


SIG_BAND, SIG_OUT = 0.008, 0.02   # 19차: 팔자 띠 안 8px(골 보호) / 띠 밖 20px(그물 칸 8~12px 까지 잔결로) — 1024 폭 기준, w× 비율


def merge_var(src: Image.Image, dst: Image.Image, sig_band: float = SIG_BAND, sig_out: float = SIG_OUT, pb=None, pa=None):
    """자리마다 자르는 폭이 다른 합치기(19차, 2026-09-29 연서님 "합친 뒤에도 확대하면 도장 — 폭 8px 이 그물 무늬(8~12px)와
    겹쳐 그 무늬가 큰 층으로 B 에서 넘어왔다 → 팔자 띠 밖은 16~24px, 띠 안만 8px, 경계는 부드럽게").

    src = 잔결 원천(재촬영), dst = 바탕(메운 B). 잔결 = 띠 지도(band_map, 넓힌 뒤 페더) 로 두 폭을 섞은 고역 층:
      fine = band·(원본 − 흐림 sig_band) + (1−band)·(원본 − 흐림 sig_out)
    out = dst − fine(dst) + fine(src 를 dst 모양으로 휜 것). 눈·눈썹·입술은 face_weight 로, 윤곽·점은 8px 층 구조 가드로 뺀다.
    (None, 기록) = 얼굴 점 못 찾음·고개 차이 큼."""
    import cv2
    s, d = src.convert("RGB"), dst.convert("RGB")
    if s.size != d.size:
        s = s.resize(d.size, Image.LANCZOS)
    pb = L.detect(s) if pb is None else pb
    pa = L.detect(d) if pa is None else pa
    if pb is None or pa is None:
        return None, {"applied": False, "skip": "no_face"}
    pose = pose_diff(pb, pa)
    if pose["yaw"] > POSE_YAW_MAX or pose["res"] > POSE_RES_MAX:
        return None, {"pose": pose, "applied": False, "skip": "pose"}
    W = d.size[0]
    ls, ld = _lab(s), _lab(d)
    mx, my = warp_maps(pb, pa, d.size)
    lw = np.dstack([cv2.remap(np.ascontiguousarray(ls[:, :, i]), mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT) for i in range(3)])
    band = band_map(d, pa)[..., None]

    def fine(lab):
        return band * (lab - cv2.GaussianBlur(lab, (0, 0), W * sig_band)) + (1 - band) * (lab - cv2.GaussianBlur(lab, (0, 0), W * sig_out))

    fs, fd = fine(lw), fine(ld)
    fw = face_weight(d.size, pa)
    skin = fw > 0.9
    # 구조 가드는 8px 층으로 잰다(20px 층은 코·볼 음영까지 커서 가드가 얼굴 절반을 뺀다)
    g8s = lw[:, :, 0] - cv2.GaussianBlur(lw[:, :, 0], (0, 0), W * sig_band)
    g8d = ld[:, :, 0] - cv2.GaussianBlur(ld[:, :, 0], (0, 0), W * sig_band)
    sd = max(float(g8d[skin].std()), float(g8s[skin].std()), 1e-6)
    big = np.maximum(np.abs(g8d), np.abs(g8s)) / sd
    struct = cv2.GaussianBlur(np.clip(STRUCT_K + 1 - big, 0, 1).astype(np.float32), (0, 0), 1.5)
    wmap = (fw * struct)[..., None]
    out = ld + (fs - fd) * wmap
    return _rgb(out), {"pose": pose, "applied": True, "sig_band": sig_band, "sig_out": sig_out,
                       "struct_kept": round(float(1 - struct[skin].mean()), 4)}


def pore_stats(img: Image.Image, pts=None) -> dict:
    """모공 불규칙 자 — 얼굴 맨살 잔결(L)에서 어두운 점(−1σ 아래 덩어리)의 크기·이웃 간격 변동계수(표준편차÷평균).
    진짜 피부는 크기·간격이 제각각(값이 크다), '같은 크기·같은 간격' 도장은 값이 작다. 15차 반복 자(repeat_stats)는
    같은 무늬가 두 번 찍힌 것만 잡아 '규칙적인 새 무늬'는 0 으로 읽는다(v57 face_hit 0.013·0.037) — 그걸 보완하는 자."""
    import cv2
    from scipy.spatial import cKDTree
    rgb = img.convert("RGB")
    pts = L.detect(rgb) if pts is None else pts
    if pts is None:
        return {"measured": False}
    W = rgb.size[0]
    _, f = split(_lab(rgb), W)
    fl = f[:, :, 0]
    skin = face_weight(rgb.size, pts) > 0.9
    sd = float(fl[skin].std())
    dark = ((fl < -sd) & skin).astype(np.uint8)
    n, cc, st, cen = cv2.connectedComponentsWithStats(dark)
    ar = st[1:, cv2.CC_STAT_AREA]
    ok = (ar >= 3) & (ar <= (W * 0.015) ** 2)
    ar, cen = ar[ok], cen[1:][ok]
    if len(ar) < 30:
        return {"measured": False}
    d, _ = cKDTree(cen).query(cen, k=2)
    nn = d[:, 1]
    cv = lambda v: float(v.std() / max(v.mean(), 1e-6))  # noqa: E731
    return {"measured": True, "n": int(len(ar)), "size_cv": round(cv(ar.astype(float)), 3), "gap_cv": round(cv(nn), 3),
            "fine_sd": round(sd, 3)}
