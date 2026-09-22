"""직후 컷 전용 항목(immediate_look) 재채점 — 사람이 판정한 지난 직후 컷으로 컷을 잡는다 (2026-09-22 연서님).

  python tools/rescore_immediate.py [--limit N] [--dry]

- 모수: outputs/*/*/ 중 review.json(사람 판정)이 있고 afters 에 immediate 가 있는 세트.
- 그림: 폴더에 사람(파일 접두)이 여럿이면(재시도) 가장 최근 Before 묶음 = 최종 컷. Before ↔ 직후 After 한 쌍.
- 채점: 운영 경로와 같은 공급자(providers.yaml selfie/clinical qa) · 문항은 qa_checklist.yaml items_immediate 한 벌.
  ⚠ 운영에선 다른 항목과 한 콜로 묻는다 — 여기선 이 항목만 묻는다(점수 분포가 조금 다를 수 있다).
- 결과: outputs/rescore/immediate_look.jsonl (한 줄 = 한 세트, 이미 잰 세트는 건너뛴다 = 재실행 안전).
"""
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bna.spec import load  # noqa: E402
from bna import providers  # noqa: E402

A = sys.argv[1:]
# --out 파일명: 문구를 고칠 때마다 새 파일로 잰다(v1 = immediate_look.jsonl, 09-22 v2 = immediate_look_v2.jsonl).
OUT = ROOT / "outputs" / "rescore" / (A[A.index("--out") + 1] if "--out" in A else "immediate_look.jsonl")
LIMIT = int(A[A.index("--limit") + 1]) if "--limit" in A else None
DRY = "--dry" in A


def sets():
    for mp in sorted((ROOT / "outputs").glob("*/*/meta.json")):
        rv = mp.parent / "review.json"
        if not rv.exists():
            continue
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
            r = json.loads(rv.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "immediate" not in [a.get("when") for a in (m.get("afters") or [])]:
            continue
        bs = sorted(mp.parent.glob("*_before.jpg"), key=lambda p: p.stat().st_mtime)
        if not bs:
            continue
        b = bs[-1]
        pre = b.name[: -len("_before.jpg")]
        a = mp.parent / f"{pre}_after_immediate.jpg"
        if not a.exists():
            a = mp.parent / f"{pre}_after.jpg"
        if not a.exists():
            continue
        yield mp.parent, m, r, b, a


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if OUT.exists():
        done = {json.loads(l)["set"] for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()}
    items = load("qa_checklist.yaml")["items_immediate"]
    pv = load("providers.yaml")
    todo = [s for s in sets() if f"{s[0].parent.name}/{s[0].name}" not in done]
    if LIMIT:
        todo = todo[:LIMIT]
    print(f"대상 {len(todo)}세트 (이미 잰 {len(done)})")
    if DRY:
        for d, m, r, b, a in todo:
            print(d.parent.name, d.name, b.name, a.name, r.get("pick"))
        return
    for d, m, r, b, a in todo:
        mode = m.get("mode") or "selfie"
        name = ((pv.get("default_provider") or {}).get(mode) or {}).get("qa", "openai")
        p = providers.get(name)
        t0 = time.time()
        try:
            raw = p.qa(b.read_bytes(), a.read_bytes(), items, mode)
        except Exception as e:
            print("실패", d, e)
            continue
        s = (raw.get("immediate_look") or {})
        row = {"set": f"{d.parent.name}/{d.name}", "mode": mode, "treatment": m.get("treatment"),
               "whens": [x.get("when") for x in m.get("afters") or []], "pick": r.get("pick"), "tags": r.get("tags"),
               "note": r.get("note"), "score": s.get("score"), "why": s.get("note"), "provider": name,
               "before": b.name, "after": a.name, "sec": round(time.time() - t0, 1)}
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(row["set"], row["pick"], row["score"])


if __name__ == "__main__":
    main()
