"""동시 3콜에서 이미지 API 지연이 나빠지나 — 실호출 3건 (2026-09-15 티모, 약 $0.57).

왜 이 모양인가: "시점별 After 를 동시에 던지면 정말 빨라지나"의 산술은 이미 실측 원장으로 풀린다
(0915 07:55 회차 usage.jsonl — /images/edits 12콜, 96~113초). 남은 미지는 하나뿐이다 —
**같은 순간에 3콜이 가면 한 콜이 느려지는가**(그러면 병렬 이득이 그만큼 깎인다).
그래서 2~3세트를 다시 돌리는 대신($6~12) 그 한 가지만 3콜로 잰다.
비교 기준은 새로 돈을 쓰지 않는다 — 같은 엔드포인트·같은 크기·같은 품질의 그날 순차 실측을 쓴다.
"""
import asyncio, json, os, statistics, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# 키는 파일이 유일한 원천이다(ops/gen-poller.mjs 와 같은 자리). 값은 찍지 않는다.
KEYS = Path(os.environ.get("BNA_KEYS_FILE", r"C:\Users\medib\teemo\keys.env"))
for line in (KEYS.read_text(encoding="utf-8").splitlines() if KEYS.exists() else []):
    if line.strip().startswith("OPENAI_API_KEY="):
        os.environ.setdefault("OPENAI_API_KEY", line.split("=", 1)[1].strip().strip('"'))

from bna.providers import get

ITEM = ROOT / "outputs" / "20260915-075514-86ac" / "0000"
REF = ITEM / "skinbooster_embo_selfie_japan40sf_0000_before.jpg"
PROMPT = ("Keep this exact same person, same framing and same lighting. "
          "Reproduce the photo as-is with no visible change to the skin.")


def solo_baseline():
    """그날 순차 회차의 /images/edits 지연 — 새 호출 없이 원장에서 읽는다."""
    prog = json.loads((ITEM.parent / "progress.json").read_text(encoding="utf-8"))
    t0, t1 = prog["started_at"], prog["finished_at"]
    rows = [json.loads(l) for l in (ROOT / "outputs" / "usage.jsonl").open(encoding="utf-8")]
    ats = sorted(r["at"] for r in rows if t0 - 2 <= r["at"] <= t1 + 2 and r["path"] == "/images/edits")
    prev, gaps = t0, []
    for a in ats:
        gaps.append(a - prev); prev = a
    return gaps


async def main():
    p = get("openai")
    ref = REF.read_bytes()
    loop = asyncio.get_running_loop()
    lat = []

    async def one(i):
        t = time.time()
        await loop.run_in_executor(None, p.edit, ref, PROMPT, None)
        lat.append(time.time() - t)

    t0 = time.time()
    await asyncio.gather(*(one(i) for i in range(3)))       # 코드와 같은 모양 — 동시 3콜
    wall = time.time() - t0

    base = solo_baseline()
    out = {"동시3_각콜_초": [round(x, 1) for x in lat], "동시3_벽시계_초": round(wall, 1),
           "순차실측_n": len(base), "순차실측_중앙_초": round(statistics.median(base), 1),
           "순차실측_최대_초": round(max(base), 1),
           "지연_악화율": round(statistics.median(lat) / statistics.median(base) - 1, 3),
           "순차라면_초": round(statistics.median(base) * 3, 1)}
    out["판정"] = ("동시 3콜이 순차 3콜보다 빠르다" if wall < statistics.median(base) * 3 * 0.9
                 else "이득이 없다 — 병렬화를 재검토하라")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


sys.exit(asyncio.run(main()))
