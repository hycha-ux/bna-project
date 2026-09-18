"""직후 컷 패치 위치 게이트 — C안 (2026-09-18 빌디/연서님: "후처리는 접고, 좌표 계산은 채점 게이트로만").

직후 컷은 프롬프트가 패치까지 한 번에 그린다(후처리 없음). 이 게이트는 **그 그림에서** 얼굴 점을 다시 찾아
패치 자리(landmarks.patch_spots)를 계산하고, 각 자리 둘레에 허용 원(반지름 = 홍채 지름 TOL_IRIS 개)을 그려
비전 모델에 "원마다 패치 중심이 안에 있나 / 원 밖에 떨어진 패치가 몇 개인가"를 묻는다.

왜 픽셀로 안 찾나: 패치는 무색 투명이라 테두리 광택 몇 px 뿐이다 — 09-18 원 검출(Hough)은 한 장에 46~81개를
  찾거나(모공·수염) 조건을 조이면 0개였다. 사람 눈에 보이는 걸 묻는 쪽이 싸고($0.004) 안정적이다.
판정은 3값: True 통과 / False 벗어남 / None 못 잼(얼굴 못 찾음·채점 실패). None 은 재생성 사유가 아니다(fail-open —
  못 잰 걸로 돈을 쓰지 않는다, 09-15 identity 교훈과 같은 결).
"""
import io

from PIL import Image, ImageDraw

from . import landmarks

TOL_IRIS = 1.0      # 허용 반경 = 홍채 지름 × 이 값 (빌디 "홍채 지름 1개 정도로 시작"). 원 반지름 r 은 홍채 반지름이라 2r×TOL
CROP_PAD = 3.0      # 채점용 확대 조각 = 자리들을 감싸고 r × 이만큼 여유

PROMPT = (
    "This is a close-up of the lower face in a photo taken right after a filler treatment. Numbered green rings "
    "have been drawn on it. Look for small round CLEAR (transparent, colourless) dressings stuck on the skin - they "
    "show only as a faint glossy circular rim, often with a tiny red dot in the middle. Ignore the green rings "
    "themselves when looking for dressings.\n"
    "For each ring 1..{n}: is the CENTRE of a clear dressing inside that ring? "
    "Then count the clear dressings on the face whose centre is NOT inside any ring.\n"
    'Reply JSON only: {{"rings": {{"1": true|false, ...}}, "outside": <int>, "note": "<short>"}}')


def _overlay(img: Image.Image, spots: list):
    """허용 원을 번호와 함께 그린 확대 조각(PNG bytes)."""
    r = max(s["r"] for s in spots)
    xs = [s["x"] for s in spots]; ys = [s["y"] for s in spots]
    box = (int(max(min(xs) - CROP_PAD * r, 0)), int(max(min(ys) - CROP_PAD * r, 0)),
           int(min(max(xs) + CROP_PAD * r, img.width)), int(min(max(ys) + CROP_PAD * r, img.height)))
    k = 1024 / max(box[2] - box[0], box[3] - box[1])
    crop = img.convert("RGB").crop(box).resize((int((box[2] - box[0]) * k), int((box[3] - box[1]) * k)))
    d = ImageDraw.Draw(crop)
    for i, s in enumerate(spots, 1):
        x, y = (s["x"] - box[0]) * k, (s["y"] - box[1]) * k
        R = 2 * s["r"] * TOL_IRIS * k
        d.ellipse([x - R, y - R, x + R, y + R], outline=(0, 230, 0), width=3)
        d.text((x + R * 0.72, y - R * 0.95), str(i), fill=(0, 230, 0))
    b = io.BytesIO(); crop.save(b, "PNG")
    return b.getvalue()


def check(img: Image.Image, p_qa) -> dict:
    """{'passed': True|False|None, 'n': 자리 수, 'inside': 원 안 개수, 'outside': 원 밖 개수, 'note'}"""
    pts = landmarks.detect(img)
    if pts is None:
        return {"passed": None, "note": "얼굴 점 못 찾음"}
    need = landmarks.patch_spots(pts)                   # 반드시 패치가 있어야 하는 자리(보이는 곳)
    if not need:
        return {"passed": None, "note": "보이는 패치 자리 없음"}
    keys = {(s["side"], s["name"]) for s in need}
    extra = [s for s in landmarks.patch_spots(pts, strict=False) if (s["side"], s["name"]) not in keys]
    spots = need + extra                                # 원 번호: 필수 먼저, '있어도 되는 자리'(먼 쪽 볼) 뒤
    try:
        res = p_qa.chat_json(PROMPT.format(n=len(spots)), [_overlay(img, spots)], purpose="patch_gate")
        data = res.get("data") or {}
    except Exception as e:                      # 채점이 죽어도 생성을 죽이지 않는다
        return {"passed": None, "n": len(need), "note": f"채점 실패: {e!r}"[:200]}
    rings = data.get("rings") or {}
    got = [rings.get(str(i)) for i in range(1, len(spots) + 1)]
    if any(v is None for v in got[:len(need)]):
        return {"passed": None, "n": len(need), "note": "채점 누락", "raw": data}
    inside = sum(1 for v in got[:len(need)] if v is True)
    try:
        outside = int(data.get("outside") or 0)
    except (TypeError, ValueError):
        outside = None
    return {"passed": (inside == len(need) and outside == 0) if outside is not None else None,
            "n": len(need), "inside": inside, "outside": outside, "optional": len(extra),
            "spots": [s["side"] + ":" + s["name"] for s in spots], "note": str(data.get("note", ""))[:200]}
