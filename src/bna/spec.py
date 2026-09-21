"""변주 샘플링 + 프롬프트 조립. API 키 없이도 동작 (dry-run)."""
import random
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config"


_CACHE = {}


def load(name):
    """config YAML 을 읽는다. 파일 수정 시각으로 캐시한다 — 프롬프트 한 장에 load 가 십수 번 불려
    300장 계획이 분 단위로 걸렸다. 파일을 고치면 mtime 이 바뀌어 바로 다시 읽는다(서버 재시작 불필요)."""
    p = CFG / name
    m = p.stat().st_mtime_ns
    hit = _CACHE.get(name)
    if hit and hit[0] == m:
        return hit[1]
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    _CACHE[name] = (m, data)
    return data


def defaults_for(mode: str) -> dict:
    """모드별 기본 프로바이더. 정본은 config/providers.yaml 의 default_provider 한 곳이다.
    2026-09-08 성연서님 확정: 셀카 = GPT(openai). 코드에 다시 리터럴로 박지 마라."""
    d = load("providers.yaml")["default_provider"]
    if mode not in d:
        raise ValueError(f"providers.yaml default_provider 에 {mode} 가 없다")
    return d[mode]


PERSON_AXES = ["country", "age", "gender", "face_shape", "skin_tone", "skin_condition", "body_type",
               "hair_style", "hair_color", "eyes", "looks", "extras"]   # looks = 미모 축 (2026-09-17), 옛 계획엔 없어 build_prompts 가 ordinary 로 채운다
# 추첨 순서: looks 를 age 보다 먼저 — looks_gates.age(미모는 20~30대만)가 looks 를 알아야 닫힌다(fail-closed).
#   서명(planner.signature)은 PERSON_AXES 순서 그대로라 옛 등록부와 계속 맞는다. (2026-09-21)
DRAW_ORDER = ["looks"] + [a for a in PERSON_AXES if a != "looks"]
SCENE_AXES = ["background", "angle", "framing", "context", "lighting", "color", "quality", "expression"]

# 시술별 '못 잼(동일인 게이트가 얼굴을 못 찾음)' 상한. 정본은 여기 하나다 —
#   selftest ⑱ 와 tools/framing_na_forecast.py 가 같이 읽는다(두 벌이면 한쪽만 고쳐져 갈린다).
# 기본 10% = 2026-09-11 성연서님 B안.
# 예외 2종:
#   filler_neck : 목만 컷이 대표 구도인데 얼굴이 프레임 밖이다 — 어떻게 섞어도 10% 아래가 안 된다.
#   피부 3종    : 2026-09-14 연서님 검수 "실제는 볼 한쪽 확대(모공이 보이는 거리)". one_cheek 의
#                 실측 못 잼률이 100% 라, 확대 컷을 의미 있게 넣는 순간 10% 는 **산술적으로 불가능**하다.
#                 목표를 낮춘 게 아니라 이 3종만 갈랐다. 되돌리는 레버 = framing_weights 하나.
#                 ⚠ 20% 는 '다섯 장 중 한 장은 동일인 검사를 못 한다'는 뜻이다 — 사람 검수가 그만큼 더 중요하다.
NA_LIMIT = {"filler_neck": 0.35, "skinbooster_embo": 0.20, "skin_pores": 0.20, "skin_redness": 0.20}
NA_LIMIT_DEFAULT = 0.10


def treatment_rules(treatment: str, mode: str) -> dict:
    """시술별 조건 제약 (treatments.yaml 의 구조 필드) → 추첨·드리프트가 같이 쓰는 한 뭉치.
    allow  : {축: 허용값} — 모드 화이트리스트와 교집합 (framing_allow · scene_allow)
    ban    : {축: 금지값} — context_ban
    framing_ban_by_angle · age_weights(0 = 그 나이 안 뽑음) · drift_lock · expression_policy
    framing_weights : 시술별 프레이밍 가중(전역 weights.framing 에 곱한다). 0 은 쓰지 마라 —
                      '안 뽑기'는 framing_allow 가 할 일이고, 여기서 0 을 주면 그 프레이밍이
                      다시 쓸 만해졌는지 확인할 길이 사라진다(age_weights 와 달리 0 을 안 거른다).
    lighting_arc    : {before: [...], after: [...]} — Before 는 센 빛, After 는 부드러운 빛처럼
                      **방향이 있는 조명 차이**. drift_lock 에 lighting 이 있으면 무시된다(잠금이 이긴다).
                      ⚠ 이건 '조명을 자유롭게 푼다'가 아니다. 자유 재추첨은 후가 전보다 나빠 보이는
                        경우를 절반쯤 만든다 — 호는 한 방향으로만 간다(2026-09-14 연서님 검수).
    severity_weights: Before 강도 추첨 가중. 안 적으면 종전대로 균등이다.
                      ⚠ 0 은 쓰지 마라 — '안 뽑기'는 before_severity 목록이 할 일이다.
    series_relax    : 경과 시리즈 컷에서 **잠금을 한 칸만 푸는** 축 목록 (2026-09-18).
                      drift_lock·SERIES_LOCK 을 이 축에서 벗기되 자유 재추첨이 아니라 이웃 한 칸이다
                      (expression 은 '입 상태 유지 + 다른 키', angle·framing 은 neighbors 표).
                      안 적으면 종전대로 완전 잠금이라 다른 시술은 하나도 안 움직인다.
    single_relax    : 같은 완화를 **단발 컷**에 거는 축 목록 (2026-09-21 정식 반영, 팔자 expression).
                      확률은 종전 주사위 그대로. ⚠ 이 함수는 화이트리스트라, 여기 칸을 안 만들면
                      yaml 에 적어도 조용히 무시된다(09-21 첫 반영에서 0/40 으로 드러났다).
    treatment 이 None 이면 빈 규칙 (예전 호출·테스트가 그대로 돈다)."""
    r = {"allow": {}, "ban": {}, "age_weights": {}, "framing_weights": {}, "drift_lock": [],
         "framing_ban_by_angle": {}, "expression_policy": "free", "lighting_arc": {},
         "severity_weights": {}, "series_relax": [], "single_relax": []}
    if not treatment:
        return r
    t = load("treatments.yaml").get(treatment)
    if t is None:
        raise ValueError(f"treatments.yaml 에 {treatment} 가 없다")
    r["age_weights"] = {str(k): float(v) for k, v in (t.get("age_weights") or {}).items()}
    r["severity_weights"] = {str(k): float(v) for k, v in (t.get("severity_weights") or {}).items()}
    r["drift_lock"] = list(t.get("drift_lock") or [])
    r["series_relax"] = list(t.get("series_relax") or [])
    r["single_relax"] = list(t.get("single_relax") or [])
    r["expression_policy"] = t.get("expression_policy", "free")
    if r["expression_policy"] == "lock" and "expression" not in r["drift_lock"]:
        r["drift_lock"].append("expression")
    if mode == "selfie":                                  # 임상은 리그가 장면을 고정하므로 셀카에만 건다
        if t.get("framing_allow"):
            r["allow"]["framing"] = list(t["framing_allow"])
        for a, ks in (t.get("scene_allow") or {}).items():
            r["allow"][a] = list(ks)
        for a, ks in (t.get("axis_ban") or {}).items():
            r["ban"][a] = list(ks)
        r["framing_ban_by_angle"] = {k: list(v) for k, v in (t.get("framing_ban_by_angle") or {}).items()}
        r["framing_weights"] = {str(k): float(v) for k, v in (t.get("framing_weights") or {}).items()}
        arc = t.get("lighting_arc") or {}
        r["lighting_arc"] = {k: list(arc.get(k) or []) for k in ("before", "after") if arc.get(k)}
    return r


def allowed_values(axis: str, keys: dict, mode: str, v: dict, tr: dict, base=None, stage=None) -> list:
    """한 축의 허용 목록. 순서대로 거른다:
    모드 화이트리스트(또는 base) → 시술 허용/금지 → 성별 제외 → 나이 0 가중 → 배경×조명 → 조명 호(stage) → 각도×프레이밍 → 배경×맥락·프레이밍×맥락.

    stage: "before" | "after" | None. lighting_arc 를 쓰는 시술에서만 뜻이 있다 —
      Before 는 arc.before(센 빛)에서, After 는 arc.after(부드러운 빛)에서 뽑는다.
      ⚠ 여기서도 빈 목록이면 한 단계 전으로 되돌린다(fail-open). 즉 그 배경이 그 빛을 못 내면
        호가 성립하지 않고 조명이 그대로 남는다 — 없는 창문을 만들어내지 않으려는 것이다.
    keys 는 지금까지 뽑힌 {축: 값키}. 표가 서로 어긋나 빈 목록이 되면 한 단계 전 목록으로 돌아간다(조용히 죽지 않게).
    ⚠ 그 폴백은 config 오류를 숨기므로 selftest 가 실측으로 잡는다."""
    rules = v.get("mode_rules", {}).get(mode, {})
    allowed = list(base) if base else list(rules.get(axis) or list(v[axis]))
    ta = (tr.get("allow") or {}).get(axis)
    if ta:
        allowed = [k for k in allowed if k in ta] or allowed
    tb = (tr.get("ban") or {}).get(axis) or []
    allowed = [k for k in allowed if k not in tb] or allowed
    g = keys.get("gender")
    if g:
        banned = v.get("gender_exclusions", {}).get(g, {}).get(axis, [])
        allowed = [k for k in allowed if k not in banned] or allowed
    if axis == "age":
        zero = {k for k, w in (tr.get("age_weights") or {}).items() if w <= 0}
        allowed = [k for k in allowed if k not in zero] or allowed
    gates = v.get("age_gates", {}).get(axis) or {}
    if gates and keys.get("age"):                     # 그 값이 어울리는 나이에만 (새치는 40대~)
        allowed = [k for k in allowed if keys["age"] in [str(a) for a in gates.get(k, [keys["age"]])]] or allowed
    # 미모 게이트 (2026-09-17): 노션 AI 셀카 장면은 looks=attractive 에만. looks 가 아직 안 뽑혔거나(옛 계획)
    #   ordinary 면 그 값은 빠진다 — 게이트 값은 '적힌 looks 에서만'이라 모르면 막는 쪽(fail-closed)이다.
    lg = v.get("looks_gates", {}).get(axis) or {}
    if lg:
        allowed = [k for k in allowed if k not in lg or keys.get("looks") in lg[k]] or allowed
    _lpf = looks_profile(keys.get("looks"), v)
    pg = (_lpf.get("gates") or {}).get(axis) or (_lpf.get("gates_bg") if axis == "background" else None)
    if pg:                                            # 미모 프로필(스위치 켰을 때만): 피곤·잡티 계열·옆빛 못 내는 배경 빼기
        allowed = [k for k in allowed if k in pg] or allowed
    pf = (_lpf.get("before_force") or {}).get(axis)
    if pf and stage == "before":
        # 미모 프로필 Before 강제(3차) — 시술 허용표(scene_allow)를 일부러 넘는다. After 는 lock_after 가 같은 값으로 잠근다.
        #   빛은 배경이 낼 수 있는 것과 교집합(없으면 강제 목록 그대로 — 배경 게이트가 이미 옆빛 배경만 남겼다).
        compat = v.get("background_lighting", {}).get(keys.get("background")) if axis == "lighting" else None
        forced = [k for k in pf if k in v[axis]]
        return [k for k in forced if not compat or k in compat] or forced
    if axis == "lighting":
        compat = v.get("background_lighting", {}).get(keys.get("background"))
        if compat:
            allowed = [k for k in allowed if k in compat] or allowed
    # 조명 호는 **배경 호환표 뒤에** 건다 — 앞에 걸면 "욕실 + 창가 햇빛" 처럼
    # 그 배경이 낼 수 없는 빛이 남는다(교집합이 비면 폴백이 호를 그대로 통과시킨다).
    if axis == "lighting" and stage and "lighting" not in (tr.get("drift_lock") or []):
        arcv = (tr.get("lighting_arc") or {}).get(stage) or []
        if arcv:
            allowed = [k for k in allowed if k in arcv] or allowed
    if axis == "framing":
        fb = (tr.get("framing_ban_by_angle") or {}).get(keys.get("angle")) or []
        allowed = [k for k in allowed if k not in fb] or allowed
    if axis == "context":
        ca = v.get("context_allow", {}).get(keys.get("background"))
        if ca:
            allowed = [k for k in allowed if k in ca] or (["none"] if "none" in v[axis] else allowed)
        fb = v.get("framing_ban", {}).get(keys.get("framing")) or []
        allowed = [k for k in allowed if k not in fb] or (["none"] if "none" in v[axis] else allowed)
        hs = keys.get("hair_style")
        if hs:                                        # 잔머리는 긴 머리에만
            allowed = [k for k in allowed if hs in v.get("context_hair", {}).get(k, [hs])] or (["none"] if "none" in v[axis] else allowed)
    return allowed


def _split_items(s: str) -> list:
    """열거를 항목으로 쪼갠다 — **괄호 안 쉼표는 구분자가 아니다**.

    2026-09-11 실사고: `same eyes (shape, size, spacing, eyelid type)` 를 통짜 `split(", ")` 로
    쪼개니 항목이 4개로 갈라졌고, `identity_exempt: [eyes]` 가 그중 `same eyes (shape` 하나만
    지워 잠금문이 `Identity must be preserved precisely: size, spacing, eyelid type), same eyebrows…`
    라는 **말이 안 되는 문장**으로 나갔다. 오류도 안 났다(지운 항목이 1개라 '조용한 무효화' 검사도 통과).
    눈꺼풀 필러를 만들다 걸렸을 뿐, 괄호를 쓰는 항목이면 어느 시술에서든 같은 일이 난다.
    """
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append(cur.strip()); cur = ""
            continue
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _drop_identity_items(text: str, keywords: list) -> tuple:
    """잠금 문장의 열거 부분(": " 뒤 ~ 첫 ". " 앞)에서 낱말이 든 항목만 뺀다.
    열거 밖 문장(크롭 지시·과장 금지·동일인 확인)은 건드리지 않는다."""
    i = text.find(": ")
    if i < 0:
        return text, 0
    j = text.find(". ", i)
    j = len(text) if j < 0 else j
    items = _split_items(text[i + 2:j])
    kept = [it for it in items if not any(k in it.lower() for k in keywords)]
    if not kept or len(kept) == len(items):
        return text, len(items) - len(kept)
    return text[:i + 2] + ", ".join(kept) + text[j:], len(items) - len(kept)

def person_description(variation: dict) -> str:
    f = {k: (variation.get(k) or {}).get("text", "") for k in PERSON_AXES}
    # 미모는 인물 **맨 앞** 형용사 + 나이 바로 뒤 구체 특징 (2026-09-21 연서님 "미모가 나온 적이 없다" —
    #   맨 끝에 붙은 부정문은 앞선 리얼리티 묘사와 뒤따르는 '더 예쁘게 마라' 규칙 셋에 눌려 안 읽혔다).
    head = " ".join(x for x in (f["looks"], f["country"], f["gender"], f["age"]) if x)
    lk = (variation.get("looks") or {}).get("key")
    detail = (load("variations.yaml").get("looks_detail") or {}).get(lk, "")
    prof = looks_profile(lk)                         # 미모 프로필(스위치 켰을 때만): 피부·머리 문장 교체 + 나라별 미인상 + 메이크업
    _k = lambda ax: (variation.get(ax) or {}).get("key")
    skin = (prof.get("skin_text") or {}).get(_k("skin_condition"), f["skin_condition"])
    hair = (prof.get("hair_text") or {}).get(_k("hair_style"), f["hair_style"])
    detail = (prof.get("detail_by_country") or {}).get(_k("country"), detail)
    parts = [head, detail, f["face_shape"], f["skin_tone"], skin,
             f["body_type"], f"{f['hair_color']}, {hair}", f["eyes"], f["extras"], prof.get("makeup", "")]
    return ", ".join(p for p in parts if p)


def selfie_scene(f: dict) -> str:
    """셀카 장면 문장: 프레이밍 → 각도 → 배경/맥락 → 빛 → 색/화질 → 표정."""
    ctx = f", {f['context']}" if f.get("context") else ""
    expr = f' {f["expression"].capitalize()}.' if f.get("expression") else ""
    return (f'{f["framing"].capitalize()}. {f["angle"]}, {f["background"]}{ctx}. '
            f'{f["lighting"]}. {f["color"]}. {f["quality"]}.{expr}')


def sample_variation(mode: str, seed=None, weights=None, treatment=None) -> dict:
    """weights: {축: {값: 가중치}} — 제외가 몰린 조건값을 덜 뽑는다(lessons.active 의 weights).
    0 으로 죽이지 않고 낮추기만 하는 이유: 그 조건 자체가 나쁜 게 아니라 지금 모델이 약한 것이고,
    완전히 빼면 다시 좋아졌는지 영영 확인할 수 없다.
    treatment: 시술별 제약(framing_allow·scene_allow·age_weights…)을 건다. None 이면 모드 규칙만."""
    rng = random.Random(seed)
    weights = weights or {}
    v = load("variations.yaml")
    tr = treatment_rules(treatment, mode)
    picked, keys = {}, {}
    for axis in DRAW_ORDER + SCENE_AXES:
        options = v[axis]
        allowed = allowed_values(axis, keys, mode, v, tr)
        w = dict(weights.get(axis) or {})
        # ⚠ 전역 가중(variations.yaml 의 weights)과 시술별 가중을 여기서 같이 곱한다.
        #   planner.plan_batch 에도 같은 곱이 있다 — 한쪽만 고치면 배치 추첨과 단건 추첨이
        #   조용히 다른 분포를 낸다(회귀 ⑱-4 가 두 경로를 함께 잰다).
        for k, gw in (v.get("weights", {}).get(axis) or {}).items():
            w[k] = w.get(k, 1.0) * float(gw)
        if axis == "age":                                # 시술별 나이 가중 (0 은 이미 allowed 에서 빠졌다)
            for k, aw in tr.get("age_weights", {}).items():
                if aw > 0:
                    w[k] = w.get(k, 1.0) * aw
        if axis == "framing":                            # 시술별 프레이밍 가중 (목주름은 목만 컷이 필수라 전역값과 다르다)
            for k, fw in tr.get("framing_weights", {}).items():
                w[k] = w.get(k, 1.0) * fw
        # 미모 프로필 가중(스위치 켰을 때만) — planner.plan_batch 에도 같은 곱이 있다(두 경로 한 벌).
        for k, pw in ((looks_profile(keys.get("looks"), v).get("weights") or {}).get(axis) or {}).items():
            w[k] = w.get(k, 1.0) * float(pw)
        if w and len(allowed) > 1:
            ws = [max(0.01, float(w.get(k, 1.0))) for k in allowed]
            key = rng.choices(allowed, weights=ws, k=1)[0]
        else:
            key = rng.choice(allowed)
        picked[axis] = {"key": key, "text": options[key]}; keys[axis] = key
    return picked


# 시리즈(한 사람의 여러 시점) 컷에서 추가로 잠그는 축. 상세 근거는 drift_after 머리말.
SERIES_LOCK = {"framing", "extras"}


def experiment_flags(as_meta: bool = False):
    """실험 회차 스위치 (2026-09-21). 기본 경로는 안 바꾸고, 켠 회차만 환경변수로 켠다.

    BNA_EXP_RELAX    쉼표 구분 축 — 단발 컷에도 시리즈 완화를 건다(drift_lock 에 있는 축만 풀린다).
                     **켠 축은 주사위도 건너뛴다**(확률 1) — 09-21 1차: 스위치를 켜도 주사위(직후 0.5·이후 0.7)에서
                     빠져 실험 2장 중 1장만 표정이 바뀌었다. 실험 묶음에서 '바꾸라고 한 축'이 안 바뀌면 표본이 아니다.
    BNA_EXP_SEVERITY Before 강도 고정 (mild|moderate|marked)
    BNA_EXP_WHEN     단발 컷 시점 고정 (immediate|1w|2w|4w) — 09-21 1차: 시점이 추첨이라 대조=직후 2 ·
                     실험=직후 1·2주 1 로 섞여 판정이 안 났다. 시술이 모르는 시점이면 무시(종전 추첨).
    as_meta=True 면 meta 에 실을 모양({relax:[…], severity:…, when:…} 또는 None)을 돌려준다.
    """
    import os
    relax = {s.strip() for s in os.environ.get("BNA_EXP_RELAX", "").split(",") if s.strip()}
    sev = os.environ.get("BNA_EXP_SEVERITY", "").strip() or None
    when = os.environ.get("BNA_EXP_WHEN", "").strip() or None
    prof = os.environ.get("BNA_EXP_LOOKS_PROFILE", "").strip() in ("1", "true", "on")
    if as_meta:
        out = {"relax": sorted(relax), "severity": sev, "when": when}
        if prof:                                       # 새 칸은 켰을 때만 싣는다 — 옛 회차 meta 와 모양이 같게
            out["looks_profile"] = True
        return out if (relax or sev or when or prof) else None
    return {"relax": relax, "severity": sev, "when": when, "looks_profile": prof}


def looks_profile(looks_key, v: dict = None) -> dict:
    """미모 프로필(variations.yaml `looks_profile`) — 실험 스위치 BNA_EXP_LOOKS_PROFILE 이 켜졌고 그 looks 에
    프로필이 있을 때만 그 dict, 아니면 {} (2026-09-21 빌디 제안·연서님 확인). 판정은 여기 한 곳이다 —
    추첨(allowed_values·sample_variation·planner)과 문장(person_description·build_prompts)·참조(batch)가 같이 부른다."""
    if not looks_key or not experiment_flags()["looks_profile"]:
        return {}
    v = v or load("variations.yaml")
    return (v.get("looks_profile") or {}).get(looks_key) or {}


def drift_after(variation: dict, mode: str, rng, timeline: str = "2w", treatment=None, series: bool = False,
                seen: dict = None) -> dict:
    """셀카 모드: After 촬영 상황을 확률적으로 바꾼다 (이목구비 축은 절대 건드리지 않음).
    timeline 이 immediate 면 같은 날(옷·머리 고정), 그 외는 다른 날(옷·머리·배경 대부분 교체).
    treatment 의 drift_lock 축(표정·각도·화질…)은 건너뛴다 — 그 축이 바뀌면 시술이 아니라 촬영 차이가 B&A 로 둔갑한다.

    series=True 면 **구도(framing)와 얼굴에 얹히는 소품(extras)을 추가로 잠근다**.
    2026-09-11 실측(팔자 3시점, 배치 20260911-124645-5cce): 컷마다 framing 이 0.6 확률로 다시 뽑혀
      직후=전체얼굴 · 1주=하관만 · 2주=전체얼굴+안경 으로 갈렸고, 1주 컷은 팔자 주름이 사실상 화면
      가장자리로 밀려났다. 심사가 그 컷을 보고 '턱선·목이 정리됐다'고 8점을 줬다 — 시술 부위가 아닌
      곳을 보고 준 점수다. 시점 비교는 '같은 구도로 다시 찍은 사진'일 때만 성립한다.
      옷·배경·조명·머리는 그대로 계속 바뀐다(다른 날에 찍은 티는 거기서 난다).

    2026-09-14 (연서님 검수 "6장 전부 전·후 구분 불가·복붙처럼 보임"): 프레이밍은 **잠금과 자유 사이**다.
      · 자유 재추첨 = '전 얼굴 전체 → 후 한쪽 볼' 점프 → 전후 비교가 물리적으로 성립 안 함(0911 사고)
      · 완전 잠금  = 여섯 장이 같은 구도 → 복붙처럼 보임(0914 아침 v10)
      그래서 `framing_neighbors` 로 **한 칸 옆 거리까지만** 옮긴다. 각도·머리와 같은 방식이다.
      시리즈 컷은 SERIES_LOCK 이 여전히 완전 잠금이다(한 사람의 여러 시점은 같은 구도여야 한다).

    2026-09-18 (연서님 검수 "전·직후·2주 세 장의 표정·입모양·구도·카메라 각도가 똑같다", 09-17 6세트 실측):
      팔자는 drift_lock[expression, angle] + SERIES_LOCK{framing} 이라 **셀카를 다른 사진으로 만드는 축
      셋이 한꺼번에 잠겨** 있었다 — 6세트 전부 after_changed_axes 에 이 셋이 한 번도 없다. 그래서 After
      장면 문장이 Before 와 글자 그대로 같고, 2주 컷은 모델이 참조를 베끼는 게 가장 싼 길이 된다
      (실측: 2주 컷 표정차 0.0027~0.0066 vs 직후 0.0063~0.0179, 복붙 탈락도 2주에서만 났다).
      → `series_relax` 에 적힌 축만 **이웃 한 칸**으로 푼다(자유 재추첨이 아니다).
      · expression : Before 의 **입 상태(다문/벌린)는 그대로** 두고 키만 바꾼다 — 벌린 입은 주름을 펴서
        시술 없이도 후가 좋아 보이고(가짜 효과), 다문 채로도 jaw_loose·lip_asym·시선·눈썹은 눈에 보이게
        달라진다. '웃음 금지'는 scene_allow 가 이미 한다.
      · angle·framing : neighbors 표 한 칸. 이웃이 없으면 **안 바뀐다**(자유 폴백 금지 — 각도가 멀리
        뛰면 주름 그림자가 달라져 촬영 차이가 효과로 둔갑한다).
      · seen : 앞 시점이 쓴 키를 피한다 — 안 피하면 직후·2주가 서로 같은 값을 뽑아 '세 장 똑같다'가
        Before 쪽만 풀린 채로 남는다."""
    v = load("variations.yaml")
    tr = treatment_rules(treatment, mode)
    relax = set(tr.get("series_relax") or []) if series else set()
    # 단발 완화 (2026-09-21 정식 반영, 연서님 "응 돌려보자") — 시리즈가 아닐 때 `single_relax` 축을 같은
    #   완화 경로(입 상태 고정 + 이웃 한 칸)로 푼다. 확률은 종전 주사위 그대로(실험 스위치와 달리 강제하지 않는다).
    #   근거·되돌리기 = treatments.yaml 해당 줄 주석. 시리즈 컷은 위 series_relax 가 이미 맡는다.
    if not series:
        relax |= set(tr.get("single_relax") or []) & set(tr.get("drift_lock") or [])
    # 실험 스위치 (2026-09-21 연서님 확인, 빌디 요청) — **단발 컷에도** 시리즈 완화를 켠다.
    #   팔자는 drift_lock[expression, angle] 이라 단발 회차 18장 전부 After 표정이 한 번도 안 바뀌었고,
    #   사람 'AI 티' 15장이 전부 팔자였다(docs/ai-look-item-0921-teemo.md §8). 완화 경로는 시리즈와 같다 —
    #   입 상태(다문/벌린)는 Before 와 묶고 키만 바꾼다(가짜 효과 방지는 그대로).
    #   ⚠ 설정(yaml)이 아니라 환경변수인 이유: 실험 회차에서만 켜고, 결과 전엔 기본 경로를 안 바꾼다.
    #     켠 회차는 meta["experiment"] 에 남는다(experiment_flags). drift_lock 에 있는 축만 풀린다.
    _exp_forced = experiment_flags()["relax"] & set(tr.get("drift_lock") or [])
    relax |= _exp_forced
    lock = (set(tr.get("drift_lock") or []) | (SERIES_LOCK if series else set())) - relax
    # 미모 프로필 3차: Before 에 강제한 표정(웃음)·빛(옆빛)은 After 에서도 그대로 — 풀리면 촬영 차이가 효과로 둔갑한다.
    #   완화(relax)보다 **뒤에** 더한다: single_relax 가 표정을 풀어도 여기서 다시 잠근다.
    lock |= set(looks_profile((variation.get("looks") or {}).get("key"), v).get("lock_after") or [])
    seen = seen or {}
    probs = v.get("after_drift", {}).get(mode, {})
    if "immediate" in probs or "later" in probs:
        probs = probs.get("immediate" if timeline == "immediate" else "later", {})
    override = v.get("after_immediate", {}).get(mode, {}) if timeline == "immediate" else {}
    # 조명 호(전=센 빛 · 후=부드러운 빛)는 **가라앉은 뒤** 컷에만 (2026-09-14 저녁). 직후는 병원·차 안에서
    # 같은 날 찍는 컷이라 센 빛이 정상이고, 부드러운 빛으로 몰면 볼록·홍조가 물광처럼 읽힌다.
    stg = None if timeline == "immediate" else "after"
    after = {k: dict(val) for k, val in variation.items()}
    keys = {k: val["key"] for k, val in after.items()}
    for axis, p in probs.items():
        # 실험으로 푼 축은 확률 1 — 주사위는 그대로 한 번 굴려 rng 흐름을 스위치 유무와 맞춘다(experiment_flags 머리말).
        _roll = rng.random() if (axis not in lock and axis in v) else None
        if axis in lock or axis not in v or (_roll >= p and axis not in _exp_forced):
            continue
        allowed = allowed_values(axis, keys, mode, v, tr, base=override.get(axis), stage=stg)
        if axis == "framing":                               # 프레이밍도 이웃 거리로만 (아래 framing_neighbors 주석)
            nb = v.get("framing_neighbors", {}).get(variation["framing"]["key"])
            if nb is not None:
                allowed = [k for k in allowed if k in nb]   # 빈 목록이면 안 바뀐다
        if axis == "angle":                                 # 각도는 이웃 각도로만 (비슷하되 동일하지 않게)
            nb = v.get("angle_neighbors", {}).get(variation["angle"]["key"])
            if nb:
                nxt = [k for k in allowed if k in nb]
                # 시리즈 완화 축은 폴백 없음 — 이웃이 없으면 안 바꾼다(위 머리말: 멀리 뛰면 가짜 효과).
                allowed = nxt if (nxt or axis in relax) else allowed
        if axis == "expression":
            # 표정은 '키가 다르다'가 아니라 '사람 눈에 다르다'여야 한다 (2026-09-14 밤 연서님 검수).
            # neutral_closed → slight_smile 은 키가 바뀌어도 입은 다문 채, 눈은 렌즈 — 실측 450세트에서
            # **입·눈이 둘 다 그대로인 세트가 47%** 였다. 확률(0.7)은 그대로 두고 고르는 쪽만 좁힌다
            # (연서님 "'무조건'이라는 단어로 너무 막아두지 말자" — 30%는 여전히 같은 표정으로 남는다).
            tb = v.get("expression_traits", {})
            cur_tr = tb.get(variation["expression"]["key"], {})
            if axis in relax:
                # 시리즈 완화: 입 상태는 Before 와 같게 묶고 키만 바꾼다 (2026-09-18 머리말 참조).
                keep = [k for k in allowed if tb.get(k, {}).get("mouth") == cur_tr.get("mouth")]
                allowed = keep or []                        # 같은 입 상태가 하나도 없으면 안 바꾼다
            else:
                vis = [k for k in allowed
                       if any(tb.get(k, {}).get(f) != cur_tr.get(f) for f in ("mouth", "eyes"))]
                allowed = vis or allowed                    # 고를 게 없으면 종전대로 (fail-open)
        if axis == "hair_style":                            # 머리는 2주 안에 될 수 있는 모양으로만 (포니테일→삭발 금지)
            nb = v.get("hair_style_neighbors", {}).get(variation["hair_style"]["key"])
            if nb is not None:
                allowed = [k for k in allowed if k in nb]   # 빈 목록이면 안 바뀐다
        opts = [k for k in allowed if k != variation[axis]["key"]]
        if axis in relax and len(opts) > 1:                 # 앞 시점이 쓴 값은 피한다 (없으면 종전대로)
            opts = [k for k in opts if k not in (seen.get(axis) or set())] or opts
        if opts:
            k = rng.choice(opts); after[axis] = {"key": k, "text": v[axis][k]}; keys[axis] = k
    # ── 조명 호가 있는 시술은 **배경보다 조명이 먼저다** (2026-09-14 오후 연서님 검수) ──
    # allowed_values 는 배경 호환표 뒤에 호를 걸고, 교집합이 비면 fail-open 으로 호를 버린다
    # (없는 창문을 만들지 않으려는 것 — 그 판단은 그대로 맞다). 문제는 **배경 쪽을 아무도 안 옮긴 것**이다:
    # After 배경이 욕실로 가면 창이 없어 부드러운 빛이 원천적으로 불가능해, 호가 조용히 깨진 채
    # 후 컷이 센 빛으로 남는다(0914 실측 22%, 그 세트는 '후가 더 나빠 보인다').
    # → 후 컷 배경이 호의 빛을 못 내면 **낼 수 있는 배경으로 옮긴다**. 옮길 곳이 없으면 종전대로 둔다(fail-open).
    arc_after = (tr.get("lighting_arc") or {}).get("after") or []
    if arc_after and stg and "lighting" not in lock and "background" not in lock:
        bl = v.get("background_lighting", {})
        if not (set(bl.get(keys.get("background"), [])) & set(arc_after)):
            bg_ok = [b for b in allowed_values("background", keys, mode, v, tr,
                                               base=override.get("background"), stage=stg)
                     if set(bl.get(b, [])) & set(arc_after)]
            if bg_ok:
                k = rng.choice(bg_ok); after["background"] = {"key": k, "text": v["background"][k]}; keys["background"] = k

    # 배경이 바뀌었으면 조명·맥락이 새 배경(과 프레이밍)에 맞는지 마지막으로 한 번 더 확인
    for axis in ("lighting", "context"):
        if axis in lock:
            continue
        ok = allowed_values(axis, keys, mode, v, tr, base=override.get(axis), stage=stg)
        if keys[axis] not in ok:
            k = rng.choice(ok); after[axis] = {"key": k, "text": v[axis][k]}; keys[axis] = k
    return after


def _norm(x: str) -> str:
    return " ".join(str(x).split())


def segments(text: str, spans: list) -> list:
    """프롬프트 문자열을 [{"k": 칸, "t": 문장}] 조각 목록으로. spans = [(칸, 그 칸이 넣은 문장)].
    문장 위치를 찾아 표시하고, 어느 칸에도 안 속한 나머지는 템플릿 고정문(k="template")이다.
    비전공자가 "이 문장은 어디서 왔나"를 화면에서 색으로 읽게 하려는 것 — 프롬프트 자체는 그대로다."""
    text = _norm(text); marks = []
    for k, v in spans:
        v = _norm(v)
        if not v:
            continue
        start = 0
        while True:
            i = text.find(v, start)
            if i < 0:
                break
            if not any(a <= i < b or a < i + len(v) <= b for _, a, b in marks):
                marks.append((k, i, i + len(v))); break
            start = i + 1
    marks.sort(key=lambda m: m[1])
    out, pos = [], 0
    def push(k, t):
        t = t.strip()
        if not t:
            return
        if out and t in (".", ",", ";", ":"):             # 홀로 남은 마침표는 앞 조각에 붙인다
            out[-1]["t"] += t; return
        out.append({"k": k, "t": t})
    for k, a, b in marks:
        if a > pos:
            push("template", text[pos:a])
        push(k, text[a:b]); pos = b
    push("template", text[pos:])
    return out


TIMELINE_ORDER = ["immediate", "1w", "2w", "4w"]


def series_points(treatment: str, series) -> list:
    """요청한 경과 시점을 시술이 허용하는 것만, 시간순으로. 빈 목록이면 시리즈가 아니다."""
    if not series:
        return []
    allowed = load("treatments.yaml")[treatment].get("timeline", ["2w"])
    return [w for w in TIMELINE_ORDER if w in series and w in allowed]


FACT_KEYS_PROMPT = ("immediate_marks", "immediate_avoid")   # 직후 컷에 그대로 들어가는 칸 (영어)
# 2026-09-14 빌디·연서님: '후' 의 기준을 실사 한 장으로 못박았다(엠보 7일차). 직후가 **아닌** After 컷에 실린다.
#   ⚠ 셀카 전용이다 — 임상 컷은 조명까지 동일하게 맞춘 편집이라 광 문장이 붙으면 그게 곧 리터칭으로 읽힌다
#     (selftest ㉜ 가 "임상 After 에 광 문장 없음"을 이미 지키고 있다, 같은 이유).
FACT_KEYS_AFTER = ("after_reference",)
FACT_KEYS_HUMAN = ("onset", "extent", "later")              # 사람이 읽는 근거 칸 (한국어 가능)
FACT_KEYS_ALL = FACT_KEYS_PROMPT + FACT_KEYS_AFTER + FACT_KEYS_HUMAN


def check_treatment_facts(treatment: str) -> None:
    """`immediate_level` · `facts` 사실 카드의 죽은 설정을 **소리 내서** 막는다 (2026-09-11).

    이 두 칸의 실패 모드는 '틀린 값'이 아니라 **아무도 안 읽는 값**이다 — 카드에 적어 두고
    프롬프트엔 안 실려서, 적은 사람은 반영된 줄 알고 그림만 계속 어긋난다(0909 identity_exempt 와 같은 유형).
    그래서 ①오타 칸 ②직후 시점이 없는 시술의 직후 설정 ③읽는 자리가 없는 값을 전부 여기서 세운다.
    """
    t = load("treatments.yaml")[treatment]
    tl = list(t.get("timeline") or [])
    has_imm = "immediate" in tl
    if t.get("immediate_level") is not None:
        # 2026-09-11 아침의 한 칸짜리 재정의는 같은 날 `series_levels` 로 승격했다(B안).
        # 남겨 두고 무시하면 적은 사람은 반영된 줄 안다 — 규칙 두 벌 대신 소리 내고 죽는다.
        raise ValueError(f"{treatment}.immediate_level 은 폐기됐다 — `series_levels: {{immediate: final}}` 로 적어라")
    ok = ("final",) + tuple(load("effects.yaml")["effect_levels"])
    for w, lvl in (t.get("series_levels") or {}).items():
        if str(lvl) not in ok:
            raise ValueError(f"{treatment}.series_levels[{w}]={lvl!r} 은 없는 강도다 (가능: {ok})")
        if w not in tl:
            raise ValueError(f"{treatment}.series_levels 에 {w} 를 적었는데 timeline 에 없다 — 죽은 설정")
    facts = t.get("facts")
    if facts is None:
        return
    if not isinstance(facts, dict) or not facts:
        raise ValueError(f"{treatment}.facts 가 비었다 — 빈 카드는 적지 마라(주석으로 두고 채울 때 푼다)")
    bad = [k for k in facts if k not in FACT_KEYS_ALL]
    if bad:
        raise ValueError(f"{treatment}.facts 에 모르는 칸 {bad} (가능: {FACT_KEYS_ALL})")
    for k in FACT_KEYS_PROMPT:
        if facts.get(k) and not has_imm:
            raise ValueError(f"{treatment}.facts.{k} 는 직후 컷에만 실리는데 timeline 에 immediate 가 없다 — 죽은 설정")
    for k in FACT_KEYS_AFTER:
        # 직후가 아닌 After 컷에만 실린다 — 시점이 직후뿐이면 아무 데도 안 붙는다(적은 사람은 붙은 줄 안다).
        if facts.get(k) and not [w for w in tl if w != "immediate"]:
            raise ValueError(f"{treatment}.facts.{k} 는 직후 아닌 After 컷에 실리는데 timeline 에 그런 시점이 없다 — 죽은 설정")
        if facts.get(k) and "selfie" not in (t.get("modes") or []):
            raise ValueError(f"{treatment}.facts.{k} 는 셀카 모드 전용인데 modes 에 selfie 가 없다 — 죽은 설정")


DRESS_WORDS = ("tape", "patch", "gauze", "dressing", "numbing cream")


def check_avoid_vs_facts(treatment: str, when: str, fact_texts: list, avoid_lines: list) -> None:
    """사실 카드와 금지문이 **같은 컷에서 반대를 지시하면** 소리 내고 멈춘다 (2026-09-11 실사고).

    그날 직후 컷엔 카드의 "입가에 재생테이프를 붙여라"와 09-10 승격 금지문의
    "테이프·패치 보이지 마라"가 함께 들어갔다. 모델은 둘 중 하나를 골랐고 우리는
    어느 쪽이 이겼는지도 모른 채 effect_visible 로 떨어졌다 — 조용한 모순이 제일 비싸다.
    푸는 법은 규칙을 지우는 게 아니라 `avoid.yaml` 그 규칙에 `not_at: [<그 시점>]`.
    """
    facts = " ".join(str(x).lower() for x in fact_texts if x)
    ban = " ".join(str(x).lower() for x in avoid_lines if x)
    if not facts or not ban:
        return
    clash = [w for w in DRESS_WORDS if w in facts and w in ban]
    if clash:
        raise ValueError(
            f"{treatment} {when} 컷: 사실 카드가 {clash} 를 그리라고 하는데 같은 컷 금지문이 "
            f"그걸 금지한다 — avoid.yaml 의 그 규칙에 `not_at: [{when}]` 을 적어라")



# "다시 찍은 사진"임을 말하는 공통 문장 (2026-09-10·09-11 성연서님 "로봇이야" → 2026-09-14 공통화).
# ⚠ 이 문장이 없으면 참조로 넘긴 Before 가 포즈·눈 뜬 정도·입 벌림까지 그대로 복제된다.
#   표정 축을 다시 뽑아도 소용없다 — 설정보다 참조 이미지가 세다(같은 구조: 물광은 빛이 만든다).
RESHOT_BASE = (
    'This is a second, separate photo of the same person, not the reference photo edited: the phone was put '
    'down and picked up again, so the arm is at a different distance and height, the head sits at a different '
    'tilt and rotation, the face is not in the same spot in the frame, the eyes are open a different amount')
RESHOT_LINE = (RESHOT_BASE + ' and the mouth is open a different amount. Do not copy the pose, the gaze or the '
               'mouth shape of the reference. ')
# 표정이 잠긴 시술(주름 필러)용 변형 — 입을 *벌리라*고 하면 그것만으로 주름이 펴져 가짜 효과가 된다.
# 그래서 '입 상태는 같게, 입 선은 복사 금지'로 갈라 적는다 (2026-09-18 연서님 검수 ③).
# 새 장면의 빛이 얼굴에도 오는가 (2026-09-18 연서님 검수 ② "합성 티"). 얼굴은 참조에서 거의 그대로
# 가져오고 배경·옷만 갈아 끼우면, 모자·다른 방인데 얼굴 밝기·그림자 방향이 전과 같아 **오려 붙인 것처럼**
# 보인다. 장면을 바꾸라는 말은 이미 있었고 '그 빛이 얼굴에도 떨어진다'는 말이 없었다.
RELIGHT_LINE = (
    'The light on the face belongs to this new scene: the direction, height and softness of the light falling on '
    'the face, and the shadows it casts beside the nose, on the cheeks and under the chin, follow the light source '
    'described in this scene and not the lighting of the reference photo.')
RESHOT_HELD = (RESHOT_BASE + '. The mouth stays in the same state as in the reference — lips closed stay closed, '
               'lips parted stay parted — because opening or stretching the mouth would change the folds being '
               'treated on its own; its exact line is still not copied, the jaw hangs a little differently and '
               'the corners rest a little differently. Do not copy the pose or the gaze of the reference. ')

# Before 피부 질감 한 줄 (종전 before.md 에 박혀 있던 문장 그대로 — 2026-09-21 미모 프로필이 이 줄만 갈아 끼우려고 뺐다)
SKIN_TEXTURE = ("Real skin with visible pores, faint peach fuzz, minor blemishes, slight redness and natural asymmetry; "
                "individual hair strands.")


def build_prompts(treatment: str, mode: str, variation: dict, seed=None, avoid=None, series=None,
                  avoid_not_at=None) -> dict:
    """avoid: {"before": [...], "after": [...]} — 제외 사유에서 배운 금지문(lessons.active).
    None 이면 붙이지 않는다(dry-run·테스트가 과거와 같은 문장을 내게).
    avoid_not_at: {금지문: [붙이지 않을 시점…]} — lessons.active 의 `not_at`."""
    from . import lessons
    av = avoid or {}
    not_at = avoid_not_at or {}
    avoid_before = lessons.avoid_text(av.get("before") or [])
    after_lines_all = list(av.get("after") or [])

    def after_lines_at(w):
        """그 컷에 실제로 붙는 금지문. 시점 예외(not_at)를 컷 단위로 뺀다."""
        return [ln for ln in after_lines_all if str(w) not in (not_at.get(ln) or [])]

    avoid_after = lessons.avoid_text(after_lines_all)
    t = load("treatments.yaml")[treatment]
    if mode not in t["modes"]:
        raise ValueError(f"{treatment} does not support mode {mode}")
    check_treatment_facts(treatment)
    rng = random.Random(seed)
    mode_extra = load("prompts/mode_extra.yaml")[mode].strip()
    # 프레이밍별 본문 (2026-09-17): 머리~바스트 셀카는 '부위를 렌즈에 바짝'이 아니라 일상 셀카다. 표에 없는 프레이밍은 종전 문장.
    _mxf = load("prompts/mode_extra.yaml").get(f"{mode}_by_framing") or {}
    if variation.get("framing", {}).get("key") in _mxf:
        mode_extra = " ".join(str(_mxf[variation["framing"]["key"]]).split())
    if "expression" not in variation:                # 예전 계획(표정 축 없던 시절)도 조립되게
        ek = "neutral_closed"; variation = {**variation, "expression": {"key": ek, "text": load("variations.yaml")["expression"][ek]}}
    if "looks" not in variation:                     # 예전 계획(미모 축 없던 시절, ~2026-09-17) = 보통
        variation = {**variation, "looks": {"key": "ordinary", "text": ""}}
    tr = treatment_rules(treatment, mode)
    fields = {k: v["text"] for k, v in variation.items()}
    rig = None
    if mode == "clinical":
        # 리그 3벌 중 하나를 세트마다 뽑는다 (2026-09-15 v1). 세트 안(전·후)에서는 고정 — After 는 같은 rig 의
        #   retake 문장을 쓴다. 종전 `rig_default` 하나는 실제 병원 사진보다 너무 깨끗했다(clinical_rig.yaml 머리말).
        rig = load("clinical_rig.yaml")
        rig_key = rng.choice(sorted(rig["rigs"]))
        r = rig["rigs"][rig_key]
        variation = {**variation, "rig": {"key": rig_key, "text": r.get("label", rig_key)}}
        angle = rig["angles"].get({"front": "front", "three_quarter": "oblique_45", "side": "side"}.get(variation["angle"]["key"], "front"))
        scene = ". ".join([angle, r["camera"], r["distance"], r["lighting"], r["background"], r["subject_setup"], r["processing"]]) + "."
    else:
        scene = selfie_scene(fields)
    # Before 의 피부 읽힘 한 줄은 모드별 (셀카 = 종전 before.md 문장 그대로, 임상 = 병원 조명용)
    skin_read = " ".join(str(load("prompts/mode_extra.yaml")["skin_read"][mode]).split())
    _srf = (load("prompts/mode_extra.yaml")["skin_read"].get(f"{mode}_by_framing") or {})
    if variation.get("framing", {}).get("key") in _srf:
        skin_read = " ".join(str(_srf[variation["framing"]["key"]]).split())
    # 미모 프로필(스위치 켰을 때만) — '피곤하고 못 나온 피부' 압력 대신 맑은 피부, 질감 문장에서 잡티·붉음만 뺀다.
    _prof = looks_profile((variation.get("looks") or {}).get("key")) if mode == "selfie" else {}
    skin_texture = " ".join(str(_prof.get("skin_texture") or SKIN_TEXTURE).split())
    if _prof.get("skin_read"):
        skin_read = " ".join(str(_prof["skin_read"]).split())
    sevs = t.get("before_severity", ["moderate"])
    # Before 강도는 **가중 추첨**이다 (2026-09-14). 종전 균등 추첨은 피부 3종에서 절반이 mild 로 떨어졌고,
    #   mild 는 effect_by_severity 상 subtle 하고만 짝지어진다 — 즉 "거의 없는 문제 → 은은한 개선"이라
    #   전후가 물리적으로 구별되지 않는 세트가 설계상 50% 였다(0914 실측 6장 중 2장).
    #   가중이 없으면 종전과 똑같이 균등이다.
    _sw = treatment_rules(treatment, mode).get("severity_weights") or {}
    _pool = [x for x in sevs for _ in range(max(1, round(4 * float(_sw.get(x, 1.0)))))]
    if mode == "clinical" and any(x != "mild" for x in _pool):
        # 임상 기록 사진은 문제가 또렷한 사람이 찍는다 — mild 는 effect_by_severity 상 subtle 로만 이어져
        #   전후가 구별되지 않는 세트가 된다 (2026-09-15 첫 실회차 "너무 안 바뀐다"). 셀카는 종전 그대로.
        _pool = [x for x in _pool if x != "mild"]
    sev = rng.choice(_pool)
    # 실험 스위치 — Before 강도 고정 (09-21 c8 교훈: 2세트 회차에선 추첨 한 건이 곧 50%라 바꾼 축이 안 걸린다).
    #   추첨은 그대로 한 번 소비한다(rng 흐름이 스위치 유무로 갈리지 않게). 시술이 모르는 값이면 무시.
    _fs = experiment_flags()["severity"]
    if _fs and _fs in sevs:
        sev = _fs
    elif _prof.get("severity") in sevs:               # 미모 프로필: Before 강도 고정(추첨은 위에서 이미 소비 — rng 흐름 불변)
        sev = _prof["severity"]
    min_age = t.get("severity_min_age", {})
    if min_age:                                   # 인물 나이가 강도 최소 나이보다 어리면 한 단계씩 낮춤
        order = list(load("variations.yaml")["age"])
        age_i = order.index(variation["age"]["key"])
        while sev in min_age and age_i < order.index(min_age[sev]) and sevs.index(sev) > 0:
            sev = sevs[sevs.index(sev) - 1]
    cond = t.get("before_condition", {})
    cond = cond.get(sev, "") if isinstance(cond, dict) else cond
    # 미모 프로필 전용 문장(있으면) — 나이 하향 **뒤**의 sev 로 고른다(late_20s 가 mild 로 내려가면 종전 mild 문장)
    cond = ((_prof.get("before_condition") or {}).get(treatment) or {}).get(sev, cond)
    before = (CFG / "prompts/before.md").read_text(encoding="utf-8").format(
        person=person_description(variation), before_condition=str(cond).strip(), scene=scene, mode_extra=mode_extra, skin_read=skin_read, avoid=avoid_before,
        skin_texture=skin_texture, **fields)
    def identity_for(ref_framing, target_framing=None):
        """동일인 잠금 문장.
        - 항목 목록은 Before·After 중 **좁은 쪽** 파일에서 온다 (레퍼런스에 없는 걸 요구하면 모델이 지어낸다).
        - `CROP:` 줄(크롭 지시)은 **생성할 사진**이 좁을 때만 남긴다 — 좁은 Before + 넓은 After 에
          "눈을 프레임 안으로 들이지 마라"가 붙으면 같은 프롬프트의 장면문("얼굴 전체")과 정면 충돌한다
          (2026-09-09 티모 실측 360건 중 36건, 10%).
        - `identity_exempt` 는 **낱말**이다(문구 아님). 잠금 파일 3벌이 서로 다른 표현을 쓰므로
          문구를 그대로 지우면 한 파일에서만 먹고 나머지에선 조용히 아무 일도 안 한다
          (0909 실측: 리프팅 82/120·인중 79/120 에서 시술 부위가 잠긴 채 남았다)."""
        vv = load("variations.yaml"); order = vv.get("identity_lock_order") or []; table = vv.get("identity_lock_by_framing") or {}
        target_framing = target_framing or ref_framing
        def narrowness(f):
            if f not in order:                       # 표에 없는 프레이밍은 '가장 좁음'으로 본다 —
                return len(order)                    # 넓은 쪽으로 폴백하면 얼굴을 프레임 안으로 끌고 온다
            return order.index(f)
        def _read(f):
            return (CFG / "prompts" / table.get(f, "identity_lock.md")).read_text(encoding="utf-8").strip()
        fr = max([ref_framing, target_framing], key=narrowness)
        lines = [ln for ln in _read(fr).splitlines() if not ln.startswith("CROP:")]
        crop = next((ln for ln in _read(target_framing).splitlines() if ln.startswith("CROP:")), None)
        if crop:                                 # 크롭 지시는 **생성할 사진**의 프레이밍 것으로 (항목 목록과 출처가 다르다)
            lines.insert(1, crop)
        text = " ".join(" ".join(lines).replace("CROP:", "").split())
        ex = [str(k).lower() for k in (t.get("identity_exempt") or [])]
        if ex:                                       # 시술 부위 항목을 잠금 목록에서 뺀다
            text, dropped = _drop_identity_items(text, ex)
            if not dropped:                          # 조용한 무효화가 이 규칙의 실패 모드였다 — 소리 내고 죽는다
                raise ValueError(f"identity_exempt {ex} 가 {table.get(fr)} 에서 아무 항목도 못 지웠다")
        if t.get("identity_note"):
            text += " " + " ".join(str(t["identity_note"]).split())
        return text
    identity = identity_for(variation["framing"]["key"])
    eff = load("effects.yaml")
    # Before 강도 ↔ After 효과 짝 (mild+눈에 띄게 = 과장, marked+은은 = 효과 없음). 나이 하향 **뒤**의 sev 로 뽑는다
    levels = (t.get("effect_by_severity") or {}).get(sev) or t.get("effect_levels", ["moderate"])
    if mode == "clinical":
        # 임상은 비교했을 때 변화가 보여야 한다 (위 mild 제외와 한 짝). 나이 하향으로 mild 가 된 20대는
        #   effect_by_severity 가 subtle 뿐이라, 그때는 시술 전체 effect_levels 에서 subtle 을 뺀 것으로 간다 —
        #   '연한 팔자가 또렷이 옅어짐'은 기록 사진에서 과장이 아니라 정상 범위다 (2026-09-15 저녁 결정).
        levels = [l for l in levels if l != "subtle"] or [l for l in t.get("effect_levels", ["moderate"]) if l != "subtle"] or list(levels)
    level = rng.choice(list(levels))
    pts = series_points(treatment, series)               # 경과 시리즈(직후·2주…)면 시점 목록, 아니면 빈 목록
    when = pts[-1] if pts else rng.choice(t.get("timeline", ["2w"]))
    _fw = experiment_flags()["when"]                  # 실험 스위치 — 단발 시점 고정(추첨은 이미 한 번 소비했다)
    if _fw and not pts and _fw in t.get("timeline", ["2w"]):
        when = _fw

    def change_for(w, final_level):
        """시점 하나의 시술 지시문. 시리즈면 최종 강도를 시점에 맞춰 낮춘다(직후 = 거의 안 보임 + 붓기).

        `lowered` 를 같이 돌려주는 이유(2026-09-11): 검수의 `effect_visible` 은 "변화가 눈에 띄나"를
        묻는데, 여기서 강도를 낮춘 컷은 **안 띄는 게 정상**이라 같은 자로 재면 지시대로 그릴수록
        떨어진다. 그 판정을 검수 쪽에서 다시 계산하면 규칙이 두 벌이 되어 조용히 갈리므로,
        **낮췄다는 사실을 만든 자리에서 그대로 실어 보낸다**(배치가 이걸 읽어 그 항목을 안 건다).
        """
        lv = final_level
        lowered = False
        if pts:
            # 시점별 강도 = 전역 표(effects.yaml) → 시술별 재정의(treatments.yaml `series_levels`) 순.
            # 2026-09-11 B안: 필러는 "효과 약 3일 후"(여신티켓 3건 실측)라 1주 컷도 최종 강도다.
            #   ⚠ 재정의를 직후 한 칸만 두면 **1주가 직후보다 약해지는 역전**이 생긴다
            #     (직후=final · 1주=subtle · 2주=final — 중간이 꺼진다). 그래서 칸이 아니라 표를 덮는다.
            sl = str(((t.get("series_levels") or {}).get(w)) or (eff.get("series_levels") or {}).get(w, "final"))
            lowered = sl != "final"
            lv = final_level if sl == "final" else sl
        # 직후이고 강도를 낮췄고 사실 카드가 있으면 after_change 를 뺀다 (2026-09-14 저녁 엠보 직후):
        #   "hydrated with a natural glow" 와 카드의 "matte with no glow yet" 이 한 문장 건너 싸운다.
        #   무엇이 보이는지는 카드가, '아직 결과가 아니다'는 early 문장이 말한다. 최종 강도 직후(필러)는 종전대로.
        card = w == "immediate" and lowered and any((t.get("facts") or {}).get(k) for k in FACT_KEYS_PROMPT)
        c = f'{eff["effect_levels"][lv]}.' if card else f'{t["after_change"].strip()} {eff["effect_levels"][lv]}.'
        if t.get("must_not_change"):
            c += " " + " ".join(str(t["must_not_change"]).split())
        if w == "immediate":
            # 직후 흔적·금지는 **사실 카드**에서 온다(시술마다 무엇이 어디에 남는지가 다르다).
            # 두 모드 공통 자리다 — 임상 프롬프트엔 after_day/skin_state 가 아예 안 붙어서,
            # 여기 말고 mode_extra 쪽에 넣으면 임상 직후 컷만 조용히 사실 카드를 못 받는다.
            marks = [(t.get("facts") or {}).get(k) for k in FACT_KEYS_PROMPT]
            if not any(marks) and not lowered:
                # 카드가 아직 없는 필러 — 최종 강도로 그리면서 직후 티가 하나도 없으면 "2주 컷"과 구별이 안 된다.
                # 시술별 흔적은 추정할 수 없으니(테이프 자리는 시술마다 다르다) 주사 공통인 붓기·발적만 얹는다.
                marks = [eff.get("immediate_final_note")]
            for v in marks:
                if v:
                    c += " " + " ".join(str(v).split())
        elif mode == "selfie":
            # 직후가 아닌 셀카 After — '후'의 기준을 실사 한 장으로 못박은 칸(엠보 7일차).
            # after_change 가 *무엇이 좋아지나*를 말하면, 이 칸은 *그 피부가 어떻게 보이나*를 말한다.
            for v in [(t.get("facts") or {}).get(k) for k in FACT_KEYS_AFTER]:
                if v:
                    c += " " + " ".join(str(v).split())
        if mode == "selfie":
            c += f' {eff["timeline"][w].capitalize()}.'
        return c, lv, lowered

    change, _lv, _low = change_for(when, level)
    variation = {**variation, "before_severity": {"key": sev, "text": str(cond).strip()},
                 "effect_level": {"key": level, "text": eff["effect_levels"][level]},
                 "timeline": {"key": when, "text": eff["timeline"][when]}}
    mx = load("prompts/mode_extra.yaml")

    def fact_spans(w):
        """그 컷에 실린 사실 카드 문장 — 화면에서 '이 문장 어디서 왔나'가 template 로 뭉개지지 않게 칸을 준다."""
        f = t.get("facts") or {}
        keys = FACT_KEYS_PROMPT if w == "immediate" else (FACT_KEYS_AFTER if mode == "selfie" else ())
        return [("facts", " ".join(str(f[k]).split())) for k in keys if f.get(k)]

    series_seen = {}            # 시리즈 컷들이 이미 쓴 값 {축: {키…}} — drift_after 의 seen (2026-09-18)

    def build_after(w, chg, lv, lowered):
        """시점 하나의 After. 시리즈든 아니든 같은 길 — 동일인 기준은 항상 Before 사진이다(After 를 다음 After 의 기준으로 쓰면 얼굴이 흘러간다)."""
        # 금지문은 컷마다 다르다(not_at). 직후 컷은 카드가 흔적을 그리라고 하므로 흔적 금지가 빠진다.
        lines_w = after_lines_at(w)
        avoid_after = lessons.avoid_text(lines_w)
        check_avoid_vs_facts(treatment, w, [s for _k, s in fact_spans(w)], lines_w)
        if mode == "clinical":
            a_var = variation
            # 다시 찍기 규정 (2026-09-15 v1): 같은 부스·같은 배경·같은 조명이되 **따로 찍은 사진**.
            #   직후 = 같은 날(옷·머리 같음), 1주 이후 = 다른 날(옷 다름, 머리 대략 같음). 두 시점 공통으로
            #   micro_drift 가 머리 위치 몇 mm·잔머리·미세 주름·노출의 '살짝 다름'을 **요구**한다 — 종전
            #   "Keep identical framing, head position, expression, headband, gown…" 은 복사본을 시켰다.
            retake = " ".join(str(rig["retake"]["same_day" if w == "immediate" else "different_day"]).split())
            micro = " ".join(str(rig["micro_drift"]).split())
            txt = (CFG / "prompts/after_clinical.md").read_text(encoding="utf-8").format(
                identity_lock=identity, retake=retake, micro_drift=micro, after_change=chg, avoid=avoid_after)
            spans = [("identity", identity), ("retake", retake), ("drift", micro), ("change", t["after_change"]),
                     ("effect", eff["effect_levels"][lv]), ("must_not", t.get("must_not_change") or "")] + fact_spans(w) + [("avoid", avoid_after)]
        else:
            a_var = drift_after(variation, mode, rng, timeline=w, treatment=treatment, series=bool(pts),
                                seen=series_seen)
            # 앞 시점이 쓴 값을 기록한다 — 다음 시점이 그걸 피해야 '세 장이 서로도 다른' 시리즈가 된다.
            for _ax in (tr.get("series_relax") or []):
                if _ax in a_var:
                    series_seen.setdefault(_ax, set()).add(a_var[_ax]["key"])
            a = {k: val["text"] for k, val in a_var.items()}
            ident = identity_for(variation["framing"]["key"], a_var["framing"]["key"])
            a_scene = dict(a); a_scene.pop("expression", None)          # 표정은 아래 expression_line 이 맡는다
            after_scene = selfie_scene(a_scene)
            after_hair = f'{a["hair_color"]}, {a["hair_style"]}' + (f', {a["extras"]}' if a["extras"] else "")
            if tr.get("expression_policy") == "lock":
                # ⚠ "must not change at all" 은 표정만이 아니라 얼굴 전체를 복사시켰다
                #   (2026-09-10 성연서님 "동일한 각도, 구도, 표정" 2장 — 이목구비·눈 뜬 정도까지 동일 = AI 티).
                #   잠글 것은 '웃음'이지 '사람'이 아니다 → 금지는 표정 하나로 좁히고,
                #   손으로 다시 찍었을 때 반드시 생기는 미세 차이는 **명시적으로 요구**한다.
                #   이 문장은 drift_lock 에 angle 이 들어간 시술(팔자·리프팅)에서 특히 중요하다 —
                #   각도 축이 잠기면 각도 문장까지 같아져 "같은 사진 복사"로 떨어진다.
                #   2026-09-11 오후 성연서님 "카메라 각도나 얼굴 각도도 너무 다 똑같아, 로봇이야" →
                #   문장을 **팔을 다시 들었다는 사실**부터 말하게 고쳤다. 종전은 '몇 도 다르게'라는
                #   *정도* 만 말해서, 각도 축이 잠긴 시술에선 모델이 같은 프레임을 그대로 복사했다.
                #   ⚠ 각도 축 자체는 여전히 잠근다 — 각도가 바뀌면 주름 그림자가 달라져 촬영 차이가
                #     시술 효과로 둔갑한다. 푸는 건 '몇 도'이지 '어느 각도'가 아니다.
                # ⚠ 2026-09-18 (연서님 검수 ③ "표정·입모양·구도·카메라 각도가 똑같다"): 종전 첫 문장은
                #   "The expression is the same as in the reference: …" 였다. 바로 뒤 RESHOT_LINE 이
                #   "포즈·시선·입모양을 베끼지 마라"라고 말하니 **한 프롬프트가 서로 반대를 지시**했고,
                #   참조 이미지를 같이 넘기는 구조에서 모델은 늘 복사 쪽을 골랐다(09-17 6세트 전수).
                #   → 뽑힌 표정을 그대로 서술하고(시리즈면 컷마다 다르다 — series_relax), 지킬 것은
                #   '웃음·입꼬리 당김 금지' 하나로 좁힌다. 같은 표정이 뽑힌 회차에도 모순이 없다.
                # 미모 프로필 3차: Before 가 살짝 웃는 컷이면 "웃지 마라"가 곧 가짜 효과다(웃음이 빠지면 팔자가 저절로 얕아진다)
                #   → 같은 웃음을 같은 세기로 유지하라고 바꾼다. 표정 축은 lock_after 로 이미 잠겨 있다.
                smile_held = (variation["expression"]["key"] == "slight_smile"
                              and "expression" in (looks_profile(variation["looks"]["key"]).get("lock_after") or []))
                keep_mouth = ('Keep exactly the same slight closed-mouth smile as in the reference, with the same '
                              'intensity - do not make it bigger or smaller and do not drop it, since changing the '
                              'smile alone would change the folds being treated. ' if smile_held else
                              'Do not smile and do not tense or lift the corners of the mouth or the cheeks, since that '
                              'alone would change the folds being treated. ')
                expression_line = (
                    f'Expression in this photo: {a["expression"]}. ' + keep_mouth + RESHOT_HELD +
                    'These differences must be visible at a glance when the two photos sit side by side, while '
                    'still reading as the same pose.')
            else:
                # ⚠ 2026-09-14 오후 (연서님 "표정·입 벌림·눈 뜬 정도가 어떻게 딱 떨어지게 똑같지?").
                #   종전 이 줄은 `it may differ slightly from the reference.` 한 마디였다 — **복제를 막는
                #   문장이 하나도 없었다**. 참조 사진(Before)을 통째로 입력으로 넘기므로, 문장이 침묵하면
                #   모델은 포즈·눈 뜬 정도·입 벌림까지 그대로 베낀다(0914 실측: 표정 축은 70% 확률로
                #   다시 뽑히는데 결과 사진은 같았다 — 설정이 아니라 프롬프트가 진 것이다).
                #   ⚠ 같은 지적을 09-10·09-11 에 이미 받아 고쳤는데 그 교정이 **lock 갈래에만** 들어갔다.
                #     표정이 자유인 시술이 오히려 방어를 못 받는 거울상이었다 → 공통 문장(RESHOT_LINE)으로 합친다.
                expression_line = (f'Expression: {a["expression"]}, clearly different from the reference. '
                                   + RESHOT_LINE)
            which = "same" if w == "immediate" else "different"
            # After 본문도 **After 의** 프레이밍으로 고른다 — 이웃 이동으로 얼굴 전체 ↔ 바스트가 바뀔 수 있다.
            _saf = mx.get("selfie_after_by_framing") or {}
            selfie_after = " ".join(str(_saf.get(a_var["framing"]["key"], mx.get("selfie_after", ""))).split())
            # ── 마감(after_finish): '피부가 빛을 어떻게 받는가' (2026-09-14 밤 연서님 "후 사진은 광이 좀 더
            #    돌아야 하는데 매트한 느낌이 든다"). 시술마다 다른 값이라 treatments.yaml 에 두고, 없으면 빈 칸이다.
            #    ⚠ 여기가 필요한 이유: After 프롬프트에 매트 쪽 압력이 **세 곳**(참조로 넘기는 Before 의 무광
            #      문장 · skin_state 의 '부위 밖 리터칭 금지' · 끝줄의 '보정 금지')인데 광을 요구하는 말은
            #      0914 실측에서 엠보 after_change 의 `natural glow` 한 마디뿐이었고 모공·홍조는 아예 없었다.
            #      after_change 에 욱여넣지 않는 이유는 그 칸이 '무엇이 좋아졌나'(효과 강도와 짝)라서다 —
            #      마감은 강도를 안 올리고 빛만 바꾼다(과장 방지).
            #    ⚠ 직후 컷엔 안 붙인다 (2026-09-14 저녁 연서님 "엠보는 직후가 다이나믹"): 직후는 볼록·홍조가
            #      보이는 시점이라 광이 돌면 4주 컷과 섞인다. 흔적은 facts.immediate_marks 가 그린다.
            finish = "" if w == "immediate" else " ".join(str(t.get("after_finish") or "").split())
            txt = (CFG / "prompts/after_selfie.md").read_text(encoding="utf-8").format(
                identity_lock=ident, after_scene=after_scene, after_hair=after_hair, after_change=chg,
                after_finish=finish, relight=RELIGHT_LINE,
                expression_line=expression_line, mode_extra=selfie_after,
                after_day=mx["after_day"][which].strip(), skin_state=mx["skin_state"][which].strip(), avoid=avoid_after)
            spans = [("identity", ident), ("change", t["after_change"]), ("effect", eff["effect_levels"][lv]),
                     ("must_not", t.get("must_not_change") or ""), ("finish", finish)] + fact_spans(w) + [("avoid", avoid_after),
                     ("day", mx["after_day"][which]), ("scene", after_scene), ("scene", RELIGHT_LINE),
                     ("scene", f"Hair: {after_hair}."), ("expression", expression_line),
                     ("skin", mx["skin_state"][which]), ("timeline", eff["timeline"][w].capitalize()), ("mode_extra", selfie_after)]
        # ── effect_visible 을 탈락 사유로 쓰지 않는 컷 (2026-09-18) ────────────────────────────
        # 종전 규칙은 '강도를 낮춘 컷'만 면제였다(09-11): 프롬프트가 "거의 안 보이게" 시켜 놓고 검수가
        # "눈에 띄어야 한다"로 재면 지시를 지킬수록 떨어진다. **직후 컷도 같은 모양인데 면제가 없었다** —
        # 필러 직후는 최종 강도(면제 아님)인데 프롬프트가 흔적(투명 패치)과 "주름이 살짝 붓는다"를 같이
        # 시키므로, 심사는 "동그란 자국은 보이지만 분명한 개선은 없다"고 읽는다.
        #   09-18 실측(배치 20260918-084112-2fae): 직후 4컷 전부 effect_visible 3.0 으로 탈락,
        #   같은 세트의 2주 컷은 8.0 통과. 재시도가 원리적으로 무의미한 자리에서 3회차까지 돌았다.
        # → 시리즈에서 **직후 컷은 계측만** 하고(meta 에 점수는 그대로 남는다) 효과 판정은 가라앉은 뒤
        #   컷이 한다. ⚠ 시리즈가 아닐 때(직후 한 장짜리)는 면제하지 않는다 — 그 세트엔 효과를 볼
        #   다른 컷이 없어서, 면제하면 아무도 효과를 안 보게 된다.
        ungated = lowered or (bool(pts) and w == "immediate")
        # 직후 패치 위치 게이트 횟수 (2026-09-18 C안) — 배치가 시점 이름을 다시 보지 않게 여기서 실어 보낸다(규칙 두 벌 금지).
        pgate = int(t.get("patch_gate") or 0) if w == "immediate" else 0
        return {"when": w, "effect_level": lv, "effect_lowered": lowered, "effect_ungated": ungated, "patch_gate": pgate,
                "after_prompt": " ".join(txt.split()), "after_variation": a_var,
                "after_changed_axes": [k for k in a_var if a_var[k]["key"] != variation[k]["key"]], "after_parts": segments(txt, spans)}

    afters = []
    for w in (pts or [when]):
        chg, lv, lowered = change_for(w, level)
        afters.append(build_after(w, chg, lv, lowered))
    last = afters[-1]
    before_parts = segments(before, [("person", person_description(variation)), ("before_condition", cond), ("scene", scene),
                                     ("mode_extra", mode_extra), ("skin_read", skin_read), ("avoid", avoid_before)])
    # ⚠ `avoid_applied` 는 "그 사진에 실제로 붙어 있던 금지문"이고 메모 초안(notedraft)이 정본으로 읽는다.
    #   after_prompt·after_parts 가 마지막 컷이므로 여기도 **마지막 컷에 붙은 목록**이어야 짝이 맞는다 —
    #   전체 목록을 적으면 직후 컷에서 빠진 규칙을 "이미 붙여 봤다"고 보고해 같은 규칙을 또 승격시킨다.
    applied = {k: list(v) for k, v in (avoid or {}).items() if v}
    if applied.get("after"):
        applied["after"] = after_lines_at(last["when"])
    return {"avoid_applied": {k: v for k, v in applied.items() if v},
            "before_parts": before_parts, "after_parts": last["after_parts"],
            "treatment": treatment, "mode": mode, "aspect": load("variations.yaml").get("output", {}).get("aspect", "4:5"),
            "variation": variation, "after_variation": last["after_variation"],
            "after_changed_axes": last["after_changed_axes"], "generation": "edit" if mode == "clinical" else "identity_reference",
            "series": pts or None, "afters": afters,          # 시리즈면 시점별 After 목록(배치·화면이 이걸 돈다). after_* 는 마지막 시점
            "before_prompt": " ".join(before.split()), "after_prompt": last["after_prompt"],
            "experiment": experiment_flags(as_meta=True)}          # 켠 실험 스위치(없으면 None) — 회차 비교 때 갈라 읽는다
