"""변주 샘플링 + 프롬프트 조립. API 키 없이도 동작 (dry-run)."""
import random
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config"


def load(name):
    return yaml.safe_load((CFG / name).read_text(encoding="utf-8"))


def sample_variation(mode: str, seed=None) -> dict:
    rng = random.Random(seed)
    v = load("variations.yaml")
    rules = v.get("mode_rules", {}).get(mode, {})
    picked = {}
    compat = v.get("background_lighting", {})
    for axis in ["country", "age", "gender", "background", "angle", "lighting", "color", "quality"]:
        options = v[axis]
        allowed = rules.get(axis) or list(options)
        if axis == "lighting" and picked["background"]["key"] in compat:
            allowed = [k for k in allowed if k in compat[picked["background"]["key"]]] or allowed
        key = rng.choice(allowed)
        picked[axis] = {"key": key, "text": options[key]}
    return picked


def build_prompts(treatment: str, mode: str, variation: dict) -> dict:
    t = load("treatments.yaml")[treatment]
    if mode not in t["modes"]:
        raise ValueError(f"{treatment} does not support mode {mode}")
    mode_extra = load("prompts/mode_extra.yaml")[mode].strip()
    fields = {k: v["text"] for k, v in variation.items()}
    framing = load("prompts/framing.yaml")[t.get("framing", ["face_closeup"])[0]]
    if mode == "clinical":
        rig = load("clinical_rig.yaml")
        r = rig["rig_default"]
        angle = rig["angles"].get({"front": "front", "three_quarter": "oblique_45", "side": "side"}.get(variation["angle"]["key"], "front"))
        scene = ". ".join([angle, r["camera"], r["distance"], r["lighting"], r["background"], r["subject_setup"], r["processing"]]) + "."
    else:
        scene = f'{fields["angle"]}, {fields["background"]}. {fields["lighting"]}. {fields["color"]}. {fields["quality"]}.'
    before = (CFG / "prompts/before.md").read_text(encoding="utf-8").format(framing=framing, scene=scene, mode_extra=mode_extra, **fields)
    after = (CFG / "prompts/after.md").read_text(encoding="utf-8").format(after_change=t["after_change"].strip())
    return {"treatment": treatment, "mode": mode, "variation": variation,
            "before_prompt": " ".join(before.split()), "after_prompt": " ".join(after.split())}
