"""배치 플래너: N개의 변주 조합을 축별로 균등 배분 (균형 샘플링) + 인물 조합 중복 금지."""
import random
from collections import Counter
from .spec import load, PERSON_AXES, SCENE_AXES


# 배분 큐의 기본 배수. 학습 가중(0~1)을 곱해도 1 밑으로 안 떨어지게 해 준다 —
# 정수 복제라 배수가 1이면 0.25 를 곱한 순간 그 값이 통째로 사라진다(회피가 아니라 삭제가 된다).
WEIGHT_SCALE = 4


def plan_batch(mode: str, n: int, seed=None, fixed=None, avoid_weights=None) -> list:
    """축마다 옵션을 섞은 순환 큐에서 뽑아 n개 안에 모든 옵션이 최대한 고르게 등장하도록 한다.

    avoid_weights: {축: {값: 0~1}} — 제외가 몰린 조건값을 **덜** 뽑는다(lessons.active).
    아예 빼지 않는 이유 = 그 조건이 나쁜 게 아니라 지금 모델이 약한 것이고, 빼 버리면
    나중에 좋아졌는지 확인할 길이 사라진다. 그래서 최소 1 은 남긴다.
    """
    rng = random.Random(seed)
    v = load("variations.yaml")
    rules = v.get("mode_rules", {}).get(mode, {})
    compat, excl = v.get("background_lighting", {}), v.get("gender_exclusions", {})
    weights = v.get("weights", {})
    avoid_weights = avoid_weights or {}
    fixed = fixed or {}

    def allowed(axis):
        return [rules.get(axis)] and [k for k in (rules.get(axis) or list(v[axis]))] or list(v[axis])

    queues = {}
    def draw(axis, filt=None):
        opts = [fixed[axis]] if axis in fixed else allowed(axis)
        if filt:
            opts = [o for o in opts if filt(o)] or opts
        q = queues.setdefault(axis, [])
        for o in q:                     # 큐에 남은 것 중 허용되는 첫 항목
            if o in opts:
                q.remove(o); return o
        w = weights.get(axis, {}); aw = avoid_weights.get(axis, {})
        def reps(o):                    # 기본 가중 × 학습 회피 가중, 최소 1
            return max(1, round(WEIGHT_SCALE * int(w.get(o, 1)) * float(aw.get(o, 1.0))))
        pool = [o for o in opts for _ in range(reps(o))]            # 가중치만큼 복제 후 섞기
        rng.shuffle(pool)
        queues[axis] = pool
        return queues[axis].pop(0)

    plans, seen = [], set()
    tries = 0
    while len(plans) < n and tries < n * 20:
        tries += 1
        p = {}
        for axis in PERSON_AXES:
            banned = excl.get(p.get("gender"), {}).get(axis, []) if "gender" in p else []
            p[axis] = draw(axis, lambda o: o not in banned)
        sig = tuple(p[a] for a in PERSON_AXES)
        if sig in seen:
            continue
        seen.add(sig)
        for axis in SCENE_AXES:
            if axis == "lighting" and p["background"] in compat:
                p[axis] = draw(axis, lambda o: o in compat[p["background"]])
            else:
                p[axis] = draw(axis)
        plans.append({a: {"key": k, "text": v[a][k]} for a, k in p.items()})
    return plans


def distribution(plans: list, axes=None) -> dict:
    axes = axes or PERSON_AXES + SCENE_AXES
    return {a: dict(Counter(p[a]["key"] for p in plans)) for a in axes}
