"""직후 컷에 투명 패치를 **모델 밖에서** 얹는다 — 21차 (2026-09-29 성연서님 "팔자 효과처럼 패치도 우리가 직접 얹어보자").

  python tools/patch_film.py <패치 없는 직후컷.jpg> <출력.jpg> [--seed N] [--debug]
  python tools/patch_film.py --compare <v57.jpg> <v58.jpg> <v59.jpg> <출력.png>

돈 0 (API 호출 없음). v58 까지 문장을 바꿔도 모델의 '패치 아이콘'(같은 원판·같은 반사·같은 동그란 점)이 안 바뀌었다.
09-18 후처리(patch_place·patch_inpaint)는 모델이 원 안 피부를 **다시 그려서** 스티커 티가 났다 → 여기선 피부를 한 픽셀도
다시 그리지 않고, 원본 픽셀 위에 '얇은 막'이 만드는 빛 변화만 더한다:
  ① 막 안: 아주 옅은 광택(밝기 +1~2%, 채도 살짝 빠짐) — 투명 막이라 결·모공·톤은 그대로 비친다
  ② 가장자리: **한쪽 호(弧)에만** 희미한 반사. 반사 자리는 사진의 빛 쪽을 따르되 패치마다 ±50° 흔든다
  ③ 들뜬 곳: 짧은 호 하나만 테두리가 살짝 두껍고 그 안쪽에 공기층 광택 + 바깥에 아주 옅은 그림자 (없는 패치도 있다)
  ④ 바늘 자국: 작은 덩어리 2~4개를 겹친 불규칙 모양, 적갈색~어두운 갈색, 중심에서 치우친 자리, 하나는 거의 안 보이게
패치마다 크기(홍채 0.85~1.15배)·타원 정도·기울기·반사 자리·들뜸·자국이 다르다(같은 seed 면 같은 결과 — 재현용).
자리 = landmarks.patch_spots (09-18 연서님 확인 자리). 타원 눌림(sx·ang)은 거기서 받고 그 위에 패치별 흔들림을 더한다.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bna.qa import landmarks  # noqa: E402

SIZE_JIT = (0.85, 1.15)     # 반지름 = 홍채 반지름 × 이 범위
ASPECT_JIT = (0.82, 1.0)    # 패치 자체 타원 정도(세로/가로) — 볼 눌림(sx) 위에 곱한다
TILT_JIT = 35.0             # 타원 기울기 흔들림(도)
FILM_LIFT = 0.024          # 막 안 밝기 올림(0~1 비율) — '거의 안 보이는' 막 (0.012 는 확대해도 안 보였다)
FILM_DESAT = 0.04           # 막 안 채도 빠짐
EDGE_SD = 0.035             # 테두리 굵기(반지름 비)
GLINT_GAIN = (0.11, 0.19)   # 한쪽 반사 세기(흰색 쪽으로 섞는 비율 최대값) — 가는 선(1차)은 펜 자국, 0.07~0.14 띠(3차)는 확대해도 안 보였다
GLINT_ARC = (55.0, 110.0)   # 반사 호 길이(도)
GLINT_JIT = 50.0            # 반사 자리 = 빛 쪽 ± 이만큼
LIFT_P = 0.6                # 들뜬 곳이 있을 확률
LIFT_ARC = (25.0, 50.0)
NEEDLE_R = (0.05, 0.13)    # 바늘 자국 크기(반지름 비)
NEEDLE_OFF = (0.25, 0.55)   # 중심에서 치우친 거리(반지름 비)
NEEDLE_COLS = [(92, 42, 36), (84, 50, 40), (74, 46, 38), (98, 56, 44), (70, 40, 34)]   # 적갈색 ~ 어두운 갈색
NEEDLE_ALPHA = (0.45, 0.85)
NEEDLE_FAINT = 0.10         # '거의 안 보이는' 한 개의 불투명도


def _arc_w(theta, centre, span):
    """각도 theta(라디안 배열)가 centre(도) ± span/2 호 안에 얼마나 드는지 0~1 (가장자리 부드럽게)."""
    d = np.degrees(np.angle(np.exp(1j * (theta - np.radians(centre)))))
    return np.clip(1 - (np.abs(d) - span / 2) / (span * 0.35 + 1e-6), 0, 1) ** 1.5


def light_angle(img, pts):
    """얼굴 빛이 오는 쪽(도, 영상 좌표 — 0=오른쪽, 90=아래). 양 볼·이마·턱 밝기 차로 대강 잡는다."""
    L = np.asarray(img.convert("L"), float)
    def m(i):
        x, y = pts[i]; r = 12
        return L[int(y) - r:int(y) + r, int(x) - r:int(x) + r].mean()
    gx = m(454) - m(234)          # 오른쪽 볼 - 왼쪽 볼 (얼굴 점 기준이지만 영상 좌표로 쓴다)
    gy = m(152) - m(10)
    xr, xl = pts[454][0], pts[234][0]
    if xr < xl:
        gx = -gx
    return float(np.degrees(np.arctan2(gy, gx))) if abs(gx) + abs(gy) > 1 else -90.0


def skin_mask(img):
    """얼굴·몸 피부(분할 2·3)만 1 — 막이 머리카락·배경·옷 위에 뜨지 않게(첫 시험: 턱선 옆 패치가 머리카락 위로 넘어갔다)."""
    import mediapipe as mp
    from PIL import ImageFilter
    seg = landmarks._segmenter()
    if seg is None:
        return None
    cat = np.squeeze(seg.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(img.convert("RGB"))))
                     .category_mask.numpy_view())
    m = Image.fromarray((np.isin(cat, (2, 3)) * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(5))
    return np.asarray(m.filter(ImageFilter.GaussianBlur(2)), float) / 255.0


def film(img, spots, seed=0, light=-90.0, debug=None, skin=None):
    rng = np.random.default_rng(seed)
    a = np.asarray(img.convert("RGB"), float) / 255.0
    H, W = a.shape[:2]
    out = a.copy()
    faint_idx = int(rng.integers(len(spots))) if spots else -1
    log = []
    for i, s in enumerate(spots):
        r = s["r"] * rng.uniform(*SIZE_JIT)
        asp = rng.uniform(*ASPECT_JIT)
        tilt = s.get("ang", 0.0) + rng.uniform(-TILT_JIT, TILT_JIT)
        rx, ry = r * s.get("sx", 1.0), r * asp
        pad = int(r * 1.6) + 4
        x0, x1 = max(0, int(s["x"]) - pad), min(W, int(s["x"]) + pad)
        y0, y1 = max(0, int(s["y"]) - pad), min(H, int(s["y"]) + pad)
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(float)
        dx, dy = xx - s["x"], yy - s["y"]
        t = np.radians(tilt)
        u = (dx * np.cos(t) + dy * np.sin(t)) / rx
        v = (-dx * np.sin(t) + dy * np.cos(t)) / ry
        rad = np.hypot(u, v)
        theta = np.arctan2(dy, dx)                                  # 영상 좌표 각도(빛 방향과 같은 축)
        inside = np.clip((1.0 - rad) / 0.04, 0, 1)                  # 막 안(가장자리 부드럽게)
        edge = np.exp(-((rad - 1.0) ** 2) / (2 * EDGE_SD ** 2))
        patch = out[y0:y1, x0:x1]
        # ① 막 안: 옅은 광택 + 채도 살짝 빠짐 (결은 그대로 — 픽셀을 섞지 않고 밝기만 민다)
        lum = patch.mean(axis=2, keepdims=True)
        film_l = FILM_LIFT * rng.uniform(0.6, 1.3)
        patch = patch + (lum - patch) * (FILM_DESAT * inside[..., None]) + film_l * inside[..., None] * (1 - patch)
        # ② 한쪽 반사
        g_c = light + rng.uniform(-GLINT_JIT, GLINT_JIT)
        g_span = rng.uniform(*GLINT_ARC)
        g_gain = rng.uniform(*GLINT_GAIN)
        # 반사는 가는 선이 아니라 가장자리 안쪽의 부드러운 띠 — 호를 따라 세기도 들쭉날쭉(첫 시험: 흰 펜 선처럼 보였다)
        g_in = rng.uniform(0.90, 0.97)
        band = np.exp(-((rad - g_in) ** 2) / (2 * (EDGE_SD * rng.uniform(1.6, 2.4)) ** 2))
        k1, k2, p1, p2 = rng.integers(2, 5), rng.integers(3, 7), rng.uniform(0, 6.3), rng.uniform(0, 6.3)
        wob = 0.55 + 0.3 * np.sin(k1 * theta + p1) + 0.15 * np.sin(k2 * theta + p2)
        glint = (0.35 * edge + 0.65 * band) * _arc_w(theta, g_c, g_span) * g_gain * np.clip(wob, 0.35, 1)
        # 막의 턱(두께)이 만드는 아주 옅은 둘레 — 반사 호만 있으면 '떠 있는 초승달'로 읽혔다(2차 시험)
        glint = glint + edge * rng.uniform(0.03, 0.05) * np.clip(wob, 0.3, 1)
        # 반대쪽 테두리는 거의 안 보이게(아주 옅은 어둠 한 줄)
        shade = edge * _arc_w(theta, g_c + 180, 120) * rng.uniform(0.01, 0.03)
        # ③ 들뜬 곳
        lift_log = None
        if rng.random() < LIFT_P:
            l_c = rng.uniform(0, 360); l_span = rng.uniform(*LIFT_ARC)
            lw = _arc_w(theta, l_c, l_span)
            thick = np.exp(-((rad - 0.97) ** 2) / (2 * (EDGE_SD * 2.2) ** 2)) * lw
            glint = glint + thick * rng.uniform(0.02, 0.045)
            gap = np.clip((rad - 0.8) / 0.17, 0, 1) * (rad < 1) * lw * rng.uniform(0.02, 0.04)   # 공기층 광택(안쪽)
            glint = glint + gap
            shade = shade + np.exp(-((rad - 1.07) ** 2) / (2 * (EDGE_SD * 1.5) ** 2)) * lw * rng.uniform(0.04, 0.08)
            lift_log = round(l_c)
        patch = patch + glint[..., None] * (1 - patch) - shade[..., None] * patch
        # ④ 바늘 자국
        alpha = NEEDLE_FAINT if i == faint_idx else rng.uniform(*NEEDLE_ALPHA)
        col = np.array(NEEDLE_COLS[int(rng.integers(len(NEEDLE_COLS)))], float) / 255.0
        col = np.clip(col + rng.uniform(-0.03, 0.03, 3), 0, 1)
        n_ang = rng.uniform(0, 2 * np.pi); n_off = rng.uniform(*NEEDLE_OFF)
        nu, nv = n_off * np.cos(n_ang), n_off * np.sin(n_ang)          # 패치 좌표계
        ncx = s["x"] + nu * rx * np.cos(t) - nv * ry * np.sin(t)
        ncy = s["y"] + nu * rx * np.sin(t) + nv * ry * np.cos(t)
        nr = r * rng.uniform(*NEEDLE_R)
        mark = np.zeros_like(rad)
        for _ in range(int(rng.integers(2, 5))):                       # 작은 덩어리 2~4개 → 불규칙 모양
            bx = ncx + rng.normal(0, nr * 0.45); by = ncy + rng.normal(0, nr * 0.45)
            bs = nr * rng.uniform(0.35, 0.8); el = rng.uniform(0.5, 1.0); ba = rng.uniform(0, np.pi)
            ddx, ddy = xx - bx, yy - by
            pu = (ddx * np.cos(ba) + ddy * np.sin(ba)) / bs
            pv = (-ddx * np.sin(ba) + ddy * np.cos(ba)) / (bs * el)
            mark = np.maximum(mark, np.exp(-(pu ** 2 + pv ** 2) * 1.6) * rng.uniform(0.6, 1.0))
        halo = np.exp(-((xx - ncx) ** 2 + (yy - ncy) ** 2) / (2 * (nr * 2.2) ** 2)) * 0.12   # 아주 옅은 붉은 기
        red = np.array([0.72, 0.38, 0.36])
        patch = patch * (1 - halo[..., None] * alpha) + (patch * red) * (halo[..., None] * alpha)
        m = (mark * alpha)[..., None]
        patch = patch * (1 - m) + (patch * 0.35 + col * 0.65) * m        # 피부 결이 자국 안에도 조금 남게
        if skin is not None:
            sk = skin[y0:y1, x0:x1][..., None]
            patch = out[y0:y1, x0:x1] * (1 - sk) + patch * sk
        out[y0:y1, x0:x1] = np.clip(patch, 0, 1)
        log.append({"name": s["name"], "side": s["side"], "r": round(r, 1), "aspect": round(asp, 2),
                    "tilt": round(tilt), "glint_at": round(g_c), "glint_arc": round(g_span), "lift_at": lift_log,
                    "needle_alpha": round(alpha, 2), "needle_r": round(nr, 1)})
        if debug is not None:
            debug.append((s["x"], s["y"], rx, ry, tilt))
    return Image.fromarray((out * 255 + 0.5).astype(np.uint8)), log


def run(src, dst, seed=0, dbg=False):
    img = Image.open(src).convert("RGB")
    pts = landmarks.detect(img)
    if pts is None:
        raise SystemExit("얼굴 점 못 찾음")
    spots = landmarks.patch_spots(pts, size=img.size)
    light = light_angle(img, pts)
    dl = [] if dbg else None
    res, log = film(img, spots, seed=seed, light=light, debug=dl, skin=skin_mask(img))
    res.save(dst, quality=95)
    if dbg:
        d = res.copy(); dr = ImageDraw.Draw(d)
        for x, y, rx, ry, _ in dl:
            dr.ellipse([x - rx, y - ry, x + rx, y + ry], outline=(0, 255, 0), width=2)
        d.save(str(Path(dst).with_suffix("")) + "_spots.jpg", quality=90)
    return {"spots": len(spots), "light_deg": round(light), "patches": log}


def mouth_crop(img, pts, scale=1.0):
    """입 주변(양 입꼬리·턱선이 다 들어가게) — 얼굴 폭 기준이라 해상도가 달라도 같은 부위."""
    W = float(np.linalg.norm(pts[454] - pts[234]))
    cx = (pts[61][0] + pts[291][0]) / 2; cy = (pts[61][1] + pts[291][1]) / 2 + 0.05 * W
    hw, hh = 0.55 * W * scale, 0.36 * W * scale
    return img.crop((int(cx - hw), int(cy - hh), int(cx + hw), int(cy + hh)))


def tiles(path, dst, zoom=1.9, side=400):
    """패치 자리마다 확대 칸(반지름 × zoom 사방) — 한 장씩 눈으로 보는 용도."""
    im = Image.open(path).convert("RGB")
    sp = landmarks.patch_spots(landmarks.detect(im), size=im.size)
    b = Image.new("RGB", (side * 3, side * ((len(sp) + 2) // 3)))
    for i, s in enumerate(sp):
        r = s["r"] * zoom
        b.paste(im.crop((int(s["x"] - r), int(s["y"] - r), int(s["x"] + r), int(s["y"] + r))).resize((side, side)),
                ((i % 3) * side, (i // 3) * side))
    b.save(dst, quality=92)


def compare(paths, labels, dst, width=1400):
    rows = []
    for p, lab in zip(paths, labels):
        img = Image.open(p).convert("RGB")
        pts = landmarks.detect(img)
        c = mouth_crop(img, pts).resize((width, int(width * 0.36 / 0.55)), Image.LANCZOS)
        rows.append((c, lab))
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    bar = 56
    H = sum(c.height + bar for c, _ in rows)
    board = Image.new("RGB", (width, H), (250, 250, 250))
    y = 0
    for c, lab in rows:
        ImageDraw.Draw(board).text((16, y + 10), lab, fill=(20, 20, 20), font=font)
        board.paste(c, (0, y + bar)); y += c.height + bar
    board.save(dst)


if __name__ == "__main__":
    A = sys.argv[1:]
    if A and A[0] == "--compare":
        compare(A[1:4], ["v57 (모델이 그린 패치)", "v58 (점 문장 교체)", "v59 (패치 없이 생성 → 막 합성)"], A[4])
    elif A and A[0] == "--tiles":
        tiles(A[1], A[2])
    else:
        seed = int(A[A.index("--seed") + 1]) if "--seed" in A else 0
        import json
        print(json.dumps(run(A[0], A[1], seed, "--debug" in A), ensure_ascii=False, indent=1))
