"""복붙 게이트 2차 — 픽셀이 아니라 **자세·표정 기하**로 잰다.

1차(픽셀) 실측 결과: 빌디가 든 증거가 0.237 로 분포 한가운데 앉았다. 생성 모델은 얼굴을 '베껴도'
픽셀은 매번 새로 그리므로 픽셀 자로는 안 잡힌다. 사람 눈에 같아 보이는 건 장면이 아니라
**고개 각도·입 벌림·눈뜸·시선**이고, 그건 랜드마크로 직접 잴 수 있다.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bna.qa import landmarks as L  # noqa: E402

UP_LIP, LOW_LIP = 13, 14
EYE_L_T, EYE_L_B, EYE_R_T, EYE_R_B = 159, 145, 386, 374
BROW_L, BROW_R = 105, 334
CHIN = 152


def pose(pts):
    """IPD 로 정규화한 자세·표정 값 — 얼굴 크기·위치·기울기와 무관하게 '어떤 표정인가'만 남긴다."""
    kp = L.key_points(pts)
    el, er = kp["eye_l"], kp["eye_r"]
    ipd = float(np.linalg.norm(er - el)) or 1.0
    mid = (el + er) / 2.0
    ang = np.arctan2((er - el)[1], (er - el)[0])
    c, s = np.cos(-ang), np.sin(-ang)
    R = np.array([[c, -s], [s, c]])

    def n(i):                                            # 회전·크기를 지운 좌표
        return R @ ((pts[i] - mid) / ipd)

    return np.array([
        float(np.linalg.norm(pts[UP_LIP] - pts[LOW_LIP]) / ipd),     # 입 벌림
        float(np.linalg.norm(kp["mouth_r"] - kp["mouth_l"]) / ipd),  # 입 너비
        float(np.linalg.norm(pts[EYE_L_T] - pts[EYE_L_B]) / ipd),    # 왼 눈뜸
        float(np.linalg.norm(pts[EYE_R_T] - pts[EYE_R_B]) / ipd),    # 오른 눈뜸
        *n(L.NOSE_TIP), *n(CHIN), *n(BROW_L), *n(BROW_R),            # 고개 방향(요·피치·롤)
    ])


rows = []
for meta in sorted((ROOT / "outputs").glob("*/*/meta.json")):
    try:
        d = json.loads(meta.read_text(encoding="utf-8"))
    except Exception:                                   # noqa: BLE001
        continue
    if d.get("mode") != "selfie" or "-sim" in meta.parent.parent.name:
        continue
    b = next(meta.parent.glob("*_before.jpg"), None)
    a = next(meta.parent.glob("*_after.jpg"), None)
    if not (b and a):
        continue
    try:
        pb, pa = L.detect(Image.open(b)), L.detect(Image.open(a))
        if pb is None or pa is None:
            continue
        va, vb = pose(pa), pose(pb)
        dist = float(np.abs(va - vb).mean())
        expr = float(np.abs(va[:4] - vb[:4]).mean())
        head = float(np.abs(va[4:] - vb[4:]).mean())
    except Exception as e:                              # noqa: BLE001
        print("ERR", meta.parent.name, e); continue
    rv = {}
    rj = meta.parent / "review.json"
    if rj.exists():
        try: rv = json.loads(rj.read_text(encoding="utf-8"))
        except Exception: pass                          # noqa: BLE001
    rows.append({"id": f"{meta.parent.parent.name}/{meta.parent.name}", "d": dist, "e": expr, "h": head,
                 "pick": rv.get("pick"), "why": (rv.get("reasons") or rv.get("tags") or [])})

rows.sort(key=lambda r: r["d"])
arr = np.array([r["d"] for r in rows])
print(f"셀카 쌍 {len(rows)}건 · 평균 {arr.mean():.4f} · 중앙 {np.median(arr):.4f}")
for q in (1, 5, 10, 25, 50, 75, 90):
    print(f"  p{q:<3} {np.percentile(arr, q):.4f}")
print("\n가장 '같은 자세' 12건 (작을수록 복붙):")
for r in rows[:12]:
    print(f"  {r['d']:.4f}  {r['id']:<28} 사람={r['pick']} {r['why']}")
print("\n가장 다른 5:")
for r in rows[-5:]:
    print(f"  {r['d']:.4f}  {r['id']:<28} 사람={r['pick']}")
ev = [r for r in rows if "085009-06ac/0001" in r["id"]]
print("\n빌디 증거(엠보 1번):", ev, "→ 순위", [i for i, r in enumerate(rows) if "085009-06ac/0001" in r["id"]])
for cut in (0.010, 0.015, 0.020, 0.025, 0.030, 0.040):
    hit = [r for r in rows if r["d"] <= cut]
    picked = [r for r in hit if r["pick"] == "pick"]
    print(f"  컷 {cut}: 걸리는 것 {len(hit)}건({len(hit)/len(rows)*100:.1f}%) · 그중 사람이 채택했던 것 {len(picked)}건 {[r['id'] for r in picked]}")
