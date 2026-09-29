"""18차 층 합치기 (2026-09-29 연서님 "17차 후보 재촬영: 모공은 좋아졌는데 사진 전체 노출이 올라 배경 벽까지 밝아져 보정한 느낌
— 16차와 반대로: 큰 층(밝기·색·그늘·팔자 효과·배경)은 재촬영 전 메운 B, 잔결 층(모공)만 재촬영에서").

  PYTHONPATH=src python tools/retake_merge.py <retake_compare 산출 폴더> <배치 폴더> [--sigma 0.004]

재료 = tools/retake_compare.py 산출(<세트>_<시점>_filled.jpg · _retake_v17.jpg). 새 생성 0, 비용 0.
합치기 = bna.texswap.swap(잔결 원천=재촬영, 바탕=메운 B, 띠 비중 1.0) — 얼굴 점 삼각망으로 재촬영을 메운 B 모양에 맞춰 휜 뒤
  잔결만 교체한다(눈·눈썹·입술·구조 윤곽은 메운 B 제 것, 얼굴 밖 = 메운 B 그대로 → 배경 밝기는 메운 B 와 같다).
자르는 폭 = FINE_SIGMA(w×). 모공(2~4px)보다 크고 팔자 골 띠 폭(w×0.018 ≈ 18px)보다 작게 — 기본 0.008, 0.003~0.005 도 같이 잰다.
골 선 = 선명도(Before 대비 %) · 배경 밝기 = 위쪽 양옆 모서리(세로 25%·가로 12%) 평균 L(0~100).
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
SRC, BATCH = Path(A[0]), Path(A[1])
# 기본 8px(09-29 두 세트 실측): 4px 는 메운 B 의 '그물 무늬'(칸 8~12px)가 큰 층에 남아 이마·바깥 볼 결이 그대로였다.
#   8px 에서도 골 선은 메운 직후 대비 0~1.9%p 만 되살아났다(팔자 골 띠 폭 w×0.018 ≈ 18px 보다 작다).
SIG = float(A[A.index("--sigma") + 1]) if "--sigma" in A else 0.008
SWEEP = sorted({0.003, 0.004, 0.005, SIG})
FT = lambda n: ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", n)  # noqa: E731
ZOOMS = [("이마", 151, 0.9), ("콧등·볼 안쪽", 197, 0.9), ("바깥 볼", 50, 0.9), ("팔자", 206, 0.9)]


def pct(e, eb):
    return None if not (e and eb) else round((e - eb) / eb * 100, 1)


def bg_L(img):
    lab = TS._lab(img); H, W = lab.shape[:2]
    h, w = int(H * 0.25), int(W * 0.12)
    return round(float(np.r_[lab[:h, :w, 0].ravel(), lab[:h, W - w:, 0].ravel()].mean()), 1)


def face_L(img, pts):
    lab = TS._lab(img)
    return round(float(lab[:, :, 0][TS.face_weight(img.size, pts) > 0.9].mean()), 1)


def crop(img, pts, idx, frac, px=280):
    k = L.key_points(pts); s = float(np.linalg.norm(k["eye_r"] - k["eye_l"])) * frac
    x, y = pts[idx]
    return img.crop((int(x - s / 2), int(y - s / 2), int(x + s / 2), int(y + s / 2))).resize((px, px), Image.LANCZOS)


def board(ims, cols, title, sub):
    cw = 280
    pts = [L.detect(im) for im in ims]
    full = [im.resize((cw, int(cw * im.size[1] / im.size[0])), Image.LANCZOS) for im in ims]
    fh = full[0].size[1]
    W, H = 130 + cw * len(ims) + 10, 150 + fh + len(ZOOMS) * (cw + 8) + 20
    c = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(c)
    d.text((14, 8), title, fill="black", font=FT(24))
    for j, (t, s) in enumerate(zip(cols, sub)):
        d.text((130 + j * cw + 6, 52), t, fill="black", font=FT(20))
        d.text((130 + j * cw + 6, 82), s, fill=(90, 90, 90), font=FT(17))
    y = 140
    for j, im in enumerate(full):
        c.paste(im, (130 + j * cw, y))
    y += fh + 8
    for nm, i, f in ZOOMS:
        d.text((8, y + cw // 2 - 12), nm, fill="black", font=FT(18))
        for j, (im, p) in enumerate(zip(ims, pts)):
            if p is not None:
                c.paste(crop(im, p, i, f), (130 + j * cw, y))
        y += cw + 8
    return c


res = {}
for ff in sorted(SRC.glob("*_filled.jpg")):
    key = ff.name[: -len("_filled.jpg")]
    sid = key.split("_")[0]
    rf = SRC / f"{key}_retake_v17.jpg"
    d = BATCH / sid
    before = Image.open(next(d.glob("*_before.jpg"))).convert("RGB")
    now = Image.open(next(d.glob("*_after.jpg"))).convert("RGB")
    filled, retake = Image.open(ff).convert("RGB"), Image.open(rf).convert("RGB")
    pb, pf, pr = L.detect(before), L.detect(filled), L.detect(retake)
    eb = FL.edge_ratio(before, pb)
    r = {"filled": pct(FL.edge_ratio(filled, pf), eb), "retake": pct(FL.edge_ratio(retake, pr), eb),
         "now": pct(FL.edge_ratio(now), eb),
         "bg": {"before": bg_L(before), "filled": bg_L(filled), "retake": bg_L(retake), "now": bg_L(now)},
         "face": {"filled": face_L(filled, pf), "retake": face_L(retake, pr)}, "sweep": {}}
    best = None
    for s in SWEEP:
        TS.FINE_SIGMA = s
        m, rec = TS.swap(retake, filled, band_w=1.0, pb=pr, pa=pf)
        if m is None:
            r["sweep"][str(s)] = rec
            continue
        r["sweep"][str(s)] = {"edge": pct(FL.edge_ratio(m, pf), eb), "pose": rec["pose"], "gain": rec["gain"]}
        if s == SIG:
            best = m
    if best is None:
        r["skip"] = "merge_failed"
        res[key] = r; print(key, json.dumps(r, ensure_ascii=False)); continue
    r["merged"] = r["sweep"][str(SIG)]["edge"]
    r["bg"]["merged"] = bg_L(best)
    r["face"]["merged"] = face_L(best, pf)
    best.save(SRC / f"{key}_merged.jpg", quality=95)
    cols = ["Before", "지금 최종(15차)", "메운 직후(큰 층)", "재촬영(잔결 층)", "합친 뒤(18차 후보)"]
    sub = [f"배경 {r['bg']['before']}", f"골 {r['now']}% · 배경 {r['bg']['now']}", f"골 {r['filled']}% · 배경 {r['bg']['filled']}",
           f"골 {r['retake']}% · 배경 {r['bg']['retake']}", f"골 {r['merged']}% · 배경 {r['bg']['merged']}"]
    board([before, now, filled, retake, best], cols, f"세트 {sid} · 골 선(Before 대비 %) · 배경 밝기(L 0~100) · 자르는 폭 {SIG * 1024:.0f}px", sub) \
        .save(SRC / f"{key}_merge_compare.jpg", quality=92)
    res[key] = r
    print(key, json.dumps(r, ensure_ascii=False), flush=True)
(SRC / "retake_merge.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
