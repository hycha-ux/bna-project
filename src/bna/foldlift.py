"""팔자 그림자 들어올리기 (A안, 2026-09-28 7차 연서님 — 비용 0, 모델 밖에서 우리가 직접).

왜: v50·v51 에서 이미지 편집 모델은 '팔자를 옅게'를 문장·부위 마스크·목표 사진 어느 쪽으로 줘도 실행하지 않았다
    (골 대비 변화 ±0.4%, 5컷). 필러가 실제로 하는 일은 **골이 만드는 그림자를 얕게** 하는 것이라, 그 그림자만 들어올린다.

어떻게(피부결 보존):
  ① 밝기(LAB 의 L)를 '중간 크기 흐림(small)'과 '큰 흐림(large)'으로 나눈다. small − large 가 음수인 곳 = 주변보다 어두운 골.
  ② 그 어두운 양만 strength 비율로 되돌려 준다. 모공·솜털 같은 잔결(원본 − small)은 손대지 않는다.
  ③ 부위 = 팔자·마리오네트 마스크(얼굴 점) × 부드러운 경계. 마스크 밖은 픽셀 그대로.
  색(a·b)은 안 건드린다 — 붉은기·패치 자국이 그대로 남는다.
⚠ 이건 '보정'이다. 과하면 그 자리만 뿌옇게 떠서 오히려 티가 난다 — strength 는 사람 검수로 정한다. 첫 값 1.0·큰 흐림 0.12 — v51 0001 로 0.6·0.05 는 눈에 안 띄었다(평균 L +0.38).
"""
import numpy as np
from PIL import Image

from .qa import landmarks as L

REGION = "nasolabial_marionette"


def lift(img: Image.Image, pts=None, strength: float = 1.0, small_frac: float = 0.012, large_frac: float = 0.12,
         feather: int = 18, region: str = REGION):
    """(보정된 사진, 기록 dict). 얼굴 점을 못 찾으면 (원본, {"applied": False}) — fail-open."""
    import cv2
    rgb = img.convert("RGB")
    if pts is None:
        pts = L.detect(rgb)
    if pts is None:
        return rgb, {"applied": False, "reason": "얼굴 점 못 찾음"}
    m = np.asarray(L.region_mask(rgb, pts, region, feather=feather), dtype=np.float32) / 255.0
    lab = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2LAB).astype(np.float32)
    Lc = lab[:, :, 0]
    w = rgb.size[0]
    ks = max(3, int(w * small_frac) | 1); kl = max(ks + 2, int(w * large_frac) | 1)
    small = cv2.GaussianBlur(Lc, (ks, ks), 0)
    large = cv2.GaussianBlur(Lc, (kl, kl), 0)
    dark = np.minimum(small - large, 0.0)                 # 주변보다 어두운 양(음수) — 골 그림자
    out = Lc - strength * dark * m                          # 그만큼만 되돌린다(마스크 안)
    lab[:, :, 0] = np.clip(out, 0, 255)
    res = Image.fromarray(cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB))
    return res, {"applied": True, "strength": strength, "mean_lift_L": round(float((-strength * dark * m)[m > 0.5].mean()), 2)}
