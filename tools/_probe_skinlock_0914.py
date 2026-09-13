"""2026-09-14 티모 — 피부결 3종의 After 프레이밍이 Before 와 같은지 실측.
고친 건 config/treatments.yaml 의 drift_lock 에 framing 을 넣은 것 하나이고,
이 프로브는 '넣었다'가 아니라 '그래서 안 흔들린다'를 잰다."""
import sys, collections
sys.path.insert(0,'src')
import random
from bna import spec as S
from bna.planner import plan_batch

def run(t, n=300):
    drift = 0; tot = 0; seen = collections.Counter()
    for seed in range(n):
        for i,p in enumerate(plan_batch('selfie',1,seed=seed,treatment=t)):
            rng = random.Random(seed*100+i)
            a = S.drift_after(p,'selfie',rng,timeline='2w',treatment=t)
            tot += 1
            seen[p['framing']['key']] += 1
            if a['framing']['key'] != p['framing']['key']: drift += 1
    return tot, drift, seen

for t in ('skinbooster_embo','skin_pores','skin_redness','nasolabial'):
    tot, drift, seen = run(t)
    print(f'{t:18} After 프레이밍이 달라진 비율 {drift}/{tot} = {drift*100/tot:.1f}%   {dict(seen.most_common(3))}')
