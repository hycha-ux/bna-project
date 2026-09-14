"""구조 검사 (A5): 정렬 오차 · 얼굴 크기 비율 · 밝기 차이 · 시술 부위 프레임 내 포함."""
import numpy as np
from PIL import Image
from . import landmarks as L
from ..spec import load


def check(before: Image.Image, after: Image.Image, mode: str, region: str) -> dict:
    tol = load("clinical_rig.yaml")["tolerance"]
    pb, pa = L.detect(before), L.detect(after)
    out = {"face_detected": pb is not None and pa is not None}
    if not out["face_detected"]:
        # ⚠ 미검출은 '실패'가 아니라 **'못 잼'** 이다 — identity 게이트와 같은 규칙(3값).
        #   종전엔 passed=False 로 떨어뜨려 배치가 MAX_ATTEMPTS 만큼 재생성했다.
        #   2026-09-08 실집행 실측: framing=one_cheek(한쪽 볼) 컷이 3회 재시도 후에도 당연히 미검출,
        #   **$1.14 를 태우고 실패**했다. 랜드마크가 없는 건 그림이 나빠서가 아니라 눈이 프레임 밖이라
        #   생기는 일이고, 다시 뽑아도 같은 변주면 또 미검출이다(재시도가 원리적으로 무의미).
        #   → passed=None(미판정). 상위(batch)가 None 을 실패로 세지 않으므로 비전 채점으로 넘어간다.
        return {**out, "passed": None, "measured": False,
                "reason": "얼굴 미검출 — 부분 크롭·측면이면 정상이다(구조 검사 미측정, 비전 채점으로 판정)"}

    kb, ka = L.key_points(pb), L.key_points(pa)
    ipd_b = np.linalg.norm(kb["eye_r"] - kb["eye_l"])
    ipd_a = np.linalg.norm(ka["eye_r"] - ka["eye_l"])
    center_b, center_a = (kb["eye_l"] + kb["eye_r"]) / 2, (ka["eye_l"] + ka["eye_r"]) / 2
    out["align_err_pct"] = float(np.linalg.norm(center_a - center_b) / ipd_b * 100)
    out["face_ratio_diff"] = float(abs(ipd_a - ipd_b) / ipd_b)
    out["luma_diff"] = float(abs(np.asarray(before.convert("L")).mean() - np.asarray(after.convert("L")).mean()) / 255)

    # 시술 부위가 프레임 안에 있는지 (아래 region_frame 머리말이 자의 근거다)
    out.update(region_frame(pa, region, after.size))

    if mode == "clinical":
        out["passed"] = (out["align_err_pct"] <= tol["landmark_align_pct"] and out["face_ratio_diff"] <= tol["face_ratio_diff"]
                         and out["luma_diff"] <= tol["luma_diff"] and out["region_in_frame"])
    else:
        out["passed"] = out["region_in_frame"]
    return out

# 부위 인덱스: 조합 표기("cheeks+nose")도 푼다. 2026-09-14 실측 전까지 이걸 안 풀어서
# skin_pores(mask_region=cheeks_nose)는 `isinstance(idx, list)` 가 False → **이 게이트를 아예 안 탔다**.
# 같은 볼인데 시술에 따라 검사가 켜지고 꺼지는 상태였다(원리: 축이 갈리면 한쪽만 벌을 받는다).
def region_points(pts, region):
    idx = L.REGIONS.get(region)
    if isinstance(idx, str) and "+" in idx:
        idx = [i for part in idx.split("+") for i in (L.REGIONS.get(part) or [])]
    return pts[idx] if isinstance(idx, list) and idx else None


def region_frame(pts, region, size, in_cut=0.90, cov_cut=0.20) -> dict:
    """시술 부위가 화면에서 **보이는가**. 순수 함수라 회귀가 좌표로 직접 본다.

    ⚠ 2026-09-14: 종전 자는 '부위 점이 한 점이라도 화면 밖이면 실패'였다. 확대 컷 비중을 4배로
      올린 뒤 이 자가 엉뚱한 것을 잡았다 — 엠보 0000 이 3회 재시도 끝에 탈락했는데(실측 안비율
      86%·화면덮음 41%) 그 사진은 볼이 **안 보이는 게 아니라 화면을 넘친** 것이었다.
      더 확대된 컷(one_cheek)은 얼굴 미검출로 '못 잼' 처리돼 통과하니, **중간 확대만 벌을 받는**
      역전이었다. 재시도가 원리적으로 무의미한 자리에 돈을 태운 것도 같은 뿌리다.
    그래서 자를 둘로 본다 — ①점 대부분이 화면 안이거나 ②남은 부위가 화면을 충분히 덮으면 보인다.
      실측 48장에서 '밀려나 사라진' 군은 화면덮음 ≤5.6%, '확대해 넘친' 군은 ≥26.9% 로
      4배 이상 벌어져 있다(중간 표본 0). 컷 20% 는 그 골짜기에 둔 값이다.
    ⚠ 이 자는 '보이나'만 본다. '부위가 화면 밖으로 밀렸나'가 원래 물음이었고 그건 그대로다.
    """
    p = region_points(pts, region)
    if p is None:
        return {"region_in_frame": True}
    w, h = size
    inside = ((p[:, 0] >= 0) & (p[:, 0] < w) & (p[:, 1] >= 0) & (p[:, 1] < h))
    in_ratio = float(inside.mean())
    x0, x1 = float(np.clip(p[:, 0], 0, w).min()), float(np.clip(p[:, 0], 0, w).max())
    y0, y1 = float(np.clip(p[:, 1], 0, h).min()), float(np.clip(p[:, 1], 0, h).max())
    cov = (x1 - x0) * (y1 - y0) / float(w * h)
    return {"region_in_frame": bool(in_ratio >= in_cut or cov >= cov_cut),
            "region_in_ratio": round(in_ratio, 3), "region_coverage": round(cov, 3)}
