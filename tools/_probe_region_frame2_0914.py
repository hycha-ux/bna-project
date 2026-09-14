"""2026-09-14 오후 2차 — '부위가 화면 안에 있나'를 재는 자를 바꿔야 하는지 실측.

1차에서 드러난 것: 같은 볼인데 시술마다 게이트가 켜지고 꺼진다.
  · skin_pores(mask_region=cheeks_nose)는 **조합 문자열**이라 isinstance(list) 가 False → 무조건 통과
  · skinbooster_embo(full_face_skin)는 얼굴 전체 폴리곤이라 **확대하면 원리적으로 실패**
확대 컷 비중을 4배로 올린 뒤 탈락이 난 자리가 여기다. 그래서 두 값을 같이 잰다(생성 0):
  in  = 부위 점 중 화면 안 비율      (지금 자: 1.0 이어야 통과)
  cov = 부위 폴리곤이 화면을 덮는 비율 (확대해서 '넘친' 것과 밀려서 '사라진' 것을 가른다)
"""
import sys, glob, os, json
sys.path.insert(0, 'src')
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from PIL import Image
from bna.qa import landmarks as L
from bna.spec import load

def measure(img_path, region):
    im = Image.open(img_path); p = L.detect(im)
    if p is None:
        return None
    idx = L.REGIONS.get(region)
    if isinstance(idx, str) and '+' in idx:                 # 조합("cheeks+nose")도 푼다
        idx = [i for part in idx.split('+') for i in (L.REGIONS.get(part) or [])]
    if not isinstance(idx, list) or not idx:
        return None
    w, h = im.size; pts = p[idx]
    inside = ((pts[:, 0] >= 0) & (pts[:, 0] < w) & (pts[:, 1] >= 0) & (pts[:, 1] < h))
    x0, x1 = np.clip(pts[:, 0], 0, w).min(), np.clip(pts[:, 0], 0, w).max()
    y0, y1 = np.clip(pts[:, 1], 0, h).min(), np.clip(pts[:, 1], 0, h).max()
    cov = float((x1 - x0) * (y1 - y0) / (w * h))            # 화면 안에 남은 부위의 넓이 비중
    return float(inside.mean()), cov

TR = load('treatments.yaml')
rows = []
for meta in sorted(glob.glob('outputs/2026*/[0-9][0-9][0-9][0-9]/meta.json')):
    m = json.load(open(meta, encoding='utf-8'))
    if m.get('mode') != 'selfie':
        continue
    d = os.path.dirname(meta)
    af = sorted(glob.glob(d + '/*_after*.jpg'))
    if not af:
        continue
    region = (TR.get(m['treatment']) or {}).get('mask_region')
    r = measure(af[-1], region)
    if r is None:
        continue
    rows.append((r[0], r[1], m.get('passed'), m['treatment'],
                 (m.get('after_variation') or m['variation']).get('framing', {}).get('key'), d))

rows.sort()
print(f'표본 {len(rows)}장 (얼굴 검출된 After)')
print(f'{"안비율":>7} {"화면덮음":>8}  통과   시술                프레이밍       경로')
for a, c, ok, t, fr, d in rows[:14]:
    print(f'{a*100:6.1f}% {c*100:7.1f}%  {str(ok):5} {t:17} {fr or "?":13} {d.split(os.sep)[-2]}/{d.split(os.sep)[-1]}')
for cut in (1.0, 0.95, 0.9, 0.85):
    n = sum(1 for a, *_ in rows if a >= cut)
    print(f'  안비율 컷 {cut*100:.0f}% → {n}/{len(rows)}장 통과')
for cov in (0.5, 0.4, 0.3, 0.2):
    n = sum(1 for a, c, *_ in rows if a >= 0.9 or c >= cov)
    print(f'  (안비율 90% 또는 화면덮음 {cov*100:.0f}%) → {n}/{len(rows)}장 통과')
