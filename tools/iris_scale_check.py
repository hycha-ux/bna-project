"""고해상도에서 패치 자리 자(홍채 지름)가 제대로 잡히는지 — 해상도 무관 비율로 대 본다 (2026-09-29 연서님 20차 ③).

  python tools/iris_scale_check.py <이미지> [<이미지> ...] [--draw out.png]

홍채 지름을 얼굴 폭(234↔454)으로 나눈 값은 해상도와 무관해야 한다. 1024×1280 컷과 2304×2880 컷에서
이 비율이 비슷하면 자는 제대로 늘어난 것이다. 겸해 좌우 홍채(468~472 / 473~477)를 따로 재 둘이 벌어지지 않는지 본다.
--draw 는 마지막 이미지에 계산 자리·허용 원(홍채 지름 × TOL_IRIS)을 그려 눈으로 확인하게 한다.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bna.qa import landmarks, patchgate  # noqa: E402


def one(path):
    img = Image.open(path)
    pts = landmarks.detect(img)
    if pts is None:
        return img, None, {"path": path, "note": "얼굴 점 못 찾음"}
    face_w = float(np.linalg.norm(pts[454] - pts[234]))
    diam, scale = landmarks.iris_diam(pts, img.size)
    # 좌우 홍채 따로: 가운데 점 + 둘레 4점의 가로 폭
    r_ir = float(np.linalg.norm(pts[469] - pts[471]))
    l_ir = float(np.linalg.norm(pts[474] - pts[476]))
    return img, pts, {"path": Path(path).name, "size": img.size, "face_w": round(face_w, 1), "iris": round(diam, 1),
                      "scale": scale, "iris/face": round(diam / face_w, 4),
                      "R/L": f"{r_ir:.1f}/{l_ir:.1f}"}


def main():
    a = sys.argv[1:]
    draw = a[a.index("--draw") + 1] if "--draw" in a else None
    paths = [p for i, p in enumerate(a) if p != "--draw" and (i == 0 or a[i - 1] != "--draw")]
    last = None
    for p in paths:
        img, pts, row = one(p)
        print(row)
        last = (img, pts)
    if draw and last and last[1] is not None:
        img, pts = last
        spots = landmarks.patch_spots(pts, size=img.size)
        im = img.convert("RGB")
        d = ImageDraw.Draw(im)
        for s in spots:
            R = 2 * s["r"] * patchgate.TOL_IRIS
            d.ellipse([s["x"] - R, s["y"] - R, s["x"] + R, s["y"] + R], outline=(0, 230, 0), width=max(2, im.width // 400))
            d.text((s["x"] + R, s["y"] - R), f'{s["side"]}:{s["name"]}', fill=(0, 230, 0))
        for i in (468, 473):
            x, y = pts[i][:2]
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(255, 0, 0))
        im.save(draw)
        print("그림:", draw, [(s["side"], s["name"], round(s["r"], 1)) for s in spots])


if __name__ == "__main__":
    main()
