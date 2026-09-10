"""프레이밍 가중을 바꿨을 때 '못 잼(n/a)' 이 얼마나 될지 미리 본다 (생성 호출 0).

추첨을 수천 번 돌려 프레이밍 분포를 재고, 거기에 **프레이밍별 실측 못 잼률**을 곱한다.
저울추를 바꿔 가며 저울이 어디서 멈추는지 먼저 보는 것 — 돈을 쓰기 전에 방향을 고른다.

⚠ 실측률의 표본이 작다(프레이밍당 4~11장). 이 값은 '예상'이지 '보장'이 아니다.
   그래서 목표를 딱 10% 에 맞추지 말고 여유를 둬라. 실측은 다음 배치들에서 저절로 쌓인다
   (검증 전용 배치는 안 뽑는다 — 2026-09-10 성연서님 결정).
⚠ 실측률은 손으로 적지 말고 원장에서 뽑아라(--from-ledger, 기본값). 굳은 숫자는 낡는다.
"""
import argparse, json, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, "src")
try:
    sys.stdout.reconfigure(encoding="utf-8")            # 이 PC 콘솔은 CP949 — 한글 출력이 죽는다
except Exception:                                       # noqa: BLE001
    pass
from bna.planner import plan_batch
from bna.spec import load


def measured_rates(out_dir: Path) -> dict:
    """프레이밍별 실측 못 잼률. demo(시뮬 자리표시) 회차는 뺀다 — 늘 ok 라 비율을 낮춰 보이게 한다."""
    n, na = Counter(), Counter()
    for m in sorted(out_dir.glob("*/*/meta.json")):
        try:
            d = json.loads(m.read_text(encoding="utf-8"))
        except Exception:                               # noqa: BLE001
            continue
        if d.get("demo"):
            continue
        f = ((d.get("variation") or {}).get("framing") or {}).get("key")
        if not f:
            continue
        n[f] += 1
        if (d.get("identity") or {}).get("gate") == "n/a":
            na[f] += 1
    return {f: {"n": c, "na": na[f], "rate": na[f] / c} for f, c in n.items()}


def forecast(rates: dict, samples: int, seed: int) -> list:
    out = []
    for t in load("treatments.yaml"):
        plans = plan_batch("selfie", samples, seed=seed, treatment=t)
        dist = Counter(p["framing"]["key"] if isinstance(p["framing"], dict) else p["framing"] for p in plans)
        tot = sum(dist.values()) or 1
        # 실측이 없는 프레이밍은 0 이 아니라 **모름**이다 — 0 으로 접으면 안 재 본 컷이 안전해 보인다.
        unknown = sum(c for f, c in dist.items() if f not in rates)
        exp = sum(c * rates[f]["rate"] for f, c in dist.items() if f in rates) / tot
        out.append({"treatment": t, "expected_na": round(exp, 3),
                    "unknown_share": round(unknown / tot, 3),
                    "dist": {f: round(c / tot, 3) for f, c in dist.most_common()}})
    out.sort(key=lambda r: -r["expected_na"])
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--samples", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    r = measured_rates(Path(a.out))
    print("[실측 못 잼률] (demo 제외)")
    for f, x in sorted(r.items(), key=lambda kv: -kv[1]["rate"]):
        print(f"  {f:14s} {x['na']:2d}/{x['n']:2d} = {x['rate']*100:5.1f}%")
    print()
    print(f"[예상 못 잼] 추첨 {a.samples}회 × 시술별")
    for row in forecast(r, a.samples, a.seed):
        flag = "OVER " if row["expected_na"] >= 0.10 else "ok   "
        print(f"  {flag}{row['treatment']:20s} {row['expected_na']*100:5.1f}%   {row['dist']}")
