"""① 시점별 After 동시 생성이 **배치 전체 벽시계**를 정말 줄이나 — 스케줄링 시뮬 (2026-09-15 티모, API 0콜·$0).

실측 지연(0915 07:55 회차 usage.jsonl): 이미지 1콜 ≈ 108초 · 비전 채점 1콜 ≈ 29초.
구조는 코드와 같다 — 항목 세마포어 min(gen,edit)=3, After 세마포어 = edit.concurrency = 3.
1/500 로 축소해 돌린다(값이 아니라 *라운드 수*를 보는 실험).

왜 재나: "세트 1회가 4장 시간 → 2장 시간"은 항목이 1개일 때의 산술이고,
항목이 동시 한도만큼 차 있으면 병목은 항목 안이 아니라 공용 슬롯이라 이득이 0일 수 있다.
"""
import asyncio, sys, time

IMG, QA, SCALE = 108.0, 29.0, 500.0
CONC, POINTS = 3, 3


async def item(mode, item_sem, after_sem, gen_sem=None):
    async with item_sem:
        if gen_sem is not None:                                # 제안안: Before 도 공급자 세마포어를 탄다
            async with gen_sem:
                await asyncio.sleep(IMG / SCALE)
        else:
            await asyncio.sleep(IMG / SCALE)                   # ① Before
        if mode == "serial":
            for _ in range(POINTS):                            # ② After — 차례로
                await asyncio.sleep(IMG / SCALE)
        else:
            async def one():
                async with after_sem:
                    await asyncio.sleep(IMG / SCALE)
            await asyncio.gather(*(one() for _ in range(POINTS)))
        for _ in range(POINTS):                                # ④ 검수 — 시점마다 차례로(둘 다 동일)
            await asyncio.sleep(QA / SCALE)


async def run(mode, count):
    # phase = 제안안(항목 한도를 풀고 공급자 한도만 남긴다). 그 외는 항목 한도 = 공급자 한도.
    item_sem = asyncio.Semaphore(999 if mode == "phase" else CONC)
    after_sem, gen_sem = asyncio.Semaphore(CONC), (asyncio.Semaphore(CONC) if mode == "phase" else None)
    t0 = time.perf_counter()
    m = "parallel" if mode == "phase" else mode
    await asyncio.gather(*(item(m, item_sem, after_sem, gen_sem) for _ in range(count)))
    return (time.perf_counter() - t0) * SCALE / 60.0           # 분


async def main():
    print(f"이미지 1콜 {IMG:.0f}s · 검수 1콜 {QA:.0f}s · 시점 {POINTS} · 동시 한도 {CONC}")
    print(f"{'세트':>4} {'종전(순차)':>11} {'초안(동시)':>11} {'차이':>9} {'참고:항목한도해제':>16}")
    rows = []
    for n in (1, 2, 3, 4, 8):
        a, b, c = await run("serial", n), await run("parallel", n), await run("phase", n)
        rows.append((n, a, b))
        print(f"{n:>4} {a:>10.1f}분 {b:>10.1f}분 {(b-a)/a*100:>+8.1f}% {c:>14.1f}분")
    worse = [r for r in rows if r[2] > r[1] * 1.02]
    print("\n" + (f"주의: 세트 {[r[0] for r in worse]} 에서 초안이 더 느리다" if worse else "모든 모수에서 같거나 빠르다"))
    return 0


sys.exit(asyncio.run(main()))
