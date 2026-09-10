"""③ 동일인 게이트 실측 프로브 (조회 전용·비용 0)."""
import json, sys
from collections import Counter, defaultdict
from pathlib import Path
OUT = Path("outputs")


def _sc(v):
    """비전 점수 칸은 회차마다 숫자였다가 {score,note} 객체였다가 한다."""
    if isinstance(v, dict):
        return v.get("score")
    return v


rows = []
for m in sorted(OUT.glob("*/*/meta.json")):
    d = json.loads(m.read_text(encoding="utf-8"))
    v = d.get("variation") or {}
    rows.append({
        "batch": d.get("batch_id"), "item": d.get("item_id"),
        "treatment": d.get("treatment"), "mode": d.get("mode"),
        "framing": (v.get("framing") or {}).get("key"),
        "angle": (v.get("angle") or {}).get("key"),
        "gate": (d.get("identity") or {}).get("gate"),
        "sim": (d.get("identity") or {}).get("similarity"),
        "mp": (d.get("structure") or {}).get("face_detected"),
        "vid": _sc(((d.get("vision") or {}).get("scores") or {}).get("identity")),
        "passed": d.get("passed"),
        "fail": d.get("fail_reasons") or [],
    })
print("총 item:", len(rows))
print("gate 분포:", dict(Counter(r["gate"] for r in rows)))
na = [r for r in rows if r["gate"] == "n/a"]
print("n/a:", len(na), f"({len(na)/len(rows)*100:.1f}%)")
print("\n[Q1] n/a 건에서 MediaPipe(structure) 검출 여부:", dict(Counter(r["mp"] for r in na)))
print("      n/a 건 vision identity 점수 분포:", dict(Counter(r["vid"] for r in na)))
print("      전체에서 MediaPipe 검출:", dict(Counter(r["mp"] for r in rows)))
print("\n[Q3] framing x gate")
tab = defaultdict(Counter)
for r in rows:
    tab[r["framing"]][r["gate"]] += 1
for f, c in sorted(tab.items(), key=lambda kv: -(kv[1]["n/a"]/max(sum(kv[1].values()),1))):
    n = sum(c.values())
    print(f'  {str(f):16s} n={n:3d}  n/a={c["n/a"]:2d} ({c["n/a"]/n*100:4.0f}%)  ok={c["ok"]:2d} review={c["review"]:2d} fail={c["fail"]:2d}')
print("\n[Q2] 측정된 similarity 분포")
sims = sorted([r["sim"] for r in rows if r["sim"] is not None])
print("  측정 건수:", len(sims))
if sims:
    print("  최소 %.3f / 중앙 %.3f / 최대 %.3f" % (sims[0], sims[len(sims)//2], sims[-1]))
    print("  구간: <0.45 %d / 0.45~0.60 %d / >=0.60 %d" % (
        sum(1 for s in sims if s < 0.45), sum(1 for s in sims if 0.45 <= s < 0.60), sum(1 for s in sims if s >= 0.60)))
json.dump(rows, open("outputs/_probe_gate_0911.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
