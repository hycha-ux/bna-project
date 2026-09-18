"""09-18 패치 붙이기 결과를 새로 그리지 않고 다시 합성한다 (돈 0) — 성연서님 "위치는 맞는데 합성이 제대로 안 됐어".

  python tools/_recomposite_0918.py
입력 = outputs/_patch_place_0918 의 _1clean(지우기 결과)·_2placed(붙이기 결과), 원본 = 2fae 직후 컷.
"""
import sys
from pathlib import Path

from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bna.qa import landmarks  # noqa: E402
import patch_place as P  # noqa: E402

B = Path("outputs/20260918-084112-2fae"); O = Path("outputs/_patch_place_0918")
for sub, st in [("0000", "nasolabial_selfie_korea30sm_0000_after_immediate"),
                ("0001", "nasolabial_selfie_korealate_20sm_0001_after_immediate")]:
    orig = Image.open(B / sub / f"{st}.jpg").convert("RGB")
    pts = landmarks.detect(orig)
    region = landmarks.region_mask(orig, pts, "nasolabial_marionette", feather=6).point(lambda v: 255 if v > 20 else 0)
    region = region.filter(ImageFilter.MaxFilter(31)).filter(ImageFilter.GaussianBlur(6))   # patch_place 와 같은 마스크
    clean = P.tone_match(orig, Image.open(O / f"{st}_1clean.jpg").convert("RGB"), region)
    spots = landmarks.patch_spots(pts)
    out, log = P.blend_patches(clean, Image.open(O / f"{st}_2placed.jpg").convert("RGB"), spots)
    out.save(O / f"{st}_3blend.jpg", quality=95)
    print(st[-26:], log)
