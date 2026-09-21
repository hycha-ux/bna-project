"""참조 이미지 라이브러리 (A1). samples_index.yaml 태그로 모드·조명·화소가 맞는 참조를 고른다.

⚠ 2026-09-11 (빌디 "refs.pick 이 시술·시점을 거르는지 확인 부탁") — **안 걸렀다.**
   종전 pick 은 `mode` 와 조명·화질·배경만 봤다. 그래서 팔자 *직후* 실사진을 색인에 넣으면
   그 사진이 리프팅 컷에도, **시술 전(Before) 컷에도** 참조로 들어간다. 직후 참조가 Before 에
   붙으면 모델이 아직 시술도 안 한 얼굴에 패치와 홍조를 그린다 — 오류 없이 전량 불량이 된다.
   그래서 두 축을 신설했다:
     · treatment : 그 시술 컷에만 쓴다. 안 적으면 범용(종전 동작 그대로).
     · timeline  : 그 시점 After 에만 쓴다. `before` 면 시술 전 컷 전용. 안 적으면 범용.
                   **시점 태그가 붙은 참조는 Before 에 절대 안 들어간다**(when=None 이면 전부 배제).
   실패 모드가 '틀린 그림'이 아니라 '조용히 섞임'이라, 모르는 값·없는 파일은 소리 내고 죽는다.
"""
import hashlib, random
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
        bad = _as_set(r.get("timeline")) - (set(TIMELINE_ORDER) | {"before"})   # before = 시술 전 컷 전용 (2026-09-14)
        if bad:
            raise ValueError(f"{where}: 없는 시점 {sorted(bad)} (가능: {TIMELINE_ORDER})")
        bad = _as_set(r.get("looks")) - set(load("variations.yaml").get("looks") or {})   # looks = 미모 축 (2026-09-17)
        if bad:
            raise ValueError(f"{where}: 없는 looks {sorted(bad)} (가능: {sorted(load('variations.yaml').get('looks') or {})})")
        if r.get("rig") is not None and str(r["rig"]) not in load("clinical_rig.yaml")["rigs"]:
            raise ValueError(f"{where}: 없는 리그 {r['rig']!r} (가능: {sorted(load('clinical_rig.yaml')['rigs'])})")
        if not (REF_DIR / r["file"]).exists():
            raise FileNotFoundError(f"{where}: 파일이 없다 — {REF_DIR / r['file']}")
        out.append(r)
    return out


def candidates(mode: str, treatment: str = None, when: str = None, rig: str = None, looks: str = None,
               background: str = None) -> list:
    """이 컷에 써도 되는 참조만. `when=None` = 시술 전(Before) 컷.
    `rig` = 이 세트가 뽑은 촬영 리그(임상). 리그 태그가 있는 참조는 **같은 리그일 때만** 쓴다 — 점수가 아니라
    필터다. 참조는 그림체(배경·조명)도 옮기므로 다른 리그 사진이 붙으면 '세트마다 리그 고정'이 깨진다
    (2026-09-15 티모: 팔자는 회색 스튜디오 참조 1장뿐이라 어떤 리그를 뽑아도 그게 붙었다). 리그 태그가 없는
    참조는 종전처럼 범용."""
    picked = []
    for r in check_index():
        if r.get("mode") != mode:
            continue
        if r.get("rig") is not None and rig is not None and str(r["rig"]) != str(rig):
            continue
        tr = _as_set(r.get("treatment"))
        if tr and treatment is not None and treatment not in tr:
            continue
        # looks 태그 참조는 **그 looks 인 세트에만** (2026-09-17 노션 AI 셀카 배경 크롭 = 미모 전용).
        #   looks 를 모르면(옛 계획·임상) 붙이지 않는다 — treatment 와 달리 필터 쪽으로 닫는다: 보통 인물에
        #   인플루언서 장면이 붙으면 그게 곧 결함이다.
        lk = _as_set(r.get("looks"))
        if lk and looks not in lk:
            continue
        # only_background = 장면 참조는 **그 배경이 뽑힌 컷에만** (2026-09-17). 배경 태그는 점수축이라
        #   '집 욕실' 컷에 카페 창가 사진이 붙을 수 있었다 — 장면을 옮기는 참조에선 그게 곧 충돌이다.
        ob = _as_set(r.get("only_background"))
        if ob and background not in ob:
            continue
        tl = _as_set(r.get("timeline"))
        if "before" in tl:
            # 시술 전 전용 참조(푸석·큰 모공·홍조가 찍힌 사진). After 에 붙으면 결과가 도로 나빠 보인다 (2026-09-14 피부 3종 참조)
            if when is not None:
                continue
        elif tl and (when is None or when not in tl):
            # 시점 태그가 붙은 참조 = 시술 흔적이 찍힌 사진이다. Before 엔 절대 안 간다.
            continue
        picked.append(r)
    return picked


def _rank(refs: list, variation: dict, when, treatment: str = None) -> list:
    """태그 점수 순. **동점은 컷마다 번갈아** 쓴다 (2026-09-14 실측).

    ⚠ 종전엔 동점이면 정렬이 안정적이라 **색인 앞 2장이 늘 뽑혔다**. 피부 3종 태그가
       셀카에 없는 값(`quality: flagship`·`background: clinic`)이라 대부분 0점 동점이었고,
       120회 추첨에서 `skin_pores_*_03` 쌍이 **7회(6%)만** 붙었다 — 사람이 올린 사진 2장이
       사실상 안 쓰인 것이다. 태그를 고쳐도 이 성질은 남으므로(동점은 언제든 생긴다) 여기서 막는다.
    ⚠ 섞는 씨앗은 그 컷의 변주다 — **같은 컷은 늘 같은 참조**여야 재현·재시도가 성립한다.
    """
    sig = "|".join(f"{a}={variation[a]['key']}" for a in sorted(variation)
                   if isinstance(variation.get(a), dict) and "key" in variation[a])
    rng = random.Random(hashlib.sha1(f"{sig}|{when}".encode("utf-8")).hexdigest())
    shuffled = list(refs)
    rng.shuffle(shuffled)                               # 동점 안의 순서 = 이 셔플 (sorted 가 안정적이라 보존된다)
    want = {a: variation[a]["key"] for a in ("lighting", "quality", "background") if a in variation}
    # 그 시술 **전용** 참조(treatment 가 이 시술 하나)는 공용 참조보다 +2 (2026-09-15 실측: 엠보 4주 컷에
    # 모공·홍조 4주 사진이 붙어 1주 컷(엠보 7일차 물광 사진)보다 나빠 보였다 — 태그 동점이라 셔플이 갈랐다).
    def score(r):
        dedicated = 2 if (treatment and _as_set(r.get("treatment")) == {treatment}) else 0
        return -(dedicated + sum(r.get("tags", {}).get(a) == v for a, v in want.items()))
    return sorted(shuffled, key=score)


def _key(variation: dict, axis: str):
    return (variation.get(axis) or {}).get("key") if isinstance(variation.get(axis), dict) else None


FACE_DIR = ROOT / "samples" / "reference" / "looks_face"
# 참조 문장 (2026-09-21 2차 연서님: 1차 "다른 사람으로" 문장은 닮음 0.13·0.20 — 참조를 거의 안 봤다.
#   "다른 사람이되 같은 미인상: 얼굴형·눈매·피부결·화장·머리는 참조를 따르고 이목구비 배치만 새로")
FACE_LINE = ("The first {n} attached photos are look references. Draw a different person with the same kind of "
             "beauty: follow the references for the face shape, the eye shape and gaze, the skin texture and tone, "
             "the makeup and the hair; only the exact placement and proportions of the features (eyes, nose, mouth) "
             "are new, so it is clearly not the same individual. Do not copy their pose, background, lighting or hands.")
# 손·팔이 보이는 참조는 뺀다 — 턱 괸 손이 결과로 따라와 'hands_absent' 탈락이 두 번 났다(v32 0000 face_10,
#   v33 0000 face_13 포함 회차, 2026-09-21). 27장을 눈으로 전수 확인해 손·든 팔·팔짱이 보이는 16장을 뺐다(남은 11장).
BAD_FACE = {f"face_{n:02d}.jpg" for n in (1, 2, 3, 4, 5, 10, 11, 12, 13, 14, 16, 17, 18, 19, 23, 24)}


def face_ref(variation: dict, key: str, treatment: str = None):
    """미모 프로필 외모 참조 (2026-09-21 빌디 ⑤) — [(bytes, 파일명), …] (없으면 []).
    스위치(BNA_EXP_LOOKS_PROFILE)가 켜졌고 그 looks 프로필에 face_refs(장수)가 있을 때만. 셀카 Before 전용.
    ⚠ samples_index.yaml 밖 폴더다 — 색인에 넣으면 candidates 가 장면 참조로도 붙인다.
    ⚠ 같은 조합이 여러 세트에 붙으면 결과가 한 얼굴로 모인다(중복 게이트 0.75) → 컷마다 해시로 다른 조합을 고른다
      (같은 컷=같은 조합이라 재현·재시도는 성립). 노션 27장끼리 쌍 유사도 최대 0.528(faces.json)."""
    from .spec import looks_profile
    k = int(looks_profile(_key(variation, "looks"), None, treatment).get("face_refs") or 0)
    files = [f for f in sorted(FACE_DIR.glob("face_*.jpg")) if f.name not in BAD_FACE]
    if not k or not files:
        return []                                     # 참조가 없으면 종전과 같은 글 조건 Before (fail-open)
    rng = random.Random(hashlib.sha1(key.encode("utf-8")).hexdigest())
    return [(f.read_bytes(), f.name) for f in rng.sample(files, min(k, len(files)))]


def pick(mode: str, variation: dict, k: int = 2, treatment: str = None, when: str = None) -> list:
    return [(REF_DIR / f).read_bytes() for f in pick_files(mode, variation, k, treatment, when)]


def pick_files(mode: str, variation: dict, k: int = 2, treatment: str = None, when: str = None) -> list:
    """pick 과 같은 선택, 파일 이름만 (검사·화면용). pick 은 이걸 읽는다 — 고르는 규칙은 한 벌."""
    cands = candidates(mode, treatment, when, _key(variation, "rig"), _key(variation, "looks"), _key(variation, "background"))
    return [r["file"] for r in _rank(cands, variation, when, treatment)[:k]]
