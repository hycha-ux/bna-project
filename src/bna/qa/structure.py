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

    # 시술 부위가 프레임 안에 있는지 (마스크 폴리곤이 이미지 경계 안)
    idx = L.REGIONS.get(region)
    if isinstance(idx, list):
        w, h = after.size
        pts = pa[idx]
        out["region_in_frame"] = bool((pts[:, 0] >= 0).all() and (pts[:, 0] < w).all() and (pts[:, 1] >= 0).all() and (pts[:, 1] < h).all())
    else:
        out["region_in_frame"] = True

    if mode == "clinical":
        out["passed"] = (out["align_err_pct"] <= tol["landmark_align_pct"] and out["face_ratio_diff"] <= tol["face_ratio_diff"]
                         and out["luma_diff"] <= tol["luma_diff"] and out["region_in_frame"])
    else:
        out["passed"] = out["region_in_frame"]
    return out
