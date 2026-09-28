"""실제 전·후 쌍의 코 옆 골 그늘 감소량 = A안 목표값 (2026-09-28 8차 연서님 "실제 쌍에서 재서 그 값을 A 목표로").

  python tools/fold_shade_ref.py [before after]      # 기본 = nasolabial_before_01 → after2w_01

골 그늘 = 부위(nasal_fold) 안에서 '중간 흐림 − 큰 흐림'의 음수 부분 평균(bna.foldlift.shade 와 같은 자).
사진마다 자기 얼굴 점으로 부위를 잡는다(정렬 불필요 — 그늘은 주변 대비라 노출·위치에 덜 흔들린다).
"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bna.foldlift import shade  # noqa: E402

REF = ROOT / "samples" / "reference" / "clinical"
a = sys.argv[1:]
b_path = Path(a[0]) if a else REF / "nasolabial_before_01.jpg"
a_path = Path(a[1]) if len(a) > 1 else REF / "nasolabial_after2w_01.jpg"
sb, sa = shade(Image.open(b_path)), shade(Image.open(a_path))
print(f"before {sb:.3f} · after {sa:.3f} · 변화 {(sa - sb) / sb * 100:+.1f}%")
