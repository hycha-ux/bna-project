"""[Q2] 문턱 재캘리브레이션 표본 실측 (조회 전용)."""
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
judged = [(k, r) for k, r in last.items() if r.get("pick") in ("pick", "reject")]
L.append(f"검수 완료(pick/reject) 쌍: {len(judged)}")
L.append(f"  그중 원장 meta 가 있는 것: {sum(1 for k,_ in judged if k in metas)}")
same, diff, unmeasured = [], [], 0
ident_tags = Counter()
for k, r in judged:
    d = metas.get(k) or {}
    s = (d.get("identity") or {}).get("similarity")
    tags = r.get("tags") or []
    note = r.get("note") or ""
    is_id = any(("닮" in t or "동일" in t or "다른 사람" in t or "identity" in t.lower()) for t in tags) \
            or ("닮" in note or "다른 사람" in note)
    if is_id:
        ident_tags[tuple(tags)] += 1
    if s is None:
        unmeasured += 1
        continue
    (diff if (r.get("pick") == "reject" and is_id) else same).append((s, k, r.get("pick"), tags, note[:40]))
L.append(f"  그중 similarity 가 실제로 재진 것: {len(same)+len(diff)}  / 못 잼: {unmeasured}")
L.append("")
L.append(f"[라벨 A] 사람이 '같은 사람 아니다'로 뺀 것: {len(diff)}건")
for s, k, p, t, n in sorted(diff):
    L.append(f"   {s:.3f}  {k}  {t} {n}")
L.append("")
L.append(f"[라벨 B] 그 외 검수 완료(=사람이 동일인 문제를 제기 안 함): {len(same)}건")
ss = sorted(x[0] for x in same)
if ss:
    L.append(f"   최소 {ss[0]:.3f} / 하위5 {[round(x,3) for x in ss[:5]]} / 중앙 {ss[len(ss)//2]:.3f} / 최대 {ss[-1]:.3f}")
    L.append(f"   0.60 미만(=현재 문턱이 죽이는 쪽): {sum(1 for x in ss if x < 0.60)}건")
    L.append(f"   0.45 미만(=현재 하드페일): {sum(1 for x in ss if x < 0.45)}건")
L.append("")
L.append("[검수 태그 전체 분포]")
tg = Counter()
for _k, r in judged:
    for t in (r.get("tags") or []):
        tg[t] += 1
for t, c in tg.most_common():
    L.append(f"   {t}: {c}")
L.append("")
L.append("[pick/reject 분포] " + str(dict(Counter(r.get("pick") for _k, r in judged))))
Path("outputs/_probe_calib_0911.txt").write_text("\n".join(L), encoding="utf-8")
print("wrote outputs/_probe_calib_0911.txt", len(L), "lines")
