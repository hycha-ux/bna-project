"""17차 후보 재촬영 비교 (2026-09-29 연서님 "16차 결 안 바뀜 — 재촬영 문안에서 'the same density everywhere'·모공 강조를 빼고
오늘 2세트 메운 B 에 재촬영만 다시 + 메우기 직후 vs 재촬영 뒤 골 수치로 재촬영이 효과를 먹는지 보자").

  PYTHONPATH=src python tools/retake_compare.py outputs/<배치> --prompt config/prompts/retake_clinical_v17.md --out <폴더> [--paid]

세트마다: 보존된 메우기 직전 B(fold_b_<시점>_a<회차>.jpg)에 배치와 **같은 메우기**(fill_to → balance_sides)를 다시 걸고
(비용 0 — 배치는 메운 직후 사진을 안 남긴다), --paid 면 후보 문안으로 재촬영 1회(편집 1회 ≈ $0.19, 결 참조 사진 없음).
골 선 선명도(Before 대비 %) = 메우기 직전 B · 메우기 직후 · 지금 최종(배치 재촬영) · 새 재촬영. 원장 = <out>/retake_compare.json.
⚠ 인자 없이(= --paid 없이) 돌리면 무료 단계만 한다 — 유료는 메우기 재현값이 배치 원장과 맞는지 눈으로 본 뒤에.
"""
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from bna import foldlift as FL
from bna import providers
from bna.qa import landmarks as L
from bna.spec import load

A = sys.argv[1:]
BATCH = Path(A[0])
PROMPT = " ".join(Path(A[A.index("--prompt") + 1]).read_text(encoding="utf-8").split())
OUT = Path(A[A.index("--out") + 1]); OUT.mkdir(parents=True, exist_ok=True)
PAID = "--paid" in A
FONT = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 26)
ZOOMS = [("이마", 151, 0.9), ("콧등·볼 안쪽", 197, 0.9), ("바깥 볼", 50, 0.9), ("팔자", 206, 0.9)]


def pct(e, eb):
    return None if not (e and eb) else round((e - eb) / eb * 100, 1)


def crop(img, pts, idx, frac, px=300):
    k = L.key_points(pts); s = float(np.linalg.norm(k["eye_r"] - k["eye_l"])) * frac
    x, y = pts[idx]
    return img.crop((int(x - s / 2), int(y - s / 2), int(x + s / 2), int(y + s / 2))).resize((px, px), Image.LANCZOS)


def board(ims, cols, title):
    cw = 300
    pts = [L.detect(im) for im in ims]
    full = [im.resize((cw, int(cw * im.size[1] / im.size[0])), Image.LANCZOS) for im in ims]
    fh = full[0].size[1]
    W, H = 140 + cw * len(ims) + 10, 100 + fh + len(ZOOMS) * (cw + 8) + 20
    c = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(c)
    d.text((16, 10), title, fill="black", font=FONT)
    for j, t in enumerate(cols):
        d.text((140 + j * cw + 6, 56), t, fill="black", font=ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 21))
    y = 94
    for j, im in enumerate(full):
        c.paste(im, (140 + j * cw, y))
    y += fh + 8
    for nm, i, f in ZOOMS:
        d.text((8, y + cw // 2 - 14), nm, fill="black", font=ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 20))
        for j, (im, p) in enumerate(zip(ims, pts)):
            if p is not None:
                c.paste(crop(im, p, i, f), (140 + j * cw, y))
        y += cw + 8
    return c


ff = load("clinical_rig.yaml")["fold_fill"]
prov = providers.get("openai") if PAID else None
res = {}
for d in sorted(p for p in BATCH.iterdir() if p.is_dir() and p.name.isdigit()):
    m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    bf, af = next(d.glob("*_before.jpg")), next(d.glob("*_after.jpg"))
    for fb in sorted(d.glob("fold_b_*_a*.jpg")):
        when = fb.stem.split("_")[2]
        rec0 = (m.get("fold_fill") or {}).get(when) or {}
        before, bimg, final = Image.open(bf).convert("RGB"), Image.open(fb).convert("RGB"), Image.open(af).convert("RGB")
        eb = FL.edge_ratio(before)
        filled, fi = FL.fill_to(bimg, eb * (1 + float(ff["edge_pct"]) / 100.0), None)
        fi.pop("_wm", None)
        if fi.get("applied") and ff.get("side_gap_max") is not None:
            filled, _ = FL.balance_sides(before, filled, float(ff["side_gap_max"]))
        filled.save(OUT / f"{d.name}_{when}_filled.jpg", quality=95)
        r = {"when": when, "edge_before_img": round(eb, 3),
             "B": pct(FL.edge_ratio(bimg), eb), "filled": pct(FL.edge_ratio(filled), eb),
             "final_now": pct(FL.edge_ratio(final), eb),
             "batch_fill_edge_after": rec0.get("edge_after"), "refill_edge_after": fi.get("edge_after"), "capped": fi.get("capped")}
        ims, cols = [before, filled, final], ["Before", "메우기 직후", "지금 최종(15차)"]
        if PAID:
            buf = io.BytesIO(); filled.save(buf, "PNG")
            out = Image.open(io.BytesIO(prov.edit(buf.getvalue(), prov.adapt_prompt(PROMPT, "after"), None, [], m.get("aspect")))).convert("RGB")
            out = out if out.size == filled.size else out.resize(filled.size, Image.LANCZOS)
            out.save(OUT / f"{d.name}_{when}_retake_v17.jpg", quality=95)
            r["retake_new"] = pct(FL.edge_ratio(out), eb)
            r["cost"] = load("pricing.yaml")["openai"]["edit"]
            ims.append(out); cols.append("새 재촬영(17차 후보)")
        t = f"세트 {d.name} · 골 선(Before 대비) B {r['B']}% · 메운 직후 {r['filled']}% · 지금 최종 {r['final_now']}%" + \
            (f" · 새 {r['retake_new']}%" if PAID else "")
        board(ims, cols, t).save(OUT / f"{d.name}_{when}_compare.jpg", quality=92)
        res[f"{d.name}_{when}"] = r
        print(d.name, json.dumps(r, ensure_ascii=False), flush=True)
(OUT / "retake_compare.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
