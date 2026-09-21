"""표정 완화 실험 보고 (2026-09-21) — 두 묶음을 채택률·유사도 두 숫자로 나란히.

  python tools/exp_expr_report.py <대조 배치ID> <실험 배치ID> [--json out.json]

유사도 = 동일인 유사도(identity.similarity, 마지막 After 기준 — batch 가 meta 에 싣는 그 값).
채택률 = 사람 검수(review.json) — **검수 전 장은 '미검수'로 따로 센다**(0 으로 세면 채택률이 거짓으로 낮다).
⚠ 2세트씩이다. 한 장이 곧 50%라 이 숫자로 '효과가 있다/없다'를 판정하지 마라 — 방향만 본다.
"""
import argparse, json, statistics, sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "outputs"


def arm(batch):
    rows = []
    for mp in sorted((OUT / batch).glob("*/meta.json")):
        m = json.loads(mp.read_text(encoding="utf-8"))
        rv = mp.parent / "review.json"
        r = json.loads(rv.read_text(encoding="utf-8")) if rv.exists() else None
        idn = m.get("identity") or {}
        rows.append({"item": mp.parent.name, "passed": m.get("passed"), "experiment": m.get("experiment"),
                     "expr_changed": "expression" in (m.get("after_changed_axes") or []),
                     "expr": ((m.get("variation") or {}).get("expression") or {}).get("key"),
                     "expr_after": ((m.get("after_variation") or {}).get("expression") or {}).get("key"),
                     "severity": ((m.get("variation") or {}).get("before_severity") or {}).get("key"),
                     "sim": idn.get("similarity"), "too_similar": idn.get("too_similar"),
                     "copy": ((m.get("structure") or {}).get("copy") or {}).get("passed"),
                     "cost": m.get("cost"), "attempt": m.get("attempt"),
                     "pick": (r or {}).get("pick"), "tags": (r or {}).get("tags") or []})
    return rows


def summary(rows):
    sims = [x["sim"] for x in rows if x["sim"] is not None]
    rev = [x for x in rows if x["pick"] in ("pick", "reject")]
    return {"n": len(rows), "passed": sum(1 for x in rows if x["passed"]),
            "expr_changed": sum(1 for x in rows if x["expr_changed"]),
            "sim_mean": round(statistics.mean(sims), 3) if sims else None,
            "too_similar": sum(1 for x in rows if x["too_similar"] is True),
            "reviewed": len(rev), "picked": sum(1 for x in rev if x["pick"] == "pick"),
            "aiti": sum(1 for x in rev if "AI 티" in x["tags"]),
            "cost": round(sum(x["cost"] or 0 for x in rows), 2)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("control"); ap.add_argument("relax"); ap.add_argument("--json")
    a = ap.parse_args()
    res = {}
    for name, b in (("대조(잠금 유지)", a.control), ("실험(표정 완화)", a.relax)):
        rows = arm(b); s = summary(rows); res[name] = {"batch": b, "summary": s, "rows": rows}
        print(f"\n[{name}] {b}")
        for x in rows:
            print(f"  {x['item']} 통과={x['passed']} 강도={x['severity']} 표정 {x['expr']}→{x['expr_after']} "
                  f"유사도={x['sim'] if x['sim'] is None else round(x['sim'], 3)} 너무같음={x['too_similar']} "
                  f"복붙게이트={x['copy']} 사람={x['pick'] or '미검수'} {x['tags']} ${x['cost']}")
        rv = f"{s['picked']}/{s['reviewed']}" if s["reviewed"] else "미검수"
        print(f"  → 채택 {rv} · 유사도 평균 {s['sim_mean']} · 너무 같음 {s['too_similar']}/{s['n']} · "
              f"표정 바뀜 {s['expr_changed']}/{s['n']} · 기계 통과 {s['passed']}/{s['n']} · ${s['cost']}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
