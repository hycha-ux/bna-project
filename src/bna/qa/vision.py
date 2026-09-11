"""비전 LLM 채점 (7항목). 프로바이더의 qa() 를 호출하고 threshold·hard_fail 규칙을 적용."""
from ..spec import load


def score(before_bytes: bytes, after_bytes: bytes, mode: str, provider, ungate=()) -> dict:
    """ungate = 이 컷에서 **묻긴 하되 탈락시키지 않을** 항목.

    2026-09-11 (빌디 지적): 경과 시리즈의 직후 컷은 프롬프트가 `early`("변화가 거의 안 보여야 하고
    최종 결과를 보여주지 마라")로 그리라고 시키는데, 같은 컷에 `effect_visible` 이 "noticeable 6점 이상"을
    요구했다. **지시대로 그릴수록 떨어지는 구조**라 시리즈를 켜는 순간 직후 컷이 전멸한다
    (실생성 회차에 시리즈가 아직 0건이라 안 터졌을 뿐이다).

    점수를 **안 묻는 게 아니라 안 거는** 이유: 그 숫자가 나중에 "직후 컷이 정말 변화가 적었나"를
    검산하는 유일한 근거다(낮게 나오는 게 정상). 안 물으면 그 검산을 영영 못 한다. 비용도 같다(한 콜).
    ⚠ `na_allowed` 는 이 목적에 못 쓴다 — 그 키를 읽는 코드가 없다(문서에만 있는 죽은 스위치).
    """
    cfg = load("qa_checklist.yaml")
    raw = provider.qa(before_bytes, after_bytes, cfg["items"], mode)   # {item: {score, note}}
    th = cfg["threshold"]
    ungate = set(ungate or ())
    # 항목별 합격선(없으면 공통 threshold). 한 항목의 점수 분포가 공통 컷과 안 맞으면
    # 그 항목 하나가 전체 통과율을 지배한다 — 2026-09-10 실측: effect_visible 평균 6.38 에
    # 컷이 7 이라 미달 54%, 나머지 4항목은 미달 0% 였다. 근거·재보정 절차는 qa_checklist.yaml 머리말.
    per = cfg.get("thresholds") or {}
    cut = lambda k: per.get(k, th)
    # 점수는 3값이다 — 숫자(쟀다) / None(이 사진엔 해당 없음) / 누락은 0점(못 쟀다, 재시도 대상).
    # None 을 임계와 비교하지 마라: '없는 것'을 탈락으로 세면 그 항목은 영영 통과할 수 없다
    # (2026-09-09 실사고 — 셀카는 폰을 안 보이게 찍으라고 지시해 놓고 fingers 가 손을 요구해 100% 탈락).
    na = [k for k, v in raw.items() if v.get("score") is None]
    fails = [k for k, v in raw.items()
             if k not in ungate and v.get("score") is not None and v["score"] < cut(k)]
    hard = [k for k in cfg.get("hard_fail", []) if k in fails]
    return {"scores": raw, "failed_items": fails, "na_items": na, "hard_fail": hard, "passed": not fails,
            "ungated": sorted(ungate),                 # 이 컷에서 안 건 항목 — 화면·통계가 '통과'로 오독하지 않게 남긴다
            "cuts": {k: cut(k) for k in raw}}          # 어느 컷으로 잰 판정인지 남긴다(컷을 바꾸면 옛 회차와 축이 갈린다)
