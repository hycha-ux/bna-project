"""직후 컷 패치를 계산된 자리에 다시 붙인다 (2026-09-18 티모, 성연서님 "마리오네트는 턱 라인, 팔자는 입 쪽으로 살짝").

  python tools/patch_place.py <직후컷.jpg> <출력폴더> [--dry] [--reuse-clean]

⚠ 유료다 — 이미지 편집 2콜(약 $0.19 × 2). --dry 면 자리만 계산해 초록 원 미리보기만 저장한다(돈 0).
  ① 지우기: 팔자·마리오네트 부위 마스크 안의 기존 패치를 지운다(모델이 아무 데나 붙인 것).
  ② 붙이기: landmarks.patch_spots 로 계산한 원 안에만 새 패치를 그린다.
  두 단계 모두 **마스크 밖은 원본 픽셀로 되돌린다**(composite) — 모델은 마스크를 '안내'로만 읽고 밖도 살짝 다시 그린다.
  자리는 모델이 아니라 이 합성이 정한다. 그래서 "2px 더 안쪽" 같은 요청이 숫자 하나(landmarks.NASO_PULL)로 된다.

이건 오늘 회차 컷으로 자리를 눈 확인하는 도구다. 배치 파이프라인 편입(직후 컷 1차=패치 없이 → 2차=이 붙이기)은
연서님이 자리를 확인한 뒤에 한다 — 자리가 틀린 채로 편입하면 모든 세트가 같은 자리로 틀린다.
"""
import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bna.qa import landmarks  # noqa: E402

CLEAN_PROMPT = (
    "Remove every small round clear dressing or sticker from the skin inside the editable area, "
    "and any tiny red needle mark under them, so that area shows plain skin. Keep the same skin texture, pores, "
    "stubble, tone, lighting, grain and focus as the rest of the photo, and keep the folds exactly as they are. "
    "Change nothing else.")
PLACE_PROMPT = (
    "Inside each editable circle, place exactly one small round clear hydrocolloid dressing, centred in the circle and "
    "filling most of it. It is colourless and the skin shows straight through it, so it is visible only as a faint glossy "
    "circular rim catching the light, with a single tiny red needle mark beneath it, a little off-centre. The dressings "
    "differ slightly from each other: one a touch smaller, one with an edge faintly lifted. Match the photo's lighting, "
    "grain and focus exactly. Change nothing outside the circles.")


def _png(img):
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()


def _jpg(img):
    b = io.BytesIO(); img.convert("RGB").save(b, "JPEG", quality=95); return b.getvalue()


def align(ref, moving):
    """모델 출력(moving)을 입력(ref)에 픽셀로 겹친다 — 닮음 변환(이동·회전·배율), ORB 특징점 + RANSAC.

    ⚠ 09-18 실측: 3/4 컷에서 편집 결과가 **구도를 살짝 옮겨** 돌아왔고, 그대로 부위 마스크로 합성하니
      입술이 두 겹이 됐다(편집은 같은 크기 사진을 주지만 같은 자리를 보장하지 않는다).
      못 맞추면(특징점 부족) 원래 것을 그대로 돌려준다 — 화면은 사람이 눈으로 보고 버린다."""
    import cv2
    import numpy as np
    a = cv2.cvtColor(np.asarray(ref.convert("RGB")), cv2.COLOR_RGB2GRAY)
    b = cv2.cvtColor(np.asarray(moving.convert("RGB")), cv2.COLOR_RGB2GRAY)
    orb = cv2.ORB_create(4000)
    ka, da = orb.detectAndCompute(a, None); kb, db = orb.detectAndCompute(b, None)
    if da is None or db is None:
        return moving, None
    ms = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(db, da), key=lambda m: m.distance)[:800]
    if len(ms) < 20:
        return moving, None
    src = np.float32([kb[m.queryIdx].pt for m in ms]); dst = np.float32([ka[m.trainIdx].pt for m in ms])
    M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3)
    if M is None:
        return moving, None
    warped = cv2.warpAffine(np.asarray(moving.convert("RGB")), M, ref.size, borderMode=cv2.BORDER_REPLICATE)
    shift = float(np.hypot(M[0, 2], M[1, 2])); scale = float(np.hypot(M[0, 0], M[1, 0]))
    return Image.fromarray(warped), {"shift_px": round(shift, 1), "scale": round(scale, 4), "inliers": int(inl.sum())}


PLACE_TRIES = 3
PRESENT_MIN = 6.0     # 원 안 평균 밝기 변화(0~255)가 이보다 작으면 '안 붙음' — 09-18 실측 붙은 원 7.1~14.8 · 빈 원 4.6~5.4(재합성 잡음) 사이 — 여유가 얇으니 표본이 늘면 다시 재라


def changed(a, b, s) -> float:
    """원 s 안에서 a→b 평균 절대 차이(회색조). 패치가 붙었는지의 대리 값."""
    import numpy as np
    box = tuple(int(v) for v in (s["x"] - s["r"], s["y"] - s["r"], s["x"] + s["r"], s["y"] + s["r"]))
    x = np.asarray(a.convert("L").crop(box), float); y = np.asarray(b.convert("L").crop(box), float)
    return float(np.abs(x - y).mean())


def preview(img, spots):
    out = img.convert("RGB").copy(); d = ImageDraw.Draw(out)
    for s in spots:
        d.ellipse([s["x"] - s["r"], s["y"] - s["r"], s["x"] + s["r"], s["y"] + s["r"]], outline=(0, 255, 0), width=3)
    return out


def main():
    src, outdir = Path(sys.argv[1]), Path(sys.argv[2]); dry = "--dry" in sys.argv
    outdir.mkdir(parents=True, exist_ok=True)
    img = Image.open(src).convert("RGB")
    pts = landmarks.detect(img)
    if pts is None:
        sys.exit("얼굴 점을 못 찾았다 — 자리 계산 불가")
    spots = landmarks.patch_spots(pts)
    print("spots:", [(s["side"], s["name"], round(s["x"]), round(s["y"]), round(s["r"])) for s in spots])
    preview(img, spots).save(outdir / f"{src.stem}_spots.png")
    if dry:
        return
    from_clean = outdir / f"{src.stem}_1clean.jpg"
    reuse = "--reuse-clean" in sys.argv and from_clean.exists()     # 지우기 단계를 다시 사지 않는다
    # 키는 티모 keys.env 에서 이름만 골라 환경에 올린다(값은 출력하지 않는다 — _probe_ratelimit_0915 와 같은 방식)
    import os
    if not os.getenv("OPENAI_API_KEY"):
        vault = Path(os.environ.get("TEEMO_KEYS", r"C:\Users\medib\teemo\keys.env"))
        for line in vault.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip()
    from bna.providers import get
    p = get("openai")
    # ① 지우기 — 부위 마스크(팔자+마리오네트)를 조금 넓혀 가장자리 패치까지 덮는다
    region = landmarks.region_mask(img, pts, "nasolabial_marionette", feather=6)
    region = region.point(lambda v: 255 if v > 20 else 0)
    from PIL import ImageFilter
    region = region.filter(ImageFilter.MaxFilter(31)).filter(ImageFilter.GaussianBlur(6))
    if reuse:
        clean = Image.open(from_clean).convert("RGB")
    else:
        b1 = p.edit(_jpg(img), CLEAN_PROMPT, _png(region), [], "4:5")
        clean = Image.open(io.BytesIO(b1)).convert("RGB").resize(img.size)
        clean, info = align(img, clean); print("align clean:", info)
        clean = landmarks.composite_outside_mask(img, clean, region)
        clean.save(from_clean, quality=95)
    # ② 붙이기 — 계산한 원 안에만. 원마다 붙었는지 재고, 빈 원만 다시(최대 PLACE_TRIES 회).
    #   ⚠ 09-18 실측: 한 번에 원 3~5개를 주면 모델이 1~2개를 비워 둔다(2장 중 2장). 개수를 말해도 비는 원이 생겨
    #     '빈 원만 마스크로 다시'가 가장 싼 확정 방법이다(빈 원 없으면 추가 비용 0).
    placed = clean
    todo = list(spots)
    for t in range(1, PLACE_TRIES + 1):
        m = landmarks.spots_mask(img.size, todo)
        prompt = f"There are {len(todo)} editable circles. " + PLACE_PROMPT
        b2 = p.edit(_jpg(placed), prompt, _png(m), [], "4:5")
        new = Image.open(io.BytesIO(b2)).convert("RGB").resize(img.size)
        new, info = align(placed, new); print(f"align placed #{t}:", info)
        placed = landmarks.composite_outside_mask(placed, new, m)
        todo = [s for s in todo if changed(clean, placed, s) < PRESENT_MIN]
        print(f"try {t}: empty circles {[(s['side'], s['name']) for s in todo]}")
        if not todo:
            break
    placed.save(outdir / f"{src.stem}_2placed.jpg", quality=95)
    print("saved", outdir)


if __name__ == "__main__":
    main()
