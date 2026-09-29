"""25차 입꼬리 메우기 고치기 (2026-09-29 연서님 24차 검수 "골 메우기가 입꼬리 주변에서 계속 흔들려").

오류 네 가지:
  ① 입꼬리 옆(팔자 끝↔마리오네트)이 거뭇하게 뭉개져 멍·얼룩 같다 — 수염 점과 결도 그 자리만 사라짐
  ② 마리오네트 쪽 트러블 자국이 After 에서 없어짐(필러는 트러블을 안 지운다)
  ③ 입가에 입술색이 피부로 번짐 — 메우기가 입술 픽셀을 재료로 가져갔다
  ④ 다른 컷은 한쪽 입꼬리 바로 옆 골 끝만 안 메워져 한쪽만 티가 남
고친 것(연서님 요청 1~6):
  1. 보호 마스크 `protect` = 입술(+여유 PROT_LIP_PX)·콧볼/콧구멍·튀는 점(어둡거나 붉은 작은 덩어리 = 점·잡티·트러블·수염 점).
     메우는 범위(cm 곱)와 재료(excl) 둘 다에서 빼고, 경계 앞 세기는 경사로로 0 까지 내린다(PROT_RAMP).
  2. 입꼬리 구역 `corner_zone` 은 띠 전체가 아니라 **골 중심선만 가늘게**(thin), 재료는 볼 쪽(입꼬리 바깥)에서만.
  3. 팔자 위·중간·아래(입꼬리) 3구간 × 좌우 감소율 `seg_drop` 기록, 아래 구간 좌우 차가 SEG_GAP_MAX 넘으면 약한 쪽 아래만 더 메움.
  5. 수염 자리(점 밀도 높은 곳)는 '주변 이하 밝기' 누르기를 BEARD_CLAMP 만큼만.
  (4 = texswap.feature_mask 의 입술·입꼬리선 여유를 입술 경계선만큼으로 좁힘, 6 = pigment.count(region="band"))
판정·기록은 전부 여기 한 곳 — 배치·도구가 같이 부른다.
"""
import numpy as np
from PIL import Image

from .qa import landmarks as L
from . import foldlift as FL

PROT_LIP_PX = 2            # 입술 여유(px, 1024 폭 기준 — 폭에 비례)
PROT_RAMP = 0.006          # 보호 경계 앞 세기 경사로 폭(w×)
SPOT_SIGMA = 3.0           # 튀는 점 = 잔결(L)이 피부 결 표준편차의 이 배 아래(어두움) 또는 a(붉음)가 이 배 위
SPOT_MM = (0.4, 6.0)       # 점 지름 범위(mm) — 모공(0.3 아래)·골 토막(길쭉)은 뺀다
EYE_MM = 90.0
CORNER_R0, CORNER_R1 = 0.15, 0.3   # 입꼬리 구역: 눈 사이 × R0 안은 완전히, R1 까지 옅어짐. 첫 판(0.45×1.5)은 구역이 팔자 아래
                                   #   절반을 덮어 e745 메우기가 -27.7% 에서 멈췄다(목표 -54.6)
THIN_W = 0.004             # 입꼬리 구역 중심선 폭(w×)
SEG_GAP_MAX = 15.0         # 아래 구간 좌우 감소율 차 상한(%p) — 13차 좌우 자와 같은 값
BEARD_CLAMP = 0.35         # 수염 자리 누르기 세기(1 = 종전 그대로)
BEARD_DENS = 0.012         # 점 밀도(면적 비) 이 이상이면 수염 자리


def _mm(pts):
    return float(np.linalg.norm(pts[263][:2] - pts[33][:2])) / EYE_MM


def _lip_mask(shape, pts, w):
    import cv2
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [cv2.convexHull(pts[FL.LIPS][:, :2].astype(np.int32))], 1)
    r = max(1, int(round(PROT_LIP_PX * w / 1024))) * 2 + 1
    return cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))) > 0


def spots(rgb: Image.Image, pts) -> np.ndarray:
    """튀는 점(불리언) — 얼굴 안 작은 둥근 덩어리 중 잔결 L 이 −SPOT_SIGMA σ 아래(점·잡티·수염 점) 또는
    a 가 +SPOT_SIGMA σ 위(트러블·붉은 자국). 골 선 토막은 길쭉해서 빠진다."""
    import cv2
    w = rgb.size[0]
    lab = FL._L(rgb)
    s = max(1.0, w * 0.004)
    dL = lab[:, :, 0] - cv2.GaussianBlur(lab[:, :, 0], (0, 0), s)
    da = lab[:, :, 1] - cv2.GaussianBlur(lab[:, :, 1], (0, 0), s)
    face = FL._face_inner(rgb, pts, 0.01)
    sdL, sda = float(dL[face].std()), float(da[face].std())
    cand = ((dL < -SPOT_SIGMA * sdL) | (da > SPOT_SIGMA * sda)) & face
    n, cc, st, _ = cv2.connectedComponentsWithStats(cand.astype(np.uint8))
    mm = _mm(pts)
    amin, amax = np.pi * (SPOT_MM[0] * mm / 2) ** 2, np.pi * (SPOT_MM[1] * mm / 2) ** 2
    keep = np.zeros(cand.shape, bool)
    for i in range(1, n):
        x, y, bw, bh, a = st[i]
        if amin <= a <= amax and max(bw, bh) <= 3 * max(1, min(bw, bh)) and a >= 0.35 * bw * bh:
            keep[cc == i] = True
    return keep


def protect(rgb: Image.Image, pts):
    """(보호 불리언, 세기 곱 0~1, 기록). 곱은 보호 자리 0 → PROT_RAMP 폭에 걸쳐 1."""
    import cv2
    w, h = rgb.size
    lip = _lip_mask((h, w), pts, w)
    nose = np.asarray(L.region_mask(rgb, pts, "nose", feather=1)) > 0
    from . import texswap
    nz = texswap._poly((h, w), pts, texswap.NOSE, max(1, int(round(2 * w / 1024))))
    sp = spots(rgb, pts)
    r = max(3, int(round(2 * w / 1024)) * 2 + 1)
    sp_d = cv2.dilate(sp.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))) > 0
    prot = lip | nose | nz | sp_d
    dist = cv2.distanceTransform((~prot).astype(np.uint8), cv2.DIST_L2, 3)
    mul = np.clip(dist / max(1.0, w * PROT_RAMP), 0, 1).astype(np.float32)
    return prot, mul, {"lip_px": int(lip.sum()), "spot_n": int(cv2.connectedComponents(sp.astype(np.uint8))[0] - 1),
                       "prot_frac": round(float(prot.mean()), 4)}


def corner_zone(rgb: Image.Image, pts):
    """(구역 0~1, 입꼬리 안쪽 불리언). 입꼬리(61·291) 둘레 원(눈 사이×CORNER_R), 안쪽 = 두 입꼬리 사이 x 범위."""
    import cv2
    w, h = rgb.size
    ipd = FL._ipd(pts)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    z = np.zeros((h, w), np.float32)
    for i in (61, 291):
        cx, cy = pts[i][:2]
        d = np.hypot(xx - cx, yy - cy) / ipd
        z = np.maximum(z, np.clip((CORNER_R1 - d) / (CORNER_R1 - CORNER_R0), 0, 1))
    x0, x1 = sorted((float(pts[61][0]), float(pts[291][0])))
    medial = (xx > x0) & (xx < x1) & (z > 0)
    return z, medial


def thin(wm: np.ndarray, w: int) -> np.ndarray:
    """띠(line_map)의 가운데 줄만 — 띠를 거리 변환해 가장 깊은 곳 근처만 남기고 THIN_W 폭으로."""
    import cv2
    core = (wm > 0.5).astype(np.uint8)
    if not core.any():
        return wm * 0
    dt = cv2.distanceTransform(core, cv2.DIST_L2, 3)
    loc = cv2.dilate(dt, np.ones((max(3, int(w * 0.01)) | 1,) * 2, np.uint8))
    ridge = ((dt >= loc * 0.8) & (dt > 1)).astype(np.uint8)
    r = max(3, int(w * THIN_W) | 1)
    t = cv2.GaussianBlur(cv2.dilate(ridge, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))).astype(np.float32), (0, 0), w * 0.002)
    return np.clip(t / max(float(t.max()), 1e-6) * 1.2, 0, 1)


def beard_weight(rgb: Image.Image, pts, sp: np.ndarray = None) -> np.ndarray:
    """누르기 세기 곱(0~1) — 튀는 점 밀도가 BEARD_DENS 이상인 입 둘레(수염 자리)는 BEARD_CLAMP 로."""
    import cv2
    w = rgb.size[0]
    sp = spots(rgb, pts) if sp is None else sp
    dens = cv2.GaussianBlur(sp.astype(np.float32), (0, 0), w * 0.02)
    b = np.clip((dens - BEARD_DENS) / BEARD_DENS, 0, 1)
    return (1 - b * (1 - BEARD_CLAMP)).astype(np.float32)


# ── 3구간 × 좌우 자 ──────────────────────────────────────────────────────────────
def _seg_masks(rgb, pts):
    """{(side, seg): 불리언} — 팔자 띠(코 옆+다리+마리오네트)를 콧볼 아래 ~ 입꼬리 ~ 턱 쪽으로 3등분."""
    out = {}
    y_top = float(max(pts[98][1], pts[327][1]))
    y_mc = float((pts[61][1] + pts[291][1]) / 2)
    y_bot = y_mc + (y_mc - y_top) * 0.6
    cuts = (y_top, y_top + (y_mc - y_top) * 0.5, y_mc - (y_mc - y_top) * 0.1, y_bot)
    H, W = rgb.size[1], rgb.size[0]
    yy = np.arange(H)[:, None] * np.ones((1, W))
    for i, s in enumerate(("l", "r")):
        band = np.asarray(L.region_mask(rgb, pts, f"_fold_side{i}", feather=1)) > 127
        for j, seg in enumerate(("up", "mid", "low")):
            out[(s, seg)] = band & (yy >= cuts[j]) & (yy < cuts[j + 1])
    return out


def _grad(rgb, pts, sf=0.02):
    import cv2
    g = cv2.GaussianBlur(FL._L(rgb)[:, :, 0], (0, 0), max(0.5, FL._ipd(pts) * sf))
    return np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))


def seg_edges(img: Image.Image, pts=None) -> dict:
    """구간별 골 선 선명도(foldlift.edge_ratio 와 같은 식: 상위 10% 경사 ÷ 볼 맨살 상위 10%). 입술·코·보호 자리는 뺀다."""
    import cv2
    rgb = img.convert("RGB")
    pts = L.detect(rgb) if pts is None else pts
    if pts is None:
        return {}
    gm = _grad(rgb, pts)
    ck = np.zeros(gm.shape, np.uint8)
    for c in (FL.CHEEK_L, FL.CHEEK_R):
        cv2.fillPoly(ck, [cv2.convexHull(pts[c][:, :2].astype(np.int32))], 1)
    top = lambda v: float(np.sort(v)[::-1][: max(1, len(v) // 10)].mean()) if len(v) else None  # noqa: E731
    base = top(gm[ck > 0]) or 1e-6
    ex = _lip_mask(gm.shape, pts, rgb.size[0]) | (np.asarray(L.region_mask(rgb, pts, "nose", feather=1)) > 0)
    out = {}
    for k, m in _seg_masks(rgb, pts).items():
        v = top(gm[m & ~ex])
        out[f"{k[0]}_{k[1]}"] = None if v is None else v / base
    return out


def seg_drop(before: Image.Image, after: Image.Image) -> dict:
    """구간×좌우 감소율(%, Before 대비) + 아래 구간 좌우 차."""
    eb, ea = seg_edges(before), seg_edges(after)
    out = {k: (None if not (eb.get(k) and ea.get(k)) else round((ea[k] - eb[k]) / eb[k] * 100, 1)) for k in eb}
    l, r = out.get("l_low"), out.get("r_low")
    out["low_gap"] = None if None in (l, r) else round(abs(l - r), 1)
    return out


# ── 본체 ──────────────────────────────────────────────────────────────────────
def fill_guarded(before: Image.Image, img: Image.Image, edge_goal: float, shade_goal=None, side_gap_max=None):
    """foldlift.fill_to 에 보호 마스크·입꼬리 규칙·수염 누르기를 얹고, 아래 구간 좌우를 맞춘다. (사진, 기록)."""
    rgb = img.convert("RGB")
    pts = L.detect(rgb)
    if pts is None:
        return rgb, {"applied": False, "reason": "얼굴 점 못 찾음"}
    w = rgb.size[0]
    wm0 = FL.line_map(rgb, pts)
    prot, mul, prec = protect(rgb, pts)
    z, medial = corner_zone(rgb, pts)
    wm = (wm0 * (1 - z) + thin(wm0, w) * z) * mul          # 입꼬리 구역은 중심선만, 보호 앞은 0
    excl = prot | medial                                   # 재료: 보호 자리·입꼬리 안쪽(입술 쪽) 제외 = 볼 쪽에서만
    bw = beard_weight(rgb, pts)
    out, info = FL.fill_to(rgb, edge_goal, shade_goal, wm=wm, excl=excl, cm_mul=mul, clamp_w=bw)
    info["guard"] = {**prec, "corner_px": int((z > 0.5).sum()), "beard_frac": round(float((bw < 0.99).mean()), 4)}
    info["_wm"] = info.get("_wm")
    if side_gap_max is not None:
        # 13차 좌우 자도 같은 보호·입꼬리 규칙으로 — 24차는 여기서 보호 없이 다시 메워 입가가 번졌다(1b51 오른쪽 입꼬리)
        out, bi = FL.balance_sides(before, out, float(side_gap_max),
                                   wm_hook=lambda x: (x * (1 - z) + thin(x, w) * z) * mul, excl=excl)
        info["side_fill"] = bi
    # 3. 아래 구간 좌우 — 약한 쪽 아래만 더(목표 = 강한 쪽 아래 감소율)
    sd = seg_drop(before, out)
    info["seg"] = sd
    if sd.get("low_gap") is not None and sd["low_gap"] > SEG_GAP_MAX:
        weak = "l" if sd["l_low"] > sd["r_low"] else "r"
        segm = _seg_masks(rgb, pts)[(weak, "low")]
        import cv2
        sm = cv2.GaussianBlur(segm.astype(np.float32), (0, 0), w * 0.006)
        wlow = FL.line_map(out, pts, pct=55.0, width=0.018, sides=(0 if weak == "l" else 1,))
        wlow = (wlow * (1 - z) + thin(wlow, w) * z) * mul * sm
        eb = seg_edges(before).get(f"{weak}_low")
        goal = eb * (1 + min(sd["l_low"], sd["r_low"]) / 100.0) if eb else None
        k_used = None
        if goal:
            lo, hi, best = 0.0, 1.0, None
            o, _ = FL.erase(out, pts, 1.0, wm=wlow, excl=excl)
            if (seg_edges(o, pts).get(f"{weak}_low") or 9) > goal:
                best, k_used = o, 1.0
            else:
                for _ in range(8):
                    mid = (lo + hi) / 2
                    o, _ = FL.erase(out, pts, mid, wm=wlow, excl=excl)
                    if (seg_edges(o, pts).get(f"{weak}_low") or 9) > goal:
                        lo = mid
                    else:
                        hi = mid
                best, _ = FL.erase(out, pts, hi, wm=wlow, excl=excl); k_used = hi
            out = best
        info["seg_fix"] = {"weak": weak, "erase": None if k_used is None else round(k_used, 3), "after": seg_drop(before, out)}
    info["edge_after"] = round(FL.edge_ratio(out, pts), 3)
    return out, info
