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


# 구도 = 어떻게 찍혔나. 사람과 따로 센다 — 2026-09-10 성연서님 "전 사진과 동일한 구도"로 들어온 지적.
# ⚠ 인물 서명에 장면 축을 **더하면 안 된다**. 축이 늘수록 조합이 유일해져 겹칠 일이 없어지고,
#   그러면 회피가 강해지는 게 아니라 **약해진다**(같은 사람이 다시 나와도 장면이 다르면 통과).
#   그래서 서명을 둘로 갈라 각각 대조한다.
# 조명·색·화질은 뺐다 — 후보가 적어 금세 다 소진되고, 사람 눈에 '같은 구도'로 읽히는 건 이 셋이다.
SCENE_SIG_AXES = ["framing", "angle", "background"]

# 구도가 '말랐다'고 볼 연속 거절 횟수. 후보 수(프레이밍×각도×배경)보다 넉넉히 크게 잡아
# 운 나쁜 연속 충돌로 일찍 접지 않게 한다.
SCENE_DRY_AFTER = 300


def scene_signature(plan: dict) -> tuple:
    return tuple(plan[a]["key"] if isinstance(plan[a], dict) else plan[a] for a in SCENE_SIG_AXES)


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


def past_scene_signatures(path: Path = REGISTRY) -> set:
    """지난 배치들이 이미 쓴 구도 조합(프레이밍·각도·배경).
    ⚠ 옛 줄에는 `scene` 이 없다 — 없는 줄은 그냥 건너뛴다(그 시절 구도는 모르는 것이지 없는 게 아니다)."""
    out = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            sc = json.loads(line).get("scene")
            if sc:
                out.add(tuple(sc))
    except (OSError, ValueError):
        return out
    return out


def remember(plans: list, batch_id: str, path: Path = REGISTRY) -> None:
    """이번 배치가 쓴 조합을 남긴다. 실패해도 배치는 그대로 진행한다(fail-open)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for p in plans:
                f.write(json.dumps({"sig": list(signature(p)), "scene": list(scene_signature(p)),
                                    "batch": batch_id,
                                    "at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
    except OSError:
        pass


def plan_batch(mode: str, n: int, seed=None, fixed=None, avoid_weights=None, treatment=None,
               avoid_sigs=None, avoid_scene_sigs=None) -> list:
    """축마다 옵션을 섞은 순환 큐에서 뽑아 n개 안에 모든 옵션이 최대한 고르게 등장하도록 한다.

    avoid_weights: {축: {값: 0~1}} — 제외가 몰린 조건값을 **덜** 뽑는다(lessons.active).
    아예 빼지 않는 이유 = 그 조건이 나쁜 게 아니라 지금 모델이 약한 것이고, 빼 버리면
    나중에 좋아졌는지 확인할 길이 사라진다. 그래서 최소 1 은 남긴다.

    avoid_sigs: 과거 배치가 이미 쓴 인물 조합(past_signatures()). 1차에서 이걸 피해 뽑고,
    n 을 못 채우면 2차에서 배치 안 중복 금지만 남긴다 — 배치가 말없이 줄어드는 게 더 나쁘다.

    avoid_scene_sigs: 과거 배치가 이미 쓴 구도 조합(past_scene_signatures()). 인물과 따로 센다 —
    2026-09-10 성연서님 "전 사진과 동일한 구도" 지적. 인물 서명에 장면 축을 더하면 조합이
    유일해져 오히려 회피가 약해진다(그 이유는 scene_signature 주석).
    """
    rng = random.Random(seed)
    v = load("variations.yaml")
    tr = treatment_rules(treatment, mode)
    weights = v.get("weights", {})
    avoid_weights = avoid_weights or {}
    fixed = fixed or {}
    tw = tr.get("age_weights") or {}                     # 시술별 나이 가중 (0 은 allowed_values 가 뺀다)
    fw = tr.get("framing_weights") or {}                 # 시술별 프레이밍 가중 (목주름만 전역과 다르다)

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
            base = float(w.get(o, 1)) * (float(tw.get(o, 1.0)) if axis == "age" else 1.0)                 * (float(fw.get(o, 1.0)) if axis == "framing" else 1.0)
            # ⚠ 최소 1 이라 WEIGHT_SCALE(=4)보다 잘게는 못 나눈다 — 가중 0.25 가 바닥이고
            #   그 아래로 적어도 0.25 로 취급된다. 더 줄여야 하면 framing_allow 에서 빼라.
            return max(1, round(WEIGHT_SCALE * base * float(aw.get(o, 1.0))))
        pool = [o for o in opts for _ in range(reps(o))]            # 가중치만큼 복제 후 섞기
        rng.shuffle(pool)
        queues[axis] = pool
        return queues[axis].pop(0)

    past = set(avoid_sigs or ())
    past_scenes = set(avoid_scene_sigs or ())
    plans, seen, seen_scenes = [], set(), set()
    for strict in (True, False):          # 1차: 과거 배치와도 안 겹치게 / 2차: 조합이 말랐을 때만
        if len(plans) >= n:
            break
        tries = 0
        # 구도 후보는 유한하다(프레이밍×각도×배경). 다 쓰고 나면 그 뒤로는 아무리 뽑아도
        # 전부 거절이라 20n 번을 헛돈다 — n=400 표본에서 회귀가 2분 → 7분이 됐다(0910 실측).
        # 그래서 구도 때문에만 연달아 거절되면 이 배치에서는 구도 회피를 접는다(fail-open,
        # "배치가 말없이 줄어드는 게 더 나쁘다"는 이 루프의 원래 원칙과 같다).
        scene_dry = False
        scene_rejects = 0
        while len(plans) < n and tries < n * 20:
            tries += 1
            p = {}
            for axis in PERSON_AXES:
                p[axis] = draw(axis, allowed_values(axis, p, mode, v, tr))
            sig = tuple(p[a] for a in PERSON_AXES)
            if sig in seen or (strict and sig in past):
                continue
            for axis in SCENE_AXES:
                p[axis] = draw(axis, allowed_values(axis, p, mode, v, tr))
            scene = tuple(p[a] for a in SCENE_SIG_AXES)
            # 구도 중복 회피(2026-09-10). **1차에서만** 막는다 — 구도 후보는 유한해서
            # 2차까지 막으면 배치가 말없이 줄어든다(그게 더 나쁘다는 게 이 루프의 원래 원칙).
            if strict and not scene_dry and (scene in seen_scenes or scene in past_scenes):
                scene_rejects += 1
                if scene_rejects >= SCENE_DRY_AFTER:
                    scene_dry = True                  # 말랐다 — 이제부터 인물 중복만 본다
                continue
            scene_rejects = 0
            # 인물 서명은 구도 검사까지 통과한 뒤에 잠근다 — 먼저 잠그면 구도 때문에 버린 회차가
            # 멀쩡한 인물 조합까지 태워, 뽑을수록 후보가 마른다.
            seen.add(sig)
            seen_scenes.add(scene)
            plans.append({a: {"key": k, "text": v[a][k]} for a, k in p.items()})
    return plans


def distribution(plans: list, axes=None) -> dict:
    axes = axes or PERSON_AXES + SCENE_AXES
    return {a: dict(Counter(p[a]["key"] for p in plans)) for a in axes}
