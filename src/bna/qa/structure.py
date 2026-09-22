"""구조 검사 (A5): 정렬 오차 · 얼굴 크기 비율 · 밝기 차이 · 시술 부위 프레임 내 포함."""
import numpy as np
from PIL import Image
from . import landmarks as L
from ..spec import load


def check(before: Image.Image, after: Image.Image, mode: str, region: str, copy_head_only: bool = False) -> dict:
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
        return {**out, "passed": None, "measured": False, "copy": copy_check(pb, pa, mode, head_only=copy_head_only),
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
    # 복붙 판정은 **여기 붙여도 값이 안 든다** — 랜드마크를 이미 떴으므로 추가 검출이 0이다.
    # 다만 `passed` 에는 섞지 않는다(별개 게이트라 화면·통계가 갈라 봐야 한다). 소비는 batch 가 한다.
    out["copy"] = copy_check(pb, pa, mode, head_only=copy_head_only)

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


# ── 복붙 게이트 (2026-09-14 빌디 지적) ──────────────────────────────────────────
# After 가 Before 의 **얼굴을 그대로 베끼고** 배경만 갈아 끼운 컷이 모든 게이트를 통과했다
# (증거 20260914-085009-06ac/0001: 배경은 차→거실인데 눈꺼풀 각도·시선·반쯤 벌린 입과 드러난
#  앞니까지 같은 그림이다. 구조 통과 · 동일인 0.86 · drift 7.0 — 사람만 reject 했다).
# 이유는 단순하다. 우리 자는 전부 *닮을수록 좋은 점수*를 준다 — 같은 사람인가(identity), 정렬이
# 맞는가(structure), 딴 게 안 변했나(drift). 복사본은 이 셋의 만점짜리 답이라, **반대 방향으로
# 재는 자가 하나도 없었다.** 이 함수가 그 자리다.
#
# ⚠ 픽셀로는 못 잡는다(2026-09-14 실측, 1차 시도를 버린 이유). 얼굴을 눈으로 포개고 시술 부위를
#   뺀 뒤 픽셀을 견줘 봤더니 그 증거가 0.237 로 **분포 한가운데**에 앉았다 — 생성 모델은 얼굴을
#   베껴도 픽셀은 매번 새로 그리기 때문이다. 사람 눈에 같아 보이는 건 픽셀이 아니라
#   **고개 방향·입 벌림·눈뜸**이고, 그건 랜드마크로 바로 잴 수 있다.
# ⚠ 셀카 전용이다. 임상 컷은 조명·각도까지 맞춘 편집이라 닮은 게 정답이고, 거기 이 자를 걸면
#   잘 만든 임상 컷이 통째로 떨어진다(방향이 반대인 두 모드에 한 자를 쓰면 한쪽은 반드시 틀린다).
UP_LIP, LOW_LIP = 13, 14
EYE_L_T, EYE_L_B, EYE_R_T, EYE_R_B = 159, 145, 386, 374
BROW_L, BROW_R, CHIN = 105, 334, 152


def pose_vector(pts) -> np.ndarray:
    """IPD 로 정규화한 자세·표정 값. 앞 4칸=표정(입·눈), 뒤=고개 방향.

    얼굴 크기·위치·기울기를 지우므로 "확대해서 찍었다"는 이유로는 값이 안 움직인다 —
    남는 건 *어떤 표정으로 어느 쪽을 보고 있나* 뿐이다.
    """
    kp = L.key_points(pts)
    el, er = kp["eye_l"], kp["eye_r"]
    ipd = float(np.linalg.norm(er - el)) or 1.0
    mid = (el + er) / 2.0
    ang = np.arctan2((er - el)[1], (er - el)[0])
    c, s = np.cos(-ang), np.sin(-ang)
    R = np.array([[c, -s], [s, c]])
    n = lambda i: R @ ((pts[i] - mid) / ipd)             # noqa: E731 — 회전·크기를 지운 좌표
    return np.array([
        float(np.linalg.norm(pts[UP_LIP] - pts[LOW_LIP]) / ipd),      # 입 벌림
        float(np.linalg.norm(kp["mouth_r"] - kp["mouth_l"]) / ipd),   # 입 너비
        float(np.linalg.norm(pts[EYE_L_T] - pts[EYE_L_B]) / ipd),     # 왼 눈뜸
        float(np.linalg.norm(pts[EYE_R_T] - pts[EYE_R_B]) / ipd),     # 오른 눈뜸
        *n(L.NOSE_TIP), *n(CHIN), *n(BROW_L), *n(BROW_R),             # 고개 방향
    ])


# 실측(2026-09-14, 셀카 실생성 50쌍 전수·시뮬 제외)으로 고른 컷. **AND 규칙**이다 — 표정도 같고
# 고개도 같아야 복붙으로 본다. 하나만 같은 건 흔하다(같은 표정으로 고개만 돌린 컷은 정상).
#   표정<=0.005 ∧ 고개<=0.015 → 4건(8%) 걸림, **그 4건 전부 사람이 이미 reject** 한 것(오탈락 0).
#   느슨하게(0.006/0.020) 가면 16%가 걸리는데 그중 3건이 사람이 채택했던 사진이다.
# ⚠ 표정 쪽 여유가 얇다 — 사람이 채택한 컷 중 가장 가까운 것이 0.0051 이다(컷 0.0050 바로 위).
#   표본 50쌍이라 이 한 점이 곧 여유의 전부다. **컷을 움직이려면 새 회차로 다시 재라**,
#   그리고 옛 회차와 비교할 땐 meta 의 `copy.cuts` 를 보고 갈라라(컷이 바뀌면 다른 자다).
COPY_EXPR_CUT, COPY_HEAD_CUT = 0.005, 0.015


def copy_check(before_pts, after_pts, mode: str, expr_cut: float = None, head_cut: float = None,
               head_only: bool = False) -> dict:
    """복붙 판정 한 벌. 셀카에서만 걸고, 임상·얼굴 미검출은 **못 잼**(None)으로 둔다.

    3값 규칙은 이 파일의 다른 자들과 같다 — None 은 실패가 아니다(상위가 실패로 세지 않는다).
    """
    ec = COPY_EXPR_CUT if expr_cut is None else expr_cut
    hc = COPY_HEAD_CUT if head_cut is None else head_cut
    cuts = {"expr": ec, "head": hc}
    if mode != "selfie":
        return {"passed": None, "measured": False, "cuts": cuts,
                "reason": "임상 컷은 닮은 게 정답이라 이 자를 걸지 않는다"}
    if before_pts is None or after_pts is None:
        return {"passed": None, "measured": False, "cuts": cuts,
                "reason": "얼굴 미검출 — 자세를 잴 수 없다(부분 크롭·측면이면 정상)"}
    va, vb = pose_vector(after_pts), pose_vector(before_pts)
    expr = float(np.abs(va[:4] - vb[:4]).mean())
    head = float(np.abs(va[4:] - vb[4:]).mean())
    # head_only(2026-09-22 연서님, 미모 프로필 `copy_gate: head`): 표정을 일부러 잠근 컷은 표정 조건이 늘 참이라
    #   AND 가 사실상 고개 하나다 — 그걸 명시로 바꾸고 원장에 규칙을 남긴다(옛 회차와 갈라 보려면 `rule` 을 봐라).
    same = head <= hc if head_only else (expr <= ec and head <= hc)
    return {"expr_diff": round(expr, 4), "head_diff": round(head, 4), "cuts": cuts,
            "rule": "head" if head_only else "expr_and_head",
            "measured": True, "passed": not same,
            "reason": "" if not same else
                      (f"전·후의 고개가 거의 같다(고개 {head:.4f}≤{hc}, 미모 컷은 고개만 본다) — 너무 같음" if head_only else
                       f"전·후의 표정과 고개가 거의 같다(표정 {expr:.4f}≤{ec} · 고개 {head:.4f}≤{hc}) — "
                       "다른 날 다시 찍은 셀카가 아니라 베껴 그린 컷으로 본다")}
