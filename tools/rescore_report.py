"""재채점 원장 → 컷 후보 표 (2026-09-21).

재는 것은 딱 둘이다.
  ① **정확도(precision)** — 이 컷에 걸린 것 중 사람도 버린 비율. 09-14 교훈("임계는 걸린 것 중
     사람이 reject 했던 비율로 고른다")이 정본이다. 여기가 낮으면 기계가 좋은 사진을 죽인다.
  ② **회수율(recall)** — 사람이 'AI 티'로 버린 것 중 이 컷이 잡아낸 비율. 지금 `ai_look` 은 0% 다.
둘은 반대로 움직이므로 한 축만 보고 컷을 정하지 마라 — 표를 둘 다 내고 고른다.

⚠ 분모를 '사람 탈락 전부'로 쓰지 마라. 손가락·효과 없음으로 버린 장은 이 문항이 잡을 대상이 아니다
  (잡으면 오히려 이 문항이 무엇을 재는지 흐려진다). 회수율 분모는 **'AI 티' 태그가 달린 장**이고,
  정확도 분모는 '이 컷에 걸린 장 전부'다 — 축이 다르니 같은 표에 이름을 박는다.
"""
import json, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LED = ROOT / "outputs" / "rescore"
AITI = "AI 티"


def load(model, variant="v1"):
    p = LED / (f"phone_real-{model}.jsonl" if variant == "v1" else f"phone_real-{model}-{variant}.jsonl")
    if not p.exists():
        return {}
    rows = {}
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("error"):
            continue
        rows[r["key"]] = r                      # 나중 줄이 이긴다(다시 잰 값)
    return rows


def sweep(rows, field, cuts, label):
    print(f"\n── {label} (n={len(rows)}) ──")
    print(f"{'컷':>4} {'걸림':>5} {'정확도(걸린 것 중 사람도 버림)':>30} {'AI티 회수율':>22} {'채택 오살':>12}")
    vals = [r for r in rows.values() if r.get(field) is not None]
    aiti_n = sum(1 for r in vals if AITI in (r.get("tags") or []))
    picks = [r for r in vals if r.get("pick") == "pick"]
    for c in cuts:
        hit = [r for r in vals if r[field] < c]
        if not hit:
            print(f"{c:>4} {0:>5}   —(걸린 게 없다)")
            continue
        also = sum(1 for r in hit if r.get("pick") == "reject")
        rec = sum(1 for r in hit if AITI in (r.get("tags") or []))
        killed = sum(1 for r in hit if r.get("pick") == "pick")
        print(f"{c:>4} {len(hit):>5} {also}/{len(hit)} = {also/len(hit)*100:>5.1f}%{'':>13}"
              f" {rec}/{aiti_n} = {(rec/aiti_n*100 if aiti_n else 0):>5.1f}%{'':>6}"
              f" {killed}/{len(picks)} = {(killed/len(picks)*100 if picks else 0):>5.1f}%")


def dist(rows, field, label):
    c = Counter(r.get(field) for r in rows.values() if r.get(field) is not None)
    by = {}
    for r in rows.values():
        v = r.get(field)
        if v is None:
            continue
        k = "AI티탈락" if AITI in (r.get("tags") or []) else ("채택" if r.get("pick") == "pick" else "기타탈락")
        by.setdefault(v, Counter())[k] += 1
    print(f"\n── {label} 점수 분포 ──")
    for v in sorted(c):
        b = by[v]
        print(f"  {v:>4} : {c[v]:>3}장  (AI티탈락 {b['AI티탈락']} · 채택 {b['채택']} · 기타탈락 {b['기타탈락']})")


def main(variant="v1", only_passed=True):
    g, m = load("gpt", variant), load("gemini", variant)
    if only_passed:
        # 기본 모수 = **기계가 통과시킨 컷**. 기계가 이미 떨어뜨린 컷은 사람에게 갈 일이 없어서,
        # 거기까지 분모에 넣으면 "이 문항을 넣으면 무엇이 달라지나"가 흐려진다.
        g = {k: v for k, v in g.items() if v.get("passed") is True}
        m = {k: v for k, v in m.items() if v.get("passed") is True}
    print(f"[문항 판 {variant}] 모수 = " + ("기계 통과분만" if only_passed else "사람이 판정한 전부"))
    if not g and not m:
        print("원장이 없다 — 먼저 `python tools/rescore_phone_real.py --model gpt` 를 돌려라.")
        return
    for name, rows in (("GPT", g), ("Gemini", m)):
        if not rows:
            print(f"\n[{name}] 원장 없음 — 아직 안 돌렸다.")
            continue
        print(f"\n{'='*78}\n[{name}] {rows[next(iter(rows))].get('vendor_model')}  {len(rows)}장")
        print("사람 판정:", Counter(r.get("pick") for r in rows.values()),
              "| AI티 태그", sum(1 for r in rows.values() if AITI in (r.get("tags") or [])))
        print("티 개수 분포:", dict(sorted(Counter(len(r.get("tells") or []) for r in rows.values()).items())))
        # 티를 '한 쌍 티'와 '한 장 티'로 갈라 다시 센다 — 재호출 0(원장에 where 를 받아 뒀다).
        # 사람이 남긴 'AI 티' 메모 6건이 전부 한 쌍 얘기였으므로, 갈라서 재는 게 이 문항의 핵심 가설이다.
        for r in rows.values():
            tl = r.get("tells") or []
            pair = [t for t in tl if (t.get("where") or "") in ("pair", "both")]
            r["score_pair"] = max(0.0, 10.0 - 2 * len(pair))
            r["score_obvious"] = max(0.0, 10.0 - 2 * sum(1 for t in tl if t.get("strength") == "obvious"))
        dist(rows, "ai_look", "옛 ai_look (모델이 준 0~10)")
        dist(rows, "score_flat2", "새 phone_real — 티 하나당 -2 (코드 산출)")
        sweep(rows, "ai_look", [7, 8, 9, 10], "옛 ai_look 컷 후보")
        sweep(rows, "score_flat2", [4, 6, 8, 10], "새 phone_real(flat2) 컷 후보")
        sweep(rows, "score_weight", [4, 6, 8, 10], "새 phone_real(obvious -2 · subtle -1) 컷 후보")
        sweep(rows, "score_pair", [6, 8, 10], "한 쌍 티만 -2 (where=pair/both)")
        sweep(rows, "score_obvious", [6, 8, 10], "obvious 티만 -2")
        sweep(rows, "model_score", [7, 8, 9, 10], "대조군 — 모델이 스스로 매긴 0~10")
        # 짚은 티가 무엇이었나 — 문항 문구를 다듬는 근거다
        parts = Counter()
        for r in rows.values():
            for t in r.get("tells") or []:
                parts[(t.get("part") or "?")[:24]] += 1
        print("\n── 많이 짚힌 자리 ──")
        for k, v in parts.most_common(12):
            print(f"  {k:<26} {v}")
    if g and m:
        both = sorted(set(g) & set(m))
        print(f"\n{'='*78}\n[두 모델 대조] 공통 {len(both)}장")
        agree = sum(1 for k in both if (g[k]["score_flat2"] < 8) == (m[k]["score_flat2"] < 8))
        print(f"  컷 8 에서 같은 판정: {agree}/{len(both)} = {agree/len(both)*100:.1f}%" if both else "")
        gt = sum(len(g[k]["tells"]) for k in both)
        mt = sum(len(m[k]["tells"]) for k in both)
        print(f"  짚은 티 총수: GPT {gt} · Gemini {mt}")
        # 사람이 AI티로 버린 장에서 누가 더 잡나 — 이게 고르는 기준이다
        tgt = [k for k in both if AITI in (g[k].get("tags") or [])]
        if tgt:
            print(f"  사람이 AI티로 버린 {len(tgt)}장 중 컷 8 에 걸린 수: "
                  f"GPT {sum(1 for k in tgt if g[k]['score_flat2'] < 8)} · "
                  f"Gemini {sum(1 for k in tgt if m[k]['score_flat2'] < 8)}")
        pk = [k for k in both if g[k].get("pick") == "pick"]
        if pk:
            print(f"  사람이 채택한 {len(pk)}장 중 컷 8 에 걸린 수(오살): "
                  f"GPT {sum(1 for k in pk if g[k]['score_flat2'] < 8)} · "
                  f"Gemini {sum(1 for k in pk if m[k]['score_flat2'] < 8)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="v1")
    ap.add_argument("--all", action="store_true", help="기계 탈락분까지 분모에 넣는다")
    a = ap.parse_args()
    main(a.variant, not a.all)
