"""동일 인물 게이트 (A3): ArcFace 임베딩 코사인 유사도. 하드 페일.
insightface 미설치 시 score=None 으로 반환하고 상위에서 비전 채점으로 대체."""
import numpy as np
from PIL import Image

THRESHOLD = 0.60   # 초안. 스파이크에서 실제 사진 쌍(같은 사람/다른 사람)으로 캘리브레이션
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


def embed(img: Image.Image):
    app = _model()
    if app is None:
        return None
    faces = app.get(np.asarray(img.convert("RGB"))[:, :, ::-1])
    if not faces:
        return None
    f = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
    e = f.normed_embedding
    return e / np.linalg.norm(e)


def similarity(before: Image.Image, after: Image.Image):
    a, b = embed(before), embed(after)
    if a is None or b is None:
        return None
    return float(np.dot(a, b))


def check(before: Image.Image, after: Image.Image, threshold: float = THRESHOLD) -> dict:
    s = similarity(before, after)
    return {"similarity": s, "passed": None if s is None else s >= threshold, "hard_fail": s is not None and s < threshold}
