"""동일 인물 게이트 (A3): ArcFace 임베딩 코사인 유사도.

⚠ 이 게이트의 실패 모드는 '틀리게 막는 것'이 아니라 **'안 재는 것'** 이다.
   부분 크롭·초근접 셀카(레퍼런스에 가까울수록)에서 detector 가 얼굴을 아예 못 잡는데,
   종전 코드는 그걸 score=None → hard_fail=False 로 흘려보내 게이트가 조용히 꺼졌다.
   2026-09-08 실측: 8장 중 4장 미검출(GPT 전량), 그 사실이 통계 어디에도 안 남았다.

그래서 두 가지를 넣었다.
 ① 레터박스 재시도 — 얼굴이 프레임을 꽉 채우면 detector 의 스케일 범위를 벗어난다.
    캔버스 가운데로 축소 배치하면 되살아난다. 실측 검출 4/8 → 7/8,
    이미 잡히던 것들의 점수도 올랐다(0.679→0.708, 0.507→0.529).
    ⚠ det_size 를 키우는 건 정반대다 — 1280 으로 올리면 8장 전부 미검출이었다.
    ⚠ det_thresh 하향(0.5→0.3)은 무효였다 — 후보 자체가 안 생기는 문제라 임계와 무관하다.
 ② 3값 게이트 — ok / fail / **n/a**. n/a 는 '다른 사람'이 아니라 '못 잼'이라
    하드 페일이 아니고 비전 채점으로 넘기되, **그 비율이 통계에 남는다**(stats.summarize).

문턱 0.60 은 그대로 두었다(정면-정면 전제). 2026-09-08 실측 표본은 같은 인물 3쌍뿐이라
바꿀 근거가 못 된다 — 다만 그 3쌍에서 **같은 인물 최저 0.529 vs 다른 인물 최고 0.447** 로
구간이 겹치지 않았고, 0.60 은 각도가 벌어진 같은-인물 쌍(측면→정면)을 죽였다.
표본 30쌍 이상으로 재캘리브레이션이 필요하다. 그 전까지 REVIEW_BAND 는 '사람이 볼 구간'이다.
"""
import numpy as np
from PIL import Image

THRESHOLD = 0.60        # 초안. 정면-정면 전제 — 각도 차가 큰 쌍에는 높다(위 주석)
REVIEW_BAND = 0.45      # 이 값 이상 THRESHOLD 미만은 '탈락'이 아니라 '사람 확인' 구간
LETTERBOX_FILL = 0.5    # 재시도 시 원본이 캔버스에서 차지하는 비율 (실측 0.5·0.35 동률, 0.5 채택)
_app = None


def _model():
    global _app
    if _app is None:
        try:
            from insightface.app import FaceAnalysis
        except ImportError:
            return None
        _app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        _app.prepare(ctx_id=0, det_size=(640, 640))
    return _app


def _letterbox(img: Image.Image, fill: float = LETTERBOX_FILL) -> Image.Image:
    """얼굴이 프레임을 꽉 채운 사진을 회색 캔버스 가운데로 축소 배치한다."""
    w, h = img.size
    side = int(max(w, h) / fill)
    bg = Image.new("RGB", (side, side), (127, 127, 127))
    bg.paste(img.convert("RGB"), ((side - w) // 2, (side - h) // 2))
    return bg


def _detect(app, img: Image.Image):
    faces = app.get(np.asarray(img.convert("RGB"))[:, :, ::-1])
    if not faces:
        return None
    f = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
    e = f.normed_embedding
    return e / np.linalg.norm(e)


def embed(img: Image.Image):
    """임베딩. 원본에서 못 잡으면 레터박스로 1회 재시도한다(부분 크롭 구제)."""
    app = _model()
    if app is None:
        return None
    e = _detect(app, img)
    # ⚠ numpy 배열은 `or` 로 이으면 안 된다(진리값이 모호해 예외). 명시적으로 None 을 본다.
    return e if e is not None else _detect(app, _letterbox(img))


def similarity(before: Image.Image, after: Image.Image):
    a, b = embed(before), embed(after)
    if a is None or b is None:
        return None
    return float(np.dot(a, b))


def check(before: Image.Image, after: Image.Image, threshold: float = THRESHOLD) -> dict:
    """gate: ok | fail | review | n/a.
    n/a = 둘 중 하나에서 얼굴을 못 잡았다(= 못 잼). 하드 페일이 아니라 비전 채점으로 넘긴다."""
    s = similarity(before, after)
    if s is None:
        gate = "n/a"
    elif s >= threshold:
        gate = "ok"
    elif s >= REVIEW_BAND:
        gate = "review"
    else:
        gate = "fail"
    # passed 는 'ok' 일 때만 True 다. n/a·review 는 False 가 아니라 **미판정(None)** —
    # 이 둘을 False 로 접으면 "못 잰 것"이 "떨어진 것"으로 둔갑해 통계가 거짓말을 한다.
    return {"similarity": s, "gate": gate,
            "passed": True if gate == "ok" else (False if gate == "fail" else None),
            "hard_fail": gate == "fail",
            "measured": s is not None}
