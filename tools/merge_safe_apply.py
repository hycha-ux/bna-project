"""23차 안전 합치기를 끝난 배치에 다시 걸어 본다 — 새 생성 0, 비용 0 (2026-09-29 연서님 "콧구멍 윗선 두 겹").

  PYTHONPATH=src python tools/merge_safe_apply.py <출력폴더> <배치ID> [<배치ID> …]

⚠ 배치는 재촬영 원본을 안 남겼다(23차부터 retake_<시점>_a<n>.jpg 로 남긴다). 그래서 재촬영 잔결의 대역으로 **지금 최종 After**를 쓴다:
  지금 최종 = 메운 B 의 큰 층 + (어긋난) 재촬영 잔결이라, 그 잔결 층이 곧 재촬영 잔결이다. 메운 B 는 보존된 메우기 전 B 에
  배치와 같은 메우기(fill_to → balance_sides)를 다시 걸어 만든다(retake_compare 와 같은 방식).
세트마다: 두 겹 자(지금 / 새) · 골 선(Before 대비 %) · 배경 밝기 · 코·눈·입 확대판(메운 B | 지금 18차 | 새 23차).
원장 = <출력>/merge_safe.json
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from bna import foldlift as FL
from bna import texswap as TS
from bna.qa import landmarks as L
from bna.spec import load

FT = lambda n: ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", n)  # noqa: E731
ZOOMS = [("코", 2, 0.9), ("눈(왼)", 159, 0.7), ("눈(오른)", 386, 0.7), ("입", 13, 1.0)]


def pct(e, eb):
    return None if not (e and eb) else round((e - eb) / eb * 100, 1)


def bg_L(img):
    lab = TS._lab(img); H, W = lab.shape[:2]
    h, w = int(H * 0.25), int(W * 0.12)
    return round(float(np.r_[lab[:h, :w, 0].ravel(), lab[:h, W - w:, 0].ravel()].mean()), 1)


def crop(img, pts, idx, frac, px=340):
    k = L.key_points(pts); s = float(np.linalg.norm(k["eye_r"] - k["eye_l"])) * frac
    x, y = pts[idx]
    return img.crop((int(x - s / 2), int(y - s / 4), int(x + s / 2), int(y + s / 4))).resize((px, px // 2), Image.LANCZOS)


def board(ims, cols, title, pts):
    cw = 340
    W, H = 110 + cw * len(ims) + 10, 90 + len(ZOOMS) * (cw // 2 + 8) + 10
    c = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(c)
    d.text((10, 8), title, fill="black", font=FT(20))
    for j, t in enumerate(cols):
        d.text((110 + j * cw + 6, 50), t, fill="black", font=FT(19))
    y = 84
    for nm, i, f in ZOOMS:
        d.text((8, y + cw // 4 - 12), nm, fill="black", font=FT(18))
        for j, im in enumerate(ims):
            c.paste(crop(im, pts, i, f), (110 + j * cw, y))       # 같은 좌표로 자른다(메운 B 의 얼굴 점) — 어긋남이 보이게
        y += cw // 2 + 8
    return c


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    ff = load("clinical_rig.yaml")["fold_fill"]
    res = {}
    for bid in sys.argv[2:]:
        for d in sorted(p for p in (Path("outputs") / bid).iterdir() if p.is_dir() and p.name.isdigit()):
            m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            before = Image.open(next(d.glob("*_before.jpg"))).convert("RGB")
            final = Image.open(next(d.glob("*_after.jpg"))).convert("RGB")
            fb = sorted(d.glob("fold_b_*_a*.jpg"))[-1]
            rec0 = next(iter((m.get("fold_fill") or {}).values()), {})
            eb = FL.edge_ratio(before)
            filled, fi = FL.fill_to(Image.open(fb).convert("RGB"), eb * (1 + float(ff["edge_pct"]) / 100.0), None)
            fi.pop("_wm", None)
            if fi.get("applied") and ff.get("side_gap_max") is not None:
                filled, _ = FL.balance_sides(before, filled, float(ff["side_gap_max"]))
            pf = L.detect(filled)
            new, r = TS.merge_safe(final, filled, pa=pf)
            key = f"{bid}/{d.name}"
            res[key] = {
                "angle": m["variation"]["angle"]["key"], "who": f'{m["variation"]["age"]["key"]}{m["variation"]["gender"]["key"][0]}',
                "refill_edge_after": fi.get("edge_after"), "batch_edge_after": rec0.get("edge_after"),
                "ghost_now": TS.ghost_score(final, filled, pf), "merge_safe": r,
                "fold_pct": {"filled": pct(FL.edge_ratio(filled), eb), "now": pct(FL.edge_ratio(final), eb),
                             "new": pct(FL.edge_ratio(new), eb) if new is not None else None},
                "bg_L": {"filled": bg_L(filled), "now": bg_L(final), "new": bg_L(new) if new is not None else None}}
            ims, cols = [filled, final], ["메운 B (재촬영 전)", "지금 (18차 합치기)"]
            if new is not None:
                new.save(out / f"{bid}_{d.name}_merge_safe.jpg", quality=95)
                ims.append(new); cols.append("새 (23차 안전 합치기)")
            t = (f"{res[key]['angle']} {res[key]['who']} · 두 겹 자 지금 {res[key]['ghost_now']} → 새 {r.get('ghost')}"
                 f" (상한 {TS.GHOST_MAX})")
            board(ims, cols, t, pf).save(out / f"{bid}_{d.name}_zoom.jpg", quality=92)
            print(key, json.dumps(res[key], ensure_ascii=False), flush=True)
    (out / "merge_safe.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
