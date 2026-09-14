"""2026-09-14 오후 — 후 컷에 '물광 참조'가 실제로 붙는지 센다(생성 0).
문장을 고쳐도 참조가 무광 쪽이면 그림체가 도로 끌려간다(오전 교훈: 참조는 그림체를 옮긴다)."""
import sys, collections
sys.path.insert(0, 'src')
sys.stdout.reconfigure(encoding='utf-8')
from bna import refs
from bna.planner import plan_batch
from bna.spec import series_points

N = 120
GLOW = {'skin_pores_after4w_02.jpg', 'skinbooster_embo_after4w_01.jpg', 'skin_redness_after4w_01.jpg'}
for t in ('skinbooster_embo', 'skin_pores', 'skin_redness'):
    pts = series_points(t, None) or ['2w']
    cnt, slots, glow_hit = collections.Counter(), 0, 0
    for seed in range(N):
        for v in plan_batch('selfie', 1, seed=seed, treatment=t):
            for when in pts:
                got = refs._rank(refs.candidates('selfie', t, when), v, when)[:2]
                slots += 1
                names = [r['file'].split('/')[-1] for r in got]
                for n in names:
                    cnt[n] += 1
                if any(n in GLOW for n in names):
                    glow_hit += 1
    print(f'== {t}: 후 컷 {slots}회 중 물광 참조가 붙은 회차 {glow_hit} ({glow_hit*100/slots:.0f}%)')
    for n, c in cnt.most_common():
        print(f'   {n:34} {c:4}회')
