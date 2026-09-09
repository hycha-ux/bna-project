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


def summarize(out_dir: Path, treatment=None, mode=None) -> dict:
    """사유별·조건별 제외 집계 + 승격 대기 메모. 화면과 프롬프트가 같은 함수를 쓴다."""
    cfg = _cfg()
    st = cfg.get("settings") or {}
    win = float(st.get("window_days", 14)) * 86400
    now = time.time()
    rows = [r for r in _latest(read(out_dir)).values()
            if r.get("pick") == "reject"
            and (treatment is None or r.get("treatment") == treatment)
            and (mode is None or r.get("mode") == mode)]
    recent = [r for r in rows if now - r.get("at", 0) <= win]
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
    notes.sort(key=lambda n: n["at"], reverse=True)
    return {"window_days": st.get("window_days", 14), "rejected": len(recent), "rejected_all": len(rows),
            "tags": dict(sorted(tags.items(), key=lambda kv: -kv[1])), "axes": axes, "notes": notes[:50],
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
    # 축 회피: 제외가 몰린 조건값의 추첨 가중치를 낮춘다
    amin, aw = int(st.get("axis_min_count", 3)), float(st.get("axis_weight", 0.25))
    weights = {a: {k: aw for k, n in vals.items() if n >= amin} for a, vals in s["axes"].items()}
    weights = {a: v for a, v in weights.items() if v}
    return {"lines": lines, "weights": weights, "from_tags": [t for t, _ in picked], "rejected": s["rejected"]}


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
                                   "providers": {}})
            _pv = (it.get("providers") or {}).get("gen")
            if _pv:                                     # 한 버전 줄에 두 모델이 섞였는지 보이게 (섞이면 비교가 무의미하다)
                a["providers"][_pv] = a["providers"].get(_pv, 0) + 1
            a["first"] = min(a["first"], created); a["last"] = max(a["last"], created)
            a["n"] += 1; a["ai_pass"] += bool(it.get("passed")); a["cost"] += float(it.get("cost") or 0)
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
        a["top_tags"] = sorted(a["tags"].items(), key=lambda kv: -kv[1])[:3]
        a["real"] = a["version"] not in ("sim", "demo", "?")
        a["provider_mixed"] = len(a["providers"]) > 1     # True 면 이 줄의 통과율을 버전 비교에 쓰면 안 된다
        rows.append(a)
    al, nm = aliases(rows), names_read(out_dir)
    for r in rows:
        r["alias"] = al.get(r["version"])
        r["note"] = (nm.get(r["version"]) or {}).get("note", "")
    rows.sort(key=lambda r: (r["real"], r["last"]), reverse=True)
    return rows
