"""임상 직후 흔적 얹기 비용 0 시험(2026-09-30 빌디·연서님) — 기존 팔자 임상 Before 위에 marks.overlay, 새 생성 없음.

  python tools/marks_trial.py [--out tmp/marks_0930] [--delta 8.3] [--spots 40] [--gloss 0.22]
산출: board.jpg(얹기 전 | 얹은 후 | 직후 참조) · zoom.jpg(볼 한쪽 확대) · stats.json(붉은 기 전후·참조)
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bna import marks as M                 # noqa: E402
from bna.qa import landmarks as L          # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "samples/reference/clinical"
CANVAS = [
    ("40대 여", "outputs/20260929-170107-82cb/0000/nasolabial_clinical_korea40sf_0000_before.jpg"),
    ("40대 남", "outputs/20260929-165346-6a49/0000/nasolabial_clinical_korea40sm_0000_before.jpg"),
    ("50대 여", "outputs/20260929-164242-eb33/0000/nasolabial_clinical_korea50sf_0000_before.jpg"),
]
TILE = 520


def font(sz):
    try:
        return ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", sz)
    except OSError:
        return ImageFont.load_default()


def lower_face(img, pts):
    """참조 사진과 비슷한 틀: 눈 밑 ~ 턱 아래, 코끝 중심 정사각."""
    fw = M.face_w(pts)
    top = (pts[145][1] + pts[374][1]) / 2 + 0.02 * fw
    bot = pts[152][1] + 0.06 * fw
    s = bot - top
    cx = pts[1][0]
    return img.crop((int(cx - s / 2), int(top), int(cx + s / 2), int(bot))).resize((TILE, TILE), Image.LANCZOS)


def cheek_zoom(img, pts, side=0):
    """볼 한쪽(사진 왼쪽) 확대 — 눈 밑~입꼬리 높이, 얼굴 가장자리~코 옆."""
    fw = M.face_w(pts)
    x1 = pts[129 if side == 0 else 358][0]
    y0 = (pts[145][1] + pts[374][1]) / 2 + 0.03 * fw
    s = 0.36 * fw
    x0 = x1 - s if side == 0 else x1
    return img.crop((int(x0), int(y0), int(x0 + s), int(y0 + s))).resize((TILE, TILE), Image.LANCZOS)


def grid(rows, heads, title):
    pad, hh, lw = 10, 44, 110
    W = lw + len(heads) * (TILE + pad) + pad
    H = 60 + hh + len(rows) * (TILE + pad) + pad
    cv = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(cv)
    d.text((pad, 14), title, fill="black", font=font(28))
    for j, h in enumerate(heads):
        d.text((lw + pad + j * (TILE + pad) + 8, 66), h, fill="black", font=font(24))
    for i, (lab, tiles) in enumerate(rows):
        y = 60 + hh + i * (TILE + pad)
        d.text((pad, y + TILE // 2 - 14), lab, fill="black", font=font(24))
        for j, t in enumerate(tiles):
            cv.paste(t, (lw + pad + j * (TILE + pad), y))
    return cv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tmp/marks_0930")
    ap.add_argument("--delta", type=float, default=None, help="볼 붉은 기 올릴 양. 없으면 참조 직후−2주 후로 잰다")
    ap.add_argument("--spots", type=int, default=40)
    ap.add_argument("--gloss", type=float, default=0.7)
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)

    ref_i = Image.open(REF / "skinbooster_embo_immediate_01.jpg").convert("RGB")
    ref_w = Image.open(REF / "skinbooster_embo_after2w_01.jpg").convert("RGB")
    ri, rw = M.measure_ref(ref_i), M.measure_ref(ref_w)
    delta = a.delta if a.delta is not None else round(ri["red"] - rw["red"], 2)
    stats = dict(ref_immediate=ri, ref_after2w=rw, delta=delta, canvases={})
    ref_tile = ref_i.resize((TILE, TILE), Image.LANCZOS)
    ref_zoom = ref_i.crop((0, 30, 170, 200)).resize((TILE, TILE), Image.LANCZOS)

    rows, zrows = [], []
    for i, (lab, rel) in enumerate(CANVAS):
        im = Image.open(ROOT / rel).convert("RGB")
        pts = L.detect(im)
        res, rec = M.overlay(im, pts, flush_delta=delta, n_spots=a.spots, gloss=a.gloss, seed=100 + i)
        res.save(out / f"{i}_marked.jpg", quality=95)
        rec.update(src=rel, before=M.measure(im, pts), after=M.measure(res, pts))
        stats["canvases"][lab] = rec
        rows.append((lab, [lower_face(im, pts), lower_face(res, pts), ref_tile]))
        zrows.append((lab, [cheek_zoom(im, pts), cheek_zoom(res, pts), ref_zoom]))
        print(lab, rec["before"]["red"], "->", rec["after"]["red"], rec)

    heads = ["얹기 전 (팔자 Before)", "얹은 후 (점·홍조·광)", "직후 참조 (병원 사진)"]
    grid(rows, heads, f"임상 직후 흔적 얹기 — 비용 0 시험 (볼 붉은 기 +{delta})").save(out / "board.jpg", quality=90)
    grid(zrows, heads, "볼 한쪽 확대").save(out / "zoom.jpg", quality=90)
    json.dump(stats, open(out / "stats.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
