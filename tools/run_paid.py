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
    # 경과 시리즈: 쉼표로 시점 (예: --series immediate,2w). 안 주면 종전대로 After 한 장.
    # `Batch` 는 처음부터 series 를 받았는데 여기에 인자가 없어서, 시리즈 회차는 CLI 로 띄울 길이
    # 아예 없었다(2026-09-11 첫 시리즈 회차에서 발견). 시술이 허용하지 않는 시점은 spec 이 걸러 낸다.
    p.add_argument("--series", help="경과 시점 목록, 쉼표 구분 (예: immediate,2w)")
    a = p.parse_args()

    series = [s.strip() for s in a.series.split(",") if s.strip()] if a.series else None
    if series:
        # ⚠ 프로바이더(=키)를 잡기 **전에** 확인한다. 뒤에 두면 키가 없는 자리에선 이 검사에 닿지도 못하고,
        #   키가 있는 자리에선 이미 유료 경로에 들어선 뒤다. 시술이 안 받는 시점을 주면 spec 이 조용히
        #   단일 컷으로 떨어뜨리는데, 그러면 "시리즈를 돌렸다"고 믿은 채 결과를 읽게 된다.
        from bna.spec import series_points
        if not series_points(a.treatment, series):
            print(f"[중단] {a.treatment} 은 {series} 시점을 허용하지 않는다 (treatments.yaml timeline 확인)", flush=True)
            return 2
    from bna.batch import Batch
    b = Batch(a.treatment, a.mode, a.count, a.seed, dict(f.split("=", 1) for f in a.fix),
              cost_cap=a.cost_cap, target_pass=a.target_pass, series=series)
    print(f"[착수] {a.treatment}/{a.mode} {a.count}세트 · 고정 {a.fix} · 상한 ${a.cost_cap}"
          f" · 시리즈 {b.series or '없음(단일 컷)'} · 배치 {b.batch_id}", flush=True)
    print("[예상] " + json.dumps(b.estimate(), ensure_ascii=False), flush=True)
    r = asyncio.run(b.run())
    print("[결과] " + json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
