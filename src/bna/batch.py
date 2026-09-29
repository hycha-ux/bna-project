"""배치 오케스트레이션: 생성 → After → 후처리 → 3단 검수 → 판정/재시도 → 저장.
asyncio 워커 풀, 이어하기(state.json), 프롬프트 버전 기록."""
import asyncio, io, json, os, time, uuid
from pathlib import Path
from PIL import Image
from .spec import ROOT, load, build_prompts, defaults_for
from .planner import plan_batch, past_signatures, past_scene_signatures, remember
from . import postprocess, refs, providers, seedbank, patchfilm
from .qa import structure, identity, dedup, vision, landmarks, patchgate
from .stats import summarize, write_manifest
from .version import prompt_version
from .progress import Progress

MAX_ATTEMPTS = int(os.environ.get("BNA_EXP_MAX_ATTEMPTS") or 3)   # 09-29 고해상도 시험: 한 장이 5배 비싸 2회로 묶는다
BEFORE_PRECHECK_TRIES = 3     # 비포 선검사(콜라주)로 다시 그리는 최대 장수 — 3장 다 콜라주면 그대로 진행해 게이트가 잡는다

# ── 재시도 정책 (2026-09-10) ────────────────────────────────────────────────
# 종전엔 탈락하면 **같은 조건으로 Before 부터 통째로** 3번까지 다시 뽑았다.
# 실측이 그게 헛돌고 있음을 보여 줬다: 시도당 통과 14.5% → 3회 누적 예상 37.5% = 실제 37.0%.
# 예상과 실제가 소수점까지 맞는다 = 3번이 완전히 독립된 주사위 = 재시도가 아무것도 안 배운다.
#
# 그래서 사유를 두 갈래로 가른다.
#   RETRY_REDRAW  조건이 원인 — 같은 조건으로 다시 그려도 같은 벽이다 → **조건을 다시 뽑아** 그린다.
#                 (성연서님 2026-09-10 "'효과가 안 보임'으로 떨어진 건 같은 조건 재시도 금지")
#   REDO_BEFORE   Before 와 After 의 *관계*가 틀렸거나 Before 자체가 틀렸다 → Before 부터 다시.
#   그 외(운)      Before 는 멀쩡한데 After 만 어긋난 것 → **Before 재사용, After 만 다시 그린다**(비용 절반).
#
# ⚠ 조건을 다시 뽑으면 그 배치의 변주 분포가 계획(plan)과 달라진다 → meta["redrawn"] 에 회차를 남긴다.
#    안 남기면 나중에 "어떤 조건이 잘 통과하나" 통계가 조용히 오염된다.
RETRY_REDRAW = {"vision:effect_visible", "structure"}
# identity_review = 닮음이 '사람 확인 구간'(0.45~0.60). 둘의 *관계*가 흔들린 것이라
# hard fail 과 같이 Before 부터 다시 그린다(After 만 다시 그리면 같은 Before 를 기준으로 또 흘러간다).
#
# collage_before = Before 한 장에 큰 얼굴이 둘(2단 콜라주). **Before 자체가 틀린 것**이라 반드시 다시 그린다
#   (2026-09-15 티모). a679f22 가 `collage` 게이트를 넣었는데 이 두 집합 어디에도 안 넣어서,
#   콜라주 Before 는 2·3회차가 **같은 Before 를 재사용**해 확정 탈락이었다(3회 × $0.66 = 회차 전액 낭비).
#   After 쪽 콜라주(`collage`)는 Before 가 멀쩡하니 여기 넣지 않는다 — 넣으면 멀쩡한 Before 를 버린다.
REDO_BEFORE = {"identity", "identity_review", "vision:identity", "structure", "collage_before"}

# 얼굴만 오린 참조를 넘길 때 붙는 한 줄 (2026-09-22, 미모 `before_ref: face_crop`). 참조가 무엇인지 말하지 않으면
#   모델이 회색 바탕·잘린 윤곽까지 그림의 일부로 읽는다. 머리 모양은 참조에 없으므로 문장(Hair: …)이 정본이라고 적는다.
FACE_CROP_LINE = ("The first reference image is only a cut-out of this person's face on a plain grey card, straightened "
                  "so the eyes are level. Use it only for who this is: the face shape, features, skin and smile. It "
                  "is not a photo to follow - the head angle, the camera height, the framing, the hair, the clothes, "
                  "the background and the light all come from the text above, and the hairstyle is exactly as "
                  "written in the Hair line. Never show the grey card or a cut-out edge.")
# 머리 전체 참조용 (09-22 v40 검수). 머리카락·두상은 참조에 있으므로 '같은 머리'로 읽게 하고, 자세·옷·배경만 문장이 정한다.
HEAD_CROP_LINE = ("The first reference image is a cut-out of this person's whole head - hair and face - on a plain grey "
                  "card, straightened so the eyes are level. Keep this same person: the same face, head shape, "
                  "hairline, parting and bangs, and the hairstyle as written in the Hair line. It is not a photo to "
                  "follow - the head angle, the camera height, the framing, the shoulders, the clothes, the background "
                  "and the light all come from the text above. Never show the grey card or a cut-out edge.")


def _retry_plan(fail_reasons):
    """탈락 사유 → (조건을 다시 뽑나, Before 를 다시 그리나).
    사유는 시리즈일 때 `structure@2w` 처럼 시점이 붙으므로 `@` 앞만 본다.

    ⚠ **조건을 다시 뽑으면 Before 도 반드시 다시 그린다** — 새 조건은 새 사람·새 장면이라
      앞 회차의 Before 를 물려받으면 프롬프트와 사진이 서로 다른 사람을 말한다.
      이 묶음은 여기 한 곳에 둔다(부르는 쪽에서 따로 켜면 두 곳이 갈린다)."""
    base = {str(f).split("@", 1)[0] for f in (fail_reasons or [])}
    redraw = bool(base & RETRY_REDRAW)
    return redraw, (redraw or bool(base & REDO_BEFORE))


class Batch:
    def __init__(self, treatment, mode, count, seed=None, fixed=None, gen=None, edit=None, qa=None, ab_prompt=None,
                 target_pass=None, cost_cap=None, series=None):
        # 프로바이더 기본값은 모드가 정한다 (config/providers.yaml). 여기에 벤더 이름을 박지 마라.
        d = defaults_for(mode)
        gen, edit, qa = gen or d["gen"], edit or d["edit"], qa or d["qa"]
        self.treatment, self.mode, self.count, self.seed = treatment, mode, count, seed
        self.fixed = fixed or {}
        self.batch_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        self.dir = ROOT / "outputs" / self.batch_id
        # ⚠ 여기서 폴더를 만들지 마라(2026-09-11). 생성자는 프로바이더를 잡기 전에 돌기 때문에,
        #   키가 없거나 인자가 틀려 그 자리에서 죽어도 `outputs/<배치>` 가 남는다. 그 빈 폴더는
        #   배치 목록·통계에 진짜 회차처럼 보이고, 실측 때마다 "이건 뭔가" 하고 다시 세게 된다
        #   (실제로 13개가 쌓여 있었고, 그날 하루에만 3개를 더 만들었다).
        #   폴더는 **처음 쓸 때** 만든다 — 아무것도 안 썼으면 그 회차는 없었던 것이 맞다.
        self.pv = prompt_version()
        # 제외 사유에서 배운 금지문·조건 회피. 배치 시작 시 한 번 읽어 회차 내내 같은 규칙을 쓴다
        # (아이템마다 다시 읽으면 도중에 검수한 게 섞여 들어가 이 배치의 조건이 갈린다).
        try:
            from . import lessons
            self.avoid = lessons.active(ROOT / "outputs", treatment, mode)
        except Exception:                                   # noqa: BLE001
            self.avoid = {"lines": {}, "weights": {}}       # 학습이 실패해도 생성은 돈다(fail-open)
        self.pricing = load("pricing.yaml")
        self.p_gen, self.p_edit, self.p_qa = providers.get(gen), providers.get(edit), providers.get(qa)
        self.registry = dedup.Registry()
        self.ab_prompt = ab_prompt   # A6: 실험용 대체 프롬프트 파일 접미사 (예: "v2")
        self.state_path = self.dir / "state.json"
        self.progress = None   # run() 에서 생성
        self.target_pass, self.cost_cap = target_pass, cost_cap   # 정지 조건: 통과작 수 / 누적 비용(USD)
        self.stopped = None
        # 경과 시리즈: 시술 전 1장 + 시점마다 After 1장 (2026-09-09 성연서님: 기본 직후·2주, 세트 단위 채택).
        # 세트(item) 하나가 통과하려면 After 전부가 통과해야 한다 — 한 장이라도 이상하면 후기로 못 쓴다.
        from .spec import series_points
        self.series = series_points(treatment, series) or None

    def _refs(self, variation: dict, when: str = None) -> list:
        """이 컷에 붙일 참조 사진. `when=None` = 시술 전(Before) 컷 (2026-09-11 A1 축 신설)."""
        return refs.pick(self.mode, variation, treatment=self.treatment, when=when)

    def _slots(self, provider) -> asyncio.Semaphore:
        """이 **공급자**의 동시 이미지 호출 한도 (2026-09-15). 같은 벤더면 Before·After 가 같은 슬롯을 쓴다.

        ⚠ 한도는 'After 몇 장'이 아니라 '그 벤더에 동시에 몇 콜'이다 — After 만 세면 새는 곳이 생긴다.
          종전(순차) 구조에선 항목 세마포어(=3)가 총량을 지켜 줬다: 한 항목은 언제나 이미지 1콜만
          들고 있었으니 동시 이미지 콜 ≤ 3. 시점별 After 를 동시에 던지면 그 전제가 깨진다 —
          한 항목이 After 3콜을 들고 있는 동안 다른 두 항목이 각자 Before 1콜을 들 수 있어
          **최대 6콜**이 된다(대역 실측에서 4콜이 실제로 관측됐다). 429 는 그렇게 온다.
          그래서 Before 도 같은 세마포어를 탄다.
        ⚠ 검수(p_qa)는 여기 넣지 않는다 — 이미지 모델과 채점 모델은 한도 버킷이 다르고, 검수는
          항목 안에서 순차라 항목 세마포어가 이미 ≤3 으로 묶는다(종전 불변식 그대로).

        자리를 여기 **한 곳**으로 둔 이유 둘.
          ① run() 과 run_item() 두 곳에서 각각 만들면 한도 숫자가 두 벌이 된다 — 한쪽만 고치면
             조용히 갈리고, 갈린 쪽이 공급자 한도를 넘겨도 오류가 아니라 429 로 나타난다.
          ② `hasattr` 로 한 번만 만들면 **이벤트 루프가 바뀔 때** 죽은 세마포어를 물려받는다.
             run_item 을 직접 부르는 길이 실제로 있고(tools/_probe_series_gate_0911.py), 한 프로세스가
             asyncio.run 을 두 번 돌면 "Future attached to a different loop" 로 터진다.
             그래서 루프를 키로 기억하고 바뀌면 다시 만든다."""
        loop = asyncio.get_running_loop()
        if getattr(self, "_slot_loop", None) is not loop:
            self._slot_map, self._slot_loop = {}, loop
        if provider.name not in self._slot_map:
            self._slot_map[provider.name] = asyncio.Semaphore(provider.concurrency)
        return self._slot_map[provider.name]

    # ---------- 단일 아이템 ----------
    async def run_item(self, idx: int, variation: dict) -> dict:
        spec = build_prompts(self.treatment, self.mode, variation, None if self.seed is None else self.seed * 1000 + idx,
                             avoid=(self.avoid or {}).get("lines"), series=self.series,
                             avoid_not_at=(self.avoid or {}).get("not_at"))
        item_id = f"{idx:04d}"
        # 프로바이더를 같이 적는다 — 버전 성적표가 prompt_version(=config 해시)으로만 묶여서,
        # 같은 버전을 다른 모델로 돌리면 두 모델의 성적이 한 줄에 섞인다(조용히 비교가 무의미해진다).
        meta = {**spec, "item_id": item_id, "batch_id": self.batch_id, "prompt_version": self.pv,
                "providers": {"gen": self.p_gen.name, "edit": self.p_edit.name, "qa": self.p_qa.name},
                "cost": 0.0, "fail_reasons": []}
        t = load("treatments.yaml")[self.treatment]
        # 참조는 **컷마다 다시 고른다** (2026-09-11). 종전엔 한 번 골라 Before·After 에 같이 썼는데,
        # 그러면 '팔자 직후' 참조가 시술 전 컷에도 들어가 아직 시술도 안 한 얼굴에 패치를 그린다.
        # 시점 축은 refs.pick(when=...) 이 가른다 — when=None 이 곧 Before 다.
        style_refs = self._refs(spec["variation"])      # spec 의 변주에 임상 리그(rig)가 들어 있다 — 참조 리그 필터용 (2026-09-15)

        before_b = before = pts = mask_img = None      # 재시도 때 Before 를 물려받는 자리
        prev_fail = []
        meta["redrawn"] = []                           # 조건을 다시 뽑은 회차 (통계가 계획과 갈리는 걸 드러낸다)
        meta["attempts_log"] = []                      # 회차별 {attempt, fail_reasons, seconds} — "22분 중 어디서 샜나"의 근거 (2026-09-15)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            meta["attempt"] = attempt; meta["fail_reasons"] = []
            loop = asyncio.get_event_loop()

            # ── 재시도 정책: 사유를 보고 무엇을 다시 할지 고른다 (위 _retry_plan 주석이 근거) ──
            redraw, redo_before = (False, True) if attempt == 1 else _retry_plan(prev_fail)
            if redraw:
                # 조건이 원인이면 같은 조건으로 다시 그리지 않는다 — 사람·장면을 다시 뽑는다.
                # 씨앗은 회차마다 갈라야 한다(안 갈면 같은 변주가 다시 나와 재추첨이 무의미하다).
                #
                # ⚠ 반드시 `plan_batch` 로 뽑아라. `sample_variation` 은 **고정 축(--fix)을 안 받는다** —
                #   2026-09-10 실사고: 재추첨이 그걸 써서 "한국인 8세트" 지시가 재추첨된 2세트에서
                #   일본인·동남아인으로 나왔다. 첫 시도만 고정을 지키고 재시도가 몰래 풀어 버린 것이다.
                #   plan_batch 는 고정 축 + 과거 배치가 쓴 인물 조합 회피(avoid_sigs)까지 함께 지킨다.
                rs = None if self.seed is None else self.seed * 1000 + idx + attempt * 100_000
                variation = plan_batch(self.mode, 1, rs, self.fixed, (self.avoid or {}).get("weights"),
                                       treatment=self.treatment, avoid_sigs=past_signatures(),
                                       avoid_scene_sigs=past_scene_signatures())[0]
                spec = build_prompts(self.treatment, self.mode, variation, rs,
                                     avoid=(self.avoid or {}).get("lines"), series=self.series,
                                     avoid_not_at=(self.avoid or {}).get("not_at"))
                meta.update({k: v for k, v in spec.items()})
                meta["redrawn"].append(attempt)
                style_refs = self._refs(spec["variation"])      # spec 의 변주에 임상 리그(rig)가 들어 있다 — 참조 리그 필터용 (2026-09-15)
                # 조건이 바뀌면 Before 도 다시 — 그 묶음은 _retry_plan 안에 있다(여기서 또 켜지 않는다)

            self._p(item_id, "before", attempt=attempt)
            # ① Before — 다시 그릴 이유가 없으면 앞 회차 것을 그대로 쓴다(생성 1회 = 비용 절반)
            if redo_before or before_b is None:
                # 비포 선검사 (2026-09-15 초안): 한 장에 큰 얼굴이 둘(before/after 콜라주)이면 후 3장을 그리기 전에
                # 비포만 다시 그린다. 후 3장 + 검수까지 간 뒤에 떨어지면 세트 통째로 다시라 시간·돈이 4배다.
                # 최대 BEFORE_PRECHECK_TRIES 장. 모델이 없으면(None) 검사를 건너뛴다(fail-open).
                # 씨앗 은행 인물 참조 (2026-09-15 저녁, 0909 ②안) — 임상만, 스위치·고르는 규칙 정본은 seedbank.py 한 곳.
                #   맞는 얼굴이 없으면 (None, None) → 종전과 똑같은 글 조건 Before. 조건을 다시 뽑으면(redraw) 여기서 다시 고른다.
                person_b, person_f = (seedbank.pick(spec["variation"], f"{item_id}|{spec['variation']['gender']['key']}|{spec['variation']['age']['key']}")
                                      if self.mode == "clinical" else (None, None))
                person_line = seedbank.prompt_line() if person_b else ""
                gen_refs = style_refs                          # Before 생성에 실제로 붙는 장면 참조
                faces, face_embs, sim_max = [], [], None
                if self.mode == "selfie":
                    # 미모 프로필 외모 참조 (2026-09-21 빌디 ⑤, 스위치 켰을 때만 — 고르는 규칙은 refs.face_ref 한 곳).
                    #   씨앗 은행과 같은 자리(첫 장)에 붙지만 뜻이 다르다: '이 사람'이 아니라 '같은 미인상, 다른 사람'.
                    #   2~3장이면 첫 장은 ref 자리, 나머지는 장면 참조 **앞**에 붙인다(문장이 "처음 N장"이라 순서가 뜻이다).
                    faces = refs.face_ref(spec["variation"], f"{self.batch_id}|{item_id}|{attempt}", self.treatment)
                    if faces:
                        person_b, person_f = faces[0][0], ",".join(n for _b, n in faces)
                        gen_refs = [b for b, _n in faces[1:]] + list(style_refs or [])
                        person_line = refs.FACE_LINE.format(n=len(faces))
                        from .spec import looks_profile as _lp
                        # ⚠ 시술을 넘겨야 한다(2026-09-22 티모) — 프로필에 `treatments` 가 생긴 뒤로 시술 없이 부르면
                        #   fail-closed 로 {} 가 나와 이 0.6 상한이 **조용히 꺼져 있었다**(09-21 정식 반영 이후).
                        sim_max = _lp(spec["variation"]["looks"]["key"], None, self.treatment).get("face_sim_max")
                        face_embs = [e for e in (await loop.run_in_executor(
                            None, lambda: [identity.embed(Image.open(io.BytesIO(b)).convert("RGB")) for b, _n in faces]))
                                     if e is not None]
                    else:
                        person_b, person_f = None, None
                meta["person_ref"] = person_f                  # 익명 파생 파일명만 — 어떤 가공 인물을 썼는지 사후 대조용
                before_prompt = self.p_gen.adapt_prompt(spec["before_prompt"], "before")
                if person_b:
                    before_prompt = person_line + " " + before_prompt
                for pre in range(1, BEFORE_PRECHECK_TRIES + 1):
                    async with self._slots(self.p_gen):        # Before 도 공급자 한도를 탄다 — _slots 머리말이 근거
                        before_b = await loop.run_in_executor(None, self.p_gen.generate, before_prompt,
                                                              spec["aspect"], person_b, gen_refs, None)
                    meta["cost"] += self.pricing[self.p_gen.name]["generate"]
                    before = Image.open(io.BytesIO(before_b))
                    nfaces = await loop.run_in_executor(None, identity.big_faces, before)
                    if (nfaces or 0) >= 2:
                        meta.setdefault("before_precheck", []).append({"attempt": attempt, "try": pre, "faces": nfaces})
                        self._p(item_id, "before", attempt=attempt, note=f"콜라주 비포 다시 ({pre})")
                        continue
                    if face_embs:
                        # 참조와의 닮음 (2026-09-21 2차 연서님: 목표 0.3~0.5, 0.6 넘으면 재시도 — 넘으면 '그 사람'을 베낀 것).
                        #   못 재면(None) 통과시킨다(fail-open). 선검사 한도를 같이 쓴다 — 다 넘어도 마지막 장으로 진행하고 기록만 남긴다.
                        e = await loop.run_in_executor(None, identity.embed, before.convert("RGB"))
                        s = max(float((e * fe).sum()) for fe in face_embs) if e is not None else None
                        meta.setdefault("face_ref_sim", []).append({"attempt": attempt, "try": pre,
                                                                     "sim": None if s is None else round(s, 3)})
                        if s is not None and sim_max and s > float(sim_max) and pre < BEFORE_PRECHECK_TRIES:
                            self._p(item_id, "before", attempt=attempt, note=f"참조를 베낌({s:.2f}) 비포 다시 ({pre})")
                            continue
                    break
                pts = landmarks.detect(before)
                mask_img = landmarks.region_mask(before, pts, t["mask_region"]) if pts is not None and t["mask_region"] in landmarks.REGIONS else None

            # ② After — 시점마다 한 장. 시리즈가 아니면 시점 하나(종전과 같다). 참조는 항상 Before(After 를 다음 기준으로 쓰면 얼굴이 흘러간다)
            self._p(item_id, "after")
            # 시점별 After 는 **동시에** 그린다 (2026-09-15 초안). 셋 다 기준이 같은 Before 라 서로 기다릴 이유가 없다 —
            # 종전엔 직후→1주→4주를 한 장씩 차례로 그려 세트 1회가 '4장 시간'이었다(0915 07:55 실측 3회차 22분 30초).
            # 공급자 동시 한도는 self._slots(공급자) 가 배치 전체에서 지킨다 — Before·After 가 같은 슬롯을 쓰므로
            # 항목 3개 × 시점 3개 = 9콜이 한꺼번에 나가지 않고, Before 콜이 그 한도를 우회하지도 않는다.
            after_sem = self._slots(self.p_edit)              # 정본은 _slots 한 곳 (머리말이 근거)
            from .spec import looks_profile as _lp2
            _lpf = _lp2((spec["variation"].get("looks") or {}).get("key"), None, self.treatment) if self.mode == "selfie" else {}
            async def one_after(af):
                after_prompt = self.p_edit.adapt_prompt(af["after_prompt"], "after")
                async with after_sem:
                    if spec["generation"] == "edit":
                        # ⚠ 임상은 마스크를 모델에 **안 보낸다** (2026-09-15 저녁, 첫 실회차 연서님: "겹쳐놔도 전과 후가 똑같다").
                        #   마스크 편집은 마스크 밖을 픽셀 그대로 잠그므로 '같은 부스에서 따로 찍은 사진'(머리 위치·잔머리·
                        #   미세 주름 살짝 다름)이 원천적으로 불가능하고, 부위 안 변화도 마스크 경계에 눌려 약해진다.
                        #   마스크는 검수(구조·부위 안 변화 측정)에만 쓴다. 셀카는 종전 그대로.
                        mask_b = _png(mask_img) if (mask_img is not None and self.p_edit.supports_mask and self.mode != "clinical") else None
                        # 임상 After 스타일 참조 (2026-09-15 티모, 연서님 결정 안 "같은 리그 After 시점만 + 얼굴은 1번 사진").
                        #   고르기는 refs.pick 한 곳 — 리그·시점 필터가 거기 있다(여기서 다시 거르지 마라).
                        #   맞는 참조가 없으면 빈 목록 → 종전과 똑같은 1장 편집이고 문구도 안 붙는다.
                        #   스위치 = clinical_rig.yaml `after_style_refs` (켠 것/끈 것 동일인 점수 비교용).
                        #   2026-09-28 빌디 요청 ①: 고르기가 refs.clinical_after_style 로 바뀌었다(같은 리그 실제 After 1장,
                        #   시술·시점 무관). 무엇을 붙였는지 meta["after_style_ref"][시점] 에 남긴다(볼 전이 사후 대조용).
                        _esf = (refs.clinical_after_style(af.get("after_variation") or spec["variation"], self.treatment,
                                                          f"{self.batch_id}|{item_id}|{af['when']}")
                                if self.mode == "clinical" and self.p_edit.supports_style_refs
                                and load("clinical_rig.yaml").get("after_style_refs") else [])
                        edit_refs = [(refs.REF_DIR / f).read_bytes() for f in _esf]
                        if _esf:
                            meta.setdefault("after_style_ref", {})[af["when"]] = _esf[0]
                        if edit_refs:
                            after_prompt = after_prompt + " " + " ".join(
                                (ROOT / "config" / "prompts" / "edit_style_refs.md").read_text(encoding="utf-8").split())
                        after_b = await loop.run_in_executor(None, self.p_edit.edit, before_b, after_prompt, mask_b, edit_refs, spec["aspect"])
                        after = Image.open(io.BytesIO(after_b))
                        # A4: 마스크 밖 원본 복원 — **셀카만**. 임상은 끈다 (2026-09-15 연서님 결정, 티모 프로브
                        #   docs/clinical-prompt-v1-review-0915-teemo.md): 임상 v1 은 '같은 부스에서 따로 찍은 사진'이라
                        #   머리 위치·잔머리·미세 주름이 살짝 달라야 하는데, 합성은 그걸 Before 픽셀로 도로 덮고
                        #   얼굴만 복원(b)해도 이중 윤곽이 난다. 마스크 자체는 모델에 그대로 보낸다(편집 범위 안내용).
                        #   대신 정렬 허용을 4% 로 풀었다(clinical_rig.yaml tolerance) — 진짜 임상 쌍도 2.65% 움직인다.
                        if mask_img is not None and self.mode != "clinical":
                            after = landmarks.composite_outside_mask(before, after, mask_img)
                        cost = self.pricing[self.p_edit.name]["edit"]
                        # ── 임상 2단계 편집 (2026-09-28 연서님) ─────────────────────────────────────────
                        #   v49 확대 비교: 마스크 없는 1장 편집은 사진을 통째로 다시 찍을 뿐 팔자를 따로 안 건드린다
                        #   (부위 쏠림 = 부위 안 변화 ÷ 밖 변화 0.68~1.1배, 채택 컷도 같음). 그래서 1단계 결과 위에
                        #   **After 자신의 얼굴 점으로 만든 부위 마스크**로 한 번 더 편집해 골만 옅게 한다.
                        #   합성은 마스크 안만 — 모델 출력은 자리가 살짝 밀려 오므로 먼저 겹친다(landmarks.align_to, 09-18).
                        #   얼굴 점을 못 찾거나 겹치기 실패면 1단계 그대로(fail-open), 무엇이 일어났는지 meta["second_pass"] 에 남긴다.
                        _sp = load("clinical_rig.yaml").get("second_pass") or {}
                        if (self.mode == "clinical" and _sp.get("enabled") and af.get("second_pass_prompt")
                                and self.p_edit.supports_mask and t["mask_region"] in landmarks.REGIONS):
                            _rec = {"applied": False}
                            _pa1 = await loop.run_in_executor(None, landmarks.detect, after)
                            if _pa1 is None:
                                _rec["reason"] = "1단계 After 얼굴 점 못 찾음"
                            else:
                                _m2 = landmarks.region_mask(after, _pa1, t["mask_region"], feather=int(_sp.get("feather", 14)))
                                # 골 깊이 참조(2026-09-28 6차 연서님): 실제 After 1장을 2번 이미지로 — 마스크는 1번에만 걸린다(openai_img.edit).
                                _dr = _sp.get("depth_ref")
                                _refs2 = [(refs.REF_DIR / _dr).read_bytes()] if _dr and self.p_edit.supports_style_refs else []
                                _p2 = af["second_pass_prompt"] + (" " + " ".join((ROOT / "config" / "prompts" / "pass2_depth_ref.md")
                                                                              .read_text(encoding="utf-8").split()) if _refs2 else "")
                                _b2 = await loop.run_in_executor(None, self.p_edit.edit, after_b,
                                                                 self.p_edit.adapt_prompt(_p2, "after"),
                                                                 _png(_m2), _refs2, spec["aspect"])
                                _rec["depth_ref"] = _dr if _refs2 else None
                                cost += self.pricing[self.p_edit.name]["edit"]
                                _a2, _info = await loop.run_in_executor(None, landmarks.align_to, after, Image.open(io.BytesIO(_b2)))
                                if _info is None:
                                    _rec["reason"] = "2단계 결과 겹치기 실패 — 1단계 유지"
                                else:
                                    # 1단계 원본은 비교용으로 남긴다(검수 화면 파일 규칙 밖 이름 — 목록엔 안 뜬다)
                                    _d = self.dir / item_id; _d.mkdir(parents=True, exist_ok=True)
                                    after.convert("RGB").save(_d / f"pass1_{af['when']}_a{attempt}.jpg", quality=92)
                                    after = Image.composite(_a2.convert("RGB"), after.convert("RGB"), _m2)
                                    _rec = {**_rec, "applied": True, **_info}
                            meta.setdefault("second_pass", {})[af["when"]] = _rec
                    else:
                        # After 는 그 시점 전용 참조까지 받는다(직후 컷엔 직후 실사진이 붙는다)
                        after_refs = self._refs(af.get("after_variation") or variation, af["when"])
                        if self.mode == "clinical":
                            # 임상 새로 그리기(2026-09-28 7차 연서님 B) — 편집 경로와 같은 부스 사진 1장을 2번 이미지로(고르기 = refs.clinical_after_style).
                            _esf = (refs.clinical_after_style(af.get("after_variation") or spec["variation"], self.treatment,
                                                              f"{self.batch_id}|{item_id}|{af['when']}")
                                    if load("clinical_rig.yaml").get("after_style_refs") else [])
                            after_refs = [(refs.REF_DIR / f).read_bytes() for f in _esf]
                            if _esf:
                                meta.setdefault("after_style_ref", {})[af["when"]] = _esf[0]
                                after_prompt = after_prompt + " " + " ".join(
                                    (ROOT / "config" / "prompts" / "edit_style_refs.md").read_text(encoding="utf-8").split())
                        # 미모 After 참조 = 얼굴만 오린 Before (2026-09-22 연서님, variations.yaml `before_ref: face_crop`).
                        #   통째 Before 는 고개·자세·화면 위치까지 따라 그리게 했다(v39 복붙 5/6). 얼굴 미검출이면 종전대로.
                        #   재시도(After 만 다시)도 같은 참조를 쓴다 — ref_b 는 이 함수 안에서만 산다.
                        #   09-22 v40 검수 "얼굴만 오리니 머리·두상이 달라져 다른 사람 같다" → head_crop(머리카락 포함)이 기본,
                        #   분할 실패면 face_crop, 그것도 안 되면 통째(fail-open). 실제로 쓴 것을 meta["before_ref"] 에 남긴다.
                        ref_b = before_b
                        _mode_ref = _lpf.get("before_ref")
                        if _mode_ref in ("head_crop", "face_crop") and pts is not None:
                            _hc = await loop.run_in_executor(None, landmarks.head_crop, before, pts) if _mode_ref == "head_crop" else None
                            _fc = _hc if _hc is not None else landmarks.face_crop(before, pts)
                            if _fc is not None:
                                ref_b = _png(_fc)
                                after_prompt = after_prompt + " " + (HEAD_CROP_LINE if _hc is not None else FACE_CROP_LINE)
                                meta.setdefault("before_ref", {})[af["when"]] = "head_crop" if _hc is not None else "face_crop"
                        # 자세 참조 (2026-09-22 연서님 v43 검수, variations.yaml `pose_ref: true`): 입력 1 = 이 사람(Before 통째),
                        #   입력 2 = Before 와 각도가 다른 노션 컷. 고르기는 refs.pose_ref 한 곳, 재시도는 같은 장(컷 키 해시).
                        #   Before 미검출이면 종전 경로(fail-open). 무엇을 붙였는지 meta["pose_ref"][시점] 에 남긴다.
                        if _lpf.get("pose_ref") and ref_b is before_b:
                            _pr = await loop.run_in_executor(None, refs.pose_ref, pts, f"{self.batch_id}|{item_id}|{af['when']}")
                            if _pr is not None:
                                after_refs = [_pr[0]] + list(after_refs or [])
                                after_prompt = after_prompt + " " + refs.POSE_LINE
                                meta.setdefault("pose_ref", {})[af["when"]] = {"attempt": attempt, **_pr[2]}
                        after_b = await loop.run_in_executor(None, self.p_edit.generate, after_prompt, spec["aspect"], ref_b, after_refs, None)
                        after = Image.open(io.BytesIO(after_b))
                        cost = self.pricing[self.p_edit.name]["generate"]
                        # 직후 패치 위치 게이트 — C안 (2026-09-18 빌디/연서님: 후처리 접고 좌표 계산은 채점으로만).
                        #   그려진 패치가 계산 자리(허용 = 홍채 지름 1개)에 없으면 **이 직후 컷만** 다시 그린다 — 세트 재시도로
                        #   넘기면 Before·2주까지 다시 사서 비용이 3배다. 스위치·횟수 = treatments.yaml `patch_gate` → spec 의 af["patch_gate"](없으면 끔).
                        #   None(못 잼)은 재생성 사유가 아니다(patchgate 머리말). 원장 = meta["patch_gate"][시점] = 회차별 결과 목록.
                        #   09-18 오후 연서님: 재시도 최대 3번(yaml), 다 떨어져도 **버리지 않는다** — 그린 컷 중 계산 자리에
                        #   가장 가까운 것(patchgate.closeness)을 남기고 meta["patch_gate_final"][시점].passed=False 로
                        #   검수 화면에 '위치 게이트 미통과'를 띄운다. 세트 탈락 사유(fail_reasons)엔 넣지 않는다 — 사람이 판단한다.
                        tries = int(af.get("patch_gate") or 0)          # spec 이 직후 컷에만 실어 보낸다
                        if tries:
                            glog = meta.setdefault("patch_gate", {}).setdefault(af["when"], [])
                            best = None                                 # (closeness, try, 컷, 결과)
                            for g in range(tries + 1):
                                gr = await loop.run_in_executor(None, patchgate.check, after, self.p_qa)
                                cost += patchgate.DETECT_COST * (gr.get("calls") or 1)   # 짚기는 Gemini(p_qa 아님), 09-18 밤부터 좌우 조각 따로
                                glog.append({"attempt": attempt, "try": g, **{k: gr.get(k) for k in ("passed", "reasons", "n", "inside", "outside", "total", "unmeasured", "scale", "offsets", "note")}})
                                if best is None or patchgate.closeness(gr) > best[0]:
                                    best = (patchgate.closeness(gr), g, after, gr)
                                if gr.get("passed") is not False or g == tries:
                                    break
                                after_b = await loop.run_in_executor(None, self.p_edit.generate, after_prompt, spec["aspect"], ref_b, after_refs, None)
                                after = Image.open(io.BytesIO(after_b))
                                cost += self.pricing[self.p_edit.name]["generate"]
                            if gr.get("passed") is False:               # 끝까지 떨어짐 → 가장 가까운 컷으로 되돌린다
                                after, gr = best[2], best[3]
                            meta.setdefault("patch_gate_final", {})[af["when"]] = {
                                "attempt": attempt, "passed": gr.get("passed"), "reasons": gr.get("reasons") or [],
                                "kept_try": best[1] if gr is best[3] else g, "draws": g + 1,
                                "inside": gr.get("inside"), "n": gr.get("n"), "outside": gr.get("outside"),
                                "total": gr.get("total"), "unmeasured": gr.get("unmeasured"), "scale": gr.get("scale"),
                                "offsets": gr.get("offsets")}
                # ── 임상 골 메우기 + 재촬영 (2026-09-28 12차 연서님 "11차 설정을 임상 기본으로: B → 골 메우기 목표~1.5배 → 재촬영 → 게이트") ──
                #   B(새로 그린 After)는 '다른 날 사진' 역할만 하고 효과는 여기서 낸다 — 편집·생성 모델은 팔자를 옅게 하지 않았다(v49~v52).
                #   ① bna.foldlift.fill_to: 골 선 선명도를 **이 세트 Before 대비** edge_pct(실제 쌍 -43.7% 와 1.5배 -65.6% 의 사이 -54.6%)로,
                #      그늘은 Before 대비 -50% 까지만 보조. 콧볼 바로 옆 그늘은 원래 남는다(11차 연서님 — 지우지 않는다: 띠·문턱 그대로).
                #   ② 편집 모델 '그대로 다시 촬영'(prompts/retake_clinical.md) — 메운 자리의 매끈함을 모공 결로 되돌린다(10차: 골은 거의 안 되살아남).
                #   얼굴 점을 못 찾으면 ①은 건너뛰고(fail-open) ②도 안 한다. 무엇을 했는지 meta["fold_fill"][시점] 에 남긴다.
                #   메우기 직전 B 원본은 fold_b_<시점>_a<회차>.jpg 로 보존(검수 화면 파일 규칙 밖 이름).
                _ff = load("clinical_rig.yaml").get("fold_fill") or {}
                if self.mode == "clinical" and _ff.get("enabled"):
                    from . import foldlift as _fl
                    _eb = await loop.run_in_executor(None, _fl.edge_ratio, before)
                    _sb = await loop.run_in_executor(None, _fl.shade, before)
                    _rec = {"applied": False}
                    if _eb and _sb:
                        _d = self.dir / item_id; _d.mkdir(parents=True, exist_ok=True)
                        after.convert("RGB").save(_d / f"fold_b_{af['when']}_a{attempt}.jpg", quality=92)
                        # 14차: shade_pct: null = 그늘 밝히기 끔(연서님 "포토샵으로 지운 느낌")
                        _sp = _ff.get("shade_pct")
                        _filled, _fi = await loop.run_in_executor(
                            None, lambda: _fl.fill_to(after, _eb * (1 + float(_ff["edge_pct"]) / 100.0),
                                                      None if _sp is None else _sb * (1 + float(_sp) / 100.0)))
                        _wm = _fi.pop("_wm", None)           # 띠 지도(배열) — 원장에 넣지 않고 재촬영 뒤 띠 자에만 쓴다
                        _rec = {**_fi, "edge_before_img": round(_eb, 3), "edge_pct": _ff["edge_pct"]}
                        if _fi.get("applied") and _ff.get("side_gap_max") is not None:
                            # 좌우 자 ① (13차): 메운 직후 좌우 감소율 차가 크면 약한 쪽만 더 메운다(비용 0) — bna.foldlift.balance_sides
                            _filled, _bi = await loop.run_in_executor(
                                None, lambda: _fl.balance_sides(before, _filled, float(_ff["side_gap_max"])))
                            _rec["side_fill"] = _bi
                        if _fi.get("applied"):
                            after = _filled
                            if _ff.get("retake"):
                                _bb = io.BytesIO(); after.convert("RGB").save(_bb, "PNG")
                                _rp = " ".join((ROOT / "config" / "prompts" / "retake_clinical.md").read_text(encoding="utf-8").split())
                                if af.get("retake_keep_marks"):
                                    # 14차 연서님 A: 직후 컷 재촬영이 투명 패치를 통째로 지웠다(v54 0003 immediate_look 2회 탈락).
                                    #   시점 판정은 spec 한 곳(retake_keep_marks) — 배치가 시점 이름을 다시 보지 않는다(selftest 규칙 두 벌 금지)
                                    _rp += " " + " ".join(str(load("clinical_rig.yaml").get("retake_keep_marks") or "").split())
                                # 15차 연서님 "전 사진을 피부 결 참조로 같이 넣어 '이 결 그대로'로" — 칸이 있으면 Before 를 2번으로
                                _tr = " ".join(str(load("clinical_rig.yaml").get("retake_texture_ref") or "").split())
                                _refs = []
                                if _tr:
                                    _b2 = io.BytesIO(); before.convert("RGB").save(_b2, "PNG")
                                    _refs = [_b2.getvalue()]
                                    _rp += " " + _tr
                                _rb = await loop.run_in_executor(None, self.p_edit.edit, _bb.getvalue(),
                                                                 self.p_edit.adapt_prompt(_rp, "after"), None, _refs, spec["aspect"])
                                _rec["retake_texture_ref"] = bool(_refs)
                                cost += self.pricing[self.p_edit.name]["edit"]
                                _ra = Image.open(io.BytesIO(_rb)).convert("RGB")
                                after = _ra if _ra.size == after.size else _ra.resize(after.size, Image.LANCZOS)
                                _rec["retake"] = True
                            _rec["edge_final"] = round(await loop.run_in_executor(None, _fl.edge_ratio, after) or 0, 3)
                            # 좌우 자 ② (13차): 재촬영 뒤 최종 좌우 차 — 검수 단계가 이 값으로 'fold_asym' 을 건다(After 만 다시)
                            _rec["side_final"] = await loop.run_in_executor(None, _fl.side_drop, before, after)
                            # 띠 안팎 자 (14차): 최종 컷을 메우기 때 찾은 같은 띠로 — 검수 단계가 band_gate 로 'fold_band' 를 건다
                            if _wm is not None:
                                _rec["band_final"] = await loop.run_in_executor(None, _fl.band_stats, after, _wm)
                            # 반복 무늬 자 (15차): 띠 안·얼굴 전체 '도장 조각 비율' — 검수 단계가 repeat_gate 로 'stamp' 를 건다
                            _rec["repeat_final"] = await loop.run_in_executor(None, _fl.repeat_stats, after, _wm)
                    meta.setdefault("fold_fill", {})[af["when"]] = _rec
                if af.get("patch_film"):
                    # 21차 (09-29 연서님): 패치 문장 없이 그린 직후 컷에 막을 얹는다 — 자 계측 뒤·검수와 저장 앞이라
                    #   검수함·대시보드에 합성본이 뜬다(첫 시험은 tools 에서만 얹어 대시보드엔 원본이 떴다). 실패는 원본 그대로(fail-open).
                    after, _pf = await loop.run_in_executor(
                        None, lambda: patchfilm.apply(after, patchfilm.seed_for(self.batch_id, item_id, attempt)))
                    meta.setdefault("patch_film", {})[af["when"]] = _pf
                return af["when"], af, after, cost
            # ⚠ `return_exceptions=True` 로 받는다 (2026-09-15 티모). 기본값이면 첫 예외가 **즉시** 올라오고
            #   나머지 시점은 취소도 안 된 채 계속 도는데, 그 장들은 **이미 돈을 쓴 호출**이라 meta["cost"] 에
            #   한 푼도 안 남는다(대역 실측: 2번째 After 가 터졌는데 유료 호출 3건이 다 나갔고 원장은 0).
            #   그 원장이 cost_cap 정지 조건의 근거이기도 하다 — 병렬로 바꾼 자리에서 새로 생긴 구멍이다.
            #   그래서 전부 기다려 **비용을 먼저 적고** 나서 첫 예외를 올린다.
            results = await asyncio.gather(*(one_after(af) for af in spec["afters"]), return_exceptions=True)
            afters_out = []                                  # [(when, af, after_img)] — 시점 순서는 spec 그대로
            for r in results:
                if not isinstance(r, BaseException):
                    when, af, after, cost = r
                    meta["cost"] += cost
                    afters_out.append((when, af, after))
            err = next((r for r in results if isinstance(r, BaseException)), None)
            if err is not None:
                meta["after_error"] = repr(err)[:300]         # 원장에 남긴다 — 조용히 넘어가는 갈래를 만들지 않는다
                # meta 는 예외와 함께 사라지므로 비용은 **progress 에** 적고 올린다(단계는 그대로 둔다).
                self._p(item_id, "after", cost=meta["cost"], note=meta["after_error"])
                raise err

            # ③ 후처리 (세트 동일 seed)
            self._p(item_id, "postprocess")
            pp_seed = hash((self.batch_id, item_id, attempt)) & 0xFFFF
            q_before = variation["quality"]["key"]
            before_out = postprocess.apply(before, q_before, self.mode, pp_seed)
            before_pp = Image.open(io.BytesIO(before_out))
            outs = []                                        # [(when, bytes, img, ungate)]
            for when, af, after in afters_out:
                q_after = af["after_variation"]["quality"]["key"]
                ab = postprocess.apply(after, q_after, self.mode, pp_seed)
                # 강도를 낮춘 시점(직후·1주)은 `effect_visible` 을 묻긴 하되 **탈락 사유로 쓰지 않는다** —
                # 프롬프트가 "거의 안 보이게" 시켜 놓고 검수가 "눈에 띄어야 한다"로 재면 지시를 지킬수록 떨어진다.
                # 판정은 spec 이 만들 때 실어 보낸 `effect_ungated` 하나다(여기서 시점 이름을 다시 보지 마라).
                # 2026-09-18: 종전엔 `effect_lowered`(강도를 낮춘 컷)만 봤다 — 직후 컷은 최종 강도인데
                # 프롬프트가 흔적·붓기를 시켜서 같은 모양으로 떨어졌다. 사유·근거는 spec.build_after 주석.
                ungate = ("effect_visible",) if af.get("effect_ungated") else ()
                # 미모 프로필 기록 전용 항목(2026-09-22 연서님 "눈 가림 검사가 눈 멀쩡한 컷을 2점으로 탈락" → eyes_uncovered).
                ungate = tuple(ungate) + tuple(x for x in (_lpf.get("ungate") or []) if x not in ungate)
                outs.append((when, ab, Image.open(io.BytesIO(ab)), ungate))

            # ④ 검수 3단 — After 마다. 세트는 전부 통과해야 통과. 시점별 결과는 meta["after_results"][when] 에 남긴다
            self._p(item_id, "qa")
            meta["after_results"] = {}
            for when, ab, after_pp, ungate in outs:
                r = {"fail_reasons": []}
                st = structure.check(before_pp, after_pp, self.mode, t["mask_region"],
                                     copy_head_only=_lpf.get("copy_gate") == "head",
                                     copy_roll_deg=_lpf.get("copy_roll_deg")); r["structure"] = st
                # passed 는 3값이다 — True(통과) / False(탈락) / None(못 잼). None 을 실패로 세면 같은 컷에 돈만 쓴다.
                if st.get("passed") is False:
                    # 임상 구조 자 기록 전용 (2026-09-28 연서님 "기계가 먼저 버리지 말고 다 보여줘" — v47 r2 에서 연서님이 괜찮게 본
                    #   1·2번 시도가 구조 자로 버려지고 3번째만 남았다). 수치는 meta 에 그대로, 탈락·재시도만 안 한다.
                    if self.mode == "clinical" and load("clinical_rig.yaml").get("structure_record_only"):
                        st["record_only"] = True
                    else:
                        r["fail_reasons"].append("structure")
                # 복붙 게이트 — 구조와 **따로** 센다(같은 칸에 넣으면 "왜 떨어졌나"가 뭉개진다).
                # 3값이라 None(임상·미검출)은 실패가 아니다. 근거·컷은 structure.copy_check 머리말.
                if (st.get("copy") or {}).get("passed") is False:
                    r["fail_reasons"].append("copy")
                # 좌우 자 ② (2026-09-28 13차 연서님 "한쪽만 메워져서 티가 나 — 차이가 크면 다시"): 재촬영 뒤 좌우 골 선 감소율 차가
                #   side_gap_max(%p) 를 넘으면 'fold_asym' — After 만 다시 그린다. 못 쟀으면(None) 걸지 않는다(fail-open).
                _gmax = (load("clinical_rig.yaml").get("fold_fill") or {}).get("side_gap_max") if self.mode == "clinical" else None
                _gap = ((((meta.get("fold_fill") or {}).get(when) or {}).get("side_final")) or {}).get("gap")
                # 14차 연서님 A: "좌우 자 대신 더 세게 메우기" + "좌우 자·3/4 탈락이 사람 눈보다 엄격해"(옛 시도 0001-t2 등 채택)
                #   → side_gate: false 면 기록만(side_final 은 원장에 남는다).
                _sg = (load("clinical_rig.yaml").get("fold_fill") or {}).get("side_gate", True)
                if _sg and _gmax is not None and _gap is not None and _gap > float(_gmax):
                    r["fail_reasons"].append("fold_asym")
                # 띠 안팎 자 (2026-09-28 14차 연서님 "띠 안팎 밝기 차·잡티 밀도 차를 재는 자 추가해서 튀면 다시"): 'fold_band' — After 만 다시.
                #   못 쟀으면 걸지 않는다(fail-open). 문턱 = clinical_rig.yaml fold_fill.band_gate, 판정 = foldlift.band_gate 하나.
                # 옷 색 자 (2026-09-28 14차 연서님 "1주 이후인데 같으면 After만 다시"): 옷을 추첨한 컷(1주~)만. 문턱 = clinical_rig
                #   clothes_gate.dE_min — 같은 옷 실측 ΔE 0~7.3(임상 배치 4개 50쌍). 못 재면 걸지 않는다(fail-open).
                _af_w = next((x for x in spec["afters"] if x["when"] == when), {})
                _cg = load("clinical_rig.yaml").get("clothes_gate") or {} if self.mode == "clinical" else {}
                if _af_w.get("clothes") and _cg.get("dE_min") is not None:
                    from .qa import clothes as _qcl
                    _cd = _qcl.clothes_diff(before_pp, after_pp)
                    r["clothes"] = {**_cd, "wanted": _af_w["clothes"]}
                    if _cd["dE"] is not None and _cd["dE"] < float(_cg["dE_min"]):
                        r["fail_reasons"].append("same_clothes")
                if self.mode == "clinical":
                    from . import foldlift as _flg
                    _bf = (((meta.get("fold_fill") or {}).get(when) or {}).get("band_final"))
                    _bbad = _flg.band_gate(_bf, (load("clinical_rig.yaml").get("fold_fill") or {}).get("band_gate"))
                    if _bbad:
                        r["fail_reasons"].append("fold_band")
                        r["fold_band"] = _bbad
                    # 반복 무늬 자 (15차 연서님 "튀면 다시"): 'stamp' — After 만 다시. 못 쟀으면 걸지 않는다(fail-open).
                    _rf = (((meta.get("fold_fill") or {}).get(when) or {}).get("repeat_final"))
                    _rbad = _flg.repeat_gate(_rf, (load("clinical_rig.yaml").get("fold_fill") or {}).get("repeat_gate"))
                    if _rbad:
                        r["fail_reasons"].append("stamp")
                        r["stamp"] = _rbad
                idn = identity.check(before_pp, after_pp); r["identity"] = idn
                # 미모 '너무 같음'은 닮음도 높을 때만 탈락 (2026-09-28 연서님 "키는 걸로", 근거 structure.copy_sim_waive).
                if "copy" in r["fail_reasons"] and structure.copy_sim_waive(st.get("copy"), idn.get("similarity"),
                                                                            _lpf.get("copy_sim_min")):
                    r["fail_reasons"].remove("copy")
                    st["copy"]["waived"] = f"닮음 {idn['similarity']:.3f} < {_lpf['copy_sim_min']} — 다시 그린 얼굴로 봄(기록만)"
                # 임상 '너무 같음' (2026-09-28 빌디 요청 ②) — 셀카 자(copy_check)는 임상에서 None 이다. 임상은 닮음 상한·정렬 하한·
                #   기울기 인정으로 따로 잰다(근거·컷 = clinical_rig.yaml copy_gate). 사유 이름은 셀카와 같은 'copy'.
                if self.mode == "clinical":
                    cc = structure.clinical_copy_check(st, idn.get("similarity"), load("clinical_rig.yaml").get("copy_gate"))
                    st["copy"] = cc
                    if cc.get("passed") is False:
                        # record_only(09-28 1회차 6/6 탈락 뒤) — 재고 남기되 탈락시키지 않는다. 판정은 원장 copy.passed 로 사후 대조.
                        if (load("clinical_rig.yaml").get("copy_gate") or {}).get("record_only"):
                            cc["record_only"] = True
                        else:
                            r["fail_reasons"].append("copy")
                # '사람 확인 구간'(0.45~0.60)도 재시도로 돌린다 — 2026-09-10 성연서님 지시.
                # 종전엔 gate="review" 를 hard_fail=False 로 흘려보내 기계가 통과시켰고,
                # 그 컷(0910 실측 0.461 1건)이 "전·후가 다른 사람"으로 사람 눈에 걸렸다.
                # 마지막 회차까지 review 면 그때는 통과시킨다 — 애매한 걸 버리는 것보다
                # 사람에게 보이는 쪽이 낫다(사진은 남아 있고 최종 판단은 사람이 한다).
                if idn.get("gate") == "review" and attempt < MAX_ATTEMPTS:
                    r["fail_reasons"].append("identity_review")
                if idn["hard_fail"]:
                    r["fail_reasons"].append("identity")
                if idn.get("collage"):                          # 한 장에 큰 얼굴이 둘 = before/after 콜라주 (2026-09-15)
                    # 어느 쪽이 콜라주인지로 사유를 가른다 — Before 면 그 Before 를 버려야 하고(REDO_BEFORE),
                    # After 면 Before 는 멀쩡하니 After 만 다시 그린다. 안 가르면 둘 중 하나가 늘 틀린다.
                    r["fail_reasons"].append("collage_before" if ((idn.get("faces") or {}).get("before") or 0) >= 2 else "collage")
                if not r["fail_reasons"]:
                    # 직후 컷 전용 자 (2026-09-22 연서님 "효과 면제는 이해하는데 대신 거는 자가 없어") — 직후는
                    #   immediate_look 으로 통과/탈락하고 effect_visible 은 기록만(qa_checklist.yaml items_immediate 머리말).
                    #   판정은 spec 이 실어 보낸 qa_extra 하나(시점 이름을 여기서 다시 보지 마라 — 규칙 두 벌 금지).
                    _qx = next((a.get("qa_extra") for w2, a, _i in afters_out if w2 == when), None)
                    vs = await loop.run_in_executor(None, vision.score, before_out, ab, self.mode, self.p_qa, ungate, _qx)
                    r["vision"] = vs; meta["cost"] += self.pricing[self.p_qa.name]["qa"]
                    r["fail_reasons"] += [f"vision:{k}" for k in vs["failed_items"]]
                meta["after_results"][when] = r
                meta["fail_reasons"] += [f if len(outs) == 1 else f"{f}@{when}" for f in r["fail_reasons"]]
            # ④-2 시점끼리 복붙 계측 (2026-09-18, **기록 전용 · 탈락 사유 아님**)
            #   종전 복붙 게이트는 Before↔After 만 잰다 — 직후↔2주 끼리 같은 그림인지는 아무도 안 봤고
            #   연서님 검수 ③("세 장이 똑같다")이 바로 그 구간이다. 여기서 바로 게이트로 쓰지 않는 이유:
            #   09-17 6세트 실측에서 **사람이 채택한 세트**도 Before↔2주 head_diff 가 0.0086 이라,
            #   같은 자를 시점끼리 걸면 통과분까지 죽는다(임계는 '걸린 것 중 사람이 reject 했던 비율'로
            #   고른다 — 09-14 교훈). 먼저 값만 모으고 분포를 본 뒤 정한다. 추가 API 호출 0(랜드마크는 로컬).
            if len(outs) >= 2 and self.mode == "selfie":
                meta["series_copy"] = {}
                for (w0, _b0, img0, _u0), (w1, _b1, img1, _u1) in zip(outs, outs[1:]):
                    p0, p1 = landmarks.detect(img0), landmarks.detect(img1)
                    meta["series_copy"][f"{w0}->{w1}"] = structure.copy_check(p0, p1, self.mode)
            # 대표(마지막 시점) 결과는 종전 키에도 — 화면·통계가 그대로 읽게
            last = meta["after_results"][outs[-1][0]]
            meta["structure"], meta["identity"] = last["structure"], last["identity"]
            if "vision" in last:
                meta["vision"] = last["vision"]
            if not meta["fail_reasons"]:
                dd = dedup.check(before_pp, f"{self.batch_id}/{item_id}", self.registry); meta["dedup"] = dd
                if not dd["passed"]:
                    meta["fail_reasons"].append("duplicate")
            after_out = outs[-1][1]
            after_outs = {when: ab for when, ab, _img, _ung in outs}

            meta["passed"] = not meta["fail_reasons"]
            meta["mask_file"] = "mask.png" if mask_img is not None else None
            meta["series"] = self.series
            self._save(item_id, meta, before_out, after_out, mask_img, after_outs if self.series else None)
            if meta["passed"]:
                self._p(item_id, "passed", passed=True, fail_reasons=[], cost=meta["cost"]); break
            meta["attempts_log"].append({"attempt": attempt, "fail_reasons": list(meta["fail_reasons"]), "at": time.time()})
            if attempt < MAX_ATTEMPTS:
                # 재시도 전 컷 보존 (2026-09-28 연서님 "재시도 전 컷도 검수함에 남게") — 다음 회차가 같은 이름 파일을 덮어쓰거나
                #   조건을 다시 뽑아 옆에 쌓여도 화면은 마지막 쌍만 보여서, 사람이 본 컷이 사라졌다(v47 r2 0001).
                #   형제 항목 `<id>-t<n>` 으로 따로 저장한다(검수함에 한 줄로 뜬다). 비용은 본 항목에 이미 있으니 0으로(이중 집계 금지).
                snap = {**meta, "item_id": f"{item_id}-t{attempt}", "retry_snapshot": True, "snapshot_of": item_id,
                        "passed": False, "cost": 0.0, "attempt": attempt}
                self._save(snap["item_id"], snap, before_out, after_out, mask_img, after_outs if self.series else None)
            self._p(item_id, "retry" if attempt < MAX_ATTEMPTS else "failed", passed=False, fail_reasons=list(meta["fail_reasons"]), cost=meta["cost"])
            prev_fail = list(meta["fail_reasons"])      # 다음 회차가 "무엇을 다시 할지" 고르는 근거
        return meta

    def _should_stop(self):
        if self.stopped or not self.progress:
            return self.stopped
        passed, cost = self.progress.totals()
        if self.target_pass and passed >= self.target_pass:
            self.stopped = f"target_pass:{passed}"
        elif self.cost_cap and cost >= self.cost_cap:
            self.stopped = f"cost_cap:{cost:.2f}"
        return self.stopped

    def _p(self, item_id, stage, **kw):
        if self.progress:
            self.progress.set(item_id, stage, **kw)

    def _save(self, item_id, meta, before_b, after_b, mask_img=None, after_outs=None):
        v = meta["variation"]; d = self.dir / item_id; d.mkdir(parents=True, exist_ok=True)
        stem = f'{self.treatment}_{self.mode}_{v["country"]["key"]}{v["age"]["key"]}{v["gender"]["key"][0]}_{item_id}'
        (d / f"{stem}_before.jpg").write_bytes(before_b)
        if after_outs:                                       # 시리즈: 시점마다 _after_<when>.jpg (마지막 시점이 _after.jpg 역할)
            for when, ab in after_outs.items():
                (d / f"{stem}_after_{when}.jpg").write_bytes(ab)
        else:
            (d / f"{stem}_after.jpg").write_bytes(after_b)
        if mask_img is not None:
            mask_img.save(d / "mask.png")
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    # ---------- 배치 ----------
    async def run(self):
        # 과거 배치가 쓴 인물 조합을 피해서 뽑는다 — 안 그러면 같은 seed 로 두 번 돌린 배치가
        # 인물 명단째로 겹친다(2026-09-09 실측, planner 머리말).
        plans = plan_batch(self.mode, self.count, self.seed, self.fixed, (self.avoid or {}).get("weights"),
                           treatment=self.treatment, avoid_sigs=past_signatures(),
                           avoid_scene_sigs=past_scene_signatures())
        remember(plans, self.batch_id)
        done = set(json.loads(self.state_path.read_text()).get("done", [])) if self.state_path.exists() else set()
        sem = asyncio.Semaphore(min(self.p_gen.concurrency, self.p_edit.concurrency))
        # 이미지 콜(최대 칸 수)·채점·얼굴 검사가 전부 기본 스레드 풀을 나눠 쓴다 (2026-09-15, 칸 3 → 10).
        # 기본 풀은 CPU+4(이 PC 16)라 이미지 10콜이 자는 동안 채점이 줄을 선다 — 넉넉히 연다(스레드는 대부분 네트워크 대기).
        from concurrent.futures import ThreadPoolExecutor
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=32))
        self._slots(self.p_gen); self._slots(self.p_edit)     # 공급자 동시 한도를 이 루프에 맞춰 준비 (정본=_slots)
        self.dir.mkdir(parents=True, exist_ok=True)   # 여기가 첫 쓰기 — 생성자가 아니라 이 자리에서 만든다
        self.progress = Progress(self.dir, len(plans))
        for i in done:
            self.progress.set(i, "passed", passed=True)   # 이어하기: 이미 끝난 항목
        results = []

        async def guarded(i, v):
            if f"{i:04d}" in done:
                return None
            async with sem:
                if self._should_stop():
                    return None
                m = await self.run_item(i, v)
            done.add(m["item_id"]); self.state_path.write_text(json.dumps({"done": sorted(done)}))
            return m

        try:
            results = [r for r in await asyncio.gather(*(guarded(i, v) for i, v in enumerate(plans))) if r]
        except Exception as e:
            self.progress.finish(error=repr(e)); raise
        write_manifest(self.dir, results)
        s = summarize(results); s["stopped"] = self.stopped
        (self.dir / "stats.json").write_text(json.dumps(s, ensure_ascii=False, indent=1))
        self.progress.finish(stopped=self.stopped)
        return s

    def estimate(self, expected_pass_rate=0.5) -> dict:
        n_after = len(self.series) if self.series else 1      # 시리즈는 After 마다 생성·검수 호출이 든다
        per_try = (self.pricing[self.p_gen.name]["generate"]
                   + n_after * (self.pricing[self.p_edit.name]["edit" if self.mode == "clinical" else "generate"] + self.pricing[self.p_qa.name]["qa"]))
        tries = self.count * min(MAX_ATTEMPTS, 1 / max(expected_pass_rate, 0.05))
        return {"items": self.count, "expected_calls": round(tries), "expected_cost_usd": round(per_try * tries, 2)}


def _png(img: Image.Image) -> bytes:
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()
