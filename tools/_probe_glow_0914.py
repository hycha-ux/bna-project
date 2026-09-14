import sys; sys.stdout.reconfigure(encoding='utf-8'); sys.path.insert(0,'src')
from bna.planner import plan_batch
from bna.spec import build_prompts
for t in ['skinbooster_embo','skin_pores','skin_redness']:
    p = plan_batch('selfie', 1, seed=7, treatment=t)[0]
    sp = build_prompts(t,'selfie',p,7001)
    print('='*20, t)
    print('--- AFTER ---'); print(sp['after_prompt'])
