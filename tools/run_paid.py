"""유료 실회차 실행기 — 비용 상한을 걸고 배치 하나를 돌린다.

왜 CLI 가 아니라 이 파일인가: `bna.cli` 에는 `--cost-cap` 이 없다. 돈이 나가는 회차를
상한 없이 띄우면, 무언가 어긋났을 때 멈추는 게 사람의 손밖에 없다.

사용: python tools/run_paid.py --treatment nasolabial --mode selfie --count 8 \
            --seed 11 --fix country=korea --cost-cap 10
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8")      # 콘솔 기본 CP949 라 한글 보고가 터진다


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--treatment", required=True)
    p.add_argument("--mode", default="selfie", choices=["clinical", "selfie"])
    p.add_argument("--count", type=int, default=8)
    p.add_argument("--seed", type=int)
    p.add_argument("--fix", action="append", default=[], help="축 고정: --fix country=korea")
    p.add_argument("--cost-cap", type=float, default=10.0, help="누적 비용이 이만큼이면 그 회차에서 멈춘다(USD)")
    p.add_argument("--target-pass", type=int, help="통과작이 이만큼 모이면 멈춘다")
    a = p.parse_args()

    from bna.batch import Batch
    b = Batch(a.treatment, a.mode, a.count, a.seed, dict(f.split("=", 1) for f in a.fix),
              cost_cap=a.cost_cap, target_pass=a.target_pass)
    print(f"[착수] {a.treatment}/{a.mode} {a.count}세트 · 고정 {a.fix} · 상한 ${a.cost_cap} · 배치 {b.batch_id}", flush=True)
    print("[예상] " + json.dumps(b.estimate(), ensure_ascii=False), flush=True)
    r = asyncio.run(b.run())
    print("[결과] " + json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
