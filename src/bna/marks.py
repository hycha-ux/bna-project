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


def overlay(img: Image.Image, pts=None, *, flush_delta: float = 5.0, n_spots: int = 40, gloss: float = 1.6,
            bumps: float = 0.08, seed: int = 0, layers=("flush", "spots", "bumps", "gloss")) -> tuple:
    """(결과, 기록). flush_delta = 볼마다 붉은 기(R−(G+B)/2) 올릴 양. n_spots = 한쪽 볼 점 수(대략).
    bumps = 볼록 그림자 세기(0 이면 끔). 기본값 = 10-06 빌디 2차 보정(홍조 낮게·광 세게·볼록 아주 약하게)."""
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

    if "spots" in layers:
        out, rec["spots_drawn"] = _spots(out, ms, fw, n_spots, rng, keep)

    if "bumps" in layers and bumps > 0:
        out, rec["bumps_drawn"] = _bumps(out, ms, fw, bumps, rng, keep)

    if "gloss" in layers and gloss > 0:
        # 젖은 광: 큰 층 밝기(튀어나온 면) 상위를 부드럽게 골라 스크린. 광 세기 × (1 + 잔결) → 모공은 광 아래 어둡게 남는다
        Lm = cv2.cvtColor((out * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
        big = cv2.GaussianBlur(Lm, (0, 0), fw * 0.012)   # 중간 크기 — 광이 얼굴 굴곡을 따라 끊기게
        oval = np.zeros((H, W), np.uint8)
        cv2.fillPoly(oval, [pts[L.FACE_OVAL].astype(np.int32)], 1)
        face = _soft(cv2.erode(oval, np.ones((int(fw * 0.03) | 1,) * 2, np.uint8)) > 0, fw * 0.02)
        vals = big[oval > 0]
        lo, hi = np.percentile(vals, 45), np.percentile(vals, 99)
        hl = np.clip((big - lo) / (hi - lo + 1e-6), 0, 1) ** 1.6
        # 10-06 빌디 "거의 안 보인다 — 코·볼 위쪽에 하이라이트": 콧등·코끝·광대 위에 자리 지도를 얹어 그쪽만 세게
        spot = np.zeros((H, W), np.float32)
        for i, rad in ((6, 0.05), (197, 0.05), (195, 0.05), (5, 0.05), (4, 0.06), (116, 0.07), (345, 0.07), (117, 0.06), (346, 0.06)):
            cv2.circle(spot, tuple(int(v) for v in pts[i]), max(2, int(fw * rad)), 1.0, -1)
        spot = np.clip(_soft(spot > 0, fw * 0.05) * 1.5, 0, 1)
        where = 0.35 + 0.65 * spot
        streak = np.clip(0.75 + 0.35 * _lowfreq_noise((H, W), fw * 0.025, rng), 0.3, 1.3)   # 겔이 고르지 않게
        fine = Lm - cv2.GaussianBlur(Lm, (0, 0), fw * 0.004)
        fine = np.clip(1 + fine / (fine[oval > 0].std() + 1e-6) * 0.6, 0.1, 2.0)   # 모공은 광 아래 어둡게 남는다
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


def _spots(arr, ms, fw, n, rng, keep):
    """무작위 점. 최소 간격을 점마다 다르게(0~1.8×기본) → 격자가 안 생기고, 30% 는 앞 점 옆에 몰리게."""
    import cv2
    H, W = arr.shape[:2]
    out = arr.copy()
    drawn = 0
    yy, xx = np.mgrid[0:H, 0:W]
    for m in ms:
        ys, xs = np.nonzero(m)
        if len(ys) == 0:
            continue
        # 볼 가장자리 가까이엔 덜: 거리 변환으로 가중
        dist = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 5)[ys, xs]
        p = np.clip(dist / (fw * 0.04), 0.15, 1.0)
        p = p / p.sum()
        # 점 수는 보이는 볼 넓이에 비례(3/4 각도 먼 볼이 좁은데 같은 수를 넣으면 띠처럼 몰린다). 정면 한쪽 볼 ≈ 0.05 fw²
        area = m.sum() / (fw * fw)
        cnt = int(n * float(np.clip(area / 0.05, 0.25, 1.3)) * rng.uniform(0.8, 1.2))
        placed = []
        tries = 0
        while len(placed) < cnt and tries < cnt * 40:
            tries += 1
            if placed and rng.random() < 0.2:           # 몰림(약하게 — 세게 몰면 멍처럼 보인다)
                cy, cx = placed[rng.integers(len(placed))]
                y, x = cy + rng.normal(0, fw * 0.02), cx + rng.normal(0, fw * 0.02)
                if not (0 <= int(y) < H and 0 <= int(x) < W and m[int(y), int(x)]):
                    continue
            else:
                i = rng.choice(len(ys), p=p)
                y, x = ys[i] + rng.random(), xs[i] + rng.random()
            gap = fw * 0.006 * rng.uniform(0.0, 1.8)
            if any((y - a) ** 2 + (x - b) ** 2 < gap * gap for a, b in placed):
                continue
            placed.append((y, x))
        for y, x in placed:
            # 10-06 빌디 "너무 작고 갈색 → 모공·잡티로 읽힌다": 지름 약 1.7배(0.5~0.9% 얼굴 폭, 가끔 1.1~1.5%),
            # 색은 보랏빛 붉은색(핏자국) — R 은 거의 안 빼고 G 를 많이·B 는 덜 뺀다(R·B 를 같이 빼면 갈색이 된다),
            # 가장자리는 번지게 — 심을 넓은 가우스로 그리고 둘레 번짐을 모든 점에 깐다
            #  (1차 시도 R 거의 안 빼기·진하기 0.35~0.7 = 형광 분홍 얼룩 → 와인빛 실측 비(R×0.6·G×0.3·B×0.5)로 되돌림)
            d = fw * (rng.uniform(0.0045, 0.0075) if rng.random() < 0.88 else rng.uniform(0.008, 0.011))
            sig = max(0.8, d / 2.0)
            r = int(sig * 8) + 2
            y0, y1, x0, x1 = max(0, int(y) - r), min(H, int(y) + r + 1), max(0, int(x) - r), min(W, int(x) + r + 1)
            ys_, xs_ = yy[y0:y1, x0:x1] - y, (xx[y0:y1, x0:x1] - x) * rng.uniform(0.8, 1.25)
            g = np.exp(-(ys_ ** 2 + xs_ ** 2) / (2 * sig * sig))
            kp = keep[y0:y1, x0:x1]
            a = rng.uniform(0.25, 0.5) * kp
            hue = rng.uniform(0, 1)                # 0 = 보랏빛 짙은 핏자국, 1 = 붉은 쪽
            absorb = np.array([0.34 - 0.10 * hue, 0.66, 0.42 + 0.10 * hue], np.float32)   # B 를 G 보다 덜 빼야 보랏빛(같이 빼면 갈색)
            halo = np.exp(-(ys_ ** 2 + xs_ ** 2) / (2 * (sig * rng.uniform(2.0, 2.8)) ** 2))   # 바늘 자리 둘레 번짐
            w = (g * a + halo * rng.uniform(0.05, 0.10) * kp)[..., None]
            out[y0:y1, x0:x1] = out[y0:y1, x0:x1] * (1 - np.clip(w, 0, 1) * absorb)
            drawn += 1
    return out, drawn


def _bumps(arr, ms, fw, amp, rng, keep):
    """볼록(10-06 빌디 "아주 낮은 세기로"): 낮고 불규칙한 융기를 그림자로만 — 높이 지도를 만들고 위에서 오는 빛으로 음영.
    격자·도장 금지: 위치는 무작위·크기·길쭉함·기울기 제각각, 서로 붙어 덩어리지기도. 피부는 곱으로만 바뀐다(결 유지)."""
    import cv2
    H, W = arr.shape[:2]
    h = np.zeros((H, W), np.float32)
    drawn = 0
    for m in ms:
        ys, xs = np.nonzero(m)
        if len(ys) == 0:
            continue
        area = m.sum() / (fw * fw)
        cnt = int(26 * float(np.clip(area / 0.05, 0.25, 1.3)) * rng.uniform(0.8, 1.2))
        for _ in range(cnt):
            i = rng.integers(len(ys))
            c = (int(xs[i]), int(ys[i]))
            ax = (max(2, int(fw * rng.uniform(0.006, 0.016))), max(2, int(fw * rng.uniform(0.004, 0.010))))
            cv2.ellipse(h, c, ax, float(rng.uniform(0, 180)), 0, 360, float(rng.uniform(0.4, 1.0)), -1)
            drawn += 1
    h = cv2.GaussianBlur(h, (0, 0), fw * 0.004)
    gy = cv2.Sobel(h, cv2.CV_32F, 0, 1, ksize=3)
    gx = cv2.Sobel(h, cv2.CV_32F, 1, 0, ksize=3)
    sh = -(gy * 0.9 + gx * 0.3)                        # 빛은 위·약간 왼쪽에서 — 윗면 밝고 아랫면 어둡게
    sh = sh / (np.abs(sh).max() + 1e-6)
    lift = 1 + amp * sh * keep + amp * 0.3 * h * keep    # 융기 윗면은 조금 밝게(부어 오른 면)
    return np.clip(arr * lift[..., None], 0, 1), drawn
