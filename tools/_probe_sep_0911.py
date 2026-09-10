"""[Q2 근거] ArcFace 가 우리 생성 얼굴을 '다른 사람'과 갈라내는가.
   같은 쌍(before_i vs after_i) 분포 vs 서로 다른 인물(before_i vs before_j) 분포를 실측한다.
   비용 0 (로컬 CPU, 생성 호출 없음)."""
import json, itertools, sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, "src")
from bna.qa import identity as I
OUT = Path("outputs")
items = []
for m in sorted(OUT.glob("*/*/meta.json")):
    d = json.loads(m.read_text(encoding="utf-8"))
    dr = m.parent
    b = next(iter(sorted(dr.glob("*_before.jpg"))), None)
    a = next(iter(sorted(dr.glob("*_after.jpg"))), None)
    if b and a:
        v = d.get("variation") or {}
        items.append({"k": f'{d.get("batch_id")}/{d.get("item_id")}', "b": b, "a": a,
                      "framing": (v.get("framing") or {}).get("key"),
                      "gate": (d.get("identity") or {}).get("gate")})
print("이미지 있는 item:", len(items), flush=True)
emb = {}
for i, it in enumerate(items):
    for side in ("b", "a"):
        e = I.embed(Image.open(it[side]))
        emb[(it["k"], side)] = e
    print(f"  {i+1}/{len(items)} {it['k']} b={'o' if emb[(it['k'],'b')] is not None else 'x'} a={'o' if emb[(it['k'],'a')] is not None else 'x'}", flush=True)
np.save("outputs/_emb_0911.npy", np.array([1]))
same, diff = [], []
for it in items:
    eb, ea = emb[(it["k"], "b")], emb[(it["k"], "a")]
    if eb is not None and ea is not None:
        same.append((float(np.dot(eb, ea)), it["k"], it["framing"]))
ks = [it["k"] for it in items if emb[(it["k"], "b")] is not None]
for x, y in itertools.combinations(ks, 2):
    diff.append(float(np.dot(emb[(x, "b")], emb[(y, "b")])))
L = []
ss = sorted(s[0] for s in same); dd = sorted(diff)


def pct(a, p):
    return a[min(len(a) - 1, int(len(a) * p))] if a else float("nan")


L.append(f"같은 쌍(before↔after) n={len(ss)}  최소 {ss[0]:.3f} p10 {pct(ss,0.1):.3f} 중앙 {pct(ss,0.5):.3f} 최대 {ss[-1]:.3f}")
L.append(f"다른 인물(before↔다른 before) n={len(dd)}  최소 {dd[0]:.3f} 중앙 {pct(dd,0.5):.3f} p95 {pct(dd,0.95):.3f} p99 {pct(dd,0.99):.3f} 최대 {dd[-1]:.3f}")
L.append("")
L.append("겹침 구간 판정")
for t in (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60):
    fn = sum(1 for x in ss if x < t); fp = sum(1 for x in dd if x >= t)
    L.append(f"  문턱 {t:.2f} → 같은 쌍을 죽임 {fn}/{len(ss)} ({fn/len(ss)*100:.0f}%) · 다른 인물을 통과 {fp}/{len(dd)} ({fp/len(dd)*100:.2f}%)")
L.append("")
L.append("같은 쌍 하위 10건 (프레이밍 포함)")
for s, k, f in sorted(same)[:10]:
    L.append(f"  {s:.3f}  {k}  {f}")
Path("outputs/_probe_sep_0911.txt").write_text("\n".join(L), encoding="utf-8")
json.dump({"same": [[s, k, f] for s, k, f in same], "diff": dd}, open("outputs/_probe_sep_0911.json", "w"), indent=0)
print("done")
