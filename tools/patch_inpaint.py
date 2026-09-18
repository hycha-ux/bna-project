"""직후 컷 패치를 **모델이 그 자리에서 직접 그리게** 한다 — B안 (2026-09-18 빌디 제안, 연서님 "새 패치가 떠 보인다").

  python tools/patch_inpaint.py <원본 직후컷.jpg> <패치 없는 컷.jpg> <출력폴더> [--dry]

A안(patch_place.blend_patches)은 모델 그림에서 고리·점만 떼어 원본 위에 얹는다 → 피부결은 살지만 원본의 빛·명암·볼 곡면이
패치에 안 실려 '떠 보인다'. B안은 오려 붙이지 않는다:
  ① 자리 = landmarks.patch_spots (A안과 같다 — 위치는 연서님 확인 끝)
  ② 마스크 = 얼굴이 돌아간 만큼 가로로 눌린 **타원**(spots_mask 의 sx·ang)
  ③ 얼굴 아래쪽만 정사각형으로 잘라 1024 로 **확대해 편집** → 줄여서 되붙인다(패치 하나가 ~55px → ~150px 로 그려져
     피부결·테두리 디테일이 산다). 편집 결과는 ORB 로 입력에 다시 겹친 뒤(3~5% 확대돼 오는 버릇 — align 머리말) 타원 안만 쓴다.
  ④ 빈 원만 최대 PLACE_TRIES 회 다시(판정 = patch_place 의 덮임률).
⚠ 유료: 편집 1콜 ≈ $0.2, 빈 원 재시도마다 +1콜.
"""
import io
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bna.qa import landmarks  # noqa: E402
import patch_place as P  # noqa: E402

PROMPT = (
    "There are {n} editable ovals on this close-up of a cheek and jaw. Inside each oval, a small round clear "
    "hydrocolloid dressing is stuck flat onto the skin, filling most of the oval. It is thin and transparent: the skin "
    "texture, pores, stubble and tone show straight through it unchanged. It follows the curve of the cheek, so it "
    "looks slightly oval where the face turns away. Its edge is a faint glossy rim, brightest on the side facing the "
    "light in this photo and darker on the shadow side, exactly like the existing highlights on the skin. Under each "
    "dressing there is one tiny red needle mark, a little off-centre. The dressings differ slightly from each other. "
    "Match this photo's lighting direction, contrast, grain and focus exactly. Change nothing outside the ovals.")
EDIT_SIDE = 1024
PAD_R = 2.5            # 잘라낼 상자 = 패치 자리 전체를 감싸고 반지름 × 이만큼 여유


def crop_box(spots, size):
    xs = [s["x"] for s in spots]; ys = [s["y"] for s in spots]; r = max(s["r"] for s in spots)
    x0, x1 = min(xs) - PAD_R * r, max(xs) + PAD_R * r
    y0, y1 = min(ys) - PAD_R * r, max(ys) + PAD_R * r
    side = int(max(x1 - x0, y1 - y0))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    side = min(side, size[0], size[1])
    bx = int(min(max(cx - side / 2, 0), size[0] - side)); by = int(min(max(cy - side / 2, 0), size[1] - side))
    return (bx, by, bx + side, by + side)


def paint(p, base, spots):
    """base(패치 없는 전체 사진)의 spots 자리에 모델이 직접 그린 결과(전체 사진)를 돌려준다. 1콜."""
    box = crop_box(spots, base.size); side = box[2] - box[0]; k = EDIT_SIDE / side
    crop = base.crop(box).resize((EDIT_SIDE, EDIT_SIDE), Image.LANCZOS)
    local = [{**s, "x": (s["x"] - box[0]) * k, "y": (s["y"] - box[1]) * k, "r": s["r"] * k} for s in spots]
    m_big = landmarks.spots_mask(crop.size, local, feather=int(4 * k))
    b = p.edit(P._jpg(crop), PROMPT.format(n=len(spots)), P._png(m_big), [], "1:1")
    out = Image.open(io.BytesIO(b)).convert("RGB").resize(crop.size)
    out, info = P.align(crop, out); print("align:", info)
    out = landmarks.composite_outside_mask(crop, out, m_big).resize((side, side), Image.LANCZOS)
    full = base.copy(); full.paste(out, box[:2])
    m_full = landmarks.spots_mask(base.size, spots, feather=3)
    return landmarks.composite_outside_mask(base, full, m_full)     # 타원 밖은 한 픽셀도 안 바뀐다(줄이기 오차 포함)


def main():
    src, clean_p, outdir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]); dry = "--dry" in sys.argv
    outdir.mkdir(parents=True, exist_ok=True)
    orig = Image.open(src).convert("RGB"); base = Image.open(clean_p).convert("RGB")
    spots = landmarks.patch_spots(landmarks.detect(orig))
    print("spots:", [(s["side"], s["name"], round(s["sx"], 2)) for s in spots])
    prev = base.copy()
    import numpy as np
    a = np.asarray(prev).copy(); m = np.asarray(landmarks.spots_mask(base.size, spots, feather=0)) > 0
    a[m] = (a[m] * 0.5 + np.array([0, 255, 0]) * 0.5).astype("uint8")
    Image.fromarray(a).save(outdir / f"{src.stem}_B_mask.png")
    if dry:
        return
    import os
    if not os.getenv("OPENAI_API_KEY"):
        for line in Path(os.environ.get("TEEMO_KEYS", r"C:\Users\medib\teemo\keys.env")).read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip()
    from bna.providers import get
    p = get("openai")
    result, todo = base, list(spots)
    for t in range(1, P.PLACE_TRIES + 1):
        result = paint(p, result, todo)
        todo = [s for s in todo if P._patch_parts(base, result, s)["cover"] < P.COVER_MIN]
        print(f"try {t}: 다시 그릴 원 {[(s['side'], s['name']) for s in todo]}")
        if not todo:
            break
    result.save(outdir / f"{src.stem}_B_inpaint.jpg", quality=95)
    print("saved", outdir)


if __name__ == "__main__":
    main()
