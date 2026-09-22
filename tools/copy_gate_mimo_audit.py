"""미모 컷 '너무 같음'(copy) 자 점검 — 사람 판정과 수치(닮음·고개·기울기)를 대 본다 (2026-09-22 연서님).

  python tools/copy_gate_mimo_audit.py

- 모수: outputs/*/*/ 중 review.json(사람 판정)이 있고, 복붙 자 규칙이 미모용(`head`, copy_gate: head)인 After.
- 한 줄 = 최종 After 한 장(시점별). 수치는 meta.after_results[시점] (없으면 meta 최상위 structure/identity).
- 결과: outputs/rescore/copy_gate_mimo.json (원장 읽기만, API 호출 0).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "rescore" / "copy_gate_mimo.json"


def rows():
    for mp in sorted((ROOT / "outputs").glob("*/*/meta.json")):
        rv = mp.parent / "review.json"
        if not rv.exists():
            continue
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
            r = json.loads(rv.read_text(encoding="utf-8"))
        except Exception:
            continue
        ar = m.get("after_results") or {}
        if not ar:
            ar = {"_": {"structure": m.get("structure"), "identity": m.get("identity"),
                        "fail_reasons": m.get("fail_reasons")}}
        for when, x in ar.items():
            c = ((x.get("structure") or {}).get("copy") or {})
            # 미모 = 복붙 자가 미모 규칙(head) 이거나, 인물 looks 가 attractive(v36 이전 미모 회차 — 옛 자 expr_and_head)
            mimo = ((m.get("variation") or {}).get("looks") or {}).get("key") == "attractive"
            if not (str(c.get("rule", "")).startswith("head") or mimo):
                continue
            idn = x.get("identity") or {}
            yield {"set": f"{mp.parent.parent.name}/{mp.parent.name}", "when": when,
                   "ver": m.get("prompt_version"), "pick": r.get("pick"), "tags": r.get("tags"),
                   "note": r.get("note"), "set_passed": m.get("passed"),
                   "fails": x.get("fail_reasons") or [], "copy_passed": c.get("passed"),
                   "head": c.get("head_diff"), "roll": c.get("roll_diff"), "expr": c.get("expr_diff"),
                   "sim": None if idn.get("similarity") is None else round(idn["similarity"], 3),
                   "rule": c.get("rule")}


def remeasure(r):
    """옛 회차(기울기 미기록)까지 같은 자로 — 최종 사진을 다시 재서 지금 미모 규칙(head+roll 10°) 판정을 붙인다."""
    from PIL import Image
    from bna.qa import landmarks as L, structure
    d = ROOT / "outputs" / r["set"]
    bs = sorted(d.glob("*_before.jpg"), key=lambda p: p.stat().st_mtime)
    if not bs:
        return
    pre = bs[-1].name[: -len("_before.jpg")]
    a = d / f"{pre}_after_{r['when']}.jpg"
    if not a.exists():
        a = d / f"{pre}_after.jpg"
    if not a.exists():
        return
    pb, pa = L.detect(Image.open(bs[-1])), L.detect(Image.open(a))
    c = structure.copy_check(pb, pa, "selfie", head_only=True, roll_deg=10)
    r.update({"re_head": c.get("head_diff"), "re_roll": c.get("roll_diff"), "re_expr": c.get("expr_diff"),
              "re_copy_passed": c.get("passed"), "after_file": a.name})


def main():
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    rs = list(rows())
    for r in rs:
        remeasure(r)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rs)}장 → {OUT}")


if __name__ == "__main__":
    main()
