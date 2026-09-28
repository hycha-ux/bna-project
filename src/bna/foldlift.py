"""팔자 그림자 들어올리기 (A안, 2026-09-28 7차 연서님 — 비용 0, 모델 밖에서 우리가 직접).

왜: v50·v51 에서 이미지 편집 모델은 '팔자를 옅게'를 문장·부위 마스크·목표 사진 어느 쪽으로 줘도 실행하지 않았다
    (골 대비 변화 ±0.4%, 5컷). 필러가 실제로 하는 일은 **골이 만드는 그림자를 얕게** 하는 것이라, 그 그림자만 들어올린다.

어떻게(피부결 보존):
  ① 밝기(LAB 의 L)를 '중간 크기 흐림(small)'과 '큰 흐림(large)'으로 나눈다. small − large 가 음수인 곳 = 주변보다 어두운 골.
  ② 그 어두운 양만 strength 비율로 되돌려 준다. 모공·솜털 같은 잔결(원본 − small)은 손대지 않는다.
  ③ 부위 = 코 옆 골 띠(nasal_fold, 콧볼 옆 → 입꼬리 바깥) × 부드러운 경계. 마스크 밖은 픽셀 그대로.
  색(a·b)은 안 건드린다 — 붉은기·패치 자국이 그대로 남는다.

세기 = 목표 감소율로 맞춘다 (2026-09-28 8차 연서님 "실제 쌍에서 재서 그 값을 A 목표로, 세기는 그 값에 맞춰"):
  `lift_to(after, target_pct, ref_shade)` 가 After 의 골 그늘이 **Before 대비 target_pct** 만큼 줄도록 strength 를 찾는다.
  목표 = tools/fold_shade_ref.py 로 잰 실제 쌍 감소율. 세기 상한은 아래 CAP —
  상한에 걸리면 기록에 `capped` 를 남긴다(그 사진은 목표까지 못 간 것이다).
⚠ 7차(v52)의 부위(nasolabial_marionette)는 윗입술·인중 쪽이라 골 자체엔 가장자리만 걸렸다 — 8차에 nasal_fold 로 바꿨다.
"""
import numpy as np
from PIL import Image

from .qa import landmarks as L

REGION = "nasal_fold"
SMALL_FRAC, LARGE_FRAC, FEATHER_FRAC = 0.012, 0.12, 0.018


def _parts(rgb, pts, region, feather):
    import cv2
    w = rgb.size[0]
    m = np.asarray(L.region_mask(rgb, pts, region, feather=feather if feather is not None else max(2, int(w * FEATHER_FRAC))),
                   dtype=np.float32) / 255.0
    lab = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2LAB).astype(np.float32)
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
    """(보정된 사진, 기록 dict). 얼굴 점을 못 찾으면 (원본, {"applied": False}) — fail-open."""
    import cv2
    rgb = img.convert("RGB")
    pts = L.detect(rgb) if pts is None else pts
    if pts is None:
        return rgb, {"applied": False, "reason": "얼굴 점 못 찾음"}
    m, lab, dark = _parts(rgb, pts, region, feather)
    lab[:, :, 0] = np.clip(lab[:, :, 0] - strength * dark * m, 0, 255)
    res = Image.fromarray(cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB))
    return res, {"applied": True, "strength": round(float(strength), 3), "region": region}


# 세기 상한 (2026-09-28 8차 실측): 1.0 으로는 목표 -50% 에 못 갔다(0000 -42% · 0001-75% 목표 -57%) — 들어올린 뒤 흐림을
#   다시 재면 골 둘레에 그늘이 남기 때문이다. 2.5 까지 연다. 1 을 넘기면 골 한가운데가 주변보다 살짝 밝아질 수 있어
#   확대 사진으로 확인해야 한다(기록의 strength 가 1 초과면 그 컷이다).
CAP = 2.5


def lift_to(img: Image.Image, target_pct: float, ref_shade: float, region: str = REGION, cap: float = CAP):
    """골 그늘이 ref_shade(보통 Before) 대비 target_pct(%, 음수 = 감소)가 되도록 세기를 이분 탐색한다.

    이미 목표보다 옅으면 세기 0(손 안 댐). 상한 cap 에서도 못 가면 cap 으로 그리고 capped=True."""
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
