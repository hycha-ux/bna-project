"""직후 컷 패치 자리 후보 랜드마크를 번호와 함께 찍어 본다 (2026-09-18 티모, 조회 전용·돈 0).

쓰임: python tools/_probe_patch_spots_0918.py <이미지> <출력.png>
연서님 검수("마리오네트 패치는 턱선, 팔자 패치는 입 쪽으로 살짝")의 기준점을 눈으로 고르기 위한 것.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bna.qa import landmarks  # noqa: E402

CAND = [61, 291, 57, 287, 212, 432, 216, 436, 206, 426, 214, 434, 192, 416, 202, 422,
        172, 136, 150, 149, 176, 148, 397, 365, 379, 378, 400, 377, 152, 58, 288,
        468, 473]

src, out = sys.argv[1], sys.argv[2]
img = Image.open(src).convert("RGB")
pts = landmarks.detect(img)
print("points:", None if pts is None else len(pts))
d = ImageDraw.Draw(img)
for i in CAND:
    if pts is None or i >= len(pts):
        continue
    x, y = pts[i]
    d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 0, 0))
    d.text((x + 4, y - 6), str(i), fill=(255, 255, 0))
# 입 아래쪽만 크게 잘라 본다
xs = [pts[i][0] for i in (58, 288)]; ys = [pts[i][1] for i in (1, 152)]
box = (int(min(xs)) - 20, int(min(ys)) - 20, int(max(xs)) + 20, int(max(ys)) + 30)
crop = img.crop(box)
crop = crop.resize((crop.width * 2, crop.height * 2))
crop.save(out)
print("saved", out)
