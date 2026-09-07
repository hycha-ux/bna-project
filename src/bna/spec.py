"""변주 샘플링 + 프롬프트 조립. API 키 없이도 동작 (dry-run)."""
import random
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config"


def load(name):
    return yaml.safe_load((CFG / name).read_text(encoding="utf-8"))


PERSON_AXES = ["country", "age", "gender", "face_shape", "skin_tone", "skin_condition", "body_type",
               "hair_style", "hair_color", "eyes", "extras"]
SCENE_AXES = ["background", "angle", "framing", "context", "lighting", "color", "quality"]


def person_description(variation: dict) -> str:
    f = {k: variation[k]["text"] for k in PERSON_AXES}
    parts = [f"{f['country']} {f['gender']} {f['age']}", f["face_shape"], f["skin_tone"], f["skin_condition"],
             f["body_type"], f"{f['hair_color']}, {f['hair_style']}", f["eyes"], f["extras"]]
    return ", ".join(p for p in parts if p)


def selfie_scene(f: dict) -> str:
    """셀카 장면 문장: 프레이밍 → 각도 → 배경/맥락 → 빛 → 색/화질."""
    ctx = f", {f['context']}" if f.get("context") else ""
    return (f'{f["framing"].capitalize()}. {f["angle"]}, {f["background"]}{ctx}. '
            f'{f["lighting"]}. {f["color"]}. {f["quality"]}.')


def sample_variation(mode: str, seed=None) -> dict:
    rng = random.Random(seed)
    v = load("variations.yaml")
    rules = v.get("mode_rules", {}).get(mode, {})
    picked = {}
    compat = v.get("background_lighting", {})
    excl = v.get("gender_exclusions", {})
    for axis in PERSON_AXES + SCENE_AXES:
        options = v[axis]
        allowed = rules.get(axis) or list(options)
        if axis == "lighting" and picked["background"]["key"] in compat:
            allowed = [k for k in allowed if k in compat[picked["background"]["key"]]] or allowed
        if "gender" in picked:
            banned = excl.get(picked["gender"]["key"], {}).get(axis, [])
            allowed = [k for k in allowed if k not in banned] or allowed
        key = rng.choice(allowed)
        picked[axis] = {"key": key, "text": options[key]}
    return picked


def drift_after(variation: dict, mode: str, rng, timeline: str = "2w") -> dict:
    """셀카 모드: After 촬영 상황을 확률적으로 바꾼다 (이목구비 축은 절대 건드리지 않음).
    timeline 이 immediate 면 같은 날(옷·머리 고정), 그 외는 다른 날(옷·머리·배경 대부분 교체)."""
    v = load("variations.yaml")
    probs = v.get("after_drift", {}).get(mode, {})
    if "immediate" in probs or "later" in probs:
        probs = probs.get("immediate" if timeline == "immediate" else "later", {})
    override = v.get("after_immediate", {}).get(mode, {}) if timeline == "immediate" else {}
    rules = v.get("mode_rules", {}).get(mode, {})           # After 도 모드 화이트리스트 안에서만 (셀카→병원벽 드리프트 버그 수정)
    compat, excl = v.get("background_lighting", {}), v.get("gender_exclusions", {})
    after = {k: dict(val) for k, val in variation.items()}
    banned = excl.get(variation["gender"]["key"], {})
    for axis, p in probs.items():
        if rng.random() >= p:
            continue
        allowed = override.get(axis) or rules.get(axis) or list(v[axis])
        if axis == "angle":                                 # 각도는 이웃 각도로만 (비슷하되 동일하지 않게)
            nb = v.get("angle_neighbors", {}).get(variation["angle"]["key"])
            allowed = [k for k in allowed if k in nb] or allowed if nb else allowed
        opts = [k for k in allowed if k != variation[axis]["key"] and k not in banned.get(axis, [])]
        if axis == "lighting" and after["background"]["key"] in compat:
            opts = [k for k in opts if k in compat[after["background"]["key"]]] or opts
        if opts:
            k = rng.choice(opts); after[axis] = {"key": k, "text": v[axis][k]}
    if after["background"]["key"] in compat and after["lighting"]["key"] not in compat[after["background"]["key"]]:
        pool = [k for k in compat[after["background"]["key"]] if k in (rules.get("lighting") or v["lighting"])] or compat[after["background"]["key"]]
        k = rng.choice(pool); after["lighting"] = {"key": k, "text": v["lighting"][k]}
    return after


def build_prompts(treatment: str, mode: str, variation: dict, seed=None) -> dict:
    t = load("treatments.yaml")[treatment]
    if mode not in t["modes"]:
        raise ValueError(f"{treatment} does not support mode {mode}")
    rng = random.Random(seed)
    mode_extra = load("prompts/mode_extra.yaml")[mode].strip()
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
        person=person_description(variation), before_condition=str(cond).strip(), scene=scene, mode_extra=mode_extra, **fields)
    identity = (CFG / "prompts/identity_lock.md").read_text(encoding="utf-8").strip()
    eff = load("effects.yaml")
    level = rng.choice(t.get("effect_levels", ["moderate"]))
    when = rng.choice(t.get("timeline", ["2w"]))
    change = f'{t["after_change"].strip()} {eff["effect_levels"][level]}.'
    if mode == "selfie":
        change += f' {eff["timeline"][when].capitalize()}.'
    variation = {**variation, "before_severity": {"key": sev, "text": str(cond).strip()},
                 "effect_level": {"key": level, "text": eff["effect_levels"][level]},
                 "timeline": {"key": when, "text": eff["timeline"][when]}}
    if mode == "clinical":
        after_var = variation
        after = (CFG / "prompts/after_clinical.md").read_text(encoding="utf-8").format(identity_lock=identity, after_change=change)
    else:
        after_var = drift_after(variation, mode, rng, timeline=when)
        a = {k: val["text"] for k, val in after_var.items()}
        after_scene = selfie_scene(a)
        after_hair = f'{a["hair_color"]}, {a["hair_style"]}' + (f', {a["extras"]}' if a["extras"] else "")
        mx = load("prompts/mode_extra.yaml"); which = "same" if when == "immediate" else "different"
        after = (CFG / "prompts/after_selfie.md").read_text(encoding="utf-8").format(
            identity_lock=identity, after_scene=after_scene, after_hair=after_hair, after_change=change,
            after_day=mx["after_day"][which].strip(), skin_state=mx["skin_state"][which].strip())
    changed = [k for k in after_var if after_var[k]["key"] != variation[k]["key"]]
    return {"treatment": treatment, "mode": mode, "aspect": load("variations.yaml").get("output", {}).get("aspect", "4:5"),
            "variation": variation, "after_variation": after_var,
            "after_changed_axes": changed, "generation": "edit" if mode == "clinical" else "identity_reference",
            "before_prompt": " ".join(before.split()), "after_prompt": " ".join(after.split())}
