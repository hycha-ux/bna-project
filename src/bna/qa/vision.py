"""비전 LLM 채점 (7항목). 프로바이더의 qa() 를 호출하고 threshold·hard_fail 규칙을 적용."""
from ..spec import load


def score(before_bytes: bytes, after_bytes: bytes, mode: str, provider) -> dict:
    cfg = load("qa_checklist.yaml")
    raw = provider.qa(before_bytes, after_bytes, cfg["items"], mode)   # {item: {score, note}}
    th = cfg["threshold"]
    fails = [k for k, v in raw.items() if v["score"] < th]
    hard = [k for k in cfg.get("hard_fail", []) if k in fails]
    return {"scores": raw, "failed_items": fails, "hard_fail": hard, "passed": not fails}
