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
               "hair_style", "hair_color", "eyes", "extras"]
SCENE_AXES = ["background", "angle", "framing", "context", "lighting", "color", "quality", "expression"]


def treatment_rules(treatment: str, mode: str) -> dict:
    """시술별 조건 제약 (treatments.yaml 의 구조 필드) → 추첨·드리프트가 같이 쓰는 한 뭉치.
    allow  : {축: 허용값} — 모드 화이트리스트와 교집합 (framing_allow · scene_allow)
    ban    : {축: 금지값} — context_ban
    framing_ban_by_angle · age_weights(0 = 그 나이 안 뽑음) · drift_lock · expression_policy
    treatment 이 None 이면 빈 규칙 (예전 호출·테스트가 그대로 돈다)."""
    r = {"allow": {}, "ban": {}, "age_weights": {}, "drift_lock": [], "framing_ban_by_angle": {}, "expression_policy": "free"}
    if not treatment:
        return r
    t = load("treatments.yaml").get(treatment)
    if t is None:
        raise ValueError(f"treatments.yaml 에 {treatment} 가 없다")
    r["age_weights"] = {str(k): float(v) for k, v in (t.get("age_weights") or {}).items()}
    r["drift_lock"] = list(t.get("drift_lock") or [])
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
    return r


def allowed_values(axis: str, keys: dict, mode: str, v: dict, tr: dict, base=None) -> list:
    """한 축의 허용 목록. 순서대로 거른다:
    모드 화이트리스트(또는 base) → 시술 허용/금지 → 성별 제외 → 나이 0 가중 → 배경×조명 → 각도×프레이밍 → 배경×맥락·프레이밍×맥락.
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
    if axis == "lighting":
        compat = v.get("background_lighting", {}).get(keys.get("background"))
        if compat:
            allowed = [k for k in allowed if k in compat] or allowed
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


def person_description(variation: dict) -> str:
    f = {k: variation[k]["text"] for k in PERSON_AXES}
    parts = [f"{f['country']} {f['gender']} {f['age']}", f["face_shape"], f["skin_tone"], f["skin_condition"],
             f["body_type"], f"{f['hair_color']}, {f['hair_style']}", f["eyes"], f["extras"]]
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
    for axis in PERSON_AXES + SCENE_AXES:
        options = v[axis]
        allowed = allowed_values(axis, keys, mode, v, tr)
        w = dict(weights.get(axis) or {})
        if axis == "age":                                # 시술별 나이 가중 (0 은 이미 allowed 에서 빠졌다)
            for k, aw in tr.get("age_weights", {}).items():
                if aw > 0:
                    w[k] = w.get(k, 1.0) * aw
        if w and len(allowed) > 1:
            ws = [max(0.01, float(w.get(k, 1.0))) for k in allowed]
            key = rng.choices(allowed, weights=ws, k=1)[0]
        else:
            key = rng.choice(allowed)
        picked[axis] = {"key": key, "text": options[key]}; keys[axis] = key
    return picked


def drift_after(variation: dict, mode: str, rng, timeline: str = "2w", treatment=None) -> dict:
    """셀카 모드: After 촬영 상황을 확률적으로 바꾼다 (이목구비 축은 절대 건드리지 않음).
    timeline 이 immediate 면 같은 날(옷·머리 고정), 그 외는 다른 날(옷·머리·배경 대부분 교체).
    treatment 의 drift_lock 축(표정·각도·화질…)은 건너뛴다 — 그 축이 바뀌면 시술이 아니라 촬영 차이가 B&A 로 둔갑한다."""
    v = load("variations.yaml")
    tr = treatment_rules(treatment, mode)
    lock = set(tr.get("drift_lock") or [])
    probs = v.get("after_drift", {}).get(mode, {})
    if "immediate" in probs or "later" in probs:
        probs = probs.get("immediate" if timeline == "immediate" else "later", {})
    override = v.get("after_immediate", {}).get(mode, {}) if timeline == "immediate" else {}
    after = {k: dict(val) for k, val in variation.items()}
    keys = {k: val["key"] for k, val in after.items()}
    for axis, p in probs.items():
        if axis in lock or axis not in v or rng.random() >= p:
            continue
        allowed = allowed_values(axis, keys, mode, v, tr, base=override.get(axis))
        if axis == "angle":                                 # 각도는 이웃 각도로만 (비슷하되 동일하지 않게)
            nb = v.get("angle_neighbors", {}).get(variation["angle"]["key"])
            if nb:
                allowed = [k for k in allowed if k in nb] or allowed
        if axis == "hair_style":                            # 머리는 2주 안에 될 수 있는 모양으로만 (포니테일→삭발 금지)
            nb = v.get("hair_style_neighbors", {}).get(variation["hair_style"]["key"])
            if nb is not None:
                allowed = [k for k in allowed if k in nb]   # 빈 목록이면 안 바뀐다
        opts = [k for k in allowed if k != variation[axis]["key"]]
        if opts:
            k = rng.choice(opts); after[axis] = {"key": k, "text": v[axis][k]}; keys[axis] = k
    # 배경이 바뀌었으면 조명·맥락이 새 배경(과 프레이밍)에 맞는지 마지막으로 한 번 더 확인
    for axis in ("lighting", "context"):
        if axis in lock:
            continue
        ok = allowed_values(axis, keys, mode, v, tr, base=override.get(axis))
        if keys[axis] not in ok:
            k = rng.choice(ok); after[axis] = {"key": k, "text": v[axis][k]}; keys[axis] = k
    return after


def build_prompts(treatment: str, mode: str, variation: dict, seed=None, avoid=None) -> dict:
    """avoid: {"before": [...], "after": [...]} — 제외 사유에서 배운 금지문(lessons.active).
    None 이면 붙이지 않는다(dry-run·테스트가 과거와 같은 문장을 내게)."""
    from . import lessons
    av = avoid or {}
    avoid_before = lessons.avoid_text(av.get("before") or [])
    avoid_after = lessons.avoid_text(av.get("after") or [])
    t = load("treatments.yaml")[treatment]
    if mode not in t["modes"]:
        raise ValueError(f"{treatment} does not support mode {mode}")
    rng = random.Random(seed)
    mode_extra = load("prompts/mode_extra.yaml")[mode].strip()
    if "expression" not in variation:                # 예전 계획(표정 축 없던 시절)도 조립되게
        ek = "neutral_closed"; variation = {**variation, "expression": {"key": ek, "text": load("variations.yaml")["expression"][ek]}}
    tr = treatment_rules(treatment, mode)
    fields = {k: v["text"] for k, v in variation.items()}
    if mode == "clinical":
        rig = load("clinical_rig.yaml")
        r = rig["rig_default"]
        angle = rig["angles"].get({"front": "front", "three_quarter": "oblique_45", "side": "side"}.get(variation["angle"]["key"], "front"))
        scene = ". ".join([angle, r["camera"], r["distance"], r["lighting"], r["background"], r["subject_setup"], r["processing"]]) + "."
    else:
        scene = selfie_scene(fields)
    sevs = t.get("before_severity", ["moderate"])
    sev = rng.choice(sevs)
    min_age = t.get("severity_min_age", {})
    if min_age:                                   # 인물 나이가 강도 최소 나이보다 어리면 한 단계씩 낮춤
        order = list(load("variations.yaml")["age"])
        age_i = order.index(variation["age"]["key"])
        while sev in min_age and age_i < order.index(min_age[sev]) and sevs.index(sev) > 0:
            sev = sevs[sevs.index(sev) - 1]
    cond = t.get("before_condition", {})
    cond = cond.get(sev, "") if isinstance(cond, dict) else cond
    before = (CFG / "prompts/before.md").read_text(encoding="utf-8").format(
        person=person_description(variation), before_condition=str(cond).strip(), scene=scene, mode_extra=mode_extra, avoid=avoid_before, **fields)
    identity = (CFG / "prompts/identity_lock.md").read_text(encoding="utf-8").strip()
    for ph in t.get("identity_exempt") or []:            # 시술 부위는 잠금에서 뺀다 (코 필러에 "same nose shape" 은 모순)
        identity = identity.replace(ph + ", ", "").replace(", " + ph, "").replace(ph, "")
    if t.get("identity_note"):
        identity += " " + " ".join(str(t["identity_note"]).split())
    eff = load("effects.yaml")
    # Before 강도 ↔ After 효과 짝 (mild+눈에 띄게 = 과장, marked+은은 = 효과 없음). 나이 하향 **뒤**의 sev 로 뽑는다
    levels = (t.get("effect_by_severity") or {}).get(sev) or t.get("effect_levels", ["moderate"])
    level = rng.choice(list(levels))
    when = rng.choice(t.get("timeline", ["2w"]))
    change = f'{t["after_change"].strip()} {eff["effect_levels"][level]}.'
    if t.get("must_not_change"):
        change += " " + " ".join(str(t["must_not_change"]).split())
    if mode == "selfie":
        change += f' {eff["timeline"][when].capitalize()}.'
    variation = {**variation, "before_severity": {"key": sev, "text": str(cond).strip()},
                 "effect_level": {"key": level, "text": eff["effect_levels"][level]},
                 "timeline": {"key": when, "text": eff["timeline"][when]}}
    if mode == "clinical":
        after_var = variation
        after = (CFG / "prompts/after_clinical.md").read_text(encoding="utf-8").format(identity_lock=identity, after_change=change, avoid=avoid_after)
    else:
        after_var = drift_after(variation, mode, rng, timeline=when, treatment=treatment)
        a = {k: val["text"] for k, val in after_var.items()}
        a_scene = dict(a); a_scene.pop("expression", None)          # 표정은 아래 expression_line 이 맡는다
        after_scene = selfie_scene(a_scene)
        after_hair = f'{a["hair_color"]}, {a["hair_style"]}' + (f', {a["extras"]}' if a["extras"] else "")
        if tr.get("expression_policy") == "lock":
            expression_line = f'Identical expression to the reference: {variation["expression"]["text"]}. The expression must not change at all between the two photos.'
        else:
            expression_line = f'Expression: {a["expression"]}; it may differ slightly from the reference.'
        mx = load("prompts/mode_extra.yaml"); which = "same" if when == "immediate" else "different"
        after = (CFG / "prompts/after_selfie.md").read_text(encoding="utf-8").format(
            identity_lock=identity, after_scene=after_scene, after_hair=after_hair, after_change=change,
            expression_line=expression_line, mode_extra=str(mx.get("selfie_after", "")).strip(),
            after_day=mx["after_day"][which].strip(), skin_state=mx["skin_state"][which].strip(), avoid=avoid_after)
    changed = [k for k in after_var if after_var[k]["key"] != variation[k]["key"]]
    return {"avoid_applied": {k: v for k, v in (avoid or {}).items() if v},
            "treatment": treatment, "mode": mode, "aspect": load("variations.yaml").get("output", {}).get("aspect", "4:5"),
            "variation": variation, "after_variation": after_var,
            "after_changed_axes": changed, "generation": "edit" if mode == "clinical" else "identity_reference",
            "before_prompt": " ".join(before.split()), "after_prompt": " ".join(after.split())}
