"""팔자 A안 — 골 선 지우기(주) + 그늘 밝히기(보조). 모델 밖에서 우리가 직접, 비용 0.

이력:
  7차(2026-09-28): 이미지 편집 모델이 '팔자를 옅게'를 어떤 방식으로 줘도 실행하지 않아(골 대비 ±0.4%, 5컷) 그늘만 들어올렸다.
  8차: 부위를 코 옆 골 띠(nasal_fold)로 옮기고 세기를 실제 쌍 목표(-50%)에 맞췄다 — 연서님 "그늘만 옅어지고 골 선이 그대로".
  9차(이 판): 연서님 "실제 필러 후는 골이 메워져서 선이 없어지는 거지 조명이 밝아지는 게 아니야" → 두 축으로 갈랐다.

① 골 선 지우기 `erase` (주):
   골 선 = 골 띠 안에서 '중간 흐림 − 큰 흐림'이 가장 어두운 줄(좌우 따로 상위 25%, 길쭉한 덩어리만 — 9차 조정: 15%·폭 1.2% 는 0000 선을 못 다 잡았다). 그 줄을 따라 **좁은 띠**를
   만들고, 띠 안에서 '잔결 흐림 − 큰 흐림'(골의 어두운 쪽 + 볼 능선의 밝은 쪽 = 단차) 을 **양쪽 부호 모두** 걷어낸다.
   잔결(원본 − 잔결 흐림: 모공·솜털)은 그대로 남는다. 즉 골을 '메운' 모양 — 선과 능선이 같이 평평해진다.
② 그늘 밝히기 `lift` (보조): 8차 방식(어두운 쪽만 들어올림). 지우기 뒤에 목표 그늘에 모자라면 그만큼만.

부위 = 코 옆 골 띠 + 마리오네트(좌우 각각 한 덩어리 — 선 찾기 문턱을 좌우 따로 잡는다. 한쪽 골이 깊으면 반대쪽 선을 못 찾는다).
측정 = `edge_ratio`(골 선 선명도, 연서님 9차 "측정에 '골 선 선명도' 추가"): 골 띠 안 밝기 경사(단차) ÷ 같은 얼굴 볼 맨살 경사.
   1 에 가까울수록 '선이 주변 피부와 같다'. 그늘(`shade`)은 어두움만 봐서 선이 남아도 통과했다(8차 A75: 그늘 -65% 인데 선이 보임).
"""
import numpy as np
from PIL import Image

from .qa import landmarks as L

REGION = "nasal_fold"
# 11차(09-28): 코 옆 띠와 마리오네트 사이 다리(fold_link_*)를 넣었다 — 입꼬리 옆 아래 골이 어느 띠에도 안 들어 0000 이 -26% 에서 멈췄다.
#   ⚠ setdefault 가 아니라 대입이다 — 한 프로세스에서 옛 값이 남으면 새 다리가 조용히 빠진다.
SIDES = ("nasolabial_fold_l+fold_link_l+marionette_l", "nasolabial_fold_r+fold_link_r+marionette_r")
SMALL_FRAC, LARGE_FRAC, FEATHER_FRAC = 0.012, 0.12, 0.018
LIPS = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
CHEEK_L, CHEEK_R = [117, 118, 101, 50, 123, 116], [346, 347, 330, 280, 352, 345]   # 볼 맨살(골 없는 대조) — 눈 밑 볼 위쪽
for _i, _s in enumerate(SIDES):
    L.REGIONS[f"_fold_side{_i}"] = _s


def _L(rgb):
    import cv2
    return cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2LAB).astype(np.float32)


def _ipd(pts):
    k = L.key_points(pts)
    return float(np.linalg.norm(k["eye_r"] - k["eye_l"]))


def _parts(rgb, pts, region, feather):
    import cv2
    w = rgb.size[0]
    m = np.asarray(L.region_mask(rgb, pts, region, feather=feather if feather is not None else max(2, int(w * FEATHER_FRAC))),
                   dtype=np.float32) / 255.0
    lab = _L(rgb)
    ks = max(3, int(w * SMALL_FRAC) | 1); kl = max(ks + 2, int(w * LARGE_FRAC) | 1)
    Lc = lab[:, :, 0]
    dark = np.minimum(cv2.GaussianBlur(Lc, (ks, ks), 0) - cv2.GaussianBlur(Lc, (kl, kl), 0), 0.0)
    return m, lab, dark


def shade(img: Image.Image, pts=None, region: str = REGION, feather=None):
    """골 그늘 = 부위 안(마스크 0.5 이상)에서 주변보다 어두운 양의 평균(L 단위). 얼굴 점 못 찾으면 None."""
    rgb = img.convert("RGB")
    pts = L.detect(rgb) if pts is None else pts
    if pts is None:
        return None
    m, _lab, dark = _parts(rgb, pts, region, feather)
    return float(-dark[m > 0.5].mean())


def lift(img: Image.Image, pts=None, strength: float = 1.0, region: str = REGION, feather=None):
    """그늘 밝히기(보조). (보정된 사진, 기록). 얼굴 점을 못 찾으면 (원본, {"applied": False}) — fail-open."""
    import cv2
    rgb = img.convert("RGB")
    pts = L.detect(rgb) if pts is None else pts
    if pts is None:
        return rgb, {"applied": False, "reason": "얼굴 점 못 찾음"}
    m, lab, dark = _parts(rgb, pts, region, feather)
    lab[:, :, 0] = np.clip(lab[:, :, 0] - strength * dark * m, 0, 255)
    res = Image.fromarray(cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB))
    return res, {"applied": True, "strength": round(float(strength), 3), "region": region}


def _face_inner(rgb, pts, margin: float = 0.03) -> np.ndarray:
    """얼굴 윤곽 안쪽(가장자리에서 w×margin 만큼 들어온 곳). 11차 첫 실행에서 마리오네트 다리가 턱선까지 닿아
    얼굴↔배경 경계를 '골 선'으로 잡고 배경색으로 메워 턱선이 녹아내렸다 — 선 찾기·메우기를 이 안에서만 한다."""
    import cv2
    m = np.zeros((rgb.size[1], rgb.size[0]), np.uint8)
    cv2.fillPoly(m, [pts[L.FACE_OVAL].astype(np.int32)], 1)
    r = max(3, int(rgb.size[0] * margin)) | 1
    return cv2.erode(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))) > 0


INNER_MARGIN = 0.015   # 13차: 3% → 1.5%. 3/4 컷의 먼 쪽 띠가 윤곽에 붙어 3% 자르기에 대부분 잘렸다(v53 0001 사진 왼쪽 골 절반만 잡힘)


def line_map(rgb: Image.Image, pts, pct: float = 75, width: float = 0.018, feather: float = 0.012,
             sides=(0, 1), margin: float = None) -> np.ndarray:
    """골 선을 따라가는 좁은 띠(0~1). 좌우 따로 문턱(상위 25%)을 잡고, 작은 점 덩어리(모공·잡티)는 버린다.
    sides = 찾을 쪽(0 = 사진 왼쪽 l, 1 = 오른쪽 r) — 좌우 자(13차)가 한쪽만 더 메울 때 쓴다."""
    import cv2
    w = rgb.size[0]
    Lc = _L(rgb)[:, :, 0]
    valley = -np.minimum(cv2.GaussianBlur(Lc, (0, 0), w * 0.006) - cv2.GaussianBlur(Lc, (0, 0), w * 0.03), 0)
    keep = np.zeros(Lc.shape, np.uint8)
    inner = _face_inner(rgb, pts, INNER_MARGIN if margin is None else margin)
    for i in sides:
        band = (np.asarray(L.region_mask(rgb, pts, f"_fold_side{i}", feather=2)) > 127) & inner
        if not band.any():
            continue
        v = valley * band
        thr = np.percentile(valley[band], pct)
        line = (v > thr).astype(np.uint8)
        n, cc, st, _ = cv2.connectedComponentsWithStats(line)
        for j in range(1, n):
            if st[j, cv2.CC_STAT_AREA] > w * w * 0.0004:
                keep[cc == j] = 1
    r = int(w * width) | 1
    # 경계 페더 0.6% → 1.2% (11차 연서님 "띠 경계 페더 넓혀줘" — 1.5배 컷에서 콧볼 옆이 뭉갠 띠로 보였다)
    wm = cv2.GaussianBlur(cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))).astype(np.float32), (0, 0), w * feather)
    soft_inner = cv2.GaussianBlur(inner.astype(np.float32), (0, 0), w * 0.008)   # 페더를 넓혀도 윤곽 밖으로 번지지 않게
    return np.clip(wm / max(float(wm.max()), 1e-6) * 1.2, 0, 1) * soft_inner


# ── 14차(2026-09-28 연서님 v54 검수 "팔자 띠가 포토샵으로 지운 느낌 — 주변보다 하얗고 너무 깨끗해") ──────────────
#   메우기가 바탕만 옆 피부 평균으로 채우고 L 채널만 건드려서 ①띠 안 잡티·모공 불균일(중간 크기 결)이 흐림에 지워지고
#   ②색(a·b)은 원래 골의 그늘색 그대로라 밝기만 올라간 자리가 희끗해 보였다. → 세 채널 모두 '바탕은 옆 피부 평균,
#   결은 **옆 피부에서 옮겨 온 결**(잡티·색 얼룩·모공 불균일)'로 채우고, 메운 자리 평균 밝기는 주변 평균 이하로 묶는다.
TRANSPLANT = True          # 끄면 13차 방식(L 바탕만 채우고 원래 잔결 유지)
DETAIL_SIGMA = 0.003       # 옮겨 올 결의 크기 상한(w×) — 모공·잡티·색 얼룩. 0.006 이면 골 선 토막까지 '결'로 분류돼
                           #   점 보존이 골을 남겼다(v54 0002 오른쪽 -16%, 0.003 이면 -46%)
MOLE_SIGMA = 6.0           # 띠 안 점(모반) 판정: 가장 어두운 곳이 결 표준편차의 이 배수 아래
DARK_MARGIN = 0.3         # 메운 자리 평균 밝기 ≤ 주변 평균 − 이 값(L 단위) — "절대 주변보다 밝아지지 않게"


def _skin_ok(rgb, pts, band_soft) -> np.ndarray:
    """결을 떠 올 수 있는 자리 = 얼굴 윤곽 안 · 띠 밖 · 코·입술 밖."""
    import cv2
    w = rgb.size[0]
    ex = np.asarray(L.region_mask(rgb, pts, "nose", feather=1)) > 0
    lip = np.zeros(ex.shape, np.uint8)
    cv2.fillPoly(lip, [cv2.convexHull(pts[LIPS].astype(np.int32))], 1)
    r = max(3, int(w * 0.02)) | 1
    ex = cv2.dilate((ex | (lip > 0)).astype(np.uint8), np.ones((r, r), np.uint8)) > 0
    # 윤곽 5% 안쪽만 — 첫 시험(v54 0002)에서 턱선 옆 어두운 그늘(머리카락·턱 그림자)이 결로 옮겨 와 얼룩이 됐다
    return _face_inner(rgb, pts, 0.05) & ~ex & (band_soft < 0.03)


def _transplant(detail: np.ndarray, src_ok: np.ndarray, need: np.ndarray, w: int, cx: float) -> np.ndarray:
    """need 자리마다 가까운 옆 피부(src_ok)의 결을 그대로 옮겨 온다(평균 내면 결이 죽으니 한 곳에서 통째로).
    방향 우선순위 = 바깥쪽(볼) 수평 → 바깥 위 → 위 → 바깥 아래 → 안쪽. 반환 = 옮긴 결(못 찾은 자리는 원래 결)."""
    import cv2
    h = detail.shape[0]
    out = detail.copy()
    done = ~need
    for mag in (0.035, 0.05, 0.07):
        d = w * mag
        for dx, dy in ((1, 0), (0.7, -0.7), (0, -1), (0.7, 0.7), (0, 1), (-0.7, -0.7), (-1, 0)):
            for side in (-1, 1):                              # 사진 왼쪽 반은 바깥 = -x, 오른쪽 반은 +x
                half = np.zeros_like(need)
                if side < 0:
                    half[:, : int(cx)] = True
                else:
                    half[:, int(cx):] = True
                todo = ~done & half
                if not todo.any():
                    continue
                sx, sy = side * dx * d, dy * d
                M = np.float32([[1, 0, -sx], [0, 1, -sy]])   # 결과(x,y) ← 원본(x+sx, y+sy)
                ok = cv2.warpAffine(src_ok.astype(np.uint8), M, (detail.shape[1], h), flags=cv2.INTER_NEAREST, borderValue=0) > 0
                src = cv2.warpAffine(detail, M, (detail.shape[1], h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                take = todo & ok
                out[take] = src[take]
                done |= take
            if done.all():
                return out
    return out


def _fill_patch(rgb, pts, cm: np.ndarray, strength: float, sf: float, fine: float):
    """cm(0~1) 자리를 옆 피부로 메운다 — 14차 공용 루틴(erase·erase_center).
    바탕(흐림 fine) = 띠 밖 피부의 정규화 흐림(sf)으로, 결(원본 − 바탕) = TRANSPLANT 면 옆 피부에서 옮겨 온 결로.
    세 채널(L·a·b) 모두. TRANSPLANT 가 꺼져 있으면 13차 그대로(L 바탕만 채움)."""
    import cv2
    w = rgb.size[0]
    lab = _L(rgb)
    a = np.clip(strength, 0, 1) * cm
    valid = np.clip(1.0 - cm * 1.5, 0, 1)
    if TRANSPLANT:
        # 채울 값도 얼굴 안 피부로만 — 14차 첫 시험에서 턱선·3/4 먼 쪽 띠가 배경(회청색)까지 평균 내 멍 같은 얼룩이 됐다
        #   (13차까지는 L 만 채워 색이 안 옮았고 윤곽 자르기가 가렸다. a·b 까지 채우자 드러났다)
        face_in = _face_inner(rgb, pts, 0.01).astype(np.float32)
        valid = valid * face_in
    chans = (0, 1, 2) if TRANSPLANT else (0,)
    if TRANSPLANT:
        src_ok = _skin_ok(rgb, pts, cm)
        need = cm > 0.02
        cx = float(pts[1][0])
        s_det = max(1.0, w * DETAIL_SIGMA)
    if TRANSPLANT:
        # 점·큰 잡티는 떠 오지 않는다 — 14차 첫 시험 v54 0001 에서 점(모반)이 띠 안에 여러 개 복제됐다(유령 점).
        #   결 지도(L)에서 −3σ 보다 어두운 덩어리와 그 둘레(w×1%)는 원천에서 뺀다. 잔 잡티(−2~−3σ)는 그대로 옮긴다.
        Lb = lab[:, :, 0] - cv2.GaussianBlur(lab[:, :, 0], (0, 0), s_det)
        blob = (Lb < -3.0 * float(Lb[src_ok].std())) if src_ok.any() else np.zeros_like(src_ok)
        r = max(3, int(w * 0.02)) | 1
        blob_d = cv2.dilate(blob.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))) > 0
        src_ok = src_ok & ~blob_d
        # 띠 **안의** 점(모반)은 지우지 않는다 — 같은 시험에서 입꼬리 아래 점이 메우기에 같이 사라졌다(사람이 바뀐다).
        #   골 선은 길쭉하니 둥근 덩어리(가로·세로 w×2.5% 이하, 채움 40% 이상)만 점으로 본다.
        #   ⚠ 골 선 토막도 짧으면 둥글게 보인다(첫 판에서 선 조각을 점으로 남겨 0002 가 -48 → -36% 로 덜 메워졌다) →
        #   점은 둥글고(가로세로 비 0.5~2) **아주 진하다**(가장 어두운 곳이 −6σ 아래 — 실측 점 −8σ 이상, 골 선 −3~−5σ).
        keep = np.zeros(blob.shape, np.uint8)
        sd0 = float(Lb[src_ok].std()) if src_ok.any() else 1.0
        n, cc, st, _ = cv2.connectedComponentsWithStats((blob & need).astype(np.uint8))
        for j in range(1, n):
            x, y, bw, bh, ar = st[j]
            if (max(bw, bh) <= w * 0.025 and ar >= 0.4 * bw * bh and ar >= 4 and 0.5 <= bw / bh <= 2
                    and float(Lb[cc == j].min()) < -MOLE_SIGMA * sd0):
                keep[cc == j] = 1
        mole = cv2.GaussianBlur(cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))).astype(np.float32), (0, 0), w * 0.003)
        mole = np.clip(mole * 2, 0, 1)
    for c in chans:
        C = lab[:, :, c]
        if TRANSPLANT:
            base = cv2.GaussianBlur(C, (0, 0), s_det)
            tex = C - base
            tex_new = _transplant(tex, src_ok, need, w, cx)
            lim = 2.5 * float(tex[src_ok].std()) if src_ok.any() else None
            if lim:                                       # 옮겨 온 결 중 튀는 덩어리(점 하나가 아니라 그림자)는 잘라 낸다
                tex_new = np.clip(tex_new, -lim, lim)
        else:
            base = cv2.GaussianBlur(C, (0, 0), fine)
            tex = tex_new = C - base
        den = cv2.GaussianBlur(valid, (0, 0), sf)
        fill = cv2.GaussianBlur(base * valid, (0, 0), sf) / np.maximum(den, 1e-3)
        if TRANSPLANT and c == 0:
            # 윤곽 끝처럼 둘레에 얼굴이 거의 없는 자리는 채울 값이 없다 — 0 나누기 근처 값(청록 점)을 쓰지 말고 손대지 않는다.
            #   ⚠ 잣대는 '둘레의 얼굴 비율'이다(띠 비율로 재면 넓은 띠 한가운데까지 약해져 v54 0002 가 -48 → -34% 로 덜 메워졌다)
            a = a * np.clip(cv2.GaussianBlur(face_in, (0, 0), sf) / 0.2, 0, 1) * np.clip(den / 0.02, 0, 1)
        mix = tex * (1 - a) + tex_new * a
        if TRANSPLANT:                                    # 서로 다른 두 결을 섞으면 세기가 최대 1/√2 로 준다(=깨끗해짐) — 세기 보존
            mix = mix / np.sqrt((1 - a) ** 2 + a ** 2)
            new = base * (1 - a) + fill * a + mix
            new = new * (1 - mole) + C * mole             # 점 자리는 원본 그대로
        else:
            new = base * (1 - a) + fill * a + mix
        lab[:, :, c] = np.clip(new, 0, 255)
    return Image.fromarray(cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB))


def _rings(rgb, pts, core_map):
    """띠 안(core) · 주변 고리(ring) 불리언 — 자·밝기 묶기 공용. ring = 띠에서 w×0.006~0.02 떨어진 바로 옆 피부
    (넓게 잡으면 볼 능선 하이라이트가 들어와 '띠가 주변보다 밝다'를 못 잡는다)."""
    import cv2
    w = rgb.size[0]
    core = core_map > 0.5
    k = lambda f: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, int(w * f) | 1),) * 2)  # noqa: E731
    near = cv2.dilate(core.astype(np.uint8), k(0.012)) > 0
    far = cv2.dilate(core.astype(np.uint8), k(0.04)) > 0
    ring = far & ~near & _skin_ok(rgb, pts, core_map * 0)
    return core, ring


def band_stats(img: Image.Image, core_map: np.ndarray, pts=None) -> dict:
    """띠 안팎 자 (14차 연서님 "띠 안팎 밝기 차·잡티 밀도 차를 재는 자 추가해서 튀면 다시").

    core_map = 메운 띠(0~1, 메우기 직전 B 에서 찾은 line_map — 재촬영 뒤 사진에도 같은 자리로 댄다).
    dL        = 띠 안 평균 밝기 − 주변 고리 평균(L, 0~100 스케일 아님 — OpenCV L 0~255). + 면 띠가 더 밝다(= 하얗게 뜸).
    tex_ratio = 띠 안 결 세기(잔결 표준편차, L) ÷ 주변 결 세기. 1 = 같은 결, 작을수록 '너무 깨끗'.
    spot_ratio= 띠 안 잡티 밀도 ÷ 주변 밀도. 잡티 = 결 지도에서 주변 기준 −2σ 보다 어두운 점.
    chroma_ratio = 색 얼룩(a·b 결 표준편차) 띠 안 ÷ 주변."""
    import cv2
    rgb = img.convert("RGB")
    pts = L.detect(rgb) if pts is None else pts
    if pts is None or core_map is None:
        return {"measured": False}
    w = rgb.size[0]
    lab = _L(rgb)
    core, ring = _rings(rgb, pts, core_map)
    if core.sum() < 50 or ring.sum() < 200:
        return {"measured": False}
    s = max(1.0, w * DETAIL_SIGMA)
    det = [lab[:, :, c] - cv2.GaussianBlur(lab[:, :, c], (0, 0), s) for c in range(3)]
    sd = lambda x, m: float(x[m].std())  # noqa: E731
    thr = -2.0 * sd(det[0], ring)
    spot = lambda m: float((det[0][m] < thr).mean())  # noqa: E731
    chroma = lambda m: float(np.hypot(det[1][m].std(), det[2][m].std()))  # noqa: E731
    return {"measured": True,
            "dL": round(float(lab[:, :, 0][core].mean() - lab[:, :, 0][ring].mean()), 2),
            "tex_ratio": round(sd(det[0], core) / max(sd(det[0], ring), 1e-6), 3),
            "spot_ratio": round(spot(core) / max(spot(ring), 1e-6), 3),
            "chroma_ratio": round(chroma(core) / max(chroma(ring), 1e-6), 3)}


def band_gate(stats: dict, cfg: dict) -> list:
    """band_stats 가 문턱을 넘은 항목 이름 목록(빈 목록 = 통과). 못 쟀으면 [] (fail-open). 문턱 정본 = clinical_rig.yaml fold_fill.band_gate."""
    if not stats or not stats.get("measured") or not cfg:
        return []
    bad = []
    if cfg.get("dL_max") is not None and stats["dL"] > float(cfg["dL_max"]):
        bad.append("bright")
    if cfg.get("tex_min") is not None and stats["tex_ratio"] < float(cfg["tex_min"]):
        bad.append("clean")
    if cfg.get("spot_min") is not None and stats["spot_ratio"] < float(cfg["spot_min"]):
        bad.append("spotless")
    return bad


def clamp_dark(img: Image.Image, core_map: np.ndarray, pts=None, margin: float = DARK_MARGIN):
    """메운 자리 평균 밝기를 주변 평균 − margin 이하로 묶는다(넘친 만큼만 띠 모양대로 내린다). 14차."""
    import cv2
    rgb = img.convert("RGB")
    pts = L.detect(rgb) if pts is None else pts
    if pts is None:
        return rgb, {"applied": False}
    lab = _L(rgb)
    core, ring = _rings(rgb, pts, core_map)
    if core.sum() < 50 or ring.sum() < 200:
        return rgb, {"applied": False}
    over = float(lab[:, :, 0][core].mean() - lab[:, :, 0][ring].mean()) + margin
    if over <= 0:
        return rgb, {"applied": False, "dL": round(over - margin, 2)}
    wmean = float(core_map[core].mean())
    lab[:, :, 0] = np.clip(lab[:, :, 0] - over * core_map / max(wmean, 1e-3), 0, 255)
    return Image.fromarray(cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB)), {"applied": True, "lowered": round(over, 2)}


def erase(img: Image.Image, pts=None, strength: float = 1.0, wm=None):
    """골 선 지우기(주) — 선 띠를 **옆 피부로 메운다**. strength 0~1(1 = 띠 한가운데를 옆 피부 값으로 완전히 대체).

    바탕(잔결 흐림)만 바꾸고 잔결(원본 − 바탕: 모공·솜털)은 되얹는다. 메울 값 = 띠 밖 피부의 가중 평균(정규화 흐림) —
    골 아래쪽 어두움과 위쪽 볼 능선의 밝음이 같이 평균돼 단차가 사라진다.
    ⚠ 9차 첫 판(단차를 빼기)은 세기를 올릴수록 띠 가장자리에 새 경계가 생겨 선명도가 오히려 올랐다(세기 3.0: 2.65→3.17) — 메우기로 바꿨다."""
    import cv2
    rgb = img.convert("RGB")
    pts = L.detect(rgb) if pts is None else pts
    if pts is None:
        return rgb, {"applied": False, "reason": "얼굴 점 못 찾음"}
    w = rgb.size[0]
    wm = line_map(rgb, pts) if wm is None else wm
    res = _fill_patch(rgb, pts, wm, strength, sf=w * 0.02, fine=max(1.0, w * 0.0015))
    return res, {"applied": True, "erase": round(float(strength), 3), "line_px": int((wm > 0.5).sum())}


def erase_center(img: Image.Image, pts=None, zone=None, strength: float = 1.0):
    """골 한가운데 가는 접힌 선 지우기 (2026-09-28 11차 연서님 "넓은 그늘은 메워졌는데 중심 접힌 선이 남는다 — 좁은 폭으로 한 번 더").

    넓은 메우기(erase)는 바탕을 w×0.02 흐림으로 채워 **넓은 그늘**은 지우지만, 폭 2~4px 짜리 실 선은 잔결(tex) 쪽으로 분류돼
    그대로 되얹혔다. 여기서는 좁은 자(w×0.002 vs w×0.008)로 실 선만 찾아 좁은 띠(w×0.006)를 좁은 흐림(w×0.006)으로 메운다.
    zone = 넓은 메우기의 선 띠(0~1) — 그 안에서만 찾는다(입술 선·콧볼 선을 건드리지 않게)."""
    import cv2
    rgb = img.convert("RGB")
    pts = L.detect(rgb) if pts is None else pts
    if pts is None:
        return rgb, {"applied": False, "reason": "얼굴 점 못 찾음"}
    w = rgb.size[0]
    zone = line_map(rgb, pts) if zone is None else zone
    lab = _L(rgb); Lc = lab[:, :, 0]
    fine = -np.minimum(cv2.GaussianBlur(Lc, (0, 0), max(0.8, w * 0.002)) - cv2.GaussianBlur(Lc, (0, 0), w * 0.008), 0)
    inside = zone > 0.3
    if not inside.any():
        return rgb, {"applied": False, "reason": "선 띠 없음"}
    thr = np.percentile(fine[inside], 80)
    thin = ((fine > thr) & inside).astype(np.uint8)
    n, cc, st, _ = cv2.connectedComponentsWithStats(thin)
    keep = np.zeros_like(thin)
    for j in range(1, n):                                  # 길쭉한 것만(모공 점 제외)
        x, y, bw, bh, area = st[j]
        if area > w * 0.02 and max(bw, bh) > w * 0.03:
            keep[cc == j] = 1
    r = max(3, int(w * 0.006)) | 1
    cm = cv2.GaussianBlur(cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))).astype(np.float32), (0, 0), w * 0.004)
    cm = np.clip(cm / max(float(cm.max()), 1e-6) * 1.3, 0, 1)
    # 14차: 이 좁은 띠가 '결까지 지운 매끈한 줄'의 주범이었다(v54 0000 은 넓은 메우기 0.001 — 이것만으로 목표 도달).
    res = _fill_patch(rgb, pts, cm, strength, sf=w * 0.006, fine=0.8)
    return res, {"applied": True, "center_px": int((cm > 0.5).sum())}


def edge_ratio(img: Image.Image, pts=None, sf: float = 0.02, side: str = None):
    """골 선 선명도 = 골 띠(코·입술 제외) 안 밝기 경사 상위 10% ÷ 볼 맨살 경사 상위 10%. 경사 흐림 = IPD×sf.

    side = "l" | "r" 면 그쪽 코 옆 띠(nasolabial_fold_l/_r)만 잰다 — 좌우 한쪽만 메워지는 사고(v53 0001)를 잡는 자.
    ⚠ l/r 은 MediaPipe 점 이름이라 **사진의 왼쪽**(49·129 쪽)이 l 이다(인물 기준 오른쪽). 볼 대조는 양쪽 그대로."""
    import cv2
    rgb = img.convert("RGB")
    pts = L.detect(rgb) if pts is None else pts
    if pts is None:
        return None
    ipd = _ipd(pts)
    m = np.asarray(L.region_mask(rgb, pts, REGION if side is None else f"nasolabial_fold_{side}", feather=1)) > 127
    ex = np.asarray(L.region_mask(rgb, pts, "nose", feather=1)) > 0
    lip = np.zeros(m.shape, np.uint8)
    cv2.fillPoly(lip, [cv2.convexHull(pts[LIPS].astype(np.int32))], 1)
    r = max(3, int(ipd * 0.05)) | 1
    ex = cv2.dilate((ex | (lip > 0)).astype(np.uint8), np.ones((r, r), np.uint8)) > 0
    mm = m & ~ex
    ck = np.zeros(m.shape, np.uint8)
    for c in (CHEEK_L, CHEEK_R):
        cv2.fillPoly(ck, [cv2.convexHull(pts[c].astype(np.int32))], 1)
    g = cv2.GaussianBlur(_L(rgb)[:, :, 0], (0, 0), max(0.5, ipd * sf))
    gm = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    top = lambda v: float(np.sort(v)[::-1][: max(1, len(v) // 10)].mean())  # noqa: E731
    return top(gm[mm]) / max(top(gm[ck > 0]), 1e-6)


def fill_to(img: Image.Image, edge_goal: float, shade_goal: float = None, cap: float = 1.0, center: bool = True,
            clamp: bool = True):
    """골 선 선명도가 edge_goal 이하가 되도록 메우기 세기를 이분 탐색(주), 이어서 그늘이 shade_goal 을 넘으면 밝히기(보조).

    상한 cap(1.0 = 띠 한가운데를 옆 피부로 완전히 대체)에서도 못 가면 capped=True. 목표 = 실제 쌍 After 의 선명도(tools/fold_shade_ref.py)."""
    rgb = img.convert("RGB")
    pts = L.detect(rgb)
    if pts is None:
        return rgb, {"applied": False, "reason": "얼굴 점 못 찾음"}
    wm = line_map(rgb, pts)
    _erase = erase
    def erase_(im, p, k):
        """선 띠는 한 번만 찾는다(세기만 바꿔 가며). 중심선 지우기(11차)도 **탐색 안에서** 같이 건다 —
        밖에서 나중에 얹으면 목표를 넘어가 버린다(첫 실행: 0001 목표 -55% 인데 -72% 로 나갔다)."""
        o, i = _erase(im, p, k, wm=wm)
        if center:
            o, ci = erase_center(o, p, zone=wm, strength=1.0)   # 실 선은 늘 끝까지 — 세기 탐색은 넓은 메우기만
            i = {**i, "center": ci.get("center_px")}
        return o, i
    e0 = edge_ratio(rgb, pts)
    info = {"edge_before": round(e0, 3), "edge_goal": round(edge_goal, 3)}
    out = rgb
    if e0 > edge_goal:
        hi_out, hi_info = erase_(rgb, pts, cap)
        if edge_ratio(hi_out, pts) > edge_goal:
            out, k, capped = hi_out, cap, True
        else:
            lo, hi = 0.0, cap
            for _ in range(10):
                mid = (lo + hi) / 2
                o, _i = erase_(rgb, pts, mid)
                if edge_ratio(o, pts) > edge_goal:
                    lo = mid
                else:
                    hi = mid
            out, _i = erase_(rgb, pts, hi); k, capped = hi, False
        info.update(erase=round(k, 3), capped=capped)
    if clamp:
        # 14차: 메운 자리가 주변보다 밝으면 그만큼 내린다(선명도 탐색 뒤 — 내리기는 단차를 만들지 않게 띠 모양대로)
        out, ci = clamp_dark(out, wm, pts)
        info["clamp"] = ci
    info["edge_after"] = round(edge_ratio(out, pts), 3)
    info["band"] = band_stats(out, wm, pts)
    info["_wm"] = wm                                      # 호출자(배치)가 재촬영 뒤 같은 자리를 재도록 — meta 에 넣기 전에 빼라
    if shade_goal is not None:
        s = shade(out, pts)
        if s > shade_goal:
            lo, hi = 0.0, 1.0
            for _ in range(10):
                mid = (lo + hi) / 2
                o, _i = lift(out, pts, mid)
                if shade(o, pts) > shade_goal:
                    lo = mid
                else:
                    hi = mid
            out, _i = lift(out, pts, hi)
            info["lift"] = round(hi, 3)
        info.update(shade_goal=round(shade_goal, 3), shade_after=round(shade(out, pts), 3))
    return out, {"applied": True, **info}


def side_drop(before: Image.Image, after: Image.Image, pb=None, pa=None) -> dict:
    """좌우 골 선 감소율(%, Before 대비) — {"l": -44.0, "r": -67.0, "gap": 23.0}. 못 재면 값 None."""
    pb = L.detect(before.convert("RGB")) if pb is None else pb
    pa = L.detect(after.convert("RGB")) if pa is None else pa
    out = {}
    for s in ("l", "r"):
        eb = edge_ratio(before, pb, side=s) if pb is not None else None
        ea = edge_ratio(after, pa, side=s) if pa is not None else None
        out[s] = None if not (eb and ea) else round((ea - eb) / eb * 100, 1)
    out["gap"] = None if None in (out["l"], out["r"]) else round(abs(out["l"] - out["r"]), 1)
    return out


def balance_sides(before: Image.Image, after: Image.Image, gap_max: float = 15.0, pct: float = 55.0):
    """좌우 자 (2026-09-28 13차 연서님 "한쪽만 메워져서 티가 나 — 좌우 따로 재서 차이가 크면 다시").

    v53 0001(3/4 컷): 사진 왼쪽 -44% / 오른쪽 -67%(차 23%p) → 제외. 먼 쪽은 띠가 좁고 골이 옅게 찍혀 상위 25% 문턱에
    골 위쪽만 걸렸다. 차가 gap_max 를 넘으면 **약한 쪽만** 문턱을 낮춰(상위 45%) 선을 다시 찾고, 그쪽 감소율이 강한 쪽에
    닿을 때까지 메우기 세기를 탐색한다(비용 0). 채택된 v53 3장의 좌우 차는 3·3·12%p — 15%p 는 그 위, 0001(23) 아래다.
    반환 (사진, 기록). 기록의 gap_after 가 여전히 크면 상위(배치)가 게이트로 다시 그리게 한다."""
    rgb = after.convert("RGB")
    pb, pa = L.detect(before.convert("RGB")), L.detect(rgb)
    sd = side_drop(before, rgb, pb, pa)
    rec = {"before": sd}
    if pa is None or sd["gap"] is None or sd["gap"] <= gap_max:
        return rgb, {**rec, "balanced": False}
    weak = "l" if sd["l"] > sd["r"] else "r"                 # 덜 줄어든(값이 큰) 쪽
    idx = 0 if weak == "l" else 1
    goal_pct = min(sd["l"], sd["r"])
    eb = edge_ratio(before, pb, side=weak)
    goal = eb * (1 + goal_pct / 100.0)
    wm = line_map(rgb, pa, pct=pct, sides=(idx,))
    lo, hi, best = 0.0, 1.0, rgb
    o, _i = erase(rgb, pa, 1.0, wm=wm)
    if edge_ratio(o, pa, side=weak) > goal:
        best, k = o, 1.0
    else:
        for _ in range(10):
            mid = (lo + hi) / 2
            o, _i = erase(rgb, pa, mid, wm=wm)
            if edge_ratio(o, pa, side=weak) > goal:
                lo = mid
            else:
                hi = mid
        best, _i = erase(rgb, pa, hi, wm=wm); k = hi
    after_sd = side_drop(before, best, pb, pa)
    return best, {**rec, "balanced": True, "weak": weak, "erase": round(k, 3), "after": after_sd}


# 8차 호환(세기 = 그늘 목표 감소율) — tools/fold_lift_pair.py --target 이 부른다.
CAP = 2.5


def lift_to(img: Image.Image, target_pct: float, ref_shade: float, region: str = REGION, cap: float = CAP):
    """골 그늘이 ref_shade(보통 Before) 대비 target_pct(%, 음수 = 감소)가 되도록 밝히기 세기를 이분 탐색한다."""
    rgb = img.convert("RGB")
    pts = L.detect(rgb)
    if pts is None or not ref_shade:
        return rgb, {"applied": False, "reason": "얼굴 점 못 찾음"}
    goal = ref_shade * (1 + target_pct / 100.0)
    s0 = shade(rgb, pts, region)
    if s0 <= goal:
        return rgb, {"applied": False, "reason": "이미 목표보다 옅음", "shade": round(s0, 3), "goal": round(goal, 3)}
    lo, hi = 0.0, cap
    out, info = lift(rgb, pts, hi, region)
    if shade(out, pts, region) > goal:
        return out, {**info, "capped": True, "shade_before_lift": round(s0, 3), "shade": round(shade(out, pts, region), 3), "goal": round(goal, 3)}
    for _ in range(14):
        mid = (lo + hi) / 2
        out, info = lift(rgb, pts, mid, region)
        if shade(out, pts, region) > goal:
            lo = mid
        else:
            hi = mid
    out, info = lift(rgb, pts, hi, region)
    return out, {**info, "capped": False, "shade_before_lift": round(s0, 3), "shade": round(shade(out, pts, region), 3), "goal": round(goal, 3)}
