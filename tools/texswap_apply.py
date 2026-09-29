"""기존 배치 After 에 '모공은 Before 에서 가져오기'(src/bna/texswap.py)를 새 생성 없이 덮고, 지금 버전과 나란히 비교한다.

  PYTHONPATH=src python tools/texswap_apply.py outputs/<배치> [--out <폴더>]

세트마다: 골 선 선명도(Before 대비 %, 지금 → 새) · 좌우 · 모공 불규칙 자(크기·간격 변동계수) · 반복 자 · 띠 비중 단계.
산출: <out>/<세트>_after_texswap.jpg · <out>/<세트>_compare.jpg(전체 + 확대 3곳) · <out>/texswap.json. 원본 After 는 건드리지 않는다.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from bna import foldlift as FL
from bna import texswap as TS
from bna.qa import landmarks as L

A = sys.argv[1:]
BATCH = Path(A[0])
OUT = Path(A[A.index("--out") + 1]) if "--out" in A else BATCH / "_texswap"
OUT.mkdir(parents=True, exist_ok=True)
FONT = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 30)

# 확대 자리(얼굴 점 번호, 조각 한 변 = 눈 사이 × 비율) — 연서님이 짚은 이마·콧등·윗볼 + 팔자
ZOOMS = [("이마", 151, 0.9), ("콧등", 197, 0.9), ("윗볼", 50, 0.9), ("팔자", 206, 0.9)]   # 0.9 ≈ 2배 확대(모공이 보이는 배율)


def pct(e, eb):
    return None if not (e and eb) else round((e - eb) / eb * 100, 1)


def fold_grad(img, pts):
    """골 선 선명도의 **분자만**(골 띠 경사 상위 10%, 볼 대조 없음). 09-29 첫 시험: 잔결을 Before 로 바꾸면 볼 맨살 경사
    (분모)가 9.45 → 8.59 로 내려가 골 선 선명도가 +5%p '되살아난' 것처럼 읽혔다 — 골 자리 경사는 18.94 → 18.91 그대로.
    교체는 볼 결도 바꾸므로 비율 자는 이 단계 판정에 못 쓴다. 같은 After 얼굴 점이라 띠 자리는 두 장이 같다."""
    import cv2
    ipd = float(np.linalg.norm(L.key_points(pts)["eye_r"] - L.key_points(pts)["eye_l"]))
    m = np.asarray(L.region_mask(img, pts, FL.REGION, feather=1)) > 127
    ex = np.asarray(L.region_mask(img, pts, "nose", feather=1)) > 0
    lip = np.zeros(m.shape, np.uint8)
    cv2.fillPoly(lip, [cv2.convexHull(pts[FL.LIPS].astype(np.int32))], 1)
    r = max(3, int(ipd * 0.05)) | 1
    ex = cv2.dilate((ex | (lip > 0)).astype(np.uint8), np.ones((r, r), np.uint8)) > 0
    if FL.ALA_EXCLUDE:
        ex = ex | (FL.ala_ramp(img, pts) < FL.ALA_MEASURE_MIN)
    g = cv2.GaussianBlur(FL._L(img)[:, :, 0], (0, 0), max(0.5, ipd * 0.02))
    v = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))[m & ~ex]
    return float(np.sort(v)[::-1][: max(1, len(v) // 10)].mean())


def crop(img, pts, idx, frac, px=340):
    ipd = float(np.linalg.norm(L.key_points(pts)["eye_r"] - L.key_points(pts)["eye_l"]))
    s = ipd * frac
    x, y = pts[idx]
    return img.crop((int(x - s / 2), int(y - s / 2), int(x + s / 2), int(y + s / 2))).resize((px, px), Image.LANCZOS)


def board(b, a, n, pb, pa, pn, title, cols):
    cw = 340
    full = [im.resize((cw, int(cw * im.size[1] / im.size[0])), Image.LANCZOS) for im in (b, a, n)]
    fh = full[0].size[1]
    rows = [(nm, [crop(b, pb, i, f), crop(a, pa, i, f), crop(n, pn, i, f)]) for nm, i, f in ZOOMS]
    W = 120 + cw * 3 + 20
    H = 60 + 44 + fh + len(rows) * (cw + 10) + 20
    c = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(c)
    d.text((20, 12), title, fill="black", font=FONT)
    for j, t in enumerate(cols):
        d.text((120 + j * cw + 8, 60), t, fill="black", font=FONT)
    y = 104
    for j, im in enumerate(full):
        c.paste(im, (120 + j * cw, y))
    y += fh + 10
    for nm, ims in rows:
        d.text((10, y + cw // 2 - 18), nm, fill="black", font=ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 22))
        for j, im in enumerate(ims):
            c.paste(im, (120 + j * cw, y))
        y += cw + 10
    return c


res = {}
for d in sorted(p for p in BATCH.iterdir() if p.is_dir() and p.name.isdigit()):
    bf = next(d.glob("*_before.jpg"), None); af = next(d.glob("*_after.jpg"), None)
    if not (bf and af):
        continue
    b, a = Image.open(bf).convert("RGB"), Image.open(af).convert("RGB")
    pb, pa = L.detect(b), L.detect(a)
    eb, ea = FL.edge_ratio(b, pb), FL.edge_ratio(a, pa)
    r = {"edge_now": pct(ea, eb), "side_now": FL.side_drop(b, a, pb, pa),
         "pore_before": TS.pore_stats(b, pb), "pore_now": TS.pore_stats(a, pa)}
    cache, steps, new = {}, [], None
    fb0, fa0 = fold_grad(b, pb), fold_grad(a, pa)
    r["fold_now"] = pct(fa0, fb0)                       # 골 자리 경사, Before 대비 %
    for bw in TS.BAND_STEPS:
        n, rec = TS.swap(b, a, band_w=bw, pb=pb, pa=pa, _cache=cache)
        if n is None:
            r["swap"] = rec
            break
        fn = fold_grad(n, pa)
        steps.append({"band_w": bw, "fold": pct(fn, fb0), "back_pct": round((fn - fa0) / fa0 * 100, 1),
                      "edge_ratio": pct(FL.edge_ratio(n, pa), eb)})
        new, r["swap"] = n, rec
        if (fn - fa0) / fa0 * 100 <= TS.EDGE_BACK_MAX:
            break
    r["steps"] = steps
    if new is not None:
        r["fold_new"] = steps[-1]["fold"]
        r["edge_new"] = steps[-1]["edge_ratio"]
        r["side_new"] = FL.side_drop(b, new, pb, pa)
        r["pore_new"] = TS.pore_stats(new, pa)
        wm = TS.band_map(a, pa)
        r["repeat_now"] = FL.repeat_stats(a, wm, pa)
        r["repeat_new"] = FL.repeat_stats(new, wm, pa)
        new.save(OUT / f"{d.name}_after_texswap.jpg", quality=95)
        t = f"세트 {d.name} · 골 자리 세기(Before 대비) {r['fold_now']}% → {r['fold_new']}% · 팔자 띠 Before 결 {steps[-1]['band_w']:.0%}"
        board(b, a, new, pb, pa, pa, t, ["Before", "지금 After", "새 After(모공=Before)"]).save(OUT / f"{d.name}_compare.jpg", quality=92)
    res[d.name] = r
    print(d.name, json.dumps(r, ensure_ascii=False))
(OUT / "texswap.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
