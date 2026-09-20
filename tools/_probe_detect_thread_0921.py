"""같은 FaceLandmarker 인스턴스를 여러 스레드가 동시에 부르면 검출이 실패하는지 재는 조회 전용 프로브.
배경: 09-18 c5 회차의 '얼굴 점 못 찾음'이 사진 탓인지 동시 호출 탓인지 가른다. 비용 0.
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from bna.qa import landmarks  # noqa: E402

imgs = [Image.open(p).convert("RGB") for p in sys.argv[1:]]
for img in imgs:                      # 먼저 단독으로 한 번씩 (기준선)
    pts = landmarks.detect(img)
    print("단독", img.size, "점" if pts is not None else "못 찾음")

fails = 0
ROUNDS = 12
with ThreadPoolExecutor(max_workers=len(imgs)) as ex:
    for _ in range(ROUNDS):
        res = list(ex.map(landmarks.detect, imgs))
        for r in res:
            if r is None:
                fails += 1
print(f"동시 {len(imgs)}콜 x {ROUNDS}회 = {len(imgs)*ROUNDS}건 중 못 찾음 {fails}건")
