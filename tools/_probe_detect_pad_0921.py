"""부분 크롭 컷에서 MediaPipe 얼굴 검출이 실패할 때, 여백 패딩·확대가 살리는지 재는 조회 전용 프로브.

배경: 09-18 c4/c5 회차에서 '코 아래 크롭' 셀카의 직후 컷이 얼굴 점 미검출(None)로
      위치 게이트가 통째로 '못 잼'이 됐다(LESSONS 09-18 c4·c5). 대책 두 층 중
      '자(iris→입 너비)'는 v26 에서 했고 남은 층이 '검출'이다.
비용 0 — 이미 있는 산출물 파일만 읽는다. 어떤 것도 쓰지 않는다.
"""
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from bna.qa import landmarks  # noqa: E402


def variants(img: Image.Image):
    w, h = img.size
    yield "원본", img
    for f in (0.25, 0.5, 1.0):                      # 사방 여백(원본 대비 비율), 가장자리색으로 채움
        pw, ph = int(w * f), int(h * f)
        edge = img.resize((1, 1)).getpixel((0, 0))
        canvas = Image.new("RGB", (w + 2 * pw, h + 2 * ph), edge)
        canvas.paste(img, (pw, ph))
        yield f"여백 {int(f*100)}%", canvas
    for s in (1.5, 2.0):
        yield f"확대 x{s}", img.resize((int(w * s), int(h * s)), Image.LANCZOS)


def main(paths):
    for p in paths:
        img = Image.open(p).convert("RGB")
        print(f"\n== {Path(p).name}  {img.size}")
        for name, v in variants(img):
            pts = landmarks.detect(v)
            print(f"   {name:10s} -> {'점 %d개' % len(pts) if pts is not None else '못 찾음'}")


if __name__ == "__main__":
    main(sys.argv[1:])
