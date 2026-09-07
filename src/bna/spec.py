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
SCENE_AXES = ["background", "angle", "lighting", "color", "quality"]


def person_description(variation: dict) -> str:
    f = {k: variation[k]["text"] for k in PERSON_AXES}
    parts = [f"{f['country']} {f['gender']} {f['age']}", f["face_shape"], f["skin_tone"], f["skin_condition"],
             f["body_type"], f"{f['hair_color']}, {f['hair_style']}", f["eyes"], f["extras"]]
    return ", ".join(p for p in parts if p)


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


def drift_after(variation: dict, mode: str, rng) -> dict:
    """셀카 모드: After 촬영 상황을 확률적으로 바꾼다 (이목구비 축은 절대 건드리지 않음)."""
    v = load("variations.yaml")
    probs = v.get("after_drift", {}).get(mode, {})
    compat, excl = v.get("background_lighting", {}), v.get("gender_exclusions", {})
    after = {k: dict(val) for k, val in variation.items()}
    banned = excl.get(variation["gender"]["key"], {})
    for axis, p in probs.items():
        if rng.random() >= p:
            continue
        opts = [k for k in v[axis] if k != variation[axis]["key"] and k not in banned.get(axis, [])]
        if axis == "lighting" and after["background"]["key"] in compat:
            opts = [k for k in opts if k in compat[after["background"]["key"]]] or opts
        if opts:
            k = rng.choice(opts); after[axis] = {"key": k, "text": v[axis][k]}
    if after["background"]["key"] in compat and after["lighting"]["key"] not in compat[after["background"]["key"]]:
        k = rng.choice(compat[after["background"]["key"]]); after["lighting"] = {"key": k, "text": v["lighting"][k]}
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
        scene = f'{fields["angle"]}, {fields["background"]}. {fields["lighting"]}. {fields["color"]}. {fields["quality"]}.'
    before = (CFG / "prompts/before.md").read_text(encoding="utf-8").format(
        person=person_description(variation), scene=scene, mode_extra=mode_extra, **fields)
    identity = (CFG / "prompts/identity_lock.md").read_text(encoding="utf-8").strip()
    eff = load("effects.yaml")
    level = rng.choice(t.get("effect_levels", ["moderate"]))
    when = rng.choice(t.get("timeline", ["2w"]))
    change = f'{t["after_change"].strip()} {eff["effect_levels"][level]}.'
    if mode == "selfie":
        change += f' {eff["timeline"][when].capitalize()}.'
    variation = {**variation, "effect_level": {"key": level, "text": eff["effect_levels"][level]},
                 "timeline": {"key": when, "text": eff["timeline"][when]}}
    if mode == "clinical":
        after_var = variation
        after = (CFG / "prompts/after_clinical.md").read_text(encoding="utf-8").format(identity_lock=identity, after_change=change)
    else:
        after_var = drift_after(variation, mode, rng)
        a = {k: val["text"] for k, val in after_var.items()}
        after_scene = f'{a["angle"]}, {a["background"]}. {a["lighting"]}. {a["color"]}. {a["quality"]}.'
        after_hair = f'{a["hair_color"]}, {a["hair_style"]}' + (f', {a["extras"]}' if a["extras"] else "")
        after = (CFG / "prompts/after_selfie.md").read_text(encoding="utf-8").format(
            identity_lock=identity, after_scene=after_scene, after_hair=after_hair, after_change=change)
    changed = [k for k in after_var if after_var[k]["key"] != variation[k]["key"]]
    return {"treatment": treatment, "mode": mode, "aspect": load("variations.yaml").get("output", {}).get("aspect", "4:5"),
            "variation": variation, "after_variation": after_var,
            "after_changed_axes": changed, "generation": "edit" if mode == "clinical" else "identity_reference",
            "before_prompt": " ".join(before.split()), "after_prompt": " ".join(after.split())}
