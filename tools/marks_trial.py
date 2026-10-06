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
    pad, lw = 10, 110
    hh = 16 + 30 * max(len(h.split("\n")) for h in heads)      # 제목 여러 줄(10-06 빌디 3차 "시험작·목표 예시"가 길다)
    W = lw + len(heads) * (TILE + pad) + pad
    H = 60 + hh + len(rows) * (TILE + pad) + pad
    cv = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(cv)
    d.text((pad, 14), title, fill="black", font=font(28))
    for j, h in enumerate(heads):
        for k, line in enumerate(h.split("\n")):
            d.text((lw + pad + j * (TILE + pad) + 8, 64 + 30 * k), line, fill="black" if k == 0 else "#555", font=font(24 if k == 0 else 20))
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
    ap.add_argument("--gloss", type=float, default=1.6)
    ap.add_argument("--bumps", type=float, default=0.34)
    ap.add_argument("--prev", default=None, help="지난 회차 얹은 결과 폴더({i}_marked.jpg) — 있으면 [지난|이번|참조] 판")
    ap.add_argument("--prev-name", default="지난 회차", help="판 제목: 지난 회차 이름(예: 2차)")
    ap.add_argument("--name", default="이번 회차", help="판 제목: 이번 회차 이름(예: 3차)")
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)

    ref_i = Image.open(REF / "skinbooster_embo_immediate_01.jpg").convert("RGB")
    ref_w = Image.open(REF / "skinbooster_embo_after2w_01.jpg").convert("RGB")
    ri, rw = M.measure_ref(ref_i), M.measure_ref(ref_w)
    # 기본 = 참조 직후−2주 후 차의 0.8배(10-06 빌디 2차 0.6배 → 3차 "너무 약하다" 0.8배)
    delta = a.delta if a.delta is not None else round(0.8 * (ri["red"] - rw["red"]), 2)
    stats = dict(ref_immediate=ri, ref_after2w=rw, delta=delta, canvases={})
    ref_tile = ref_i.resize((TILE, TILE), Image.LANCZOS)
    ref_zoom = ref_i.crop((0, 30, 170, 200)).resize((TILE, TILE), Image.LANCZOS)
    prev = ROOT / a.prev if a.prev else None

    rows, zrows = [], []
    for i, (lab, rel) in enumerate(CANVAS):
        im = Image.open(ROOT / rel).convert("RGB")
        pts = L.detect(im)
        res, rec = M.overlay(im, pts, flush_delta=delta, gloss=a.gloss, bumps=a.bumps, seed=100 + i)
        res.save(out / f"{i}_marked.jpg", quality=95)
        rec.update(src=rel, before=M.measure(im, pts), after=M.measure(res, pts))
        stats["canvases"][lab] = rec
        first = Image.open(prev / f"{i}_marked.jpg").convert("RGB") if prev else im
        rows.append((lab, [lower_face(first, pts), lower_face(res, pts), ref_tile]))
        zrows.append((lab, [cheek_zoom(first, pts, 0), cheek_zoom(res, pts, 0), cheek_zoom(first, pts, 1),
                            cheek_zoom(res, pts, 1), ref_zoom]))
        print(lab, rec["before"]["side"], "->", rec["after"]["side"], rec)

    # 10-06 빌디 3차: 1·2열이 팔자 Before 를 빌린 시험작이고 3열은 다른 사람의 실제 사진임을 제목에 박는다(연서님 혼동)
    p0, p1 = (a.prev_name, a.name) if prev else ("얹기 전", a.name)
    sub = "시험작(팔자 Before 위에 얹음)"
    heads = [f"{p0}\n{sub if prev else '(팔자 Before 원본)'}", f"{p1}\n{sub}", "목표 예시\n(다른 사람, 실제 엠보 직후)"]
    grid(rows, heads, f"임상 직후 흔적 얹기 — 비용 0 시험 (볼마다 붉은 기 +{delta})").save(out / "board.jpg", quality=90)
    zh = [f"{p0}·왼볼\n시험작", f"{p1}·왼볼\n시험작", f"{p0}·오른볼\n시험작", f"{p1}·오른볼\n시험작",
          "목표 예시\n(다른 사람, 실제 엠보 직후)"]
    grid(zrows, zh, "볼 확대 (사진 기준 왼볼·오른볼)").save(out / "zoom.jpg", quality=90)
    json.dump(stats, open(out / "stats.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
