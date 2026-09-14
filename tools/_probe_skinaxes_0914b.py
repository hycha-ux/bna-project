"""2026-09-14 오후 — 머리 고정·수염 금지·눈 유지 이웃을 넣은 뒤의 대가를 잰다.
막았으면 '얼마나 단조로워졌나'와 '조명 호는 여전히 도나'를 같은 자리에서 재야 한다(생성 0)."""
import sys, collections
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'src')
from bna.planner import plan_batch
from bna.spec import build_prompts

SKIN = ['skinbooster_embo', 'skin_pores', 'skin_redness']
SOFT, HARSH = {'window', 'window_soft'}, {'ceiling_harsh', 'flash', 'fluorescent'}
N = 150
tot = changed = arc = after_harsh = 0
cnt = collections.Counter()
for t in SKIN:
    for i, p in enumerate(plan_batch('selfie', N, seed=99, treatment=t)):
        sp = build_prompts(t, 'selfie', p, 99000 + i); a = sp['after_variation']
        diff = [k for k in p if isinstance(p[k], dict) and a.get(k, {}).get('key') != p[k]['key']]
        tot += 1; changed += len(diff)
        for k in diff:
            cnt[k] += 1
        if p['lighting']['key'] in HARSH and a['lighting']['key'] in SOFT:
            arc += 1
        if a['lighting']['key'] in HARSH:
            after_harsh += 1
print(f'표본 {tot}세트')
print(f'After 에서 바뀌는 축 평균 {changed/tot:.1f}개 — 세트끼리 달라 보이려면 이게 0 이면 안 된다')
print('  자주 바뀌는 축:', dict(cnt.most_common(6)))
print(f'조명 호(전=센 빛 → 후=부드러운 빛) {arc*100/tot:.0f}%')
print(f'⚠ 후 컷이 여전히 센 빛 {after_harsh*100/tot:.0f}% — 이 구간은 "후가 더 나빠 보일" 수 있다')
