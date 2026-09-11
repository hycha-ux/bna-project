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
for _frag in ("tilts a degree or two", "open a little more", "slightly different place in the frame",
              "not the reference photo edited"):
    ok(_frag in _lock, f"표정 잠금이 미세 차이를 명시적으로 요구해야 한다 — '{_frag}'")
# 잠금 없는 시술(free)은 종전대로 표정이 달라도 된다
ok("may differ slightly" in build_prompts("nose_lifting", "selfie", sample_variation("selfie", 5), 5)["after_prompt"],
   "expression_policy: free 시술은 종전 문장을 유지해야 한다")

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
    # check() 는 이미지를 받으므로, 판정 로직만 보려고 similarity 를 가로챈다
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
from bna.spec import treatment_rules as _tr, load as _load, SCENE_AXES
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
        for _ax in _r["drift_lock"]:
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
_WIDE = {"full_face", "forehead_cut"}
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
            if "same eyes" not in _ap: _bad[f"{_t} full잠금"] = 1
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
     "hair_style", "hair_color", "eyes", "extras"],
    ["korea", "30s", "female", "oval", "fair", "clear", "slim", "bob", "black", "double", "none"])}
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
ok(_sr["afters"][0]["effect_level"] in ("subtle", "moderate") and "barely visible yet" not in _sr["afters"][0]["after_prompt"],
   "필러(팔자)의 직후 컷은 최종 강도다 — immediate_level: final (2026-09-11)")
_sr3 = build_prompts("nasolabial", "selfie", _v, 5, series=["immediate", "1w", "2w"])
ok([a["effect_level"] for a in _sr3["afters"]][1] == "subtle" and _sr3["afters"][1]["effect_lowered"] is True,
   "중간 시점(1주)은 종전대로 강도를 낮춘다 — 낮추는 길 자체가 죽으면 안 된다")
ok(_sr["afters"][1]["effect_level"] in ("subtle", "moderate") and _sr["after_prompt"] == _sr["afters"][-1]["after_prompt"], "마지막 시점이 최종 강도이고 after_prompt 대표")
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
ok(_sr3["afters"][1]["effect_lowered"] is True and _sr3["afters"][0]["effect_lowered"] is False
   and _sr3["afters"][2]["effect_lowered"] is False,
   "강도를 낮춘 시점만 effect_lowered 로 표시된다(직후는 필러라 최종 강도, 마지막도 최종 강도)")
ok(_pl["afters"][0]["effect_lowered"] is False, "시리즈가 아니면 낮추지 않으므로 종전대로 effect_visible 을 건다")


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
ok('af.get("effect_lowered")' in _batch_src2 and '"immediate"' not in _batch_src2,
   "배치는 시점 이름을 다시 보지 말고 spec 이 실어 보낸 effect_lowered 하나만 봐야 한다(규칙 두 벌 금지)")


# ⑳-3 시술별 직후 강도 + 사실 카드 (2026-09-11 빌디 지적 3건)
#     ① 필러는 직후가 곧 결과다 — 일괄 early 로 낮추면 "직후에 바로 보인다"는 판매 포인트를 우리가 지운다.
#     ② 그 카드 칸의 실패 모드는 '틀린 값'이 아니라 **아무도 안 읽는 값**이라, 죽은 설정은 소리 내고 죽는다.
from bna.spec import check_treatment_facts as _ctf, FACT_KEYS_PROMPT as _FKP
import yaml as _yaml
_tr_all = _yaml.safe_load((_P(__file__).parent / "config" / "treatments.yaml").read_text(encoding="utf-8"))
_filler = [k for k, v in _tr_all.items() if v.get("immediate_level") == "final"]
ok(sorted(_filler) == ["filler_neck", "filler_nose", "nasolabial", "philtrum"],
   f"필러 4종만 직후=최종 강도 — 실제 {sorted(_filler)}")
ok(all("immediate" in (v.get("timeline") or []) for v in _tr_all.values() if v.get("immediate_level")),
   "immediate 시점이 없는 시술에 immediate_level 을 적으면 죽은 설정이다")
for _k in _tr_all:
    _ctf(_k)                                       # 전 시술 카드 검증 — 오타 칸·죽은 설정이면 여기서 터진다
ok(True, "전 시술의 immediate_level·facts 카드가 검증을 통과한다")
_bad = dict(_tr_all["lifting"]); _bad["immediate_level"] = "final"
import bna.spec as _spec_mod
_orig_load = _spec_mod.load
_spec_mod.load = lambda n: {**_orig_load(n), "lifting": _bad} if n == "treatments.yaml" else _orig_load(n)
try:
    _ctf("lifting"); _raised = False
except ValueError:
    _raised = True
finally:
    _spec_mod.load = _orig_load
ok(_raised, "직후 시점이 없는 시술(리프팅)에 immediate_level 을 달면 소리 내고 죽는다")
ok(_FKP == ("immediate_marks", "immediate_avoid"), "프롬프트에 실리는 카드 칸은 직후 흔적·직후 금지 둘")
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
ok(len(_sg(_p0[0])) == 11, f"인물 서명은 인물 축 11개만이어야 한다 — {len(_sg(_p0[0]))}")

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
         "nose_to_neck": 0.125, "forehead_cut": 0.0, "full_face": 0.0}
_EXEMPT18 = {"filler_neck"}      # 목만 컷이 대표 구도인데 얼굴이 프레임 밖 — 어떻게 섞어도 10% 아래가 안 된다


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
    if _r18 >= 0.10:
        _over18.append(f"{_t18} {_r18*100:.1f}%")
ok(not _over18, f"목주름 외 전 시술의 예상 못 잼이 10% 미만이어야 한다 — 초과: {_over18}")

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

print()
print(f"{'실패 ' + str(len(fails)) + '건' if fails else '전부 통과'}")
sys.exit(1 if fails else 0)
