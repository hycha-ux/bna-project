"""표정 완화 2차 비교 실행기 (2026-09-21 연서님 확인 · 빌디 요청).

  python tools/run_exp_expr_2w.py --dry     # 돈 0 — 두 묶음의 계획(시점·강도·표정 변경)만 뽑아 비교 가능한지 본다
  python tools/run_exp_expr_2w.py           # 실행(세션 밖에서 띄워라 — 40~60분)

규칙 (1차의 실패 두 개를 막는다 — teemo/LESSONS.md 09-21):
  · 두 묶음 공통: 단발 시점 2주(BNA_EXP_WHEN) · Before 강도 moderate · 나이 40대
  · 대조: 표정 잠금 유지 / 실험: BNA_EXP_RELAX=expression (켠 축은 주사위도 건너뛴다)
  · **셈에 넣는 장** = 기계 통과 ∧ (실험이면 After 표정이 실제로 바뀐 장). 모자라면 모자란 수만큼 다시 뽑는다.
  · 묶음당 누적 $5 에서 멈춘다(재충전 배치의 상한 = 5 − 이미 쓴 돈). 모자란 채 멈추면 그 사실을 보고에 적는다.
  · 두 묶음은 **순차** 실행 — 이미지 한도 분당 8장이라 나란히 돌리면 429.
끝나면 teemo 의 표 굽기 → 스레드 게시까지 한다(아무도 다시 멘션하지 않으므로).
"""
import json, os, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEEMO = Path(r"C:\Users\medib\teemo")
OUT = ROOT / "outputs"
STATE = TEEMO / "out" / "exp-expr-2w-0921.json"
LOG = TEEMO / "out" / "exp-expr-2w-0921.log"
THREAD = "1789954469.842639"
CAP = 5.0
NEED = 2
COMMON = {"BNA_EXP_SEVERITY": "moderate", "BNA_EXP_WHEN": "2w"}
ARMS = [("대조", {}), ("실험", {"BNA_EXP_RELAX": "expression"})]
ID_RE = re.compile(r"(\d{8}-\d{6}-[0-9a-f]{4})")   # 한글 글자로 찾지 마라(09-21 1차 보고기 사고)


def L(m):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {m}\n")


def load_keys():
    for line in (TEEMO / "keys.env").read_text(encoding="utf-8").splitlines():
        k, _, v = line.strip().partition("=")
        if k in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def items_of(batch):
    rows = []
    for mp in sorted((OUT / batch).glob("*/meta.json")):
        m = json.loads(mp.read_text(encoding="utf-8"))
        rows.append({"passed": m.get("passed") is True, "cost": m.get("cost") or 0.0,
                     "expr_changed": "expression" in (m.get("after_changed_axes") or []),
                     "when": [a["when"] for a in (m.get("afters") or [])][-1:]})
    return rows


def counts(arm, batches):
    rows = [r for b in batches for r in items_of(b)]
    ok = [r for r in rows if r["passed"] and (arm == "대조" or r["expr_changed"])]
    return len(ok), round(sum(r["cost"] for r in rows), 3)


def run_batch(env, n, cap):
    e = {**os.environ, **COMMON, **env, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    for k in ("BNA_EXP_RELAX",):
        if k not in env:
            e.pop(k, None)
    p = subprocess.run([sys.executable, "tools/run_paid.py", "--treatment", "nasolabial", "--mode", "selfie",
                        "--count", str(n), "--fix", "age=40s", "--cost-cap", f"{cap:.2f}"],
                       cwd=ROOT, env=e, capture_output=True)
    out = p.stdout.decode("utf-8", "replace")
    m = ID_RE.search(out)
    L(f"run_paid exit={p.returncode} n={n} cap={cap:.2f} batch={m.group(1) if m else None}")
    if not m:
        L("stdout 앞부분: " + out[:400].replace("\n", " | "))
        L("stderr 끝부분: " + p.stderr.decode("utf-8", "replace")[-400:].replace("\n", " | "))
    return m.group(1) if m else None


def dry():
    sys.path.insert(0, str(ROOT / "src"))
    from bna.spec import build_prompts
    from bna.planner import plan_batch
    for arm, env in ARMS:
        for k in ("BNA_EXP_RELAX", "BNA_EXP_SEVERITY", "BNA_EXP_WHEN"):
            os.environ.pop(k, None)
        os.environ.update({**COMMON, **env})
        plans = plan_batch("selfie", NEED, 4242, {"age": "40s"}, treatment="nasolabial")
        for i, v in enumerate(plans):
            r = build_prompts("nasolabial", "selfie", v, 4242 + i)
            a = r["after_variation"]["expression"]["key"]
            print(f"[dry] {arm} {i}: 시점 {r['afters'][-1]['when']} · 강도 {r['variation']['before_severity']['key']} · "
                  f"나이 {v['age']['key']} · 표정 {v['expression']['key']}→{a} · 바뀐 축 {r['after_changed_axes']} · exp={r['experiment']}")
    for k in ("BNA_EXP_RELAX", "BNA_EXP_SEVERITY", "BNA_EXP_WHEN"):
        os.environ.pop(k, None)


def main():
    if "--dry" in sys.argv:
        dry(); return
    load_keys()
    state = {"arms": {}, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    for arm, env in ARMS:
        batches = []
        while True:
            have, spent = counts(arm, batches)
            left = round(CAP - spent, 2)
            if have >= NEED:
                break
            if left < 0.6:                                   # 한 세트 최소 비용(~$0.58) 미만이면 못 뽑는다
                L(f"{arm}: 상한 도달 — 셈 {have}/{NEED} · ${spent}"); break
            b = run_batch(env, NEED - have, left)
            if not b:
                L(f"{arm}: 배치 ID 를 못 읽었다 — 중단"); break
            batches.append(b)
            state["arms"][arm] = {"batches": batches}
            STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        have, spent = counts(arm, batches)
        state["arms"][arm] = {"batches": batches, "counted": have, "spent": spent}
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        L(f"{arm} 끝: 배치 {batches} · 셈 {have}/{NEED} · ${spent}")
    state["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    # 보고 — teemo 쪽 스크립트가 표를 굽고 게시한다(게시 도구·토큰은 teemo 에만 있다)
    r = subprocess.run(["node", str(TEEMO / "tools" / "post-exp-expr-2w-0921.mjs")], cwd=TEEMO, capture_output=True)
    L(f"게시 exit={r.returncode} {r.stdout.decode('utf-8','replace')[-200:]} {r.stderr.decode('utf-8','replace')[-300:]}")


if __name__ == "__main__":
    main()
