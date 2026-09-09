"""씨앗·파생 사진의 *열람용* 축소본을 만든다.

왜: 파생 원본이 장당 1.5MB 라 35장이면 22MB 다 — 격자 화면에서 그대로 부르면 느리고,
    필요 이상으로 큰 얼굴을 클라우드에 두게 된다. 긴 변 1024·q82 면 눈으로 판정하기엔
    충분하고 용량은 1/10 이다.

    python ops/seedbank-view.py <입력폴더> <출력폴더> [파일명...]

EXIF 는 애초에 씨앗 단계에서 지웠지만, 여기서도 픽셀만 새로 써서 아무것도 물려주지 않는다.
"""
import sys
from pathlib import Path
from PIL import Image

MAX_SIDE = 1024
QUALITY = 82


def main() -> int:
    if len(sys.argv) < 3:
        print("사용법: seedbank-view.py <입력폴더> <출력폴더> [파일명...]")
        return 2
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    names = sys.argv[3:] or [p.name for p in sorted(src.glob("*.jpg"))]
    dst.mkdir(parents=True, exist_ok=True)

    done = 0
    for name in names:
        img = Image.open(src / name)
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > MAX_SIDE:
            s = MAX_SIDE / max(w, h)
            img = img.resize((round(w * s), round(h * s)), Image.LANCZOS)
        out = Image.new("RGB", img.size)   # 픽셀만 옮긴다 = 메타데이터 미상속
        out.paste(img)
        out.save(dst / name, "JPEG", quality=QUALITY, optimize=True)
        done += 1
    print(f"열람용 축소 {done}장 -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
