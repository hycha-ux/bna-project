"""직후 컷 패치를 계산된 자리에 다시 붙인다 (2026-09-18 티모, 성연서님 "마리오네트는 턱 라인, 팔자는 입 쪽으로 살짝").

  python tools/patch_place.py <직후컷.jpg> <출력폴더> [--dry] [--reuse-clean]

⚠ 유료다 — 이미지 편집 2콜(약 $0.19 × 2). --dry 면 자리만 계산해 초록 원 미리보기만 저장한다(돈 0).
  ① 지우기: 팔자·마리오네트 부위 마스크 안의 기존 패치를 지운다(모델이 아무 데나 붙인 것).
  ② 붙이기: landmarks.patch_spots 로 계산한 원 안에만 새 패치를 그린다(고리가 온전하지 않은 원만 최대 3회 다시).
  ③ 합성: 모델 그림에서 고리·바늘 점만 떼어 원본 피부 위에 얹는다(blend_patches — 09-18 '합성 티' 교정).
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


PLACE_TRIES = 3       # 빈(또는 반쪽) 원만 다시 그리는 횟수 상한


# ── 붙인 자국 없애기 (2026-09-18 성연서님 "위치는 맞는데 합성이 제대로 안 됐어") ──
#   원본 크기로 확대해 본 원인 4개: ①패치 안 피부가 주변보다 매끈(모공 사라짐 = 원판을 오려 붙인 티)
#   ②원판 안 톤이 살짝 다름 ③테두리가 두껍고 번쩍(스티커 같음) ④그린 테두리가 반쪽뿐인 컷(초승달).
#   → 모델 결과를 통째로 쓰지 않고 **테두리 고리 + 바늘 점만** 원본 피부 위에 얹는다. 피부 결은 원본 그대로다
#     (투명 패치는 피부가 비쳐 보이는 물건이라 결이 보이는 게 맞다). 톤 차이는 저주파(흐린 판)끼리 맞춰 없앤다.
#     테두리가 반쪽이거나 없으면 같은 사진의 **가장 온전한 패치**를 본으로 찍는다(추가 호출 0).
RIM_GAIN = 0.75       # 테두리 세기 — 09-11 "너무 티나게 붙어 있어서 AI 같다" 이후 기준은 '희미한 광택 고리'다
RIM_SD = 0.09         # 고리 두께(반지름 비) — 실측 테두리 3~4px ÷ 반지름 26~27px
DOT_MIN = 7.0         # 붉은 기 증가가 이보다 작으면 점 없음 (09-18 실측: 정면 17.5~27 / 3/4 10~11 / 빈 원 4~5)
DOT_TARGET = 20.0     # 흐린 점을 이 세기까지 올린다 (정면 컷 점 중앙값 수준)
COVER_MIN = 0.7       # 고리가 둘레의 이만큼 이상 보여야 '온전' — 초승달은 0.3~0.5


def _patch_parts(orig, edited, s):
    """원 s 둘레에서 (고리 반지름, 고리+점 무게 맵, 톤 맞춘 차이, 둘레 덮임률, 상자) 를 잰다."""
    import cv2
    import numpy as np
    R = int(s["r"] * 1.7)
    x0, y0 = int(s["x"]) - R, int(s["y"]) - R
    box = (x0, y0, x0 + 2 * R, y0 + 2 * R)
    o = np.asarray(orig.crop(box), float); e = np.asarray(edited.crop(box), float)
    sig = s["r"] * 0.6
    e = e + (cv2.GaussianBlur(o, (0, 0), sig) - cv2.GaussianBlur(e, (0, 0), sig))   # 톤(저주파) 맞춤
    d = e - o
    yy, xx = np.mgrid[0:2 * R, 0:2 * R]
    pos = np.maximum(d.mean(axis=2), 0)
    # 고리의 **실제** 중심·반지름을 찾는다 (09-18 2차 교정, 연서님 "1번째 세트는 제대로 합성이 안 됨").
    #   모델은 원 안에서 패치를 한쪽으로 치우쳐 그린다 — 계산한 원 중심에 고리를 가정하면 실제 고리와 한쪽만 겹쳐
    #   반쪽 고리(초승달)만 옮겨지고 점이 테두리에 붙는다(정면 컷 턱선 패치가 그랬다). 밝은 고리가 가장 잘 맞는
    #   (중심 이동 ±0.4r, 반지름 0.6~1.3r) 을 격자로 고른다.
    best = (-1.0, 0.0, 0.0, 1.0)
    for dx in np.arange(-0.4, 0.41, 0.1):
        for dy in np.arange(-0.4, 0.41, 0.1):
            rd = np.hypot(xx - (s["x"] - x0 + dx * s["r"]), yy - (s["y"] - y0 + dy * s["r"])) / s["r"]
            for q in np.arange(0.6, 1.31, 0.05):
                sc = float(pos[np.abs(rd - q) < 0.06].mean())
                if sc > best[0]:
                    best = (sc, dx, dy, q)
    _sc, dx, dy, rr = best
    cx, cy = s["x"] - x0 + dx * s["r"], s["y"] - y0 + dy * s["r"]
    rad = np.hypot(xx - cx, yy - cy) / s["r"]
    ang = np.arctan2(yy - cy, xx - cx)
    rr = float(rr)
    ring = np.exp(-((rad - rr) ** 2) / (2 * RIM_SD ** 2))
    # 덮임률 = 둘레 24칸 중 '밝은 고리'가 보이는 칸 비율. 밝기 증가(+)만 센다 — 피부결 손실(±)이 섞이면
    #   초승달도 1.0 이 나왔다(09-18 첫 판정 실패). 기준 = 원 안쪽 밝기 증가 p90 의 2배(최소 8).
    #   09-18 실측: 정면 컷 온전한 고리 0.79~1.0 / 3/4 컷 반쪽·흐린 고리 0.33~0.46.
    band = np.abs(rad - rr) < 0.15
    bg = float(np.percentile(pos[rad < max(rr - 0.3, 0.2)], 90))
    bins = np.digitize(ang, np.linspace(-np.pi, np.pi, 25))
    hits = np.array([pos[band & (bins == b)].max() if (band & (bins == b)).any() else 0 for b in range(1, 25)])
    cover = float(np.mean(hits > max(2 * bg, 8.0)))
    red = lambda a: a[..., 0] - (a[..., 1] + a[..., 2]) / 2
    # 바늘 점 = 고리 안에서 붉은 기가 가장 많이 오른 곳. 고정 임계(12)는 3/4 컷의 흐린 점(10~11)을 통째로 버렸다
    #   (09-18 2차) → 그 원 최대값의 60% 이상(최소 DOT_MIN)으로 상대 판정, 흐린 점은 DOT_TARGET 까지 끌어올린다.
    dr = red(e) - red(o)
    inner = rad < rr * 0.9
    mx = float(dr[inner].max()) if inner.any() else 0.0
    dot = (dr >= max(DOT_MIN, 0.6 * mx)) & inner if mx >= DOT_MIN else np.zeros_like(inner)
    dotw = cv2.GaussianBlur(cv2.dilate(dot.astype(np.uint8), np.ones((3, 3))).astype(float), (0, 0), 1.2)
    if dot.any():
        d = d.copy()
        d[dotw > 0.05] *= min(DOT_TARGET / mx, 2.5) if mx < DOT_TARGET else 1.0
    w = np.maximum(ring * RIM_GAIN, np.clip(dotw * 1.5, 0, 1))
    return {"rr": rr, "w": w, "d": d, "cover": cover, "box": box, "rad": rad, "dotw": dotw,
            "has_dot": bool(dot.sum() >= 3), "off": (round(float(dx), 1), round(float(dy), 1))}


def blend_patches(orig, edited, spots):
    """원본(orig) 위에 모델 결과(edited)의 테두리·점만 얹는다. 반쪽·빈 원은 같은 사진의 가장 온전한 패치로 찍는다.
    돌려주는 것: (합성 사진, [{name, cover, source}])"""
    import numpy as np
    out = np.asarray(orig.convert("RGB"), float).copy()
    parts = [(_patch_parts(orig, edited, s), s) for s in spots]
    good = [p for p, _s in parts if p["cover"] >= COVER_MIN]
    tmpl = max(good, key=lambda p: (p["has_dot"], p["cover"])) if good else None   # 점까지 있는 패치를 본으로
    log = []
    for p, s in parts:
        src = p if p["cover"] >= COVER_MIN else tmpl
        if src is None:
            log.append({"name": s["name"], "side": s["side"], "cover": round(p["cover"], 2), "source": "none"}); continue
        x0, y0, x1, y1 = p["box"]
        dd, ww = src["d"], src["w"]
        if src is not p:          # 본 패치를 이 자리 크기로 맞춰 찍는다(점은 본의 것을 그대로 — 같은 조명·같은 사진)
            import cv2
            n = x1 - x0
            dd = cv2.resize(dd, (n, n)); ww = cv2.resize(ww, (n, n))
        h, wdt = out.shape[:2]
        cx0, cy0, cx1, cy1 = max(x0, 0), max(y0, 0), min(x1, wdt), min(y1, h)
        sl = (slice(cy0 - y0, cy1 - y0), slice(cx0 - x0, cx1 - x0))
        out[cy0:cy1, cx0:cx1] += dd[sl] * ww[sl][..., None]
        if src is p and not p["has_dot"] and tmpl is not None and tmpl["has_dot"]:
            # 고리는 온전한데 바늘 점이 없는 원 (09-18 정면 컷 왼쪽 팔자) — 본 패치의 점만 빌려 찍는다
            import cv2
            n = x1 - x0
            dotd = cv2.resize(tmpl["d"] * (tmpl["dotw"][..., None] > 0.05), (n, n))
            dotw = cv2.resize(np.clip(tmpl["dotw"] * 1.5, 0, 1), (n, n))
            out[cy0:cy1, cx0:cx1] += dotd[sl] * dotw[sl][..., None]
        log.append({"name": s["name"], "side": s["side"], "cover": round(p["cover"], 2), "off": p["off"],
                    "dot": p["has_dot"], "source": "own" if src is p else "template"})
    return Image.fromarray(np.clip(out, 0, 255).astype("uint8")), log


def tone_match(orig, edited, mask, sigma=40):
    """마스크 안의 톤 쏠림(저주파)만 원본에 맞춘다 — 09-18 3/4 컷 지우기 단계에서 볼 전체가 누렇게 떴다."""
    import cv2
    import numpy as np
    o = np.asarray(orig.convert("RGB"), float); e = np.asarray(edited.convert("RGB"), float)
    m = np.asarray(mask.convert("L"), float)[..., None] / 255
    fixed = e + (cv2.GaussianBlur(o, (0, 0), sigma) - cv2.GaussianBlur(e, (0, 0), sigma)) * m
    return Image.fromarray(np.clip(fixed, 0, 255).astype("uint8"))


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
    import numpy as np
    # 볼(cheeks)까지 — 09-18 3/4 컷에서 팔자 위쪽 볼에 앉은 옛 패치가 부위 마스크 밖이라 안 지워지고 남았다
    region = Image.fromarray(np.maximum(np.asarray(region), np.asarray(
        landmarks.region_mask(img, pts, "cheeks", feather=0).point(lambda v: 255 if v > 20 else 0))))
    region = region.filter(ImageFilter.MaxFilter(31)).filter(ImageFilter.GaussianBlur(6))
    if reuse:
        clean = Image.open(from_clean).convert("RGB")
    else:
        b1 = p.edit(_jpg(img), CLEAN_PROMPT, _png(region), [], "4:5")
        clean = Image.open(io.BytesIO(b1)).convert("RGB").resize(img.size)
        clean, info = align(img, clean); print("align clean:", info)
        clean = landmarks.composite_outside_mask(img, clean, region)
        clean = tone_match(img, clean, region)          # 지운 자리 톤 쏠림(누렇게 뜸) 되돌리기
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
        # 빈 원 = 고리가 온전하지 않은 원(덮임률). 종전 '평균 변화량'은 초승달·흐린 고리를 '붙음'으로 셌다(09-18).
        todo = [s for s in todo if _patch_parts(clean, placed, s)["cover"] < COVER_MIN]
        print(f"try {t}: 다시 그릴 원 {[(s['side'], s['name']) for s in todo]}")
        if not todo:
            break
    placed.save(outdir / f"{src.stem}_2placed.jpg", quality=95)
    # ③ 합성 — 모델 그림을 통째로 쓰지 않고 고리·점만 원본 피부 위에 (blend_patches 머리말)
    final, log = blend_patches(clean, placed, spots)
    print("blend:", log)
    final.save(outdir / f"{src.stem}_3blend.jpg", quality=95)
    print("saved", outdir)


if __name__ == "__main__":
    main()
