"""임상 직후 흔적 얹기 — 모델 밖, 비용 0 (2026-09-30 빌디·연서님 "흔적은 우리가 얹는 쪽으로").

팔자 때처럼 편집 모델은 임상 직후 흔적(붉은 점·홍조·젖은 광)을 거의 안 그린다 → 기존 사진 위에 코드로 얹는다.
피부를 새로 그리지 않는다(09-29 v59 하얀 얼룩) — 세 층 모두 원본 픽셀에 곱하거나(점·홍조) 스크린으로 더할(광) 뿐이라
모공·잔털 결은 그대로 비친다. 윤곽 부위(콧구멍·콧볼·눈·눈썹·입술·입꼬리선·헤어라인)는 23차 안전 합치기와 같은
texswap.feature_mask 로 뺀다.

  ① 붉은 점  — 볼 부위에 무작위 위치(격자·도장 금지: 최소 간격도 점마다 다르게), 크기·색·진하기 제각각, 가끔 몇 개씩 몰림
  ② 홍조     — 볼에 은은한 분홍. 저주파 얼룩 무늬로 세기를 흔들고 넓게 흐려 경계가 없다. 목표 = 참조 직후−2주 후 붉은 기 차
  ③ 젖은 광  — 얼굴 튀어나온 면(밝은 큰 층)에 스크린 광. 광 세기에 원본 잔결을 곱해 모공이 광 아래로 비친다

붉은 기 자 = R − (G+B)/2 의 볼 부위 평균(빌디 자와 같은 식). 점 탐지 자 = 붉은 기 − 주변(중앙값) 이 문턱을 넘는 작은 덩이.
"""
import numpy as np
from PIL import Image

from .qa import landmarks as L
from . import texswap as T

# 볼 부위(사진 왼쪽 = 사람 오른볼). 눈 밑~광대 아래 · 코 옆~턱선. 오른쪽은 좌우 짝 점
CHEEK_0 = [116, 117, 118, 119, 100, 142, 203, 206, 216, 212, 214, 135, 138, 215, 177, 137, 227, 123, 147, 187, 192, 213]
CHEEK_1 = [345, 346, 347, 348, 329, 371, 423, 426, 436, 432, 434, 364, 367, 435, 401, 366, 447, 352, 376, 411, 416, 433]

SPOT_THR = 10.0      # 점 탐지: 붉은 기 − 주변 중앙값 문턱
SPOT_BG = 0.035      # 주변 중앙값 창(얼굴 폭 ×)
SPOT_MAX_AREA = 0.0009   # 점 하나 최대 넓이(얼굴 폭² ×) — 넘으면 점이 아니라 홍조 얼룩


def face_w(pts) -> float:
    return float(np.linalg.norm(pts[454] - pts[234]))


def cheek_masks(img: Image.Image, pts, hair: bool = True):
    """(볼0, 볼1) bool — 볼 껍질 ∩ 얼굴 윤곽 − 윤곽 부위(23차 feature_mask 재사용)."""
    import cv2
    W, H = img.size
    oval = np.zeros((H, W), np.uint8)
    cv2.fillPoly(oval, [pts[L.FACE_OVAL].astype(np.int32)], 1)
    feat = T.feature_mask((W, H), pts, img if hair else None, lip_grow=0.004)
    out = []
    for idx in (CHEEK_0, CHEEK_1):
        m = T._poly((H, W), pts, idx)
        out.append(m & (oval > 0) & ~feat)
    return out


def redness(arr: np.ndarray) -> np.ndarray:
    a = arr.astype(np.float32)
    return a[..., 0] - (a[..., 1] + a[..., 2]) / 2


def spot_stats(img: Image.Image, pts, mask: np.ndarray) -> dict:
    """붉은 점 개수·크기·붉은 기(점 빼고 바탕)."""
    import cv2
    arr = np.asarray(img.convert("RGB"))
    r = redness(arr)
    fw = face_w(pts)
    k = int(fw * SPOT_BG) | 1
    rb = cv2.medianBlur(np.clip(r + 128, 0, 255).astype(np.uint8), max(3, k)).astype(np.float32) - 128
    d = (r - rb) * mask
    n, lab, st, _ = cv2.connectedComponentsWithStats((d > SPOT_THR).astype(np.uint8), 8)
    amax = SPOT_MAX_AREA * fw * fw
    areas = [st[i, cv2.CC_STAT_AREA] for i in range(1, n) if 1 < st[i, cv2.CC_STAT_AREA] <= amax]
    spot_px = np.isin(lab, [i for i in range(1, n) if 1 < st[i, cv2.CC_STAT_AREA] <= amax])
    bg = mask & ~cv2.dilate(spot_px.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    return dict(red=round(float(r[mask].mean()), 2), red_bg=round(float(r[bg].mean()), 2),
                spots=len(areas), spots_per_fw2=round(len(areas) / (mask.sum() / fw / fw), 1),
                spot_d_med=round(float(np.sqrt(np.median(areas)) / fw * 1000), 2) if areas else None)


def measure(img: Image.Image, pts=None, hair=True) -> dict:
    pts = L.detect(img) if pts is None else pts
    ms = cheek_masks(img, pts, hair)
    both = ms[0] | ms[1]
    rec = spot_stats(img, pts, both)
    rec["side"] = [spot_stats(img, pts, m)["red"] for m in ms]
    # 광: 볼 부위 밝기 상위 2% 가 중앙값보다 얼마나 밝은가(번들거림 대용 자, 사람 간 비교는 참고치)
    Lc = np.asarray(img.convert("L"), np.float32)[both]
    rec["gloss"] = round(float(np.percentile(Lc, 98) - np.median(Lc)), 1)
    return rec


def measure_ref(img: Image.Image) -> dict:
    """참조 사진(코~턱 잘린 컷)용 — 눈이 틀 밖이라 볼 위쪽 점이 틀 밖에 찍힌다 → 볼 껍질을 사진 위 끝까지 늘려 잰다."""
    import cv2
    pts = L.detect(img)
    W, H = img.size
    feat = T.feature_mask((W, H), pts, img, lip_grow=0.004)
    ms = []
    for idx in (CHEEK_0, CHEEK_1):
        q = pts[idx].copy()
        up = q.copy()
        up[:, 1] = 5
        m = np.zeros((H, W), np.uint8)
        cv2.fillPoly(m, [cv2.convexHull(np.vstack([q, up]).astype(np.int32))], 1)
        ms.append((m > 0) & ~feat)
    r = redness(np.asarray(img.convert("RGB")))
    both = ms[0] | ms[1]
    rgb = np.asarray(img.convert("RGB"), np.float32)[both].mean(0)
    return dict(red=round(float(r[both].mean()), 2), side=[round(float(r[m].mean()), 2) for m in ms],
                rgb=[round(float(v), 1) for v in rgb])


def _lowfreq_noise(shape, scale_px, rng) -> np.ndarray:
    import cv2
    H, W = shape
    s = max(4, int(scale_px))
    g = rng.standard_normal((H // s + 2, W // s + 2)).astype(np.float32)
    g = cv2.resize(g, (W, H), interpolation=cv2.INTER_CUBIC)
    g = cv2.GaussianBlur(g, (0, 0), s * 0.6)
    return (g - g.mean()) / (g.std() + 1e-6)


def _soft(mask: np.ndarray, sig: float) -> np.ndarray:
    import cv2
    return np.clip(cv2.GaussianBlur(mask.astype(np.float32), (0, 0), sig), 0, 1)


def overlay(img: Image.Image, pts=None, *, flush_delta: float = 5.0, gloss: float = 1.6,
            bumps: float = 0.34, seed: int = 0, layers=("flush", "spots", "bumps", "gloss")) -> tuple:
    """(결과, 기록). flush_delta = 볼마다 붉은 기(R−(G+B)/2) 올릴 양. 점 수 = 볼록 자리 수(+떠도는 점 소수).
    bumps = 볼록 음영 세기(0 이면 끔). 기본값 = 10-06 빌디 3차 보정(볼록 보이게·점은 볼록 가운데·코 광 매끈)."""
    import cv2
    rng = np.random.default_rng(seed)
    pts = L.detect(img) if pts is None else pts
    W, H = img.size
    fw = face_w(pts)
    ms = cheek_masks(img, pts)
    both = ms[0] | ms[1]
    feat = T.feature_mask((W, H), pts, img, lip_grow=0.004)
    keep = 1.0 - _soft(feat, fw * 0.006)      # 윤곽 부위 0
    arr = np.asarray(img.convert("RGB")).astype(np.float32) / 255.0
    out = arr.copy()
    rec = dict(face_w=round(fw, 1))

    if "flush" in layers:
        # 홍조(10-06 빌디: 한쪽만 둥글게 진함=블러셔 → 양볼 고르게·넓게·경계 없이·약하게).
        #  볼마다 따로 넓은 평평한 지도(가운데 봉우리 금지 — 흐린 뒤 1.8배 잘라 윗면을 평평하게)를 만들고,
        #  볼마다 세기 k 를 따로 맞춰 3/4 컷에서도 먼 볼·가까운 볼의 붉은 기 증가가 같게 한다. 얼룩 흔들림은 ±8% 로만
        blot = np.clip(1 + 0.08 * _lowfreq_noise((H, W), fw * 0.18, rng), 0.85, 1.15)
        ks = []
        for m in ms:
            if m.sum() == 0:
                ks.append(0.0)
                continue
            grow = cv2.dilate(m.astype(np.uint8), np.ones((int(fw * 0.05) | 1,) * 2, np.uint8)) > 0
            base = np.clip(_soft(grow, fw * 0.07) * 1.8, 0, 1)
            wmap = base * blot * keep
            r0 = redness(out * 255)[m].mean()
            k = 0.0
            for _ in range(12):      # 목표 붉은 기에 맞춰 세기 k 를 찾는다(곱 → 선형 아님)
                k2 = k + (flush_delta - (redness(_tint(out, wmap, k) * 255)[m].mean() - r0)) / 180.0
                k = float(np.clip(k2, 0, 0.6))
            out = _tint(out, wmap, k)
            ks.append(round(k, 4))
        rec["flush_k"] = ks

    # 10-06 빌디 3차: 볼록이 '엠보'로 읽히게 하는 주인공 — 자리를 먼저 정하고(줄지어·불규칙), 붉은 점은 그 가운데(주사 자리)에 찍는다
    sites = _bump_sites(ms, fw, rng)
    rec["bump_sites"] = len(sites)

    if "bumps" in layers and bumps > 0:
        out = _bumps(out, sites, fw, bumps, keep)

    if "spots" in layers:
        out, rec["spots_drawn"], rec["spots_stray"] = _spots(out, ms, sites, fw, rng, keep)

    if "gloss" in layers and gloss > 0:
        # 젖은 광: 큰 층 밝기(튀어나온 면) 상위를 부드럽게 골라 스크린. 광 세기 × (1 + 잔결) → 모공은 광 아래 어둡게 남는다
        Lm = cv2.cvtColor((out * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
        big = cv2.GaussianBlur(Lm, (0, 0), fw * 0.012)   # 중간 크기 — 광이 얼굴 굴곡을 따라 끊기게
        # 10-06 빌디 3차 "콧등이 땀 맺힌 것처럼 오돌토돌": 코는 광 자리를 넓게 흐린 밝기로 고르고(작은 굴곡에 안 끊기게),
        # 아래에서 겔 얼룩·잔결 곱도 뺀다 → 매끈한 한 줄 번들거림. 볼 광은 2차 그대로
        nose = np.zeros((H, W), np.float32)
        for i in (6, 197, 195, 5, 4, 1):
            cv2.circle(nose, tuple(int(v) for v in pts[i]), max(2, int(fw * 0.045)), 1.0, -1)
        nose = np.clip(_soft(nose > 0, fw * 0.03) * 1.3, 0, 1)
        big = big * (1 - nose) + cv2.GaussianBlur(Lm, (0, 0), fw * 0.03) * nose
        oval = np.zeros((H, W), np.uint8)
        cv2.fillPoly(oval, [pts[L.FACE_OVAL].astype(np.int32)], 1)
        face = _soft(cv2.erode(oval, np.ones((int(fw * 0.03) | 1,) * 2, np.uint8)) > 0, fw * 0.02)
        vals = big[oval > 0]
        lo, hi = np.percentile(vals, 45), np.percentile(vals, 99)
        hl = np.clip((big - lo) / (hi - lo + 1e-6), 0, 1) ** 1.6
        # 10-06 빌디 "거의 안 보인다 — 코·볼 위쪽에 하이라이트": 콧등·코끝·광대 위에 자리 지도를 얹어 그쪽만 세게
        spot = np.zeros((H, W), np.float32)
        for i, rad in ((116, 0.07), (345, 0.07), (117, 0.06), (346, 0.06)):
            cv2.circle(spot, tuple(int(v) for v in pts[i]), max(2, int(fw * rad)), 1.0, -1)
        spot = np.clip(_soft(spot > 0, fw * 0.05) * 1.5, 0, 1)
        # 코 "과하다": 코 전체에 깔던 광(바탕 0.35)을 0.12 로 낮추고, 콧등 가운데 줄 하나에만 매끈한 광 띠
        #  (1회 시도 = 코 전체 0.6배 → 원래 굵은 모공 결이 광 아래로 그대로 비쳐 여전히 오돌토돌)
        band = np.zeros((H, W), np.float32)
        cv2.polylines(band, [pts[[6, 197, 195, 5, 4]].astype(np.int32)], False, 1.0, max(2, int(fw * 0.022)))
        band = np.clip(_soft(band > 0, fw * 0.012) * 1.4, 0, 1)
        where = (0.35 - 0.23 * nose) + 0.65 * np.maximum(spot, 0.75 * band)
        streak = np.clip(0.75 + 0.35 * _lowfreq_noise((H, W), fw * 0.025, rng), 0.3, 1.3)   # 겔이 고르지 않게
        streak = streak * (1 - nose) + nose
        fine = Lm - cv2.GaussianBlur(Lm, (0, 0), fw * 0.004)
        fine = np.clip(1 + fine / (fine[oval > 0].std() + 1e-6) * 0.6, 0.1, 2.0)   # 모공은 광 아래 어둡게 남는다
        fine = 1 + (fine - 1) * (1 - 0.85 * nose)
        # 상한 0.42: 2.2배·상한 0.7 시험에서 눈 밑·콧등이 결 없는 하얀 판이 됐다(09-29 v59 얼룩과 같은 꼴) — 상한은 잔결 곱 앞에 건다
        s = np.clip(np.clip(gloss * hl * where * streak * face * keep, 0, 0.42) * fine, 0, 0.6)[..., None]
        s = s * np.array([1.0, 0.99, 0.97], np.float32)      # 조명 색 거의 흰색
        out = 1 - (1 - out) * (1 - s)
        rec["gloss_mean"] = round(float(s[oval > 0].mean()), 4)

    return Image.fromarray(np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8)), rec


def _tint(arr, wmap, k):
    t = arr.copy()
    w = (wmap * k)[..., None]
    return t * (1 - w * np.array([0.03, 0.50, 0.26], np.float32))   # 분홍(연한 자주) — B 를 덜 빼야 주황이 안 된다


def _bump_sites(ms, fw, rng):
    """볼록 자리 [(y, x, 반지름, 볼 번호)]. 10-06 빌디 3차 "볼 전체에 대략 줄지어 — 칸 맞춘 격자·같은 모양 반복 금지".
    볼마다 줄 방향(수평 ±25°)·줄 간격·줄 안 간격을 따로 뽑고 자리마다 흔든다. 볼 가운데는 촘촘·바깥은 듬성
    (가장자리 거리로 솎음), 서로 겹쳐 덩어리지지 않게 최소 간격(자리 반지름 합의 0.9배)."""
    import cv2
    sites = []
    for si, m in enumerate(ms):
        if m.sum() == 0:
            continue
        H, W = m.shape
        dist = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 5)
        ys, xs = np.nonzero(m)
        cy, cx = ys.mean(), xs.mean()
        ang = np.deg2rad(rng.uniform(-25, 25))
        u = np.array([np.cos(ang), np.sin(ang)])          # 줄 방향(x, y)
        v = np.array([-u[1], u[0]])                       # 줄 사이 방향
        row = fw * rng.uniform(0.034, 0.042)
        span = np.hypot(H, W)
        mine = []
        for k in range(-int(span / row), int(span / row) + 1):
            off = k * row + rng.normal(0, row * 0.12)
            t = -span / 2 + rng.uniform(0, row)
            while t < span / 2:
                step = fw * rng.uniform(0.026, 0.044)
                t += step
                p = np.array([cx, cy]) + u * t + v * (off + rng.normal(0, row * 0.18))
                x, y = p[0] + rng.normal(0, step * 0.2), p[1]
                if not (0 <= int(y) < H and 0 <= int(x) < W and m[int(y), int(x)]):
                    continue
                if rng.random() > np.clip(dist[int(y), int(x)] / (fw * 0.06), 0.15, 1.0) * 0.9:
                    continue                              # 바깥은 듬성 · 가운데도 10% 는 빈자리
                r = fw * rng.uniform(0.010, 0.017)
                if any((y - a) ** 2 + (x - b) ** 2 < ((r + c) * 0.9) ** 2 for a, b, c, _ in mine):
                    continue
                mine.append((y, x, r, si))
        sites += mine
    return sites


def _bumps(arr, sites, fw, amp, keep):
    """볼록(10-06 빌디 3차 "눈에 보이게 — 낮은 돔에 위쪽 하이라이트·아래쪽 그늘"): 자리마다 낮은 돔 높이 지도를 깔고
    위·약간 왼쪽에서 오는 빛으로 음영. 그늘은 곱(결 유지), 하이라이트는 스크린(작게). 크기·길쭉함·기울기·높이 제각각."""
    import cv2
    H, W = arr.shape[:2]
    h = np.zeros((H, W), np.float32)
    rng = np.random.default_rng(len(sites) * 7919 + int(fw))
    for y, x, r, _ in sites:
        R = int(r * 2.2) + 2
        y0, y1, x0, x1 = max(0, int(y) - R), min(H, int(y) + R + 1), max(0, int(x) - R), min(W, int(x) + R + 1)
        if y1 <= y0 or x1 <= x0:
            continue
        gy, gx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        th = rng.uniform(0, np.pi)
        el = rng.uniform(0.75, 1.3)
        dx, dy = gx - x, gy - y
        a = (dx * np.cos(th) + dy * np.sin(th)) / (r * el)
        b = (-dx * np.sin(th) + dy * np.cos(th)) / (r / el)
        # 가우스 돔 — 1회 시도(가장자리가 급한 돔 q^1.5)는 음영이 테두리에 가는 초승달로 몰려 회색 '털·대시'로 읽혔다
        h[y0:y1, x0:x1] = np.maximum(h[y0:y1, x0:x1], rng.uniform(0.6, 1.0) * np.exp(-2.2 * (a * a + b * b)))
    gy = cv2.Sobel(h, cv2.CV_32F, 0, 1, ksize=3) / 8
    gx = cv2.Sobel(h, cv2.CV_32F, 1, 0, ksize=3) / 8
    sh = np.clip(-(gy * 0.9 + gx * 0.3) * fw * 0.016, -1.2, 1.2) * keep   # +: 윗면(빛 받음) −: 아랫면(그늘)
    # 그늘은 붉은 기를 남기는 곱(R 을 덜 뺀다 — 같이 빼면 회색 얼룩), 하이라이트는 스크린으로 그늘보다 세게, 부푼 면은 아주 살짝 밝게
    dark = (amp * 0.55 * np.maximum(-sh, 0))[..., None] * np.array([0.55, 0.85, 0.8], np.float32)
    out = arr * (1 - dark) * (1 + amp * 0.12 * h * keep)[..., None]
    # 하이라이트 0.9 시도 = 볼록마다 하얀 알갱이(비립종처럼 읽힘) → 0.5 + 넓게 흐림
    hi = cv2.GaussianBlur(np.maximum(sh, 0).astype(np.float32), (0, 0), fw * 0.003)
    s = (amp * 0.5 * hi)[..., None] * np.array([1.0, 0.99, 0.97], np.float32)
    return np.clip(1 - (1 - out) * (1 - s), 0, 1)


def _spots(arr, ms, sites, fw, rng, keep):
    """붉은 점(10-06 빌디·연서님 3차 "크기·색·모양이 똑같아 합성 티"): 볼록 가운데(주사 자리)에 85%, 볼록 없는 곳엔 소수(자리의 8%).
    점마다 ①크기 바늘 끝(0.15% 얼굴 폭)~조금 큼(0.8%), 전체로는 2차보다 작게 ②진하기 거의 안 보이는 연분홍~와인, 진한 건 소수
    (베타 분포 꼬리) ③모양 길쭉함·기울기·가장자리 번짐(지수) 제각각 + 덩어리 찌그러짐. 색: 연한 점은 분홍(R 거의 안 뺌),
    진한 점은 와인(G>B>R 로 뺌 — 10-06 교훈: R·B 같이 빼면 갈색)."""
    import cv2
    H, W = arr.shape[:2]
    out = arr.copy()
    centers = [(y + rng.normal(0, r * 0.12), x + rng.normal(0, r * 0.12)) for y, x, r, _ in sites if rng.random() < 0.85]
    n_on = len(centers)
    for m in ms:                                          # 떠도는 점: 서로·볼록 점과 떨어지게
        ys, xs = np.nonzero(m)
        if len(ys) == 0:
            continue
        want = int(0.08 * sum(1 for s in sites if m[int(s[0]), int(s[1])]))
        for _ in range(want * 30):
            if want <= 0:
                break
            i = rng.integers(len(ys))
            y, x = ys[i] + rng.random(), xs[i] + rng.random()
            if any((y - a) ** 2 + (x - b) ** 2 < (fw * 0.015) ** 2 for a, b in centers):
                continue
            centers.append((y, x))
            want -= 1
    pink = np.array([0.08, 0.55, 0.36], np.float32)
    wine = np.array([0.40, 0.70, 0.46], np.float32)
    for y, x in centers:
        d = fw * float(np.clip(rng.lognormal(np.log(0.0038), 0.45), 0.0015, 0.008))
        sig = max(0.6, d / 2.0)
        sx, sy = sig * rng.uniform(0.75, 1.6), sig * rng.uniform(0.7, 1.05)
        th = rng.uniform(0, np.pi)
        R = int(max(sx, sy) * 4) + 2
        y0, y1, x0, x1 = max(0, int(y) - R), min(H, int(y) + R + 1), max(0, int(x) - R), min(W, int(x) + R + 1)
        if y1 <= y0 or x1 <= x0:
            continue
        gy, gx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        dx, dy = gx - x, gy - y
        a = (dx * np.cos(th) + dy * np.sin(th)) / sx
        b = (-dx * np.sin(th) + dy * np.cos(th)) / sy
        q = (a * a + b * b) / 2
        g = np.exp(-q ** rng.uniform(0.7, 1.6))           # 지수 <1 = 가장자리 번짐, >1 = 또렷
        lump = rng.standard_normal((3, 3)).astype(np.float32)
        lump = cv2.resize(lump, (x1 - x0, y1 - y0), interpolation=cv2.INTER_CUBIC)
        g = g * np.clip(1 + 0.3 * lump, 0.4, 1.6)         # 완벽한 원 X — 덩어리 찌그러짐
        a_ = 0.18 + 0.70 * rng.beta(1.4, 2.6)             # 대부분 연함, 진한 와인은 꼬리 소수
        t = (a_ - 0.18) / 0.70
        absorb = pink * (1 - t) + wine * t
        w = np.clip(g * a_ * keep[y0:y1, x0:x1], 0, 0.9)[..., None]
        out[y0:y1, x0:x1] = out[y0:y1, x0:x1] * (1 - w * absorb)
    return out, len(centers), len(centers) - n_on
