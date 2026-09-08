"""회귀 — 설정·라우팅이 조용히 되돌아가는 걸 막는다.
실행: PYTHONPATH=src python selftest.py   (키 불필요, 네트워크 호출 0)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")   # Windows 콘솔 기본 CP949 라 한글·— 가 터진다
from bna.spec import defaults_for, load, build_prompts, sample_variation

fails = []


def ok(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        fails.append(msg)


# ① 셀카 = GPT (2026-09-08 성연서님 확정). gen·edit·qa 셋 다.
d = defaults_for("selfie")
ok(d["gen"] == "openai" and d["edit"] == "openai" and d["qa"] == "openai",
   f"셀카 기본 프로바이더가 GPT(openai) 셋 다여야 한다 — 실제 {d}")
ok(defaults_for("clinical")["gen"] == "gemini", "임상 기본은 종전대로 gemini")

# ② 벤더 이름을 코드에 다시 박지 않았는가 (정본은 providers.yaml 하나)
for f in ("src/bna/cli.py", "src/bna/batch.py"):
    src = open(f, encoding="utf-8").read()
    ok('default="gemini"' not in src and 'gen="gemini"' not in src,
       f"{f} 에 프로바이더 기본값 리터럴이 남아 있으면 안 된다")

# ③ 셀카 출력 비율이 GPT 크기표에 있는가 (없으면 실행 시점에 터진다)
aspect = load("variations.yaml").get("output", {}).get("aspect")
sizes = load("providers.yaml")["openai"]["aspect_size"]
ok(aspect in sizes, f"output.aspect={aspect} 가 providers.yaml aspect_size 에 있어야 한다")

# ④ gpt-image-2 크기 제약: 두 변 16의 배수 · 긴변 ≤3840 · 비율 ≤3:1 · 총 픽셀 65.5만~829만
for a, s in sizes.items():
    w, h = (int(x) for x in s.split("x"))
    ok(w % 16 == 0 and h % 16 == 0 and max(w, h) <= 3840
       and max(w, h) / min(w, h) <= 3 and 655360 <= w * h <= 8294400,
       f"aspect_size[{a}]={s} 가 gpt-image-2 제약을 만족해야 한다")

# ⑤ 프로바이더 이름이 전부 pricing 에 있는가 (없으면 배치가 KeyError 로 죽는다)
pricing = load("pricing.yaml")
for mode in ("selfie", "clinical"):
    for role, name in defaults_for(mode).items():
        ok(name in pricing, f"pricing.yaml 에 {name} 단가가 있어야 한다 ({mode}.{role})")

# ⑥ Before 표본에 '시술 직후 전용' 맥락이 섞이지 않는가 (2026-09-08 실측 35.8% 결함)
AFTER_ONLY = {"outing_top", "clinic_headband", "hair_flat_after", "cotton_pad"}
bad = [s for s in range(300) if sample_variation("selfie", s)["context"]["key"] in AFTER_ONLY]
ok(not bad, f"Before 300 표본에 직후 전용 맥락이 0건이어야 한다 — 실제 {len(bad)}건")

# ⑦ 셀카 프롬프트가 조립되는가 (템플릿 키 누락 조기 발견)
v = sample_variation("selfie", 5)
p = build_prompts("nasolabial", "selfie", v, 5)
ok(p["before_prompt"] and p["after_prompt"], "셀카 Before/After 프롬프트가 비어 있으면 안 된다")

print()
print(f"{'실패 ' + str(len(fails)) + '건' if fails else '전부 통과'}")
sys.exit(1 if fails else 0)
