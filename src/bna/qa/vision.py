"""비전 LLM 채점 (7항목). 프로바이더의 qa() 를 호출하고 threshold·hard_fail 규칙을 적용."""
from ..spec import load


def score(before_bytes: bytes, after_bytes: bytes, mode: str, provider) -> dict:
    cfg = load("qa_checklist.yaml")
    raw = provider.qa(before_bytes, after_bytes, cfg["items"], mode)   # {item: {score, note}}
    th = cfg["threshold"]
    # 항목별 합격선(없으면 공통 threshold). 한 항목의 점수 분포가 공통 컷과 안 맞으면
    # 그 항목 하나가 전체 통과율을 지배한다 — 2026-09-10 실측: effect_visible 평균 6.38 에
    # 컷이 7 이라 미달 54%, 나머지 4항목은 미달 0% 였다. 근거·재보정 절차는 qa_checklist.yaml 머리말.
    per = cfg.get("thresholds") or {}
    cut = lambda k: per.get(k, th)
    # 점수는 3값이다 — 숫자(쟀다) / None(이 사진엔 해당 없음) / 누락은 0점(못 쟀다, 재시도 대상).
    # None 을 임계와 비교하지 마라: '없는 것'을 탈락으로 세면 그 항목은 영영 통과할 수 없다
    # (2026-09-09 실사고 — 셀카는 폰을 안 보이게 찍으라고 지시해 놓고 fingers 가 손을 요구해 100% 탈락).
    na = [k for k, v in raw.items() if v.get("score") is None]
    fails = [k for k, v in raw.items() if v.get("score") is not None and v["score"] < cut(k)]
    hard = [k for k in cfg.get("hard_fail", []) if k in fails]
    return {"scores": raw, "failed_items": fails, "na_items": na, "hard_fail": hard, "passed": not fails,
            "cuts": {k: cut(k) for k in raw}}          # 어느 컷으로 잰 판정인지 남긴다(컷을 바꾸면 옛 회차와 축이 갈린다)
