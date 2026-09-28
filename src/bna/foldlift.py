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
SIDES = ("nasolabial_fold_l+marionette_l", "nasolabial_fold_r+marionette_r")
SMALL_FRAC, LARGE_FRAC, FEATHER_FRAC = 0.012, 0.12, 0.018
LIPS = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
CHEEK_L, CHEEK_R = [117, 118, 101, 50, 123, 116], [346, 347, 330, 280, 352, 345]   # 볼 맨살(골 없는 대조) — 눈 밑 볼 위쪽
for _i, _s in enumerate(SIDES):
    L.REGIONS.setdefault(f"_fold_side{_i}", _s)


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


def line_map(rgb: Image.Image, pts, pct: float = 75, width: float = 0.018) -> np.ndarray:
    """골 선을 따라가는 좁은 띠(0~1). 좌우 따로 문턱(상위 15%)을 잡고, 작은 점 덩어리(모공·잡티)는 버린다."""
    import cv2
    w = rgb.size[0]
    Lc = _L(rgb)[:, :, 0]
    valley = -np.minimum(cv2.GaussianBlur(Lc, (0, 0), w * 0.006) - cv2.GaussianBlur(Lc, (0, 0), w * 0.03), 0)
    keep = np.zeros(Lc.shape, np.uint8)
    for i in range(len(SIDES)):
        band = np.asarray(L.region_mask(rgb, pts, f"_fold_side{i}", feather=2)) > 127
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
    wm = cv2.GaussianBlur(cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))).astype(np.float32), (0, 0), w * 0.006)
    return np.clip(wm / max(float(wm.max()), 1e-6) * 1.2, 0, 1)


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
    lab = _L(rgb); Lc = lab[:, :, 0]
    base = cv2.GaussianBlur(Lc, (0, 0), max(1.0, w * 0.0015))
    tex = Lc - base
    valid = np.clip(1.0 - wm * 1.5, 0, 1)
    sf = w * 0.02
    fill = cv2.GaussianBlur(base * valid, (0, 0), sf) / np.maximum(cv2.GaussianBlur(valid, (0, 0), sf), 1e-3)
    a = np.clip(strength, 0, 1) * wm
    lab[:, :, 0] = np.clip(base * (1 - a) + fill * a + tex, 0, 255)
    res = Image.fromarray(cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB))
    return res, {"applied": True, "erase": round(float(strength), 3), "line_px": int((wm > 0.5).sum())}


def edge_ratio(img: Image.Image, pts=None, sf: float = 0.02):
    """골 선 선명도 = 골 띠(코·입술 제외) 안 밝기 경사 상위 10% ÷ 볼 맨살 경사 상위 10%. 경사 흐림 = IPD×sf."""
    import cv2
    rgb = img.convert("RGB")
    pts = L.detect(rgb) if pts is None else pts
    if pts is None:
        return None
    ipd = _ipd(pts)
    m = np.asarray(L.region_mask(rgb, pts, REGION, feather=1)) > 127
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


def fill_to(img: Image.Image, edge_goal: float, shade_goal: float = None, cap: float = 1.0):
    """골 선 선명도가 edge_goal 이하가 되도록 메우기 세기를 이분 탐색(주), 이어서 그늘이 shade_goal 을 넘으면 밝히기(보조).

    상한 cap(1.0 = 띠 한가운데를 옆 피부로 완전히 대체)에서도 못 가면 capped=True. 목표 = 실제 쌍 After 의 선명도(tools/fold_shade_ref.py)."""
    rgb = img.convert("RGB")
    pts = L.detect(rgb)
    if pts is None:
        return rgb, {"applied": False, "reason": "얼굴 점 못 찾음"}
    wm = line_map(rgb, pts)
    _erase = erase
    erase_ = lambda im, p, k: _erase(im, p, k, wm=wm)  # noqa: E731 — 선 띠는 한 번만 찾는다(세기만 바꿔 가며)
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
    info["edge_after"] = round(edge_ratio(out, pts), 3)
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
