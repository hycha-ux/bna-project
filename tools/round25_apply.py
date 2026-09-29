"""25차 입꼬리 메우기 고치기 — 새 생성 없이 끝난 세트에 다시 적용해 비교 (2026-09-29 연서님 24차 검수).

  PYTHONPATH=src python tools/round25_apply.py <출력폴더> <배치ID> [<배치ID> …]

돈 0. 세트마다: 메우기 전 B(fold_b) → foldguard.fill_guarded(보호 마스크·입꼬리 중심선·볼 쪽 재료·수염 누르기 약하게·아래 구간 좌우)
 → 좌우 자(balance_sides, 배치와 같게) → 안전 합치기(재촬영 잔결, 입술 경계선만큼만 제외 lip_grow) → 지금 최종과 비교.
원장 = <출력>/round25.json, 판 = <출력>/<배치>_<세트>.jpg(두 입꼬리 확대: Before | 지금 | 새 25차), 새 After = <출력>/<배치>_<세트>_after25.jpg
배치 폴더는 건드리지 않는다(대시보드 반영은 연서님 판단 뒤).
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from bna import foldguard as FG, foldlift as FL, texswap as TS, pigment as PG
from bna.qa import landmarks as L
from bna.spec import load

FT = lambda n: ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", n)  # noqa: E731
LIP_GROW = 0.002


def pct(e, eb):
    return None if not (e and eb) else round((e - eb) / eb * 100, 1)


def crop(img, pts, idx, frac=0.7, px=360):
    s = FL._ipd(pts) * frac
    x, y = pts[idx][:2]
    return img.crop((int(x - s / 2), int(y - s / 2), int(x + s / 2), int(y + s / 2))).resize((px, px), Image.LANCZOS)


def board(ims, cols, title, pts):
    cw = 360
    W, H = 20 + cw * len(ims) + 10 * (len(ims) - 1), 90 + 2 * (cw + 10)
    c = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(c)
    d.text((14, 8), title, fill="black", font=FT(20))
    for j, t in enumerate(cols):
        d.text((20 + j * (cw + 10), 50), t, fill="black", font=FT(20))
    for r, idx in enumerate((61, 291)):
        for j, (im, p) in enumerate(zip(ims, pts)):
            c.paste(crop(im, p, idx), (20 + j * (cw + 10), 84 + r * (cw + 10)))
    return c


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    ff_cfg = load("clinical_rig.yaml").get("fold_fill") or {}
    res = {}
    for bid in sys.argv[2:]:
        for d in sorted(p for p in (Path("outputs") / bid).iterdir() if p.is_dir() and p.name.isdigit()):
            m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            when = next(iter(m.get("fold_fill") or {}), None)
            fbs, rts = sorted(d.glob(f"fold_b_{when}_a*.jpg")), sorted(d.glob(f"retake_{when}_a*.jpg"))
            if not fbs or not rts:
                res[f"{bid}/{d.name}"] = {"skip": "fold_b/retake 원본 없음"}; continue
            bef = Image.open(next(d.glob("*_before.jpg"))).convert("RGB")
            old = Image.open(next(d.glob("*_after.jpg"))).convert("RGB")
            fb, rt = Image.open(fbs[-1]).convert("RGB"), Image.open(rts[-1]).convert("RGB")
            eb = FL.edge_ratio(bef)
            new, gi = FG.fill_guarded(bef, fb, eb * (1 + float(ff_cfg["edge_pct"]) / 100.0), side_gap_max=ff_cfg.get("side_gap_max"))
            gi.pop("_wm", None)                           # 좌우 자(balance_sides)는 fill_guarded 안에서 같은 보호로 돈다
            filled_edge = FL.edge_ratio(new)
            mg, mr = TS.merge_safe(rt, new, lip_grow=LIP_GROW)
            final = mg if mg is not None else rt
            final.save(out / f"{bid}_{d.name}_after25.jpg", quality=92)
            r = {"when": when, "angle": m["variation"]["angle"]["key"], "who": f'{m["variation"]["age"]["key"]}{m["variation"]["gender"]["key"][0]}',
                 "fold_pct": {"old_final": pct(FL.edge_ratio(old), eb), "new_filled": pct(filled_edge, eb), "new_final": pct(FL.edge_ratio(final), eb)},
                 "seg_old": FG.seg_drop(bef, old), "seg_new": FG.seg_drop(bef, final),
                 "guard": gi.get("guard"), "seg_fix": gi.get("seg_fix"),
                 "merge": {"applied": mg is not None, "skip": mr.get("skip"), "ghost": mr.get("ghost")},
                 "band_spots": {k: {x: v.get(x) for x in ("n", "red")} for k, v in
                                (("before", PG.count(bef, region="band")), ("old", PG.count(old, region="band")),
                                 ("new", PG.count(final, region="band")))}}
            res[f"{bid}/{d.name}"] = r
            pts = [L.detect(x) for x in (bef, old, final)]
            board([bef, old, final], ["Before", "지금(24차)", "새 25차"],
                  f"25차 {r['who']} {r['angle']} {when} — 골 지금 {r['fold_pct']['old_final']}% → 새 {r['fold_pct']['new_final']}%",
                  pts).save(out / f"{bid}_{d.name}.jpg", quality=90)
            print(bid, json.dumps(r, ensure_ascii=False), flush=True)
    (out / "round25.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
