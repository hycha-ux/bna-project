r"""'티모에게 넘기기' 대기열 — 보기 · 닫기 (2026-09-10 빌디 조율).

학습 탭에서 승격감이 아닌 메모(프롬프트 설계·검수기·조건 가중치)를 사람이 넘기면
`outputs/handoffs.jsonl` 에 `status=open` 으로 쌓인다. 티모가 조치한 뒤 여기서 닫는다.

  PYTHONPATH=src python tools/handoff.py                       # 대기 목록
  PYTHONPATH=src python tools/handoff.py --all                 # 닫힌 것까지
  PYTHONPATH=src python tools/handoff.py --done "카메라 앵글" --memo "after 프롬프트 각도 문장 수정"
  PYTHONPATH=src python tools/handoff.py --wontfix "..." --memo "표본 1건이라 관측만"

⚠ `--memo` 는 필수다. 무엇을 했는지가 없으면 닫힌 기록이 '누가 언제 닫았다'뿐이라,
  같은 메모가 또 올라올 때 지난번 조치를 아무도 모른다.
⚠ 닫아도 그 메모는 승격 대기 목록으로 돌아오지 않는다(무한 왕복 방지) — 같은 실수가 또 나면
  성적표(학습 탭 scorecard)가 잡는다.
"""
import argparse
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bna import lessons                                  # noqa: E402

OUT = ROOT / "outputs"
KIND_KR = {"rule": "규칙감", "prompt_design": "프롬프트 설계", "gate": "검수기",
           "axis": "조건 가중치", None: "판정 불가"}


def _fmt(r, mark):
    when = time.strftime("%m-%d %H:%M", time.localtime(r.get("at") or 0))
    line = [f"{mark} [{when}] {r.get('note')}",
            f"     종류={KIND_KR.get(r.get('kind'), r.get('kind'))}"
            f" · 넘긴이={r.get('by') or '?'}"]
    if r.get("why"):
        line.append(f"     왜  : {r['why']}")
    if r.get("en"):
        line.append(f"     초안: {r['en']}")
    if r.get("memo"):
        line.append(f"     조치: {r['memo']}  (status={r.get('status')})")
    return "\n".join(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="닫힌 것까지 본다")
    ap.add_argument("--done", metavar="메모일부", help="조치 완료로 닫는다")
    ap.add_argument("--wontfix", metavar="메모일부", help="안 고치기로 하고 닫는다(이유는 --memo)")
    ap.add_argument("--memo", default="", help="무엇을 했는지 한 줄 (닫을 때 필수)")
    a = ap.parse_args()

    target, status = (a.done, "done") if a.done else ((a.wontfix, "wontfix") if a.wontfix else (None, None))
    if target:
        if not a.memo.strip():
            print("--memo 가 필요하다. 무엇을 했는지 한 줄 적어라(없으면 닫힌 기록이 쓸모없다).")
            return 2
        # 부분일치로 찾는다 — 메모 전문을 다시 치게 하면 오타로 엉뚱한 걸 닫는다
        hits = [r for r in lessons.handoffs_open(OUT) if target.strip() in (r.get("note") or "")]
        if not hits:
            print(f"열린 넘기기 중에 {target!r} 를 포함한 메모가 없다. 목록부터 봐라.")
            return 2
        if len(hits) > 1:
            print(f"{len(hits)}건이 걸렸다 — 더 길게 적어 하나만 고르게 해라:")
            for r in hits:
                print("  · " + (r.get("note") or ""))
            return 2                                    # 여러 건을 한 번에 닫지 않는다(조치 메모가 서로 다르다)
        r = lessons.handoffs_resolve(OUT, hits[0]["note"], status, a.memo)
        print(("닫았다: " if r.get("ok") else "실패: ") + str(r.get("handoff", {}).get("note") or r.get("error")))
        return 0 if r.get("ok") else 1

    op = lessons.handoffs_open(OUT)
    print(f"티모 확인 대기 {len(op)}건")
    for r in op:
        print(_fmt(r, "●"))
    if a.all:
        dn = lessons.handoffs_done(OUT)
        print(f"\n처리됨 {len(dn)}건")
        for r in dn:
            print(_fmt(r, "○"))
    if not op and not a.all:
        print("(비어 있다 — 캡틴 티모, 대기열 깨끗합니다!)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
