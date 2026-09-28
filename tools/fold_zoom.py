"""팔자 부위 전·후 확대 비교 + '편집이 그 자리를 실제로 바꿨나' 수치 (2026-09-28 연서님 "효과 없음 4장 확대 비교 올려줘").

  python tools/fold_zoom.py <batch_id> <item> [<item> …] --out <png>

한 줄 = [전 확대 | 후 확대(전에 맞춰 정렬) | 변화 지도(밝을수록 많이 바뀜)].
- 정렬: 팔자 밖 얼굴 점(눈·이마·코 위)으로 닮음 변환을 구해 After 를 Before 좌표로 옮긴다 — 머리가 움직인 만큼은 변화로 안 센다.
- 수치(API 0, 로컬):
    in/out  = 팔자·마리오네트 부위 안 평균 밝기 변화 ÷ 부위 밖(이마·볼 위) 평균 밝기 변화. 1 근처 = 부위를 따로 안 건드림(전체가 같이 흔들림),
              클수록 편집이 부위에 몰렸다.
    주름 대비 = 부위 안 밝기 표준편차(그림자 골의 깊이 대리값) 전→후. 줄면 골이 옅어진 것.
결과 PNG 1장 + 같은 이름 .json.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bna.qa import landmarks as L  # noqa: E402
from bna.qa.structure import region_points  # noqa: E402

# 8차(2026-09-28)부터 코 옆 골 띠(nasal_fold) — 연서님 기준 "코 옆 그늘". 7차까지 수치(v49~v52 확대)는 nasolabial_marionette 로 잰 값이다.
REGION = "nasal_fold"
STABLE = [33, 133, 263, 362, 70, 105, 300, 334, 10, 151, 9, 168, 6, 197, 234, 454, 127, 356]   # 눈·눈썹·이마·콧대·관자 — 필러가 안 건드리는 점
CTRL = [116, 117, 118, 345, 346, 347, 10, 151, 108, 337]                                        # 대조 = 볼 윗부분·이마


def pair(d: Path, pass1=False):
    """전·후 한 쌍. 파일 짝은 meta 의 현재 인물(stem) 기준 — 재시도로 옛 인물 파일이 남아 있어도 안 섞인다.
    pass1=True 면 '전' 자리에 2단계 편집 직전(1단계) 사진을 놓는다 — 2단계가 무엇을 바꿨는지만 본다."""
    from bna.api import stem_of
    m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    st = stem_of(m)
    b = next((p for p in sorted(d.glob("*_before.jpg")) if st and p.name.startswith(st + "_")), None) or sorted(d.glob("*_before.jpg"))[0]
    a = b.with_name(b.name.replace("_before.jpg", "_after.jpg"))
    if pass1:
        b = sorted(d.glob("pass1_*.jpg"), key=lambda p: p.stat().st_mtime)[-1]
    return m, Image.open(b).convert("RGB"), Image.open(a).convert("RGB")


def poly_mask(shape, pts, idx_region):
    mk = np.zeros(shape[:2], np.uint8)
    reg = L.REGIONS[idx_region]
    parts = reg.split("+") if isinstance(reg, str) else [idx_region]
    for p in parts:
        ids = L.REGIONS[p]
        cv2.fillPoly(mk, [cv2.convexHull(pts[ids].astype(np.int32))], 255)
    return mk


def one(d: Path, pass1=False):
    m, bi, ai = pair(d, pass1)
    B, A = np.asarray(bi), np.asarray(ai.resize(bi.size))
    pb, pa = L.detect(bi), L.detect(Image.fromarray(A))
    if pb is None or pa is None:
        return None
    M, _ = cv2.estimateAffinePartial2D(pa[STABLE].astype(np.float32), pb[STABLE].astype(np.float32))
    Aw = cv2.warpAffine(A, M, (B.shape[1], B.shape[0]), borderMode=cv2.BORDER_REPLICATE)
    rp = region_points(pb, REGION)
    x0, y0 = rp.min(0); x1, y1 = rp.max(0)
    pad = 0.18 * (x1 - x0)
    x0, y0, x1, y1 = [int(v) for v in (max(0, x0 - pad), max(0, y0 - pad), min(B.shape[1], x1 + pad), min(B.shape[0], y1 + pad))]
    gb = cv2.cvtColor(B, cv2.COLOR_RGB2GRAY).astype(float)
    ga = cv2.cvtColor(Aw, cv2.COLOR_RGB2GRAY).astype(float)
    # 전체 밝기 차는 빼고 본다(노출 차이가 '변화'로 잡히지 않게)
    ga_n = ga - (ga.mean() - gb.mean())
    diff = np.abs(ga_n - gb)
    mk = poly_mask(B.shape, pb, REGION) > 0
    ctrl = np.zeros(B.shape[:2], np.uint8)
    cv2.fillPoly(ctrl, [cv2.convexHull(pb[CTRL].astype(np.int32))], 255)
    ctrl = (ctrl > 0) & ~mk
    ratio = float(diff[mk].mean() / max(diff[ctrl].mean(), 1e-6))
    sd_b, sd_a = float(gb[mk].std()), float(ga_n[mk].std())
    # 골 그늘 깊이(2026-09-28 7차 — 연서님 기준 "코 옆 그늘이 실제로 옅어지나"): 부위 안에서 주변(큰 흐림)보다 어두운 양의 평균.
    #   foldlift 와 같은 자(중간 흐림 − 큰 흐림의 음수 부분)다. 표준편차는 입술·수염까지 섞여 무뎠다.
    def _shade(g):
        w = g.shape[1]; ks = max(3, int(w * 0.012) | 1); kl = max(ks + 2, int(w * 0.12) | 1)
        d = cv2.GaussianBlur(g, (ks, ks), 0) - cv2.GaussianBlur(g, (kl, kl), 0)
        return float(-np.minimum(d, 0)[mk].mean())
    sh_b, sh_a = _shade(gb), _shade(ga_n)
    crop = lambda im: Image.fromarray(im[y0:y1, x0:x1])  # noqa: E731
    heat = np.clip(diff / 40.0 * 255, 0, 255).astype(np.uint8)
    heat = cv2.applyColorMap(heat, cv2.COLORMAP_INFERNO)[:, :, ::-1]
    out = {"item": d.name + ("@pass1" if pass1 else ""), "when": (m.get("afters") or [{}])[-1].get("when"),
           "in_out": round(ratio, 2), "fold_sd_before": round(sd_b, 1), "fold_sd_after": round(sd_a, 1),
           "fold_sd_change_pct": round((sd_a - sd_b) / sd_b * 100, 1),
           "shade_before": round(sh_b, 2), "shade_after": round(sh_a, 2), "shade_change_pct": round((sh_a - sh_b) / sh_b * 100, 1),
           "sim": round(float((m.get("identity") or {}).get("similarity") or 0), 3)}
    # 골 선 선명도(9차, bna.foldlift.edge_ratio — 사진마다 자기 얼굴 점, 볼 맨살 대비) 전→후
    from bna.foldlift import edge_ratio
    eb, ea = edge_ratio(bi), edge_ratio(ai)
    if eb and ea:
        out.update(edge_before=round(eb, 3), edge_after=round(ea, 3), edge_change_pct=round((ea - eb) / eb * 100, 1))
    return out, [crop(B), crop(Aw), crop(np.ascontiguousarray(heat))]


def main():
    a = sys.argv[1:]
    oi = a.index("--out")
    out_png = Path(a[oi + 1])
    a = a[:oi] + a[oi + 2:]
    bid = a[0]
    items = [x for x in a[1:] if not x.startswith("--")]
    labels = {x.split("=")[0]: x.split("=")[1] for x in items if "=" in x}
    items = [x.split("=")[0] for x in items]
    rows, res = [], []
    for it in items:
        r = one(ROOT / "outputs" / bid / it.split("@")[0], it.endswith("@pass1"))
        if r is None:
            res.append({"item": it, "error": "얼굴 점 못 찾음"}); continue
        o, ims = r; o["label"] = labels.get(it, ""); res.append(o); rows.append((o, ims))
    H = 330
    font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 22)
    fsm = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 18)
    sc = [[im.resize((int(im.width * H / im.height), H)) for im in ims] for _o, ims in rows]
    W = max(sum(i.width for i in s) for s in sc) + 40
    head = 40
    canvas = Image.new("RGB", (W, head + len(rows) * (H + 64)), "white")
    dr = ImageDraw.Draw(canvas)
    dr.text((12, 8), "팔자 부위 확대 — 전 | 후(전에 맞춰 정렬) | 바뀐 곳(밝을수록 많이)", fill="black", font=font)
    y = head
    for (o, _ims), s in zip(rows, sc):
        dr.text((12, y + 4), f"{o['item']} · {o['when']} · {o['label']}   골 선 {o.get('edge_change_pct', 0):+}% · 골 그늘 {o['shade_change_pct']:+}% · 부위 쏠림 {o['in_out']}배 · 닮음 {o['sim']}",
                fill="black", font=fsm)
        x = 12
        for im in s:
            canvas.paste(im, (x, y + 34)); x += im.width + 6
        y += H + 64
    canvas.save(out_png)
    out_png.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in res:
        print(r)


if __name__ == "__main__":
    main()
