"""변주 샘플링 + 프롬프트 조립. API 키 없이도 동작 (dry-run)."""
import random
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config"


_CACHE = {}


def load(name):
    """config YAML 을 읽는다. 파일 수정 시각으로 캐시한다 — 프롬프트 한 장에 load 가 십수 번 불려
    300장 계획이 분 단위로 걸렸다. 파일을 고치면 mtime 이 바뀌어 바로 다시 읽는다(서버 재시작 불필요)."""
    p = CFG / name
    m = p.stat().st_mtime_ns
    hit = _CACHE.get(name)
    if hit and hit[0] == m:
        return hit[1]
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    _CACHE[name] = (m, data)
    return data


def defaults_for(mode: str) -> dict:
    """모드별 기본 프로바이더. 정본은 config/providers.yaml 의 default_provider 한 곳이다.
    2026-09-08 성연서님 확정: 셀카 = GPT(openai). 코드에 다시 리터럴로 박지 마라."""
    d = load("providers.yaml")["default_provider"]
    if mode not in d:
        raise ValueError(f"providers.yaml default_provider 에 {mode} 가 없다")
    return d[mode]


PERSON_AXES = ["country", "age", "gender", "face_shape", "skin_tone", "skin_condition", "body_type",
               "hair_style", "hair_color", "eyes", "extras"]
SCENE_AXES = ["background", "angle", "framing", "context", "lighting", "color", "quality", "expression"]


def treatment_rules(treatment: str, mode: str) -> dict:
    """시술별 조건 제약 (treatments.yaml 의 구조 필드) → 추첨·드리프트가 같이 쓰는 한 뭉치.
    allow  : {축: 허용값} — 모드 화이트리스트와 교집합 (framing_allow · scene_allow)
    ban    : {축: 금지값} — context_ban
    framing_ban_by_angle · age_weights(0 = 그 나이 안 뽑음) · drift_lock · expression_policy
    framing_weights : 시술별 프레이밍 가중(전역 weights.framing 에 곱한다). 0 은 쓰지 마라 —
                      '안 뽑기'는 framing_allow 가 할 일이고, 여기서 0 을 주면 그 프레이밍이
                      다시 쓸 만해졌는지 확인할 길이 사라진다(age_weights 와 달리 0 을 안 거른다).
    treatment 이 None 이면 빈 규칙 (예전 호출·테스트가 그대로 돈다)."""
    r = {"allow": {}, "ban": {}, "age_weights": {}, "framing_weights": {}, "drift_lock": [],
         "framing_ban_by_angle": {}, "expression_policy": "free"}
    if not treatment:
        return r
    t = load("treatments.yaml").get(treatment)
    if t is None:
        raise ValueError(f"treatments.yaml 에 {treatment} 가 없다")
    r["age_weights"] = {str(k): float(v) for k, v in (t.get("age_weights") or {}).items()}
    r["drift_lock"] = list(t.get("drift_lock") or [])
    r["expression_policy"] = t.get("expression_policy", "free")
    if r["expression_policy"] == "lock" and "expression" not in r["drift_lock"]:
        r["drift_lock"].append("expression")
    if mode == "selfie":                                  # 임상은 리그가 장면을 고정하므로 셀카에만 건다
        if t.get("framing_allow"):
            r["allow"]["framing"] = list(t["framing_allow"])
        for a, ks in (t.get("scene_allow") or {}).items():
            r["allow"][a] = list(ks)
        for a, ks in (t.get("axis_ban") or {}).items():
            r["ban"][a] = list(ks)
        r["framing_ban_by_angle"] = {k: list(v) for k, v in (t.get("framing_ban_by_angle") or {}).items()}
        r["framing_weights"] = {str(k): float(v) for k, v in (t.get("framing_weights") or {}).items()}
    return r


def allowed_values(axis: str, keys: dict, mode: str, v: dict, tr: dict, base=None) -> list:
    """한 축의 허용 목록. 순서대로 거른다:
    모드 화이트리스트(또는 base) → 시술 허용/금지 → 성별 제외 → 나이 0 가중 → 배경×조명 → 각도×프레이밍 → 배경×맥락·프레이밍×맥락.
    keys 는 지금까지 뽑힌 {축: 값키}. 표가 서로 어긋나 빈 목록이 되면 한 단계 전 목록으로 돌아간다(조용히 죽지 않게).
    ⚠ 그 폴백은 config 오류를 숨기므로 selftest 가 실측으로 잡는다."""
    rules = v.get("mode_rules", {}).get(mode, {})
    allowed = list(base) if base else list(rules.get(axis) or list(v[axis]))
    ta = (tr.get("allow") or {}).get(axis)
    if ta:
        allowed = [k for k in allowed if k in ta] or allowed
    tb = (tr.get("ban") or {}).get(axis) or []
    allowed = [k for k in allowed if k not in tb] or allowed
    g = keys.get("gender")
    if g:
        banned = v.get("gender_exclusions", {}).get(g, {}).get(axis, [])
        allowed = [k for k in allowed if k not in banned] or allowed
    if axis == "age":
        zero = {k for k, w in (tr.get("age_weights") or {}).items() if w <= 0}
        allowed = [k for k in allowed if k not in zero] or allowed
    gates = v.get("age_gates", {}).get(axis) or {}
    if gates and keys.get("age"):                     # 그 값이 어울리는 나이에만 (새치는 40대~)
        allowed = [k for k in allowed if keys["age"] in [str(a) for a in gates.get(k, [keys["age"]])]] or allowed
    if axis == "lighting":
        compat = v.get("background_lighting", {}).get(keys.get("background"))
        if compat:
            allowed = [k for k in allowed if k in compat] or allowed
    if axis == "framing":
        fb = (tr.get("framing_ban_by_angle") or {}).get(keys.get("angle")) or []
        allowed = [k for k in allowed if k not in fb] or allowed
    if axis == "context":
        ca = v.get("context_allow", {}).get(keys.get("background"))
        if ca:
            allowed = [k for k in allowed if k in ca] or (["none"] if "none" in v[axis] else allowed)
        fb = v.get("framing_ban", {}).get(keys.get("framing")) or []
        allowed = [k for k in allowed if k not in fb] or (["none"] if "none" in v[axis] else allowed)
        hs = keys.get("hair_style")
        if hs:                                        # 잔머리는 긴 머리에만
            allowed = [k for k in allowed if hs in v.get("context_hair", {}).get(k, [hs])] or (["none"] if "none" in v[axis] else allowed)
    return allowed


def _drop_identity_items(text: str, keywords: list) -> tuple:
    """잠금 문장의 열거 부분(": " 뒤 ~ 첫 ". " 앞)에서 낱말이 든 항목만 뺀다.
    열거 밖 문장(크롭 지시·과장 금지·동일인 확인)은 건드리지 않는다."""
    i = text.find(": ")
    if i < 0:
        return text, 0
    j = text.find(". ", i)
    j = len(text) if j < 0 else j
    items = text[i + 2:j].split(", ")
    kept = [it for it in items if not any(k in it.lower() for k in keywords)]
    if not kept or len(kept) == len(items):
        return text, len(items) - len(kept)
    return text[:i + 2] + ", ".join(kept) + text[j:], len(items) - len(kept)

def person_description(variation: dict) -> str:
    f = {k: variation[k]["text"] for k in PERSON_AXES}
    parts = [f"{f['country']} {f['gender']} {f['age']}", f["face_shape"], f["skin_tone"], f["skin_condition"],
             f["body_type"], f"{f['hair_color']}, {f['hair_style']}", f["eyes"], f["extras"]]
    return ", ".join(p for p in parts if p)


def selfie_scene(f: dict) -> str:
    """셀카 장면 문장: 프레이밍 → 각도 → 배경/맥락 → 빛 → 색/화질 → 표정."""
    ctx = f", {f['context']}" if f.get("context") else ""
    expr = f' {f["expression"].capitalize()}.' if f.get("expression") else ""
    return (f'{f["framing"].capitalize()}. {f["angle"]}, {f["background"]}{ctx}. '
            f'{f["lighting"]}. {f["color"]}. {f["quality"]}.{expr}')


def sample_variation(mode: str, seed=None, weights=None, treatment=None) -> dict:
    """weights: {축: {값: 가중치}} — 제외가 몰린 조건값을 덜 뽑는다(lessons.active 의 weights).
    0 으로 죽이지 않고 낮추기만 하는 이유: 그 조건 자체가 나쁜 게 아니라 지금 모델이 약한 것이고,
    완전히 빼면 다시 좋아졌는지 영영 확인할 수 없다.
    treatment: 시술별 제약(framing_allow·scene_allow·age_weights…)을 건다. None 이면 모드 규칙만."""
    rng = random.Random(seed)
    weights = weights or {}
    v = load("variations.yaml")
    tr = treatment_rules(treatment, mode)
    picked, keys = {}, {}
    for axis in PERSON_AXES + SCENE_AXES:
        options = v[axis]
        allowed = allowed_values(axis, keys, mode, v, tr)
        w = dict(weights.get(axis) or {})
        # ⚠ 전역 가중(variations.yaml 의 weights)과 시술별 가중을 여기서 같이 곱한다.
        #   planner.plan_batch 에도 같은 곱이 있다 — 한쪽만 고치면 배치 추첨과 단건 추첨이
        #   조용히 다른 분포를 낸다(회귀 ⑱-4 가 두 경로를 함께 잰다).
        for k, gw in (v.get("weights", {}).get(axis) or {}).items():
            w[k] = w.get(k, 1.0) * float(gw)
        if axis == "age":                                # 시술별 나이 가중 (0 은 이미 allowed 에서 빠졌다)
            for k, aw in tr.get("age_weights", {}).items():
                if aw > 0:
                    w[k] = w.get(k, 1.0) * aw
        if axis == "framing":                            # 시술별 프레이밍 가중 (목주름은 목만 컷이 필수라 전역값과 다르다)
            for k, fw in tr.get("framing_weights", {}).items():
                w[k] = w.get(k, 1.0) * fw
        if w and len(allowed) > 1:
            ws = [max(0.01, float(w.get(k, 1.0))) for k in allowed]
            key = rng.choices(allowed, weights=ws, k=1)[0]
        else:
            key = rng.choice(allowed)
        picked[axis] = {"key": key, "text": options[key]}; keys[axis] = key
    return picked


def drift_after(variation: dict, mode: str, rng, timeline: str = "2w", treatment=None) -> dict:
    """셀카 모드: After 촬영 상황을 확률적으로 바꾼다 (이목구비 축은 절대 건드리지 않음).
    timeline 이 immediate 면 같은 날(옷·머리 고정), 그 외는 다른 날(옷·머리·배경 대부분 교체).
    treatment 의 drift_lock 축(표정·각도·화질…)은 건너뛴다 — 그 축이 바뀌면 시술이 아니라 촬영 차이가 B&A 로 둔갑한다."""
    v = load("variations.yaml")
    tr = treatment_rules(treatment, mode)
    lock = set(tr.get("drift_lock") or [])
    probs = v.get("after_drift", {}).get(mode, {})
    if "immediate" in probs or "later" in probs:
        probs = probs.get("immediate" if timeline == "immediate" else "later", {})
    override = v.get("after_immediate", {}).get(mode, {}) if timeline == "immediate" else {}
    after = {k: dict(val) for k, val in variation.items()}
    keys = {k: val["key"] for k, val in after.items()}
    for axis, p in probs.items():
        if axis in lock or axis not in v or rng.random() >= p:
            continue
        allowed = allowed_values(axis, keys, mode, v, tr, base=override.get(axis))
        if axis == "angle":                                 # 각도는 이웃 각도로만 (비슷하되 동일하지 않게)
            nb = v.get("angle_neighbors", {}).get(variation["angle"]["key"])
            if nb:
                allowed = [k for k in allowed if k in nb] or allowed
        if axis == "hair_style":                            # 머리는 2주 안에 될 수 있는 모양으로만 (포니테일→삭발 금지)
            nb = v.get("hair_style_neighbors", {}).get(variation["hair_style"]["key"])
            if nb is not None:
                allowed = [k for k in allowed if k in nb]   # 빈 목록이면 안 바뀐다
        opts = [k for k in allowed if k != variation[axis]["key"]]
        if opts:
            k = rng.choice(opts); after[axis] = {"key": k, "text": v[axis][k]}; keys[axis] = k
    # 배경이 바뀌었으면 조명·맥락이 새 배경(과 프레이밍)에 맞는지 마지막으로 한 번 더 확인
    for axis in ("lighting", "context"):
        if axis in lock:
            continue
        ok = allowed_values(axis, keys, mode, v, tr, base=override.get(axis))
        if keys[axis] not in ok:
            k = rng.choice(ok); after[axis] = {"key": k, "text": v[axis][k]}; keys[axis] = k
    return after


def _norm(x: str) -> str:
    return " ".join(str(x).split())


def segments(text: str, spans: list) -> list:
    """프롬프트 문자열을 [{"k": 칸, "t": 문장}] 조각 목록으로. spans = [(칸, 그 칸이 넣은 문장)].
    문장 위치를 찾아 표시하고, 어느 칸에도 안 속한 나머지는 템플릿 고정문(k="template")이다.
    비전공자가 "이 문장은 어디서 왔나"를 화면에서 색으로 읽게 하려는 것 — 프롬프트 자체는 그대로다."""
    text = _norm(text); marks = []
    for k, v in spans:
        v = _norm(v)
        if not v:
            continue
        start = 0
        while True:
            i = text.find(v, start)
            if i < 0:
                break
            if not any(a <= i < b or a < i + len(v) <= b for _, a, b in marks):
                marks.append((k, i, i + len(v))); break
            start = i + 1
    marks.sort(key=lambda m: m[1])
    out, pos = [], 0
    def push(k, t):
        t = t.strip()
        if not t:
            return
        if out and t in (".", ",", ";", ":"):             # 홀로 남은 마침표는 앞 조각에 붙인다
            out[-1]["t"] += t; return
        out.append({"k": k, "t": t})
    for k, a, b in marks:
        if a > pos:
            push("template", text[pos:a])
        push(k, text[a:b]); pos = b
    push("template", text[pos:])
    return out


TIMELINE_ORDER = ["immediate", "1w", "2w", "4w"]


def series_points(treatment: str, series) -> list:
    """요청한 경과 시점을 시술이 허용하는 것만, 시간순으로. 빈 목록이면 시리즈가 아니다."""
    if not series:
        return []
    allowed = load("treatments.yaml")[treatment].get("timeline", ["2w"])
    return [w for w in TIMELINE_ORDER if w in series and w in allowed]


def build_prompts(treatment: str, mode: str, variation: dict, seed=None, avoid=None, series=None) -> dict:
    """avoid: {"before": [...], "after": [...]} — 제외 사유에서 배운 금지문(lessons.active).
    None 이면 붙이지 않는다(dry-run·테스트가 과거와 같은 문장을 내게)."""
    from . import lessons
    av = avoid or {}
    avoid_before = lessons.avoid_text(av.get("before") or [])
    avoid_after = lessons.avoid_text(av.get("after") or [])
    t = load("treatments.yaml")[treatment]
    if mode not in t["modes"]:
        raise ValueError(f"{treatment} does not support mode {mode}")
    rng = random.Random(seed)
    mode_extra = load("prompts/mode_extra.yaml")[mode].strip()
    if "expression" not in variation:                # 예전 계획(표정 축 없던 시절)도 조립되게
        ek = "neutral_closed"; variation = {**variation, "expression": {"key": ek, "text": load("variations.yaml")["expression"][ek]}}
    tr = treatment_rules(treatment, mode)
    fields = {k: v["text"] for k, v in variation.items()}
    if mode == "clinical":
        rig = load("clinical_rig.yaml")
        r = rig["rig_default"]
        angle = rig["angles"].get({"front": "front", "three_quarter": "oblique_45", "side": "side"}.get(variation["angle"]["key"], "front"))
        scene = ". ".join([angle, r["camera"], r["distance"], r["lighting"], r["background"], r["subject_setup"], r["processing"]]) + "."
    else:
        scene = selfie_scene(fields)
    sevs = t.get("before_severity", ["moderate"])
    sev = rng.choice(sevs)
    min_age = t.get("severity_min_age", {})
    if min_age:                                   # 인물 나이가 강도 최소 나이보다 어리면 한 단계씩 낮춤
        order = list(load("variations.yaml")["age"])
        age_i = order.index(variation["age"]["key"])
        while sev in min_age and age_i < order.index(min_age[sev]) and sevs.index(sev) > 0:
            sev = sevs[sevs.index(sev) - 1]
    cond = t.get("before_condition", {})
    cond = cond.get(sev, "") if isinstance(cond, dict) else cond
    before = (CFG / "prompts/before.md").read_text(encoding="utf-8").format(
        person=person_description(variation), before_condition=str(cond).strip(), scene=scene, mode_extra=mode_extra, avoid=avoid_before, **fields)
    def identity_for(ref_framing, target_framing=None):
        """동일인 잠금 문장.
        - 항목 목록은 Before·After 중 **좁은 쪽** 파일에서 온다 (레퍼런스에 없는 걸 요구하면 모델이 지어낸다).
        - `CROP:` 줄(크롭 지시)은 **생성할 사진**이 좁을 때만 남긴다 — 좁은 Before + 넓은 After 에
          "눈을 프레임 안으로 들이지 마라"가 붙으면 같은 프롬프트의 장면문("얼굴 전체")과 정면 충돌한다
          (2026-09-09 티모 실측 360건 중 36건, 10%).
        - `identity_exempt` 는 **낱말**이다(문구 아님). 잠금 파일 3벌이 서로 다른 표현을 쓰므로
          문구를 그대로 지우면 한 파일에서만 먹고 나머지에선 조용히 아무 일도 안 한다
          (0909 실측: 리프팅 82/120·인중 79/120 에서 시술 부위가 잠긴 채 남았다)."""
        vv = load("variations.yaml"); order = vv.get("identity_lock_order") or []; table = vv.get("identity_lock_by_framing") or {}
        target_framing = target_framing or ref_framing
        def narrowness(f):
            if f not in order:                       # 표에 없는 프레이밍은 '가장 좁음'으로 본다 —
                return len(order)                    # 넓은 쪽으로 폴백하면 얼굴을 프레임 안으로 끌고 온다
            return order.index(f)
        def _read(f):
            return (CFG / "prompts" / table.get(f, "identity_lock.md")).read_text(encoding="utf-8").strip()
        fr = max([ref_framing, target_framing], key=narrowness)
        lines = [ln for ln in _read(fr).splitlines() if not ln.startswith("CROP:")]
        crop = next((ln for ln in _read(target_framing).splitlines() if ln.startswith("CROP:")), None)
        if crop:                                 # 크롭 지시는 **생성할 사진**의 프레이밍 것으로 (항목 목록과 출처가 다르다)
            lines.insert(1, crop)
        text = " ".join(" ".join(lines).replace("CROP:", "").split())
        ex = [str(k).lower() for k in (t.get("identity_exempt") or [])]
        if ex:                                       # 시술 부위 항목을 잠금 목록에서 뺀다
            text, dropped = _drop_identity_items(text, ex)
            if not dropped:                          # 조용한 무효화가 이 규칙의 실패 모드였다 — 소리 내고 죽는다
                raise ValueError(f"identity_exempt {ex} 가 {table.get(fr)} 에서 아무 항목도 못 지웠다")
        if t.get("identity_note"):
            text += " " + " ".join(str(t["identity_note"]).split())
        return text
    identity = identity_for(variation["framing"]["key"])
    eff = load("effects.yaml")
    # Before 강도 ↔ After 효과 짝 (mild+눈에 띄게 = 과장, marked+은은 = 효과 없음). 나이 하향 **뒤**의 sev 로 뽑는다
    levels = (t.get("effect_by_severity") or {}).get(sev) or t.get("effect_levels", ["moderate"])
    level = rng.choice(list(levels))
    pts = series_points(treatment, series)               # 경과 시리즈(직후·2주…)면 시점 목록, 아니면 빈 목록
    when = pts[-1] if pts else rng.choice(t.get("timeline", ["2w"]))

    def change_for(w, final_level):
        """시점 하나의 시술 지시문. 시리즈면 최종 강도를 시점에 맞춰 낮춘다(직후 = 거의 안 보임 + 붓기).

        `lowered` 를 같이 돌려주는 이유(2026-09-11): 검수의 `effect_visible` 은 "변화가 눈에 띄나"를
        묻는데, 여기서 강도를 낮춘 컷은 **안 띄는 게 정상**이라 같은 자로 재면 지시대로 그릴수록
        떨어진다. 그 판정을 검수 쪽에서 다시 계산하면 규칙이 두 벌이 되어 조용히 갈리므로,
        **낮췄다는 사실을 만든 자리에서 그대로 실어 보낸다**(배치가 이걸 읽어 그 항목을 안 건다).
        """
        lv = final_level
        lowered = False
        if pts:
            sl = (eff.get("series_levels") or {}).get(w, "final")
            lowered = sl != "final"
            lv = final_level if sl == "final" else sl
        c = f'{t["after_change"].strip()} {eff["effect_levels"][lv]}.'
        if t.get("must_not_change"):
            c += " " + " ".join(str(t["must_not_change"]).split())
        if mode == "selfie":
            c += f' {eff["timeline"][w].capitalize()}.'
        return c, lv, lowered

    change, _lv, _low = change_for(when, level)
    variation = {**variation, "before_severity": {"key": sev, "text": str(cond).strip()},
                 "effect_level": {"key": level, "text": eff["effect_levels"][level]},
                 "timeline": {"key": when, "text": eff["timeline"][when]}}
    mx = load("prompts/mode_extra.yaml")

    def build_after(w, chg, lv, lowered):
        """시점 하나의 After. 시리즈든 아니든 같은 길 — 동일인 기준은 항상 Before 사진이다(After 를 다음 After 의 기준으로 쓰면 얼굴이 흘러간다)."""
        if mode == "clinical":
            a_var = variation
            txt = (CFG / "prompts/after_clinical.md").read_text(encoding="utf-8").format(identity_lock=identity, after_change=chg, avoid=avoid_after)
            spans = [("identity", identity), ("change", t["after_change"]), ("effect", eff["effect_levels"][lv]),
                     ("must_not", t.get("must_not_change") or ""), ("avoid", avoid_after)]
        else:
            a_var = drift_after(variation, mode, rng, timeline=w, treatment=treatment)
            a = {k: val["text"] for k, val in a_var.items()}
            ident = identity_for(variation["framing"]["key"], a_var["framing"]["key"])
            a_scene = dict(a); a_scene.pop("expression", None)          # 표정은 아래 expression_line 이 맡는다
            after_scene = selfie_scene(a_scene)
            after_hair = f'{a["hair_color"]}, {a["hair_style"]}' + (f', {a["extras"]}' if a["extras"] else "")
            if tr.get("expression_policy") == "lock":
                # ⚠ "must not change at all" 은 표정만이 아니라 얼굴 전체를 복사시켰다
                #   (2026-09-10 성연서님 "동일한 각도, 구도, 표정" 2장 — 이목구비·눈 뜬 정도까지 동일 = AI 티).
                #   잠글 것은 '웃음'이지 '사람'이 아니다 → 금지는 표정 하나로 좁히고,
                #   손으로 다시 찍었을 때 반드시 생기는 미세 차이는 **명시적으로 요구**한다.
                #   이 문장은 drift_lock 에 angle 이 들어간 시술(팔자·리프팅)에서 특히 중요하다 —
                #   각도 축이 잠기면 각도 문장까지 같아져 "같은 사진 복사"로 떨어진다.
                expression_line = (
                    f'The expression is the same as in the reference: {variation["expression"]["text"]}. '
                    'Do not smile and do not tense the mouth or cheeks, since that alone would change the '
                    'folds being treated. Everything else is a separate handheld photo and must show the small '
                    'differences that always occur: the head tilts a degree or two differently, the eyes are '
                    'open a little more or a little less, the lips rest with slightly different tension, and the '
                    'face sits in a slightly different place in the frame. This is a second photo of the same '
                    'person, not the reference photo edited.')
            else:
                expression_line = f'Expression: {a["expression"]}; it may differ slightly from the reference.'
            which = "same" if w == "immediate" else "different"
            txt = (CFG / "prompts/after_selfie.md").read_text(encoding="utf-8").format(
                identity_lock=ident, after_scene=after_scene, after_hair=after_hair, after_change=chg,
                expression_line=expression_line, mode_extra=str(mx.get("selfie_after", "")).strip(),
                after_day=mx["after_day"][which].strip(), skin_state=mx["skin_state"][which].strip(), avoid=avoid_after)
            spans = [("identity", ident), ("change", t["after_change"]), ("effect", eff["effect_levels"][lv]),
                     ("must_not", t.get("must_not_change") or ""), ("avoid", avoid_after),
                     ("day", mx["after_day"][which]), ("scene", after_scene), ("scene", f"Hair: {after_hair}."), ("expression", expression_line),
                     ("skin", mx["skin_state"][which]), ("timeline", eff["timeline"][w].capitalize()), ("mode_extra", mx.get("selfie_after", ""))]
        return {"when": w, "effect_level": lv, "effect_lowered": lowered,
                "after_prompt": " ".join(txt.split()), "after_variation": a_var,
                "after_changed_axes": [k for k in a_var if a_var[k]["key"] != variation[k]["key"]], "after_parts": segments(txt, spans)}

    afters = []
    for w in (pts or [when]):
        chg, lv, lowered = change_for(w, level)
        afters.append(build_after(w, chg, lv, lowered))
    last = afters[-1]
    before_parts = segments(before, [("person", person_description(variation)), ("before_condition", cond), ("scene", scene),
                                     ("mode_extra", mode_extra), ("avoid", avoid_before)])
    return {"avoid_applied": {k: v for k, v in (avoid or {}).items() if v},
            "before_parts": before_parts, "after_parts": last["after_parts"],
            "treatment": treatment, "mode": mode, "aspect": load("variations.yaml").get("output", {}).get("aspect", "4:5"),
            "variation": variation, "after_variation": last["after_variation"],
            "after_changed_axes": last["after_changed_axes"], "generation": "edit" if mode == "clinical" else "identity_reference",
            "series": pts or None, "afters": afters,          # 시리즈면 시점별 After 목록(배치·화면이 이걸 돈다). after_* 는 마지막 시점
            "before_prompt": " ".join(before.split()), "after_prompt": last["after_prompt"]}
