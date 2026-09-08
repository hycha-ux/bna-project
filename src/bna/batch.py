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

MAX_ATTEMPTS = 3


class Batch:
    def __init__(self, treatment, mode, count, seed=None, fixed=None, gen=None, edit=None, qa=None, ab_prompt=None):
        # 프로바이더 기본값은 모드가 정한다 (config/providers.yaml). 여기에 벤더 이름을 박지 마라.
        d = defaults_for(mode)
        gen, edit, qa = gen or d["gen"], edit or d["edit"], qa or d["qa"]
        self.treatment, self.mode, self.count, self.seed = treatment, mode, count, seed
        self.fixed = fixed or {}
        self.batch_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        self.dir = ROOT / "outputs" / self.batch_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.pv = prompt_version()
        self.pricing = load("pricing.yaml")
        self.p_gen, self.p_edit, self.p_qa = providers.get(gen), providers.get(edit), providers.get(qa)
        self.registry = dedup.Registry()
        self.ab_prompt = ab_prompt   # A6: 실험용 대체 프롬프트 파일 접미사 (예: "v2")
        self.state_path = self.dir / "state.json"

    # ---------- 단일 아이템 ----------
    async def run_item(self, idx: int, variation: dict) -> dict:
        spec = build_prompts(self.treatment, self.mode, variation, None if self.seed is None else self.seed * 1000 + idx)
        item_id = f"{idx:04d}"
        meta = {**spec, "item_id": item_id, "batch_id": self.batch_id, "prompt_version": self.pv, "cost": 0.0, "fail_reasons": []}
        t = load("treatments.yaml")[self.treatment]
        style_refs = refs.pick(self.mode, variation)

        for attempt in range(1, MAX_ATTEMPTS + 1):
            meta["attempt"] = attempt; meta["fail_reasons"] = []
            loop = asyncio.get_event_loop()
            # ① Before
            before_b = await loop.run_in_executor(None, self.p_gen.generate, self.p_gen.adapt_prompt(spec["before_prompt"], "before"),
                                                  spec["aspect"], None, style_refs, None)
            meta["cost"] += self.pricing[self.p_gen.name]["generate"]
            before = Image.open(io.BytesIO(before_b))

            # ② After
            after_prompt = self.p_edit.adapt_prompt(spec["after_prompt"], "after")
            if spec["generation"] == "edit":
                pts = landmarks.detect(before)
                mask_img = landmarks.region_mask(before, pts, t["mask_region"]) if pts is not None and t["mask_region"] in landmarks.REGIONS else None
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
            pp_seed = hash((self.batch_id, item_id, attempt)) & 0xFFFF
            q_before = variation["quality"]["key"]; q_after = spec["after_variation"]["quality"]["key"]
            before_out = postprocess.apply(before, q_before, self.mode, pp_seed)
            after_out = postprocess.apply(after, q_after, self.mode, pp_seed)
            before_pp, after_pp = Image.open(io.BytesIO(before_out)), Image.open(io.BytesIO(after_out))

            # ④ 검수 3단
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
            self._save(item_id, meta, before_out, after_out)
            if meta["passed"]:
                break
        return meta

    def _save(self, item_id, meta, before_b, after_b):
        v = meta["variation"]; d = self.dir / item_id; d.mkdir(exist_ok=True)
        stem = f'{self.treatment}_{self.mode}_{v["country"]["key"]}{v["age"]["key"]}{v["gender"]["key"][0]}_{item_id}'
        (d / f"{stem}_before.jpg").write_bytes(before_b); (d / f"{stem}_after.jpg").write_bytes(after_b)
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    # ---------- 배치 ----------
    async def run(self):
        plans = plan_batch(self.mode, self.count, self.seed, self.fixed)
        done = set(json.loads(self.state_path.read_text()).get("done", [])) if self.state_path.exists() else set()
        sem = asyncio.Semaphore(min(self.p_gen.concurrency, self.p_edit.concurrency))
        results = []

        async def guarded(i, v):
            if f"{i:04d}" in done:
                return None
            async with sem:
                m = await self.run_item(i, v)
            done.add(m["item_id"]); self.state_path.write_text(json.dumps({"done": sorted(done)}))
            return m

        results = [r for r in await asyncio.gather(*(guarded(i, v) for i, v in enumerate(plans))) if r]
        write_manifest(self.dir, results)
        s = summarize(results); (self.dir / "stats.json").write_text(json.dumps(s, ensure_ascii=False, indent=1))
        return s

    def estimate(self, expected_pass_rate=0.5) -> dict:
        per_try = (self.pricing[self.p_gen.name]["generate"] + self.pricing[self.p_edit.name]["edit" if self.mode == "clinical" else "generate"]
                   + self.pricing[self.p_qa.name]["qa"])
        tries = self.count * min(MAX_ATTEMPTS, 1 / max(expected_pass_rate, 0.05))
        return {"items": self.count, "expected_calls": round(tries), "expected_cost_usd": round(per_try * tries, 2)}


def _png(img: Image.Image) -> bytes:
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()
