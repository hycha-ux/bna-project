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
    for axis in ["country", "age", "gender", "background", "angle", "lighting", "color", "quality"]:
        options = v[axis]
        allowed = rules.get(axis) or list(options)
        key = rng.choice(allowed)
        picked[axis] = {"key": key, "text": options[key]}
    return picked


def build_prompts(treatment: str, mode: str, variation: dict) -> dict:
    t = load("treatments.yaml")[treatment]
    if mode not in t["modes"]:
        raise ValueError(f"{treatment} does not support mode {mode}")
    mode_extra = load("prompts/mode_extra.yaml")[mode].strip()
    fields = {k: v["text"] for k, v in variation.items()}
    before = (CFG / "prompts/before.md").read_text(encoding="utf-8").format(mode_extra=mode_extra, **fields)
    after = (CFG / "prompts/after.md").read_text(encoding="utf-8").format(after_change=t["after_change"].strip())
    return {"treatment": treatment, "mode": mode, "variation": variation,
            "before_prompt": " ".join(before.split()), "after_prompt": " ".join(after.split())}
