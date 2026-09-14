"""2026-09-14 밤 — 표정 축이 After 에서 실제로 '달라 보이게' 바뀌는지 잰다(생성 0).
'키가 다르다'와 '사람 눈에 다르다'는 다른 값이다 — 둘을 같이 낸다.
  · 세밀 축 = config 의 expression_traits (입 벌림 × 눈/시선 5종) — 코드가 쓰는 그 표
  · 거친 축 = 입 벌림 × '눈이 평범한가 아닌가' 2종 — 표와 독립이라 채점이 자기 채점이 안 된다"""
import sys, collections
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'src')
from bna.planner import plan_batch
from bna.spec import build_prompts, load

SKIN = ['skinbooster_embo', 'skin_pores', 'skin_redness']
MOUTH_OPEN = {'relaxed_open', 'gaze_screen', 'lips_speak'}
EYE_ODD = {'eyes_narrow', 'blink_soft', 'brow_up', 'gaze_off', 'gaze_screen'}
TB = load('variations.yaml').get('expression_traits', {})
N = 150
tot = key_same = coarse_same = fine_same = viol = 0
for t in SKIN:
    for i, p in enumerate(plan_batch('selfie', N, seed=99, treatment=t)):
        a = build_prompts(t, 'selfie', p, 99000 + i)['after_variation']
        b, af = p['expression']['key'], a['expression']['key']
        tot += 1
        key_same += b == af
        coarse_same += ((b in MOUTH_OPEN) == (af in MOUTH_OPEN)) and ((b in EYE_ODD) == (af in EYE_ODD))
        fs = TB.get(b, {}) == TB.get(af, {})
        fine_same += fs
        viol += (b != af) and fs                 # 키는 바뀌었는데 입·눈 상태가 그대로 = 막으려던 것
print(f'표본 {tot}세트 (피부 3종)')
print(f'표정 키 그대로            {key_same*100/tot:.0f}%   ← 의도한 여유(잠그지 않았다)')
print(f'입·눈 상태 그대로(세밀)   {fine_same*100/tot:.0f}%')
print(f'입·눈 상태 그대로(거친)   {coarse_same*100/tot:.0f}%')
print(f'⚠ 위반(키는 달라졌는데 상태 동일) {viol}건 — 0 이어야 한다')
