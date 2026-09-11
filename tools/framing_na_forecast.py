"""프레이밍 가중을 바꿨을 때 '못 잼(n/a)' 이 얼마나 될지 미리 본다 (생성 호출 0).

추첨을 수천 번 돌려 프레이밍 분포를 재고, 거기에 **프레이밍별 실측 못 잼률**을 곱한다.
저울추를 바꿔 가며 저울이 어디서 멈추는지 먼저 보는 것 — 돈을 쓰기 전에 방향을 고른다.

⚠ 실측률의 표본이 작다(프레이밍당 4~11장). 이 값은 '예상'이지 '보장'이 아니다.
   그래서 목표를 딱 10% 에 맞추지 말고 여유를 둬라. 실측은 다음 배치들에서 저절로 쌓인다
   (검증 전용 배치는 안 뽑는다 — 2026-09-10 성연서님 결정).
⚠ 실측률은 늘 원장(outputs/*/*/meta.json)에서 다시 읽는다 — 코드에 굳은 숫자를 두지 않는다.
   (selftest ⑱ 의 _NA18 만 예외다. 회귀는 결정적이어야 하므로 그때 잰 값을 박아 두고,
    값을 갱신할 때 근거(장수)를 같이 적는다.)

--compare : 버전별 **예상 vs 실측**. '예상 8.1% 였는데 실제로 몇 %였나'를 사람 기억이 아니라
            원장에서 낸다. 예상은 지금 설정이 아니라 **그 버전의 설정**(git show)으로 다시 재므로
            "그때 그 설정이 맞았나"가 성립한다.
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


def _yaml_at(sha: str, rel: str):
    """그 커밋 시점의 설정 파일. 없으면 None(옛 커밋에 없던 파일·sha 를 못 찾는 경우)."""
    import subprocess, yaml
    try:
        txt = subprocess.check_output(["git", "show", f"{sha}:config/{rel}"], text=True,
                                      encoding="utf-8", stderr=subprocess.DEVNULL, timeout=10)
    except Exception:                                   # noqa: BLE001
        return None
    return yaml.safe_load(txt)


def expected_at(sha: str, treatment: str, rates: dict, samples: int, seed: int):
    """그 버전의 설정으로 추첨했을 때의 예상 못 잼. 지금 설정이 아니라 **그때 설정**으로 재야
    '예상이 맞았나'가 성립한다 — 지금 값과 대면 늘 맞거나 늘 틀린다."""
    import bna.planner as P
    from bna import spec
    va, tr = _yaml_at(sha, "variations.yaml"), _yaml_at(sha, "treatments.yaml")
    if va is None or tr is None:
        return None
    real = spec.load

    def fake(name):
        return va if name == "variations.yaml" else (tr if name == "treatments.yaml" else real(name))
    spec.load, P.load = fake, fake
    try:
        if treatment not in tr:
            return None
        d = Counter(p["framing"]["key"] if isinstance(p["framing"], dict) else p["framing"]
                    for p in P.plan_batch("selfie", samples, seed=seed, treatment=treatment))
    except Exception:                                   # noqa: BLE001
        return None
    finally:
        spec.load, P.load = real, real
    tot = sum(d.values()) or 1
    return sum(c * rates[f]["rate"] for f, c in d.items() if f in rates) / tot


def compare(out_dir: Path, rates: dict, samples: int, seed: int) -> list:
    """버전별 **예상 vs 실측** 못 잼. 배치가 돌면 이 한 줄이 곧 답이다 —
    '예상 8.1% 였는데 실제로 몇 %였나'를 사람 기억이 아니라 원장에서 낸다."""
    from bna import lessons
    rows = []
    for r in lessons.by_version(out_dir):
        if not r.get("real") or not r.get("n"):
            continue
        # 그 버전이 실제로 뽑은 시술 구성 그대로 예상을 낸다(시술마다 예상이 다르다)
        sha = r["version"].split("-")[0]
        tot = sum((r.get("treatments") or {}).values()) or 1
        parts, miss = 0.0, 0
        for t, c in (r.get("treatments") or {}).items():
            e = expected_at(sha, t, rates, samples, seed)
            if e is None:
                miss += c
            else:
                parts += e * c
        exp = (parts / (tot - miss)) if tot - miss else None
        rows.append({"version": r["version"], "alias": r.get("alias"), "name": r.get("note"),
                     "n": r["n"], "actual": r.get("id_na_rate"), "expected": exp,
                     "first": r.get("first") or 0, "unknown_share": round(miss / tot, 3)})
    # 버전 문자열로 정렬하면 git 해시 순이라 아무 뜻이 없다 — 처음 쓴 순서(v1→v2…)가 사람이 읽는 순서다
    rows.sort(key=lambda x: x["first"])
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--samples", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--compare", action="store_true", help="버전별 예상 vs 실측 못 잼")
    a = ap.parse_args()
    r = measured_rates(Path(a.out))
    print("[실측 못 잼률] (demo 제외)")
    for f, x in sorted(r.items(), key=lambda kv: -kv[1]["rate"]):
        print(f"  {f:14s} {x['na']:2d}/{x['n']:2d} = {x['rate']*100:5.1f}%")
    print()
    if a.compare:
        from bna.version import prompt_version
        cur = prompt_version()
        print("[예상 vs 실측 못 잼] 버전별 (사진이 있는 버전만)")
        _rows = compare(Path(a.out), r, a.samples, a.seed)
        for row in _rows:
            e = "  (설정 못 읽음)" if row["expected"] is None else f"{row['expected']*100:5.1f}%"
            ac = "  (없음)" if row["actual"] is None else f"{row['actual']*100:5.1f}%"
            gap = "" if (row["expected"] is None or row["actual"] is None) \
                else f"  차이 {abs(row['actual'] - row['expected'])*100:4.1f}%p"
            mark = " <- 지금 설정" if row["version"] == cur else ""
            print(f"  {str(row['alias'] or '?'):4s} n={row['n']:3d}  예상 {e}  실측 {ac}{gap}{mark}  {row['name'] or ''}")
        # ⚠ 한 배치가 8장이면 사진 한 장이 12.5%p 다 — 한 회차의 차이로 '예상이 틀렸다'를 판정하지 마라.
        _g = [abs(x["actual"] - x["expected"]) for x in _rows
              if x["actual"] is not None and x["expected"] is not None]
        if _g:
            print(f"\n  참고: 지난 버전들의 예상↔실측 차이 중앙값 {sorted(_g)[len(_g)//2]*100:.1f}%p "
                  f"(최대 {max(_g)*100:.1f}%p, n={len(_g)}) — 배치가 8장이라 한 회차만으로는 못 가린다.")
        # ⚠ 지금 설정으로 뽑은 사진이 아직 없으면 비교할 줄 자체가 없다 — 그걸 침묵으로 두지 않는다.
        if not any(x["version"] == cur for x in _rows):
            print("")
            print(f"  ⚠ 지금 설정({cur})으로 뽑은 사진이 아직 없다 — 다음 실배치가 돌면 이 표에 줄이 생긴다.")
            print("     ⚠ prompt_version 은 git 커밋 + 설정 해시라 **커밋만 해도 바뀐다**.")
            print("        버전 이름표는 배치를 돌린 뒤에 붙여라(먼저 붙이면 아무 배치도 안 가리키는 유령이 된다).")
    else:
        print(f"[예상 못 잼] 추첨 {a.samples}회 × 시술별")
        for row in forecast(r, a.samples, a.seed):
            flag = "OVER " if row["expected_na"] >= 0.10 else "ok   "
            print(f"  {flag}{row['treatment']:20s} {row['expected_na']*100:5.1f}%   {row['dist']}")
