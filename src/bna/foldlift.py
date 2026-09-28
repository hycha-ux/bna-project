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
    base = cv2.GaussianBlur(Lc, (0, 0), 0.8)
    tex = Lc - base
    valid = np.clip(1.0 - cm * 1.5, 0, 1)
    sf = w * 0.006
    fill = cv2.GaussianBlur(base * valid, (0, 0), sf) / np.maximum(cv2.GaussianBlur(valid, (0, 0), sf), 1e-3)
    a = np.clip(strength, 0, 1) * cm
    lab[:, :, 0] = np.clip(base * (1 - a) + fill * a + tex, 0, 255)
    res = Image.fromarray(cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB))
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


def fill_to(img: Image.Image, edge_goal: float, shade_goal: float = None, cap: float = 1.0, center: bool = True):
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
