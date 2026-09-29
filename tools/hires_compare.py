"""고해상도 시험 비교 (2026-09-29 연서님 "1024×1280 은 모공이 1px 도 안 돼 모델이 부풀려 그린다 — 2304×2880 1세트와 같은 부위 확대 비교").

  PYTHONPATH=src python tools/hires_compare.py <지금 해상도 세트 폴더> <고해상도 세트 폴더> <출력.jpg>

같은 부위 = 얼굴 점 기준·눈 사이 거리 × 0.45 정사각(해상도가 달라도 얼굴에서 같은 넓이). 칸마다 원본 픽셀 수를 적는다.
열 = 지금 해상도 Before · After(최종) · 고해상도 Before · After(최종). 행 = 이마·콧등·윗볼·팔자.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from bna.qa import landmarks as L

LO, HI, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
FT = lambda n: ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", n)  # noqa: E731
ZOOMS = [("이마", 151), ("콧등", 197), ("윗볼", 50), ("팔자", 206)]
FRAC, CW = 0.45, 380


def pair(d):
    return [Image.open(next(d.glob(f"*_{k}.jpg"))).convert("RGB") for k in ("before", "after")]


ims = pair(LO) + pair(HI)
pts = [L.detect(im) for im in ims]
cols = [f"{ims[0].size[0]}×{ims[0].size[1]} Before", "After(최종)", f"{ims[2].size[0]}×{ims[2].size[1]} Before", "After(최종)"]
W, H = 100 + CW * 4 + 10, 60 + len(ZOOMS) * (CW + 34) + 10
c = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(c)
for j, t in enumerate(cols):
    d.text((100 + j * CW + 6, 14), t, fill="black", font=FT(22))
y = 56
for nm, idx in ZOOMS:
    d.text((8, y + CW // 2), nm, fill="black", font=FT(20))
    for j, (im, p) in enumerate(zip(ims, pts)):
        k = L.key_points(p); s = float(np.linalg.norm(k["eye_r"] - k["eye_l"])) * FRAC
        x, yy = p[idx]
        cr = im.crop((int(x - s / 2), int(yy - s / 2), int(x + s / 2), int(yy + s / 2)))
        c.paste(cr.resize((CW, CW), Image.LANCZOS), (100 + j * CW, y + 26))
        d.text((100 + j * CW + 6, y + 2), f"원본 {cr.size[0]}px", fill=(90, 90, 90), font=FT(16))
    y += CW + 34
c.save(OUT, quality=92)
print(OUT)
