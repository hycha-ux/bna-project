"""배치 오케스트레이션: 생성 → After → 후처리 → 3단 검수 → 판정/재시도 → 저장.
asyncio 워커 풀, 이어하기(state.json), 프롬프트 버전 기록."""
import asyncio, io, json, time, uuid
from pathlib import Path
from PIL import Image
from .spec import ROOT, load, build_prompts, defaults_for
from .planner import plan_batch, past_signatures, past_scene_signatures, remember
from . import postprocess, refs, providers
from .qa import structure, identity, dedup, vision, landmarks
from .stats import summarize, write_manifest
from .version import prompt_version
from .progress import Progress

MAX_ATTEMPTS = 3
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
                for pre in range(1, BEFORE_PRECHECK_TRIES + 1):
                    async with self._slots(self.p_gen):        # Before 도 공급자 한도를 탄다 — _slots 머리말이 근거
                        before_b = await loop.run_in_executor(None, self.p_gen.generate, self.p_gen.adapt_prompt(spec["before_prompt"], "before"),
                                                              spec["aspect"], None, style_refs, None)
                    meta["cost"] += self.pricing[self.p_gen.name]["generate"]
                    before = Image.open(io.BytesIO(before_b))
                    nfaces = await loop.run_in_executor(None, identity.big_faces, before)
                    if (nfaces or 0) < 2:
                        break
                    meta.setdefault("before_precheck", []).append({"attempt": attempt, "try": pre, "faces": nfaces})
                    self._p(item_id, "before", attempt=attempt, note=f"콜라주 비포 다시 ({pre})")
                pts = landmarks.detect(before)
                mask_img = landmarks.region_mask(before, pts, t["mask_region"]) if pts is not None and t["mask_region"] in landmarks.REGIONS else None

            # ② After — 시점마다 한 장. 시리즈가 아니면 시점 하나(종전과 같다). 참조는 항상 Before(After 를 다음 기준으로 쓰면 얼굴이 흘러간다)
            self._p(item_id, "after")
            # 시점별 After 는 **동시에** 그린다 (2026-09-15 초안). 셋 다 기준이 같은 Before 라 서로 기다릴 이유가 없다 —
            # 종전엔 직후→1주→4주를 한 장씩 차례로 그려 세트 1회가 '4장 시간'이었다(0915 07:55 실측 3회차 22분 30초).
            # 공급자 동시 한도는 self._slots(공급자) 가 배치 전체에서 지킨다 — Before·After 가 같은 슬롯을 쓰므로
            # 항목 3개 × 시점 3개 = 9콜이 한꺼번에 나가지 않고, Before 콜이 그 한도를 우회하지도 않는다.
            after_sem = self._slots(self.p_edit)              # 정본은 _slots 한 곳 (머리말이 근거)
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
                        edit_refs = (self._refs(af.get("after_variation") or spec["variation"], af["when"])
                                     if self.mode == "clinical" and self.p_edit.supports_style_refs
                                     and load("clinical_rig.yaml").get("after_style_refs") else [])
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
                    else:
                        # After 는 그 시점 전용 참조까지 받는다(직후 컷엔 직후 실사진이 붙는다)
                        after_refs = self._refs(af.get("after_variation") or variation, af["when"])
                        after_b = await loop.run_in_executor(None, self.p_edit.generate, after_prompt, spec["aspect"], before_b, after_refs, None)
                        after = Image.open(io.BytesIO(after_b))
                        cost = self.pricing[self.p_edit.name]["generate"]
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
                # 판정은 spec 이 만들 때 실어 보낸 `effect_lowered` 하나다(여기서 시점 이름을 다시 보지 마라).
                ungate = ("effect_visible",) if af.get("effect_lowered") else ()
                outs.append((when, ab, Image.open(io.BytesIO(ab)), ungate))

            # ④ 검수 3단 — After 마다. 세트는 전부 통과해야 통과. 시점별 결과는 meta["after_results"][when] 에 남긴다
            self._p(item_id, "qa")
            meta["after_results"] = {}
            for when, ab, after_pp, ungate in outs:
                r = {"fail_reasons": []}
                st = structure.check(before_pp, after_pp, self.mode, t["mask_region"]); r["structure"] = st
                # passed 는 3값이다 — True(통과) / False(탈락) / None(못 잼). None 을 실패로 세면 같은 컷에 돈만 쓴다.
                if st.get("passed") is False:
                    r["fail_reasons"].append("structure")
                # 복붙 게이트 — 구조와 **따로** 센다(같은 칸에 넣으면 "왜 떨어졌나"가 뭉개진다).
                # 3값이라 None(임상·미검출)은 실패가 아니다. 근거·컷은 structure.copy_check 머리말.
                if (st.get("copy") or {}).get("passed") is False:
                    r["fail_reasons"].append("copy")
                idn = identity.check(before_pp, after_pp); r["identity"] = idn
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
                    vs = await loop.run_in_executor(None, vision.score, before_out, ab, self.mode, self.p_qa, ungate)
                    r["vision"] = vs; meta["cost"] += self.pricing[self.p_qa.name]["qa"]
                    r["fail_reasons"] += [f"vision:{k}" for k in vs["failed_items"]]
                meta["after_results"][when] = r
                meta["fail_reasons"] += [f if len(outs) == 1 else f"{f}@{when}" for f in r["fail_reasons"]]
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
