"""19차 자리별 폭 합치기 비교 (2026-09-29 연서님 "합친 뒤에도 확대하면 도장 — 팔자 띠 밖 16~24px, 띠 안만 8px").

  PYTHONPATH=src python tools/retake_merge_var.py <retake_compare 산출 폴더> <배치 폴더> [--out-sig 0.02]

재료 = retake_compare 산출(_filled · _retake_v17) + retake_merge 산출(_merged = 18차 8px 한 폭). 새 생성 0, 비용 0.
세트마다 Before · 지금 최종(15차) · 18차(8px 한 폭) · 19차(띠 밖 w×out-sig · 띠 안 8px) 를 나란히:
골 선(Before 대비 %) · 배경 밝기(L) · 반복 무늬 자(repeat_stats: face_p90/face_hit, band_p90) + 확대 4곳(2배).
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
OUT_SIG = float(A[A.index("--out-sig") + 1]) if "--out-sig" in A else TS.SIG_OUT
FT = lambda n: ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", n)  # noqa: E731
ZOOMS = [("이마", 151), ("콧등", 197), ("윗볼", 50), ("팔자", 206)]


def pct(e, eb):
    return None if not (e and eb) else round((e - eb) / eb * 100, 1)


def bg_L(img):
    lab = TS._lab(img); H, W = lab.shape[:2]
    h, w = int(H * 0.25), int(W * 0.12)
    return round(float(np.r_[lab[:h, :w, 0].ravel(), lab[:h, W - w:, 0].ravel()].mean()), 1)


def crop2x(img, pts, idx, half=0.075):
    s = int(img.size[0] * half)                    # 사진 폭의 15% 정사각 → 300px(1024 폭이면 약 2배)
    x, y = pts[idx]
    return img.crop((int(x - s), int(y - s), int(x + s), int(y + s))).resize((300, 300), Image.LANCZOS)


def board(ims, cols, subs, title):
    cw = 300
    pts = [L.detect(im) for im in ims]
    full = [im.resize((cw, int(cw * im.size[1] / im.size[0])), Image.LANCZOS) for im in ims]
    fh = full[0].size[1]
    W, H = 110 + cw * len(ims) + 10, 170 + fh + len(ZOOMS) * (cw + 8) + 20
    c = Image.new("RGB", (W, H), "white"); dr = ImageDraw.Draw(c)
    dr.text((14, 8), title, fill="black", font=FT(24))
    for j, (t, s) in enumerate(zip(cols, subs)):
        dr.text((110 + j * cw + 6, 50), t, fill="black", font=FT(20))
        for k, line in enumerate(s):
            dr.text((110 + j * cw + 6, 80 + k * 24), line, fill=(80, 80, 80), font=FT(16))
    y = 160
    for j, im in enumerate(full):
        c.paste(im, (110 + j * cw, y))
    y += fh + 8
    for nm, i in ZOOMS:
        dr.text((8, y + cw // 2 - 12), nm, fill="black", font=FT(18))
        for j, (im, p) in enumerate(zip(ims, pts)):
            if p is not None:
                c.paste(crop2x(im, p, i), (110 + j * cw, y))
        y += cw + 8
    return c


res = {}
for ff in sorted(SRC.glob("*_filled.jpg")):
    key = ff.name[: -len("_filled.jpg")]
    sid = key.split("_")[0]
    d = BATCH / sid
    before = Image.open(next(d.glob("*_before.jpg"))).convert("RGB")
    now = Image.open(next(d.glob("*_after.jpg"))).convert("RGB")
    filled = Image.open(ff).convert("RGB")
    retake = Image.open(SRC / f"{key}_retake_v17.jpg").convert("RGB")
    m8 = Image.open(SRC / f"{key}_merged.jpg").convert("RGB")
    pb, pf, pr, pn = L.detect(before), L.detect(filled), L.detect(retake), L.detect(now)
    var, rec = TS.merge_var(retake, filled, TS.SIG_BAND, OUT_SIG, pb=pr, pa=pf)
    if var is None:
        res[key] = {"skip": rec}; print(key, rec); continue
    var.save(SRC / f"{key}_merged_var.jpg", quality=95)
    eb = FL.edge_ratio(before, pb)
    wm = TS.band_map(filled, pf)
    r = {"merge": rec}
    for nm, im, p in (("now", now, pn), ("m8", m8, pf), ("var", var, pf), ("retake", retake, pr)):
        rs = FL.repeat_stats(im, wm if p is pf else TS.band_map(im, p), p)
        r[nm] = {"edge": pct(FL.edge_ratio(im, p), eb), "bg": bg_L(im),
                 "face_p90": rs.get("face_p90"), "face_hit": rs.get("face_hit"), "band_p90": rs.get("band_p90")}
    r["bg_before"], r["bg_filled"] = bg_L(before), bg_L(filled)
    cols = ["Before", "지금 최종(15차)", "18차 · 8px 한 폭", f"19차 · 띠 밖 {OUT_SIG * 1024:.0f}px"]
    subs = [[f"배경 {r['bg_before']}"]] + [[f"골 {r[k]['edge']}% · 배경 {r[k]['bg']}", f"반복 자 {r[k]['face_p90']} / {r[k]['face_hit']}"]
                                           for k in ("now", "m8", "var")]
    board([before, now, m8, var], cols, subs, f"세트 {sid} · 골 선(Before 대비) · 배경 밝기 · 반복 자(얼굴 상위10% 닮음 / 도장 조각 비율)") \
        .save(SRC / f"{key}_var_compare.jpg", quality=92)
    res[key] = r
    print(key, json.dumps(r, ensure_ascii=False), flush=True)
(SRC / "retake_merge_var.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
