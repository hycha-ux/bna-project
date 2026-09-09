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

# ⑧ 동일인 게이트 — '안 재는 것'이 '통과'로 둔갑하지 않는가 (2026-09-08 실측 반영)
from bna.qa import identity
ok(identity.check.__doc__ and "n/a" in identity.check.__doc__, "identity.check 가 3값 게이트여야 한다")
for gate, sim, want_hard, want_passed in [("ok", 0.75, False, True), ("review", 0.50, False, None),
                                          ("fail", 0.20, True, False), ("n/a", None, False, None)]:
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
_s = _les.summarize(_d); _act = _les.active(_d)
ok(_s["tags"].get("손가락") == 3, f"제외 사유가 집계돼야 한다 — 실제 {_s['tags']}")
ok(_act["from_tags"] == ["손가락"], "많이 찍힌 사유가 금지문으로 켜져야 한다")
ok(_act["weights"].get("angle", {}).get("side") == 0.25, "제외가 몰린 조건값은 가중치가 내려가야 한다")
ok(len(_s["notes"]) == 3 and not _act["lines"].get("custom"),
   "자유 메모는 승격 대기로만 남고 자동으로 프롬프트에 들어가지 않는다")
# 채택으로 바꿔도 과거 줄은 안 지운다(전후 비교의 근거라 append-only 여야 한다)
_les.record(_d, "b1", "0000", {"pick": "pick", "tags": [], "note": ""})
ok(len(_les.read(_d)) == 4 and _les.summarize(_d)["rejected"] == 2,
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
        if _r["expression_policy"] == "lock" and "Identical expression" not in _sp["after_prompt"]: _viol[f"{_t} expr_lock"] = _viol.get(f"{_t} expr_lock", 0) + 1
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

print()
print(f"{'실패 ' + str(len(fails)) + '건' if fails else '전부 통과'}")
sys.exit(1 if fails else 0)
