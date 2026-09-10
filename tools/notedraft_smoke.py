r"""메모 → 규칙 초안 실호출 스모크. 원장(outputs/lessons.jsonl)의 진짜 메모로 잰다.

왜 있나: 이 기능의 전제가 "키워드 표는 단어를 맞추고 AI 는 원인을 맞춘다"라서,
그 전제 자체를 실측으로 확인하지 않으면 더 비싼 오답기를 만든 것이 된다.
둘을 나란히 찍어 사람이 눈으로 본다.

사용(키 주입 필요):
  $env:OPENAI_API_KEY = (teemo\keys.env 에서)  ;  PYTHONPATH=src python tools/notedraft_smoke.py
옵션: --no-images (사진 없이 텍스트만 — 사진값이 얼마인지 보려고)

⚠ 실호출이라 돈이 든다(메모당 약 $0.007). 캐시에 쓰지 않는다 — 스모크가 본 원장을 오염시키지 않게.
"""
import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bna import lessons, notedraft                      # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--limit", type=int, default=4)
    a = ap.parse_args()
    out = ROOT / "outputs"

    s = lessons.summarize(out)
    groups = s.get("notes") or []
    if not groups:
        print("승격 대기 메모가 없다 — 검수에서 메모를 남긴 제외 건이 있어야 한다.")
        return 2

    total = 0.0
    for g in groups[: a.limit]:
        items = g.get("items") or []
        meta, prompts, imgs = ({}, {}, None)
        if items:
            meta, prompts, imgs = notedraft._load_item(out, items[0]["batch"], items[0]["item"],
                                                       not a.no_images)
        r = notedraft.draft_rule(g["note"], g.get("tags"), meta, prompts, imgs)
        total += r.get("usd") or 0
        print("=" * 78)
        print(f"메모   : {g['note']}   (태그 {g.get('tags')} · {g.get('count')}건)")
        print(f"그때 붙어 있던 금지문 {len(notedraft.applied_rules(meta))}개")
        print(f"[키워드표] {lessons.suggest_en(g['note'], g.get('tags')) or '(없음)'}")
        print(f"[AI why ] {r.get('why')}")
        print(f"[AI en  ] {r.get('en')}")
        print(f"[AI kind] {r.get('kind')}  · 승격가능={r.get('promotable')}"
              f"  · covered_by={(r.get('covered_by') or '')[:60] or '(없음)'}")
        print(f"          출처={r.get('source')} 토큰={r.get('tokens')} ${r.get('usd')}")
    print("=" * 78)
    print(f"합계 ${total:.4f} (≈ ₩{total * 1390:,.0f})  사진첨부={'없음' if a.no_images else '전·후 1쌍'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
