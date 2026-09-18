"""직후 컷 패치 위치 게이트 — C안 (2026-09-18 빌디/연서님: "후처리는 접고, 좌표 계산은 채점 게이트로만").

직후 컷은 프롬프트가 패치까지 한 번에 그린다(후처리 없음). 이 게이트는 **그 그림에서** 얼굴 점을 다시 찾아
패치 자리(landmarks.patch_spots)를 계산하고, 각 자리 둘레에 허용 원(반지름 = 홍채 지름 TOL_IRIS 개)을 둔다.
패치는 비전 모델이 **하나씩 상자로 짚고**(DETECT_MODEL), 원 안/밖·개수·어긋난 방향과 거리는 **코드가 잰다**.

왜 픽셀로 안 찾나: 패치는 무색 투명이라 테두리 광택 몇 px 뿐이다 — 09-18 원 검출(Hough)은 한 장에 46~81개를
  찾거나(모공·수염) 조건을 조이면 0개였다. 사람 눈에 보이는 걸 짚게 하는 쪽이 싸고 안정적이다.
왜 판정을 모델에 안 맡기나 (09-18 저녁 연서님 "겹친 패치를 덜 센다" + "실제 자리와 계산 자리의 차이를 적어 달라"):
  종전엔 GPT(gpt-5.1)에 원 그린 그림을 주고 "원마다 참/거짓 + 원 밖 개수(정수)"를 물었다 → 붙은 테두리를 뭉쳐 셌다
  (5개쯤 보이는데 3). 좌표로 물었더니 **GPT 좌표는 엉뚱했다**(패치 3개 사진에 5점을 빈 턱에 찍음, 같은 사진 두 번에
  원 안 2→3). 같은 조각 4장을 Gemini 2.5 Flash / 3.1 Pro / 3.8 Flash 로 짚게 해 확대 사진으로 대 보니 **3.8 Flash 만
  상자가 테두리에 딱 붙었다**(tmp 눈 확인 PNG, 09-18). 그래서 짚기는 Gemini, 재기는 코드로 갈랐다.
판정은 3값: True 통과 / False 벗어남 / None 못 잼(얼굴 못 찾음·채점 실패). None 은 재생성 사유가 아니다(fail-open —
  못 잰 걸로 돈을 쓰지 않는다, 09-15 identity 교훈과 같은 결).
"""
import io
from itertools import permutations

from PIL import Image, ImageDraw, ImageFont

from . import landmarks

TOL_IRIS = 1.5      # 허용 반경 = 홍채 지름 × 이 값. 원 반지름 r 은 홍채 반지름이라 2r×TOL
                    #   1.0(빌디 "홍채 지름 1개로 시작") → 1.5 (09-18 오후 연서님 "실사진도 그 정도는 흔들린다").
                    #   ⚠ 여분 패치(개수)는 이걸 넓혀도 안 풀린다 — 그건 REASON 'count' 로 따로 센다.

# 탈락 사유 두 갈래 (09-18 오후 연서님 "원 밖 여분과 자리 오차가 갈라져 보이게").
#   count    = 원 밖에 떨어진 패치가 있다(개수가 많다) — 프롬프트(개수 문장)로 고칠 일
#   position = 반드시 있어야 할 원이 비었다(자리가 틀렸거나 빠졌다) — 허용 반경·위치 문장으로 고칠 일
#   둘 다일 수 있다(자리가 밀려 원 밖에 앉으면 원 하나가 비고 밖에 하나가 생긴다).
REASON_KO = {"count": "원 밖 여분", "position": "자리 오차"}


def closeness(gr: dict) -> tuple:
    """재시도가 다 떨어졌을 때 남길 컷을 고르는 키 — 클수록 계산 자리에 가깝다.
    원 안에 앉은 패치 수가 많을수록, 그다음 원 밖 여분이 적을수록. 못 잰 컷(None)은 맨 뒤."""
    if gr.get("inside") is None:
        return (-1, 0)
    return (gr["inside"], -(gr.get("outside") or 0))
CROP_PAD = 5.0      # 채점용 확대 조각 = 자리들을 감싸고 r × 이만큼 여유
                    #   3.0 → 5.0 (09-18 저녁): 허용 원 반지름이 3r(=1.5 홍채 지름)이라 3.0 이면 원이 조각 끝에 닿아,
                    #   바깥으로 밀린 패치가 조각 밖으로 잘려 '원 빔'만 남고 어디로 밀렸는지를 못 쟀다.

DETECT_MODEL = "gemini-3.8-flash"     # 짚기 모델 — 위 머리말의 09-18 비교로 골랐다. 바꾸면 눈 확인부터 다시.
MISS_IRIS = 3.0                       # 짝으로 인정하는 최대 거리(홍채 지름). 넘으면 '그 자리 빠짐'으로 보고한다.
MAX_DRESSINGS = 10                   # 짝짓기 전수 상한(10P6 = 15만 — 이보다 많이 짚으면 그림 자체가 틀렸다)
DETECT_COST = 0.003                  # 1회 어림(USD) — 약 1.9천 토큰. 확정 단가 아님, 원장엔 토큰을 그대로 적는다.

# 패치를 하나씩 상자로 짚게 한다(세는 게 아니라 짚는 것 — 겹친 테두리도 각자 한 상자). 원은 안 그린 깨끗한 조각을 보낸다
#   (원이 있으면 모델이 원을 패치로 짚거나 원 안만 본다).
PROMPT = (
    "Photo of the lower face right after a filler treatment. Small round CLEAR (transparent, colourless) "
    "hydrocolloid dressings are stuck on the skin; each shows only as a faint glossy circular or oval rim, "
    "usually with a tiny red dot inside. Detect EVERY such dressing, one box per rim. Rims that touch or "
    "overlap are separate dressings. A partial rim cut by the picture edge still counts. A red dot with no rim "
    "is not a dressing. "
    'Return JSON list: [{"box_2d": [ymin, xmin, ymax, xmax], "label": "dressing"}] with coordinates 0-1000.')


def _detect(crop: Image.Image) -> list:
    """깨끗한 조각 → [(cx, cy)] (조각 픽셀). 실패는 예외로 올린다(부르는 쪽이 None=못 잼으로 접는다)."""
    import base64, json, os, time, urllib.request
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY 없음")
    b = io.BytesIO(); crop.save(b, "JPEG", quality=92)
    body = {"contents": [{"parts": [{"text": PROMPT}, {"inline_data": {
                "mime_type": "image/jpeg", "data": base64.b64encode(b.getvalue()).decode()}}]}],
            "generationConfig": {"response_mime_type": "application/json", "temperature": 0}}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{DETECT_MODEL}:generateContent",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
    j = json.load(urllib.request.urlopen(req, timeout=120))
    try:                                         # 원장 — openai 쪽과 같은 파일, purpose 로 칸을 가른다
        from pathlib import Path
        p = Path(__file__).resolve().parents[3] / "outputs" / "usage.jsonl"
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": round(time.time(), 3), "path": "gemini:generateContent", "model": DETECT_MODEL,
                                "usage": j.get("usageMetadata") or {}, "purpose": "patch_gate"}) + "\n")
    except Exception:
        pass
    items = json.loads(j["candidates"][0]["content"]["parts"][0]["text"])
    if isinstance(items, dict):
        items = items.get("dressings") or items.get("items") or []
    out = []
    for q in items:
        y0, x0, y1, x1 = [float(v) for v in q["box_2d"]]
        out.append(((x0 + x1) / 2000 * crop.width, (y0 + y1) / 2000 * crop.height))
    return out


def _crop_box(img: Image.Image, spots: list):
    r = max(s["r"] for s in spots)
    xs = [s["x"] for s in spots]; ys = [s["y"] for s in spots]
    return (int(max(min(xs) - CROP_PAD * r, 0)), int(max(min(ys) - CROP_PAD * r, 0)),
            int(min(max(xs) + CROP_PAD * r, img.width)), int(min(max(ys) + CROP_PAD * r, img.height)))


def _overlay(img: Image.Image, spots: list):
    """허용 원을 번호와 함께 그린 확대 조각(PNG bytes)."""
    box = _crop_box(img, spots)
    k = 1024 / max(box[2] - box[0], box[3] - box[1])
    crop = img.convert("RGB").crop(box).resize((int((box[2] - box[0]) * k), int((box[3] - box[1]) * k)))
    d = ImageDraw.Draw(crop)
    try:                                         # 번호가 기본 글꼴(10px)로는 모델이 못 읽었다(09-18 저녁 확대 확인)
        font = ImageFont.load_default(size=36)
    except TypeError:
        font = None
    for i, s in enumerate(spots, 1):
        x, y = (s["x"] - box[0]) * k, (s["y"] - box[1]) * k
        R = 2 * s["r"] * TOL_IRIS * k
        d.ellipse([x - R, y - R, x + R, y + R], outline=(0, 230, 0), width=3)
        d.text((x + R * 0.72, y - R * 0.95), str(i), fill=(0, 230, 0), font=font, stroke_width=2, stroke_fill=(0, 0, 0))
    b = io.BytesIO(); crop.save(b, "PNG")
    return b.getvalue()


def _axes(pts):
    """얼굴 기준 축 — (across 단위벡터, up 단위벡터). landmarks.patch_spots 와 같은 정의."""
    import numpy as np
    pts = np.asarray(pts, float)
    up = pts[10] - pts[152]; up /= np.linalg.norm(up)
    across = pts[454] - pts[234]; across /= np.linalg.norm(across)
    return across, up


def offset(spot: dict, x: float, y: float, axes) -> dict:
    """계산 자리 → 실제 패치 중심의 차이. 얼굴 기준(바깥=귀 쪽 +, 위 +), 단위 = 홍채 지름(2r).
    09-18 저녁 연서님 "같은 방향으로 계속 벗어나는지 보려는 것" — 사진 좌우가 아니라 얼굴 기준이라야 양쪽 볼을 한 칸에 모은다."""
    across, up = axes
    o = across if spot["side"] == "R" else -across
    dx, dy = x - spot["x"], y - spot["y"]
    unit = 2 * spot["r"]
    out_, up_ = (dx * o[0] + dy * o[1]) / unit, (dx * up[0] + dy * up[1]) / unit
    return {"out": round(float(out_), 2), "up": round(float(up_), 2), "dist": round(float((out_ ** 2 + up_ ** 2) ** 0.5), 2)}


def direction_ko(off: dict) -> str:
    """{'out','up'} → '바깥·아래' 같은 한 줄. 0.3 홍채 미만 성분은 방향으로 안 친다."""
    h = "바깥" if off["out"] >= 0.3 else "입 쪽" if off["out"] <= -0.3 else ""
    v = "위" if off["up"] >= 0.3 else "아래" if off["up"] <= -0.3 else ""
    return "·".join(p for p in (h, v) if p) or "제자리"


def check(img: Image.Image, p_qa=None, detect=None) -> dict:
    # p_qa 는 배치 호출 모양을 안 바꾸려고 남겼다(09-18 저녁부터 짚기는 Gemini 직접). detect = 시험용 가짜 짚기.
    """{'passed': True|False|None, 'n': 자리 수, 'inside': 찬 필수 원 수, 'outside': 원 밖 패치 수, 'total': 본 패치 수,
        'offsets': 필수 자리마다 실제 패치와의 차이(얼굴 기준 방향·홍채 지름), 'dressings': 짚은 패치 좌표, 'note'}"""
    pts = landmarks.detect(img)
    if pts is None:
        return {"passed": None, "note": "얼굴 점 못 찾음"}
    need = landmarks.patch_spots(pts)                   # 반드시 패치가 있어야 하는 자리(보이는 곳)
    if not need:
        return {"passed": None, "note": "보이는 패치 자리 없음"}
    keys = {(s["side"], s["name"]) for s in need}
    extra = [s for s in landmarks.patch_spots(pts, strict=False) if (s["side"], s["name"]) not in keys]
    spots = need + extra                                # 원 번호: 필수 먼저, '있어도 되는 자리'(먼 쪽 볼) 뒤
    box = _crop_box(img, spots)
    k = 1024 / max(box[2] - box[0], box[3] - box[1])
    crop = img.convert("RGB").crop(box).resize((int((box[2] - box[0]) * k), int((box[3] - box[1]) * k)))
    try:
        found = (detect or _detect)(crop)
    except Exception as e:                      # 채점이 죽어도 생성을 죽이지 않는다
        return {"passed": None, "n": len(need), "note": f"채점 실패: {e!r}"[:200]}
    N = len(need)
    ds = [{"x": box[0] + cx / k, "y": box[1] + cy / k, "ring": 0} for cx, cy in found][:MAX_DRESSINGS]
    # 짝짓기 — 필수 자리마다 패치 하나씩, 거리 합이 가장 작은 짝(전수; N≤6·패치≤10 이라 싸다).
    #   '원마다 가장 가까운 패치'로 하면 두 원이 겹친 자리의 패치 하나를 두 원이 같이 가져가거나, 한 원이 뺏겨 빈 원의
    #   '어긋남'이 엉뚱한 먼 패치로 재진다(09-18 저녁 일본 40대 남 컷: 입꼬리 원을 비우고 첫 패치가 옆 원에 앉았다).
    dist = lambda d, s: ((d["x"] - s["x"]) ** 2 + (d["y"] - s["y"]) ** 2) ** 0.5
    best, pick = None, {}
    idx = list(range(len(ds)))
    for combo in permutations(idx + [None] * max(0, N - len(ds)), N):   # None = 짝 없음(패치가 모자랄 때만)
        c =sum(dist(ds[j], need[i]) if j is not None else 1e9 for i, j in enumerate(combo))
        if best is None or c < best:
            best, pick = c, {i: j for i, j in enumerate(combo) if j is not None}
    # 홍채 지름 MISS_IRIS 개보다 먼 짝은 짝이 아니다 — 그 자리엔 패치가 없고, 먼 패치는 다른 곳의 여분이다
    #   (09-18 저녁 중국 40대 여 컷: 오른쪽 턱선 패치가 빠졌는데 전수 짝짓기가 반대쪽 볼 패치를 5.7개 거리에서 끌어왔다).
    pick = {i: j for i, j in pick.items() if dist(ds[j], need[i]) <= 2 * need[i]["r"] * MISS_IRIS}
    inside = 0
    for i, j in pick.items():
        if dist(ds[j], need[i]) <= 2 * need[i]["r"] * TOL_IRIS:
            inside += 1; ds[j]["ring"] = i + 1
    matched = set(pick.values())
    for j, d in enumerate(ds):                  # 짝 없는 패치 — '있어도 되는 자리'(먼 쪽 볼) 원 안이면 여분이 아니다
        if j not in matched:
            opt = [n for n, s in enumerate(extra, N + 1) if dist(d, s) <= 2 * s["r"] * TOL_IRIS]
            d["ring"] = opt[0] if opt else 0
    extras = sum(1 for j, d in enumerate(ds) if j not in matched and d["ring"] == 0)
    outside = sum(1 for d in ds if d["ring"] == 0)
    # count 는 '원 밖에 있다'가 아니라 '필수 자리 수보다 많다'로 판정한다 (09-18 오후 첫 2세트 실측: 직후 8장 중 7장이
    #   "원 안 2 + 원 밖 1" = 셋을 그렸는데 하나가 밀린 것. outside>0 으로 세면 밀린 패치 하나가 두 사유로 동시에 잡혀
    #   개수 문제가 8/8 로 부풀었다 — 실제 여분(총 4개 이상)은 1장). 밀린 패치는 짝이 있으니 position 하나로만 센다.
    #   09-18 저녁: 짚기가 겹친 패치도 각자 잡으므로, 짝 못 받은 패치(= 필수 자리 수를 넘친 몫)가 곧 여분이다.
    reasons = (["position"] if inside < N else []) + (["count"] if extras else [])
    # 자리 차이(얼굴 기준 방향·홍채 지름 거리) — 짝지은 패치 기준. 얼굴 축을 못 구하면(가짜 점 등) 비운다.
    try:
        axes = _axes(pts)
    except Exception:
        axes = None
    offs = []
    for i, s in enumerate(need):
        if i not in pick or axes is None:
            offs.append({"spot": s["side"] + ":" + s["name"], "found": False, "dir": "빠짐"}); continue
        d = ds[pick[i]]
        o = offset(s, d["x"], d["y"], axes)
        offs.append({"spot": s["side"] + ":" + s["name"], "found": True, "in_ring": d["ring"] == i + 1, **o,
                     "dir": direction_ko(o)})
    return {"passed": inside == N and not extras, "reasons": reasons,
            "n": N, "inside": inside, "outside": outside, "total": len(ds), "optional": len(extra),
            "offsets": offs, "spots": [s["side"] + ":" + s["name"] for s in spots],
            "dressings": [{k: round(v, 1) if k != "ring" else v for k, v in d.items()} for d in ds],
            "note": f"{DETECT_MODEL} 짚음 {len(ds)}개"}
