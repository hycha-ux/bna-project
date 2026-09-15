"""임상 After 합성 방식 3안을 **실제 '따로 찍은' 전후 한 쌍**으로 눈 확인 (2026-09-15 티모, 빌디 확인 요청 1).

재료: samples/reference/clinical/nasolabial_before_01 + after2w_01 (같은 부스·다른 날 실사진).
      생성 없이 돈 0 — 모델 대신 '진짜 다시 찍은 After' 를 넣고 합성만 돌린다.
안:   now = 현행 composite_outside_mask(팔자 마스크 밖 = Before)
      b   = 빌디 제안(얼굴 안쪽 = Before, 머리·옷·배경 = After)
      off = 합성 없음(모델 출력 그대로)
출력: outputs/_probe/composite_0915.png (참조 사진 = 외부 웹 이미지 → 리포 밖·내부 확인용)
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bna.qa import landmarks as L  # noqa: E402

REF = ROOT / "samples" / "reference" / "clinical"
OUT = ROOT / "outputs" / "_probe"
OUT.mkdir(parents=True, exist_ok=True)

before = Image.open(REF / "nasolabial_before_01.jpg").convert("RGB")
after = Image.open(REF / "nasolabial_after2w_01.jpg").convert("RGB")
print("size before/after:", before.size, after.size)
if after.size != before.size:
    # 현행 코드는 크기가 다르면 Image.composite 가 ValueError 로 죽는다 — 여기선 보려고 맞춘다
    after = after.resize(before.size, Image.LANCZOS)

pb, pa = L.detect(before), L.detect(after)
if pb is None or pa is None:
    sys.exit("랜드마크 미검출 — 프로브 중단")
kb, ka = L.key_points(pb), L.key_points(pa)
ipd = float(np.linalg.norm(kb["eye_r"] - kb["eye_l"]))
shift = (ka["eye_l"] + ka["eye_r"]) / 2 - (kb["eye_l"] + kb["eye_r"]) / 2
luma = abs(np.asarray(before.convert("L")).mean() - np.asarray(after.convert("L")).mean()) / 255
print(f"실사진 쌍 실측: 눈 중심 이동 {shift.round(1)}px = IPD 대비 {np.linalg.norm(shift) / ipd * 100:.2f}% · 밝기차 {luma:.3f}")

m_naso = L.region_mask(before, pb, "nasolabial")
m_face = L.region_mask(before, pb, "full_face_skin")
now = L.composite_outside_mask(before, after, m_naso)
b = Image.composite(before, after, m_face)          # 얼굴 안 = Before, 밖 = After

# 경계 이음매 크기: 마스크 가장자리 띠에서 결과의 가로 그래디언트 평균을 원본 After 와 비교
def seam(img, mask):
    m = np.asarray(mask, dtype=float) / 255
    band = (m > 0.2) & (m < 0.8)
    g = np.abs(np.diff(np.asarray(img.convert("L"), dtype=float), axis=1))
    return float(g[band[:, 1:]].mean())

for name, img, mask in (("now", now, m_naso), ("b", b, m_face)):
    print(f"{name}: 경계 띠 그래디언트 {seam(img, mask):.2f} (같은 띠의 원본 After {seam(after, mask):.2f})")

W = 420
def tile(img, label):
    t = img.resize((W, int(img.height * W / img.width)))
    ImageDraw.Draw(t).rectangle([0, 0, W, 26], fill=(0, 0, 0))
    ImageDraw.Draw(t).text((6, 6), label, fill=(255, 255, 255))
    return t
tiles = [tile(before, "BEFORE"), tile(after, "AFTER (real reshoot)"),
         tile(now, "now: outside naso mask = Before"), tile(b, "b: inside face = Before")]
sheet = Image.new("RGB", (W * 4, tiles[0].height), "white")
for i, t in enumerate(tiles):
    sheet.paste(t, (W * i, 0))
sheet.save(OUT / "composite_0915.png")

# 이음매 확대(얼굴 윤곽 왼쪽 볼 가장자리)
x, y = int(pb[234][0]), int(pb[234][1])
box = (max(0, x - 80), max(0, y - 120), x + 80, y + 120)
zoom = Image.new("RGB", (160 * 3 * 2, 240 * 2), "white")
for i, img in enumerate((after, now, b)):
    zoom.paste(img.crop(box).resize((320, 480), Image.NEAREST), (320 * i, 0))
zoom.save(OUT / "composite_0915_zoom.png")
print("saved", OUT / "composite_0915.png")
