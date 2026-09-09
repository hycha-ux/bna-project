"""비전 LLM 채점 (7항목). 프로바이더의 qa() 를 호출하고 threshold·hard_fail 규칙을 적용."""
from ..spec import load


def score(before_bytes: bytes, after_bytes: bytes, mode: str, provider) -> dict:
    cfg = load("qa_checklist.yaml")
    raw = provider.qa(before_bytes, after_bytes, cfg["items"], mode)   # {item: {score, note}}
    th = cfg["threshold"]
    # 점수는 3값이다 — 숫자(쟀다) / None(이 사진엔 해당 없음) / 누락은 0점(못 쟀다, 재시도 대상).
    # None 을 임계와 비교하지 마라: '없는 것'을 탈락으로 세면 그 항목은 영영 통과할 수 없다
    # (2026-09-09 실사고 — 셀카는 폰을 안 보이게 찍으라고 지시해 놓고 fingers 가 손을 요구해 100% 탈락).
    na = [k for k, v in raw.items() if v.get("score") is None]
    fails = [k for k, v in raw.items() if v.get("score") is not None and v["score"] < th]
    hard = [k for k in cfg.get("hard_fail", []) if k in fails]
    return {"scores": raw, "failed_items": fails, "na_items": na, "hard_fail": hard, "passed": not fails}
