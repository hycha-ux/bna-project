import argparse, asyncio, json
from .spec import build_prompts
from .planner import plan_batch, distribution


def main():
    p = argparse.ArgumentParser(description="온리프 B&A 배치 생성기")
    p.add_argument("--treatment", required=True)
    p.add_argument("--mode", choices=["clinical", "selfie"], required=True)
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--seed", type=int)
    p.add_argument("--fix", action="append", default=[], help="축 고정: --fix gender=female")
    p.add_argument("--plan", action="store_true", help="변주 분포만 출력")
    p.add_argument("--dry-run", action="store_true", help="프롬프트만 출력 (키 불필요)")
    p.add_argument("--estimate", action="store_true", help="예상 호출 수·비용")
    p.add_argument("--run", action="store_true", help="실제 배치 실행")
    p.add_argument("--gen", default="gemini"); p.add_argument("--edit", default="gemini"); p.add_argument("--qa", default="gemini")
    a = p.parse_args()

    fixed = dict(f.split("=", 1) for f in a.fix)
    plans = plan_batch(a.mode, a.count, a.seed, fixed)
    if a.plan:
        print(json.dumps(distribution(plans), ensure_ascii=False, indent=1)); return
    if a.dry_run:
        for i, v in enumerate(plans):
            print(json.dumps(build_prompts(a.treatment, a.mode, v, None if a.seed is None else a.seed * 1000 + i), ensure_ascii=False, indent=2))
        return
    from .batch import Batch
    b = Batch(a.treatment, a.mode, a.count, a.seed, fixed, a.gen, a.edit, a.qa)
    if a.estimate:
        print(json.dumps(b.estimate(), indent=1)); return
    if a.run:
        print(json.dumps(asyncio.run(b.run()), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
