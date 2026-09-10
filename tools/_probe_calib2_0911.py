"""[Q2] 채택(=사람이 동일인으로 인정) 축으로 다시. 조회 전용."""
import json, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, "src")
from bna import lessons
OUT = Path("outputs")
metas = {}
for m in sorted(OUT.glob("*/*/meta.json")):
    d = json.loads(m.read_text(encoding="utf-8"))
    metas[f'{d.get("batch_id")}/{d.get("item_id")}'] = d
last = {}
for r in lessons.read(OUT):
    last[f'{r.get("batch")}/{r.get("item")}'] = r
L = []


def sim(k):
    return ((metas.get(k) or {}).get("identity") or {}).get("similarity")


def gate(k):
    return ((metas.get(k) or {}).get("identity") or {}).get("gate")


pick = [k for k, r in last.items() if r.get("pick") == "pick"]
rej = [(k, r) for k, r in last.items() if r.get("pick") == "reject"]
idrej = [(k, r) for k, r in rej if "동일 인물 아님" in (r.get("tags") or [])]
oth = [(k, r) for k, r in rej if "동일 인물 아님" not in (r.get("tags") or [])]
L.append(f"채택 {len(pick)} / 제외 {len(rej)} (그중 '동일 인물 아님' {len(idrej)})")
L.append("")
ps = sorted(x for x in (sim(k) for k in pick) if x is not None)
L.append(f"[A] 채택된 쌍 = 사람이 '같은 사람'이라 한 것: {len(pick)}건 중 재진 것 {len(ps)}건")
L.append(f"    값: {[round(x,3) for x in ps]}")
if ps:
    L.append(f"    최저 {ps[0]:.3f}  ← '같은 사람 최저'")
    L.append(f"    0.60 미만: {sum(1 for x in ps if x<0.60)}건 / 0.45 미만: {sum(1 for x in ps if x<0.45)}건")
L.append(f"    채택인데 못 잼(n/a): {sum(1 for k in pick if sim(k) is None)}건")
L.append("")
L.append(f"[B] '동일 인물 아님'으로 뺀 쌍: {len(idrej)}건")
for k, r in idrej:
    s = sim(k)
    L.append(f"    {k}  sim={'못 잼' if s is None else round(s,3)}  gate={gate(k)}  note={(r.get('note') or '')[:50]}")
L.append("")
os_ = sorted(x for x in (sim(k) for k, _ in oth) if x is not None)
L.append(f"[C] 다른 사유로 뺀 쌍(동일인은 문제 없다고 본 것): 재진 것 {len(os_)}건")
L.append(f"    최저 {os_[0]:.3f} / 최대 {os_[-1]:.3f} / 0.60 미만 {sum(1 for x in os_ if x<0.60)}건" if os_ else "    없음")
L.append("")
L.append("[D] 게이트 판정 vs 사람 판정 교차 (검수 완료 46건)")
tab = Counter()
for k, r in last.items():
    if r.get("pick") in ("pick", "reject"):
        lab = "동일인아님" if "동일 인물 아님" in (r.get("tags") or []) else r.get("pick")
        tab[(gate(k), lab)] += 1
for (g, p), c in sorted(tab.items(), key=lambda x: str(x[0])):
    L.append(f"    gate={str(g):7s} × 사람={str(p):10s} : {c}")
Path("outputs/_probe_calib2_0911.txt").write_text("\n".join(L), encoding="utf-8")
print("ok")
