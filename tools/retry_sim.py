"""재시도 정책·합격선을 바꾸면 비용이 얼마나 주는지 - 실측 부트스트랩 시뮬레이션.

왜 시뮬인가. 정책을 바꾼 효과를 실제로 재려면 유료 회차를 다시 돌려야 한다($27). 그 전에
"돈이 얼마나 줄 것 같은가"를 우리 실측 위에서 먼저 계산한다.

무엇을 표본으로 쓰나. 2026-09-08~09 유료 회차 27세트의 **최종 시도** 결과다(각 세트의 마지막
시도만 meta.json 에 남는다). 한 번의 생성 시도가 어떻게 끝나는지를 이 27개에서 복원추출한다.

[주의] 그런데 최종 시도는 **모든 시도의 공정한 표본이 아니다.** 통과한 세트는 통과한 시도 1개만 남기고,
   탈락한 세트도 마지막 1개만 남는다 - 실제 69시도 중 42개(전부 탈락)가 덮여 사라졌다.
   그래서 이 27개를 그냥 뽑으면 통과율이 37% 로 나오는데, 진짜 시도당 통과율은 10/69 = 14.5% 다.
   (첫 판에 이걸 안 보정해 현행 통과율이 75% 로 나왔다 - 실측 37% 의 두 배다.)
   → 탈락 시도에 가중치 (69-10)/17 = 3.47 을 준다. 즉 **탈락 표본이 사라진 42개를 대신 든다.**
   가정: 안 남은 42개의 탈락이 남은 17개와 같은 분포다. 확인할 길이 없어 가정으로 적어 둔다.

이 가정이 왜 타당한가. 실측이 "시도당 통과 14.5% → 3회 누적 예상 37.5%"를 냈고 실제가 37.0%였다.
예상과 실제가 소수점까지 맞았다 = 세 번의 시도가 서로 독립이었다는 뜻이라, 시도 하나를
독립 추첨으로 모형화하는 게 맞다.

그리고 이 파일은 **현행 정책을 실측으로 재현하지 못하면 아무 숫자도 내지 않고 죽는다**(--check).
보정이 틀린 시뮬은 틀린 걸 말해 주지 않고 그럴듯한 숫자를 주기 때문이다.

[주의] 재추첨(②)의 이득은 여기서 구조적으로 안 잡힌다 - 시도를 독립 추첨으로 두면 다시 뽑아도 확률이 같다.
   즉 아래 숫자는 ②를 뺀 **하한**이고, ②의 이득은 실회차로만 잰다.

사용: python tools/retry_sim.py [--trials 20000]
"""
import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
# config/pricing.yaml 의 호출당 단가(추정치, 미실측 - tools/usage_report.py 가 실단가를 잰다)
GEN, QA = 0.19, 0.01
# 재시도 정책은 **파이프라인의 것을 그대로 가져다 쓴다**(리터럴 복붙 금지 - 두 벌이 되면
# 시뮬이 실제와 다른 정책을 재고, 그걸 알려 주는 것이 아무것도 없다).
sys.path.insert(0, str(ROOT / "src"))
from bna.batch import _retry_plan, MAX_ATTEMPTS   # noqa: E402


# 정책을 바꾼 날. 이 날 이후 회차는 **다른 규칙으로 돈 것**이라 같은 모수에 섞으면 안 된다 -
# 2026-09-10 실측: 새 8세트를 같이 넣었더니 '현행' 재현이 43.0% 로 뜨고 실측 51.4% 와 8.4%p 어긋나
# 보정 게이트가 숫자를 안 내고 죽었다(그게 맞는 동작이다). 정책 비교의 모수는 바꾸기 **전** 회차다.
POLICY_CHANGE = "20260910"


def load_attempts(until=POLICY_CHANGE):
    """정책 변경 **전** 유료 회차의 최종 시도 결과 + 실제 시도·통과 수(가중치 보정에 쓴다)."""
    rows = []
    attempts = passes = 0
    for d in sorted(OUT.iterdir()):
        if not d.is_dir():
            continue
        if until and d.name[:8] >= until:
            continue                                    # 새 정책으로 돈 회차는 이 모수에 안 섞는다
        for it in sorted(d.iterdir()):
            f = it / "meta.json"
            if not f.exists():
                continue
            m = json.loads(f.read_text(encoding="utf-8"))
            if m.get("demo") or (m.get("providers") or {}).get("gen") != "openai":
                continue
            sc = {}
            for k, v in ((m.get("vision") or {}).get("scores") or {}).items():
                x = v.get("score") if isinstance(v, dict) else v
                if isinstance(x, (int, float)):
                    sc[k] = x
            # 비전까지 갔나 = structure/identity 를 통과했나. 안 갔으면 그 회차엔 검수 비용이 없다.
            reached = bool(m.get("vision"))
            hard = [f for f in (m.get("fail_reasons") or []) if str(f).split("@")[0] in ("structure", "identity")]
            # 사람 판정(있으면). **기계 통과는 산출물이 아니다** - 최종 관문은 사람이라,
            # 진짜 단가는 "사람이 채택한 사진 1장당"이다. 2026-09-10 실측: 기계 통과 10건 중 4건을 사람이 되돌렸다.
            rv = it / "review.json"
            pick = None
            if rv.exists():
                try:
                    pick = json.loads(rv.read_text(encoding="utf-8")).get("pick")
                except Exception:
                    pick = None
            sim = (m.get("identity") or {}).get("similarity")
            rows.append({"scores": sc, "reached": reached, "hard": [str(f).split("@")[0] for f in hard],
                         "passed": bool(m.get("passed")), "pick": pick,
                         # 0.45~0.60 = 기계가 통과시키던 '사람 확인 구간'
                         "id_review": isinstance(sim, (int, float)) and 0.45 <= sim < 0.60})
            attempts += int(m.get("attempt") or 1)
            passes += bool(m.get("passed"))
    return rows, {"attempts": attempts, "passes": passes, "sets": len(rows)}


def weighted_pool(rows, real):
    """덮여 사라진 탈락 시도를 남은 탈락 표본이 대신 들도록 가중치를 준다.
    통과 표본 1 : 탈락 표본 (전체탈락시도 / 남은탈락표본). 반환은 (표본, 누적가중치)."""
    fails = [r for r in rows if not r["passed"]]
    lost = real["attempts"] - real["passes"]          # 전체 탈락 시도 수
    w_fail = (lost / len(fails)) if fails else 1.0
    pool, cum, acc = [], [], 0.0
    for r in rows:
        acc += 1.0 if r["passed"] else w_fail
        pool.append(r); cum.append(acc)
    return pool, cum, w_fail


def draw(pool, cum, rng):
    x = rng.random() * cum[-1]
    lo, hi = 0, len(cum) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cum[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return pool[lo]


def judge(a, cuts, default_cut, id_review=False):
    """이 시도가 통과했나 + 탈락 사유. 컷을 바꿔 다시 매긴다.
    id_review: 닮음 '사람 확인 구간'(0.45~0.60)을 재시도 사유로 볼지 (2026-09-10 성연서님 승인 ②)."""
    if not a["reached"]:
        return False, a["hard"] or ["structure"]
    if id_review and a.get("id_review"):
        return False, ["identity_review"]
    # 여기 오면 structure/identity 는 이미 통과했다(batch.py 가 통과했을 때만 비전을 부른다).
    # 그래서 남은 판정은 비전 점수뿐이다.
    fails = [f"vision:{k}" for k, v in a["scores"].items() if v < cuts.get(k, default_cut)]
    return (not fails), fails


def run_set(pool, cum, rng, cuts, default_cut, reuse_before, smart_retry, id_review=False):
    """세트 하나를 정책대로 끝까지 굴린다 → (통과?, 비용)."""
    cost = 0.0
    prev = []
    last_pick = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        redraw, need_before = _retry_plan(prev)
        if attempt == 1 or not reuse_before:
            redo_before = True                                  # 종전 정책: 늘 Before 부터
        else:
            # ②(조건 재추첨)를 끄면 조건 탈락도 Before 를 물려받는다 - 그 차이를 재려고 갈라 둔다
            redo_before = need_before if smart_retry else (need_before and not redraw)
        if redo_before:
            cost += GEN                                         # Before 생성
        cost += GEN                                             # After 생성
        a = draw(pool, cum, rng)
        if a["reached"]:
            cost += QA                                          # 비전 검수는 structure/identity 통과분만
        ok, fails = judge(a, cuts, default_cut, id_review)
        # 검수 화면엔 **기계 탈락작도 올라간다** - 2026-09-10 실측에서 사람이 채택한 10건 중 4건이
        # 기계가 버린 것이었다. 그래서 사람이 보는 건 늘 '마지막 시도의 사진'이다.
        # 기계 통과 여부로 채택 후보를 좁히면 실측($2.68)이 재현되지 않는다.
        if ok:
            return True, cost, a["pick"]
        prev = fails
        last_pick = a["pick"]
    return False, cost, last_pick


def sim(pool, cum, trials, seed, **kw):
    rng = random.Random(seed)
    n_pass = n_adopt = n_known = 0
    total = 0.0
    for _ in range(trials):
        ok, c, pick = run_set(pool, cum, rng, **kw)
        n_pass += ok
        total += c
        if pick is not None:
            n_known += 1
            n_adopt += (pick == "pick")
    return {"pass_rate": n_pass / trials, "cost_per_set": total / trials,
            "cost_per_pass": (total / n_pass) if n_pass else None,
            # 사람 채택 1장당 = 세트당비용 / (통과율 x 통과작의 사람 채택률)
            # 사람 채택률 = 세트 하나가 최종적으로 채택될 확률(기계 통과 여부와 무관)
            "adopt_rate": (n_adopt / n_known) if n_known else None,
            "cost_per_adopt": (total / trials) / (n_adopt / n_known) if (n_known and n_adopt) else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--until", default=POLICY_CHANGE,
                    help="이 날짜(YYYYMMDD) 앞의 회차만 모수로 쓴다. 정책이 섞이면 보정이 깨진다")
    a = ap.parse_args()
    rows, real = load_attempts(a.until)
    if not rows:
        print("표본 없음 - 유료 회차 meta.json 이 있어야 한다('0원'이 아니라 '못 잼').")
        return 2
    pool, cum, w_fail = weighted_pool(rows, real)

    # ── 보정 검사: 현행 정책을 실측으로 재현 못 하면 아무 숫자도 내지 않는다 ──
    # 틀린 시뮬은 "틀렸다"고 말해 주지 않고 그럴듯한 숫자를 준다. 그래서 여기서 세운다.
    base_kw = dict(cuts={}, default_cut=7, reuse_before=False, smart_retry=False)
    chk = sim(pool, cum, max(a.trials, 20000), a.seed, **base_kw)
    real_rate = real["passes"] / real["sets"]
    gap = abs(chk["pass_rate"] - real_rate)
    print(f"[보정] 현행 재현 {chk['pass_rate']*100:.1f}% vs 실측 {real_rate*100:.1f}% (모수: {a.until} 이전 회차) "
          f"(표본 {real['sets']}세트 / {real['attempts']}시도, 탈락 가중 x{w_fail:.2f})")
    if gap > 0.05:
        print(f"보정 실패 - 차이 {gap*100:.1f}%p. 이 표본으로는 정책 비교를 낼 수 없다.")
        return 3

    cases = [
        ("현행 (컷 7 · 같은 조건 3회 · Before 매번)", dict(cuts={}, default_cut=7, reuse_before=False, smart_retry=False)),
        ("① Before 재사용만", dict(cuts={}, default_cut=7, reuse_before=True, smart_retry=False)),
        ("②' 조건탈락도 Before 재사용 안 함", dict(cuts={}, default_cut=7, reuse_before=True, smart_retry=True)),
        ("③ 합격선만 6 (재시도는 종전)", dict(cuts={"effect_visible": 6}, default_cut=7, reuse_before=False, smart_retry=False)),
        ("①+③ 같이", dict(cuts={"effect_visible": 6}, default_cut=7, reuse_before=True, smart_retry=False)),
        ("①+②+③ (0910 오전 정책)", dict(cuts={"effect_visible": 6}, default_cut=7, reuse_before=True, smart_retry=True)),
        ("+ 닮음 확인구간도 재시도 (지금)", dict(cuts={"effect_visible": 6}, default_cut=7, reuse_before=True, smart_retry=True, id_review=True)),
    ]
    out = []
    for name, kw in cases:
        r = sim(pool, cum, a.trials, a.seed, **kw)
        out.append({"case": name, **r})
    base = out[0]
    for r in out:
        r["save_pct"] = None if not r["cost_per_adopt"] else (1 - r["cost_per_adopt"] / base["cost_per_adopt"]) * 100

    if a.json:
        print(json.dumps({"pool": len(rows), "trials": a.trials, "calib": chk["pass_rate"], "real": real_rate, "rows": out}, ensure_ascii=False, indent=1))
        return 0
    print(f"표본 {len(pool)}시도 · 시행 {a.trials:,}회 · 단가 생성 ${GEN}/장 (추정치)\n")
    print(f"{'정책':44} {'기계통과':>8} {'세트당$':>8} {'기계1장$':>9} {'사람채택':>8} {'사람1장$':>9} {'절감':>6}")
    for r in out:
        cp = f"{r['cost_per_pass']:.2f}" if r["cost_per_pass"] else "-"
        ca = f"{r['cost_per_adopt']:.2f}" if r["cost_per_adopt"] else "-"
        ar = f"{r['adopt_rate']*100:.0f}%" if r["adopt_rate"] else "-"
        sv = f"{r['save_pct']:.0f}%" if r["save_pct"] else "-"
        print(f"{r['case']:44} {r['pass_rate']*100:>7.1f}% {r['cost_per_set']:>8.2f} {cp:>9} {ar:>8} {ca:>9} {sv:>6}")
    print("\n[주의] ②(조건 재추첨)의 이득은 이 모형에서 구조적으로 안 잡힌다 - 시도를 독립 추첨으로 두기 때문이다.")
    print("       따라서 위 절감은 하한이고, ②의 실제 효과는 유료 회차로만 잰다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
