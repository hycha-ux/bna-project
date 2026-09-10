"""넘긴 메모를 처리(status≠open)하면 '승격 대기' 목록으로 돌아오는가? (2026-09-10 티모 검토)

돌아오면 화면이 다시 '티모에게 넘기기'를 보여 주고 사람이 또 누른다 = 무한 왕복.
지금 api.lessons_payload 의 필터가 handoffs_open(열린 것만)이라 그렇게 될 것으로 보였다 — 실측한다.
"""
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bna import lessons                                  # noqa: E402

out = Path(tempfile.mkdtemp())
NOTE = "카메라 앵글이 벗어남"
lessons.handoffs_add(out, NOTE, en="Keep the angle.", why="각도 드리프트", kind="prompt_design")
print("넘긴 직후  · 열린 넘기기:", [r["note"] for r in lessons.handoffs_open(out)])

# 처리 완료를 흉내 — append-only 원장에 status 를 바꾼 줄을 붙인다
row = {"note": NOTE, "en": "", "why": "", "kind": "prompt_design", "by": "teemo",
       "at": 0, "status": "done"}
import json                                              # noqa: E402
with (out / lessons.HANDOFFS).open("a", encoding="utf-8") as f:
    f.write(json.dumps(row, ensure_ascii=False) + "\n")

opened = {lessons._norm(r["note"]) for r in lessons.handoffs_open(out)}
print("처리 뒤    · 열린 넘기기:", [r["note"] for r in lessons.handoffs_open(out)])
back_open = lessons._norm(NOTE) not in opened
back_all = lessons._norm(NOTE) not in lessons.handoffs_notes(out)
print(f"→ 옛 필터(handoffs_open) : 승격 대기로 {'돌아온다 (무한 왕복)' if back_open else '안 돌아온다'}")
print(f"→ 지금 필터(handoffs_notes): 승격 대기로 {'돌아온다 (무한 왕복)' if back_all else '안 돌아온다'}")
sys.exit(0 if not back_all else 1)
