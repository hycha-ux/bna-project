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
ok(defaults_for("clinical") == {"gen": "openai", "edit": "openai", "qa": "openai"}, "임상 기본도 GPT 셋 다 (2026-09-15 연서님 확정, Gemini 미구현)")

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

# ⑥-2 시술 직후 After 에 '피부에 바른 것'이 안 붙는가 (2026-09-10 "어색한 마취크림" 5/5 실측)
#     cotton_pad 는 정의만 남기고 후보에서 뺐다 — 세 곳(after_immediate·context_allow·mode_rules) 중
#     한 곳만 되살아나도 다시 뽑히므로 조립된 프롬프트 자체를 본다.
_vy = load("variations.yaml")
ok("cotton_pad" not in (_vy["after_immediate"]["selfie"]["context"]),
   "after_immediate 후보에 cotton_pad 가 없어야 한다")
ok(not [b for b, c in _vy["context_allow"].items() if "cotton_pad" in c],
   f"context_allow 어느 배경에도 cotton_pad 가 없어야 한다 — 실제 {[b for b, c in _vy['context_allow'].items() if 'cotton_pad' in c]}")
def _immediate_after(tr, seed):
    """직후(immediate) 시점 After 프롬프트. 시리즈로 뽑아 그 시점만 본다."""
    p_ = build_prompts(tr, "selfie", sample_variation("selfie", seed), seed, series=["immediate"])
    for a_ in p_.get("afters") or []:
        if a_["when"] == "immediate":
            return a_["after_prompt"]
    return p_["after_prompt"]

_cream = [s_ for s_ in range(200)
          if any(w in _immediate_after("nasolabial", s_) for w in ("cotton pad", "ointment"))]
ok(not _cream, f"직후 After 200 표본에 크림·거즈 지시가 0건이어야 한다 — 실제 {len(_cream)}건")
ok("clean and dry" in load("prompts/mode_extra.yaml")["after_day"]["same"],
   "직후 설정에 '피부는 깨끗하고 마른 상태' 긍정문이 있어야 한다(금지어 나열 대신)")

# ⑥-3 표정 잠금이 '얼굴 복사'가 되지 않는가 (2026-09-10 "동일한 각도, 구도, 표정" 2장)
#     잠글 것은 웃음 하나다. 미세 차이 요구 문장이 빠지면 다시 복사로 돌아간다.
_lock = build_prompts("nasolabial", "selfie", sample_variation("selfie", 5), 5)["after_prompt"]
ok("must not change at all" not in _lock,
   "표정 잠금에 '전혀 바뀌면 안 된다'는 절대 문구가 남아 있으면 안 된다(얼굴 전체를 복사시킨다)")
ok("Do not smile" in _lock, "표정 잠금은 '웃지 마라'로 좁혀져야 한다")
# 2026-09-11 오후 성연서님 "카메라 각도도 얼굴 각도도 다 똑같아, 로봇이야" → '몇 도 다르게'라는 *정도*
# 대신 **팔을 다시 들었다는 사실**부터 말하게 바꿨다. 각도 축 자체는 여전히 잠근다(그림자가 효과로 둔갑).
# ⚠ 2026-09-14: 이 시료가 **문구 그대로**를 박고 있어서, 같은 뜻을 더 강하게 쓴 개정이 회귀로 걸렸다.
#   지킬 것은 낱말이 아니라 **요구 항목**이다 → 항목별로 본다(문구는 RESHOT_LINE 한 곳에서 바뀐다).
for _frag in ("picked up again", "eyes are open", "not in the same spot in the frame",
              "visible at a glance", "not the reference photo edited"):
    ok(_frag in _lock, f"표정 잠금이 미세 차이를 명시적으로 요구해야 한다 — '{_frag}'")
# 잠금 없는 시술(free)도 **같은 요구**를 받아야 한다 (2026-09-14 연서님 "딱 떨어지게 똑같다").
#   ⚠ 종전 이 줄은 free 갈래가 `may differ slightly` 한 마디이길 *요구*하고 있었다 — 오늘 사고를
#     고착시킨 시료다. 자유는 '표정을 달리 뽑아도 된다'는 뜻이지 '복제를 허용한다'가 아니다.
_free14 = build_prompts("nose_lifting", "selfie", sample_variation("selfie", 5), 5)["after_prompt"]
ok("not the reference photo edited" in _free14 and "Do not copy the pose" in _free14,
   "expression_policy: free 시술도 '참조를 베끼지 마라'를 받아야 한다")
ok("may differ slightly" not in _free14,
   "free 갈래의 옛 한 줄('살짝 달라도 된다')은 되살아나면 안 된다 — 그게 복제를 막지 못했다")

# ⑥-4 각도×프레이밍 금지 조합이 실제로 안 뽑히는가 (2026-09-10 검수 "카메라 앵글이 벗어남")
#     아래 ⑳ 전수 검사가 이미 framing_ban_by_angle 을 보지만, 이 조합은 '왜 막았는지'가 검수 메모라
#     되살아나면 같은 돈을 다시 태운다 — 시술·조합을 이름으로 못 박아 둔다.
from bna.planner import plan_batch as _pb0
_bad = [p_ for p_ in _pb0("selfie", 300, seed=3, treatment="nasolabial")
        if p_["framing"]["key"] == "one_cheek" and p_["angle"]["key"] in ("tilted", "selfie_side", "chin_up")]
ok(not _bad, f"팔자 300 표본에 '한쪽 볼 + 기울임/측면/턱들기' 조합이 0건이어야 한다 — 실제 {len(_bad)}건")

# ⑦ 셀카 프롬프트가 조립되는가 (템플릿 키 누락 조기 발견)
v = sample_variation("selfie", 5)
p = build_prompts("nasolabial", "selfie", v, 5)
ok(p["before_prompt"] and p["after_prompt"], "셀카 Before/After 프롬프트가 비어 있으면 안 된다")

# ⑧ 동일인 게이트 — '안 재는 것'이 '통과'로 둔갑하지 않는가 (2026-09-08 실측 반영)
from bna.qa import identity
ok(identity.check.__doc__ and "n/a" in identity.check.__doc__, "identity.check 가 3값 게이트여야 한다")
# ⚠ 시료 점수는 상수에서 만든다 — 리터럴로 박으면 문턱을 재캘리브레이션할 때마다 여기가 같이
#   틀리고, 그때 고쳐야 할 곳이 두 곳이 된다(2026-09-11 실사고: 0.60→0.45 로 내리자 0.5 가
#   review 에서 ok 로 넘어가 이 검사가 깨졌다). 숫자를 잠그는 자리는 17-7 한 곳이다.
_T, _R = identity.THRESHOLD, identity.REVIEW_BAND
for gate, sim, want_hard, want_passed in [("ok", _T + 0.15, False, True), ("review", (_T + _R) / 2, False, None),
                                          ("fail", _R - 0.15, True, False), ("n/a", None, False, None)]:
    # check() 는 이미지를 받으므로, 판정 로직만 보려고 similarity 를 가로챈다.
    # (이미지 없이 부르는 이 길은 big_faces 가 None='못 잼'으로 답해 준다 — identity.big_faces 머리말 참조.
    #  종전엔 여기서 insightface 설치 기계만 죽어 뒤쪽 검사가 통째로 안 돌았다, 2026-09-15 티모)
    orig = identity.similarity
    identity.similarity = lambda a, b, _s=sim: _s
    try:
        r = identity.check(None, None)
    finally:
        identity.similarity = orig
    ok(r["gate"] == gate and r["hard_fail"] is want_hard and r["passed"] is want_passed,
       f"similarity={sim} → gate={gate}·hard_fail={want_hard}·passed={want_passed} (실제 {r})")

# ⑨ 미검출 구제(레터박스)가 코드에 살아 있는가. 시료 8장이 있으면 실측까지 한다.
import inspect
ok("_letterbox" in inspect.getsource(identity.embed), "embed 가 레터박스 재시도를 해야 한다(부분 크롭 구제)")

FIX = r"C:\Users\medib\teemo\out\gen0908"
import glob as _g
shots = sorted(_g.glob(FIX + r"\g*_[AB]_*.png"))
if len(shots) == 8:
    from PIL import Image
    got = sum(identity.embed(Image.open(f)) is not None for f in shots)
    ok(got >= 7, f"시료 8장 중 7장 이상 검출돼야 한다(2026-09-08 실측: 구제 전 4 → 후 7) — 실제 {got}")
else:
    print(f"SKIP  시료 8장이 없어 검출률 실측 생략 ({FIX})")

# ⑩ 구조 검사도 3값이어야 한다 — 미검출을 실패로 세면 같은 컷을 3번 다시 뽑는다(2026-09-08 $1.14 소각)
import re
st_src = open("src/bna/qa/structure.py", encoding="utf-8").read()
ok('"passed": None' in st_src, "structure.check 의 미검출은 passed=None(못 잼)이어야 한다")
b_src = open("src/bna/batch.py", encoding="utf-8").read()
ok('st.get("passed") is False' in b_src, "batch 는 structure passed 가 False 일 때만 실패로 세야 한다")

# ⑪ GPT 는 input_fidelity 를 안 받는다(실측) — 설정이 비어 있어야 그 파라미터를 안 보낸다
pcfg = load("providers.yaml")["openai"]
ok(not pcfg.get("input_fidelity"),
   f"gpt-image-2 는 input_fidelity 미지원 — providers.yaml 값이 비어 있어야 한다(실제 {pcfg.get('input_fidelity')!r})")

# ⑫ 재시도 전 파일 스트림 되감기 (안 하면 2회차에 0바이트가 나가 엉뚱한 오류로 둔갑)
o_src = open("src/bna/providers/openai_img.py", encoding="utf-8").read()
ok("stream.seek(0)" in o_src, "_post 는 재시도 전에 파일 스트림을 되감아야 한다")

# ⑬ 랜드마크는 Tasks API 여야 한다 (mediapipe 1.x 에 mp.solutions 가 없다)
l_src = open("src/bna/qa/landmarks.py", encoding="utf-8").read()
ok("mp.solutions.face_mesh.FaceMesh(" not in l_src and "FaceLandmarker" in l_src,
   "landmarks 는 옛 FaceMesh 호출이 아니라 Tasks API(FaceLandmarker)를 써야 한다")

# ⑭ 즉시 업로드 훅이 '완료 지점' 두 곳에 살아 있는가 (2026-09-08 성연서님 "최대한 즉각적으로")
#    빠지면 아무 오류 없이 최대 10분 지연으로 되돌아간다 — 화면만 보고는 못 알아챈다.
pr_src = open("src/bna/progress.py", encoding="utf-8").read()
q_src = open("src/bna/queue.py", encoding="utf-8").read()
ok("cloudpush.nudge" in pr_src, "progress.set(사진 1장 판정)이 끝나면 클라우드로 밀어 올려야 한다")
ok("cloudpush.nudge" in q_src, "queue 러너가 배치를 끝내면 클라우드로 밀어 올려야 한다")
# 사람이 기다리는 건 생성이 아니라 검수다 — 판정·규칙 승격도 즉시 올라가야 한다 (2026-09-10).
api_src = open("src/bna/api.py", encoding="utf-8").read()
ok("cloudpush.nudge" in api_src.split("def save_review")[1][:1200],
   "검수 저장이 끝나면 클라우드로 밀어 올려야 한다")
ok(api_src.count("cloudpush.nudge") >= 2, "규칙 승격도 클라우드로 밀어 올려야 한다")

# ⑮ 스위치가 실제로 먹는가 — 꺼 두면 프로세스를 띄우지 않는다(다른 PC·CI 에서 조용히)
import os as _os
from bna import cloudpush
_os.environ["BNA_AUTO_PUSH"] = "0"
ok(cloudpush.nudge("회귀") is False and cloudpush.enabled()[0] is False,
   "BNA_AUTO_PUSH=0 이면 업로드를 시도하지 않아야 한다")
_os.environ.pop("BNA_AUTO_PUSH")

# ⑯ 겹쳐 돌지 않는가 — 사진 10장이 연달아 끝나도 업로드는 접혀야 한다(leading + trailing)
import tempfile, time as _time, shutil as _shutil
from pathlib import Path as _Path
if _shutil.which("node"):
    tmp = _Path(tempfile.mkdtemp())
    stub, counter = tmp / "stub.mjs", tmp / "runs.txt"
    stub.write_text("import {appendFileSync} from 'node:fs';\n"
                    f"appendFileSync('{counter.as_posix()}', 'x');\n"
                    "await new Promise(r => setTimeout(r, 400));\n", encoding="utf-8")
    cloudpush.SCRIPT, cloudpush.ENVFILE, cloudpush.LOG = stub, stub, tmp / "push.log"
    cloudpush.MIN_INTERVAL = 0
    for _ in range(10):
        cloudpush.nudge("회귀")
    _time.sleep(2.0)
    runs = len(counter.read_text(encoding="utf-8")) if counter.exists() else 0
    ok(1 <= runs <= 2, f"nudge 10회는 업로드 1~2회로 접혀야 한다 — 실제 {runs}회")
    _shutil.rmtree(tmp, ignore_errors=True)
else:
    print("SKIP  node 없음 — 훅 겹침 검사 건너뜀")


# ⑰ 검수 → 드라이브 · 제외 사유 → 프롬프트 (2026-09-08 성연서님 지시)
import json as _json, tempfile as _tf
from pathlib import Path as _P
from bna import lessons as _les
from bna.planner import plan_batch as _pb

# 금지문은 있을 때만 붙는다 — 빈 문장을 프롬프트에 넣지 않는다
_v = sample_variation("selfie", seed=1)
_a = build_prompts("nasolabial", "selfie", _v, seed=1)
_b = build_prompts("nasolabial", "selfie", _v, seed=1,
                   avoid={"before": ["keep real skin texture"], "after": ["same person only"]})
ok("Avoid the mistakes" not in _a["before_prompt"], "배운 게 없으면 금지문을 안 붙인다")
ok("keep real skin texture." in _b["before_prompt"], "before 금지문이 프롬프트에 들어간다")
ok("same person only." in _b["after_prompt"], "after 금지문이 프롬프트에 들어간다")
ok(_b["avoid_applied"], "어느 규칙이 붙어 나갔는지 meta 에 남는다(나중에 재려면 필요)")

# 축 회피는 '덜 뽑기'지 '빼기'가 아니다 — 0 이 되면 다시 좋아졌는지 확인할 길이 없다
from collections import Counter as _C
_key = lambda p: p["angle"]["key"] if isinstance(p["angle"], dict) else p["angle"]
_base = _pb("selfie", 400, seed=7)
_top = _C(_key(p) for p in _base).most_common(1)[0][0]
_n0 = sum(1 for p in _base if _key(p) == _top)
_n1 = sum(1 for p in _pb("selfie", 400, seed=7, avoid_weights={"angle": {_top: 0.25}}) if _key(p) == _top)
ok(0 < _n1 < _n0, f"제외가 몰린 조건은 덜 뽑되 0 이 되면 안 된다 — {_top} {_n0} → {_n1}")

# 교훈 원장: 제외를 누르면 사유·조건·메모가 쌓이고, 그게 금지문·축회피로 나온다
_d = _P(_tf.mkdtemp()) / "outputs"; _d.mkdir(parents=True)
for _i in range(3):
    _it = _d / "b1" / f"{_i:04d}"; _it.mkdir(parents=True)
    _it.joinpath("meta.json").write_text(_json.dumps(
        {"treatment": "nasolabial", "mode": "selfie", "variation": {"angle": {"key": "side"}}}), encoding="utf-8")
    _les.record(_d, "b1", f"{_i:04d}", {"pick": "reject", "tags": ["손가락"], "note": "손이 6개"})
# 비교군: 같은 수만큼 정면을 채택으로 넣는다. 비교군이 없으면 "그 값이 유난히 나쁜지"를 말할 수 없고,
# 비교군 없이 누르는 것이 2026-09-10 에 고친 버그다(많이 쓴 값이 자동으로 나쁜 값이 되던 것).
for _i in range(3):
    _it = _d / "b2" / f"{_i:04d}"; _it.mkdir(parents=True)
    _it.joinpath("meta.json").write_text(_json.dumps(
        {"treatment": "nasolabial", "mode": "selfie", "variation": {"angle": {"key": "front"}}}), encoding="utf-8")
    _les.record(_d, "b2", f"{_i:04d}", {"pick": "pick", "tags": [], "note": ""})
_s = _les.summarize(_d); _act = _les.active(_d)
ok(_s["tags"].get("손가락") == 3, f"제외 사유가 집계돼야 한다 — 실제 {_s['tags']}")
ok(_act["from_tags"] == ["손가락"], "많이 찍힌 사유가 금지문으로 켜져야 한다")
ok(_act["weights"].get("angle", {}).get("side") == 0.25, "제외가 몰린 조건값은 가중치가 내려가야 한다")
ok("front" not in _act["weights"].get("angle", {}), "잘 통과한 조건값은 누르지 않아야 한다")
ok(len(_s["notes"]) == 1 and _s["notes"][0]["count"] == 3 and not _act["lines"].get("custom"),
   f"같은 자유 메모 3건은 한 줄로 병합돼 승격 대기로만 남고 자동으로 프롬프트에 들어가지 않는다 — {[(n['note'], n['count']) for n in _s['notes']]}")
ok("no hands" in _s["notes"][0]["suggest_en"], f"메모('손')를 보고 영어 초안이 채워져야 한다 — {_s['notes'][0]['suggest_en']!r}")
# 채택으로 바꿔도 과거 줄은 안 지운다(전후 비교의 근거라 append-only 여야 한다)
_les.record(_d, "b1", "0000", {"pick": "pick", "tags": [], "note": ""})
ok(len(_les.read(_d)) == 7 and _les.summarize(_d)["rejected"] == 2,
   "원장은 append-only 이고 집계는 아이템별 마지막 판정만 센다")

# 드라이브 레인: 채택만 올라가고, 제외는 지우는 게 아니라 내린다
import subprocess as _sp
_lanes = _sp.run(["node", "--input-type=module", "-e", """
import {targetsFor, planLanes, LANE_PICKED, LANE_FULL} from './ops/drive-backup.mjs';
const rv = {'b1/0000': {pick:'pick', treatment:'nasolabial', mode:'selfie'},
            'b1/0001': {pick:'reject', treatment:'nasolabial', mode:'selfie'}};
const picked = targetsFor('outputs/b1/0000/x_after.jpg', rv, {full:false});
const rejected = targetsFor('outputs/b1/0001/x_after.jpg', rv, {full:false});
const meta = targetsFor('outputs/b1/0000/meta.json', rv, {full:false});
const man = {[LANE_PICKED+'/nasolabial_selfie/b1_0000_x_after.jpg']: {id:'gone', sig:'0:0', key:'b1/0000'}};
const ev = planLanes(process.cwd(), man, {full:false, reviews:{'b1/0000':{pick:'reject'}}}).evict;
console.log(JSON.stringify({picked:picked.length, rejected:rejected.length, meta:meta.length, evict:ev.length}));
"""], cwd=str(_P(__file__).resolve().parent), capture_output=True, text=True, encoding="utf-8", errors="replace")
if _lanes.returncode == 0:
    _r = _json.loads(_lanes.stdout.strip().splitlines()[-1])
    ok(_r["picked"] == 1, "채택한 사진은 드라이브 채택본으로 간다")
    ok(_r["rejected"] == 0, "제외한 사진은 채택본에 안 올라간다")
    ok(_r["meta"] == 0, "채택본은 사진만 — meta.json 같은 부속은 안 올린다")
    ok(_r["evict"] == 1, "채택이 풀리면 채택본에서 내릴 목록에 잡힌다")
else:
    print("SKIP  node 레인 검사 —", (_lanes.stderr or "").strip().splitlines()[-1:] or "")


# ⑱ 프롬프트 구조 v2 (2026-09-09 성연서님 "1단계 구조부터") — 시술별 제약이 추첨·드리프트·조립 세 곳에 다 먹는가.
#    조용히 통과하는 결함이라 실측으로 잡는다. 문장이 아니라 '그 상황을 안 만드는' 쪽이 기준.
from bna.spec import treatment_rules as _tr, load as _load, SCENE_AXES, looks_profile
from bna.planner import plan_batch as _pb2
_V = _load("variations.yaml"); _T = _load("treatments.yaml")
ok("filler" not in _T and {"filler_nose", "filler_neck"} <= set(_T), "필러는 코필러·목주름필러 2종으로 분할돼 있어야 한다 (성연서님 확정)")
ok("expression" in _V and "expression" in SCENE_AXES, "표정 축이 있어야 한다")
for _t, _x in _T.items():
    for _f in ("must_not_change", "framing_allow", "effect_by_severity", "expression_policy", "age_weights"):
        ok(_f in _x, f"{_t}: 구조 필드 {_f} 가 있어야 한다")
_viol = {}
for _t in _T:
    _r = _tr(_t, "selfie")
    for _s in range(120):
        _p = sample_variation("selfie", _s, treatment=_t); _k = {a: x["key"] for a, x in _p.items()}
        for _a, _al in _r["allow"].items():
            if _k[_a] not in _al: _viol.setdefault(f"{_t} allow:{_a}", 0); _viol[f"{_t} allow:{_a}"] += 1
        if _k["context"] in (_V["framing_ban"].get(_k["framing"]) or []): _viol[f"{_t} framing_ban"] = _viol.get(f"{_t} framing_ban", 0) + 1
        _ca = _V["context_allow"].get(_k["background"])
        if _ca and _k["context"] not in _ca: _viol[f"{_t} context_allow"] = _viol.get(f"{_t} context_allow", 0) + 1
        if _k["context"] in (_r["ban"].get("context") or []): _viol[f"{_t} context_ban"] = _viol.get(f"{_t} context_ban", 0) + 1
        if any(_r["age_weights"].get(_k["age"], 1) <= 0 for _ in [0]): _viol[f"{_t} age0"] = _viol.get(f"{_t} age0", 0) + 1
        _sp = build_prompts(_t, "selfie", _p, _s); _af = _sp["after_variation"]
        # single_relax(단발 완화, 09-21 팔자 expression)는 잠금 위의 **허가된 예외**다 — 대신 그 축은
        #   '입 상태 유지'가 새 제약이다(바뀌어도 되지만 다문 입↔벌린 입으로는 못 간다).
        for _ax in _r["drift_lock"]:
            if _ax in _r.get("single_relax", []):
                _mt = load("variations.yaml").get("expression_traits", {}) if _ax == "expression" else {}
                if _ax == "expression" and _mt.get(_af[_ax]["key"], {}).get("mouth") != _mt.get(_p[_ax]["key"], {}).get("mouth"):
                    _viol[f"{_t} relax-mouth:{_ax}"] = _viol.get(f"{_t} relax-mouth:{_ax}", 0) + 1
                continue
            # 미모 프로필 after_relax(09-22 각도)도 허가된 예외 — 대신 이웃 한 칸이 새 제약이다(㊷가 따로 잰다).
            #   09-22 오후 `after_angles` 가 있으면 이웃표 대신 그 목록이 제약이다(㊹가 따로 잰다).
            _lp_c = looks_profile(_p.get("looks", {}).get("key"), None, _t)
            if _ax in (_lp_c.get("after_relax") or []):
                _okset = (_lp_c.get(f"after_{_ax}s") or _V.get(f"{_ax}_neighbors", {}).get(_p[_ax]["key"]) or [])
                if _af[_ax]["key"] != _p[_ax]["key"] and _af[_ax]["key"] not in _okset:
                    _viol[f"{_t} relax-nb:{_ax}"] = _viol.get(f"{_t} relax-nb:{_ax}", 0) + 1
                continue
            if _af[_ax]["key"] != _p[_ax]["key"]: _viol[f"{_t} drift:{_ax}"] = _viol.get(f"{_t} drift:{_ax}", 0) + 1
        _ak = {a: x["key"] for a, x in _af.items()}
        if _ak["context"] in (_V["framing_ban"].get(_ak["framing"]) or []): _viol[f"{_t} after framing_ban"] = _viol.get(f"{_t} after framing_ban", 0) + 1
        _sev = _sp["variation"]["before_severity"]["key"]; _lv = _sp["variation"]["effect_level"]["key"]
        if _sev in _T[_t]["effect_by_severity"] and _lv not in _T[_t]["effect_by_severity"][_sev]: _viol[f"{_t} effect_pair"] = _viol.get(f"{_t} effect_pair", 0) + 1
        if _r["expression_policy"] == "lock" and "Do not smile" not in _sp["after_prompt"]: _viol[f"{_t} expr_lock"] = _viol.get(f"{_t} expr_lock", 0) + 1
        if "the phone is not visible" not in _sp["after_prompt"]: _viol[f"{_t} after mode_extra"] = _viol.get(f"{_t} after mode_extra", 0) + 1
        if " ".join(str(_T[_t]["must_not_change"]).split())[:40] not in _sp["after_prompt"]: _viol[f"{_t} must_not_change"] = _viol.get(f"{_t} must_not_change", 0) + 1
ok(not _viol, f"시술 9종 × 120 표본에서 제약 위반이 0 이어야 한다 — {_viol}")
# 프레이밍별 동일인 잠금 — 눈이 프레임 밖이면 "same eyes" 를 요구하지 않는다 (티모 0908 실측: 눈을 끌고 들어온다)
# 2026-09-09 티모 실측으로 세 구멍을 메웠다. 검사 모수를 2종 → 9종 전수로 넓힌다:
#   ① identity_exempt 가 문구라 잠금 파일 3벌 중 한 벌에서만 먹었다 (리프팅 82/120·인중 79/120 미적용)
#   ② 좁은 Before + 넓은 After 에 크롭 지시가 붙어 같은 프롬프트의 장면문과 충돌 (360건 중 36건)
#   ③ 목 잠금의 "목을 더 어려 보이게 하지 마라" 가 목주름 시술 자체를 부정 (neck_only 58/58)
_WIDE = {"head_to_bust", "full_face", "forehead_cut"}
_seen, _bad = set(), {}
for _t in _T:
    if "selfie" not in _T[_t]["modes"]:
        continue
    for _s in range(60):
        _p = sample_variation("selfie", _s, treatment=_t); _sp = build_prompts(_t, "selfie", _p, _s)
        _bf, _af = _p["framing"]["key"], _sp["after_variation"]["framing"]["key"]
        _frs = {_bf, _af}; _ap = _sp["after_prompt"]; _head = _ap.split("Anyone comparing")[0]
        if "neck_only" in _frs:
            if "same eyes" in _ap or "same neck length" not in _ap: _bad[f"{_t} neck잠금"] = 1
            _seen.add("neck")
        elif _frs & {"lower_face", "one_cheek", "nose_to_neck"}:
            if "same eyes" in _ap or "Identity is carried by the lower face" not in _ap: _bad[f"{_t} lower잠금"] = 1
            _seen.add("lower")
        else:
            # 2026-09-11: 눈꺼풀 필러는 눈을 일부러 잠금에서 뺀다(그 눈을 바꾸는 시술이다).
            #   그래서 규칙은 "same eyes 가 있어야 한다"가 아니라 **"빼면 대신 박아야 한다"** 다 —
            #   빼기만 하고 대체 문장이 없으면 모델이 눈을 자유롭게 바꿔 다른 사람이 된다.
            if "eyes" in [str(k).lower() for k in (_T[_t].get("identity_exempt") or [])]:
                _note = " ".join(str(_T[_t].get("identity_note") or "").split())
                if not _note or _note not in _ap: _bad[f"{_t} 눈면제인데 대체 문장 없음"] = 1
            elif "same eyes" not in _ap:
                _bad[f"{_t} full잠금"] = 1
            _seen.add("full")
        # ② 생성할 사진(After)이 넓으면 크롭 지시가 붙으면 안 된다 — 장면문이 "얼굴 전체"라고 말한다
        if (_af in _WIDE) == ("keep the crop as specified" in _ap): _bad[f"{_t} 크롭지시 {_bf}->{_af}"] = 1
        # ① 시술 부위 낱말이 잠금 항목에 남아 있으면 안 된다 (After 지시와 정면 충돌)
        for _kw in (_T[_t].get("identity_exempt") or []):
            if str(_kw).lower() in _head.split("Identity")[-1].split(".")[0].lower():
                _bad[f"{_t} exempt무효:{_kw}"] = 1
        # ③ 과장 금지문은 "아래에 적은 변화는 예외" 를 달고 있어야 한다
        if "do not make the" in _ap and "Apart from the specific change described below" not in _ap:
            _bad[f"{_t} 과장금지 예외없음"] = 1
ok(not _bad, f"시술 전수 × 60 표본에서 잠금 위반이 0 이어야 한다 — {_bad}")
ok(_seen == {"neck", "lower", "full"}, f"세 잠금이 전부 실제로 뽑혀야 한다 — {_seen}")
# 비전 채점의 '해당 없음'(n/a) 은 탈락이 아니다 — 2026-09-09 실사고
# 셀카 프롬프트는 "폰이 보이지 않게" 라고 지시하는데 fingers 는 손을 요구했다. 심사가
# "Hands or phone not visible" 이라 적고 0점을 줘 **모든 셀카가 100% 탈락**했다(3장 3회씩, $3.49, 통과 0).
from bna.qa import vision as _VIS
class _FakeQA:
    def __init__(self, sc): self.sc = sc
    def qa(self, b, a, items, mode):
        return {k: {"score": self.sc.get(k, 9.0), "note": ""} for k in items}
_good = {k: 9.0 for k in load("qa_checklist.yaml")["items"]}
# 2026-09-10 성연서님 지시로 손 항목의 **뜻이 뒤집혔다**: "잘 그려졌나" → "아예 없어야 한다".
# 그래서 없을 때가 만점이고, 나오면 잘 그려졌든 아니든 탈락이다.
ok("fingers" not in _good and "hands_absent" in _good,
   f"손 항목은 hands_absent 여야 한다(옛 키 fingers 가 살아 있으면 옛 점수와 섞인다) — {sorted(_good)}")
_r = _VIS.score(b"", b"", "selfie", _FakeQA(_good))
ok(_r["passed"] and _r["failed_items"] == [] and _r["na_items"] == [],
   f"손이 안 보이면 만점 통과이고 n/a 가 필요 없다 — {_r['failed_items']} / na={_r.get('na_items')}")
_r0 = _VIS.score(b"", b"", "selfie", _FakeQA({**_good, "hands_absent": 3.0}))
ok(not _r0["passed"] and "hands_absent" in _r0["failed_items"],
   "손이 나오면 탈락이어야 한다(잘 그려졌는지와 무관)")
_rh = _VIS.score(b"", b"", "selfie", _FakeQA({**_good, "identity": 3.0}))
ok(_rh["hard_fail"] == ["identity"], "동일인 임계 미달은 여전히 hard_fail 이어야 한다")
# 심사 응답의 "n/a" 문자열이 실제로 None 으로 파싱되는가 (프로바이더 쪽 관문)
import bna.providers.openai_img as _OI
_parse = {}
for _k, _v in {"hands_absent": {"score": "n/a", "note": "없음"}, "hair": {"score": 8, "note": ""},
               "skin_texture": {"score": True, "note": ""}}.items():
    _s = _v.get("score")
    if isinstance(_s, bool): _s = None
    if isinstance(_s, (int, float)): _parse[_k] = float(_s)
    elif isinstance(_s, str) and _s.strip().lower() in ("n/a", "na", "not applicable", "none"): _parse[_k] = None
    else: _parse[_k] = 0.0
ok(_parse == {"hands_absent": None, "hair": 8.0, "skin_texture": 0.0},
   f'"n/a"→None · 숫자→그대로 · True(점수 아님)→0점(재시도) 이어야 한다 — {_parse}')
# 버전 성적표는 prompt_version(config 해시)으로만 묶인다 — 같은 버전을 다른 모델로 돌리면
# 두 모델 성적이 한 줄에 섞여 "이전 버전 대비" 비교가 조용히 무의미해진다 (0909 티모)
import tempfile as _tf, json as _js, time as _tm
from bna import lessons as _LS
with _tf.TemporaryDirectory() as _d:
    _root = _Path(_d) if (_Path := __import__("pathlib").Path) else None
    for _i, _gen in enumerate(("openai", "openai", "gemini")):
        _it = _root / "b1" / f"{_i:04d}"; _it.mkdir(parents=True)
        (_it / "meta.json").write_text(_js.dumps({
            "prompt_version": "v-테스트", "treatment": "nasolabial", "passed": True, "cost": 0.5,
            "providers": {"gen": _gen, "edit": _gen, "qa": _gen}}), encoding="utf-8")
    _rows = _LS.by_version(_root)
    ok(len(_rows) == 1 and _rows[0].get("provider_mixed") is True,
       f"한 버전 줄에 모델이 둘 섞이면 provider_mixed 로 드러나야 한다 — {[(r['version'], r.get('providers')) for r in _rows]}")
    ok(_rows[0]["providers"] == {"openai": 2, "gemini": 1}, f"모델별 장수가 세어져야 한다 — {_rows[0].get('providers')}")
# 넘기기 원장: 같은 메모는 마지막 줄만, open 만 (2026-09-10 "티모에게 넘기기")
with _tf.TemporaryDirectory() as _d:
    _hp = _Path(_d)
    _LS.handoffs_add(_hp, "각도가 벗어남", "", "각도 드리프트 과다", "axis")
    _LS.handoffs_add(_hp, "각도가 벗어남.", "", "다시 적음", "prompt_design")
    _ho = _LS.handoffs_open(_hp)
    ok(len(_ho) == 1 and _ho[0]["kind"] == "prompt_design", f"넘기기 원장은 같은 메모를 마지막 줄로 접어야 한다 — {_ho}")
    # 닫기 — 조치를 끝내면 '확인 대기'에서 빠지고 '처리됨'으로 간다
    _rv = _LS.handoffs_resolve(_hp, "각도가 벗어남", "done", "after 프롬프트의 각도 문장을 고쳤다")
    ok(_rv.get("ok") and not _LS.handoffs_open(_hp) and len(_LS.handoffs_done(_hp)) == 1,
       f"처리하면 대기에서 빠지고 처리됨으로 가야 한다 — {_rv}")
    ok(_LS.handoffs_done(_hp)[0].get("memo"), "닫힌 줄엔 무엇을 했는지(memo)가 남아야 한다")
    # ⚠ 이 줄이 핵심이다: 닫힌 메모가 승격 대기 목록으로 **돌아오면 안 된다**.
    #   열린 것만 빼면 닫는 순간 되돌아오고, 초안이 rule 이 아니라 화면은 또 '넘기기'를 보여 준다
    #   → 사람이 또 누르고 또 닫는 무한 왕복 (2026-09-10 실측 tools/_probe_handoff_loop.py).
    ok(_LS._norm("각도가 벗어남") in _LS.handoffs_notes(_hp),
       "닫힌 넘기기도 handoffs_notes 에 남아 승격 대기 목록에서 빠져야 한다(무한 왕복 방지)")
    ok("handoffs_notes(OUT)" in open("src/bna/api.py", encoding="utf-8").read(),
       "화면 payload 의 제외 기준은 handoffs_open 이 아니라 handoffs_notes 여야 한다")
    ok(not _LS.handoffs_resolve(_hp, "없는 메모", "done", "x").get("ok"), "넘긴 적 없는 메모는 못 닫는다")
    ok(not _LS.handoffs_resolve(_hp, "각도가 벗어남", "open", "x").get("ok"), "open 으로는 닫을 수 없다")
    # 소스에 날것 제어문자가 있으면 git 이 바이너리로 봐 diff·병합이 죽는다 (2026-09-10 promote.mjs 실사고)
    for _f in ("cloud/lib/promote.mjs", "cloud/push-cloud.mjs", "cloud/api/app.js"):
        _b = open(_f, "rb").read()
        ok(not any(c in _b for c in (b"\x00", b"\x1f", b"\x7f")),
           f"{_f} 에 날것 제어문자가 있으면 안 된다(이스케이프 '글자'로 써라)")
# 버전 별명은 처음 쓴 순서다 — 마지막 사용 순으로 정렬된 표에서 번호가 뒤집히면 "v2가 v1보다 나아졌다"를 거꾸로 읽는다
_al = _LS.aliases([{"version": "b", "first": 20, "real": True}, {"version": "a", "first": 10, "real": True},
                   {"version": "sim", "first": 5, "real": False}], current="c")
ok(_al == {"a": "v1", "b": "v2", "c": "v3"}, f"별명은 처음 쓴 순서 + 현재 버전은 다음 번호, 시뮬은 번호 없음 — {_al}")
# identity_exempt 가 조용히 무효가 되면(파일 표현이 갈리면) 소리 내고 죽어야 한다
try:
    _sv = sample_variation("selfie", 3, treatment="filler_nose")
    import bna.spec as _S
    _orig = _S.load("treatments.yaml")["filler_nose"]["identity_exempt"]
    _S.load("treatments.yaml")["filler_nose"]["identity_exempt"] = ["존재하지않는낱말"]
    try:
        build_prompts("filler_nose", "selfie", _sv, 3); _raised = False
    except ValueError:
        _raised = True
    finally:
        _S.load("treatments.yaml")["filler_nose"]["identity_exempt"] = _orig
    ok(_raised, "identity_exempt 가 아무 항목도 못 지우면 예외를 던져야 한다 (조용한 무효화 금지)")
except Exception as _e:                                  # noqa: BLE001
    ok(False, f"exempt 무효 감시 검사 자체가 깨졌다 — {_e!r}")
for _t in ("filler_nose", "nose_lifting"):
    _sp = build_prompts(_t, "selfie", sample_variation("selfie", 3, treatment=_t), 3)
    ok("same nose shape" not in _sp["after_prompt"] and "the alar base stay" in _sp["after_prompt"], f"{_t}: 동일인 잠금이 코를 예외로 둬야 한다 (0909 dry-run 모순)")
    ok(all(sample_variation("selfie", s, treatment=_t)["extras"]["key"] not in ("glasses", "glasses_thick") for s in range(150)), f"{_t}: 안경이 콧대를 가리면 안 된다")
_neck = _pb2("selfie", 40, 3, treatment="filler_neck")
ok(all(p["framing"]["key"] in ("nose_to_neck", "neck_only") for p in _neck), "목주름 필러는 목이 화면에 있는 프레이밍만 (플래너)")
ok(all(p["context"]["key"] != "necklace" for p in _neck), "목주름 필러에 목걸이가 없어야 한다 (플래너)")
ok(all(p["age"]["key"] not in ("late_teens", "early_20s") for p in _pb2("selfie", 40, 3, treatment="nasolabial")), "팔자주름에 10대·20대 초가 없어야 한다 (플래너)")
ok(all(p["expression"]["key"] == "neutral_closed" for p in _pb2("clinical", 10, 3, treatment="nasolabial")), "임상은 무표정 고정")
# 임상 프롬프트 v1 (2026-09-15): 리그 3벌 세트 고정 · After 는 '같은 부스에서 따로 찍은 사진' + 살짝 다름 요구 · 셀카 문장은 임상에 안 붙는다
_pc15 = build_prompts("nasolabial", "clinical", sample_variation("clinical", 5, treatment="nasolabial"), 5, series=["immediate", "2w"])
ok(_pc15["variation"]["rig"]["key"] in ("grey_studio", "blue_backdrop", "clinic_wall"), "임상 리그는 3벌 중 하나를 세트마다 뽑는다")
ok("plainer and more tired" not in _pc15["before_prompt"] and "greasy T-zone" not in _pc15["before_prompt"], "임상 Before 에 셀카용 '피곤·번들거림' 문장이 안 붙는다")
ok("Keep identical" not in _pc15["after_prompt"] and "separate exposure" in _pc15["after_prompt"], "임상 After 는 복사본이 아니라 따로 찍은 사진(살짝 다름 요구)")
ok("later the same day" in _pc15["afters"][0]["after_prompt"] and "later visit" in _pc15["afters"][1]["after_prompt"], "임상 다시 찍기: 직후 = 같은 날, 2주 = 다른 날")
ok(all(k in _pc15["after_prompt"] for k in ("flyaways", "eyes are open a slightly different amount", "collar, neckline, straps and folds")) and "wearing is different" not in _pc15["after_prompt"],
   "살짝 다름 3항목(잔머리·눈/입·옷 매무새)이 문안에 있고, 옷은 같은 옷 (2026-09-15 저녁 연서님)")
# 보통 인물 기준(09-21 미모 프로필은 미모 인물의 피부 읽힘을 따로 바꾼다 — ㊴가 그쪽을 잰다)
#   구도도 얼굴 전체로 못박는다(바스트 컷은 피부 읽힘 문장이 따로다 — 시드에 맡기면 09-22 게이트 뒤 바스트가 뽑혔다)
ok("tired" in build_prompts("nasolabial", "selfie", {**sample_variation("selfie", 5, treatment="nasolabial"),
                                                     "looks": {"key": "ordinary", "text": ""},
                                                     "framing": {"key": "full_face", "text": "the whole face fills the frame"}}, 5)["before_prompt"],
   "셀카 Before 의 피부 읽힘 문장은 그대로(보통 인물)")
# 첫 실회차 "겹쳐놔도 똑같다" 수정 (2026-09-15 저녁): 임상은 mild·subtle 안 뽑고, After 문안은 편집 지시가 아니다
_c15 = [build_prompts("nasolabial", "clinical", sample_variation("clinical", s, treatment="nasolabial"), s) for s in range(20)]
ok(all(p["variation"]["effect_level"]["key"] != "subtle" for p in _c15), "임상은 subtle 효과를 뽑지 않는다 — 전후가 비교에서 보여야 한다")
ok(all(p["variation"]["before_severity"]["key"] != "mild" for p in _c15 if p["variation"]["age"]["key"] not in ("late_teens", "early_20s", "late_20s")),
   "임상 30대 이상은 mild Before 를 뽑지 않는다 (20대는 나이 하향으로 mild 가 될 수 있고, 그때도 효과는 subtle 이 아니다)")
ok("Edit this exact photo" not in _c15[0]["after_prompt"] and "must not be a copy" in _c15[0]["after_prompt"],
   "임상 After 는 '이 사진을 편집'이 아니라 '두 번째 사진' + 복사본 금지")
ok(any(build_prompts("nasolabial", "selfie", sample_variation("selfie", s, treatment="nasolabial"), s)["variation"]["before_severity"]["key"] == "mild" for s in range(30)),
   "셀카는 종전대로 mild 도 뽑힌다")
# 참조는 세트가 뽑은 리그와 같은 것만 (2026-09-15 티모 선결 B)
from bna import refs as _refs15
_v15 = build_prompts("lifting", "clinical", sample_variation("clinical", 5, treatment="lifting"), 5)["variation"]
_v15 = {**_v15, "rig": {"key": "blue_backdrop", "text": ""}}
_f15 = _refs15.pick_files("clinical", _v15, treatment="lifting")
ok(_f15 == ["clinical/lifting_before_01.jpg"], f"임상 Before 참조는 세트 리그(blue_backdrop)와 같은 것만 — {_f15}")
ok(_refs15.pick_files("clinical", {**_v15, "rig": {"key": "grey_studio", "text": ""}}, treatment="lifting") == [],
   "리프팅에 회색 스튜디오 참조가 없으면 다른 리그 사진을 억지로 붙이지 않는다(빈 목록)")
ok(_refs15.pick_files("clinical", {**_v15, "rig": {"key": "clinic_wall", "text": ""}}, treatment="lifting", when="4w") == ["clinical/lifting_after4w_02.jpg"],
   "임상 After 참조도 리그·시점이 맞는 것만")
# 임상 After 편집: 첫 장 = Before, 참조는 뒤 · 마스크는 알파 채널로 (2026-09-15 티모)
import io as _io15, os as _os15
from PIL import Image as _Im15
from bna.providers import openai_img as _oi15
_m15 = _Im15.new("L", (8, 8), 0); _m15.putpixel((1, 1), 255)
_mb15 = _io15.BytesIO(); _m15.save(_mb15, "PNG")
_a15 = _Im15.open(_io15.BytesIO(_oi15.alpha_mask(_mb15.getvalue())))
ok(_a15.mode == "RGBA" and _a15.getpixel((1, 1))[3] == 0 and _a15.getpixel((0, 0))[3] == 255,
   "OpenAI 마스크: 흰색(편집 허용) → 투명, 검정(보존) → 불투명")
_key15 = _os15.environ.get("OPENAI_API_KEY")
_os15.environ["OPENAI_API_KEY"] = _key15 or "selftest-dummy"          # 실호출 없음 — _post 를 가로챈다
try:
    _p15, _seen15 = _oi15.OpenAIProvider(), {}
    _p15._post = lambda path, files=None, data=None, body=None, retry_without=(), extra=None: (_seen15.update(files=files, data=data), {"data": [{"b64_json": ""}]})[1]
    _p15.edit(b"BEFORE", "p", _mb15.getvalue(), [b"REF1", b"REF2"], "4:5")
    ok(_seen15["data"].get("size") == "1024x1280", f"편집도 Before 와 같은 크기로 요청한다(크기가 다르면 정렬 검사가 가짜 오차) — {_seen15['data'].get('size')}")
    ok([f[1].getvalue() for n, f in _seen15["files"] if n == "image[]"] == [b"BEFORE", b"REF1", b"REF2"],
       "편집 입력 첫 장 = Before, 참조는 그 뒤(마스크는 첫 장에만 걸린다)")
    ok(_Im15.open(_io15.BytesIO(next(f[1].getvalue() for n, f in _seen15["files"] if n == "mask"))).mode == "RGBA",
       "편집 호출에 실제로 나가는 마스크가 RGBA")
finally:
    if _key15 is None:
        _os15.environ.pop("OPENAI_API_KEY", None)
ok("self.p_edit.edit, before_b, after_prompt, mask_b, edit_refs, spec[\"aspect\"]" in open("src/bna/batch.py", encoding="utf-8").read(),
   "임상 After 편집 호출이 스타일 참조를 실제로 넘긴다(provider 만 받고 배치가 안 넘기면 죽은 기능)")
# 진행 기록 교체가 '읽는 중'과 겹쳐도 배치가 안 죽는다 (2026-09-15 티모 — 임상 첫 실회차 b925 가 이 예외로 중단)
import tempfile as _tf15
from pathlib import Path as _P15
from bna import progress as _pg15
_real_replace15, _calls15 = _pg15.os.replace, {"n": 0}
def _flaky15(a, b):
    _calls15["n"] += 1
    if _calls15["n"] <= 2:
        raise PermissionError("[WinError 5] reader holds the file")
    return _real_replace15(a, b)
def _always15(a, b):
    raise PermissionError("[WinError 5] always")
with _tf15.TemporaryDirectory() as _td15:
    _src15 = _P15(_td15) / "x.tmp"
    _src15.write_text("{}", encoding="utf-8")
    try:
        _pg15.os.replace = _flaky15
        ok(_pg15._replace(_src15, _P15(_td15) / "x.json") is True and _calls15["n"] == 3,
           f"교체가 두 번 거부돼도 다시 시도해 성공한다 — 시도 {_calls15['n']}회")
        _src15.write_text("{}", encoding="utf-8")
        _pg15.os.replace = _always15
        ok(_pg15._replace(_src15, _P15(_td15) / "x.json") is False,
           "끝내 거부되면 예외 없이 이번 기록만 건너뛴다(유료 배치를 죽이지 않는다)")
    finally:
        _pg15.os.replace = _real_replace15
# 씨앗 은행 인물 참조 (2026-09-15 저녁 티모, 0909 ②안) — 통과한 파생 얼굴만 · 성별 같고 나이 ±1칸 · 꺼져 있으면 아무것도 안 붙는다
from bna import seedbank as _sb15
_rows15 = [{"file": "a.jpg", "gender": "female", "age_bucket": "30s", "passed": True},
           {"file": "b.jpg", "gender": "male", "age_bucket": "late_20s", "passed": True}]
_vf15 = {"gender": {"key": "female"}, "age": {"key": "40s"}}
ok([r["file"] for r in _sb15.candidates(_vf15, _rows15)] == ["a.jpg"], "여성 40대엔 여성 30대 얼굴만(±1칸) — 남성 얼굴은 안 붙는다")
ok(_sb15.candidates({"gender": {"key": "female"}, "age": {"key": "60s"}}, _rows15) == [],
   "나이가 2칸 넘게 벌어지면 붙이지 않는다(종전 글 조건 Before 로)")
ok(_sb15.age_bucket(31) == "30s" and _sb15.age_bucket(24) == "early_20s" and _sb15.age_bucket(64) == "60s",
   "추정 나이 → variations.yaml 나이대 키")
_real_cfg15 = _sb15._cfg
with _tf15.TemporaryDirectory() as _sbd15:
    for _n15 in ("a.jpg", "c.jpg"):
        (_P15(_sbd15) / _n15).write_bytes(b"x")
    (_P15(_sbd15) / "attrs.json").write_text(_json.dumps({"pool": [
        {"file": "a.jpg", "gender": "female", "age_bucket": "30s", "passed": True},
        {"file": "c.jpg", "gender": "female", "age_bucket": "30s", "passed": False},
        {"file": "gone.jpg", "gender": "female", "age_bucket": "30s", "passed": True}]}), encoding="utf-8")
    try:
        _sb15._cfg = lambda: {"clinical_before_person_ref": True, "pool_dir": _sbd15, "attrs": str(_P15(_sbd15) / "attrs.json")}
        ok([r["file"] for r in _sb15.pool()] == ["a.jpg"], "통과 못 한 파생(원본을 닮음)·파일 없는 항목은 후보에서 빠진다")
        ok(_sb15.pick(_vf15, "k")[1] == "a.jpg", "켜져 있고 맞는 얼굴이 있으면 그 얼굴을 고른다")
        _sb15._cfg = lambda: {"clinical_before_person_ref": False, "pool_dir": _sbd15, "attrs": str(_P15(_sbd15) / "attrs.json")}
        ok(_sb15.pick(_vf15, "k") == (None, None), "스위치가 꺼져 있으면 얼굴을 안 고른다")
    finally:
        _sb15._cfg = _real_cfg15
_bsrc15 = open("src/bna/batch.py", encoding="utf-8").read()
# 09-21: Before 호출의 장면 참조 칸은 gen_refs(기본 = style_refs, 미모 프로필이면 외모 참조 2·3번째 장이 앞에 붙는다)
ok("seedbank.pick(" in _bsrc15 and 'spec["aspect"], person_b, gen_refs, None' in _bsrc15
   and "gen_refs = style_refs" in _bsrc15,
   "배치가 고른 얼굴을 Before 호출의 인물 참조 칸으로 실제로 넘긴다(고르기만 하고 안 넘기면 죽은 배선)")
ok(set(sample_variation("selfie", 1)) >= set(SCENE_AXES), "treatment 없이도(예전 호출) 추첨이 된다")
from bna.qa import landmarks as _lm
import numpy as _np
_pts = _np.zeros((468, 2)); _pts[10] = (100, 0); _pts[152] = (100, 200)
for _i in _lm.JAW_LINE: _pts[_i] = (50 + _i % 100, 200)
_poly = _lm.neck_polygon(_pts)
ok(len(_poly) == 2 * len(_lm.JAW_LINE) and max(y for _, y in _poly) > 200, "목 마스크는 턱선에서 아래로 내린 폴리곤이어야 한다")
# 머리가 기울어도 목을 따라가야 한다 (0909 티모 실측: 아래(+y)로만 내리면 20도에서 IoU 62%)
_rot = _np.zeros((468, 2)); _c = _np.array([200.0, 250.0]); _th = _np.radians(25.0)
_R = _np.array([[_np.cos(_th), -_np.sin(_th)], [_np.sin(_th), _np.cos(_th)]])
for _i, _xy in {10: (200.0, 100.0), 152: (200.0, 400.0)}.items(): _rot[_i] = _c + _R @ (_np.array(_xy) - _c)
for _i in _lm.JAW_LINE: _rot[_i] = _c + _R @ (_np.array([200.0, 400.0]) - _c)
_pg = _lm.neck_polygon(_rot)
_step = _np.array(_pg[-1]) - _np.array(_pg[0])          # 아래변으로 내려간 방향
_axis = _rot[152] - _rot[10]
_cos = float(_step @ _axis / (_np.linalg.norm(_step) * _np.linalg.norm(_axis)))
ok(_cos > 0.999, f"기운 머리에서도 목 마스크는 얼굴 축 방향으로 내려가야 한다 — cos={_cos:.3f}")

# ⑲ 홈 재구성 (2026-09-09) — 요청 본문은 한 번만 읽는다(두 번 읽으면 단일 스레드 서버가 멈춘다), 시뮬·샘플은 기본 제외, 목표 장수 저장
_api_src = (_P(__file__).parent / "src" / "bna" / "api.py").read_text(encoding="utf-8")
ok(_api_src.count("self._body()") == 1, "do_POST 는 본문을 딱 한 번만 읽어야 한다 (두 번째 read 는 영원히 블록)")
from bna import api as _api
_o = _api.overview_payload(14); _o2 = _api.overview_payload(14, include_sim=True)
ok(_o["window"]["total"] <= _o2["window"]["total"], "시뮬·샘플 포함 시 생성 수가 줄어들면 안 된다")
ok(all(b["target"] >= 1 for b in _o["board"]) and len(_o["board"]) >= len(_load("treatments.yaml")), "현황판은 시술 전부 + 목표 장수를 낸다")
ok("picked" in _o["window"] and "pending_total" in _o and "na_rate" in _o["gates"]["identity"], "홈 KPI 에 채택·검수 대기·게이트 못 잼 비율이 있어야 한다")

# ⑳ 인물 조합이 배치를 넘어 반복되지 않는다 (2026-09-09 티모 실측 — "같은 조건이면 얼굴이 비슷하다")
#    뿌리는 둘이었다: 러너 기본 seed 가 5 로 고정 + 중복 금지가 배치 안에서만.
#    같은 seed 로 두 번 돌린 09-09 nasolabial 배치의 0000·0002 가 인물 11축 전부 동일했고
#    그 두 쌍의 얼굴 유사도가 0.421·0.392(전체 평균 0.099)였다.
from bna.planner import plan_batch as _pb, signature as _sig
_a = _pb("selfie", 8, 5, treatment="nasolabial")
_b = _pb("selfie", 8, 5, treatment="nasolabial")
ok([_sig(p) for p in _a] == [_sig(p) for p in _b], "같은 seed 는 같은 명단이어야 한다 (재현성은 유지)")
_sa = {_sig(p) for p in _a}
_c = _pb("selfie", 8, 5, treatment="nasolabial", avoid_sigs=_sa)
ok(len({_sig(p) for p in _c} & _sa) == 0, "과거 배치가 쓴 인물 조합은 다음 배치에서 다시 안 나와야 한다")
ok(len(_c) == 8, "과거 조합을 피하느라 배치 장수가 줄면 안 된다")
# 조합이 말랐을 때: 배치가 조용히 비는 게 아니라 배치 안 중복 금지만 남기고 채운다(fail-open)
_one = {k: v for k, v in zip(
    ["country", "age", "gender", "face_shape", "skin_tone", "skin_condition", "body_type",
     "hair_style", "hair_color", "eyes", "looks", "extras"],
    ["korea", "30s", "female", "oval", "fair", "clear", "slim", "bob", "black", "double", "ordinary", "none"])}
_d = _pb("selfie", 4, 1, fixed=_one, treatment="nasolabial")
_e = _pb("selfie", 4, 1, fixed=_one, treatment="nasolabial", avoid_sigs={_sig(p) for p in _d})
ok(len(_e) == 1, "가능한 조합이 1개뿐이면 과거에 썼더라도 그 1개를 낸다 (fail-open)")
_runner = (_P(__file__).parent / "tools" / "run-selfie-batches.ps1").read_text(encoding="utf-8")
ok("[int]$Seed = 0" in _runner and "Get-Random" in _runner,
   "러너 기본 seed 는 고정값이 아니라 회차마다 새로 뽑아야 한다 (고정이면 명단이 통째로 반복된다)")
_batch_src = (_P(__file__).parent / "src" / "bna" / "batch.py").read_text(encoding="utf-8")
ok("avoid_sigs=past_signatures()" in _batch_src and "remember(plans" in _batch_src,
   "Batch 는 과거 인물 조합을 읽어 피하고 이번 조합을 남겨야 한다 (한쪽만 있으면 레지스트리가 안 자란다)")

# ⑳ 경과 시리즈 (2026-09-09 성연서님: 기본 직후·2주, 세트 단위 채택)
from bna.spec import series_points as _sp
_v = sample_variation("selfie", 5, treatment="nasolabial")
_pl = build_prompts("nasolabial", "selfie", _v, 5); _sr = build_prompts("nasolabial", "selfie", _v, 5, series=["2w", "immediate"])
ok(_pl["series"] is None and len(_pl["afters"]) == 1, "시리즈가 아니면 After 하나(종전과 같다)")
ok(_sr["series"] == ["immediate", "2w"] and [a["when"] for a in _sr["afters"]] == ["immediate", "2w"], "시점은 시간순으로 정렬된다")
# 허용 강도는 **설정에서 읽는다**(2026-09-21) — 여기 이름을 손으로 적어 두면 강도를 한 칸 올릴 때마다
#   이 줄이 같이 빨개져, 고친 사람이 "회귀가 깨졌다"로 읽고 되돌리게 된다. 재는 건 이름이 아니라
#   '직후 컷이 낮춰지지 않았나'(effect_lowered=False)다.
_NASO_LV = tuple(load("treatments.yaml")["nasolabial"]["effect_levels"])
ok(_sr["afters"][0]["effect_level"] in _NASO_LV and _sr["afters"][0]["effect_lowered"] is False
   and "barely visible yet" not in _sr["afters"][0]["after_prompt"],
   "필러(팔자)의 직후 컷은 최종 강도다 — immediate_level: final (2026-09-11)")
# 낮추는 길은 **필러가 아닌 시술**로 잰다 — 필러는 B안 이후 어느 시점도 안 낮춘다.
_vn = sample_variation("selfie", 5, treatment="nose_lifting")
_sr3 = build_prompts("nose_lifting", "selfie", _vn, 5, series=["1w", "2w"])
ok(_sr3["afters"][0]["effect_level"] == "subtle" and _sr3["afters"][0]["effect_lowered"] is True,
   "에너지 시술의 중간 시점(1주)은 종전대로 강도를 낮춘다 — 낮추는 길 자체가 죽으면 안 된다")
ok(_sr["afters"][1]["effect_level"] in _NASO_LV and _sr["afters"][1]["effect_lowered"] is False
   and _sr["after_prompt"] == _sr["afters"][-1]["after_prompt"], "마지막 시점이 최종 강도이고 after_prompt 대표")
ok(len({a["after_prompt"] for a in _sr["afters"]}) == 2, "시점마다 프롬프트가 다르다")
ok("right after the procedure" in _sr["afters"][0]["after_prompt"] and "two weeks" in _sr["afters"][1]["after_prompt"], "시점 문구가 각자 붙는다")
ok(_sp("skin_pores", ["immediate", "2w"]) == ["2w"], "시술이 허용하지 않는 시점은 빠진다")
from bna.api import after_files_of as _afo, last_after as _la
_files = ["x_before.jpg", "x_after_2w.jpg", "x_after_immediate.jpg"]
ok(list(_afo(_files)) == ["immediate", "2w"] and _la(_files) == "x_after_2w.jpg", "파일 이름 → 시점 순 after_files, 대표는 마지막 시점")
ok(_afo(["x_before.jpg", "x_after.jpg"]) == {"final": "x_after.jpg"}, "시리즈가 아니면 final 하나")
from bna.api import estimate_payload as _est
_e1 = _est({"treatment": "nasolabial", "mode": "selfie", "count": 8}); _e2 = _est({"treatment": "nasolabial", "mode": "selfie", "count": 8, "series": ["immediate", "2w"]})
ok(_e2["afters"] == 2 and _e2["expected_cost_usd"] > _e1["expected_cost_usd"], "시리즈 비용은 시점 수만큼 커진다")

# ⑳-2 직후 컷에는 effect_visible 을 걸지 않는다 (2026-09-11 빌디 지적, 시리즈 켜기 전 수리)
#      프롬프트는 직후 컷에 "변화가 거의 안 보여야 하고 최종 결과를 보여주지 마라"(early)라고 시키는데
#      검수는 같은 컷에 "눈에 띄어야 한다 6점 이상"을 요구했다 = 지시대로 그릴수록 떨어지는 구조.
#      실생성 회차에 시리즈가 0건이라 아직 안 터졌을 뿐이고, 켜는 순간 직후 컷이 전멸한다.
ok(_sr3["afters"][0]["effect_lowered"] is True and _sr3["afters"][1]["effect_lowered"] is False,
   "강도를 낮춘 시점만 effect_lowered 로 표시된다(마지막 시점은 최종 강도라 아니다)")
ok(all(a["effect_lowered"] is False for a in _sr["afters"]),
   "필러(팔자)는 직후부터 최종 강도라 낮춘 시점이 하나도 없다")
ok(_pl["afters"][0]["effect_lowered"] is False, "시리즈가 아니면 낮추지 않으므로 종전대로 effect_visible 을 건다")
# ⑳-2b 직후 컷의 면제는 강도와 별개다 (2026-09-18, 배치 20260918-084112-2fae 실측)
#   필러 직후는 최종 강도(=effect_lowered False)인데 프롬프트가 흔적·붓기를 시키므로 심사가
#   "자국은 보이지만 분명한 개선은 없다"로 3.0 을 준다 — 직후 4컷 전부 탈락, 같은 세트 2주는 8.0 통과.
#   → 판정 플래그를 `effect_ungated` 로 갈랐다(면제는 넓히고 '강도를 낮췄나'는 그대로 보고에 남긴다).
ok(_sr["afters"][0]["when"] == "immediate" and _sr["afters"][0]["effect_ungated"] is True,
   "시리즈의 직후 컷은 강도를 안 낮췄어도 effect_visible 로 떨어지지 않는다")
ok(_sr["afters"][-1]["effect_ungated"] is False,
   "가라앉은 뒤 컷은 반드시 효과 판정을 받는다 — 여기까지 면제하면 아무도 효과를 안 본다")
_pl_i = build_prompts("nasolabial", "selfie", sample_variation("selfie", 5), 5)
ok(all(a["effect_ungated"] is False for a in _pl_i["afters"]),
   "시리즈가 아닌 한 장짜리는 면제하지 않는다(그 세트엔 효과를 볼 다른 컷이 없다)")


class _QaStub:
    """검수 모델 대역 — effect_visible 만 컷 아래(3점), 나머지는 만점."""
    def qa(self, b, a, items, mode):
        return {k: {"score": 3.0 if k == "effect_visible" else 10.0, "note": ""} for k in items}


from bna.qa import vision as _vis
_vg = _vis.score(b"", b"", "selfie", _QaStub())
_vu = _vis.score(b"", b"", "selfie", _QaStub(), ungate=("effect_visible",))
ok("effect_visible" in _vg["failed_items"] and not _vg["passed"], "평소엔 effect_visible 미달이 탈락이다")
ok(_vu["failed_items"] == [] and _vu["passed"] and _vu["ungated"] == ["effect_visible"],
   f"직후 컷은 effect_visible 로 탈락하지 않는다 — 실제 {_vu['failed_items']}")
ok(_vu["scores"]["effect_visible"]["score"] == 3.0,
   "점수는 그대로 남긴다(안 묻는 게 아니라 안 거는 것 — 직후 컷이 정말 변화가 적었나를 나중에 검산한다)")
_batch_src2 = (_Path(__file__).resolve().parent / "src" / "bna" / "batch.py").read_text(encoding="utf-8")
ok('af.get("effect_ungated")' in _batch_src2 and '"immediate"' not in _batch_src2,
   "배치는 시점 이름을 다시 보지 말고 spec 이 실어 보낸 effect_ungated 하나만 봐야 한다(규칙 두 벌 금지)")


# ⑳-3 시술별 직후 강도 + 사실 카드 (2026-09-11 빌디 지적 3건)
#     ① 필러는 직후가 곧 결과다 — 일괄 early 로 낮추면 "직후에 바로 보인다"는 판매 포인트를 우리가 지운다.
#     ② 그 카드 칸의 실패 모드는 '틀린 값'이 아니라 **아무도 안 읽는 값**이라, 죽은 설정은 소리 내고 죽는다.
from bna.spec import check_treatment_facts as _ctf, FACT_KEYS_PROMPT as _FKP
import yaml as _yaml
_tr_all = _yaml.safe_load((_P(__file__).parent / "config" / "treatments.yaml").read_text(encoding="utf-8"))
_filler = [k for k, v in _tr_all.items() if (v.get("series_levels") or {}).get("immediate") == "final"]
ok(sorted(_filler) == ["filler_eyelid", "filler_neck", "filler_nose", "nasolabial", "philtrum"],
   f"필러 5종만 직후=최종 강도 — 실제 {sorted(_filler)}")
ok(not [k for k, v in _tr_all.items() if v.get("immediate_level") is not None],
   "폐기된 immediate_level 이 설정에 남아 있으면 안 된다(승격 = series_levels)")
# ⑳-3b B안: 필러는 1주도 최종 강도다 — 한 칸만 올리면 1주가 직후보다 약해지는 역전이 생긴다
for _k in _filler:
    _sl = _tr_all[_k]["series_levels"]
    ok("1w" in (_tr_all[_k].get("timeline") or []) and _sl.get("1w") == "final",
       f"{_k}: 1주 컷이 있고 그것도 최종 강도다 (여신티켓 '효과 약 3일 후')")
_lv = [a["effect_level"] for a in build_prompts("nasolabial", "selfie", _v, 5,
                                                series=["immediate", "1w", "2w"])["afters"]]
ok(len(set(_lv)) == 1, f"필러 시리즈는 시점이 지나며 약해지지 않는다 — 실제 {_lv}")
for _k in _tr_all:
    _ctf(_k)                                       # 전 시술 카드 검증 — 오타 칸·죽은 설정이면 여기서 터진다
ok(True, "전 시술의 immediate_level·facts 카드가 검증을 통과한다")
import bna.spec as _spec_mod
_orig_load = _spec_mod.load
def _raises(patch):
    _spec_mod.load = lambda n: {**_orig_load(n), "lifting": patch} if n == "treatments.yaml" else _orig_load(n)
    try:
        _ctf("lifting"); return False
    except ValueError:
        return True
    finally:
        _spec_mod.load = _orig_load
ok(_raises({**_tr_all["lifting"], "series_levels": {"immediate": "final"}}),
   "timeline 에 없는 시점(리프팅의 immediate)을 series_levels 에 달면 소리 내고 죽는다")
ok(_raises({**_tr_all["lifting"], "series_levels": {"2w": "nope"}}), "없는 강도 이름도 막는다")
ok(_raises({**_tr_all["lifting"], "immediate_level": "final"}),
   "폐기된 immediate_level 은 조용히 무시하지 말고 '승격됐다'고 알리며 죽는다")
ok(_FKP == ("immediate_marks", "immediate_avoid"), "프롬프트에 실리는 카드 칸은 직후 흔적·직후 금지 둘")
# ⑳-4 괄호 안 쉼표는 항목 구분자가 아니다 (2026-09-11 눈꺼풀 필러에서 실제로 터진 자리)
from bna.spec import _split_items as _si, _drop_identity_items as _dii
ok(_si("same eyes (shape, size, spacing, eyelid type), same eyebrows, same nose") ==
   ["same eyes (shape, size, spacing, eyelid type)", "same eyebrows", "same nose"],
   "괄호 안 쉼표로 항목이 갈라지면 안 된다")
_txt, _n = _dii("Identity must be preserved precisely: same eyes (shape, size, spacing, eyelid type), "
                "same eyebrows, same nose shape. Anyone comparing.", ["eyes"])
ok(_n == 1 and "eyelid type)" not in _txt and "same eyebrows, same nose shape" in _txt,
   f"눈 항목만 통째로 빠지고 괄호 잔재가 안 남아야 한다 — 실제 {_txt!r}")
_pe = build_prompts("filler_eyelid", "selfie", sample_variation("selfie", 3, treatment="filler_eyelid"), 3)
ok("size, spacing, eyelid type)" not in _pe["after_prompt"] and "same eyes" not in _pe["after_prompt"],
   "눈꺼풀 필러 실프롬프트에 깨진 잠금 잔재가 없어야 한다")
ok("eye_area" == _tr_all["filler_eyelid"]["mask_region"] and
   set(_tr_all["filler_eyelid"]["framing_allow"]) == {"full_face", "forehead_cut"},
   "눈꺼풀 필러는 눈이 프레임에 남는 프레이밍만 쓴다(lower 계열엔 eyes 항목이 없어 면제가 터진다)")
from bna.qa.landmarks import REGIONS as _RG
ok(_RG["eye_area"] == "periorbital_l+periorbital_r" and not (set(_RG["periorbital_l"]) & set(_RG["periorbital_r"])),
   "눈 마스크는 좌우 따로다 — 한 폴리곤으로 이으면 미간이 통째로 편집 허용이 된다")
ok(all(0 <= i <= 467 for k in ("periorbital_l", "periorbital_r") for i in _RG[k]),
   "랜드마크 인덱스가 범위 안이어야 한다")
# 새 시술은 화면에도 있어야 한다 — '기타' 폴백이 있어 안 보이진 않지만 부위 줄이 틀린다("띄울 길까지가 기능")
_web = (_P(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")
_grp = _web.split("const GROUPS = [")[1].split("];")[0]
_missing = [k for k in _tr_all if f"'{k}'" not in _grp]
ok(not _missing, f"treatments.yaml 의 시술이 전부 화면 GROUPS 에 있어야 한다 — 빠진 것 {_missing}")
_mx_src = (_P(__file__).parent / "config" / "prompts" / "mode_extra.yaml").read_text(encoding="utf-8")
ok("nothing is resting on it" not in _mx_src and "the treatment description below says is" in _mx_src,
   "'피부에 아무것도 없음'은 필러 직후(재생테이프·붓기)와 충돌한다 — '시술 설명이 말하는 것만'으로 바꿨다")
_mk = "small skin-coloured dressing patches beside each corner of the mouth"
import bna.spec as _sm
_t2 = dict(_tr_all["nasolabial"]); _t2["facts"] = {"immediate_marks": _mk}
_ol = _sm.load
_sm.load = lambda n: {**_ol(n), "nasolabial": _t2} if n == "treatments.yaml" else _ol(n)
try:
    _pf = _sm.build_prompts("nasolabial", "selfie", _v, 5, series=["immediate", "2w"])
    _pfc = _sm.build_prompts("nasolabial", "clinical", _sm.sample_variation("clinical", 5, treatment="nasolabial"), 5, series=["immediate", "2w"])
finally:
    _sm.load = _ol
ok(_mk in _pf["afters"][0]["after_prompt"] and _mk not in _pf["afters"][1]["after_prompt"],
   "사실 카드의 직후 흔적은 직후 컷에만 실린다(2주 컷에 테이프가 붙으면 그게 더 큰 사고)")
ok(_mk in _pfc["afters"][0]["after_prompt"],
   "임상 모드 직후 컷도 사실 카드를 받는다(임상엔 after_day 가 없어 mode_extra 쪽에 넣으면 조용히 빠진다)")
ok(any(sp["k"] == "facts" for sp in _pf["afters"][0]["after_parts"]),
   "화면에서 그 문장의 출처가 'facts' 로 보여야 한다(template 로 뭉개면 어디서 왔는지 못 읽는다)")
_qa_src = (_P(__file__).parent / "config" / "qa_checklist.yaml").read_text(encoding="utf-8")
ok("only part of the treated line or fold changed" in _qa_src,
   "검수 effect_visible 은 일부 구간만 바뀐 컷을 감점해야 한다(부분 소거는 시술이 아니라 지우개)")
ok("entire length of the fold" in _tr_all["nasolabial"]["after_change"],
   "팔자 시술 문장이 콧볼~입꼬리 전 구간을 못 박는다")
# 살아 있는 카드(팔자 필러)가 실제 프롬프트에 실리는가
_pn = build_prompts("nasolabial", "selfie", _v, 5, series=["immediate", "2w"])
ok("hydrocolloid dressings" in _pn["afters"][0]["after_prompt"]
   and "hydrocolloid" not in _pn["afters"][1]["after_prompt"],
   "팔자 직후 컷에만 패치·바늘 자국이 실린다(2주 컷에 남으면 그게 더 큰 사고)")
# 2026-09-11 저녁엔 패치를 통째로 뺐었다("티나게 붙어 더 AI 같다"). 2026-09-17 성연서님이 실사진 탭
#   강남언니 #118(정면 D+0)을 보고 뒤집었다 — "투명한 패치가 있어, 시술 직후는 보여야 해, 그 병원에서
#   시술한 모습이니까". 이제 직후 컷엔 패치가 **있어야** 하고, 2주 컷엔 여전히 없어야 한다.
#   ⚠ 'patch' 단독으로 재지 마라 — 피부 연속성 문장이 잡티를 셀 때 'dry patch'(각질)를 쓴다.
for _w in ("dressing", "hydrocolloid", "tape", "sticker"):
    ok(_w not in _pn["afters"][1]["after_prompt"],
       f"팔자 2주 컷에 '{_w}' 가 있으면 안 된다 — 패치는 직후에만")
ok(not any(w in _pn["afters"][0]["after_prompt"] for w in ("cotton pad", "ointment", "bandage", "gauze")),
   "직후 금지는 품목을 나열하지 않는다 — 적으면 모델이 그린다(0910 마취크림 5/5)")

# ㉒-d 머리~바스트 셀카 (2026-09-17 연서님 "클로즈업 말고 전체 셀카도" — 09-16 회의 "전신 아님, 머리~바스트 셀카 형태")
#    프레이밍 한 칸이 아니라 **본문 세 벌**(Before 본문·Before 피부 읽힘·After 본문)이 같이 바뀌어야 한다 —
#    종전 셀카 본문은 "문제 부위를 렌즈에 바짝"이라 바스트 컷과 정면충돌한다. 한 벌만 바뀌면 전은 바스트, 후는 클로즈업 지시가 된다.
_vb = load("variations.yaml")
ok("head_to_bust" in _vb["framing"] and _vb["identity_lock_by_framing"].get("head_to_bust") == "identity_lock.md"
   and _vb["identity_lock_order"][0] == "head_to_bust",
   "머리~바스트는 프레이밍 표·동일인 잠금 표(눈 있음 = 전체 잠금)·넓이 순서(가장 넓음)에 다 있어야 한다")
ok("head_to_bust" in _tr_all["nasolabial"]["framing_allow"]
   and not any("head_to_bust" in (_tr_all[k].get("framing_allow") or []) for k in _tr_all if k != "nasolabial"),
   "머리~바스트는 팔자에만 열린다(메인 시술부터 소량 재보기) — 다른 시술 framing_allow 엔 없어야 한다")
_vbf = dict(_v); _vbf["framing"] = {"key": "head_to_bust", "text": _vb["framing"]["head_to_bust"]}
_vbf["looks"] = {"key": "ordinary", "text": ""}      # 보통 인물 기준(미모 프로필은 피부 읽힘을 따로 바꾼다 — ㊴)
_pbust = build_prompts("nasolabial", "selfie", _vbf, 17, series=["immediate", "2w"])
ok("arm's length" in _pbust["before_prompt"] and "pushed close to the lens" not in _pbust["before_prompt"],
   "바스트 Before 본문은 일상 셀카 문장이고 '부위를 렌즈에 바짝' 문장이 없어야 한다")
ok("plainer and more tired" not in _pbust["before_prompt"] and "normal phone selfie" in _pbust["before_prompt"],
   "바스트 Before 피부 읽힘은 '피곤하고 못 나온 사진' 압력 대신 무보정만 지킨다")
ok("both hands are out of frame" in _pbust["before_prompt"],
   "바스트 컷도 손·폰은 화면 밖(09-10 기준) — 문장이 직접 말해야 한다")
for _ab in _pbust["afters"]:
    if _ab["after_variation"]["framing"]["key"] == "head_to_bust":
        ok("the phone is not visible" in _ab["after_prompt"] and "close to the lens" not in _ab["after_prompt"],
           f"바스트 After({_ab['when']}) 본문도 바스트 문장이어야 한다 — '부위를 렌즈에 바짝' 금지")
# 종전 본문 기준은 보통 인물·얼굴 전체로 못박는다 — 시드 5 는 09-22 미모 구도 게이트 뒤 미모·바스트로 뽑혀 이 비교가 성립하지 않았다.
_pnorm = build_prompts("nasolabial", "selfie", {**_v, "looks": {"key": "ordinary", "text": ""},
                                                "framing": {"key": "full_face", "text": _vb["framing"]["full_face"]}}, 17, series=["2w"])
ok("arm's length" not in _pnorm["before_prompt"] and "pushed close to the lens" in _pnorm["before_prompt"],
   "다른 프레이밍의 Before 본문은 종전 문장 그대로다")

# ㉒-e 미모 축 (2026-09-17 연서님 "미모도 프롬프트 축으로" — 09-16 회의 "미모 셀카형 6:4")
from collections import Counter as _Clk
from bna.planner import plan_batch as _pblk
_lk = _Clk(p["looks"]["key"] for p in _pblk("selfie", 1000, seed=17, treatment="nasolabial"))
ok(0.5 <= _lk["attractive"] / 1000 <= 0.7, f"셀카 미모 비율은 6:4 근처여야 한다 — 실제 {_lk['attractive']/10:.0f}%")
_lkc = _Clk(p["looks"]["key"] for p in _pblk("clinical", 200, seed=17, treatment="nasolabial"))
ok(set(_lkc) == {"ordinary"}, f"임상은 미모를 고르지 않는다(ordinary 고정) — 실제 {dict(_lkc)}")
ok(load("variations.yaml")["looks"]["ordinary"] == "",
   "'보통'은 빈 문장이어야 한다 — 종전 프롬프트가 글자 하나 안 바뀌어야 옛 회차와 비교가 이어진다")
_vo = dict(_v); _vo.pop("looks", None)
ok("looks" in build_prompts("nasolabial", "selfie", _vo, 5)["variation"],
   "미모 축이 없는 옛 계획도 조립돼야 한다(ordinary 로 채움)")
_va = dict(_v); _va["looks"] = {"key": "attractive", "text": load("variations.yaml")["looks"]["attractive"]}
_pa = build_prompts("nasolabial", "selfie", _va, 5)
ok(_pa["before_prompt"].startswith("Realistic unedited photo of a strikingly pretty "),
   f"미모는 인물 맨 앞 형용사여야 한다(2026-09-21 연서님 '미모가 나온 적이 없다') — 실제 {_pa['before_prompt'][:70]!r}")
ok("the kind of face that gets compliments" in _pa["before_prompt"] and "not a model" not in _pa["before_prompt"],
   "미모 특징은 구체 문장으로, 부정문('모델 아님')은 빼야 한다 — 부정문이 리얼리티 규칙 셋에 눌려 보통 얼굴로 수렴했다")
_lka = {p["age"]["key"] for p in _pblk("selfie", 1000, seed=17, treatment="nasolabial") if p["looks"]["key"] == "attractive"}
ok(_lka <= {"early_20s", "late_20s", "30s"} and _lka,
   f"미모 인물은 20~30대만 (2026-09-21 연서님) — 실제 {sorted(_lka)}")
_lko = {p["age"]["key"] for p in _pblk("selfie", 1000, seed=17, treatment="nasolabial") if p["looks"]["key"] == "ordinary"}
ok("40s" in _lko and "50s" in _lko, f"40대~는 보통 인물에서 계속 뽑혀야 한다(미모 게이트가 나이를 통째로 죽이면 안 된다) — 실제 {sorted(_lko)}")
_vs = sample_variation("selfie", seed=3, treatment="nasolabial")
ok("looks" in _vs and "age" in _vs, "단건 추첨(sample_variation)도 looks 를 age 앞에 뽑아야 한다(DRAW_ORDER)")

# ㉒-c 팔자 + 마리오네트 (2026-09-17 연서님 "마리오네트 부위도 함께 시술 변화가 있었으면")
#    실사진(온볼라썸 #1·#117·#118) 태그가 전부 팔자+마리오네트다. 네 칸(부위·마스크·Before·After)이 같이 넓어야 한다 —
#    마스크만 옛 폴리곤이면 셀카 모드에서 마리오네트 변화·직후 패치가 composite_outside_mask 로 Before 픽셀에 덮여 사라진다.
from bna.qa import landmarks as _LM
from bna.qa import structure as _ST
_nl = _tr_all["nasolabial"]
ok(_nl["mask_region"] == "nasolabial_marionette" and _nl["mask_region"] in _LM.REGIONS,
   "팔자 마스크는 팔자+마리오네트 합성 부위여야 한다")
_mar = set(_LM.REGIONS["marionette_l"]) | set(_LM.REGIONS["marionette_r"])
_LIPS = {61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 0, 267, 37, 39, 40, 185, 409, 270, 269, 13, 14}
ok(not (_mar & _LIPS) and 152 not in _mar,
   f"마리오네트 폴리곤에 입술·턱 끝 점이 들어가면 안 된다(입술 모양·턱이 편집 허용이 된다) — 실제 {sorted(_mar & _LIPS)}")
ok({57, 212, 192, 172}.issubset(set(_LM.REGIONS["marionette_l"])) and {287, 432, 416, 397}.issubset(set(_LM.REGIONS["marionette_r"])),
   "마리오네트 폴리곤은 입꼬리(57/287)에서 시작해 입꼬리 높이 바깥 볼(192/416, 직후 패치 자리)·턱선(172/397)까지 닿아야 한다")
import numpy as _np
_fake = _np.zeros((478, 2))
_rp = _ST.region_points(_fake, "nasolabial_marionette")
ok(_rp is not None and len(_rp) == len(_LM.REGIONS["nasolabial"]) + len(_LM.REGIONS["marionette_l"]) + len(_LM.REGIONS["marionette_r"]),
   "구조 검사가 세 폴리곤 합성 표기를 전부 푼다(안 풀면 region_in_frame 게이트를 조용히 안 탄다 — 0914 skin_pores 사고)")
ok("marionette" in _nl["after_change"] and "corner of the mouth" in _nl["after_change"],
   "팔자 After 문장이 마리오네트(입꼬리→턱 쪽)도 같이 얕아진다고 말해야 한다")
ok(all("marionette" in _nl["before_condition"][k] for k in ("moderate", "marked")),
   "팔자 Before(moderate·marked)가 마리오네트 주름을 말해야 한다 — Before 에 없는 주름은 After 에서 좋아질 수 없다")
ok("chin shape" in _nl["must_not_change"] and "corners of the mouth stay" in _nl["must_not_change"],
   "마스크가 턱선까지 닿으므로 턱 모양·입꼬리 높이는 글로 잠가야 한다")

# ㉑ 사실 카드 ↔ 금지문 충돌 (2026-09-11 실사고: 직후 컷이 테이프를 '그려라'와 '그리지 마라'를 동시에 받았다)
import yaml as _yaml
_av_cfg = _yaml.safe_load((_P(__file__).parent / "config" / "prompts" / "avoid.yaml").read_text(encoding="utf-8"))
_dress = [c for c in (_av_cfg.get("custom") or []) if "tape" in (c.get("en") or "")]
ok(_dress and "immediate" in (_dress[0].get("not_at") or []),
   "테이프·패치 금지 규칙엔 not_at: [immediate] 가 있어야 한다 — 직후 컷엔 카드가 테이프를 그리라고 한다")
_ban = _dress[0]["en"]
_pnq = build_prompts("nasolabial", "selfie", _v, 5, series=["immediate", "2w"],
                     avoid={"before": [], "after": [_ban]}, avoid_not_at={_ban: ["immediate"]})
ok(_ban not in _pnq["afters"][0]["after_prompt"] and _ban in _pnq["afters"][1]["after_prompt"],
   "그 금지문은 직후 컷에서만 빠지고 다른 컷엔 그대로 붙는다(규칙을 지우는 게 아니라 컷 단위로 뺀다)")
ok(_pnq["avoid_applied"]["after"] == [_ban],
   "avoid_applied 는 마지막 컷(=after_prompt 가 실린 컷)에 붙은 목록이어야 한다 — 메모 초안이 이걸 정본으로 읽는다")
_pni = build_prompts("nasolabial", "selfie", _v, 5, series=["immediate"],
                     avoid={"before": [], "after": [_ban]}, avoid_not_at={_ban: ["immediate"]})
ok(_pni["avoid_applied"].get("after") in (None, []),
   "직후 컷 하나만 만든 회차엔 그 금지문이 '붙였다'로 기록되면 안 된다(안 붙인 규칙을 붙였다고 적으면 또 승격시킨다)")
# ⚠ 이 가드는 **합성 카드**로 잰다 (2026-09-11 저녁) — 살아 있는 팔자 카드에서 패치 문장을 빼는 순간
#   충돌할 거리가 없어져 가드가 조용해졌다. 가드가 죽은 게 아니라 시료가 사라진 것이라, 시료를 만든다.
#   (살아 있는 설정에 기대는 회귀는 그 설정이 바뀌면 검사 자체가 증발한다.)
_sm.load = lambda n: {**_ol(n), "nasolabial": _t2} if n == "treatments.yaml" else _ol(n)
try:
    _sm.build_prompts("nasolabial", "selfie", _v, 5, series=["immediate"],
                      avoid={"before": [], "after": [_ban]})     # not_at 없이 = 예외를 잊은 상태
    _clash = None
except ValueError as _e:
    _clash = str(_e)
finally:
    _sm.load = _ol
ok(_clash and "not_at" in _clash,
   f"예외를 안 적은 채 카드와 금지문이 같은 컷에 붙으면 소리 내고 멈춰야 한다 — {_clash}")
_act = _les.active(_P(__file__).parent / "outputs", "nasolabial", "selfie")
ok((_act.get("not_at") or {}).get(_ban) == ["immediate"],
   f"lessons.active 가 not_at 표를 같이 돌려줘야 한다 — 안 넘기면 spec 이 예외를 모른 채 가드에 걸린다({_act.get('not_at')})")


# ㉑ 내보내기 zip 에 사용 범위 안내가 들어간다 (2026-09-10 파트장 "내부만" 확정, 정본 docs/usage-policy.md).
#    zip 은 결과물이 이 시스템을 떠나는 유일한 경로라, 파일만 받은 사람도 범위를 알아야 한다.
import json as _json, tempfile as _tf, zipfile as _zf, time as _time
_tmp = _P(_tf.mkdtemp())
_item = _tmp / "b1" / "0000"; _item.mkdir(parents=True)
(_item / "x_before.jpg").write_bytes(b"x"); (_item / "x_after.jpg").write_bytes(b"x")
(_item / "meta.json").write_text(_json.dumps({"treatment": "nasolabial", "mode": "selfie", "passed": True}), encoding="utf-8")
(_item / "review.json").write_text(_json.dumps({"pick": "pick", "tags": [], "updated_at": _time.time()}), encoding="utf-8")
_saved_out = _api.OUT
try:
    _api.OUT = _tmp
    _res, _code = _api.export_payload({})
    _names = _zf.ZipFile(_tmp / "exports" / (_res["name"] + ".zip")).namelist()
finally:
    _api.OUT = _saved_out
ok(_code == 200 and any("사용범위" in _n for _n in _names), f"내보내기 zip 에 사용 범위 안내가 들어가야 한다 — {_names}")

# ── 재시도 정책 (2026-09-10 성연서님 "①재시도 때 Before 재사용 ②'효과가 안 보임'은 같은 조건 재시도 금지") ──
from bna.batch import _retry_plan

_rd, _rb = _retry_plan(["vision:effect_visible"])
ok(_rd and _rb, "효과가 안 보임 → 조건을 다시 뽑고 Before 도 다시 그린다(같은 조건 재시도 금지)")

_rd, _rb = _retry_plan(["vision:drift"])
ok((not _rd) and (not _rb), "구도 흐트러짐 → 조건은 그대로, Before 재사용(After 만 다시)")

_rd, _rb = _retry_plan(["vision:hands_absent"])
ok((not _rd) and (not _rb), "손이 나옴 → 조건은 그대로, Before 재사용")

_rd, _rb = _retry_plan(["identity"])
ok((not _rd) and _rb, "동일인 어긋남 → 둘의 관계가 틀린 것이라 Before 부터 다시(조건은 그대로)")

# 시리즈면 사유에 시점이 붙는다(`structure@2w`) — `@` 앞만 보지 않으면 정책이 통째로 안 걸린다
_rd, _rb = _retry_plan(["vision:effect_visible@2w"])
ok(_rd and _rb, "시점이 붙은 사유(`...@2w`)도 같은 정책으로 걸려야 한다")

_rd, _rb = _retry_plan([])
ok((not _rd) and (not _rb), "사유가 없으면 아무것도 다시 하지 않는다")

# ── 항목별 합격선 (2026-09-10, 사람 검수 27건 근거) ──
_qa = load("qa_checklist.yaml")
ok((_qa.get("thresholds") or {}).get("effect_visible") == 6,
   f"effect_visible 합격선은 6 이어야 한다(사람 채택 6점 40% · 5점 이하 0%) — 실제 {_qa.get('thresholds')}")
ok(_qa["threshold"] == 7, "나머지 항목의 공통 합격선은 7 그대로여야 한다")

# 컷은 vision.score 가 실제로 쓰는가 — 설정만 있고 코드가 안 읽으면 조용히 아무 일도 안 일어난다
import bna.qa.vision as _v


class _FakeQA:
    def qa(self, b, a, items, mode):
        return {"effect_visible": {"score": 6, "note": ""}, "drift": {"score": 6, "note": ""}}


_r = _v.score(b"", b"", "selfie", _FakeQA())
ok(_r["failed_items"] == ["drift"],
   f"6점은 effect_visible 만 통과하고 drift 는 탈락해야 한다 — 실제 {_r['failed_items']}")
ok(_r["cuts"]["effect_visible"] == 6 and _r["cuts"]["drift"] == 7, "어느 컷으로 쟀는지 판정에 남아야 한다")


# ── 학습 되먹임 (2026-09-10 성연서님 "제외 이유 학습이 새 사진에 반영돼야 한다") ──
import tempfile as _tf, time as _t, json as _j
from pathlib import Path as _P
from bna import lessons as _L

def _ledger(rows):
    d = _P(_tf.mkdtemp())
    with (d / "lessons.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(_j.dumps({"at": _t.time(), "batch": "b", "item": r["item"], "pick": r["pick"],
                              "tags": r.get("tags", []), "note": "", "treatment": "nasolabial",
                              "mode": "selfie", "axes": r["axes"]}, ensure_ascii=False) + chr(10))
    return d

# 많이 쓴 조건값이 '제외 건수가 많다'는 이유만으로 눌리면 안 된다.
# 실사고: 한국인만 27세트 돌린 뒤 country=korea 가 0.25 로 눌려, 안 써 본 나라가 4배 유리해졌다.
_rows = ([{"item": f"k{i}", "pick": "reject", "axes": {"country": "korea"}} for i in range(8)]
         + [{"item": f"kp{i}", "pick": "pick", "axes": {"country": "korea"}} for i in range(8)]
         + [{"item": "j0", "pick": "reject", "axes": {"country": "japan"}},
            {"item": "j1", "pick": "pick", "axes": {"country": "japan"}}])
_a = _L.active(_ledger(_rows), "nasolabial", "selfie")
ok("country" not in _a["weights"],
   f"제외율이 같으면 많이 쓴 조건값을 누르지 않아야 한다 — 실제 {_a['weights'].get('country')}")

# 반대로 정말 유난히 잘 떨어지는 값은 눌러야 한다(기능이 죽지 않았는지).
_rows2 = ([{"item": f"b{i}", "pick": "reject", "axes": {"framing": "one_cheek"}} for i in range(9)]
          + [{"item": f"g{i}", "pick": "pick", "axes": {"framing": "full_face"}} for i in range(8)]
          + [{"item": "g9", "pick": "reject", "axes": {"framing": "full_face"}}])
_a2 = _L.active(_ledger(_rows2), "nasolabial", "selfie")
ok(_a2["weights"].get("framing", {}).get("one_cheek") is not None
   and "full_face" not in _a2["weights"].get("framing", {}),
   f"유난히 잘 떨어지는 값만 눌러야 한다 — 실제 {_a2['weights'].get('framing')}")

# 한 축의 값이 전부 걸리면 상대 확률이 그대로다 = 누른 게 아니다 → 축째로 빼야 한다
_rows3 = ([{"item": f"x{i}", "pick": "reject", "axes": {"angle": "front"}} for i in range(4)]
          + [{"item": f"y{i}", "pick": "reject", "axes": {"angle": "tilted"}} for i in range(4)]
          + [{"item": "z0", "pick": "pick", "axes": {"angle": "front"}}])
_a3 = _L.active(_ledger(_rows3), "nasolabial", "selfie")
ok("angle" not in _a3["weights"], f"축의 값이 전부 걸리면 그 축은 빼야 한다 — 실제 {_a3['weights'].get('angle')}")

# 재추첨은 고정 축(--fix)을 지켜야 한다. sample_variation 은 fixed 를 받지 않으므로 쓰면 안 된다.
_bsrc = (_P("src") / "bna" / "batch.py").read_text(encoding="utf-8")
_redraw = _bsrc.split("if redraw:", 1)[1].split("style_refs = refs.pick", 1)[0]
ok("plan_batch(" in _redraw and "sample_variation(" not in _redraw,
   "재추첨은 plan_batch 로 뽑아야 한다(sample_variation 은 고정 축을 무시한다)")

from bna.planner import plan_batch as _pb
_p1 = _pb("selfie", 1, 4242, {"country": "korea"}, None, treatment="nasolabial")[0]
ok(_p1["country"]["key"] == "korea", f"고정 축은 어떤 씨앗에서도 지켜져야 한다 — 실제 {_p1['country']['key']}")


# ── 2026-09-10 성연서님 승인 3건 ────────────────────────────────────────────
# ① 손: 셀카에서 '손가락으로 볼 가리키기'를 아예 안 뽑는다(손 등장의 뿌리였다)
_vv = load("variations.yaml")
ok("finger_on_cheek" not in (_vv["mode_rules"]["selfie"].get("context") or []),
   "셀카 맥락 후보에 finger_on_cheek 이 없어야 한다")
_ctx = {k for p in _pb("selfie", 120, seed=3, treatment="nasolabial") for k in [p["context"]["key"]]}
ok("finger_on_cheek" not in _ctx, f"120 표본에서 한 번도 안 뽑혀야 한다 — {sorted(_ctx)}")
# ⚠ 위 두 줄은 **Before 축만** 본다. 2026-09-11 실측: 사람이 '손가락'으로 뺀 9건 중 **4건은 Before 가 아니라
#   After 드리프트**가 finger_on_cheek 으로 옮겨간 것이었다(Before 는 hair_in_face). 09-10 보고가
#   "나머지는 손과 무관한 설정"이라고 잘못 가른 이유가 이 사각이다 — `variation` 만 보고 `after_variation` 을 안 봤다.
#   제거는 두 경로를 다 덮지만(아래 실측 0/N), 덮는다는 사실 자체에 가드가 없으면 다음에 또 못 본다.
import random as _rnd
from bna.spec import drift_after
_dr = set()
for _i in range(120):
    _pv = _pb("selfie", 1, seed=900 + _i, treatment="nasolabial")[0]
    for _tl in ("immediate", "2w"):
        _dr.add(drift_after(_pv, "selfie", _rnd.Random(_i * 7 + len(_tl)), timeline=_tl, treatment="nasolabial")["context"]["key"])
ok("finger_on_cheek" not in _dr, f"After 드리프트도 finger_on_cheek 으로 가면 안 된다 — {sorted(_dr)}")

# ── 유령 배치 폴더 (2026-09-11) ──────────────────────────────────────────────
# 생성자가 `outputs/<배치>` 를 먼저 만들던 탓에, 키가 없거나 인자가 틀려 그 자리에서 죽어도
# 빈 폴더가 남아 배치 목록에 진짜 회차처럼 보였다(실측 13개가 쌓여 있었다).
_bsrc = (_Path(__file__).resolve().parent / "src" / "bna" / "batch.py").read_text(encoding="utf-8")
_ctor = _bsrc.split("def __init__", 1)[1].split("# ---------- 단일 아이템", 1)[0]
ok("mkdir" not in _ctor, "Batch 생성자는 출력 폴더를 만들면 안 된다(실패해도 유령 회차가 남는다)")
ok("self.dir.mkdir" in _bsrc.split("async def run(", 1)[-1] or "self.dir.mkdir(parents=True, exist_ok=True)" in _bsrc,
   "대신 첫 쓰기 자리에서 만들어야 한다(안 만들면 회차가 통째로 저장 실패한다)")
# ⚠ 위 가드는 batch.py 만 본다. `batch.json` 은 **run() 보다 먼저** api.py 가 쓰므로 그쪽이
#   진짜 첫 쓰기다 — 2026-09-11 실측: 생성자 mkdir 을 빼자 대기열로 들어온 실모드 요청이
#   FileNotFoundError(2) 로 죽었다(대기열·직접 실행 두 진입점 모두). 쓰는 줄마다 짝을 강제한다.
_asrc = (_Path(__file__).resolve().parent / "src" / "bna" / "api.py").read_text(encoding="utf-8")
_writes = [s for s in _asrc.split('(b.dir / "batch.json").write_text')[:-1]]
ok(len(_writes) >= 2 and all("b.dir.mkdir(parents=True, exist_ok=True)" in s[-400:] for s in _writes),
   "api.py 가 batch.json 을 쓰기 직전에 폴더를 만들어야 한다(대기열·직접 실행 두 자리 모두)")
ok("with anatomically correct fingers" not in
   (_P("config") / "prompts" / "mode_extra.yaml").read_text(encoding="utf-8").split("# ⚠ selfie_with_hand")[0],
   "손을 요구하는 문구가 살아 있는 설정으로 남아 있으면 안 된다")

# ② 동일인 '사람 확인 구간'(0.45~0.60)은 자동 통과가 아니라 재시도다
from bna.qa import identity as _ID
# 숫자 자체는 17-7 이 잠근다(실측 근거와 같은 자리에). 여기서는 '사람 확인 구간이 존재하는가'만 본다.
ok(_ID.check.__doc__ and 0 < _ID.REVIEW_BAND < _ID.THRESHOLD,
   f"사람 확인 구간이 있어야 한다 — 실제 {_ID.REVIEW_BAND}~{_ID.THRESHOLD}")
_bsrc2 = (_P("src") / "bna" / "batch.py").read_text(encoding="utf-8")
ok('idn.get("gate") == "review"' in _bsrc2 and 'identity_review' in _bsrc2,
   "batch 가 review 구간을 재시도 사유로 올려야 한다")
_rd, _rb = _retry_plan(["identity_review"])
ok((not _rd) and _rb, "review 구간은 조건은 그대로 두고 Before 부터 다시 그려야 한다")
ok("identity_review" in _bsrc2.split("attempt < MAX_ATTEMPTS")[0].rsplit("gate", 1)[-1] or
   'attempt < MAX_ATTEMPTS' in _bsrc2,
   "마지막 회차에서는 review 를 통과시켜야 한다(애매한 걸 버리지 않는다)")

# ③ 구도 중복: 과거 회차와 프레이밍·각도·배경 조합이 겹치지 않게
from bna.planner import scene_signature as _ss, past_scene_signatures as _pss, SCENE_SIG_AXES as _SSA
ok(_SSA == ["framing", "angle", "background"], f"구도 서명 축은 셋이다 — {_SSA}")
_p0 = _pb("selfie", 6, seed=21, treatment="nasolabial")
_used = {_ss(p) for p in _p0}
_p1 = _pb("selfie", 6, seed=22, treatment="nasolabial", avoid_scene_sigs=_used)
ok(not ({_ss(p) for p in _p1} & _used), "다음 배치는 과거 구도 조합을 피해야 한다")
ok(len({_ss(p) for p in _p1}) == len(_p1), "한 배치 안에서도 구도 조합이 겹치지 않아야 한다")
# 과거 조합을 전부 막아도 배치가 조용히 줄면 안 된다(2차 폴백)
_all = {_ss(p) for p in _pb("selfie", 400, seed=1, treatment="nasolabial")}
ok(len(_pb("selfie", 6, seed=23, treatment="nasolabial", avoid_scene_sigs=_all)) == 6,
   "구도가 말라도 배치 개수는 채워야 한다(말없이 줄지 않는다)")
# 인물 서명에 장면을 섞지 않았는가 — 섞으면 회피가 오히려 약해진다
from bna.planner import signature as _sg
ok(len(_sg(_p0[0])) == 12, f"인물 서명은 인물 축 12개만이어야 한다(미모 축 포함, 2026-09-17) — {len(_sg(_p0[0]))}")

# 구도가 마르면 회피를 접어야 한다 — 안 접으면 남은 20n 번을 전부 거절로 헛돈다.
# 2026-09-10 실측: 이 가드가 없을 때 n=400 계획이 분 단위로 늘어 회귀가 2분 → 7분이 됐다.
import time as _tm2
_t0 = _tm2.time()
_big = _pb("selfie", 400, seed=31, treatment="nasolabial")
_el = _tm2.time() - _t0
ok(len(_big) == 400 and _el < 20,
   f"구도 후보보다 많은 n 도 채우고 오래 걸리면 안 된다 — {len(_big)}개 / {_el:.1f}s")
# 접더라도 '적당히 많이 다르게'는 지켜야 한다(접는 게 곧 포기는 아니다)
ok(len({_ss(p) for p in _big}) >= 100,
   f"말라서 접어도 구도 다양성은 남아야 한다 — 고유 구도 {len({_ss(p) for p in _big})}개")


# ── 전·후 짝 맞추기 (2026-09-10 실사고) ─────────────────────────────────────
# 재시도로 조건을 다시 뽑으면 파일 이름 앞부분이 바뀌는데 옛 회차 파일이 남는다.
# 그 상태에서 before 는 '첫 번째', after 는 '마지막'을 고르던 탓에 화면의 전·후가
# **서로 다른 사람**이 됐다(0910 배치 0000: before 일본인 / after 한국인).
import bna.api as _API
_pd = _P(_tf.mkdtemp()) / "b" / "0000"
_pd.mkdir(parents=True)
for _n in ["nasolabial_selfie_japanlate_20sf_0000_before.jpg", "nasolabial_selfie_japanlate_20sf_0000_after.jpg",
           "nasolabial_selfie_korealate_20sf_0000_before.jpg", "nasolabial_selfie_korealate_20sf_0000_after.jpg"]:
    _pd.joinpath(_n).write_bytes(b"x")
_meta = {"treatment": "nasolabial", "mode": "selfie", "item_id": "0000",
         "variation": {"country": {"key": "japan"}, "age": {"key": "late_20s"}, "gender": {"key": "female"}}}
_fp = _API.pair_files(_pd, _meta)
_bf = next((f for f in _fp if f.endswith("_before.jpg")), None)
_af = _API.last_after(_fp)
ok(_bf and _af and _bf.replace("_before.jpg", "") == _af.replace("_after.jpg", ""),
   f"전·후는 반드시 같은 회차(같은 이름)여야 한다 — before={_bf} after={_af}")
ok("japan" in (_bf or ""), f"지금 meta 가 말하는 조건의 파일을 골라야 한다 — {_bf}")
# 옛 배치(이름 규칙이 다른 것)는 종전대로 전부 본다 — 화면이 비는 것보다 낫다
_pd2 = _P(_tf.mkdtemp()) / "b" / "0000"
_pd2.mkdir(parents=True)
for _n in ["old_before.jpg", "old_after.jpg"]:
    _pd2.joinpath(_n).write_bytes(b"x")
ok(len(_API.pair_files(_pd2, _meta)) == 2, "이름이 안 맞는 옛 배치는 fail-open 으로 전부 보여야 한다")


# ⑯ 메모 → 규칙 초안 (2026-09-10 빌디 조율). 네트워크 0 — 가짜 프로바이더로 판정 로직만 잰다.
from bna import notedraft as _ND, lessons as _LS

class _FakeProv:
    def __init__(self, data, fail=False):
        self.data, self.fail, self.seen = data, fail, None
    def chat_json(self, prompt, images=(), *, purpose="chat", model=None):
        if self.fail:
            raise RuntimeError("boom")
        self.seen = prompt
        return {"data": self.data, "model": "gpt-5.1",
                "usage": {"prompt_tokens": 1634, "completion_tokens": 213}}

_APPLIED = "head angle and camera height must match the stated framing; do not drift to a different pose"
_META = {"treatment": "nasolabial", "mode": "selfie",
         "avoid_applied": {"before": [_APPLIED], "after": [_APPLIED, "no text or watermarks"]},
         "variation": {"framing": {"key": "cheek_only"}, "angle": {"key": "three_quarter"}}}

# 16-1 그때 이미 붙어 있던 금지문이 입력에 실려야 한다. 안 실으면 있는 규칙을 또 규칙으로 낸다.
_p = _FakeProv({"why": "프레이밍이 시술 부위를 잘랐다", "en": "Keep the treated area fully inside the frame.",
                "kind": "rule", "covered_by": ""})
_r = _ND.draft_rule("시술 부위 중앙이 잘려서 시술되지 않음", ["AI 티"], _META,
                    {"before": "b-prompt", "after": "a-prompt"}, None, provider=_p)
ok(_APPLIED in (_p.seen or ""), "already_applied(그때 붙어 있던 금지문)가 모델 입력에 있어야 한다")
ok("a-prompt" in (_p.seen or "") and "cheek_only" in (_p.seen or ""),
   "실제 쓴 프롬프트와 프레이밍 축 값이 모델 입력에 있어야 한다")
ok(_r["kind"] == "rule" and _r["promotable"] is True, f"새 규칙이면 승격 가능해야 한다 — {_r}")

# 16-2 이미 붙어 있던 문장이면 모델이 rule 이라 해도 승격은 아무 일도 안 한다(코드가 못박는다).
_r2 = _ND.draft_rule("각도가 계속 틀어짐", ["각도"], _META, {}, None,
                     provider=_FakeProv({"why": "각도 드리프트", "en": _APPLIED, "kind": "rule", "covered_by": ""}))
ok(_r2["covered_by"] == _APPLIED and _r2["promotable"] is False,
   f"이미 붙어 있던 문장은 covered_by 로 잡히고 승격 불가여야 한다 — {_r2}")

# 16-3 모르는 kind 는 rule 로 밀지 않는다(승격 쪽으로 fail-open 하면 안 되는 축).
_r3 = _ND.draft_rule("메모", [], _META, {}, None,
                     provider=_FakeProv({"why": "x", "en": "Keep the pose steady.", "kind": "몰라", "covered_by": ""}))
ok(_r3["kind"] is None and _r3["promotable"] is False, f"판정 불가는 None 이어야 한다 — {_r3}")

# 16-4 en 은 프롬프트에 그대로 들어간다 — 비ASCII 제거 + 상한
_r4 = _ND.draft_rule("메모", [], _META, {}, None,
                     provider=_FakeProv({"why": "x", "en": "한글 Keep it real " + "z" * 400, "kind": "rule"}))
ok(_r4["en"].isascii() and len(_r4["en"]) <= _ND.MAX_EN, f"en 은 ASCII·{_ND.MAX_EN}자 이내여야 한다 — {len(_r4['en'])}")

# 16-5 호출 실패는 던지지 않고 키워드 표로 폴백한다(검수 화면이 멈추면 안 된다)
_r5 = _ND.draft_rule("손가락이 이상함", ["손가락"], _META, {}, None, provider=_FakeProv({}, fail=True))
ok(_r5["source"] == "keywords" and _r5["promotable"] is False and _r5["en"],
   f"실패는 폴백이어야 하고 출처가 남아야 한다 — {_r5}")

# 16-6 캐시 키는 화면 병합 키와 같은 함수여야 한다(따로 만들면 그룹 1 : 초안 2 가 된다)
_src = open("src/bna/notedraft.py", encoding="utf-8").read()
ok("lessons._norm(" in _src, "캐시 키는 lessons._norm 을 그대로 써야 한다")

# 16-7 단가 정본은 config/pricing.yaml 하나 (실측: 검수 1회 $0.0042)
ok(abs(_ND.usd_of("gpt-5.1", {"prompt_tokens": 1634, "completion_tokens": 213}) - 0.00417) < 0.0002,
   "usd_of 가 실측 단가($0.0042)를 재현해야 한다")
_ur = open("tools/usage_report.py", encoding="utf-8").read()
ok("image_in\": 8.00" not in _ur and "token_rates" in _ur,
   "usage_report 는 단가를 리터럴로 갖지 말고 pricing.yaml 의 token_rates 를 읽어야 한다")
ok((load("pricing.yaml") or {}).get("token_rates"), "pricing.yaml 에 token_rates 가 있어야 한다")
ok(load("providers.yaml").get("note_draft"), "초안 벤더는 providers.yaml 의 note_draft 가 정본이다")

# 16-8 원장 칸 가르기 — 검수와 초안이 같은 모델이라 purpose 가 없으면 실단가가 흐려진다
_oi = open("src/bna/providers/openai_img.py", encoding="utf-8").read()
ok('"purpose": "qa"' in _oi and 'purpose="note_draft"' in _src,
   "qa·note_draft 호출은 usage 원장에 purpose 를 남겨야 한다")


# 17 프레이밍 × 동일인 게이트 표 (2026-09-11) — ③ 게이트가 '어디서' 안 재는지 보이게
def _metas(rows):
    """meta.json 만 놓인 out_dir 을 만든다 (검수 원장 lessons.jsonl 은 일부러 안 만든다)."""
    d = _P(_tf.mkdtemp())
    for i, r in enumerate(rows):
        it = d / "b1" / f"{i:04d}"
        it.mkdir(parents=True)
        (it / "meta.json").write_text(_j.dumps({
            "batch_id": "b1", "item_id": f"{i:04d}", "treatment": "nasolabial", "mode": "selfie",
            "demo": r.get("demo", False),
            "variation": {"framing": {"key": r["framing"], "text": ""}},
            "identity": {"gate": r["gate"]},
            "structure": {"face_detected": r.get("mp", False)},
        }, ensure_ascii=False), encoding="utf-8")
    return d

# 17-1 모수는 검수 원장이 아니라 생성 원장 전량이다 — 사람이 아직 안 본 장도 세야
#      "게이트가 몇 %에서 꺼져 있나"가 나온다. 위 _ledger 와 달리 lessons.jsonl 이 아예 없다.
_g = _L.gate_by_framing(_metas([{"framing": "one_cheek", "gate": "n/a"}] * 3
                               + [{"framing": "full_face", "gate": "ok"}] * 2))
ok(_g["total"] == 5 and _g["overall"]["na_rate"] == 0.6,
   f"검수 안 한 장도 세야 한다 — 실제 total={_g['total']} na_rate={_g['overall']['na_rate']}")

# 17-2 demo(시뮬레이션) 배치는 빠져야 한다. 자리표시 이미지는 before/after 가 사실상 같은 그림이라
#      게이트가 늘 ok 로 나온다 — 섞으면 못 잼 비율이 낮아 보인다
#      (2026-09-11 실측: 68장 중 22장이 시뮬, 그중 13장 ok → 32.6% 가 29.4% 로 읽혔다).
_g2 = _L.gate_by_framing(_metas([{"framing": "one_cheek", "gate": "n/a"}] * 3
                                + [{"framing": "full_face", "gate": "ok", "demo": True}] * 7))
ok(_g2["total"] == 3 and _g2["excluded_demo"] == 7 and _g2["overall"]["na_rate"] == 1.0,
   f"demo 배치는 모수에서 빠져야 한다 — 실제 total={_g2['total']} na_rate={_g2['overall']['na_rate']}")

# 17-3 못 잼 중 'MediaPipe 는 잡은 것'을 갈라 센다 — 검출기 하나만 실패한 건은
#      랜드마크 5점으로 다리를 놓아 구제할 수 있고, 둘 다 못 잡은 건은 그 길이 없다.
_g3 = _L.gate_by_framing(_metas([{"framing": "lower_face", "gate": "n/a", "mp": True},
                                 {"framing": "lower_face", "gate": "n/a", "mp": False}]))
ok(_g3["overall"]["na_mp_ok"] == 1 and _g3["framings"][0]["na_mp_ok"] == 1,
   f"못 잼 중 랜드마크는 잡은 건을 갈라 세야 한다 — 실제 {_g3['overall']['na_mp_ok']}")

# 17-4 못 잼이 심한 프레이밍이 맨 위로 온다 (화면이 그대로 그리므로 정렬이 곧 결론이다)
_g4 = _L.gate_by_framing(_metas([{"framing": "full_face", "gate": "ok"}] * 5
                                + [{"framing": "one_cheek", "gate": "n/a"}] * 2))
ok(_g4["framings"][0]["framing"] == "one_cheek",
   f"못 잼 비율이 높은 프레이밍이 맨 위여야 한다 — 실제 {_g4['framings'][0]['framing']}")

# 17-5 summarize 가 이 표를 실어 보내야 한다 (화면·빌디가 읽는 자리)
ok("gate_by_framing" in _L.summarize(_metas([{"framing": "full_face", "gate": "ok"}])),
   "lessons.summarize 응답에 gate_by_framing 이 있어야 한다")

# 17-6 깨진 meta 한 장이 표 전체를 죽이지 않는다 (fail-open)
_d6 = _metas([{"framing": "full_face", "gate": "ok"}])
(_d6 / "b1" / "9999").mkdir(parents=True)
(_d6 / "b1" / "9999" / "meta.json").write_text("{깨짐", encoding="utf-8")
ok(_L.gate_by_framing(_d6)["total"] == 1, "깨진 meta 한 장이 표를 죽이면 안 된다")


# 17-7 동일인 문턱은 실측으로 정해진 값이다 (2026-09-11 재캘리브레이션)
#      음성 666쌍(서로 다른 item 의 before 교차)의 최대가 0.441 이라 0.45 가 오탐 0 의 최저 문턱이다.
#      0.60 으로 되돌리면 같은 쌍을 26%(8/31) 죽이면서 막아 주는 건 0 이다 — 되돌리려면
#      tools/_probe_sep_0911.py 를 다시 돌려 근거부터 새로 내라.
from bna.qa import identity as _ID
ok(_ID.THRESHOLD == 0.45 and _ID.REVIEW_BAND == 0.35,
   f"동일인 문턱은 실측값(0.45/0.35)이어야 한다 — 실제 {_ID.THRESHOLD}/{_ID.REVIEW_BAND}")
ok(_ID.REVIEW_BAND < _ID.THRESHOLD,
   "사람 확인 구간은 통과 문턱보다 낮아야 한다(뒤집히면 review 가 영영 안 생긴다)")


# ⑱ 프레이밍 비중 조정 (2026-09-11 성연서님 B안) — 눈 안 보이는 컷은 쓰되 못 잼 10% 미만
from collections import Counter as _C18
from bna.planner import plan_batch as _pb18
# 프레이밍별 실측 못 잼률(2026-09-11, demo 제외 46장). 표본이 작으니 값이 아니라 **순서**가 요점이다.
# 새로 재려면 tools/framing_na_forecast.py — 이 상수는 그때 같이 갱신하고 근거(장수)를 남겨라.
_NA18 = {"one_cheek": 1.00, "neck_only": 0.75, "lower_face": 0.50,
         "nose_to_neck": 0.125, "forehead_cut": 0.0, "full_face": 0.0,
         "head_to_bust": 0.0}     # 눈이 프레임 안 — 실측 전 가정(2026-09-17). 얼굴이 작아 다른 이유로 못 잴 수 있다 → 첫 소량 회차 뒤 갱신
# 상한표의 정본은 bna.spec.NA_LIMIT 하나다 (2026-09-14) — 이 회귀와 tools/framing_na_forecast.py 가
#   같이 읽는다. 종전엔 회귀에 10%, 도구에 10% 가 따로 박혀 있어 한쪽만 고치면 조용히 갈렸다.
from bna.spec import NA_LIMIT as _LIM18, NA_LIMIT_DEFAULT as _LIMD18
_EXEMPT18 = set()                # 예외도 상한표가 말한다(목주름 35% · 피부 3종 20%)


def _na18(t, n=1200, seed=18):
    d = _C18(p["framing"]["key"] if isinstance(p["framing"], dict) else p["framing"]
             for p in _pb18("selfie", n, seed=seed, treatment=t))
    tot = sum(d.values()) or 1
    return sum(c * _NA18[f] for f, c in d.items() if f in _NA18) / tot, {f: c / tot for f, c in d.items()}


# ⚠ 씨앗을 하나만 쓰면 추첨 요동으로 9%대와 10%대를 오간다(0911 실측: 같은 설정이 9.3% / 10.5%).
#    여러 씨앗의 **최악값**으로 본다 — 목표를 아슬아슬하게 맞추지 말라는 뜻이기도 하다.
_over18 = []
for _t18 in load("treatments.yaml"):
    if _t18 in _EXEMPT18:
        continue
    _r18 = max(_na18(_t18, 1200, sd)[0] for sd in (18, 19, 20))
    _lim18 = _LIM18.get(_t18, _LIMD18)
    if _r18 >= _lim18:
        _over18.append(f"{_t18} {_r18*100:.1f}% (상한 {_lim18*100:.0f}%)")
ok(not _over18, f"예상 못 잼이 시술별 상한(bna.spec.NA_LIMIT) 미만이어야 한다 — 초과: {_over18}")

# ⑱-1b 피부 3종은 확대 컷이 실제로 늘었는가 — 상한만 재면 '안 늘려도 통과'라 방향을 못 지킨다
_close18 = {t: sum(_na18(t, 1200, 18)[1].get(f, 0) for f in ("one_cheek", "lower_face"))
            for t in ("skinbooster_embo", "skin_pores", "skin_redness")}
_close18_txt = {k: f"{v*100:.0f}%" for k, v in _close18.items()}
ok(all(0.20 <= v <= 0.40 for v in _close18.values()),
   f"피부 3종 확대 컷(한쪽 볼·아래 얼굴) 비중은 20~40% 여야 한다 — 실제 {_close18_txt}")

# ⑱-2 '빼기'가 아니라 '낮추기'다. 0 으로 죽이면 모델이 좋아졌는지 확인할 길이 사라진다.
_fw18 = load("variations.yaml")["weights"]["framing"]
ok(all(float(x) > 0 for x in _fw18.values()) and set(_fw18) >= set(_NA18),
   f"프레이밍 가중은 전부 0 보다 커야 한다(빼려면 framing_allow 에서 빼라) — {_fw18}")
_r18n, _d18n = _na18("filler_neck")
ok(_d18n.get("neck_only", 0) > 0.15,
   f"목주름에서 목만 컷은 대표 구도라 살아 있어야 한다 — 실제 {_d18n.get('neck_only', 0)*100:.1f}%")

# ⑱-3 목주름은 구조적으로 10% 에 못 간다 — 목만을 아예 0 으로 죽여도 nose_to_neck 자체가 12.5% 다.
#      이 검사가 깨지면 '목주름도 됐다'가 아니라 실측률이 바뀐 것이니 면제를 다시 판단해라.
ok(_NA18["nose_to_neck"] >= 0.10,
   f"목주름 면제의 근거는 nose_to_neck 실측률이다 — 이 값이 내려갔으면 면제를 재검토하라({_NA18['nose_to_neck']})")

# ⑱-4 추첨 경로가 둘이다(plan_batch · sample_variation). 시술별 프레이밍 가중을 한쪽만 반영하면
#      배치와 단건이 조용히 다른 분포를 낸다 — 목만 컷 비중이 두 경로에서 같은지 본다.
_sv18 = _C18(sample_variation("selfie", seed=_s, treatment="filler_neck")["framing"]["key"]
             for _s in range(600))
_svr18 = _sv18["neck_only"] / sum(_sv18.values())
ok(abs(_svr18 - _d18n.get("neck_only", 0)) < 0.12,
   f"두 추첨 경로의 프레이밍 분포가 비슷해야 한다 — plan_batch {_d18n.get('neck_only',0):.2f} vs sample_variation {_svr18:.2f}")

# ⑱-5 검수 화면(빌디)이 '기계 못 잼' 배지에 쓰는 계약 필드다. 이름·값을 바꾸면 배지가 조용히 빈다.
_orig18 = _ID.similarity
_ID.similarity = lambda a, b: None          # '못 잼' = 검출 실패. 실제 이미지 없이 판정 로직만 본다
try:
    _nares18 = _ID.check(None, None)
finally:
    _ID.similarity = _orig18
ok(_nares18["gate"] == "n/a",
   f"얼굴을 못 잡으면 gate 는 정확히 'n/a' 여야 한다(검수 배지 계약) — 실제 {_nares18['gate']}")
ok(_nares18["measured"] is False and _nares18["passed"] is None and _nares18["hard_fail"] is False,
   f"못 잼은 measured=False·passed=None·hard_fail=False 여야 한다(탈락으로 접으면 통계가 거짓말한다) — {_nares18}")


# ⑱-6 버전 표에 '못 잼 비율' 칸 — 프레이밍 비중을 바꾼 효과가 보이는 유일한 자리다.
#      통과율·제외율에는 안 나타난다(못 잼은 떨어진 게 아니라 안 잰 것이라 어느 분자에도 없다).
_d18v = _P(_tf.mkdtemp())
for _i18, (_g18, _ms18) in enumerate([("n/a", False), ("n/a", False), ("ok", True), ("fail", True)]):
    _it18 = _d18v / "b" / f"{_i18:04d}"
    _it18.mkdir(parents=True)
    (_it18 / "meta.json").write_text(_j.dumps({
        "prompt_version": "vX", "treatment": "nasolabial", "passed": _ms18,
        "identity": {"gate": _g18, "measured": _ms18}}), encoding="utf-8")
_row18 = [r for r in _L.by_version(_d18v) if r["version"] == "vX"][0]
ok(_row18["id_na"] == 2 and _row18["id_na_rate"] == 0.5,
   f"못 잼 비율의 분모는 그 버전의 전체 장수다 — 실제 {_row18['id_na']}/{_row18['n']} = {_row18['id_na_rate']}")


# ⑱-7 버전 이름표는 '설정 해시'로도 찾아야 한다 (2026-09-11, 하루에 두 번 유령이 됐다)
#      prompt_version = git짧은sha-설정해시 라 **문서 한 줄만 커밋해도** 새 버전이 된다.
#      배치 전에 붙여 둔 이름표가 아무 배치도 안 가리키게 되는 게 그 결과다.
_d18n2 = _P(_tf.mkdtemp())
for _i, _v in enumerate(["aaaaaaa-2fb1005f", "bbbbbbb-2fb1005f"]):
    _it = _d18n2 / f"b{_i}" / "0000"
    _it.mkdir(parents=True)
    (_it / "meta.json").write_text(_j.dumps({"prompt_version": _v, "treatment": "nasolabial",
                                             "passed": True, "identity": {"gate": "ok", "measured": True}}),
                                   encoding="utf-8")
_L.names_set(_d18n2, "aaaaaaa-2fb1005f", "프레이밍 비중 조정")
_rows18 = {r["version"]: r["note"] for r in _L.by_version(_d18n2)}
ok(_rows18.get("bbbbbbb-2fb1005f") == "프레이밍 비중 조정",
   f"커밋만 바뀐 같은 설정은 이름표를 물려받아야 한다 — 실제 {_rows18}")
# 다른 설정까지 물려받으면 안 된다 — 그러면 이름이 아니라 낙서가 된다
_it2 = _d18n2 / "b9" / "0000"; _it2.mkdir(parents=True)
(_it2 / "meta.json").write_text(_j.dumps({"prompt_version": "ccccccc-99999999", "treatment": "nasolabial",
                                          "passed": True, "identity": {"gate": "ok", "measured": True}}),
                                encoding="utf-8")
ok({r["version"]: r["note"] for r in _L.by_version(_d18n2)}.get("ccccccc-99999999") == "",
   "설정 해시가 다르면 이름표를 물려받지 않아야 한다")

# ⑲-시리즈 구도 잠금 (2026-09-11 실측, 배치 20260911-124645-5cce)
#   시점 컷마다 framing 이 다시 뽑혀 1주 컷에서 팔자 주름이 화면 밖으로 밀려났고, 심사는 그 컷에
#   '턱선이 정리됐다'며 8점을 줬다 — 시술 부위가 아닌 곳을 보고 준 점수다.
#   시리즈에서는 구도와 얼굴에 얹히는 소품(안경·모자·마스크)을 컷 전체에서 고정한다.
_SER = ["immediate", "1w", "2w"]
_drift_axes = {"framing": 0, "extras": 0, "background": 0, "lighting": 0}
for _s in range(60):
    _v = sample_variation("selfie", _s)
    _p = build_prompts("nasolabial", "selfie", _v, _s, series=_SER)
    for _a in _p["afters"]:
        for _ax in _drift_axes:
            if _a["after_variation"][_ax]["key"] != _v[_ax]["key"]:
                _drift_axes[_ax] += 1
# ⚠ 2026-09-18 개정: 구도 '완전 잠금'은 `series_relax` 로 **이웃 한 칸**이 됐다 (연서님 검수 ③
#   "전·직후·2주 세 장의 표정·입모양·구도·카메라 각도가 똑같다"). 지킬 것은 '안 바뀐다'가 아니라
#   **멀리 안 뛴다**다 — 0911 사고는 '얼굴 전체 → 하관만' 점프였고 이웃 한 칸은 그 점프를 못 만든다.
_V18 = load("variations.yaml")
_far = []
for _s in range(60):
    _v = sample_variation("selfie", _s)
    for _a in build_prompts("nasolabial", "selfie", _v, _s, series=_SER)["afters"]:
        _k0, _k1 = _v["framing"]["key"], _a["after_variation"]["framing"]["key"]
        if _k1 != _k0 and _k1 not in (_V18.get("framing_neighbors", {}).get(_k0) or []):
            _far.append((_k0, _k1))
ok(not _far, f"시리즈 구도는 이웃 한 칸까지만 옮겨야 한다(먼 점프 금지) — 실제 {_far[:3]}")
ok(_drift_axes["framing"] > 0, "시리즈 컷 구도가 한 건도 안 움직이면 세 장이 같은 사진처럼 보인다(series_relax 가 죽었나)")
ok(_drift_axes["extras"] == 0, f"시리즈 컷에서 안경·모자가 붙었다 떨어지면 안 된다 — 실제 {_drift_axes['extras']}건")
# ⑲-2 완화가 '가짜 효과'를 만들지 않는가 (2026-09-18). 입을 벌리면 그것만으로 팔자가 펴진다 →
#   표정은 바뀌어도 **입 상태(다문/벌린)는 Before 와 같아야** 한다. 각도도 이웃 한 칸까지다.
_tb18 = _V18.get("expression_traits", {})
_mouth_bad, _ang_bad, _same_all = [], [], 0
for _s in range(60):
    _v = sample_variation("selfie", _s)
    _as = build_prompts("nasolabial", "selfie", _v, _s, series=_SER)["afters"]
    for _a in _as:
        _av = _a["after_variation"]
        if _tb18.get(_av["expression"]["key"], {}).get("mouth") != _tb18.get(_v["expression"]["key"], {}).get("mouth"):
            _mouth_bad.append((_v["expression"]["key"], _av["expression"]["key"]))
        _ka, _kb = _v["angle"]["key"], _av["angle"]["key"]
        if _ka != _kb and _kb not in (_V18.get("angle_neighbors", {}).get(_ka) or []):
            _ang_bad.append((_ka, _kb))
    if all(_a["after_variation"][_x]["key"] == _v[_x]["key"]
           for _a in _as for _x in ("expression", "angle", "framing")):
        _same_all += 1
ok(not _mouth_bad, f"시리즈 표정 완화가 입 상태를 바꾸면 안 된다(벌린 입은 주름을 펴서 가짜 효과) — 실제 {_mouth_bad[:3]}")
ok(not _ang_bad, f"시리즈 각도는 이웃 한 칸까지만 — 실제 {_ang_bad[:3]}")
ok(_same_all <= 6, f"세 축이 전부 Before 와 같은 세트가 60개 중 {_same_all}개 — 완화가 사실상 안 걸렸다")
# ⑲-3 완화는 `series_relax` 를 적은 시술에만 (전역 누수 금지) — 리프팅은 종전대로 완전 잠금이다.
_leak = [(_x, _a["after_variation"][_x]["key"], _v0[_x]["key"])
         for _s in range(40)
         for _v0 in [sample_variation("selfie", _s, treatment="lifting")]
         for _a in build_prompts("lifting", "selfie", _v0, _s, series=["2w", "4w"])["afters"]
         for _x in ("expression", "angle", "framing")
         if _a["after_variation"][_x]["key"] != _v0[_x]["key"]]
ok(not _leak, f"series_relax 를 안 적은 시술(리프팅)은 표정·각도·구도가 그대로여야 한다 — 실제 {_leak[:3]}")
# ⚠ 잠근 건 둘뿐이다. 배경·조명까지 굳으면 '같은 사진을 복사한 티'가 나서 시리즈의 목적이 뒤집힌다.
ok(_drift_axes["background"] > 0 and _drift_axes["lighting"] > 0,
   f"배경·조명은 시리즈에서도 계속 달라져야 한다 — 실제 배경 {_drift_axes['background']}건·조명 {_drift_axes['lighting']}건")
# 시리즈가 아닌 한 장짜리는 종전대로 구도가 흔들릴 수 있다 (잠금이 전역으로 새지 않았는가)
_solo = sum(1 for _s in range(60)
            if build_prompts("nasolabial", "selfie", sample_variation("selfie", _s), _s)["after_variation"]["framing"]["key"]
            != sample_variation("selfie", _s)["framing"]["key"])
ok(_solo > 0, f"한 장짜리 After 의 구도 변주까지 잠기면 안 된다 — 실제 {_solo}건")

# ㉑ 표정이 한 가지로 쏠리지 않는가 (2026-09-11 성연서님 "표정이 다 똑같아 AI 티가 난다")
#    실측 74세트에서 무표정 2종이 96% 였다. 얼굴이 달라도 표정이 같으면 같은 사람처럼 보인다.
import collections as _co
def _expr_dist(t, n=400):
    c = _co.Counter()
    for _s in range(n):
        c[sample_variation("selfie", _s, treatment=t)["expression"]["key"]] += 1
    return c
_ed = _expr_dist("nasolabial")
ok(len(_ed) >= 5, f"입 주변 시술은 표정이 최소 5종은 나와야 한다 — 실제 {len(_ed)}종 {_ed.most_common()}")
ok(max(_ed.values()) / sum(_ed.values()) <= 0.40,
   f"한 표정이 40% 넘게 쏠리면 안 된다 — 실제 {max(_ed.values()) / sum(_ed.values()):.0%}")
ok("slight_smile" not in _ed, "팔자에 미소가 들어가면 안 된다 (웃으면 시술 없이도 주름이 달라진다)")
# 눈 시술은 반대다 — 눈·눈썹·시선을 건드리는 칸이 하나라도 새면 그게 시술 효과로 둔갑한다
_EYE_MOVING = {"gaze_off", "gaze_screen", "brow_up", "eyes_narrow", "blink_soft"}
_ee = _expr_dist("filler_eyelid")
ok(not (_EYE_MOVING & set(_ee)),
   f"눈 부위 시술에 눈·시선 변주가 들어가면 안 된다 — 실제 {sorted(_EYE_MOVING & set(_ee))}")
# ⚠ 칸을 만들어도 모드 화이트리스트에 없으면 **한 번도 안 뽑힌다** (2026-09-11 실사고: 5칸을 넣고
#   300 표본을 돌렸는데 분포가 종전 2종 그대로였다 — 오류도 경고도 없었다).
_vy2 = load("variations.yaml")
_wl = set(_vy2["mode_rules"]["selfie"]["expression"]) | set(_vy2["mode_rules"]["clinical"]["expression"])
ok(set(_vy2["expression"]) <= _wl,
   f"어느 모드에서도 안 뽑히는 유령 표정이 있으면 안 된다 — 실제 {sorted(set(_vy2['expression']) - _wl)}")

# ㉔ 표정 *이름*이 아니라 **입 상태**로 세라 (2026-09-11 오후 성연서님 "입모양이 너무 똑같은 모양이야 로봇처럼")
#    오전엔 이름을 3→8종으로 늘리고 "흩어졌다"고 봤는데, 늘린 5칸이 전부 눈·눈썹만 바꿔서
#    실측 입 상태는 여전히 2종·74%가 같은 모양이었다. 축 이름이 통과해도 사람 눈은 입을 먼저 본다.
#    ⚠ 'no smile' 이 들어간 문구를 미소로 세지 마라 — 첫 계측이 그렇게 세서 13.8%를 미소로 오분류했다.
def _mouth_of(text):
    t = text.lower()
    if "parted" in t or "barely apart" in t or "mouth is open" in t:
        return "open"
    if "smile" in t and "no smile" not in t and "not a smile" not in t and "not smiling" not in t:
        return "smile"
    if "jaw hangs loose" in t or "not symmetric" in t:
        return "closed_loose"
    return "closed"
_exprs_cfg = _vy2["expression"]
_md = _co.Counter()
for _k, _n in _ed.items():
    _md[_mouth_of(_exprs_cfg[_k])] += _n
_mtop = max(_md.values()) / sum(_md.values())
ok(len(_md) >= 3, f"팔자 입 상태가 최소 3종은 나와야 한다 — 실제 {len(_md)}종 {_md.most_common()}")
ok(_mtop <= 0.60, f"한 입 모양이 60% 넘게 쏠리면 로봇처럼 보인다 — 실제 {_mtop:.0%} {_md.most_common()}")
ok("smile" not in _md, "팔자 입 변주에 웃음이 섞이면 안 된다(웃으면 주름이 저절로 깊어진다)")
# 같은 축이라도 시술마다 넓힐 수 있는 방향이 다르다 — 입이 판정 부위인 시술엔 이 칸을 주지 않는다
_MOUTH_MOVING = {"jaw_loose", "lips_speak", "lip_asym"}
for _t in ("philtrum", "filler_eyelid"):
    ok(not (_MOUTH_MOVING & set(_expr_dist(_t))),
       f"{_t}: 입·눈이 판정 부위인 시술에 입 변주가 들어가면 안 된다 — 실제 {sorted(_MOUTH_MOVING & set(_expr_dist(_t)))}")

# ㉒ 팔자 직후 패치 자리·재질 (2026-09-17, 실사진 탭 강남언니 #118 정면 D+0·#117 3/4 D+0 으로 확정)
#    09-11 오전 '콧볼 옆' → 오후 '아래쪽'(3/4 사진 1장) → 저녁 '통째로 뺌'을 거쳐, 09-17 성연서님이
#    정면 실사진을 보고 되살렸다. 기준은 그 사진: 패치는 **입꼬리 높이 바깥 볼**(입꼬리에서 3~4cm), 한쪽에
#    둘, 지름 1cm **투명** 원형이고, 홍조는 볼 전체로 넓지 **않다**(피부톤 그대로 + 패치 밑 붉은 점 하나씩).
_im = _immediate_after("nasolabial", 7)
# ⚠ 'beside the nostril' 단독으로 재지 마라 — after_change 가 주름 *길이*를 말할 때 같은 말을 쓴다
#   (콧볼 옆에서 입꼬리까지). 금지 대상은 패치를 거기 앉히는 문장 하나다.
ok("patch sitting high" not in _im and "patches sitting high" not in _im and "far from the nose" in _im,
   "직후 패치를 콧볼 옆(주름 위쪽)에 붙이면 안 된다 — 주름 아래 끝")
# 09-17 저녁 성연서님 "볼이 아니라 팔자 끝나는 아래 지점에 양쪽 두 개씩" — cm·볼 서술이 돌아오면 모델이 볼 한복판·귀 쪽에 흩는다
ok("lower end of the nasolabial fold" in _im and "on both sides" in _im
   and "centimetres" not in _im and "low on the cheek" not in _im,
   "패치 자리는 '팔자 아래 끝 · 양쪽' 이어야 한다 — cm·볼 서술 금지(09-17 저녁 검수)")
# 같은 날 #118 실사진 표시(파란 체크 = 선의 아래 끝, 한쪽 셋) — 마리오네트 끝 패치가 빠지면 표시와 다르다
ok("three per side" in _im and "right on the jawline" in _im and "marionette line meets the jaw" in _im,
   "패치는 한쪽 셋: 팔자 끝 둘 + 마리오네트 끝 하나 — 마리오네트는 턱선 위(09-17 #118 표시 → 09-18 연서님 '턱 라인으로')")
# 09-18 C안: 위치 게이트는 직후 컷에만, 스위치는 spec 이 싣는다(배치는 시점 이름을 안 본다)
from bna.spec import build_prompts as _bp_pg
_pg_afters = [a for a in _bp_pg("nasolabial", "selfie", sample_variation("selfie", 7, treatment="nasolabial"), 7,
                                 series=["immediate", "2w"])["afters"]]
ok([a["patch_gate"] for a in _pg_afters] == [3, 0], f"패치 위치 게이트는 직후 컷에만 3회(09-18 오후 연서님 상한) — 실제 {[a['patch_gate'] for a in _pg_afters]}")
# 09-18 오후 연서님: 여분 패치는 '개수' 문제 — 문장이 한쪽 정확히 셋 + 여섯이 전부라고 말해야 한다(금지 자리 나열 없이)
ok("exactly three per side" in _im and "only dressings" in _im and "forehead" not in _im,
   "직후 패치 개수 문장: '정확히 한쪽 셋 · 이 여섯이 전부' 긍정형(금지 자리 나열 금지 — 09-10 교훈)")
# 게이트 사유 두 갈래 + 허용 1.5 + '가장 가까운 컷' 고르기 — 비전 호출 없이 가짜 채점기로
from bna.qa import patchgate as _pgm, landmarks as _lmm
ok(_pgm.TOL_IRIS == 1.0, f"위치 게이트 허용 = 홍채 지름 1.0개(09-18 밤 1.5→1.0 복귀) — 실제 {_pgm.TOL_IRIS}")
# 09-18 저녁: 짚기는 모델(가짜 detect), 원 안/밖·짝짓기·여분은 코드 — 가짜 짚기는 원본 픽셀 좌표를 조각 픽셀로 바꿔 돌려준다
_orig_detect, _orig_spots, _orig_axes = _lmm.detect, _lmm.patch_spots, _pgm._axes
_lmm.detect = lambda img: "pts"
_pgm._axes = lambda pts: (__import__("numpy").array([1.0, 0.0]), __import__("numpy").array([0.0, -1.0]))  # 가로=+x, 위=-y
_pg_spots = [{"side": "L", "name": n, "x": 100 + 40 * i, "y": 100, "r": 5} for i, n in enumerate(["a", "b", "c"])]
_lmm.patch_spots = lambda pts, strict=True, size=None: _pg_spots if strict else _pg_spots + _pg_opt
_pg_opt = []                                    # '있어도 되는 자리'(정면 마리오네트 등) — 아래 시험에서만 채운다
from PIL import Image as _PImg
_blank = _PImg.new("RGB", (400, 300))
_pg_box = _pgm._crop_box(_blank, _pg_spots)
_pg_k = 1024 / max(_pg_box[2] - _pg_box[0], _pg_box[3] - _pg_box[1])
def _pg_det(*xy):
    return lambda crop: [((x - _pg_box[0]) * _pg_k, (y - _pg_box[1]) * _pg_k) for x, y in xy]
_g_ok = _pgm.check(_blank, detect=_pg_det((101, 100), (140, 104), (178, 99)))
_g_cnt = _pgm.check(_blank, detect=_pg_det((101, 100), (140, 104), (178, 99), (100, 150), (40, 60)))
_g_pos = _pgm.check(_blank, detect=_pg_det((101, 100), (178, 99)))
_g_both = _pgm.check(_blank, detect=_pg_det((140, 100), (180, 100), (100, 125), (100, 140), (60, 40)))
_g_shift = _pgm.check(_blank, detect=_pg_det((100, 118), (140, 100), (180, 100)))
_g_twin = _pgm.check(_blank, detect=_pg_det((98, 100), (104, 101), (140, 100), (180, 100)))   # 한 원에 겹친 둘
_g_fail = _pgm.check(_blank, detect=lambda crop: (_ for _ in ()).throw(RuntimeError("x")))
_g_none = _pgm.check(_blank, detect=_pg_det())
# 09-18 밤: 정면 마리오네트 = '있어도 되는 자리' — 없어도 통과, 있으면 그 원 안이어야(원 밖이면 여분)
_pg_opt = [{"side": "L", "name": "mario_end", "x": 140, "y": 122, "r": 5, "need": False}]
_g_optnone = _pgm.check(_blank, detect=_pg_det((101, 100), (140, 104), (178, 99)))
_g_optin = _pgm.check(_blank, detect=_pg_det((101, 100), (140, 104), (178, 99), (141, 123)))
_g_optoff = _pgm.check(_blank, detect=_pg_det((101, 100), (140, 104), (178, 99), (140, 145)))
_g_optsteal = _pgm.check(_blank, detect=_pg_det((101, 100), (178, 99), (141, 121)))   # 옆 패치 못 짚음 + 턱선 패치
_pg_opt = []
_lmm.detect, _lmm.patch_spots, _pgm._axes = _orig_detect, _orig_spots, _orig_axes
ok(_g_none["passed"] is None and _g_none["unmeasured"] == 3,
   f"하나도 못 짚음 = 못 잼(패치가 희미해서 — 09-18 밤 연서님 '없음이 아니라 못 잼') — {_g_none}")
ok(_g_optnone["passed"] is True and _g_optin["passed"] is True,
   f"정면 마리오네트는 없어도·원 안에 있어도 통과 — {_g_optnone.get('reasons')}/{_g_optin.get('reasons')}")
ok(_g_optoff["passed"] is False and _g_optoff["reasons"] == ["count"],
   f"마리오네트가 턱선 원 밖(볼 중간)이면 탈락 — {_g_optoff.get('reasons')}")
ok(_g_optsteal["passed"] is True and _g_optsteal["unmeasured"] == 1,
   f"턱선 원 안 패치를 빈 필수 자리 짝으로 끌어오지 않는다(못 잼 1) — {_g_optsteal.get('reasons')}, 못 잼 {_g_optsteal.get('unmeasured')}")
# 자 — 눈 점이 화면 밖이면 입 너비 × MOUTH_IRIS (09-18 밤 연서님 ④, c4 한국 30대 코 아래 크롭)
import numpy as _np_pg
_pp = _np_pg.zeros((478, 2)); _pp[61] = (100, 200); _pp[291] = (200, 200)
_pp[468:478] = (150, -30); _pp[474], _pp[476], _pp[469], _pp[471] = (140, -30), (170, -30), (130, -30), (160, -30)
ok(_lmm.iris_diam(_pp, size=(300, 300)) == (100 * _lmm.MOUTH_IRIS, "mouth"), "눈이 화면 밖 → 자 = 입 너비 × 0.265")
_pp[468:478, 1] = 50
ok(_lmm.iris_diam(_pp, size=(300, 300)) == (30.0, "iris"), "눈이 화면 안 → 자 = 홍채(큰 쪽)")
ok(_lmm.MARIO_OUT == 0.5 and not hasattr(_lmm, "MARIO_INSET"),
   "마리오네트 목표 = MediaPipe 턱선에서 반지름 0.5 바깥(09-18 밤 연서님 — INSET 두 번 올라감 교정)")
ok(_g_twin["passed"] is False and _g_twin["reasons"] == ["count"] and _g_twin["total"] == 4,
   f"겹친 패치 둘도 각자 센다(09-18 저녁 '5개쯤 보이는데 3개') — {_g_twin.get('reasons')}, total={_g_twin.get('total')}")
ok(_g_fail["passed"] is None, "짚기 실패 = 못 잼(None) — 재생성 사유 아님(fail-open)")
_sh = _g_shift["offsets"][0]
ok(_sh["found"] and not _sh["in_ring"] and _sh["dir"] == "아래" and abs(_sh["dist"] - 1.8) < 0.01,
   f"어긋남 = 얼굴 기준 방향·홍채 지름 거리(09-18 저녁 연서님 \"같은 방향으로 계속 벗어나는지\") — {_sh}")
ok(_g_ok["passed"] is True and _g_ok["reasons"] == [], f"게이트 통과 — {_g_ok}")
ok(_g_cnt["passed"] is False and _g_cnt["reasons"] == ["count"], f"원 밖 여분만 = count — {_g_cnt.get('reasons')}")
ok(_g_pos["passed"] is True and _g_pos["unmeasured"] == 1,
   f"원 빔(짝 없음) = 못 잼 — 재생성 사유 아님(09-18 밤 연서님, 희미한 패치) — {_g_pos.get('reasons')}, 못 잼 {_g_pos.get('unmeasured')}")
ok(_g_both["reasons"] == ["position", "count"], f"원 빔 + 총 4개 = 두 사유 — {_g_both.get('reasons')}")
ok(_g_shift["passed"] is False and _g_shift["reasons"] == ["position"],
   f"셋을 그렸는데 하나가 원 밖으로 밀림 = 자리 오차만(개수 아님, 09-18 오후 실측 7/8) — {_g_shift.get('reasons')}")
ok(max([_g_both, _g_cnt, _g_shift], key=_pgm.closeness) is _g_cnt
   and _pgm.closeness({"inside": None}) < _pgm.closeness(_g_both),
   "다 떨어지면 남길 컷 = 원 안 많을수록 → 원 밖 적을수록, 못 잰 컷은 맨 뒤")
# 09-21: 부분 크롭 컷 — 원본에서 얼굴을 못 찾으면 여백을 붙여 한 번 더 찾고, 그렇게 잰 회차는 '기록 전용'(passed=None).
#   실측 근거는 _face_pts 머리말(c5 배치 Before: 원본 못 찾음 → 여백 50% 에서 478점).
import inspect as _insp_pg
_pad_seen = []
def _pad_detect(img):
    _pad_seen.append(img.size)
    if img.size == (400, 300):                  # 원본 = 못 찾음, 여백 붙인 것만 찾는다
        return None
    return _np_pg.zeros((478, 2)) + [210, 160]
_lmm.detect = _pad_detect
_pts_pad, _was_pad = _pgm._face_pts(_PImg.new("RGB", (400, 300)))
ok(_was_pad and _pad_seen[-1] == (800, 600) and abs(_pts_pad[0][0] - 10) < 1e-6 and abs(_pts_pad[0][1] - 10) < 1e-6,
   f"못 찾으면 여백 50% 붙여 재검출 + 좌표는 원본 기준으로 복원 — {_pad_seen}, {_pts_pad[0] if _pts_pad is not None else None}")
_lmm.patch_spots, _pgm._axes = (lambda pts, strict=True, size=None: _pg_spots), (lambda pts: (
    _np_pg.array([1.0, 0.0]), _np_pg.array([0.0, -1.0])))
_g_pad = _pgm.check(_blank, detect=_pg_det((101, 100), (140, 104), (178, 99)))
_lmm.detect, _lmm.patch_spots, _pgm._axes = _orig_detect, _orig_spots, _orig_axes
ok(_g_pad["passed"] is None and _g_pad["reasons"] == [] and "여백" in _g_pad["note"] and _g_pad["inside"] == 3,
   f"여백으로 찾은 컷은 기록 전용(다시 그리지 않는다 — 지어낸 눈 좌표로 유료 재생성 금지) — {_g_pad.get('passed')}, {_g_pad.get('note')}")
ok("여백 붙여 잼" in _insp_pg.getsource(_pgm.check) and "기록 전용" in _insp_pg.getsource(_pgm._face_pts),
   "여백 재검출은 게이트가 아니라 기록 — 코드에 그 이유가 적혀 있어야 한다")
import inspect as _insp_pg
from bna import batch as _bt_pg
_bsrc = _insp_pg.getsource(_bt_pg)
ok("patch_gate_final" in _bsrc and "patchgate.closeness" in _bsrc,
   "배치: 끝까지 떨어진 직후 컷은 버리지 않고 가장 가까운 컷 + patch_gate_final 표시")
_wsrc = (__import__("pathlib").Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")
ok("posGateChip(it)" in _wsrc and "위치 게이트 <b>미통과</b>" in _wsrc, "검수 화면에 '위치 게이트 미통과' 표시")
# 같은 날 "얼굴 크기가 다른데 패치 크기가 똑같다 = 합성 티" — 실측 얼굴 2.25배 vs 패치 1.45배. 절대 크기(cm) 대신 홍채에 묶는다
ok("iris" in _im and "one centimetre" not in _im,
   "패치 크기는 얼굴 안의 기준(홍채)에 묶어야 한다 — '1cm' 는 사진에 자가 없어 고정 픽셀로 찍힌다")
ok("clear hydrocolloid" in _im and "thin transparent film" in _im and "faint reflection of light along one side" in _im
   and "zoomed in" in _im and "glossy circular rim" not in _im,
   "패치는 투명이고, 왜 안 보이는지(얇은 필름·피부가 비침·한쪽 가장자리 희미한 반사·확대해야 보임)까지 적어야 한다 — "
   "'거의 안 보임'만 적으면 티나게 그린다(09-11 실측). 09-18 밤 연서님: '링만 반질'은 흰 테두리가 또렷해 내렸다")
ok("flushed pink" not in _im and "scattered" not in _im and "same ordinary, even tone" in _im,
   "볼 전체 홍조·흩뿌린 주사자국은 실사진에 없다 — 피부톤 그대로 + 패치 밑 점 하나씩")
_imk = " ".join(str(_tr_all["nasolabial"]["facts"]["immediate_marks"]).split())
ok(" no " not in f" {_imk} " and "not " not in _imk.replace("nowhere", ""),
   "직후 흔적 카드는 긍정형이어야 한다 — 금지 품목을 적으면 모델이 그린다(0910 마취크림 5/5)")

# ㉒-b 끊긴 배치 자동 종결 (2026-09-14 성연서님 "종결 처리 할 수 없나") — 진행 기록이 30분 넘게 멈췄고 이 서버가 돌리는 게 아니면 닫는다
import bna.progress as _prog_mod
import time, json
import tempfile as _tf2
_sd = _P(_tf2.mkdtemp())
_pj = {"planned": 3, "started_at": time.time() - 5 * 86400, "finished_at": None, "error": None,
       "items": {"0000": {"stage": "passed", "attempt": 1, "passed": True, "fail_reasons": [], "updated_at": time.time() - 5 * 86400, "elapsed": 1},
                 "0001": {"stage": "after", "attempt": 1, "passed": None, "fail_reasons": [], "updated_at": time.time() - 5 * 86400, "elapsed": 1},
                 "0002": {"stage": "queued", "attempt": 0, "passed": None, "fail_reasons": [], "updated_at": None, "elapsed": 0}}}
(_sd / "progress.json").write_text(json.dumps(_pj), encoding="utf-8")
ok(_prog_mod.close_stale(_sd), "닷새 전에 멈춘 배치는 닫힌다")
_rd2 = _prog_mod.read(_sd)
ok(_rd2["summary"]["running"] is False and _rd2["summary"]["stopped"] == "interrupted" and _rd2["items"]["0001"]["stage"] == "skipped" and _rd2["items"]["0000"]["stage"] == "passed",
   "닫히면 진행 중 아님 · stopped=interrupted · 남은 사진은 skipped · 끝난 사진은 그대로")
_pj["finished_at"] = None; _pj["items"]["0001"]["updated_at"] = time.time() - 60
(_sd / "progress.json").write_text(json.dumps(_pj), encoding="utf-8")
ok(not _prog_mod.close_stale(_sd), "1분 전에 움직인 배치는 닫지 않는다(진짜 돌고 있을 수 있다)")

# ㉓ 참조 사진(A1)이 시술·시점을 거르는가 (2026-09-11 빌디 "refs.pick 이 거르는지 확인")
#    종전엔 **안 걸렀다** — 모드와 조명·화질·배경만 봤다. 그래서 '팔자 직후' 실사진을 색인에 넣으면
#    리프팅 컷에도, 시술 전(Before) 컷에도 들어간다. 뒤쪽이 특히 나쁘다: 아직 시술도 안 한 얼굴에
#    패치와 홍조가 그려지는데 오류는 하나도 안 난다.
import bna.refs as _refs_mod
import tempfile as _tf
_rd = _P(_tf.mkdtemp()); (_rd / "selfie").mkdir()
for _f in ("na_imm.jpg", "generic.jpg", "lift_2w.jpg", "pores_before.jpg"):
    (_rd / "selfie" / _f).write_bytes(b"\xff\xd8\xff")
_refs_mod.REF_DIR = _rd
_orig_rload = _refs_mod.load
_IDX = {"refs": [
    {"file": "selfie/na_imm.jpg", "mode": "selfie", "treatment": "nasolabial", "timeline": "immediate"},
    {"file": "selfie/generic.jpg", "mode": "selfie"},
    {"file": "selfie/lift_2w.jpg", "mode": "selfie", "treatment": "lifting", "timeline": "2w"},
    {"file": "selfie/pores_before.jpg", "mode": "selfie", "treatment": "skin_pores", "timeline": "before"},
]}
def _use(idx):
    _refs_mod.load = lambda n: idx if n == "samples_index.yaml" else _orig_rload(n)
_use(_IDX)
def _names(**kw):
    return [r["file"] for r in _refs_mod.candidates(**kw)]
ok(_names(mode="selfie", treatment="nasolabial", when="immediate")
   == ["selfie/na_imm.jpg", "selfie/generic.jpg"], "팔자 직후 컷엔 그 시술·그 시점 참조 + 범용이 붙는다")
ok(_names(mode="selfie", treatment="nasolabial", when=None) == ["selfie/generic.jpg"],
   "시점 태그가 붙은 참조는 시술 전(Before) 컷에 절대 안 들어간다")
ok(_names(mode="selfie", treatment="lifting", when="immediate") == ["selfie/generic.jpg"],
   "다른 시술의 참조가 섞이면 안 된다")
ok(_names(mode="selfie", treatment="nasolabial", when="2w") == ["selfie/generic.jpg"],
   "같은 시술이라도 다른 시점의 참조가 섞이면 안 된다")
ok(_names(mode="clinical", treatment="nasolabial", when="immediate") == [],
   "모드가 다르면 안 붙는다(종전 축 유지)")
# 2026-09-14: `timeline: before` = 시술 전 컷 전용(결함이 찍힌 사진). After 에 붙으면 결과가 도로 나빠 보인다.
ok(_names(mode="selfie", treatment="skin_pores", when=None) == ["selfie/generic.jpg", "selfie/pores_before.jpg"],
   "시술 전 전용 참조는 Before 컷에 붙는다")
ok(_names(mode="selfie", treatment="skin_pores", when="4w") == ["selfie/generic.jpg"],
   "시술 전 전용 참조는 After 컷엔 절대 안 붙는다")
def _idx_raises(entry, exc=Exception):
    _use({"refs": [entry]})
    try:
        _refs_mod.check_index(); return False
    except exc:
        return True
    finally:
        _use(_IDX)
ok(_idx_raises({"file": "selfie/generic.jpg", "mode": "selfie", "treatment": "nasolabail"}),
   "시술 이름 오타는 조용히 범용이 되지 말고 소리 내고 죽는다")
ok(_idx_raises({"file": "selfie/generic.jpg", "mode": "selfie", "timeline": "3w"}),
   "없는 시점 이름도 막는다")
ok(_idx_raises({"file": "selfie/nope.jpg", "mode": "selfie"}, FileNotFoundError),
   "색인에만 있고 파일이 없는 참조는 유령이다 — 죽는다")
_refs_mod.load = _orig_rload
_refs_mod.REF_DIR = _P(__file__).parent / "samples" / "reference"
ok(isinstance(_refs_mod.check_index(), list), "실제 색인(config/samples_index.yaml)이 검증을 통과한다")
# 살아 있는 색인이 **실제로** 그 컷에만 붙는가 (색인에 올려 두고 안 붙으면 넣은 사람은 붙은 줄 안다)
_live = lambda **kw: [r["file"] for r in _refs_mod.candidates(**kw)]
if _live(mode="selfie", treatment="nasolabial", when="immediate"):
    ok(not _live(mode="selfie", treatment="nasolabial", when=None),
       "실제 색인의 직후 참조가 시술 전(Before) 컷에 붙으면 안 된다")
    ok(not _live(mode="selfie", treatment="lifting", when="immediate"),
       "실제 색인의 팔자 참조가 다른 시술 컷에 붙으면 안 된다")
    # 빌디 요청 문장 그대로: "팔자 직후 After 컷에만 이 참조가 잡힌다" — 붙는 칸 1개 / 안 붙는 칸 전부
    _cells = {(tr, w): _live(mode="selfie", treatment=tr, when=w)
              for tr in ("nasolabial", "lifting", "filler_nose")
              for w in (None, "immediate", "1w", "2w", "4w")}
    _hit = sorted(k for k, v in _cells.items() if v)
    ok(_hit == [("nasolabial", "immediate")],
       f"팔자 직후 After 컷에만 이 참조가 잡힌다 — 실제로 잡힌 칸 {_hit}")
# 축을 만들어도 부르는 쪽이 안 넘기면 한 번도 안 걸린다(유령 칸) — 소비자를 직접 본다
_bsrc = open("src/bna/batch.py", encoding="utf-8").read()
ok("treatment=self.treatment" in _bsrc and "when=when" in _bsrc,
   "batch 가 참조를 고를 때 시술·시점을 실제로 넘겨야 한다")
ok(_bsrc.count("self._refs(") >= 3 and "refs.pick(self.mode, variation)" not in _bsrc,
   "Before·재추첨·After 세 자리 모두 새 경로를 써야 한다(한 곳이라도 옛 호출이면 그 컷만 안 걸린다)")

# ㉕ 프롬프트 패치 번호 v{n} + 카테고리 (2026-09-11 성연서님 "v{n} 넘버 붙이자, 카테고리도")
#    번호는 **설정 해시**로 센다 — 종전엔 prompt_version 전체(git sha 포함)로 세서 *문서 한 줄만
#    커밋해도* 번호가 올라갔다(실측 v10·v11·v12 가 전부 같은 프롬프트 d677e740). 번호로 부르자는
#    취지가 "같은 프롬프트를 세 이름으로 부르는" 결과가 되던 자리다.
# ⚠ 시료 해시는 **8자**로 쓴다 — 이름표 물려받기가 뒷자리 6자 미만을 'sim'·'demo' 같은 가짜로 보고 건너뛴다.
_vr = [{"version": v, "real": True, "first": i} for i, v in enumerate(
    ["aaa-11111111", "bbb-22222222", "ccc-22222222", "ddd-33333333"])]
_va = _L.aliases(_vr, "eee-33333333")
ok([_va[r["version"]] for r in _vr] == ["v1", "v2", "v2", "v3"],
   f"코드만 바뀐 같은 설정은 같은 번호여야 한다 — 실제 {[_va[r['version']] for r in _vr]}")
ok(_va["eee-33333333"] == "v3", "아직 사진이 없어도 설정이 같으면 그 번호를 쓴다(새 번호를 만들지 않는다)")
ok(_L.aliases(_vr, "fff-99999999")["fff-99999999"] == "v4", "설정이 새로우면 다음 번호를 미리 준다")
ok(set(_L.CAT_BY_CONFIG.values()) <= set(_L.VERSION_CATS),
   f"자동 카테고리가 허용 목록 밖을 내면 안 된다 — 실제 {sorted(set(_L.CAT_BY_CONFIG.values()) - set(_L.VERSION_CATS))}")
for _f in ("treatments.yaml", "variations.yaml", "effects.yaml", "samples_index.yaml", "qa_checklist.yaml"):
    ok(_f in _L.CAT_BY_CONFIG, f"프롬프트를 바꾸는 설정 {_f} 에 카테고리가 있어야 한다(없으면 칸이 조용히 빈다)")
_d25 = _P(_tf.mkdtemp())
_L.names_set(_d25, "aaa-11111111", "손으로 붙인 이름", cat="변주")
ok(_L.names_read(_d25)["aaa-11111111"]["cat"] == "변주", "이름표에 카테고리가 같이 저장돼야 한다")
ok(_L._note_by_config(_L.names_read(_d25), "zzz-11111111").get("cat") == "변주",
   "설정 해시가 같으면 **카테고리까지** 물려받아야 한다(한쪽만 따라오면 반쪽 표기가 된다)")
try:
    _L.names_set(_d25, "bbb-22222222", "x", cat="없는칸"); _catbad = False
except ValueError:
    _catbad = True
ok(_catbad, "모르는 카테고리는 조용히 저장하지 말고 소리 내고 죽는다")

# ㉖ 피부 3종 0914 검수 반영 — 조명 호·프레이밍 이웃·강도 가중·Before 전용 참조
#    (연서님 검수 "6장 전부 AI 티 + 전·후 구분 불가", 빌디 전달 5건)
from bna.planner import plan_batch as _pb26
from bna.spec import treatment_rules as _tre26, allowed_values as _av26f
_SKIN26 = ["skinbooster_embo", "skin_pores", "skin_redness"]
_SOFT26, _HARSH26 = {"window", "window_soft"}, {"ceiling_harsh", "flash", "fluorescent"}
_NB26 = load("variations.yaml")["framing_neighbors"]
_bad26, _arc26, _sev26, _n26 = [], 0, 0, 0
for _t26 in _SKIN26:
    for _i26, _p26 in enumerate(_pb26("selfie", 150, seed=26, treatment=_t26)):
        _sp26 = build_prompts(_t26, "selfie", _p26, 26000 + _i26); _av26 = _sp26["after_variation"]
        _b26, _a26 = _p26["lighting"]["key"], _av26["lighting"]["key"]
        _n26 += 1
        # ① 호는 **한 방향**이다. 반대로 가면(후가 더 센 빛) 효과가 거꾸로 보인다.
        if _b26 in _SOFT26:
            _bad26.append(f"{_t26} Before 가 부드러운 빛({_b26})")
        if _b26 in _HARSH26 and _a26 in _SOFT26:
            _arc26 += 1
        # ② 프레이밍은 같거나 **한 칸 옆**까지만 (자유 재추첨이면 전후 비교가 깨진다)
        _fb26, _fa26 = _p26["framing"]["key"], _av26["framing"]["key"]
        if _fa26 != _fb26 and _fa26 not in (_NB26.get(_fb26) or []):
            _bad26.append(f"{_t26} 프레이밍 점프 {_fb26}->{_fa26}")
        if _sp26["variation"]["before_severity"]["key"] == "marked":
            _sev26 += 1
ok(not _bad26, f"피부 3종: Before 는 센 빛 · After 프레이밍은 이웃까지 — 위반 {_bad26[:4]} ({len(_bad26)}건)")
# ㉘ 2026-09-14 오후 연서님 검수 (모공 2세트 실물): "전·후가 같은 사람의 2주 뒤로 안 읽힌다".
#    원인 세 가지를 각각 시료로 박는다 — 셋 다 오류 없이 통과하던 값들이라 눈으로만 보면 또 샌다.
_EYES28 = {"head_to_bust": True, "full_face": True, "forehead_cut": True,
           "lower_face": False, "one_cheek": False, "nose_to_neck": False, "neck_only": False}
_hair28, _beard28, _eye28, _n28 = [], [], [], 0
for _t28 in _SKIN26:
    for _i28, _p28 in enumerate(_pb26("selfie", 150, seed=28, treatment=_t28)):
        _sp28 = build_prompts(_t28, "selfie", _p28, 28000 + _i28); _a28 = _sp28["after_variation"]
        _n28 += 1
        # ① 머리 모양은 전·후 동일 (2주 뒤 삭발이 실제로 뽑혔다)
        if _a28["hair_style"]["key"] != _p28["hair_style"]["key"]:
            _hair28.append(f'{_t28} {_p28["hair_style"]["key"]}->{_a28["hair_style"]["key"]}')
        # ② 수염은 전·후 어디에도 없다 (볼·코를 덮으면 시술 부위가 화면에서 사라진다)
        for _w28, _v28 in (("전", _p28), ("후", _a28)):
            if _v28["extras"]["key"] in ("beard_light", "beard_full"):
                _beard28.append(f'{_t28} {_w28} {_v28["extras"]["key"]}')
        # ③ 프레이밍이 옮겨 가도 **눈 유무는 그대로** (눈이 사라지면 사람도 게이트도 대조 못 한다)
        _fb28, _fa28 = _p28["framing"]["key"], _a28["framing"]["key"]
        if _EYES28.get(_fb28) != _EYES28.get(_fa28):
            _eye28.append(f"{_t28} {_fb28}->{_fa28}")
ok(not _hair28, f"피부 3종: After 머리 모양은 안 바뀐다 — 위반 {_hair28[:3]} ({len(_hair28)}건)")
ok(not _beard28, f"피부 3종: 수염은 전·후 어디에도 안 나온다(시술 부위를 덮는다) — 위반 {_beard28[:3]} ({len(_beard28)}건)")
ok(not _eye28, f"프레이밍이 옮겨 가도 눈 유무는 그대로 — 위반 {_eye28[:3]} ({len(_eye28)}건, 표본 {_n28})")
# 이웃표 자체도 본다 — 표를 넓히는 순간 위 실측이 통과해도 다음 값에서 샌다(같은 구멍의 거울상).
_nbbad28 = [f"{_k}->{_v}" for _k, _vs in _NB26.items() for _v in _vs if _EYES28.get(_k) != _EYES28.get(_v)]
ok(not _nbbad28, f"프레이밍 이웃표에 눈 유무가 갈리는 짝이 없다 — {_nbbad28}")

# ㉙ 2026-09-14 오후 (연서님 "고치고 가자") — 남은 두 구멍.
#    ①시술 부위가 '안 보이는 것'과 '확대해서 넘친 것'을 가르는 자 ②후 컷 조명 호가 배경에 지는 것.
import numpy as _np29
from bna.qa.structure import region_frame as _rf29, region_points as _rp29
from bna.qa import landmarks as _lm29

def _pts29(n=478, x=500.0, y=500.0):
    a = _np29.zeros((n, 2)); a[:, 0] = x; a[:, 1] = y; return a

_W29, _H29 = 1024, 1280
_p29 = _pts29()
for _i29, _k29 in enumerate(_lm29.REGIONS["cheeks"]):          # 볼 폴리곤을 화면 가운데 작게 편다
    _p29[_k29] = (400 + _i29 * 2, 600 + _i29)
ok(_rf29(_p29, "cheeks", (_W29, _H29))["region_in_frame"], "부위가 화면 안에 다 있으면 통과")

_p29b = _p29.copy()
for _k29 in _lm29.REGIONS["cheeks"][:20]:                      # 절반 가까이 화면 왼쪽 밖으로 (작게 보임 = 밀려났다)
    _p29b[_k29] = (-50, 600)
_r29b = _rf29(_p29b, "cheeks", (_W29, _H29))
ok(not _r29b["region_in_frame"],
   f"부위가 화면 밖으로 밀려 조금만 보이면 실패 — 안비율 {_r29b['region_in_ratio']} 덮음 {_r29b['region_coverage']}")

_p29c = _p29.copy()                                            # 같은 만큼 밖인데 남은 부위가 화면을 크게 덮는다(확대 컷)
for _i29, _k29 in enumerate(_lm29.REGIONS["cheeks"]):
    _p29c[_k29] = (-200 + _i29 * 60, 100 + _i29 * 25)
_r29c = _rf29(_p29c, "cheeks", (_W29, _H29))
ok(_r29c["region_in_frame"],
   f"확대해서 넘친 컷은 통과한다(3회 재시도로 태운 자리) — 안비율 {_r29c['region_in_ratio']} 덮음 {_r29c['region_coverage']}")

ok(_rp29(_p29, "cheeks_nose") is not None and len(_rp29(_p29, "cheeks_nose")) > len(_rp29(_p29, "cheeks")),
   "조합 부위(cheeks+nose)도 인덱스를 푼다 — 안 풀면 그 시술만 검사를 통째로 건너뛴다")

# ② 후 컷은 배경을 옮겨서라도 호의 빛을 낸다 (욕실은 창이 없어 종전엔 22%가 센 빛으로 남았다)
_SOFT29, _HARSH29 = {"window", "window_soft"}, {"ceiling_harsh", "flash", "fluorescent"}
_bad29, _n29 = [], 0
for _t29 in _SKIN26:
    for _i29b, _pv29 in enumerate(_pb26("selfie", 100, seed=29, treatment=_t29)):
        _sp29 = build_prompts(_t29, "selfie", _pv29, 29000 + _i29b); _a29 = _sp29["after_variation"]
        if _sp29["variation"]["timeline"]["key"] == "immediate":
            continue                                        # 직후 컷은 같은 날 병원 빛이라 호가 안 걸린다(㉝)
        _n29 += 1
        if _a29["lighting"]["key"] in _HARSH29:
            _bad29.append(f'{_t29} {_a29["background"]["key"]}/{_a29["lighting"]["key"]}')
ok(len(_bad29) / _n29 <= 0.05,
   f"후 컷이 센 빛으로 남는 세트는 5% 이하 — 실제 {len(_bad29)*100/_n29:.0f}% ({_bad29[:3]})")

# ㉚ 2026-09-14 오후 2차 (연서님 "표정·입 벌림·눈 뜬 정도가 어떻게 딱 떨어지게 똑같지?" /
#    "비포가 피부가 더 좋아 보이지 않았으면 해, 특히 광").
#    ① 참조로 넘긴 Before 가 포즈까지 복제되는 걸 막는 문장은 **모든 시술**에 붙어야 한다 —
#       09-10 에 만든 그 문장이 expression_policy=lock 갈래에만 있었다(자유인 시술이 무방비인 거울상).
_RESHOT30 = []
for _t30 in ("skin_pores", "skinbooster_embo", "skin_redness", "nasolabial", "lifting_thread"):
    try:
        _p30 = _pb26("selfie", 1, seed=30, treatment=_t30)[0]
    except Exception:
        continue
    _sp30 = build_prompts(_t30, "selfie", _p30, 30001)
    _ap30 = _sp30["after_prompt"]
    if "not the reference photo edited" not in _ap30 or "Do not copy the pose" not in _ap30:
        _RESHOT30.append(_t30)
ok(not _RESHOT30, f"모든 셀카 시술의 After 에 '참조를 베끼지 마라' 문장이 붙는다 — 빠진 시술 {_RESHOT30}")

# ② Before 는 광이 돌면 안 된다 (전 사진이 후 사진보다 좋아 보이면 세트가 뒤집힌다)
_GLOW30 = [t for t in ("skin_pores", "skinbooster_embo", "skin_redness")
           if "no healthy glow" not in build_prompts(t, "selfie", _pb26("selfie", 1, seed=31, treatment=t)[0], 31001)["before_prompt"]]
ok(not _GLOW30, f"Before 프롬프트에 광 금지가 붙는다 — 빠진 시술 {_GLOW30}")

# ③ 그 금지가 After 로 새면 안 된다 (After 는 물광이 목표다 — 같은 문장이 양쪽에 붙으면 목표가 서로를 지운다)
_LEAK30 = [t for t in ("skin_pores", "skinbooster_embo", "skin_redness")
           if "no healthy glow" in build_prompts(t, "selfie", _pb26("selfie", 1, seed=31, treatment=t)[0], 31001)["after_prompt"]]
ok(not _LEAK30, f"광 금지는 Before 에만 — After 로 샌 시술 {_LEAK30}")

# ㉛ 2026-09-14 오후 3차 (연서님 "효과가 약하다" 신호 추적) — After 프롬프트가 **스스로를 지우던** 문장.
#    `skin_state.different` 끝줄이 "not cleaner or smoother overall than the reference" 였고,
#    바로 다음 문장이 "The treatment result is now visible: ..." 였다. 피부 3종은 시술 부위가 곧
#    얼굴 피부라 앞 문장이 뒤 문장을 통째로 무효화한다(실측: 효과 점수 8 → 6, 3/3 이 합격선 턱걸이).
#    ⚠ 지울 것은 '리터칭'이지 '개선'이 아니다 — 금지는 시술 부위 **밖**에만 걸린다.
_CONTRA31 = []
for _t31 in ("skin_pores", "skinbooster_embo", "skin_redness", "nasolabial"):
    _ap31 = build_prompts(_t31, "selfie", _pb26("selfie", 1, seed=31, treatment=_t31)[0], 31111, series=["2w", "4w"])["after_prompt"]   # 가라앉은 컷만(직후는 ㉝)
    if "not cleaner or smoother overall" in _ap31:
        _CONTRA31.append(f"{_t31}:개선금지문장부활")
    if "Outside the treated area" not in _ap31:
        _CONTRA31.append(f"{_t31}:부위밖한정이없음")
ok(not _CONTRA31, f"After 에 '전보다 깨끗하면 안 된다'가 남아 효과를 지우면 안 된다 — {_CONTRA31}")

# 참조는 그림체를 옮긴다 — 후 컷엔 물광(After) 참조가 붙어야 한다. 실측 120회 기준 100%.
from bna import refs as _rf31
_GLOWREF31 = {"skin_pores_after4w_02.jpg", "skinbooster_embo_after4w_01.jpg", "skin_redness_after4w_01.jpg"}
_miss31, _tot31 = 0, 0
for _t31 in _SKIN26:
    for _s31 in range(30):
        for _v31 in _pb26("selfie", 1, seed=_s31, treatment=_t31):
            _got31 = [r["file"].split("/")[-1] for r in
                      _rf31._rank(_rf31.candidates("selfie", _t31, "2w"), _v31, "2w")[:2]]
            _tot31 += 1
            if not (set(_got31) & _GLOWREF31):
                _miss31 += 1
ok(_miss31 / _tot31 <= 0.05,
   f"후 컷에는 물광 참조가 붙는다(그림체가 무광으로 끌리지 않게) — 안 붙은 회차 {_miss31}/{_tot31}")




ok(_arc26 / _n26 >= 0.60,
   f"'전=센 빛 → 후=부드러운 빛'이 6할 이상이어야 한다(물광은 빛이 만든다) — 실제 {_arc26/_n26*100:.0f}%")
ok(_sev26 / _n26 >= 0.55,
   f"Before 강도는 marked 쪽으로 기울어야 한다(mild+subtle 짝은 전후가 구별 안 된다) — 실제 {_sev26/_n26*100:.0f}%")
# ③ 잠금이 호를 이긴다 — drift_lock 에 lighting 을 도로 넣으면 되돌아가야 한다(되돌릴 레버가 살아 있나)
_tr26 = _tre26("skinbooster_embo", "selfie")
ok(_tr26["lighting_arc"].get("before") and _tr26["lighting_arc"].get("after"),
   "조명 호가 treatment_rules 까지 실려 와야 한다(안 실리면 설정이 죽은 칸이 된다)")
_tr26b = dict(_tr26, drift_lock=list(_tr26["drift_lock"]) + ["lighting"])
ok(_av26f("lighting", {"background": "home"}, "selfie", load("variations.yaml"), _tr26b, stage="after")
   == _av26f("lighting", {"background": "home"}, "selfie", load("variations.yaml"), _tr26b),
   "drift_lock 에 lighting 이 있으면 호는 무시돼야 한다(잠금이 이긴다 = 되돌리는 레버)")
# ④ 시술 전 전용 참조는 After 컷에 안 붙는다 (방향만 반대인 0911 사고).
#    축은 빌디가 같은 날 올린 `timeline: before` 하나다 — 티모가 짜던 `stage` 축은 같은 일을 두 벌로
#    만들므로 버렸다(둘이면 한쪽만 고쳐져 갈린다). 회귀는 남긴다: 막는 성질이 같기 때문이다.
import bna.refs as _R26
_orig26 = _R26.check_index
_R26.check_index = lambda: [{"file": "x.jpg", "mode": "selfie", "timeline": "before", "tags": {}},
                            {"file": "y.jpg", "mode": "selfie", "timeline": "2w", "tags": {}},
                            {"file": "z.jpg", "mode": "selfie", "tags": {}}]
_bef26 = [r["file"] for r in _R26.candidates("selfie")]
_aft26 = [r["file"] for r in _R26.candidates("selfie", when="2w")]
_R26.check_index = _orig26
ok(_bef26 == ["x.jpg", "z.jpg"] and _aft26 == ["y.jpg", "z.jpg"],
   f"timeline=before 참조는 Before 에만·시점 태그는 그 시점 After 에만 — 실제 {_bef26} / {_aft26}")

# ㉗ 참조 사진이 **실제로 붙는가** (2026-09-14). 색인에 있는데 안 붙는 참조는 유령과 같다 —
#    파일도 있고 태그도 있어 아무도 이상을 못 느끼는데, 그림엔 한 번도 안 들어간다.
#    실사고: 태그에 셀카에 없는 값(quality: flagship · background: clinic)이 들어가 전부 0점 동점이 됐고,
#    안정 정렬이 색인 앞 2장만 계속 골라 `skin_pores_*_03` 쌍이 120회 중 7회(6%)만 붙었다.
_V27 = load("variations.yaml")
_bad27 = []
for _r27 in _R26.check_index():                       # ㉖ 에서 이미 import 한 bna.refs
    for _ax27, _val27 in (_r27.get("tags") or {}).items():
        if _ax27 in _V27 and _val27 not in _V27[_ax27]:
            _bad27.append(f"{_r27['file']} {_ax27}={_val27}")
ok(not _bad27, f"참조 태그는 그 축에 실재하는 값이어야 한다(오타는 영원히 0점이다) — {_bad27}")

from collections import Counter as _C27
_seen27 = _C27()
for _t27 in ("skin_pores", "skinbooster_embo", "skin_redness"):
    # 120장 — 직후 참조 8장은 태그가 전부 같아 동점 무작위라, 60장(직후 ≈16컷·자리 32)이면 한 장이 0회일 확률이 ≈10%다.
    #   2026-09-21 추첨 큐를 (축, 허용 집합)별로 나누며 난수 순서가 바뀌자 05.jpg 가 걸렸다(코드 결함 아님) → 표본을 늘려 ≈0.1% 로.
    for _i27, _p27 in enumerate(_pb26("selfie", 120, seed=27, treatment=_t27)):
        _sp27 = build_prompts(_t27, "selfie", _p27, 27000 + _i27)
        _w27 = _sp27["afters"][0]["when"]
        for _r27 in _R26._rank(_R26.candidates("selfie", _t27, None), _p27, None)[:2]:
            _seen27[_r27["file"]] += 1
        for _r27 in _R26._rank(_R26.candidates("selfie", _t27, _w27), _sp27["after_variation"], _w27)[:2]:
            _seen27[_r27["file"]] += 1
_skinrefs27 = [r["file"] for r in _R26.check_index() if "skin" in r["file"]]
_never27 = [f for f in _skinrefs27 if _seen27[f] == 0]
ok(not _never27, f"피부 3종 참조는 한 장도 빠짐없이 실제로 붙어야 한다 — 한 번도 안 붙은 것 {_never27}")

# 같은 컷이면 늘 같은 참조여야 한다 (재시도·재현이 성립해야 하므로 셔플은 결정적이어야 한다)
_p27a = _pb26("selfie", 1, seed=271, treatment="skin_pores")[0]
ok(_R26._rank(_R26.candidates("selfie", "skin_pores", None), _p27a, None)
   == _R26._rank(_R26.candidates("selfie", "skin_pores", None), _p27a, None),
   "동점 섞기는 결정적이어야 한다 — 같은 컷은 늘 같은 참조")

# ㉜ 2026-09-14 밤 (연서님 "후 사진은 광이 조금 더 돌아야 하는데 매트한 느낌이 더 든다" /
#    "피부 3종 표정 다르게 뽑기를 '무조건'이라는 단어로 너무 막아두지 말자").
#    ① 표정: 확률로 잠그지 않는다. 대신 *바뀔 때는* 입 벌림이나 눈/시선 중 하나가 실제로 다른 칸을 고른다.
#       실측 근거(450세트): 키는 69% 바뀌는데 입·눈이 둘 다 그대로인 세트가 47% 였다
#       (neutral_closed → slight_smile 처럼 둘 다 '다문 입·렌즈 응시'인 이웃).
_V32 = load("variations.yaml")
_TB32 = _V32.get("expression_traits", {})
_missing32 = [k for k in _V32["mode_rules"]["selfie"]["expression"] if k not in _TB32]
ok(not _missing32, f"셀카에 쓰는 표정 칸은 전부 expression_traits 에 있어야 한다(빠지면 조용히 옛 동작) — {_missing32}")

_viol32, _same32, _n32 = [], 0, 0
for _t32 in ("skin_pores", "skinbooster_embo", "skin_redness"):
    for _i32, _p32 in enumerate(_pb26("selfie", 60, seed=32, treatment=_t32)):
        _a32 = build_prompts(_t32, "selfie", _p32, 32000 + _i32, series=["4w"])["after_variation"]   # 가라앉은 컷만(직후는 ㉝)
        _b32k, _a32k = _p32["expression"]["key"], _a32["expression"]["key"]
        _n32 += 1
        if _b32k == _a32k:
            _same32 += 1
        elif _TB32.get(_b32k) == _TB32.get(_a32k):
            _viol32.append(f"{_b32k}→{_a32k}")
ok(not _viol32, f"표정이 바뀐 세트는 입 벌림이나 눈/시선이 실제로 달라야 한다 — 위반 {_viol32[:4]}")
#    ⚠ '무조건 금지'는 여기서 지킨다 — 같은 표정으로 남는 여유가 사라지면 그것대로 기계가 된다.
ok(0.15 <= _same32 / _n32 <= 0.45,
   f"표정을 잠그지 않는다(연서님 지시) — 전후 같은 표정으로 남는 세트가 있어야 한다, 실제 {_same32/_n32*100:.0f}%")
ok(_V32["after_drift"]["selfie"]["later"]["expression"] < 1.0,
   "표정 재추첨 확률은 1.0 이면 안 된다 — 잠금 재발 감시(2026-09-14 연서님)")

#    ② 광: After 에 '피부가 빛을 어떻게 받는가'를 말하는 칸이 있어야 한다.
#       0914 실측으로 매트 쪽 압력은 세 곳인데 광을 요구하는 말은 엠보 한 마디뿐이었고 모공·홍조는 0개였다.
_FIN32 = []
for _t32 in ("skin_pores", "skinbooster_embo", "skin_redness"):
    _sp32 = build_prompts(_t32, "selfie", _pb26("selfie", 1, seed=33, treatment=_t32)[0], 33001, series=["4w"])   # 가라앉은 컷만(직후는 ㉝)
    if "dewy sheen" not in _sp32["after_prompt"]:
        _FIN32.append(f"{_t32}:After광없음")
    # ⚠ Before 에는 "no dewy sheen"(금지문)이 있으므로 낱말로 재면 늘 걸린다 — 마감 칸 자체로 잰다
    if "Skin finish:" in _sp32["before_prompt"]:
        _FIN32.append(f"{_t32}:Before로샘")            # 전이 후보다 좋아 보이면 세트가 뒤집힌다
    if "more luminous than the flat matte skin in the reference" not in _sp32["after_prompt"]:
        _FIN32.append(f"{_t32}:참조대비문구없음")      # 참조(무광 Before)가 그림체를 끌어당기는 걸 막는 문장
    if not any(p.get("k") == "finish" for p in _sp32["after_parts"]):
        _FIN32.append(f"{_t32}:화면칸없음")            # 검수 화면이 "이 문장 어디서 왔나"를 못 보여준다
ok(not _FIN32, f"스킨부스터 3종 After 에 피부 마감(광) 칸이 붙는다 — {_FIN32}")

#    광은 '보정'과 한 끗 차이다 — 광 안에서도 모공·솜털이 보여야 한다는 제동이 같이 붙어야 한다.
_ap32 = build_prompts("skin_pores", "selfie", _pb26("selfie", 1, seed=33, treatment="skin_pores")[0], 33001)["after_prompt"]
ok("pores, peach fuzz and fine texture stay clearly visible" in _ap32 and "glass-skin" in _ap32,
   "광 요구엔 '질감은 남는다·유리알 피부 금지' 제동이 같이 붙어야 한다(과장이 AI 티다)")

#    마감 칸이 없는 시술엔 한 글자도 안 붙는다(빈 칸이 템플릿에 구멍을 남기지 않는지 포함)
_ap32n = build_prompts("nasolabial", "selfie", _pb26("selfie", 1, seed=33, treatment="nasolabial")[0], 33001)["after_prompt"]
ok("dewy sheen" not in _ap32n and "{after_finish}" not in _ap32n,
   "after_finish 가 없는 시술엔 마감 문장도 빈 슬롯도 남지 않는다")

#    임상 After 는 '같은 사진 편집·조명 동일'이라 광을 얹으면 그건 시술이 아니라 리터칭이다 — 안 붙는 게 맞다.
_apc32 = build_prompts("skin_pores", "clinical", _pb26("clinical", 1, seed=33, treatment="skin_pores")[0], 33002)["after_prompt"]
ok("dewy sheen" not in _apc32, "임상 After 에는 광 문장이 붙지 않는다(조명 동일 편집이라 광은 리터칭이 된다)")


# ㉝ 2026-09-14 저녁 연서님 "엠보는 직후가 조금 다이나믹한데 요렇게 직후로 보여지거든" (실사 6장).
#    엠보에 직후 시점이 생겼다 — 직후 컷은 격자 볼록(팽진)이 보이고, 물광 마감·부드러운 조명 호는 안 붙는다.
_EMBO33 = []
_arc33 = set(_tr_all["skinbooster_embo"]["lighting_arc"]["after"])
_soft33, _n33 = 0, 0
for _s33 in range(20):
    _sp33 = build_prompts("skinbooster_embo", "selfie", _pb26("selfie", 1, seed=_s33, treatment="skinbooster_embo")[0], 33300 + _s33, series=["immediate", "4w"])
    _by33 = {a["when"]: a for a in _sp33["afters"]}
    if list(_by33) != ["immediate", "4w"]:
        _EMBO33.append(f"seed{_s33}:시점{list(_by33)}"); continue
    _im, _w4 = _by33["immediate"]["after_prompt"], _by33["4w"]["after_prompt"]
    if "grid of small raised bumps" not in _im: _EMBO33.append(f"seed{_s33}:직후에볼록없음")
    if "Skin finish:" in _im: _EMBO33.append(f"seed{_s33}:직후에광마감")
    if "natural glow" in _im: _EMBO33.append(f"seed{_s33}:직후에물광문장")   # 카드의 "no glow yet" 과 싸운다
    # ⚠ 낱말 `raised bumps` 로 보면 안 된다 — 09-14 에 붙인 7일차 기준 문장이 `no raised bumps`(금지문)라
    #   이 자가 금지문을 요구문으로 읽고 20/20 을 실패로 냈다(같은 날 `dewy sheen` 과 똑같은 함정).
    #   직후 컷이 볼록을 부르는 **그 문장**(facts.immediate_marks 의 시작 어구)이 없는지를 본다.
    if "grid of small raised bumps" in _w4 or "Skin finish:" not in _w4: _EMBO33.append(f"seed{_s33}:4주컷이상")
    if _by33["immediate"]["effect_level"] != "early": _EMBO33.append(f"seed{_s33}:직후강도{_by33['immediate']['effect_level']}")
    if not any(p.get("k") == "facts" for p in _by33["immediate"]["after_parts"]): _EMBO33.append(f"seed{_s33}:화면칸없음")
    _n33 += 1; _soft33 += _by33["immediate"]["after_variation"]["lighting"]["key"] in _arc33
ok(not _EMBO33, f"엠보 직후 컷은 격자 볼록이 보이고 광 마감은 4주 컷에만 붙는다 — {_EMBO33}")
ok(_n33 and _soft33 < _n33, f"직후 컷은 부드러운 빛으로 몰리지 않는다(같은 날 병원 빛) — 부드러운 빛 {_soft33}/{_n33}")
ok(_tr_all["skinbooster_embo"]["timeline"][0] == "immediate", "엠보 timeline 에 immediate 가 맨 앞에 있다")



# ㉞ 2026-09-14 승격 두 사고 — ①승격이 주석을 통째로 지웠다 ②승격이 커밋을 안 해 git 이 되돌렸다.
#    둘 다 "오류 0 인데 규칙이 사라진다"라 회귀가 없으면 다음에도 똑같이 조용하다.
import shutil as _sh34
import subprocess as _sp34
import tempfile as _tf34
from pathlib import Path as _P34

import yaml as _yml34

import bna.lessons as _L34
import bna.spec as _S34

_HEAD34 = """# 머리말 주석(정본)
settings:
  top_n: 3
tags:
  손가락:
    en: no hands
    where:
    - before
custom:
- en: first rule
  where:
  - after
  # ⚠ 이 설명이 정본이다 — 지워지면 다음 사람이 위 줄을 지운다
  not_at:
  - immediate
  from: 첫 규칙
  since: '2026-09-10'
"""


def _mkcfg34(body: str, tmp):
    """임시 config/prompts/avoid.yaml 을 만들고 bna.spec.CFG 를 그리로 돌린다."""
    d = _P34(tmp) / "config" / "prompts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "avoid.yaml").write_text(body, encoding="utf-8")
    return d / "avoid.yaml"


def _promote34(body: str, en: str, note: str = "메모", root=None, where=None):
    """진짜 promote() 를 임시 트리에서 돌린다(CFG·ROOT 만 갈아 끼운다)."""
    _cfg0, _root0 = _S34.CFG, _S34.ROOT
    tmp = root or _tf34.mkdtemp()
    try:
        p = _mkcfg34(body, tmp)
        _S34.CFG, _S34.ROOT = _P34(tmp) / "config", _P34(tmp)
        r = _L34.promote(note, en, where)
        return r, p.read_text(encoding="utf-8")
    finally:
        _S34.CFG, _S34.ROOT = _cfg0, _root0
        if root is None:
            _sh34.rmtree(tmp, ignore_errors=True)


_r34, _txt34 = _promote34(_HEAD34, "second rule")
ok(_r34.get("ok") and _r34.get("kept_comments"), f"승격은 덧붙이기로 들어간다 — {_r34.get('kept_comments')}")
ok("# ⚠ 이 설명이 정본이다" in _txt34, "custom 안 주석이 승격 뒤에도 남는다 (09-14 사고: safe_dump 가 지웠다)")
ok("# 머리말 주석(정본)" in _txt34, "머리말 주석도 그대로 남는다")
_y34 = _yml34.safe_load(_txt34)
ok([c["en"] for c in _y34["custom"]] == ["first rule", "second rule"], "새 규칙은 맨 끝에 붙는다")
ok(_y34["custom"][0].get("not_at") == ["immediate"], "옆 규칙의 값은 안 건드린다")
ok(_y34["tags"]["손가락"]["en"] == "no hands" and _y34["settings"]["top_n"] == 3, "tags·settings 는 그대로다")

# custom 뒤에 다른 최상위 키가 오면 그 **앞**에 넣어야 한다(뒤에 붙이면 남의 블록에 섞인다)
_r34b, _txt34b = _promote34(_HEAD34 + "\nextra:\n  a: 1\n", "third rule")
_y34b = _yml34.safe_load(_txt34b)
ok(_r34b.get("kept_comments") and [c["en"] for c in _y34b["custom"]] == ["first rule", "third rule"]
   and _y34b.get("extra") == {"a": 1}, f"custom 뒤에 다른 키가 있어도 그 앞에 넣는다 — {_y34b.get('extra')}")

# custom: 이 아예 없는 파일도 열 수 있어야 한다
_r34c, _txt34c = _promote34("settings:\n  top_n: 3\n", "lonely rule")
ok((_yml34.safe_load(_txt34c).get("custom") or [{}])[0].get("en") == "lonely rule", "custom 이 없으면 새로 연다")

# 같은 문장은 두 번 안 들어간다(종전 규칙 유지)
_r34d, _ = _promote34(_HEAD34, "first rule")
ok(not _r34d.get("ok") and "이미" in (_r34d.get("error") or ""), "같은 en 은 거부한다")

# 'after photo' 문장은 화면이 전·후를 보내도 After 에만 붙는다(09-15 팔자·09-17 수염 — Before 가 '후 사진'을 말한 사고 2회)
_BEARD34 = "In the after photo the person must have the same beard as in the before photo."
_r34w, _txt34w = _promote34(_HEAD34, _BEARD34, where=["before", "after"])
ok(_r34w.get("where_narrowed") and _yml34.safe_load(_txt34w)["custom"][-1]["where"] == ["after"],
   f"'after photo' 문장은 before 자리를 뺀다 — {_r34w.get('rule', {}).get('where')}")
ok(_L34._narrow_where("no visible pores on the cheek", ["before", "after"]) == (["before", "after"], False),
   "'after photo' 가 없으면 자리를 안 건드린다")
ok(_L34._narrow_where("same tone as the before photo", ["after"]) == (["after"], False),
   "After 가 '전 사진'과 비교하는 문장은 좁히지 않는다")
ok(_L34._narrow_where("the After-Photo keeps lighting", ["before"]) == (["after"], True),
   "대소문자·하이픈 표기도 잡는다")

# ── 자동 커밋 ────────────────────────────────────────────────────────────────
_git34 = _sh34.which("git")
if not _git34:
    print("SKIP  git 없음 — 승격 자동 커밋 검사 건너뜀")
else:
    _t34 = _tf34.mkdtemp()
    try:
        def _g34(*a, cwd=_t34):
            return _sp34.run([_git34, *a], cwd=cwd, text=True, capture_output=True, timeout=20)
        _g34("init", "-q", "-b", "main")
        _g34("config", "user.email", "t@t"); _g34("config", "user.name", "t")
        _mkcfg34(_HEAD34, _t34)
        (_P34(_t34) / "남의파일.txt").write_text("처음", encoding="utf-8")
        _g34("add", "-A"); _g34("commit", "-q", "-m", "init")
        # 남이 편집 중인 파일을 만들어 둔다 — 승격이 이걸 쓸어 담으면 안 된다
        (_P34(_t34) / "남의파일.txt").write_text("편집 중", encoding="utf-8")
        _r34e, _ = _promote34(_HEAD34, "commit me", root=_t34)
        _c34 = _r34e.get("commit") or {}
        ok(_c34.get("ok") and _c34.get("sha"), f"승격이 그 자리에서 커밋한다 — {_c34}")
        _files34 = _g34("show", "--name-only", "--format=", "HEAD").stdout.split()
        ok(_files34 == ["config/prompts/avoid.yaml"], f"커밋에 담기는 건 avoid.yaml 하나뿐 — {_files34}")
        ok(_g34("status", "--porcelain", "--", "남의파일.txt").stdout.strip().startswith("M"),
           "남이 편집 중인 파일은 손대지 않는다(커밋도 스테이징도)")
        ok(_g34("diff", "--quiet", "--", "config/prompts/avoid.yaml").returncode == 0,
           "커밋 뒤 avoid.yaml 은 깨끗하다 — git 이 되돌려도 규칙이 살아남는 자리")
        # 리베이스 중이면 아무것도 안 한다
        (_P34(_t34) / ".git" / "REBASE_HEAD").write_text("x", encoding="utf-8")
        _r34f, _ = _promote34(_HEAD34, "during rebase", root=_t34)
        ok(_r34f.get("ok") and not (_r34f.get("commit") or {}).get("ok")
           and "리베이스" in ((_r34f.get("commit") or {}).get("why") or ""),
           f"병합·리베이스 중엔 커밋하지 않는다(승격 자체는 산다) — {(_r34f.get('commit') or {}).get('why')}")
        (_P34(_t34) / ".git" / "REBASE_HEAD").unlink()
    finally:
        _sh34.rmtree(_t34, ignore_errors=True)

# 깃이 아닌 폴더에서도 승격은 살아야 한다(fail-open)
_r34g, _txt34g = _promote34(_HEAD34, "no git here")
ok(_r34g.get("ok") and not (_r34g.get("commit") or {}).get("ok")
   and "no git here" in _txt34g, "깃 저장소가 아니어도 승격은 성공한다(커밋만 건너뜀)")


# ㉟ 2026-09-14 빌디 지적 — 복붙 게이트(신설) + 셀카 drift 완화.
#    둘은 **한 벌이다**: 완화만 하면 복사본이 더 쉽게 통과하고, 게이트만 넣으면 잘 그린 컷이 애꿎게 죽는다.
from pathlib import Path as _P35

import numpy as _np35
import yaml as _yml35

from bna.qa import structure as _ST35
from bna.qa import vision as _VS35

Path, yaml = _P35, _yml35                               # 이 절 안에서만 쓰는 짧은 이름

# 실사 랜드마크로 자를 검증한다 — 지어낸 좌표는 "값이 흐르나"만 보고 **자가 맞나**를 못 본다.
_PAIR35 = Path("outputs/20260914-085009-06ac/0001")     # 빌디가 든 증거(배경만 갈아 끼운 복사본)
_OK35 = Path("outputs/20260910-153348-63cb/0002")       # 사람이 채택한 컷(가장 다른 자세)


def _pts35(d: Path):
    from PIL import Image as _I
    from bna.qa import landmarks as _L
    b = next(d.glob("*_before.jpg"), None); a = next(d.glob("*_after.jpg"), None)
    if not (b and a):
        return None, None
    return _L.detect(_I.open(b)), _L.detect(_I.open(a))


if not _PAIR35.exists():
    print("SKIP  0914 엠보 시료가 없다 — 복붙 게이트 실사 검사 건너뜀")
else:
    _pb35, _pa35 = _pts35(_PAIR35)
    _r35 = _ST35.copy_check(_pb35, _pa35, "selfie")
    ok(_r35["passed"] is False, f"빌디가 든 복사본은 탈락한다 — {_r35}")
    ok("표정" in _r35["reason"] and "고개" in _r35["reason"],
       "탈락 사유에 무엇이 같았는지(표정·고개)를 적는다 — 사람이 재현할 수 있어야 한다")
    # 임상은 닮은 게 정답이다 — 같은 시료라도 걸리면 안 된다
    _c35 = _ST35.copy_check(_pb35, _pa35, "clinical")
    ok(_c35["passed"] is None and not _c35["measured"],
       f"임상 컷엔 이 자를 걸지 않는다(못 잼, 실패 아님) — {_c35['passed']}")
    if _OK35.exists():
        _ob35, _oa35 = _pts35(_OK35)
        _o35 = _ST35.copy_check(_ob35, _oa35, "selfie")
        ok(_o35["passed"] is True, f"사람이 채택한 컷은 통과한다 — {_o35}")

# 얼굴 미검출은 실패가 아니라 '못 잼'이다(이 파일 다른 자들과 같은 3값 규칙)
_n35 = _ST35.copy_check(None, None, "selfie")
ok(_n35["passed"] is None and not _n35["measured"], "얼굴 미검출은 탈락이 아니라 못 잼이다")

# 자가 크기·위치·기울기에 안 흔들려야 한다 — "확대해서 찍었다"가 복붙으로 둔갑하면 안 된다
_base35 = _np35.array([[100.0 + i * 3, 200.0 + (i % 7) * 5] for i in range(478)])
_scaled35 = _base35 * 2.3 + _np35.array([57.0, -31.0])
_v1, _v2 = _ST35.pose_vector(_base35), _ST35.pose_vector(_scaled35)
ok(float(_np35.abs(_v1 - _v2).max()) < 1e-6,
   f"자세 값은 얼굴 크기·위치가 변해도 그대로다 — 최대차 {float(_np35.abs(_v1 - _v2).max()):.2e}")

# 표정만 같고 고개가 다르면 복붙이 아니다(AND 규칙) — 하나만 같은 건 흔하다
_moved35 = _base35.copy(); _moved35[152] = _moved35[152] + _np35.array([0.0, 400.0])   # 턱만 크게 이동
_r2 = _ST35.copy_check(_base35, _moved35, "selfie")
ok(_r2["passed"] is True and _r2["expr_diff"] <= _ST35.COPY_EXPR_CUT,
   f"표정이 같아도 고개가 다르면 통과한다(AND 규칙) — 표정 {_r2['expr_diff']} 고개 {_r2['head_diff']}")
ok(_ST35.copy_check(_base35, _base35.copy(), "selfie")["passed"] is False,
   "완전히 같은 얼굴은 반드시 탈락한다")
# 컷을 meta 에 남긴다 — 컷을 바꾸면 옛 회차와 다른 자다(무엇으로 잰 판정인지 추적 가능해야 한다)
ok(_ST35.copy_check(_base35, _base35.copy(), "selfie")["cuts"] ==
   {"expr": _ST35.COPY_EXPR_CUT, "head": _ST35.COPY_HEAD_CUT}, "어느 컷으로 잰 판정인지 남긴다")

# ── 셀카 drift 완화 ──────────────────────────────────────────────────────────
_QA35 = yaml.safe_load(Path("config/qa_checklist.yaml").read_text(encoding="utf-8"))
_sel35 = {**_QA35["items"], **(_QA35.get("items_selfie") or {})}
_cli35 = {**_QA35["items"], **(_QA35.get("items_clinical") or {})}
ok(set(_sel35) == set(_QA35["items"]) and set(_cli35) == set(_QA35["items"]),
   "모드별 덮어쓰기는 항목을 늘리거나 지우지 않는다(키만 덮는다)")
ok(_sel35["drift"] != _cli35["drift"], "셀카·임상 drift 문항이 실제로 갈렸다")
_low = _sel35["drift"].lower()
ok("never lower the score" in _low and "expected" in _low,
   "셀카 drift 는 장면·표정 차이에 **감점하지 말라**고 명시한다(빌디 0914)")
for _w in ("background", "lighting", "expression", "head angle"):
    ok(_w in _low, f"셀카 drift 가 '{_w}' 를 감점 대상에서 빼는 말을 담고 있다")
ok("nothing outside the treated area" in _cli35["drift"].lower(),
   "임상 drift 는 종전 뜻(부위 밖 변화 금지)을 그대로 지킨다")


# 심사에 실제로 그 문항이 가는지 — 설정만 갈라 놓고 provider 에 옛 문항을 넘기면 아무것도 안 바뀐다
class _Spy35:
    name = "spy"

    def qa(self, b, a, items, mode):
        self.items, self.mode = items, mode
        return {k: {"score": 9.0, "note": ""} for k in items}


_spy35 = _Spy35()
_VS35.score(b"x", b"y", "selfie", _spy35)
ok(_spy35.items["drift"] == _sel35["drift"], "셀카 회차는 셀카 문항이 심사에 간다")
_VS35.score(b"x", b"y", "clinical", _spy35)
ok(_spy35.items["drift"] == _cli35["drift"], "임상 회차는 임상 문항이 심사에 간다")

# 복붙 게이트가 배치의 탈락 사유로 실제로 연결돼 있는지 (설정·함수만 있고 아무도 안 부르면 죽은 자다)
_bt35 = Path("src/bna/batch.py").read_text(encoding="utf-8")
ok('"copy"' in _bt35 and 'st.get("copy")' in _bt35,
   "batch 가 복붙 판정을 읽어 탈락 사유에 넣는다(안 읽으면 죽은 게이트다)")
ok('out["copy"] = copy_check' in Path("src/bna/qa/structure.py").read_text(encoding="utf-8"),
   "structure.check 가 복붙 판정을 함께 낸다(랜드마크 재검출 0)")

# ㉞ 2026-09-15 07:55 엠보 배치 실사고 — Before 가 before/after 글자가 박힌 2단 콜라주로 나왔다.
#    Before 프롬프트에 'after photo' 가 세 번 있었다(before.md 끝줄 · 팔자 승격 규칙이 전 시술 Before 에 붙음 · '후기 앱').
_COL34 = []
from bna import lessons as _ls34
from bna.spec import ROOT as _ROOT34
for _t34 in ("skinbooster_embo", "skin_pores", "nasolabial"):
    _av34 = _ls34.active(_ROOT34 / "outputs", _t34, "selfie")           # 승격 규칙은 배치가 이 길로 넣는다(batch.py:67)
    _sp34 = build_prompts(_t34, "selfie", _pb26("selfie", 1, seed=34, treatment=_t34)[0], 34001, series=["4w"] if _t34 != "nasolabial" else ["2w"],
                          avoid=_av34["lines"], avoid_not_at=_av34["not_at"])
    _bp34, _ap34 = _sp34["before_prompt"], _sp34["after_prompt"]
    if "after photo" in _bp34: _COL34.append(f"{_t34}:Before에 after photo")
    if "review app" in _bp34 or "review app" in _ap34: _COL34.append(f"{_t34}:후기앱")
    if "One single snapshot" not in _bp34: _COL34.append(f"{_t34}:한장긍정문없음")
    if _t34 != "nasolabial" and "nasolabial folds" in _ap34: _COL34.append(f"{_t34}:팔자규칙이 다른 시술 After에")
    if _t34 == "nasolabial" and "nasolabial folds must be softened" not in _ap34: _COL34.append("nasolabial:팔자규칙 사라짐")
ok(not _COL34, f"Before 프롬프트는 '후 사진'을 말하지 않고, 팔자 승격 규칙은 팔자 After 에만 붙는다 — {_COL34}")

#    콜라주 게이트 — 큰 얼굴이 둘이면 잡고, 배경의 작은 얼굴은 무시한다(모델 없이 상자 계산만 검사)
from bna.qa import identity as _idn34
class _F34:
    def __init__(s, w, h): s.bbox = (0, 0, w, h)
ok(_idn34.count_big([_F34(100, 100), _F34(95, 100)]) == 2 and _idn34.count_big([_F34(100, 100), _F34(20, 20)]) == 1
   and _idn34.count_big([]) == 0, "콜라주 게이트: 큰 얼굴 둘 = 콜라주, 배경의 작은 얼굴은 무시")
ok('"collage"' in open("src/bna/batch.py", encoding="utf-8").read(), "배치가 콜라주를 탈락 사유로 센다")

#    엠보 4주 컷 참조는 엠보 전용 사진이 공용(모공·홍조) 사진보다 먼저다 (1주 컷보다 4주가 나빠 보이던 원인)
from bna import refs as _rf34
_first34 = []
for _s34 in range(10):
    _v34 = build_prompts("skinbooster_embo", "selfie", _pb26("selfie", 1, seed=_s34, treatment="skinbooster_embo")[0], 34100 + _s34, series=["4w"])["after_variation"]
    _first34.append(_rf34._rank(_rf34.candidates("selfie", "skinbooster_embo", "4w"), _v34, "4w", "skinbooster_embo")[0]["file"].split("/")[-1])
ok(all(f.startswith("skinbooster_embo_") for f in _first34), f"엠보 4주 컷의 1순위 참조는 엠보 전용 사진이다 — {sorted(set(_first34))}")


# ㉟ 시점별 After 동시 생성 · 비포 콜라주 선검사 · 429 재시도 (2026-09-15 티모 검토)
#    값이 아니라 *구조*를 지키는 회귀다 — 이 셋은 한 벌이라 하나만 되돌리면 조용히 갈린다.
#    벽시계·동시 재고 실측은 tools/_probe_after_parallel_0915.py(대역, $0)·_sim_after_parallel_0915.py.
_BAT35 = open("src/bna/batch.py", encoding="utf-8").read()
_OAI35 = open("src/bna/providers/openai_img.py", encoding="utf-8").read()
from bna.batch import REDO_BEFORE as _RB35, RETRY_REDRAW as _RR35, _retry_plan as _rp35
#    ① 콜라주 Before 는 반드시 다시 그린다 — 안 그러면 2·3회차가 같은 콜라주로 확정 탈락한다
ok("collage_before" in _RB35 and _rp35(["collage_before"])[1] is True,
   "콜라주 Before 탈락은 Before 를 다시 그린다(REDO_BEFORE)")
ok(_rp35(["collage"])[1] is False and "collage" not in _RB35,
   "After 쪽 콜라주는 멀쩡한 Before 를 버리지 않는다")
ok(_rp35(["collage_before@4w"])[1] is True, "시리즈 접미(@시점)가 붙어도 같은 판정")
#    ② 사유를 어느 쪽 얼굴 수로 가르는지 — 이 줄이 사라지면 ①이 영원히 안 발동한다
ok('"collage_before" if ((idn.get("faces") or {}).get("before") or 0) >= 2' in _BAT35,
   "콜라주 사유를 Before/After 얼굴 수로 가른다")
#    ③ gather 는 예외를 삼키지 말고 **비용을 먼저 적고** 올린다(기본값이면 이미 쓴 돈이 원장에서 사라진다)
ok("return_exceptions=True" in _BAT35 and 'meta["after_error"]' in _BAT35,
   "시점별 After gather 는 return_exceptions=True 로 받아 비용을 적고 예외를 올린다")
#    ④ After 동시 한도는 한 곳에서만 만든다(두 벌이면 한쪽만 고쳐져 공급자 한도를 넘긴다)
ok(_BAT35.count("asyncio.Semaphore(") == 2 and "def _slots" in _BAT35,
   "이미지 동시 한도 세마포어는 _slots 한 곳에서만 만든다(run() 의 항목 세마포어 1개 + 여기 1개)")
#    ④-2 Before 도 같은 슬롯을 타야 한다 — After 만 세면 한도를 우회해 429 가 온다(대역 실측 4콜 > 한도 3)
ok("self._slots(self.p_gen)" in _BAT35 and "self._slots(self.p_edit)" in _BAT35,
   "Before·After 가 같은 공급자 슬롯을 쓴다(Before 가 한도를 우회하지 않는다)")
ok("get_running_loop" in _BAT35, "세마포어는 이벤트 루프가 바뀌면 다시 만든다(hasattr 한 번 금지)")
#    ⑤ 선검사 상한이 있다(없으면 콜라주가 계속 나오는 프롬프트에서 회차가 안 끝난다)
from bna.batch import BEFORE_PRECHECK_TRIES as _BP35
ok(isinstance(_BP35, int) and 1 <= _BP35 <= 5, f"비포 선검사 상한이 상수로 있다 — {_BP35}")
#    ⑥ 429·5xx 재시도는 병렬화의 짝 방어다 — 둘 중 하나만 끄지 마라
ok("RETRY_WAITS_S" in _OAI35 and "retry-after" in _OAI35 and "== 429" in _OAI35,
   "OpenAI 호출은 429·5xx 를 기다렸다 다시 보낸다(병렬 버스트의 짝 방어)")
#    ⑦ 못 잴 입력은 '못 잼'으로 답한다 — 이 줄이 깨지면 selftest 가 중간에서 죽어 뒤쪽이 통째로 안 돈다
#       (초록불이 기계마다 갈리는 유형이라, 세는 줄 자체를 여기 둔다)
ok(_idn34.big_faces(None) is None, "big_faces(None) 은 0 이 아니라 None(못 잼)")


# ㊱ 동시 칸 3 → 10 + 출발 간격 (2026-09-15 성연서님 "분당 이미지 수 8장")
#    칸과 간격은 한 벌이다 — 칸만 늘리면 배치 시작 순간 10콜이 한꺼번에 나가 한도에 부딪힌다.
import yaml as _y36
from bna.providers.openai_img import _StartGate as _SG36, GATE_SAFETY as _GS36
_cfg36 = _y36.safe_load(open("config/providers.yaml", encoding="utf-8"))["openai"]
_OAI36 = open("src/bna/providers/openai_img.py", encoding="utf-8").read()
ok(isinstance(_cfg36.get("concurrency"), int) and isinstance(_cfg36.get("images_per_minute"), (int, float)),
   f"동시 칸·분당 한도는 providers.yaml 이 정본이다 — {_cfg36.get('concurrency')}칸 · {_cfg36.get('images_per_minute')}장/분")
#    ① 칸이 한도 안에서 도는지 산술로 — 1콜 ≈ 105초(09-15 실측 중앙 104.3~109.1)
ok(_cfg36["concurrency"] * 60 / 105 < _cfg36["images_per_minute"] * _GS36,
   f"칸 × 60 ÷ 105 < 한도 × 안전율 — {_cfg36['concurrency'] * 60 / 105:.1f} < {_cfg36['images_per_minute'] * _GS36:.1f}")
#    ② 간격: 가짜 시계로 동시에 10콜이 몰려도 한도 × 안전율보다 촘촘히 출발하지 않는다
_t36 = [0.0]
_g36 = _SG36(8, clock=lambda: _t36[0], sleep=lambda s: None)
_starts36 = [_g36.wait() for _ in range(10)]          # 같은 순간에 10콜 — 각 콜이 몇 초 뒤 출발하는지
ok(abs(_starts36[1] - 60 / (8 * _GS36)) < 1e-9 and _starts36[0] == 0.0,
   f"첫 콜은 바로, 다음 콜은 {60 / (8 * _GS36):.2f}초 뒤")
ok(sum(1 for s in _starts36 if s < 60) <= int(8 * _GS36) + 1,
   f"몰린 10콜 중 첫 60초 안에 출발하는 건 한도 이내 — {sum(1 for s in _starts36 if s < 60)}콜")
_t36[0] = 1000.0
ok(_g36.wait() == 0.0, "오래 쉬었으면 밀린 간격을 쌓아 두지 않고 바로 출발한다")
ok(_SG36(None).wait() == 0.0 and _SG36(0).wait() == 0.0, "한도 값이 없으면 간격 없음(종전 동작)")
#    ③ 이미지 경로만 문을 지나고, 429 재시도도 같은 문을 다시 지난다(루프 안)
ok('path.startswith("/images/")' in _OAI36 and "self.gate.wait()" in _OAI36
   and _OAI36.index("self.gate.wait()") > _OAI36.index("for i in range(len(RETRY_WAITS_S) + 1)"),
   "출발 간격은 이미지 콜에만, 재시도 루프 안에서 매번 건다")
#    ④ 문은 프로세스 공용 한 개 — 인스턴스마다 만들면 인스턴스 수만큼 한도가 늘어난다
ok(_OAI36.count("_StartGate(") == 1 and "_IMAGE_GATE = _StartGate(" in _OAI36,
   "_StartGate 는 한 곳(공용 _IMAGE_GATE)에서만 만든다")


# ㊲ 진행 기록만 따로 올리기 (2026-09-15 빌디 제안 5번 · 성연서님 "진행해볼까?")
#    빠지면 오류 없이 "몇 분씩 멈춰 보이는 화면"으로 되돌아간다 — 09-15 재부팅 1시간 무응답이 화면에 안 보인 구조.
_PR37 = open("src/bna/progress.py", encoding="utf-8").read()
ok(_PR37.count("cloudpush.nudge_progress(") >= 3 and "_heartbeat" in _PR37 and "self._done.set()" in _PR37,
   "진행 요약은 시작·단계마다·끝에 올리고, 심장박동은 끝나면 멈춘다")
ok('cloudpush.nudge("배치 시작")' in _PR37, "배치 시작에 전체 한 번 — 안 하면 클라우드 목록에 새 배치가 안 뜬다")
from bna import cloudpush as _cp37
ok(_cp37.HEARTBEAT_S == 60 and "HEARTBEAT_S = 60" in open("cloud/lib/liveprog.mjs", encoding="utf-8").read(),
   "심장박동 간격은 PC(cloudpush)와 화면(liveprog)이 같은 값이다")
if _shutil.which("node"):
    _t37 = _Path(tempfile.mkdtemp()); _bd37 = _t37 / "20260915-120000-test"; _bd37.mkdir()
    (_bd37 / "progress.json").write_text(json.dumps({"planned": 2, "started_at": time.time(), "finished_at": None, "error": None,
        "items": {"0000": {"stage": "after", "attempt": 1, "passed": None, "fail_reasons": [], "updated_at": time.time(), "elapsed": 0}}}), encoding="utf-8")
    _stub37, _runs37 = _t37 / "stub.mjs", _t37 / "runs.txt"
    _stub37.write_text("import {appendFileSync, readFileSync} from 'node:fs';\n"
                       "const j = JSON.parse(readFileSync(process.argv[2], 'utf8'));\n"
                       f"appendFileSync('{_runs37.as_posix()}', process.argv[3] + '|' + j.summary.done + '/' + j.summary.planned + '|' + (j.pushed_at > 0) + '\\n');\n"
                       "await new Promise(r => setTimeout(r, 300));\n", encoding="utf-8")
    _save37 = (_cp37.SCRIPT, _cp37.ENVFILE, _cp37.LOG, _cp37.PROG_SCRIPT, _cp37.PROG_MIN_INTERVAL)
    _cp37.SCRIPT, _cp37.ENVFILE, _cp37.LOG, _cp37.PROG_SCRIPT, _cp37.PROG_MIN_INTERVAL = _stub37, _stub37, _t37 / "push.log", _stub37, 0.5
    _fired37 = [_cp37.nudge_progress(_bd37) for _ in range(10)]
    _time.sleep(2.0)
    _lines37 = _runs37.read_text(encoding="utf-8").splitlines() if _runs37.exists() else []
    ok(_fired37[0] is True and not any(_fired37[1:]) and 1 <= len(_lines37) <= 2,
       f"nudge_progress 10회는 업로드 1~2회로 접힌다 — 실제 {len(_lines37)}회")
    ok(bool(_lines37) and _lines37[0] == "20260915-120000-test|0/2|true",
       f"넘기는 파일은 progress.read 요약 + pushed_at, 인자는 배치 ID — {_lines37[:1]}")
    _os.environ["BNA_AUTO_PUSH"] = "0"
    ok(_cp37.nudge_progress(_bd37) is False, "BNA_AUTO_PUSH=0 이면 진행 올리기도 꺼진다(같은 스위치)")
    _os.environ.pop("BNA_AUTO_PUSH")
    _cp37.SCRIPT, _cp37.ENVFILE, _cp37.LOG, _cp37.PROG_SCRIPT, _cp37.PROG_MIN_INTERVAL = _save37
    _shutil.rmtree(_t37, ignore_errors=True)
else:
    print("SKIP  node 없음 — 진행 올리기 접힘 검사 건너뜀")


# ㊱ 미모 셀카 장면 (2026-09-17 성연서님 "노션 AI 셀카를 베이스로" 1·2단계)
#    ① 노션 셀카 30세트에서 뽑은 배경·옷·빛은 looks=attractive 에서만 ② 얼굴 없는 배경 크롭 참조는
#    미모 · 전 컷 · 그 배경일 때만. 한 곳이라도 새면 보통 인물이 인플루언서 사진이 되거나 욕실 컷에 카페가 붙는다.
from bna import refs as _rf36
from bna.planner import plan_batch as _pb36
_NEW36 = {"cafe_window", "terrace_golden", "park_green", "knit_cardigan", "white_blouse", "fitted_black_top", "golden_hour"}
_leak36, _hit36, _refbad36, _refhit36 = [], 0, [], 0
for _s36 in range(4):
    for _p36 in _pb36("selfie", 40, 3600 + _s36, {}, treatment="nasolabial"):
        _lk36 = _p36["looks"]["key"]
        _vals36 = {_p36[a]["key"] for a in ("background", "context", "lighting")}
        if _lk36 != "attractive" and _vals36 & _NEW36:
            _leak36.append((_lk36, sorted(_vals36 & _NEW36)))
        _hit36 += bool(_lk36 == "attractive" and _vals36 & _NEW36)
        _fb36 = _rf36.pick_files("selfie", _p36, treatment="nasolabial")
        _bg36 = [f for f in _fb36 if "attractive_bg" in f]
        _refhit36 += bool(_bg36)
        if _bg36 and (_lk36 != "attractive" or _p36["background"]["key"] not in {"cafe_window", "terrace_golden", "outdoor", "cafe"}):
            _refbad36.append((_lk36, _p36["background"]["key"], _bg36))
        for _w36 in ("immediate", "2w"):
            if any("attractive_bg" in f for f in _rf36.pick_files("selfie", _p36, treatment="nasolabial", when=_w36)):
                _refbad36.append(("after", _w36))
ok(not _leak36 and _hit36 > 0, f"노션 장면 값은 미모 셀카에서만 뽑힌다(보통 누수 0, 미모 적중 {_hit36}) — 누수 {_leak36[:3]}")
ok(not _refbad36 and _refhit36 > 0, f"배경 크롭 참조는 미모·전 컷·맞는 배경에만 붙는다(적중 {_refhit36}) — 위반 {_refbad36[:3]}")
_nob36 = _rf36.pick_files("selfie", {"looks": {"key": "attractive"}, "background": {"key": "bathroom"}}, treatment="nasolabial")
ok(not [f for f in _nob36 if "attractive_bg" in f], f"욕실 컷엔 카페·테라스 크롭이 안 붙는다 — {_nob36}")

# ㊲ 실험 스위치 + '너무 같음' 기록 (2026-09-21 연서님 확인 · 빌디 요청, docs/ai-look-item-0921-teemo.md §8)
#    ① 스위치가 꺼져 있으면 팔자 단발 After 표정은 **절대** 안 바뀐다(기본 경로 불변 — 실험 전 결과를 흔들지 않는다)
#    ② 켜면 표정이 바뀌되 **입 상태는 Before 와 같다**(가짜 효과 방지는 시리즈 완화와 같은 규칙)
#    ③ angle 은 스위치에 안 넣었으면 계속 잠겨 있다(한 회차 한 축) ④ 강도 고정 ⑤ meta 에 켠 스위치가 남는다
#    ⑥ too_similar 는 기록 전용 — 3값이고, 탈락 사유 목록에 들어갈 길이 없다
import os as _os37
from bna.spec import experiment_flags as _ef37
_tb37 = load("variations.yaml").get("expression_traits", {})
def _run37(env):
    for k in ("BNA_EXP_RELAX", "BNA_EXP_SEVERITY", "BNA_EXP_WHEN"):
        _os37.environ.pop(k, None)
    _os37.environ.update(env)
    out = []
    for sd in range(40):
        # 보통 인물로 고정(09-21 미모 프로필 정식 반영) — 미모 컷은 표정이 lock_after 로 잠겨 이 검사의 대상(완화 경로)이 아니다
        v = {**sample_variation("selfie", 3700 + sd), "looks": {"key": "ordinary", "text": ""}}
        r = build_prompts("nasolabial", "selfie", v, 3700 + sd)
        out.append((v, r))
    for k in ("BNA_EXP_RELAX", "BNA_EXP_SEVERITY", "BNA_EXP_WHEN"):
        _os37.environ.pop(k, None)
    return out
_off37 = _run37({})
_on37 = _run37({"BNA_EXP_RELAX": "expression", "BNA_EXP_SEVERITY": "moderate"})
# 2026-09-21 정식 반영(treatments.yaml 팔자 single_relax:[expression]) — 종전 이 줄은 "기본 경로에선 표정이
#   한 번도 안 바뀐다"를 지켰다(실험 결과 전 기본 경로 불변). 결과(§9) 뒤 연서님 OK 로 뒤집었으므로 계약이 바뀐다:
#   ① 기본 경로에서도 표정이 바뀐다 ② 하지만 **강제는 아니다**(주사위 0.7 — 일부는 그대로 남는다)
#   ③ 바뀐 표정도 입 상태는 Before 와 같다(가짜 효과 방지) ④ angle 은 계속 잠긴다.
_offchg37 = [(v, r) for v, r in _off37 if "expression" in r["after_changed_axes"]]
ok(0 < len(_offchg37) < 40, f"정식 경로 — 팔자 단발 표정이 바뀌되 강제는 아니다({len(_offchg37)}/40, 주사위 0.7)")
_offmouth37 = [1 for v, r in _offchg37
               if _tb37.get(v["expression"]["key"], {}).get("mouth") != _tb37.get(r["after_variation"]["expression"]["key"], {}).get("mouth")]
ok(not _offmouth37, f"정식 경로 — 바뀐 표정도 입 상태는 Before 와 같다 — 위반 {len(_offmouth37)}")
ok(all("angle" not in r["after_changed_axes"] for _v, r in _off37), "정식 경로 — angle 은 계속 잠겨 있다(single_relax 에 없다)")
_chg37 = [(v, r) for v, r in _on37 if "expression" in r["after_changed_axes"]]
ok(len(_chg37) >= 10, f"스위치 켬 — 팔자 단발 After 표정이 바뀐다({len(_chg37)}/40, 주사위 0.7 × 이웃 유무)")
_mouth37 = [(v["expression"]["key"], r["after_variation"]["expression"]["key"]) for v, r in _chg37
            if _tb37.get(v["expression"]["key"], {}).get("mouth") != _tb37.get(r["after_variation"]["expression"]["key"], {}).get("mouth")]
ok(not _mouth37, f"스위치 켬 — 바뀐 표정도 입 상태(다문/벌린)는 Before 와 같다 — 위반 {_mouth37[:3]}")
ok(all("angle" not in r["after_changed_axes"] for _v, r in _on37), "스위치 켬 — angle 은 넣지 않았으므로 계속 잠겨 있다(한 회차 한 축)")
# 강도 고정은 **나이 규칙(severity_min_age)을 이기지 않는다** — 20대에 깊은 팔자를 그리면 그 자체가 AI 티다.
#   그래서 실험 회차는 --fix age 로 나이를 같이 고정한다(아래 실행 기록). 테스트도 나이가 허락하는 장만 본다.
_ages37 = list(load("variations.yaml")["age"])
_mina37 = (load("treatments.yaml")["nasolabial"].get("severity_min_age") or {}).get("moderate")
_ok_age37 = [(v, r) for v, r in _on37 if not _mina37 or _ages37.index(v["age"]["key"]) >= _ages37.index(_mina37)]
ok(_ok_age37 and all(r["variation"]["before_severity"]["key"] == "moderate" for _v, r in _ok_age37),
   f"BNA_EXP_SEVERITY=moderate — 나이가 허락하는 {len(_ok_age37)}장 전부 Before 강도가 moderate")
ok(all(r["experiment"] == {"relax": ["expression"], "severity": "moderate", "when": None} for _v, r in _on37)
   and all(r["experiment"] is None for _v, r in _off37), "meta['experiment'] — 켠 회차만 스위치가 남고 끈 회차는 None")
# ㊲-2 (09-21 2차) 시점 고정 + 켠 축은 주사위 건너뛰기. 1차는 시점이 섞이고(직후 2 vs 직후1·2주1)
#   스위치를 켜도 주사위에 빠져 실험 2장 중 1장만 표정이 바뀌어 판정이 안 났다.
_on37b = _run37({"BNA_EXP_RELAX": "expression", "BNA_EXP_SEVERITY": "moderate", "BNA_EXP_WHEN": "2w"})
ok(all(r["afters"][-1]["when"] == "2w" for _v, r in _on37b), "BNA_EXP_WHEN=2w — 40장 전부 단발 시점이 2주")
_chg37b = sum(1 for _v, r in _on37b if "expression" in r["after_changed_axes"])
ok(_chg37b >= 36, f"켠 축은 주사위를 건너뛴다 — 표정 바뀜 {_chg37b}/40 (주사위 0.7 이면 ~28; 남는 건 같은 입 상태 이웃이 없는 경우뿐)")
_off37b = _run37({"BNA_EXP_SEVERITY": "moderate", "BNA_EXP_WHEN": "2w"})
# 정식 반영 뒤 '대조(스위치 없음)'는 더 이상 표정 잠금이 아니다 — 실험 스위치와의 차이는 '강제냐 확률이냐'다.
_offb37 = sum(1 for _v, r in _off37b if "expression" in r["after_changed_axes"])
ok(_offb37 < _chg37b, f"스위치 없는 경로는 실험 스위치보다 덜 바꾼다(확률 {_offb37}/40 < 강제 {_chg37b}/40)")
ok([r["variation"]["age"]["key"] for _v, r in _on37b] == [r["variation"]["age"]["key"] for _v, r in _off37b],
   "스위치 유무가 인물 추첨(rng 흐름)을 바꾸지 않는다 — 같은 seed 면 같은 사람")
from bna.qa import identity as _id37
ok(_id37.TOO_SIMILAR == 0.82 and _id37.TOO_SIMILAR > _id37.THRESHOLD, "too_similar 컷 0.82 는 동일인 하한(0.45) 위에 있다")
import inspect as _in37
from bna import batch as _bt37
_src37 = _in37.getsource(_bt37)
ok("too_similar" not in _src37, "too_similar 는 기록 전용 — batch.py 가 탈락 사유로 읽는 곳이 없다")

# ㊳ (09-21 연서님 "필요하면 팔자에 golden_hour 열자") 팔자 미모 셀카에 늦은 오후 옆빛이 실제로 뽑히는가.
#   존재를 단언한다 — 설정에 적고도 허용표 교집합에서 조용히 빠지는 게 이 레포의 반복 사고다(0921 교훈).
#   ⚠ 보통 인물엔 여전히 0이어야 한다(looks_gates). 테라스 배경은 빛 교집합이 비면 안 된다.
from bna.planner import plan_batch as _pb38
_v38 = _pb38("selfie", 400, 4242, {}, treatment="nasolabial")
_att38 = [v for v in _v38 if v["looks"]["key"] == "attractive"]
_gh38 = sum(v["lighting"]["key"] == "golden_hour" for v in _att38)
ok(_gh38 >= len(_att38) * 0.2, f"팔자 미모 셀카에 golden_hour 가 뽑힌다 — {_gh38}/{len(_att38)}")
ok(not any(v["lighting"]["key"] == "golden_hour" for v in _v38 if v["looks"]["key"] != "attractive"),
   "golden_hour 는 미모 전용 — 보통 인물 0장")
ok(all(v["lighting"]["key"] in ("golden_hour", "backlit") for v in _v38 if v["background"]["key"] == "terrace_golden"),
   "황금빛 테라스 배경은 배경 허용 빛(golden_hour·backlit) 안에서만 뽑힌다 — 창가 빛으로 어긋나지 않는다")

# ㊴ (09-21 빌디 미모 프로필, 연서님 확인) 스위치 BNA_EXP_LOOKS_PROFILE 을 켰을 때만 5가지가 **실제로 나오는가**,
#   끄면 종전 문장 그대로인가. 존재를 단언한다(0921 교훈 — 적고도 조용히 안 먹는 게 반복 사고).
import os
from bna import refs as _rf39
from bna.spec import SKIN_TEXTURE as _st39
def _run39(on):
    # on: True=환경변수 켬 · False=환경변수로 강제 끔("0") · None=스위치 없음(정식 경로 — 설정 enabled 를 따른다)
    os.environ.pop("BNA_EXP_LOOKS_PROFILE", None)
    if on is not None:
        os.environ["BNA_EXP_LOOKS_PROFILE"] = "1" if on else "0"
    try:
        vs = [v for v in _pb38("selfie", 200, 4242, {}, treatment="nasolabial") if v["looks"]["key"] == "attractive"]
        return vs, [build_prompts("nasolabial", "selfie", v, 4242 + i) for i, v in enumerate(vs)], _rf39.face_ref(vs[0], "t", "nasolabial")
    finally:
        os.environ.pop("BNA_EXP_LOOKS_PROFILE", None)
_v39off, _r39off, _f39off = _run39(False)
_v39on, _r39on, _f39on = _run39(True)
ok(all(_st39 in r["before_prompt"] for r in _r39off) and not any("natural makeup" in r["before_prompt"] for r in _r39off)
   and _f39off == [] and all((r["experiment"] or {}).get("looks_profile") is False for r in _r39off),
   "미모 프로필을 강제로 끄면(=되돌리기) 종전 그대로 — 질감 문장 원문·메이크업 없음·외모 참조 없음")
# 정식 반영(09-21 "①~③ OK"): 스위치 없이도 켜지고, meta 실험 칸은 비어 있다(정식 경로라서)
_v39def, _r39def, _f39def = _run39(None)
ok(_r39def and all("natural makeup" in r["before_prompt"] and r["experiment"] is None for r in _r39def) and len(_f39def) == 3,
   "미모 프로필 정식 반영 — 스위치 없이 켜지고 meta 실험 칸은 None")
ok(all("obvious at a glance" in a["after_prompt"] for r in _r39def for a in r["afters"] if a["when"] != "immediate"),
   "미모 프로필 ④ — 미모 컷 After(직후 제외)에 '한눈에 보인다' 한 줄")
# 정식 반영 첫 회귀에서 전역으로 켜져 피부 3종 조명 호가 깨졌다 → 팔자 밖 시술엔 안 먹어야 한다(treatments 범위)
_oth39 = [t for t in load("treatments.yaml") if t != "nasolabial" and "selfie" in load("treatments.yaml")[t].get("modes", [])]
_leak39 = [t for t in _oth39 for i, v in enumerate(_pb38("selfie", 40, 77, {"looks": "attractive"}, treatment=t)[:5])
           if "natural makeup" in build_prompts(t, "selfie", v, 77 + i)["before_prompt"] or _rf39.face_ref(v, "t", t)]
ok(_oth39 and not _leak39, f"미모 프로필은 팔자에만 — 다른 시술 {len(_oth39)}종에 새지 않는다 (샘 {sorted(set(_leak39))})")
# ④ 2차: 미모 전용 moderate — 30대는 moderate + 전용 문장("솔직한 나이" 없음), late_20s 는 나이 하향으로 mild(종전 문장)
_r39m = [r for r in _r39on if r["variation"]["age"]["key"] == "30s"]
ok(_r39m and all(r["variation"]["before_severity"]["key"] == "moderate" and "pretty, well-kept face" in r["before_prompt"]
                 and "honest age" not in r["before_prompt"] for r in _r39m),
   f"프로필 ④(2차) — 미모 30대는 moderate + 전용 문장, '솔직한 나이' 없음 ({len(_r39m)}장)")
ok(all(r["variation"]["before_severity"]["key"] == "mild" for r in _r39on if r["variation"]["age"]["key"] == "late_20s"),
   "프로필 ④(2차) — late_20s 는 팔자 최소 나이 규칙대로 mild 로 내려간다(규칙을 우회하지 않는다)")
_rk39 = [r for r in _r39on if r["variation"]["country"]["key"] == "korea"]
ok(_rk39 and all("Korean beauty look" in r["before_prompt"] for r in _rk39)
   and not any("Korean beauty look" in r["before_prompt"] for r in _r39on if r["variation"]["country"]["key"] != "korea"),
   "프로필(2차) — 한국적 미인상 문장은 한국 인물에만")
ok(not any(v["extras"]["key"].startswith("glasses") for v in _v39on), "프로필(2차) — 미모 인물에 안경 없음")
ok(len(_f39on) == 3 and len({n for _b, n in _f39on}) == 3 and not {n for _b, n in _f39on} & _rf39.BAD_FACE,
   f"프로필 ⑤(2차) — 참조 3장, 서로 다른 장, 손 든 참조 제외 ({[n for _b, n in _f39on]})")
ok(all("natural makeup" in r["before_prompt"] and "minor blemishes" not in r["before_prompt"]
       and "visible pores" in r["before_prompt"] for r in _r39on),
   "프로필 ①② — 메이크업 문장이 붙고, 잡티 문장은 빠지고, 모공·솜털 질감은 남는다")
ok(not any(v["extras"]["key"] == "tired" or v["skin_condition"]["key"] in ("redness", "acne_marks", "oily") for v in _v39on),
   "프로필 ① — 피곤·붉음·여드름 자국·번들 피부가 미모 인물에서 안 뽑힌다")
_lh39 = lambda vs, ax, k: sum(v[ax]["key"] == k for v in vs) / max(1, len(vs))
# ㊵ (09-21 3차 연서님 "미모 Before 는 옆빛·살짝 웃는 표정") — 웃는 Before 에 안 웃는 After 가 오면 가짜 효과다.
#   Before 강제 + After 잠금 + After 문장 교체가 한 벌로 먹는지, 그리고 스위치를 끄면 팔자 웃음 금지가 그대로인지.
_r40 = [r for r in _r39on]
ok(_r40 and all(r["variation"]["expression"]["key"] == "slight_smile" == r["after_variation"]["expression"]["key"] for r in _r40),
   f"프로필 3차 — 미모 Before·After 둘 다 살짝 웃음 ({len(_r40)}장)")
# 09-22 A안(연서님): After 빛은 잠금이 아니라 '옆빛 3종 안에서 Before 와 다른 종류'로 바뀌었다.
_SIDE40 = {"window", "golden_hour", "mixed"}
ok(all(r["variation"]["lighting"]["key"] in ("window", "golden_hour")
       and r["after_variation"]["lighting"]["key"] in _SIDE40 for r in _r40),
   "프로필 3차 — 미모 Before 는 옆빛(창가·늦은 오후), After 도 옆빛 3종 안")
_lchg40 = sum(r["after_variation"]["lighting"]["key"] != r["variation"]["lighting"]["key"] for r in _r40)
ok(_lchg40 >= len(_r40) * 0.9, f"A안 — 미모 After 빛 종류가 실제로 바뀐다 ({_lchg40}/{len(_r40)})")
ok(all(r["after_variation"]["lighting"]["key"] in (_V.get("background_lighting", {}).get(r["after_variation"]["background"]["key"]) or [r["after_variation"]["lighting"]["key"]])
       for r in _r40), "A안 — 바뀐 빛은 After 배경이 낼 수 있는 빛이다")
_m40 = [v for v in _pb38("selfie", 300, 77, {}, treatment="nasolabial") if v["gender"]["key"] == "male"]
ok(len({v["hair_style"]["key"] for v in _m40}) >= 4, f"남성 머리가 여러 가지로 나온다 — {sorted({v['hair_style']['key'] for v in _m40})}")
ok(not any(v["hair_style"]["key"] in ("side_part", "slicked_back", "short_perm", "crop_fringe")
           for v in _pb38("selfie", 300, 77, {}, treatment="nasolabial") if v["gender"]["key"] == "female"), "남성 전용 머리는 여성에게 안 나온다")
ok(all("Do not smile" not in a["after_prompt"] and "same slight closed-mouth smile" in a["after_prompt"]
       for r in _r40 for a in r["afters"]), "프로필 3차 — After 문장이 '웃지 마라'가 아니라 '같은 웃음 그대로'")
ok(not any(r["variation"]["expression"]["key"] == "slight_smile" for r in _r39off),
   "프로필 스위치를 끄면 팔자 Before 에 웃음이 안 뽑힌다(scene_allow 그대로)")
ok(_lh39(_v39on, "framing", "head_to_bust") > _lh39(_v39off, "framing", "head_to_bust"),
   f"프로필 ③ — 머리~바스트 비중이 오른다 ({_lh39(_v39off, 'framing', 'head_to_bust'):.2f}→{_lh39(_v39on, 'framing', 'head_to_bust'):.2f})")
# ㊶ (09-22 빌디 "미모 컷은 크롭이면 안 된다 — full_face·head_to_bust 둘만, 가중이 아니라 게이트")
#   v35 0001 이 가중만 걸린 상태에서 lower_face 로 나갔다. Before·After(직후·2주 이웃 이동 포함) 전부를 잰다.
#   존재도 같이 단언한다 — 둘 다 실제로 나와야 '게이트'지 한쪽으로 쏠린 가중이 아니다.
_F41 = {"full_face", "head_to_bust"}
_r41 = [build_prompts("nasolabial", "selfie", v, 4242 + i, series=["immediate", "2w"]) for i, v in enumerate(_v39on)]
_fr41 = [r["variation"]["framing"]["key"] for r in _r41] + [a["after_variation"]["framing"]["key"] for r in _r41 for a in r["afters"]]
ok(_fr41 and set(_fr41) <= _F41, f"미모 구도 게이트 — Before·After 전부 얼굴 전체·상반신만 ({sorted(set(_fr41))}, {len(_fr41)}컷)")
ok(set(r["variation"]["framing"]["key"] for r in _r41) == _F41, "미모 구도 게이트 — 두 구도가 실제로 둘 다 나온다")
ok(any(v["framing"]["key"] not in _F41 for v in _v39off), "미모 프로필을 끄면 구도 게이트도 풀린다(되돌리기 경로)")
# ㊷ (09-22 연서님 "미모 After 각도 한 칸 풀어서. 표정·빛 잠금은 그대로") — 새 동작이 실제로 나오는가(0 초과)와
#   이웃 한 칸만인가, 잠금 둘은 그대로인가, 보통 인물 각도는 여전히 잠겼는가.
_nb42 = load("variations.yaml")["angle_neighbors"]
_ab42 = [(r["variation"], a["after_variation"]) for r in _r41 for a in r["afters"]]
_mv42 = [(b, a) for b, a in _ab42 if a["angle"]["key"] != b["angle"]["key"]]
ok(0 < len(_mv42) < len(_ab42), f"미모 After 각도가 실제로 바뀐다(강제 아님) — {len(_mv42)}/{len(_ab42)}컷")
ok(all(a["angle"]["key"] in _nb42[b["angle"]["key"]] for b, a in _mv42), "미모 After 각도는 이웃 한 칸만")
ok(all(a["expression"]["key"] == b["expression"]["key"] for b, a in _ab42),
   "미모 After 표정 잠금은 그대로(빛은 09-22 A안으로 옆빛 안에서 바뀐다 — ㊵)")
_ord42 = [v for v in _pb38("selfie", 200, 4242, {}, treatment="nasolabial") if v["looks"]["key"] != "attractive"][:40]
ok(all(a["after_variation"]["angle"]["key"] == v["angle"]["key"]
       for i, v in enumerate(_ord42) for a in build_prompts("nasolabial", "selfie", v, 900 + i)["afters"]),
   "보통 인물 단발 After 각도는 여전히 잠김")
# ㊸ (09-22 연서님 v37 검수 "패치가 AI 합성 느낌·효과 없음") — 미모 단발 컷은 2주만(패치·붓기 직후 컷 제외),
#   보통 인물은 종전대로 직후·1주·2주가 다 나온다(프로필 밖으로 새지 않는다).
_w43 = {r["afters"][-1]["when"] for r in _r39on}
ok(_w43 == {"2w"}, f"미모 단발 컷은 2주만 — {sorted(_w43)} ({len(_r39on)}장)")
_wo43 = {build_prompts("nasolabial", "selfie", v, 900 + i)["afters"][-1]["when"] for i, v in enumerate(_ord42)}
ok({"immediate", "2w"} <= _wo43, f"보통 인물 시점은 그대로 추첨 — {sorted(_wo43)}")
# ㊹ (09-22 연서님 "얼굴만 오려서 넘기고 · 고개 차이 0.015 아래면 '너무 같음' 게이트 · After 각도 후보 넓혀서") —
#   ① 미모 단발 After 각도는 **반드시** 바뀌고 after_angles 안에서만 ② 목록이 이웃 한 칸보다 실제로 넓게 쓰인다
#   ③ 고개만 보는 규칙은 표정이 달라도 고개가 같으면 '너무 같음' ④ 종전 AND 규칙은 그대로 ⑤ 얼굴 못 찾으면 오리지 않는다.
_AA44 = set(load("variations.yaml")["looks_profile"]["attractive"]["after_angles"])
_ab44 = [(r["variation"], r["afters"][-1]["after_variation"]) for r in _r39on]
ok(all(a["angle"]["key"] != b["angle"]["key"] and a["angle"]["key"] in _AA44 for b, a in _ab44),
   f"㊹ 미모 단발 After 각도는 반드시 바뀌고 후보 목록 안 ({len(_ab44)}장)")
_used44 = {a["angle"]["key"] for _b, a in _ab44}
ok(len(_used44) >= 4 and any(a["angle"]["key"] not in _nb42.get(b["angle"]["key"], []) for b, a in _ab44),
   f"㊹ 후보가 이웃 한 칸보다 넓게 쓰인다 — {sorted(_used44)}")
import numpy as _np44
from bna.qa import structure as _st44, landmarks as _lm44
_pb44 = _np44.random.default_rng(44).uniform(100, 900, (478, 2))
_pa44 = _pb44.copy(); _pa44[13] += (0, 40); _pa44[14] -= (0, 40)          # 입만 크게 벌림 — 고개는 그대로
ok(_st44.copy_check(_pb44, _pa44, "selfie", head_only=True)["passed"] is False,
   "㊹ 고개만 보는 규칙 — 표정이 달라도 고개가 같으면 '너무 같음'")
ok(_st44.copy_check(_pb44, _pa44, "selfie")["passed"] is True, "㊹ 종전 AND 규칙(보통 인물)은 그대로 — 표정이 다르면 통과")
from PIL import Image as _Im44
ok(_lm44.face_crop(_Im44.new("RGB", (64, 64)), None) is None, "㊹ 얼굴 못 찾으면 오리지 않는다(종전 통째 참조로 fail-open)")

print()
print(f"{'실패 ' + str(len(fails)) + '건' if fails else '전부 통과'}")
sys.exit(1 if fails else 0)
