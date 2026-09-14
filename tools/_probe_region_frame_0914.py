"""2026-09-14 오후 — region_in_frame 이 '한 점이라도 밖이면 실패'인 게 맞는 자인지 실측.

계기: 엠보 0000 이 3회 재시도 후 이 게이트로 탈락($1.92 중 절반이 재시도). 그런데 더 확대된
one_cheek 컷(0002)은 **얼굴 미검출 → 못 잼**으로 통과했다 — 확대할수록 벌을 받는 게 아니라
'중간 확대'만 벌을 받는 역전이다. 그래서 컷을 정하기 전에 분포부터 잰다(생성 0).
"""
import sys, glob, os, json
sys.path.insert(0, 'src')
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from PIL import Image
from bna.qa import landmarks as L

def ratio(img_path, region):
    im = Image.open(img_path)
    p = L.detect(im)
    if p is None:
        return None
    idx = L.REGIONS.get(region)
    if not isinstance(idx, list):
        return None
    w, h = im.size
    pts = p[idx]
    inside = ((pts[:, 0] >= 0) & (pts[:, 0] < w) & (pts[:, 1] >= 0) & (pts[:, 1] < h))
    return float(inside.mean())

rows = []
for meta in sorted(glob.glob('outputs/2026*/[0-9][0-9][0-9][0-9]/meta.json')):
    m = json.load(open(meta, encoding='utf-8'))
    if m.get('mode') != 'selfie':
        continue
    d = os.path.dirname(meta)
    af = [f for f in glob.glob(d + '/*_after*.jpg')]
    if not af:
        continue
    from bna.spec import load as _l
    region = (_l('treatments.yaml').get(m['treatment']) or {}).get('mask_region') or 'cheeks'
    region = 'cheeks' if region == 'cheeks_nose' else region
    r = ratio(sorted(af)[-1], region)
    if r is None:
        continue
    rows.append((r, m.get('passed'), m['treatment'], (m.get('after_variation') or m['variation']).get('framing', {}).get('key'), d))

rows.sort()
print(f'표본 {len(rows)}장 (얼굴이 검출된 After 컷만 — 미검출은 이 게이트를 아예 안 탄다)')
print('부위 점이 화면 안에 있는 비율 · 낮은 순 12개')
for r, ok, t, fr, d in rows[:12]:
    print(f'  {r*100:5.1f}%  통과={ok}  {t:17} {fr:13} {d}')
full = [r for r, *_ in rows if r >= 1.0]
print(f'\n100%(지금 기준 통과) {len(full)}/{len(rows)}장 = {len(full)*100/len(rows):.0f}%')
for cut in (0.98, 0.95, 0.9, 0.85, 0.8):
    n = sum(1 for r, *_ in rows if r >= cut)
    print(f'  컷 {cut*100:.0f}% 이면 {n}/{len(rows)}장 통과')
