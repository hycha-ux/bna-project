"""outputs/usage.jsonl(호출별 토큰 원장) → 실단가 산출.

왜 있나: config/pricing.yaml 의 호출당 단가는 **추정치**다(openai $0.19, 2026-09-08 미실측).
"통과 1세트 $2.68" 이 그 추정 위에 서 있어서, 실청구와 맞춰 보기 전엔 예산으로 못 쓴다.
API 응답의 usage 가 과금 원장 그 자체이므로 그걸 그대로 접어 실단가를 낸다.

[주의] 원장은 2026-09-10 계측 신설 **이후** 회차부터 쌓인다 — 그 앞(09-08·09-09 27세트)은 비어 있다.
   비어 있으면 '0원'이 아니라 '아직 안 잼'이다.

사용: python tools/usage_report.py [--jsonl <경로>]
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 공표 요금(USD / 1M 토큰). 출처=developers.openai.com/api/docs/pricing, 확인일 2026-09-10.
# [주의] 값을 바꾸면 확인일도 같이 바꿔라 — 낡은 요금표는 가짜 실측이 된다.
RATES = {
    "gpt-image-2": {"image_in": 8.00, "cached_in": 2.00, "out": 30.00, "text_in": 8.00},
    "gpt-5.1":     {"image_in": 1.25, "cached_in": 0.125, "out": 10.00, "text_in": 1.25},
}
# gpt-image-2 의 '텍스트 입력' 단가는 공표표에 따로 없어 이미지 입력과 같게 뒀다(보수적 가정).
ASSUMED = {"gpt-image-2": "text_in"}


def rate_for(model):
    for k, v in RATES.items():
        if model and model.startswith(k):
            return k, v
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default=str(ROOT / "outputs" / "usage.jsonl"))
    a = ap.parse_args()
    p = Path(a.jsonl)
    if not p.exists():
        print(f"원장 없음: {p}\n→ 아직 실회차가 안 돌았다는 뜻이다('0원'이 아니라 '못 잼').")
        return 2

    groups = defaultdict(lambda: {"n": 0, "in": 0, "cached": 0, "out": 0, "usd": 0.0, "unknown": 0})
    rows = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        rows += 1
        u = r.get("usage") or {}
        model = r.get("model") or "?"
        key, rt = rate_for(model)
        det = u.get("input_tokens_details") or u.get("prompt_tokens_details") or {}
        cached = int(det.get("cached_tokens") or 0)
        tin = int(u.get("input_tokens") or u.get("prompt_tokens") or 0)
        tout = int(u.get("output_tokens") or u.get("completion_tokens") or 0)
        gk = f"{model} {r.get('size') or ''} {r.get('quality') or ''}".strip()
        g = groups[gk]
        g["n"] += 1; g["in"] += tin; g["cached"] += cached; g["out"] += tout
        if not rt:
            g["unknown"] += 1
            continue
        # 이미지/텍스트 입력이 갈려 있으면 각각, 아니면 통째로 image_in 단가(보수적).
        img = int(det.get("image_tokens") or 0)
        txt = int(det.get("text_tokens") or 0)
        billable_in = max(tin - cached, 0)
        if img or txt:
            usd = (img * rt["image_in"] + txt * rt["text_in"]) / 1e6
        else:
            usd = billable_in * rt["image_in"] / 1e6
        usd += cached * rt["cached_in"] / 1e6 + tout * rt["out"] / 1e6
        g["usd"] += usd

    total = sum(g["usd"] for g in groups.values())
    print(f"원장 {rows}줄 · 합계 ${total:.4f}\n")
    print(f"{'호출 종류':40} {'건':>4} {'입력토큰':>10} {'출력토큰':>10} {'실비용$':>9} {'건당$':>8}")
    for k, g in sorted(groups.items()):
        per = g["usd"] / g["n"] if g["n"] else 0
        mark = "  [단가미상]" if g["unknown"] else ""
        print(f"{k:40} {g['n']:>4} {g['in']:>10,} {g['out']:>10,} {g['usd']:>9.4f} {per:>8.4f}{mark}")
    if ASSUMED:
        print("\n[주의] 가정: " + ", ".join(f"{m}의 {f}" for m, f in ASSUMED.items()) + " 단가는 공표표에 없어 이미지 입력과 같게 뒀다.")
    print("→ pricing.yaml 의 추정 단가와 다르면, 그 파일 값을 여기 건당$로 바꾸고 바꾼 날짜를 적어라.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
