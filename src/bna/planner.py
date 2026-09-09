"""배치 플래너: N개의 변주 조합을 축별로 균등 배분 (균형 샘플링) + 인물 조합 중복 금지.

⚠ 중복 금지는 **배치 안에서만** 걸려 있었다(2026-09-09 실측). 러너 기본 seed 가 5 로 고정이라
   같은 시술을 두 번 돌리면 인물 명단이 통째로 같았고, 실제로 09-09 nasolabial 두 배치의
   0000·0002 가 인물 11축 전부 동일 → 얼굴 유사도 0.421·0.392 로 전체 평균(0.099)의 4배였다.
   그래서 과거 배치의 인물 조합을 파일로 남기고(person_registry.jsonl) 다음 배치가 그걸 피한다.
   조합이 말라 n 을 못 채우면 **배치가 조용히 줄지 않게** 배치 안 중복 금지만 남기고 채운다(fail-open).
"""
import json, random, time
from collections import Counter
from pathlib import Path
from .spec import ROOT, load, PERSON_AXES, SCENE_AXES, treatment_rules, allowed_values

REGISTRY = ROOT / "outputs" / "person_registry.jsonl"


# 배분 큐의 기본 배수. 학습 가중(0~1)을 곱해도 1 밑으로 안 떨어지게 해 준다 —
# 정수 복제라 배수가 1이면 0.25 를 곱한 순간 그 값이 통째로 사라진다(회피가 아니라 삭제가 된다).
WEIGHT_SCALE = 4


def signature(plan: dict) -> tuple:
    """인물 축 11개의 값 조합 = 이 사람이 누구인가. 장면(배경·조명)은 사람이 아니라 상황이라 뺀다."""
    return tuple(plan[a]["key"] if isinstance(plan[a], dict) else plan[a] for a in PERSON_AXES)


def past_signatures(path: Path = REGISTRY) -> set:
    """지난 배치들이 이미 쓴 인물 조합. 읽기 실패는 빈 집합으로 넘긴다(생성이 멈추면 안 된다)."""
    out = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.add(tuple(json.loads(line)["sig"]))
    except (OSError, ValueError, KeyError):
        return out
    return out


def remember(plans: list, batch_id: str, path: Path = REGISTRY) -> None:
    """이번 배치가 쓴 조합을 남긴다. 실패해도 배치는 그대로 진행한다(fail-open)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for p in plans:
                f.write(json.dumps({"sig": list(signature(p)), "batch": batch_id,
                                    "at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
    except OSError:
        pass


def plan_batch(mode: str, n: int, seed=None, fixed=None, avoid_weights=None, treatment=None,
               avoid_sigs=None) -> list:
    """축마다 옵션을 섞은 순환 큐에서 뽑아 n개 안에 모든 옵션이 최대한 고르게 등장하도록 한다.

    avoid_weights: {축: {값: 0~1}} — 제외가 몰린 조건값을 **덜** 뽑는다(lessons.active).
    아예 빼지 않는 이유 = 그 조건이 나쁜 게 아니라 지금 모델이 약한 것이고, 빼 버리면
    나중에 좋아졌는지 확인할 길이 사라진다. 그래서 최소 1 은 남긴다.

    avoid_sigs: 과거 배치가 이미 쓴 인물 조합(past_signatures()). 1차에서 이걸 피해 뽑고,
    n 을 못 채우면 2차에서 배치 안 중복 금지만 남긴다 — 배치가 말없이 줄어드는 게 더 나쁘다.
    """
    rng = random.Random(seed)
    v = load("variations.yaml")
    tr = treatment_rules(treatment, mode)
    weights = v.get("weights", {})
    avoid_weights = avoid_weights or {}
    fixed = fixed or {}
    tw = tr.get("age_weights") or {}                     # 시술별 나이 가중 (0 은 allowed_values 가 뺀다)

    queues = {}
    def draw(axis, opts):
        """허용 목록(opts) 안에서 순환 큐로 뽑는다 — 축별로 고르게, 가중치만큼 더 자주."""
        opts = [fixed[axis]] if axis in fixed else opts
        q = queues.setdefault(axis, [])
        for o in q:                     # 큐에 남은 것 중 허용되는 첫 항목
            if o in opts:
                q.remove(o); return o
        w = weights.get(axis, {}); aw = avoid_weights.get(axis, {})
        def reps(o):                    # 기본 가중 × 시술 가중 × 학습 회피 가중, 최소 1
            base = float(w.get(o, 1)) * (float(tw.get(o, 1.0)) if axis == "age" else 1.0)
            return max(1, round(WEIGHT_SCALE * base * float(aw.get(o, 1.0))))
        pool = [o for o in opts for _ in range(reps(o))]            # 가중치만큼 복제 후 섞기
        rng.shuffle(pool)
        queues[axis] = pool
        return queues[axis].pop(0)

    past = set(avoid_sigs or ())
    plans, seen = [], set()
    for strict in (True, False):          # 1차: 과거 배치와도 안 겹치게 / 2차: 조합이 말랐을 때만
        if len(plans) >= n:
            break
        tries = 0
        while len(plans) < n and tries < n * 20:
            tries += 1
            p = {}
            for axis in PERSON_AXES:
                p[axis] = draw(axis, allowed_values(axis, p, mode, v, tr))
            sig = tuple(p[a] for a in PERSON_AXES)
            if sig in seen or (strict and sig in past):
                continue
            seen.add(sig)
            for axis in SCENE_AXES:
                p[axis] = draw(axis, allowed_values(axis, p, mode, v, tr))
            plans.append({a: {"key": k, "text": v[a][k]} for a, k in p.items()})
    return plans


def distribution(plans: list, axes=None) -> dict:
    axes = axes or PERSON_AXES + SCENE_AXES
    return {a: dict(Counter(p[a]["key"] for p in plans)) for a in axes}
