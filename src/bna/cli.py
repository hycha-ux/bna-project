import argparse, json, uuid
from pathlib import Path
from .spec import build_prompts, ROOT
from .planner import plan_batch, distribution


def main():
    p = argparse.ArgumentParser(description="온리프 B&A 생성기")
    p.add_argument("--treatment", required=True)
    p.add_argument("--mode", choices=["clinical", "selfie"], required=True)
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--seed", type=int)
    p.add_argument("--dry-run", action="store_true", help="이미지 생성 없이 프롬프트만 출력")
    p.add_argument("--plan", action="store_true", help="배치 변주 분포만 출력")
    p.add_argument("--fix", action="append", default=[], help="축 고정 예: --fix gender=female --fix country=korea")
    a = p.parse_args()

    fixed = dict(f.split("=", 1) for f in a.fix)
    plans = plan_batch(a.mode, a.count, a.seed, fixed)
    if a.plan:
        print(json.dumps(distribution(plans), ensure_ascii=False, indent=1)); return

    for variation in plans:
        spec = build_prompts(a.treatment, a.mode, variation)
        spec["id"] = uuid.uuid4().hex[:8]
        if a.dry_run:
            print(json.dumps(spec, ensure_ascii=False, indent=2))
            continue
        out = ROOT / "outputs" / a.treatment / a.mode / spec["id"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "meta.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        from . import providers
        before = providers.generate_before(spec["before_prompt"])
        after = providers.edit_after(before, spec["after_prompt"])
        (out / "before.jpg").write_bytes(before)
        (out / "after.jpg").write_bytes(after)
        print("saved", out)


if __name__ == "__main__":
    main()
