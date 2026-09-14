"""2026-09-14 티모 — 포텐자 01 쌍(모공 전·후)을 뺀 뒤 남은 8장이 어느 컷에 붙는지 다시 실측.

빼기 전 실측(120회)에서 배운 것: 색인을 통과하고 파일이 제자리여도 **실제로 안 붙는 사진**이
생긴다. 그래서 '뺐다'가 아니라 '남은 게 골고루 붙는다'를 잰다. 생성은 하지 않는다(비용 0).
"""
import sys, collections
sys.path.insert(0, 'src')
from bna import refs
from bna.planner import plan_batch
from bna.spec import series_points

N = 120

for t in ('skinbooster_embo', 'skin_pores'):
    pts = series_points(t, None) or ['2w']
    cnt = collections.Counter()
    slots = 0
    for seed in range(N):
        for v in plan_batch('selfie', 1, seed=seed, treatment=t):
            for when in [None] + list(pts):
                got = refs._rank(refs.candidates('selfie', t, when), v, when)[:2]
                slots += 1
                for r in got:
                    cnt[(r['file'].split('/')[-1], 'Before' if when is None else when)] += 1
    print(f'\n== {t}  (시점 {pts} · 추첨 {N}회 · 참조 자리 {slots}칸)')
    for (f, w), c in sorted(cnt.items()):
        print(f'   {w:<9} {f:<34} {c:5}회  {c*100/N:5.1f}% (컷당)')
    # 한 번도 안 붙은 참조가 있는가
    all_files = {r['file'].split('/')[-1] for when in [None] + list(pts)
                 for r in refs.candidates('selfie', t, when)}
    never = sorted(all_files - {f for f, _ in cnt})
    print(f'   → 후보 {len(all_files)}장 중 한 번도 안 붙은 것: {never or "없음"}')
