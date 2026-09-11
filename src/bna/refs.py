"""참조 이미지 라이브러리 (A1). samples_index.yaml 태그로 모드·조명·화소가 맞는 참조를 고른다.

⚠ 2026-09-11 (빌디 "refs.pick 이 시술·시점을 거르는지 확인 부탁") — **안 걸렀다.**
   종전 pick 은 `mode` 와 조명·화질·배경만 봤다. 그래서 팔자 *직후* 실사진을 색인에 넣으면
   그 사진이 리프팅 컷에도, **시술 전(Before) 컷에도** 참조로 들어간다. 직후 참조가 Before 에
   붙으면 모델이 아직 시술도 안 한 얼굴에 패치와 홍조를 그린다 — 오류 없이 전량 불량이 된다.
   그래서 두 축을 신설했다:
     · treatment : 그 시술 컷에만 쓴다. 안 적으면 범용(종전 동작 그대로).
     · timeline  : 그 시점 After 에만 쓴다. 안 적으면 범용.
                   **시점 태그가 붙은 참조는 Before 에 절대 안 들어간다**(when=None 이면 전부 배제).
   실패 모드가 '틀린 그림'이 아니라 '조용히 섞임'이라, 모르는 값·없는 파일은 소리 내고 죽는다.
"""
from pathlib import Path
from .spec import load, ROOT, TIMELINE_ORDER

REF_DIR = ROOT / "samples" / "reference"


def _as_set(v) -> set:
    """한 칸에 문자열 하나도, 목록도 쓸 수 있게. 안 적었으면 빈 집합 = 범용."""
    if v is None:
        return set()
    return {str(x) for x in (v if isinstance(v, (list, tuple, set)) else [v])}


def check_index() -> list:
    """색인의 죽은 설정을 **소리 내서** 막는다. 반환=검증된 항목 목록.

    막는 것: ①모르는 시술 이름(오타) ②없는 시점 이름 ③파일이 실제로 없는 항목.
    ③을 조용히 넘기면 색인엔 있는데 한 번도 안 붙는 참조가 생긴다 — 넣은 사람은 붙은 줄 안다.
    """
    treatments = set(load("treatments.yaml"))
    out = []
    for i, r in enumerate(load("samples_index.yaml").get("refs") or []):
        where = f"samples_index.yaml refs[{i}] ({r.get('file')})"
        if not r.get("file") or not r.get("mode"):
            raise ValueError(f"{where}: file·mode 는 필수다")
        bad = _as_set(r.get("treatment")) - treatments
        if bad:
            raise ValueError(f"{where}: 모르는 시술 {sorted(bad)} (가능: {sorted(treatments)})")
        bad = _as_set(r.get("timeline")) - set(TIMELINE_ORDER)
        if bad:
            raise ValueError(f"{where}: 없는 시점 {sorted(bad)} (가능: {TIMELINE_ORDER})")
        if not (REF_DIR / r["file"]).exists():
            raise FileNotFoundError(f"{where}: 파일이 없다 — {REF_DIR / r['file']}")
        out.append(r)
    return out


def candidates(mode: str, treatment: str = None, when: str = None) -> list:
    """이 컷에 써도 되는 참조만. `when=None` = 시술 전(Before) 컷."""
    picked = []
    for r in check_index():
        if r.get("mode") != mode:
            continue
        tr = _as_set(r.get("treatment"))
        if tr and treatment is not None and treatment not in tr:
            continue
        tl = _as_set(r.get("timeline"))
        if tl and (when is None or when not in tl):
            # 시점 태그가 붙은 참조 = 시술 흔적이 찍힌 사진이다. Before 엔 절대 안 간다.
            continue
        picked.append(r)
    return picked


def pick(mode: str, variation: dict, k: int = 2, treatment: str = None, when: str = None) -> list:
    refs = candidates(mode, treatment, when)
    want = {a: variation[a]["key"] for a in ("lighting", "quality", "background") if a in variation}
    scored = sorted(refs, key=lambda r: -sum(r.get("tags", {}).get(a) == v for a, v in want.items()))
    return [(REF_DIR / r["file"]).read_bytes() for r in scored[:k]]
