"""배치 오케스트레이션: 생성 → After → 후처리 → 3단 검수 → 판정/재시도 → 저장.
asyncio 워커 풀, 이어하기(state.json), 프롬프트 버전 기록."""
import asyncio, io, json, time, uuid
from pathlib import Path
from PIL import Image
from .spec import ROOT, load, build_prompts, defaults_for
from .planner import plan_batch
from . import postprocess, refs, providers
from .qa import structure, identity, dedup, vision, landmarks
from .stats import summarize, write_manifest
from .version import prompt_version
from .progress import Progress

MAX_ATTEMPTS = 3


class Batch:
    def __init__(self, treatment, mode, count, seed=None, fixed=None, gen=None, edit=None, qa=None, ab_prompt=None,
                 target_pass=None, cost_cap=None):
        # 프로바이더 기본값은 모드가 정한다 (config/providers.yaml). 여기에 벤더 이름을 박지 마라.
        d = defaults_for(mode)
        gen, edit, qa = gen or d["gen"], edit or d["edit"], qa or d["qa"]
        self.treatment, self.mode, self.count, self.seed = treatment, mode, count, seed
        self.fixed = fixed or {}
        self.batch_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        self.dir = ROOT / "outputs" / self.batch_id
        self.dir.mkdir(parents=True, exist_ok=True)
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

    # ---------- 단일 아이템 ----------
    async def run_item(self, idx: int, variation: dict) -> dict:
        spec = build_prompts(self.treatment, self.mode, variation, None if self.seed is None else self.seed * 1000 + idx,
                             avoid=(self.avoid or {}).get("lines"))
        item_id = f"{idx:04d}"
        # 프로바이더를 같이 적는다 — 버전 성적표가 prompt_version(=config 해시)으로만 묶여서,
        # 같은 버전을 다른 모델로 돌리면 두 모델의 성적이 한 줄에 섞인다(조용히 비교가 무의미해진다).
        meta = {**spec, "item_id": item_id, "batch_id": self.batch_id, "prompt_version": self.pv,
                "providers": {"gen": self.p_gen.name, "edit": self.p_edit.name, "qa": self.p_qa.name},
                "cost": 0.0, "fail_reasons": []}
        t = load("treatments.yaml")[self.treatment]
        style_refs = refs.pick(self.mode, variation)

        for attempt in range(1, MAX_ATTEMPTS + 1):
            meta["attempt"] = attempt; meta["fail_reasons"] = []
            loop = asyncio.get_event_loop()
            self._p(item_id, "before", attempt=attempt)
            # ① Before
            before_b = await loop.run_in_executor(None, self.p_gen.generate, self.p_gen.adapt_prompt(spec["before_prompt"], "before"),
                                                  spec["aspect"], None, style_refs, None)
            meta["cost"] += self.pricing[self.p_gen.name]["generate"]
            before = Image.open(io.BytesIO(before_b))

            # ② After
            self._p(item_id, "after")
            after_prompt = self.p_edit.adapt_prompt(spec["after_prompt"], "after")
            # 시술 부위 마스크는 두 모드 다 뽑아 둔다 — 임상은 편집·합성에 쓰고, 셀카는 검수 화면 오버레이("어디가 바뀌어야 하나")에 쓴다
            pts = landmarks.detect(before)
            mask_img = landmarks.region_mask(before, pts, t["mask_region"]) if pts is not None and t["mask_region"] in landmarks.REGIONS else None
            if spec["generation"] == "edit":
                mask_b = _png(mask_img) if (mask_img is not None and self.p_edit.supports_mask) else None
                after_b = await loop.run_in_executor(None, self.p_edit.edit, before_b, after_prompt, mask_b)
                after = Image.open(io.BytesIO(after_b))
                if mask_img is not None:                       # A4: 마스크 밖 원본 복원 (모델 지원 여부와 무관)
                    after = landmarks.composite_outside_mask(before, after, mask_img)
                meta["cost"] += self.pricing[self.p_edit.name]["edit"]
            else:
                after_b = await loop.run_in_executor(None, self.p_edit.generate, after_prompt, spec["aspect"], before_b, style_refs, None)
                after = Image.open(io.BytesIO(after_b))
                meta["cost"] += self.pricing[self.p_edit.name]["generate"]

            # ③ 후처리 (세트 동일 seed)
            self._p(item_id, "postprocess")
            pp_seed = hash((self.batch_id, item_id, attempt)) & 0xFFFF
            q_before = variation["quality"]["key"]; q_after = spec["after_variation"]["quality"]["key"]
            before_out = postprocess.apply(before, q_before, self.mode, pp_seed)
            after_out = postprocess.apply(after, q_after, self.mode, pp_seed)
            before_pp, after_pp = Image.open(io.BytesIO(before_out)), Image.open(io.BytesIO(after_out))

            # ④ 검수 3단
            self._p(item_id, "qa")
            st = structure.check(before_pp, after_pp, self.mode, t["mask_region"]); meta["structure"] = st
            # passed 는 3값이다 — True(통과) / False(탈락) / None(못 잼).
            # None 을 실패로 세면 재시도해도 결과가 같은 컷(부분 크롭·측면)에 돈만 쓴다.
            if st.get("passed") is False:
                meta["fail_reasons"].append("structure")
            idn = identity.check(before_pp, after_pp); meta["identity"] = idn
            if idn["hard_fail"]:
                meta["fail_reasons"].append("identity")
            if not meta["fail_reasons"]:
                vs = await loop.run_in_executor(None, vision.score, before_out, after_out, self.mode, self.p_qa)
                meta["vision"] = vs; meta["cost"] += self.pricing[self.p_qa.name]["qa"]
                meta["fail_reasons"] += [f"vision:{k}" for k in vs["failed_items"]]
            if not meta["fail_reasons"]:
                dd = dedup.check(before_pp, f"{self.batch_id}/{item_id}", self.registry); meta["dedup"] = dd
                if not dd["passed"]:
                    meta["fail_reasons"].append("duplicate")

            meta["passed"] = not meta["fail_reasons"]
            meta["mask_file"] = "mask.png" if mask_img is not None else None
            self._save(item_id, meta, before_out, after_out, mask_img)
            if meta["passed"]:
                self._p(item_id, "passed", passed=True, fail_reasons=[], cost=meta["cost"]); break
            self._p(item_id, "retry" if attempt < MAX_ATTEMPTS else "failed", passed=False, fail_reasons=list(meta["fail_reasons"]), cost=meta["cost"])
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

    def _save(self, item_id, meta, before_b, after_b, mask_img=None):
        v = meta["variation"]; d = self.dir / item_id; d.mkdir(exist_ok=True)
        stem = f'{self.treatment}_{self.mode}_{v["country"]["key"]}{v["age"]["key"]}{v["gender"]["key"][0]}_{item_id}'
        (d / f"{stem}_before.jpg").write_bytes(before_b); (d / f"{stem}_after.jpg").write_bytes(after_b)
        if mask_img is not None:
            mask_img.save(d / "mask.png")
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    # ---------- 배치 ----------
    async def run(self):
        plans = plan_batch(self.mode, self.count, self.seed, self.fixed, (self.avoid or {}).get("weights"), treatment=self.treatment)
        done = set(json.loads(self.state_path.read_text()).get("done", [])) if self.state_path.exists() else set()
        sem = asyncio.Semaphore(min(self.p_gen.concurrency, self.p_edit.concurrency))
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
        per_try = (self.pricing[self.p_gen.name]["generate"] + self.pricing[self.p_edit.name]["edit" if self.mode == "clinical" else "generate"]
                   + self.pricing[self.p_qa.name]["qa"])
        tries = self.count * min(MAX_ATTEMPTS, 1 / max(expected_pass_rate, 0.05))
        return {"items": self.count, "expected_calls": round(tries), "expected_cost_usd": round(per_try * tries, 2)}


def _png(img: Image.Image) -> bytes:
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()
