"""① 시점별 After 동시 생성 · ③ 비포 콜라주 선검사 — 오프라인 대역 검증 (2026-09-15 티모, API 0콜·$0).

왜 selftest 로 안 끝나나: 이 초안이 바꾼 건 값이 아니라 **호출 순서와 동시성**이라,
벽시계와 동시 재고(in-flight)를 재야 보인다. 대역 프로바이더에 인위 지연을 주고 센다.
  A 시점 순서 보존 · 비용 합산 · After 구간 벽시계
  B 세마포어 상한 — 항목 3개 × 시점 3개 = 9콜이 한꺼번에 나가지 않나
  D 예외 — 한 시점이 터지면 나머지 두 장의 비용이 원장에 남나(gather 기본값의 함정)
  E 선검사 — 콜라주면 Before 만 다시, 3장에서 멈추고 기록이 남나
"""
import asyncio, io, json, os, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("OPENAI_API_KEY", "stub")

from PIL import Image
from bna import providers
from bna.providers.base import Provider

TREAT, SERIES = "skinbooster_embo", ["immediate", "1w", "4w"]   # 0915 07:55 회차와 같은 축
LAT = 0.40          # 대역 호출 1건의 지연(초). 실측 /images/edits 는 ~108초다
st = {"now": 0, "peak": 0, "before": 0, "after": 0, "boom_at": None, "after_t": [], "all_t": []}


def _png(color=(200, 170, 160)):
    b = io.BytesIO(); Image.new("RGB", (512, 640), color).save(b, "PNG"); return b.getvalue()


class Stub(Provider):
    name, concurrency = "openai", 3
    supports_ref = supports_style_refs = True

    def __init__(self):
        pass

    def _work(self, kind):
        st["now"] += 1; st["peak"] = max(st["peak"], st["now"])
        t0 = time.time()
        try:
            time.sleep(LAT)
            st[kind] += 1
            st["all_t"].append((t0, time.time()))
            if kind == "after":
                st["after_t"].append((t0, time.time()))
                if st["boom_at"] == st["after"]:
                    raise RuntimeError(f"대역 폭발: after #{st['after']}")
            return _png()
        finally:
            st["now"] -= 1

    def generate(self, prompt, aspect, ref=None, style_refs=None, seed=None):
        return self._work("after" if ref else "before")     # After 는 Before 를 참조로 받는다

    def edit(self, image, prompt, mask=None):
        return self._work("after")

    def qa(self, before, after, items, mode):
        return {k: {"score": 10.0, "note": "stub"} for k in items}


providers.get = lambda name: Stub()            # noqa: E731

from bna.batch import Batch                    # providers.get 을 바꾼 뒤 import
from bna.planner import plan_batch
from bna.qa import identity

_faces = []                                    # big_faces 가 차례로 돌려줄 값 (E 실험)
identity.big_faces = lambda img, ratio=0.25: (_faces.pop(0) if _faces else 1)
identity.check = lambda b, a, threshold=identity.THRESHOLD: {
    "similarity": 0.8, "gate": "ok", "passed": True, "hard_fail": False, "measured": True,
    "faces": {"before": 1, "after": 1}, "collage": False}


def mk(series, count=1):
    b = Batch(TREAT, "selfie", count, seed=5, series=series)
    try:
        b.dir.rmdir()
    except OSError:
        pass
    tmp = Path(tempfile.mkdtemp(prefix="bna_probe_"))
    b.dir = tmp; b.state_path = tmp / "state.json"
    b._after_sem = asyncio.Semaphore(b.p_edit.concurrency)
    return b


def reset(boom_at=None):
    st.update(now=0, peak=0, before=0, after=0, boom_at=boom_at, after_t=[], all_t=[])
    _faces.clear()


def span(ts):
    return round(max(e for _, e in ts) - min(s for s, _ in ts), 2) if ts else 0.0


async def main():
    bad, out = [], {}
    v = plan_batch("selfie", 1, 5, {}, None, treatment=TREAT)[0]

    # ── A: 시점 3개, 항목 1개 ─────────────────────────────────────────────
    reset(); b = mk(SERIES)
    meta = await b.run_item(0, v)
    out["A_시점"] = list(meta["after_results"].keys())
    out["A_Before장"] = st["before"]; out["A_After장"] = st["after"]
    out["A_비용"] = round(meta["cost"], 4)
    out["A_After구간_벽시계"] = span(st["after_t"])
    out["A_순차가정"] = round(st["after"] * LAT, 2)
    out["A_동시최대"] = st["peak"]
    if out["A_시점"] != SERIES:
        bad.append(f'시점 순서가 흐트러졌다: {out["A_시점"]}')
    if meta["cost"] <= 0:
        bad.append("비용이 0 — gather 로 옮기면서 합산이 빠졌다")
    if st["after"] != 3:
        bad.append(f'After 3장이어야 한다 — {st["after"]}장(실험 무효)')
    if out["A_After구간_벽시계"] > out["A_순차가정"] * 0.7:
        bad.append(f'After 구간이 안 줄었다: {out["A_After구간_벽시계"]}s / 순차 {out["A_순차가정"]}s')

    # ── B: 항목 3개 × 시점 3개 = 9콜이 한꺼번에 나가는가 ──────────────────
    reset(); b = mk(SERIES, count=3)
    sem = asyncio.Semaphore(min(b.p_gen.concurrency, b.p_edit.concurrency))
    vs = plan_batch("selfie", 3, 5, {}, None, treatment=TREAT)

    async def one(i, vv):
        async with sem:
            return await b.run_item(i, vv)

    t0 = time.time(); await asyncio.gather(*(one(i, vv) for i, vv in enumerate(vs)))
    out["B_동시최대"] = st["peak"]; out["B_한도"] = b.p_edit.concurrency
    out["B_이미지콜"] = st["before"] + st["after"]; out["B_벽시계"] = round(time.time() - t0, 2)
    out["B_콜÷한도_하한"] = round((st["before"] + st["after"]) / b.p_edit.concurrency * LAT, 2)
    out["B_이미지구간_벽시계"] = span(st["all_t"])
    if st["peak"] > b.p_edit.concurrency:
        bad.append(f'공급자 동시 한도 초과: 최대 {st["peak"]} > {b.p_edit.concurrency}')

    # ── D: 2번째 After 가 터지면 나머지 비용이 원장에 남나 ────────────────
    reset(boom_at=2); b = mk(SERIES)
    err = None
    try:
        await b.run_item(0, v)
    except Exception as e:                      # noqa: BLE001
        err = repr(e)[:70]
    await asyncio.sleep(LAT * 3)                # 살아남은 태스크가 끝날 시간
    out["D_예외"] = err
    out["D_실제_유료After"] = st["after"]
    out["D_원장에_남은비용"] = "meta 를 못 받았다(예외) → 0"
    if err is None:
        bad.append("D: 예외가 안 올라왔다(실험 무효)")

    # ── E: 선검사 — 콜라주 2회 뒤 정상 ────────────────────────────────────
    reset(); _faces.extend([2, 2, 1]); b = mk(None)
    meta = await b.run_item(0, v)
    out["E_Before장"] = st["before"]; out["E_기록"] = meta.get("before_precheck")
    if st["before"] != 3:
        bad.append(f'E: Before 3장이어야 한다 — {st["before"]}장')

    # ── E2: 3장 다 콜라주면 그대로 진행(무한루프 아님) ────────────────────
    reset(); _faces.extend([2] * 20); b = mk(None)
    meta = await b.run_item(0, v)
    out["E2_Before장_전회차합"] = st["before"]; out["E2_기록수"] = len(meta.get("before_precheck") or [])
    out["E2_탈락사유"] = meta["fail_reasons"]
    if st["before"] > 9:
        bad.append(f'E2: 회차당 3장을 넘겼다 — 총 {st["before"]}장')

    print(json.dumps(out, ensure_ascii=False, indent=1))
    print("\n" + ("PASS: 대역 통과" if not bad else "FAIL:\n  " + "\n  ".join(bad)))
    return 1 if bad else 0


sys.exit(asyncio.run(main()))
