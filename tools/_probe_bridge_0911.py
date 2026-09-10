"""[Q1 실측] 못 잼(n/a) 구제 — MediaPipe 5점으로 정렬해 ArcFace 인식 모델에 직접 먹인다.
   insightface 의 '검출기'가 못 잡는 것이지 '인식 모델'이 못 재는 게 아니다.
   검출기만 우회하면 되는지 실측한다. 비용 0(로컬 CPU)."""
import json, sys, itertools
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, "src")
from bna.qa import identity as I, landmarks as L
from insightface.utils import face_align

OUT = Path("outputs")


def five(img):
    pts = L.detect(img)
    if pts is None:
        return None
    k = L.key_points(pts)
    return np.array([k["eye_l"], k["eye_r"], k["nose"], k["mouth_l"], k["mouth_r"]], dtype=np.float32)


def bridge_embed(img):
    """MediaPipe 5점 → norm_crop(112) → ArcFace 인식 모델."""
    app = I._model()
    if app is None:
        return None
    kps = five(img)
    if kps is None:
        return None
    bgr = np.asarray(img.convert("RGB"))[:, :, ::-1]
    aimg = face_align.norm_crop(bgr, landmark=kps, image_size=112)
    rec = app.models.get("recognition")
    if rec is None:
        return None
    e = rec.get_feat(aimg).flatten()
    return e / np.linalg.norm(e)


items = []
for m in sorted(OUT.glob("*/*/meta.json")):
    if "-sim/" in m.as_posix():
        continue
    d = json.loads(m.read_text(encoding="utf-8"))
    dr = m.parent
    b = next(iter(sorted(dr.glob("*_before.jpg"))), None)
    a = next(iter(sorted(dr.glob("*_after.jpg"))), None)
    if not (b and a):
        continue
    v = d.get("variation") or {}
    items.append({"k": f'{d.get("batch_id")}/{d.get("item_id")}', "b": b, "a": a,
                  "framing": (v.get("framing") or {}).get("key"),
                  "gate": (d.get("identity") or {}).get("gate"),
                  "sim": (d.get("identity") or {}).get("similarity")})
print("대상 item:", len(items), flush=True)
E = {}
for i, it in enumerate(items):
    for s in ("b", "a"):
        img = Image.open(it[s])
        E[(it["k"], s, "arc")] = I.embed(img)
        E[(it["k"], s, "br")] = bridge_embed(img)
    print(f"  {i+1}/{len(items)}", flush=True)


def sim(k, kind):
    x, y = E[(k, "b", kind)], E[(k, "a", kind)]
    return None if (x is None or y is None) else float(np.dot(x, y))


L2 = []
na = [it for it in items if it["gate"] == "n/a"]
res = [(it["k"], it["framing"], sim(it["k"], "br")) for it in na]
got = [r for r in res if r[2] is not None]
L2.append(f"[구제] 종전 n/a {len(na)}건 중 다리(MediaPipe 5점→ArcFace)로 재진 것: {len(got)}건")
for k, f, s in sorted(res, key=lambda r: (r[2] is None, -(r[2] or 0))):
    L2.append(f"   {('못 잼' if s is None else f'{s:.3f}')}  {f:14s} {k}")
L2.append("")
# 다리 축의 같은쌍 vs 다른인물 분포 (전 item)
ss = sorted(x for x in (sim(it["k"], "br") for it in items) if x is not None)
ks = [it["k"] for it in items if E[(it["k"], "b", "br")] is not None]
dd = sorted(float(np.dot(E[(x, "b", "br")], E[(y, "b", "br")])) for x, y in itertools.combinations(ks, 2))


def pct(a, p):
    return a[min(len(a) - 1, int(len(a) * p))] if a else float("nan")


L2.append(f"[다리 축 분포] 같은 쌍 n={len(ss)} 최소 {ss[0]:.3f} p10 {pct(ss,.1):.3f} 중앙 {pct(ss,.5):.3f}")
L2.append(f"               다른 인물 n={len(dd)} 중앙 {pct(dd,.5):.3f} p99 {pct(dd,.99):.3f} 최대 {dd[-1]:.3f}")
for t in (0.30, 0.35, 0.40, 0.45, 0.50, 0.60):
    fn = sum(1 for x in ss if x < t); fp = sum(1 for x in dd if x >= t)
    L2.append(f"   문턱 {t:.2f} → 같은 쌍 죽임 {fn}/{len(ss)} ({fn/len(ss)*100:.0f}%) · 다른 인물 통과 {fp}/{len(dd)} ({fp/len(dd)*100:.2f}%)")
L2.append("")
# 원래 잡히던 것들에서 두 축이 같은 값을 주는가 (다리가 기존 축을 대체해도 되는지)
both = [(sim(it["k"], "arc"), sim(it["k"], "br")) for it in items
        if sim(it["k"], "arc") is not None and sim(it["k"], "br") is not None]
if both:
    d = [abs(a - b) for a, b in both]
    L2.append(f"[두 축 일치] 둘 다 잰 {len(both)}건 차이 평균 {sum(d)/len(d):.3f} 최대 {max(d):.3f}")
Path("outputs/_probe_bridge_0911.txt").write_text("\n".join(L2), encoding="utf-8")
print("done")
