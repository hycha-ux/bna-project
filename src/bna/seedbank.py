"""씨앗 은행 → 임상 Before 인물 참조 (2026-09-15 저녁 티모, 연서님 요청 · 0909 문서 ②안 배선).

무엇을 넣나: **파생 얼굴 중 measure.py 판정을 통과한 것만** — 씨앗(실제 환자 사진 정제본)은 넣지 않는다.
  씨앗 은행 README 의 흐름이 `KOS 실사진 ─(파생)→ 가공 인물 ─(Before ref)→ B&A` 이고
  "파생물이 원본을 닮으면 그 파생물은 버린다"가 넘지 않는 선이라서다. 실제 환자 얼굴을 곧장 Before 에 넣으면
  B&A 사진이 **실존 환자의 가짜 시술 결과**가 된다 — 그건 이 배선이 정할 일이 아니라 사람 결정이다.
통과 기준: 제 씨앗과의 유사도 ≤ 대조군(서로 다른 실제 환자끼리) p90, 그리고 씨앗이 '같은 사람 의심' 묶음에 없음.
  숫자는 `tools/seedbank_attrs.py` 가 measure·prep 결과를 읽어 `seed-attrs.json` 에 굽는다(여기 박지 않는다).
고르는 법: 성별이 같고 나이대가 ±1칸 안인 것만, 세트 키로 결정적으로. 맞는 게 없으면 **(None, None)** —
  종전 글 조건 Before 로 간다. 다른 성별 얼굴을 억지로 붙이면 프롬프트 인물 묘사와 사진이 서로 다른 사람을 말한다.
⚠ 켜면 파생 얼굴(가공 인물)이 OpenAI 로 올라간다 — 회수 불가. 끄기 = config/seedbank.yaml `clinical_before_person_ref: false`.
"""
import hashlib
import json
from pathlib import Path

from .spec import CFG, load

AGE_ORDER = ["late_teens", "early_20s", "late_20s", "30s", "40s", "50s", "60s"]    # variations.yaml age 키 순서


def age_bucket(age: float) -> str:
    for cut, key in ((20, "late_teens"), (25, "early_20s"), (30, "late_20s"), (40, "30s"), (50, "40s"), (60, "50s")):
        if age < cut:
            return key
    return "60s"


def _cfg() -> dict:
    p = CFG / "seedbank.yaml"
    return (load("seedbank.yaml") or {}) if p.is_file() else {}


def enabled() -> bool:
    return bool(_cfg().get("clinical_before_person_ref"))


def pool() -> list:
    """쓸 수 있는 파생 얼굴 [{file, gender, age_bucket, own_sim, …}]. 속성표·파일이 없으면 빈 목록(fail-open)."""
    c = _cfg()
    attrs, pdir = Path(c.get("attrs") or ""), Path(c.get("pool_dir") or "")
    if not c.get("attrs") or not attrs.is_file():
        return []
    rows = json.loads(attrs.read_text(encoding="utf-8")).get("pool") or []
    return [r for r in rows if r.get("passed") and (pdir / r["file"]).is_file()]


def candidates(variation: dict, rows: list) -> list:
    g = (variation.get("gender") or {}).get("key")
    a = (variation.get("age") or {}).get("key")
    if a not in AGE_ORDER:
        return []
    ai = AGE_ORDER.index(a)
    return [r for r in rows if r.get("gender") == g and r.get("age_bucket") in AGE_ORDER
            and abs(AGE_ORDER.index(r["age_bucket"]) - ai) <= 1]


def pick(variation: dict, key: str):
    """(얼굴 bytes, 파일명) 또는 (None, None). key = 세트를 가르는 문자열(같은 세트는 늘 같은 얼굴)."""
    if not enabled():
        return None, None
    cand = candidates(variation, pool())
    if not cand:
        return None, None
    cand.sort(key=lambda r: hashlib.sha1(f"{key}|{r['file']}".encode("utf-8")).hexdigest())
    f = cand[0]["file"]
    return (Path(_cfg()["pool_dir"]) / f).read_bytes(), f


def prompt_line() -> str:
    return " ".join((CFG / "prompts" / "before_person_ref.md").read_text(encoding="utf-8").split())
