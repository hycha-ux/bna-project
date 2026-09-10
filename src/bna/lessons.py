"""제외 사유 → 다음 생성 프롬프트 (2026-09-08 성연서님 지시 "재발하지 않는 구조").

되먹임 고리는 네 칸이다. 어느 한 칸이 빠지면 학습이 아니라 그냥 기록이다.

  ①쌓기   제외를 누를 때마다 사유·조건·메모를 `outputs/lessons.jsonl` 에 한 줄 붙인다
          (append-only — 판정을 바꿔도 과거 줄은 안 지운다. 지우면 전후 비교를 못 한다).
  ②고르기 최근 창에서 실제로 많이 찍힌 사유 상위 N개만 고른다.
          전부 붙이지 않는 이유 = `config/prompts/avoid.yaml` 머리말.
  ③붙이기 `spec.build_prompts` 가 그 금지문을 `{avoid}` 자리에 넣는다.
          겸해 제외가 몰린 조건값(예: 옆모습·욕실 거울)은 추첨 확률을 낮춘다 —
          문장으로 "하지 마"라고 하는 것보다 그 상황을 안 만드는 쪽이 확실하다.
  ④재기   규칙마다 도입 시각이 있어, 도입 전/후 그 사유의 제외율을 갈라 잰다.
          안 떨어지면 문장이 약한 것이고, 그때 축 회피로 올린다.

⚠ 자유 메모는 자동으로 프롬프트에 안 들어간다. 사람이 영어 한 문장으로 다듬어
  「규칙으로 승격」을 눌러야 산다(오타·모순·환자 정보·프롬프트 인젝션 차단).
"""
import json
import time
from pathlib import Path

import yaml

LEDGER = "lessons.jsonl"


def _cfg():
    from .spec import CFG
    p = CFG / "prompts" / "avoid.yaml"
    if not p.exists():
        return {"settings": {}, "tags": {}, "custom": []}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def record(out_dir: Path, batch: str, item: str, rv: dict) -> None:
    """검수 한 건을 원장에 붙인다. 실패해도 검수를 막지 않는다(fail-open).

    ⚠ 제외뿐 아니라 **모든 판정**을 적는다. 제외만 적으면 나중에 채택으로 바꿔도
      원장엔 제외가 마지막 줄로 남아, 이미 고친 실수를 계속 금지문으로 붙인다.
    """
    try:
        meta = json.loads((out_dir / batch / item / "meta.json").read_text(encoding="utf-8"))
    except Exception:                                   # noqa: BLE001
        meta = {}
    row = {
        "at": time.time(), "batch": batch, "item": item, "pick": rv.get("pick"),
        "tags": rv.get("tags", []), "note": (rv.get("note") or "").strip(),
        "treatment": meta.get("treatment"), "mode": meta.get("mode"),
        "prompt_version": meta.get("prompt_version"),
        "axes": {k: v.get("key") for k, v in (meta.get("variation") or {}).items() if isinstance(v, dict)},
    }
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / LEDGER).open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:                                   # noqa: BLE001
        pass


def read(out_dir: Path) -> list:
    p = out_dir / LEDGER
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:                               # noqa: BLE001
            continue                                    # 깨진 한 줄이 원장 전체를 죽이지 않는다
    return rows


def _latest(rows: list) -> dict:
    """아이템별 마지막 판정만 남긴다 — 눌렀다 지웠다 한 걸 여러 번 세지 않기 위해."""
    last = {}
    for r in rows:
        last[f'{r.get("batch")}/{r.get("item")}'] = r
    return last


# 자유 메모 → 영어 금지문 제안. 같은 메모가 반복되면 사람이 매번 영작하지 않도록 (2026-09-10 성연서님 "문구 제안·병합").
# 키워드가 메모에 들어 있으면 그 문장을 미리 채운다. 사람이 고쳐서 승격하니 초안이지 정본이 아니다.
# ⚠ config/ 가 아니라 여기 두는 이유: config 를 건드리면 프롬프트 버전이 바뀐다. 이 표는 프롬프트에 직접 안 들어간다.
NOTE_SUGGEST = [
    (("마취", "마취크림", "거즈", "테이프", "밴드", "패치"),
     "no numbing cream, gauze, tape, patches or any clinic dressing visible on the skin"),
    (("바늘", "주사기", "시린지", "니들"), "no needles, syringes or injection equipment anywhere in the frame"),
    (("붓기", "부기", "멍", "붉", "홍조"), "no swelling, bruising or redness beyond what the stated time point allows"),
    (("손", "손가락"), "no hands, fingers, arms or phone anywhere in the frame"),
    (("머리", "머리카락", "헤어"), "render individual hair strands with a natural hairline; no melted, clumped or painted-on hair"),
    (("치아", "이빨", "잇몸"), "teeth must be natural and correctly counted; no extra, merged or overly white teeth"),
    (("눈동자", "눈", "시선"), "eyes must be symmetric with natural irises and a consistent gaze between the two photos"),
    (("배경", "장면", "소품", "물건"), "the setting, clothing and props must be consistent and physically plausible; no floating or duplicated objects"),
    (("거울", "반사"), "mirror reflections must match the subject exactly; no second face or mismatched reflection"),
    (("옷", "의상", "귀걸이", "악세", "액세"), "clothing and accessories must stay identical between the two photos"),
    (("피부", "질감", "모공", "플라스틱"), "keep real skin micro-texture: visible pores, faint peach fuzz, uneven tone; no airbrushed or plastic skin"),
    (("다른 사람", "동일인", "딴사람", "얼굴이 바"), "the person must remain unmistakably the same individual as the reference: same bone structure, eye shape, nose width, lip shape and moles"),
    (("과함", "과해", "너무 많이", "티가 많이"), "the treatment change must stay subtle and clinically plausible; do not exaggerate the result"),
    (("효과 없", "차이 없", "변화 없"), "the treatment change must be clearly visible when the two photos are compared side by side"),
    (("각도", "포즈", "고개"), "head angle and camera height must match the stated framing; do not drift to a different pose"),
    (("텍스트", "글자", "워터마크", "로고"), "no text, captions, logos or watermarks anywhere in the image"),
    (("어색", "부자연", "AI", "그림 같"), "must look like an ordinary phone snapshot, not a rendered or illustrated image; no glossy CGI sheen, no perfect symmetry"),
]


def suggest_en(note: str, tags=None) -> str:
    """메모(한글) → 영어 금지문 초안. 키워드 표 우선, 없으면 같이 찍힌 사유 버튼의 문장, 그것도 없으면 빈 문자열."""
    n = (note or "").replace(" ", "")
    for keys, en in NOTE_SUGGEST:
        if any(k.replace(" ", "") in n for k in keys):
            return en
    tag_cfg = (_cfg().get("tags") or {})
    for t in tags or []:
        if (tag_cfg.get(t) or {}).get("en"):
            return tag_cfg[t]["en"]
    return ""


def _norm(note: str) -> str:
    """병합 키 — 띄어쓰기·문장부호·대소문자 차이는 같은 메모로 본다."""
    import re
    return re.sub(r"[\s\.\,\!\?~\-_/·]+", "", (note or "")).lower()


def summarize(out_dir: Path, treatment=None, mode=None) -> dict:
    """사유별·조건별 제외 집계 + 승격 대기 메모. 화면과 프롬프트가 같은 함수를 쓴다."""
    cfg = _cfg()
    st = cfg.get("settings") or {}
    win = float(st.get("window_days", 14)) * 86400
    now = time.time()
    judged = [r for r in _latest(read(out_dir)).values()
              if r.get("pick") in ("pick", "reject")
              and (treatment is None or r.get("treatment") == treatment)
              and (mode is None or r.get("mode") == mode)]
    rows = [r for r in judged if r.get("pick") == "reject"]
    recent = [r for r in rows if now - r.get("at", 0) <= win]
    # 축 회피의 분모. **제외 건수만 세면 많이 쓴 조건값이 무조건 나쁜 값이 된다** —
    # 2026-09-10 실사고: 한국인으로 27세트를 돌렸더니 country=korea 가 제외 10건으로 잡혀
    # 추첨 가중치 0.25 로 눌렸고, 한 번도 안 써 본 일본·동남아가 상대적으로 4배 유리해졌다.
    # 그래서 '한국인만' 시킨 회차에서 일본인·동남아인이 나왔다. 비율로 재야 한다.
    uses = {}
    for r in [x for x in judged if now - x.get("at", 0) <= win]:
        for a, k in (r.get("axes") or {}).items():
            if k:
                uses.setdefault(a, {}).setdefault(k, 0)
                uses[a][k] += 1
    tags, axes, notes = {}, {}, []
    for r in recent:
        for t in r.get("tags", []):
            tags[t] = tags.get(t, 0) + 1
        for a, k in (r.get("axes") or {}).items():
            if k:
                axes.setdefault(a, {}).setdefault(k, 0)
                axes[a][k] += 1
        if r.get("note"):
            notes.append({"note": r["note"], "at": r["at"], "batch": r["batch"], "item": r["item"],
                          "tags": r.get("tags", []), "treatment": r.get("treatment")})
    # 같은 메모는 한 줄로 병합 + 영어 초안. 이미 승격된 메모(custom.from)는 목록에서 뺀다 — 안 빼면 같은 메모를 또 올린다.
    promoted = {_norm((c or {}).get("from", "")) for c in (cfg.get("custom") or [])} - {""}
    groups = {}
    for n in notes:
        k = _norm(n["note"])
        if not k or k in promoted:
            continue
        g = groups.setdefault(k, {"note": n["note"], "count": 0, "at": 0, "items": [], "tags": {}, "treatments": {}})
        g["count"] += 1; g["at"] = max(g["at"], n["at"])
        g["items"].append({"batch": n["batch"], "item": n["item"], "at": n["at"]})
        for t in n.get("tags", []):
            g["tags"][t] = g["tags"].get(t, 0) + 1
        if n.get("treatment"):
            g["treatments"][n["treatment"]] = g["treatments"].get(n["treatment"], 0) + 1
    merged = []
    for g in groups.values():
        g["tags"] = [t for t, _ in sorted(g["tags"].items(), key=lambda kv: -kv[1])]
        g["items"].sort(key=lambda x: x["at"], reverse=True)
        g["suggest_en"] = suggest_en(g["note"], g["tags"])
        merged.append(g)
    merged.sort(key=lambda g: (-g["count"], -g["at"]))
    judged_recent = [x for x in judged if now - x.get("at", 0) <= win]
    return {"window_days": st.get("window_days", 14), "rejected": len(recent), "rejected_all": len(rows),
            "judged": len(judged_recent), "axis_uses": uses,
            "tags": dict(sorted(tags.items(), key=lambda kv: -kv[1])), "axes": axes, "notes": merged[:50],
            "custom": cfg.get("custom") or []}


def active(out_dir: Path, treatment=None, mode=None) -> dict:
    """지금 프롬프트에 붙일 금지문 + 낮출 조건값. build_prompts 가 이걸 부른다."""
    cfg = _cfg()
    st = cfg.get("settings") or {}
    s = summarize(out_dir, treatment, mode)
    tag_cfg = cfg.get("tags") or {}
    picked = [(t, n) for t, n in s["tags"].items()
              if n >= int(st.get("min_count", 2)) and t in tag_cfg][: int(st.get("top_n", 3))]
    lines = {"before": [], "after": []}
    for t, _n in picked:
        c = tag_cfg[t]
        for w in c.get("where", ["before", "after"]):
            if c.get("en"):
                lines[w].append(c["en"])
    for c in cfg.get("custom") or []:                   # 사람이 승격시킨 규칙은 항상 붙는다
        for w in c.get("where", ["after"]):
            if c.get("en") and c["en"] not in lines.get(w, []):
                lines.setdefault(w, []).append(c["en"])
    # 축 회피: 그 조건값이 **평균보다 유난히 잘 떨어질 때만** 추첨 가중치를 낮춘다.
    #
    # ⚠ 종전엔 제외 '건수'만 봤다. 그러면 많이 쓴 값이 자동으로 나쁜 값이 된다 — 분모가 없으니까.
    #   2026-09-10 실사고: 한국인으로만 27세트를 돌린 뒤 country=korea 가 0.25 로 눌렸고,
    #   한 번도 안 써 본 일본·동남아는 1.0 이라 4배 유리해졌다. 그래서 '한국인 고정' 회차에서
    #   일본인·동남아인이 나왔다. 학습이 안 된 게 아니라 **거꾸로 배운 것**이다.
    #   지금은 그 값의 제외율이 전체 제외율보다 `axis_rate_margin` 배 높을 때만 누른다.
    amin = int(st.get("axis_min_count", 3))
    aw = float(st.get("axis_weight", 0.25))
    margin = float(st.get("axis_rate_margin", 1.3))
    base = (s["rejected"] / s["judged"]) if s.get("judged") else 0.0
    weights = {}
    for a, vals in s["axes"].items():
        hit = {}
        for k, n in vals.items():
            used = (s.get("axis_uses", {}).get(a) or {}).get(k, 0)
            if used < amin or not base:
                continue                            # 표본이 적으면 조건을 죽이지 않는다
            if (n / used) >= base * margin:
                hit[k] = aw
        # 그 축에서 **써 본 값이 전부** 걸리면 아무것도 안 누른 것과 같다(상대 확률이 그대로다) → 축째로 뺀다.
        # 비교 대상은 제외된 값 목록(vals)이 아니라 실제 사용된 값 목록이다 —
        # vals 로 재면 "제외가 한 값에만 몰린" 정상 상황까지 통째로 빠진다.
        used_vals = s.get("axis_uses", {}).get(a) or {}
        if hit and len(hit) < max(len(used_vals), 1):
            weights[a] = hit
    return {"lines": lines, "weights": weights, "from_tags": [t for t, _ in picked], "rejected": s["rejected"],
            "reject_rate": base}


def avoid_text(lines: list) -> str:
    """프롬프트에 넣을 한 줄. 규칙이 없으면 빈 문자열(빈 문장을 넣지 않는다)."""
    return ("Avoid the mistakes seen in earlier rejected results: " + " ".join(
        s if s.endswith('.') else s + '.' for s in lines)) if lines else ""


def promote(note: str, en: str, where=None) -> dict:
    """메모 한 줄을 규칙으로 승격. avoid.yaml 의 custom 에 붙는다(사람 확인 후에만)."""
    from .spec import CFG
    p = CFG / "prompts" / "avoid.yaml"
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    rule = {"en": en.strip(), "where": where or ["after"], "from": (note or "").strip(),
            "since": time.strftime("%Y-%m-%d")}
    cfg.setdefault("custom", [])
    if any((c or {}).get("en") == rule["en"] for c in cfg["custom"]):
        return {"ok": False, "error": "같은 규칙이 이미 있습니다"}
    cfg["custom"].append(rule)
    # 머리말 주석은 정본이라 지우지 않는다 — 본문만 다시 쓰고 주석 블록은 그대로 앞에 붙인다
    src = p.read_text(encoding="utf-8")
    head = src.split("\nsettings:")[0]
    body = yaml.safe_dump({k: cfg[k] for k in ("settings", "tags", "custom") if k in cfg},
                          allow_unicode=True, sort_keys=False, width=200)
    p.write_text(head + "\n" + body, encoding="utf-8")
    # 규칙을 넣으면 버전(설정 해시)이 바뀐다 — 새 버전에 "왜 바뀌었나"를 메모로 자동 남긴다. 사람이 나중에 고쳐도 된다.
    try:
        from .version import prompt_version
        from .spec import ROOT
        out = ROOT / "outputs"
        nv = prompt_version()
        if nv not in names_read(out):
            names_set(out, nv, f"규칙 추가: {(note or en).strip()}")
    except Exception:                                   # noqa: BLE001
        pass
    return {"ok": True, "rule": rule, "count": len(cfg["custom"])}


def scorecard(out_dir: Path) -> list:
    """규칙 도입 전/후 그 사유의 제외 건수. 안 떨어지면 문장이 약한 것이다."""
    cfg = _cfg()
    rows = list(_latest(read(out_dir)).values())
    out = []
    for c in cfg.get("custom") or []:
        try:
            since = time.mktime(time.strptime(c.get("since", ""), "%Y-%m-%d"))
        except Exception:                               # noqa: BLE001
            continue
        before = [r for r in rows if r.get("at", 0) < since]
        after = [r for r in rows if r.get("at", 0) >= since]
        out.append({"rule": c.get("en"), "from": c.get("from"), "since": c.get("since"),
                    "before_rejects": sum(1 for r in before if r.get("pick") == "reject"),
                    "after_rejects": sum(1 for r in after if r.get("pick") == "reject"),
                    "after_reviewed": len(after)})
    return out

HANDOFFS = "handoffs.jsonl"


def handoffs_read(out_dir: Path) -> list:
    """'티모에게 넘기기' 원장 — 승격감이 아닌 메모(프롬프트 설계·검수기·조건 가중치)를 사람이 넘긴 것. append-only."""
    p = out_dir / HANDOFFS
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            if line.strip():
                out.append(json.loads(line))
        except Exception:                               # noqa: BLE001
            continue
    return out


def handoffs_add(out_dir: Path, note: str, en: str = "", why: str = "", kind=None, by=None) -> dict:
    row = {"note": (note or "").strip()[:300], "en": (en or "").strip()[:400], "why": (why or "").strip()[:200],
           "kind": kind, "by": by, "at": time.time(), "status": "open"}
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / HANDOFFS).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def handoffs_open(out_dir: Path) -> list:
    """같은 메모는 마지막 줄만. status 가 open 인 것만."""
    last = {}
    for r in handoffs_read(out_dir):
        last[_norm(r.get("note", ""))] = r
    return [r for r in last.values() if r.get("status", "open") == "open"]


NAMES = "version_names.json"


def names_read(out_dir: Path) -> dict:
    """버전 해시 → 사람이 붙인 메모. outputs/ 에 둔다(config 에 두면 해시가 바뀐다)."""
    p = out_dir / NAMES
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:                                   # noqa: BLE001
        return {}


def names_set(out_dir: Path, version: str, note: str) -> dict:
    d = names_read(out_dir)
    note = (note or "").strip()
    if note:
        d[version] = {"note": note[:80], "at": time.time()}
    else:
        d.pop(version, None)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / NAMES).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


# 설정 파일 → 사람 말. 버전 제목은 "무엇이 바뀐 버전인가"로 읽혀야 한다 (2026-09-10 성연서님 "해시 말고 '시술 카테고리' '제외사항' 같은 식으로").
CONFIG_KO = {
    "treatments.yaml": "시술 정의", "variations.yaml": "변주 조건", "prompts/avoid.yaml": "제외 규칙",
    "prompts/after_selfie.md": "셀카 후 프롬프트", "prompts/after_clinical.md": "임상 후 프롬프트", "prompts/before.md": "전 프롬프트",
    "prompts/identity_lock.md": "동일인 잠금", "prompts/identity_lock_lower.md": "동일인 잠금(하안)", "prompts/identity_lock_neck.md": "동일인 잠금(목)",
    "prompts/mode_extra.yaml": "모드별 추가문", "clinical_rig.yaml": "임상 촬영 조건", "effects.yaml": "효과 정의",
    "postprocess.yaml": "후처리", "pricing.yaml": "단가", "providers.yaml": "모델 라우팅", "qa_checklist.yaml": "AI 검수 항목",
    "samples_index.yaml": "참고 사진 목록",
}


def _git_changed(prev_sha: str, sha: str) -> list:
    """두 커밋 사이에 바뀐 config/ 파일을 사람 말로. 깃이 없거나 커밋을 모르면 빈 목록(제목은 시술만으로 만든다)."""
    import subprocess
    from .spec import ROOT
    try:
        out = subprocess.check_output(["git", "diff", "--name-only", prev_sha, sha, "--", "config/"],
                                      cwd=ROOT, text=True, stderr=subprocess.DEVNULL, timeout=5)
    except Exception:                                   # noqa: BLE001
        return []
    names = []
    for line in out.splitlines():
        rel = line.strip().replace("config/", "", 1)
        ko = CONFIG_KO.get(rel) or ("브랜드" if rel.startswith("brand/") else rel)
        if ko not in names:
            names.append(ko)
    return names


def titles(rows: list, treatments_ko: dict) -> dict:
    """해시 → 자동 제목 '팔자주름 · 제외 규칙 변경'. 첫 버전은 '첫 설정', 커밋이 같은데 해시만 다르면 '설정 수정(커밋 전)'."""
    real = sorted([r for r in rows if r.get("real")], key=lambda r: r["first"])
    out, prev = {}, None
    for r in real:
        tr = sorted((r.get("treatments") or {}).items(), key=lambda kv: -kv[1])
        tr_ko = [treatments_ko.get(k, k) for k, _ in tr[:2]] + (["외 %d" % (len(tr) - 2)] if len(tr) > 2 else [])
        sha = r["version"].split("-")[0]
        if prev is None:
            what = "첫 설정"
        elif sha == prev.split("-")[0]:
            what = "설정 수정(커밋 전)"
        else:
            ch = _git_changed(prev.split("-")[0], sha)
            what = (" · ".join(ch[:3]) + " 변경") if ch else "코드만 변경"
        out[r["version"]] = " · ".join([x for x in [" ".join(tr_ko) if tr_ko else "", what] if x])
        prev = r["version"]
    return out


def aliases(rows: list, current=None) -> dict:
    """해시 → 'v1'·'v2'… 처음 쓴 순서. 해시는 기계용이고 사람은 순번으로 읽는다 (2026-09-10 성연서님 "복잡하고 어렵다").
    현재 버전으로 아직 사진을 안 만들었으면 다음 번호를 미리 준다. 시뮬·샘플은 번호를 안 받는다."""
    real = sorted([r for r in rows if r.get("real")], key=lambda r: r["first"])
    out = {r["version"]: f"v{i + 1}" for i, r in enumerate(real)}
    if current and current not in out:
        out[current] = f"v{len(real) + 1}"
    return out


def by_version(out_dir: Path) -> list:
    """프롬프트 버전별 성적 — 고도화의 기준선. 버전(config 해시)마다 AI 통과율·사람 제외율·상위 제외 사유를 낸다.
    dry-run 은 사진이 없으니 뺀다. sim/demo 는 실제 프롬프트가 아니라 따로 표시만 한다."""
    if not out_dir.exists():
        return []
    acc = {}
    for d in out_dir.iterdir():
        if not d.is_dir() or d.name == "exports":
            continue
        try:
            info = json.loads((d / "batch.json").read_text(encoding="utf-8")) if (d / "batch.json").exists() else {}
        except Exception:                               # noqa: BLE001
            info = {}
        if info.get("kind") == "dry_run":
            continue
        created = info.get("created_at") or d.stat().st_mtime
        for m in d.glob("*/meta.json"):
            try:
                it = json.loads(m.read_text(encoding="utf-8"))
            except Exception:                           # noqa: BLE001
                continue
            if it.get("dry_run"):
                continue
            v = it.get("prompt_version") or "?"
            a = acc.setdefault(v, {"version": v, "first": created, "last": created, "n": 0, "ai_pass": 0,
                                   "reviewed": 0, "rejected": 0, "tags": {}, "treatments": {}, "cost": 0.0,
                                   "providers": {}, "attempts": 0, "id_review": 0, "id_measured": 0})
            _pv = (it.get("providers") or {}).get("gen")
            if _pv:                                     # 한 버전 줄에 두 모델이 섞였는지 보이게 (섞이면 비교가 무의미하다)
                a["providers"][_pv] = a["providers"].get(_pv, 0) + 1
            a["first"] = min(a["first"], created); a["last"] = max(a["last"], created)
            a["n"] += 1; a["ai_pass"] += bool(it.get("passed")); a["cost"] += float(it.get("cost") or 0)
            # 재시도 비용 — 프롬프트를 느슨하게 풀면 동일인 게이트가 더 자주 되돌려보낼 수 있다.
            # 그 대가가 버전 줄에 안 보이면 "제외율은 좋아졌는데 돈이 늘었다"를 못 읽는다 (2026-09-10 빌디 질문).
            a["attempts"] += int(it.get("attempt") or 1)
            _id = it.get("identity") or {}
            if _id.get("measured"):
                a["id_measured"] += 1
                if _id.get("gate") == "review":
                    a["id_review"] += 1
            t = it.get("treatment") or "?"; a["treatments"][t] = a["treatments"].get(t, 0) + 1
            rp = m.parent / "review.json"
            if rp.exists():
                try:
                    rv = json.loads(rp.read_text(encoding="utf-8"))
                except Exception:                       # noqa: BLE001
                    rv = {}
                if rv.get("pick") in ("pick", "reject"):
                    a["reviewed"] += 1
                if rv.get("pick") == "reject":
                    a["rejected"] += 1
                    for tg in rv.get("tags", []):
                        a["tags"][tg] = a["tags"].get(tg, 0) + 1
    rows = []
    for a in acc.values():
        a["ai_pass_rate"] = round(a["ai_pass"] / a["n"], 3) if a["n"] else 0
        a["reject_rate"] = round(a["rejected"] / a["reviewed"], 3) if a["reviewed"] else None
        a["cost_per_pass"] = round(a["cost"] / a["ai_pass"], 4) if a["ai_pass"] else None
        a["attempts_per_item"] = round(a["attempts"] / a["n"], 2) if a["n"] else None
        # 잰 것 중에서만 센다 — 미검출(n/a)을 분모에 넣으면 게이트가 꺼진 배치가 '좋아 보인다'
        a["id_review_rate"] = round(a["id_review"] / a["id_measured"], 3) if a["id_measured"] else None
        a["top_tags"] = sorted(a["tags"].items(), key=lambda kv: -kv[1])[:3]
        a["real"] = a["version"] not in ("sim", "demo", "?")
        a["provider_mixed"] = len(a["providers"]) > 1     # True 면 이 줄의 통과율을 버전 비교에 쓰면 안 된다
        rows.append(a)
    al, nm = aliases(rows), names_read(out_dir)
    try:
        from .spec import load
        tko = {k: v.get("name_ko", k) for k, v in load("treatments.yaml").items()}
    except Exception:                                   # noqa: BLE001
        tko = {}
    ti = titles(rows, tko)
    for r in rows:
        r["alias"] = al.get(r["version"])
        r["title"] = ti.get(r["version"], "")
        r["note"] = (nm.get(r["version"]) or {}).get("note", "")
    rows.sort(key=lambda r: (r["real"], r["last"]), reverse=True)
    return rows
