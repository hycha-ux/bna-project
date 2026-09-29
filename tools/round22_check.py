"""22차 결과 확인 (2026-09-29 연서님 "지문 같은 결 · 배경 밝기(재촬영 전 대비) · 골 수치(메운 직후/최종) · 직후로 읽히는지").

  PYTHONPATH=src python tools/round22_check.py <출력폴더> <배치ID> [<배치ID> …]

돈 0. 세트마다:
  · 골 선 선명도(Before 대비 %) = B(메우기 전) · 메운 직후 · 최종 — 값은 meta.fold_fill 원장에서 읽는다(다시 재지 않는다)
  · 배경 밝기 L(0~100, 위쪽 양옆 모서리) = 재촬영 전(보존된 메우기 전 B — 메우기는 배경을 안 건드린다) vs 최종
  · 얼굴 밝기 L(얼굴 안쪽) 같은 두 장
  · 확대판: Before | 재촬영 전 B | 최종 × (이마·콧등·볼 안쪽·바깥 볼·팔자) — 지문 같은 결은 눈으로 본다
원장 = <출력>/round22.json, 판 = <출력>/<배치>_<세트>.jpg
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from bna import texswap as TS
from bna.qa import landmarks as L

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


def crop(img, pts, idx, frac, px=300):
    k = L.key_points(pts); s = float(np.linalg.norm(k["eye_r"] - k["eye_l"])) * frac
    x, y = pts[idx]
    return img.crop((int(x - s / 2), int(y - s / 2), int(x + s / 2), int(y + s / 2))).resize((px, px), Image.LANCZOS)


def board(ims, cols, title):
    cw = 300
    pts = [L.detect(im) for im in ims]
    full = [im.resize((cw, int(cw * im.size[1] / im.size[0])), Image.LANCZOS) for im in ims]
    fh = full[0].size[1]
    W, H = 150 + cw * len(ims) + 10, 100 + fh + len(ZOOMS) * (cw + 8) + 20
    c = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(c)
    d.text((14, 10), title, fill="black", font=FT(24))
    for j, t in enumerate(cols):
        d.text((150 + j * cw + 6, 56), t, fill="black", font=FT(21))
    y = 94
    for j, im in enumerate(full):
        c.paste(im, (150 + j * cw, y))
    y += fh + 8
    for nm, i, f in ZOOMS:
        d.text((8, y + cw // 2 - 14), nm, fill="black", font=FT(20))
        for j, (im, p) in enumerate(zip(ims, pts)):
            if p is not None:
                c.paste(crop(im, p, i, f), (150 + j * cw, y))
        y += cw + 8
    return c


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    res = {}
    for bid in sys.argv[2:]:
        for d in sorted(p for p in (Path("outputs") / bid).iterdir() if p.is_dir() and p.name.isdigit()):
            m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            bef = Image.open(next(d.glob("*_before.jpg"))).convert("RGB")
            aft = Image.open(next(p for p in d.glob("*_after.jpg"))).convert("RGB")
            fbs = sorted(d.glob("fold_b_*_a*.jpg"))
            fb = Image.open(fbs[-1]).convert("RGB") if fbs else None      # 마지막 시도의 메우기 전 B = 최종 컷의 재촬영 전
            ff = next(iter((m.get("fold_fill") or {}).values()), {})
            eb = ff.get("edge_before_img")
            pa = L.detect(aft)
            r = {"angle": m["variation"]["angle"]["key"], "who": f'{m["variation"]["age"]["key"]}{m["variation"]["gender"]["key"][0]}',
                 "passed": m.get("passed"), "attempt": m.get("attempt"), "cost_est": m.get("cost"),
                 "fold_pct": {"B": pct(ff.get("edge_before"), eb), "filled": pct(ff.get("edge_after"), eb),
                              "final": pct(ff.get("edge_final"), eb)},
                 "fill_capped": ff.get("capped"), "retake_prompt": ff.get("retake_prompt"),
                 "merge": (ff.get("retake_merge") or {}).get("applied"),
                 "bg_L": {"pre_retake": bg_L(fb) if fb else None, "final": bg_L(aft)},
                 "face_L": {"pre_retake": face_L(fb, L.detect(fb)) if fb else None, "final": face_L(aft, pa) if pa is not None else None},
                 "fail_reasons": m.get("fail_reasons")}
            res[f"{bid}/{d.name}"] = r
            ims, cols = [bef, aft], ["Before", "최종 After"]
            if fb:
                ims, cols = [bef, fb, aft], ["Before", "재촬영 전 B(메우기 전)", "최종 After"]
            board(ims, cols, f"22차 {r['angle']} {r['who']} — 골 {r['fold_pct']} · 배경 {r['bg_L']}").save(
                out / f"{bid}_{d.name}.jpg", quality=90)
    (out / "round22.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
