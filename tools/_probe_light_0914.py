import sys, collections; sys.stdout.reconfigure(encoding='utf-8'); sys.path.insert(0,'src')
from bna.planner import plan_batch
from bna.spec import build_prompts
c=collections.Counter()
for t in ['skinbooster_embo','skin_pores','skin_redness']:
    for i,p in enumerate(plan_batch('selfie',150,seed=99,treatment=t)):
        sp=build_prompts(t,'selfie',p,99000+i); c[sp['after_variation']['lighting']['key']]+=1
n=sum(c.values()); print({k:f'{v*100/n:.0f}%' for k,v in c.most_common()})
