"""배치 플래너: N개의 변주 조합을 축별로 균등 배분 (균형 샘플링) + 인물 조합 중복 금지."""
import random
from collections import Counter
from .spec import load, PERSON_AXES, SCENE_AXES


def plan_batch(mode: str, n: int, seed=None, fixed=None) -> list:
    """축마다 옵션을 섞은 순환 큐에서 뽑아 n개 안에 모든 옵션이 최대한 고르게 등장하도록 한다."""
    rng = random.Random(seed)
    v = load("variations.yaml")
    rules = v.get("mode_rules", {}).get(mode, {})
    compat, excl = v.get("background_lighting", {}), v.get("gender_exclusions", {})
    weights = v.get("weights", {})
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
        w = weights.get(axis, {})
        pool = [o for o in opts for _ in range(int(w.get(o, 1)))]   # 가중치만큼 복제 후 섞기
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
