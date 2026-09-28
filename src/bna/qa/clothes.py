"""옷 색 비교 자 (2026-09-28 14차 연서님 "전·후 옷 영역 색 비교 자 넣어서 1주 이후인데 같으면 After만 다시").

옷 영역 = 턱 끝(152) 아래로 얼굴 높이의 35% 내려간 곳부터 사진 끝까지, 얼굴 가운데 ±얼굴 폭 0.9배. 거기서
피부처럼 보이는 픽셀(얼굴 볼 색과 가까운 것 — 목·쇄골)을 빼고 남은 픽셀의 Lab 중앙값을 옷 색으로 본다.
머리카락이 걸쳐도 중앙값이라 덜 흔들린다. 전·후 옷 색 차 = 두 중앙값의 ΔE(CIE76, OpenCV Lab 0~255 스케일을 L*a*b* 로 환산).
못 재면(얼굴 점 없음·옷 영역이 너무 작음) None — 게이트는 걸지 않는다(fail-open).
"""
import numpy as np
from PIL import Image

from . import landmarks as L

CHEEK = [117, 118, 101, 50, 346, 347, 330, 280]


def _lab(rgb):
    import cv2
    lab = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2LAB).astype(np.float32)
    lab[:, :, 0] *= 100.0 / 255.0
    lab[:, :, 1:] -= 128.0
    return lab


def clothes_color(img: Image.Image, pts=None):
    """옷 영역 Lab 중앙값과 쓴 픽셀 수. 못 재면 None."""
    rgb = img.convert("RGB")
    pts = L.detect(rgb) if pts is None else pts
    if pts is None:
        return None
    h, w = rgb.size[1], rgb.size[0]
    oval = pts[L.FACE_OVAL]
    top, chin = float(oval[:, 1].min()), float(pts[152][1])
    fx0, fx1 = float(oval[:, 0].min()), float(oval[:, 0].max())
    fw, fh, cx = fx1 - fx0, chin - top, (fx0 + fx1) / 2
    # 임상 구도는 턱 바로 아래에서 잘린다(1024×1280 실측: 턱 1009, 옷은 양옆 980부터) — 턱 아래 5% 부터 본다
    y0 = int(min(h - 1, chin + fh * 0.05))
    x0, x1 = int(max(0, cx - fw * 0.9)), int(min(w, cx + fw * 0.9))
    if h - y0 < h * 0.03 or x1 - x0 < 10:
        return None
    lab = _lab(rgb)
    reg = lab[y0:, x0:x1].reshape(-1, 3)
    ck = lab[pts[CHEEK][:, 1].astype(int).clip(0, h - 1), pts[CHEEK][:, 0].astype(int).clip(0, w - 1)]
    skin = np.median(ck, axis=0)
    c = max(4, int(w * 0.05))
    bg = np.median(np.concatenate([lab[:c, :c].reshape(-1, 3), lab[:c, -c:].reshape(-1, 3)]), axis=0)   # 배경 = 위 두 모서리
    far = (np.linalg.norm(reg - skin, axis=1) > 12.0) & (np.linalg.norm(reg - bg, axis=1) > 8.0)   # 목 피부·배경 빼기
    px = reg[far]
    if len(px) < max(300, reg.shape[0] * 0.08):
        return None
    return {"lab": [round(float(v), 1) for v in np.median(px, axis=0)], "n": int(len(px))}


def clothes_diff(before: Image.Image, after: Image.Image) -> dict:
    """{"dE": 전·후 옷 색 차, "before": {...}, "after": {...}} — 못 재면 dE None."""
    cb, ca = clothes_color(before), clothes_color(after)
    if not (cb and ca):
        return {"dE": None, "before": cb, "after": ca}
    return {"dE": round(float(np.linalg.norm(np.array(cb["lab"]) - np.array(ca["lab"]))), 1), "before": cb, "after": ca}
