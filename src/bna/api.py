"""로컬 대시보드 API + 정적 서빙 (표준 라이브러리만 사용, 의존성 추가 없음).

실행:  PYTHONPATH=src python3 -m bna.api            # http://localhost:8765
      PYTHONPATH=src python3 -m bna.api --demo     # 키 없이 화면을 보기 위한 데모 배치 1개 생성 후 실행

엔드포인트
  GET  /api/config                 시술·모드·축 옵션
  POST /api/plan                   {treatment, mode, count, seed, fixed} → 분포 + 프롬프트(dry-run)
  POST /api/estimate               같은 입력 → 예상 호출 수·비용 (키 없으면 pricing 표만으로 계산)
  POST /api/run                    실제 배치 시작 (백그라운드 스레드). 키·프로바이더 없으면 오류 반환
  POST /api/dryrun_save            프롬프트만 든 배치를 outputs/ 에 저장 (이미지 없음)
  GET  /api/batches                outputs/ 아래 배치 목록 + stats
  GET  /api/batches/<id>           배치 아이템 전체 (meta + review)
  GET  /api/batches/<id>/progress  진행 상황 (progress.json 요약)
  POST /api/demo_run               가짜 실행 시뮬레이션 (키 없이 진행 화면 검증용, 항목당 수 초)
  GET  /api/queue                  큐 상태 (jobs, paused, 예상 비용)
  POST /api/queue/add              {jobs:[{treatment, mode, count, seed, fixed, target_pass, cost_cap, simulate}]} 또는 단일
  POST /api/queue/cancel|remove|move|pause|clear_finished
  POST /api/review                 {batch, item, pick, tags, note} → outputs/<batch>/<item>/review.json
  GET  /api/library                채택(pick)된 항목 전체 (배치 무관), 시술·유형 요약
  GET  /api/lessons                제외 사유 집계 + 승격 대기 메모 + 지금 붙는 금지문 + 규칙 성적표
  POST /api/lessons/promote        {note, en, where[]} → config/prompts/avoid.yaml 의 custom 에 규칙 추가
  GET  /api/overview?days=14       대시보드 집계 (일별 생성·통과·탈락 사유, 시술·조건별 통과율, 오늘 시간대별)
  POST /api/export                 {treatment?, mode?} → outputs/exports/<ts>/ 에 선택 항목 복사 + manifest.csv + zip
  GET  /exports/<name>.zip         내보낸 zip 다운로드
  GET  /files/<batch>/<item>/<f>   이미지
"""
import argparse, asyncio, csv, json, os, random, shutil, threading, time, uuid, webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from .spec import ROOT, load, build_prompts, PERSON_AXES, SCENE_AXES, defaults_for
from .planner import plan_batch, distribution
from .stats import load_items, summarize
from . import progress as prog
from . import cloudpush, drivesync, lessons
from .queue import Queue

OUT = ROOT / "outputs"
WEB = ROOT / "web"
RUNNING = {}   # batch_id → {"status", "started", "error"}


# ---------- 데이터 ----------
def config_payload():
    t = load("treatments.yaml"); v = load("variations.yaml")
    axes = {a: list(v[a]) for a in PERSON_AXES + SCENE_AXES}
    return {"treatments": {k: {"name_ko": x.get("name_ko", k), "modes": list(x.get("modes", {})), "timeline": list(x.get("timeline") or ["2w"])} for k, x in t.items()},
            "modes": ["selfie", "clinical"], "axes": axes, "mode_rules": v.get("mode_rules", {}),
            "pricing": load("pricing.yaml"), "checklist": list(load("qa_checklist.yaml")["items"]), "out_dir": str(OUT),
            "default_provider": load("providers.yaml")["default_provider"]}


def _plans(req):
    fixed = {k: val for k, val in (req.get("fixed") or {}).items() if val}
    seed = req.get("seed"); seed = int(seed) if seed not in (None, "") else None
    return plan_batch(req["mode"], int(req.get("count", 4)), seed, fixed, treatment=req.get("treatment")), seed, fixed


def plan_payload(req):
    plans, seed, fixed = _plans(req)
    specs = [build_prompts(req["treatment"], req["mode"], v, None if seed is None else seed * 1000 + i, series=req.get("series")) for i, v in enumerate(plans)]
    return {"count": len(plans), "distribution": distribution(plans), "items": specs, "series": specs[0].get("series") if specs else None}


def estimate_payload(req, expected_pass_rate=0.5):
    p = load("pricing.yaml"); d = defaults_for(req["mode"])
    gen, edit, qa = req.get("gen") or d["gen"], req.get("edit") or d["edit"], req.get("qa") or d["qa"]
    from .spec import series_points
    n_after = max(1, len(series_points(req["treatment"], req.get("series")))) if req.get("treatment") else 1
    per_try = p[gen]["generate"] + n_after * (p[edit]["edit" if req["mode"] == "clinical" else "generate"] + p[qa]["qa"])
    n = int(req.get("count", 1)); tries = n * min(3, 1 / max(expected_pass_rate, 0.05))
    return {"items": n, "expected_calls": round(tries * (1 + 2 * n_after)), "expected_cost_usd": round(per_try * tries, 2), "per_try_usd": round(per_try, 4), "afters": n_after}


def dryrun_save(req):
    plans, seed, fixed = _plans(req)
    bid = time.strftime("%Y%m%d-%H%M%S") + "-dry"
    d = OUT / bid; d.mkdir(parents=True, exist_ok=True)
    items = []
    for i, v in enumerate(plans):
        spec = build_prompts(req["treatment"], req["mode"], v, None if seed is None else seed * 1000 + i)
        meta = {**spec, "item_id": f"{i:04d}", "batch_id": bid, "attempt": 0, "passed": None, "fail_reasons": [], "cost": 0.0, "dry_run": True}
        (d / meta["item_id"]).mkdir(exist_ok=True)
        (d / meta["item_id"] / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        items.append(meta)
    (d / "batch.json").write_text(json.dumps({"batch_id": bid, "treatment": req["treatment"], "mode": req["mode"], "count": len(items),
                                              "kind": "dry_run", "seed": seed, "fixed": fixed, "created_at": time.time()}, ensure_ascii=False))
    return {"batch_id": bid, "count": len(items)}


def start_run(req):
    from . import providers
    try:
        from .batch import Batch
        b = Batch(req["treatment"], req["mode"], int(req.get("count", 1)), req.get("seed") or None, req.get("fixed") or {},
                  req.get("gen") or None, req.get("edit") or None, req.get("qa") or None, series=req.get("series"))
    except providers.NotConfigured as e:
        return {"error": f"프로바이더 키 없음: {e}"}, 400
    (b.dir / "batch.json").write_text(json.dumps({"batch_id": b.batch_id, "treatment": b.treatment, "mode": b.mode, "count": b.count,
                                                  "kind": "run", "created_at": time.time()}, ensure_ascii=False))
    RUNNING[b.batch_id] = {"status": "running", "started": time.time(), "error": None}

    def worker():
        try:
            asyncio.run(b.run()); RUNNING[b.batch_id]["status"] = "done"
        except Exception as e:                      # noqa
            RUNNING[b.batch_id].update(status="error", error=repr(e))
    threading.Thread(target=worker, daemon=True).start()
    return {"batch_id": b.batch_id, "status": "running"}, 200


def _reviews(d: Path):
    out = {}
    for r in d.glob("*/review.json"):
        out[r.parent.name] = json.loads(r.read_text(encoding="utf-8"))
    return out


def batch_summary(d: Path):
    info = json.loads((d / "batch.json").read_text(encoding="utf-8")) if (d / "batch.json").exists() else {"batch_id": d.name}
    items = load_items(d)
    if not info.get("treatment") and items:
        info.update(treatment=items[0].get("treatment"), mode=items[0].get("mode"), count=len(items))
    st = json.loads((d / "stats.json").read_text(encoding="utf-8")) if (d / "stats.json").exists() else summarize(items)
    rv = _reviews(d)
    st["reviewed"] = len(rv); st["picked"] = sum(1 for r in rv.values() if r.get("pick") == "pick")
    st["rejected"] = sum(1 for r in rv.values() if r.get("pick") == "reject")
    st["pending"] = sum(1 for it in items if it.get("passed") and (rv.get(it.get("item_id"), {}).get("pick") not in ("pick", "reject")))   # AI 통과했는데 사람이 아직 안 본 것
    tags = {}
    for r in rv.values():
        for tg in r.get("tags", []):
            tags[tg] = tags.get(tg, 0) + 1
    st["review_tags"] = tags
    info["kind"] = info.get("kind") or ("dry_run" if items and items[0].get("dry_run") else "run")
    pg = prog.read(d)
    if pg:
        info["progress"] = pg["summary"]
    info["status"] = RUNNING.get(d.name, {}).get("status") or ("running" if pg and pg["summary"]["running"] else "done")
    info["error"] = RUNNING.get(d.name, {}).get("error") or (pg or {}).get("error")
    info["mtime"] = d.stat().st_mtime
    return {**info, "stats": st}


def batches_payload():
    if not OUT.exists():
        return []
    # 폴더만 있고 batch.json 도 항목도 없는 것(시작 직후 죽은 배치)은 목록에 안 올린다 — 화면에 "undefined" 로 떴었다
    dirs = [d for d in OUT.iterdir() if d.is_dir() and d.name != "exports"
            and ((d / "batch.json").exists() or any(d.glob("*/meta.json")))]
    return sorted((batch_summary(d) for d in dirs), key=lambda b: b["mtime"], reverse=True)


def mask_payload(bid: str, iid: str):
    """시술 부위 마스크를 지금 만든다(없을 때). 랜드마크가 없는 PC 에서는 못 만든다 — 그때는 화면이 버튼을 숨긴다."""
    d = OUT / bid / iid
    if not d.is_dir() or "/" in bid or "/" in iid or ".." in bid or ".." in iid:
        return {"ok": False, "error": "not found"}
    if (d / "mask.png").exists():
        return {"ok": True, "file": "mask.png"}
    try:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        from PIL import Image
        from .qa import landmarks
        before = next(iter(sorted(d.glob("*_before.jpg"))), None)
        if before is None:
            return {"ok": False, "error": "시술 전 사진이 없습니다"}
        region = load("treatments.yaml").get(meta.get("treatment"), {}).get("mask_region")
        if region not in landmarks.REGIONS:
            return {"ok": False, "error": "이 시술은 부위 마스크가 없습니다"}
        img = Image.open(before); pts = landmarks.detect(img)
        if pts is None:
            return {"ok": False, "error": "얼굴을 못 찾았거나 랜드마크 모듈이 없습니다"}
        landmarks.region_mask(img, pts, region).save(d / "mask.png")
        return {"ok": True, "file": "mask.png"}
    except Exception as e:                       # noqa: BLE001
        return {"ok": False, "error": repr(e)}


def _fake_gates(rng, fails):
    """샘플·시뮬레이션 배치의 게이트 결과 — 실제 identity.check / structure.check 와 같은 키로 쓴다(화면이 한 코드로 읽게)."""
    if "identity" in fails:
        sim = round(rng.uniform(0.30, 0.44), 3); gate = "fail"
    else:
        roll = rng.random()
        if roll < 0.15:
            sim, gate = None, "n/a"
        elif roll < 0.35:
            sim = round(rng.uniform(0.45, 0.60), 3); gate = "review"
        else:
            sim = round(rng.uniform(0.60, 0.80), 3); gate = "ok"
    idn = {"similarity": sim, "gate": gate, "passed": True if gate == "ok" else (False if gate == "fail" else None),
           "hard_fail": gate == "fail", "measured": sim is not None}
    st_p = False if "structure" in fails else (None if rng.random() < 0.15 else True)
    st = {"passed": st_p, "face_detected": st_p is not None, "align_err_pct": round(rng.uniform(0, 12), 1),
          "face_ratio_diff": round(rng.uniform(0, 0.1), 3), "luma_diff": round(rng.uniform(0, 0.15), 3), "region_in_frame": st_p is not False}
    return idn, st


def _demo_images(d, stem, hue, iid, series=None):
    """자리표시 사진. 시리즈면 시점마다 _after_<when>.jpg (색이 시점 순으로 조금씩 밝아진다)."""
    from PIL import Image, ImageDraw
    kinds = [("before", "before.jpg", 35, 70)] + ([(f"after {w}", f"after_{w}.jpg", 50, 74 + 4 * k) for k, w in enumerate(series)] if series else [("after", "after.jpg", 50, 78)])
    for label, suffix, sat, lum in kinds:
        img = Image.new("RGB", (400, 500), f"hsl({hue},{sat}%,{lum}%)")
        dr = ImageDraw.Draw(img); dr.ellipse((100, 90, 300, 330), fill=f"hsl({hue},30%,88%)")
        dr.text((20, 460), f"DEMO {label.upper()} #{iid}", fill="black"); dr.text((20, 20), "placeholder — no real generation", fill="black")
        img.save(d / f"{stem}_{suffix}", quality=80)


def _demo_mask(d, size=(400, 500)):
    """샘플 배치용 부위 오버레이 자리표시(뺨~입가 타원 두 개). 실제 배치는 랜드마크로 만든다."""
    from PIL import Image, ImageDraw, ImageFilter
    m = Image.new("L", size, 0); dr = ImageDraw.Draw(m)
    dr.polygon([(150, 250), (180, 300), (170, 330), (135, 290)], fill=255); dr.polygon([(250, 250), (220, 300), (230, 330), (265, 290)], fill=255)
    m.filter(ImageFilter.GaussianBlur(8)).save(d / "mask.png")


AFTER_ORDER = ["immediate", "1w", "2w", "4w"]


def after_files_of(files: list) -> dict:
    """*_after.jpg 또는 *_after_<when>.jpg → {when: 파일}. 시리즈가 아니면 {"final": 파일}."""
    out = {}
    for f in files:
        if f.endswith("_after.jpg"):
            out["final"] = f
        else:
            for w in AFTER_ORDER:
                if f.endswith(f"_after_{w}.jpg"):
                    out[w] = f
    return {k: out[k] for k in AFTER_ORDER + ["final"] if k in out}


def last_after(files: list):
    af = after_files_of(files)
    return list(af.values())[-1] if af else None


def stem_of(meta: dict) -> str:
    """이 아이템의 **현재** 파일 이름 앞부분. batch._save 와 같은 규칙이다(바꾸면 둘 다 바꿔라)."""
    v = (meta or {}).get("variation") or {}
    try:
        return (f'{meta.get("treatment")}_{meta.get("mode")}_'
                f'{v["country"]["key"]}{v["age"]["key"]}{v["gender"]["key"][0]}_{meta.get("item_id")}')
    except (KeyError, TypeError):
        return ""


def pair_files(item_dir, meta: dict) -> list:
    """전·후 한 쌍을 고를 후보 파일. **반드시 같은 회차의 것이어야 한다.**

    ⚠ 2026-09-10 실사고: 재시도 때 조건을 다시 뽑으면 파일 이름 앞부분(사람 정보)이 바뀌는데
      옛 회차 파일이 그대로 남는다. 그 상태에서 before 는 '첫 번째', after 는 '마지막'을 고르던 탓에
      **전·후가 서로 다른 사람**으로 화면에 떴다(0910 배치 0000: before 일본인 / after 한국인,
      성연서님이 '동일 인물 아님'으로 제외하셨는데 그게 정확한 판정이었다).
      그래서 지금 meta 가 말하는 조건의 이름을 가진 파일만 본다. 그런 파일이 없으면(옛 배치 등)
      종전대로 전부 본다 — 화면이 비는 것보다는 낫다(fail-open).
    """
    files = sorted(p.name for p in item_dir.glob("*.jpg"))
    stem = stem_of(meta)
    same = [f for f in files if stem and f.startswith(stem + "_")]
    return same or files


def batch_detail(bid: str):
    d = OUT / bid
    if not d.is_dir():
        return None
    rv = _reviews(d); items = []
    for m in sorted(load_items(d), key=lambda x: x.get("item_id", "")):
        iid = m["item_id"]; files = pair_files(d / iid, m)
        m["before_file"] = next((f for f in files if f.endswith("_before.jpg")), None)
        m["after_file"] = last_after(files)                     # 대표 = 마지막 시점
        m["after_files"] = after_files_of(files)                # 시리즈면 {immediate: …, 2w: …}
        m["mask_file"] = "mask.png" if (d / iid / "mask.png").exists() else None   # 검수 화면 부위 오버레이
        m["review"] = dict(rv.get(iid, {}))
        if m["review"].get("pick") == "pick":          # 화면 배지가 짐작하지 않게 실제 드라이브 상태를 싣는다
            m["review"]["drive"] = drivesync.state_of(d.name, iid)
        items.append(m)
    return {**batch_summary(d), "items": items}


def lessons_payload():
    """제외 사유 되먹임 한 화면 — 집계·지금 붙는 금지문·승격 대기 메모·규칙 성적표."""
    s = lessons.summarize(OUT)
    a = lessons.active(OUT)
    from .version import prompt_version
    from . import notedraft
    cfg = lessons._cfg(); st = cfg.get("settings") or {}
    # AI 초안(티모 notedraft, 캐시 outputs/note_drafts.json)을 병합 그룹에 붙인다. 승격 버튼은 promotable 로 (티모 요청).
    # 키워드 표 초안은 AI 초안이 없을 때만 남는다 — 화면이 "단어 매칭"이라고 표시한다.
    drafts = notedraft.read_cache(OUT)
    # 넘긴 적 있는 메모는 **닫힌 것까지** 뺀다 — 열린 것만 빼면 티모가 처리해 닫는 순간
    # 그 메모가 승격 대기로 돌아오고, 초안이 여전히 rule 이 아니라 화면은 또 '넘기기'를 보여 준다
    # (무한 왕복). 정본·근거 = lessons.handoffs_notes 주석.
    handed = lessons.handoffs_notes(OUT)
    notes = []
    for n in s.get("notes") or []:
        k = lessons._norm(n["note"])
        if k in handed:
            continue                                    # 이미 티모에게 넘긴 메모는 목록에서 뺀다
        d = drafts.get(k)
        if d and d.get("source") == "ai":
            n["draft"] = {kk: d.get(kk) for kk in ("why", "en", "kind", "covered_by", "promotable", "source", "usd")}
            n["suggest_en"] = d.get("en") or n.get("suggest_en", "")
        else:
            n["draft"] = None
        notes.append(n)
    s["notes"] = notes
    # reviewed_total: 채택·제외 합계(원장 기준). 0이면 화면이 "첫 검수 안내"를 낸다 — 검수 0건인 상태에서
    # 되먹임 고리가 어디에 쌓이고 언제 붙는지가 안 보였다 (2026-09-10 성연서님 "구조가 안 그려진다").
    # tag_rules: 제외 사유 버튼 ↔ 붙을 영어 금지문. 안내에서 "이 버튼을 누르면 이 문장이 붙는다"를 실물로 보여준다.
    bv = lessons.by_version(OUT); cur = prompt_version()
    return {**s, "active": a, "scorecard": lessons.scorecard(OUT), "by_version": bv,
            "current_version": cur, "current_alias": lessons.aliases(bv, cur).get(cur),
            "settings_top_n": st.get("top_n", 3),
            "settings": {"top_n": st.get("top_n", 3), "window_days": st.get("window_days", 14), "min_count": st.get("min_count", 2),
                         "axis_min_count": st.get("axis_min_count", 3), "axis_weight": st.get("axis_weight", 0.25)},
            # 버전 표와 같은 기준(review.json)으로 센다 — 원장(lessons.jsonl)으로 세면 옛 시뮬 판정이 빠져 표와 어긋난다
            "reviewed_total": sum(int(r.get("reviewed") or 0) for r in bv),
            "handoffs": lessons.handoffs_open(OUT), "handoffs_done": lessons.handoffs_done(OUT),
            "draft_totals": notedraft.totals(OUT),
            "tag_rules": {t: (c or {}).get("en", "") for t, c in (cfg.get("tags") or {}).items()},
            "preview": {k: lessons.avoid_text(v) for k, v in (a.get("lines") or {}).items() if v}}


def save_review(req):
    d = OUT / req["batch"] / req["item"]
    if not d.is_dir():
        return {"error": "item not found"}, 404
    rv = {"pick": req.get("pick"), "tags": req.get("tags", []), "note": req.get("note", ""), "updated_at": time.time()}
    (d / "review.json").write_text(json.dumps(rv, ensure_ascii=False, indent=1), encoding="utf-8")
    # 채택 → 드라이브에 올린다 / 제외·판정 지움 → 채택본에서 내린다 (2026-09-08 성연서님 지시).
    # 훅은 백그라운드라 검수를 막지 않는다. 응답의 drive 는 '지금 이 순간' 상태이고,
    # 방금 채택한 건은 아직 pending 이 맞다 — 화면이 "저장 대기"로 정직하게 낸다.
    before = drivesync.state_of(req["batch"], req["item"])
    drivesync.nudge(req["batch"], req["item"])
    rv["drive"] = drivesync.state_of(req["batch"], req["item"])
    if rv["pick"] != "pick" and before == "uploaded":
        rv["drive"] = "removed"
    lessons.record(OUT, req["batch"], req["item"], rv)      # 제외 사유를 교훈 원장에 쌓는다
    # 검수도 '완료 지점'이다 (2026-09-10). 종전엔 생성 완료에만 훅이 걸려 있어, 사람이 판정을 눌러도
    # 남의 화면(학습·검수 탭)에 뜨기까지 최대 10분(주기 회차)이 비었다 — 정작 사람이 기다리는 건
    # 이쪽이다. 훅은 백그라운드+최소 간격이라 검수 응답을 늦추지 않는다(10장 연속 판정 → 업로드 몇 회).
    cloudpush.nudge(f"검수 {req['batch']}/{req['item']} {rv['pick']}")
    return rv, 200


# ---------- 목표 장수 ----------
# config/ 가 아니라 outputs/goals.json 에 둔다 — config 를 건드리면 프롬프트 버전 해시가 바뀐다(version.py).
def goals_payload():
    p = OUT / "goals.json"
    # pick_rate: 사람 채택률 목표. 자동화의 기준선 — AI 통과분 중 사람이 이 비율 이상 채택하면 사람 검수를 줄일 수 있다
    # (2026-09-10 성연서님 "보수적으로 90%까지").
    g = {"default": 30, "per": {}, "pick_rate": 0.9}
    if p.exists():
        try:
            g.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:                       # noqa: BLE001
            pass
    return g


def goals_save(req):
    g = goals_payload()
    if "default" in req:
        g["default"] = max(1, int(req["default"]))
    if "pick_rate" in req:
        g["pick_rate"] = min(1.0, max(0.0, float(req["pick_rate"])))
    if isinstance(req.get("per"), dict):
        g["per"] = {k: max(0, int(v)) for k, v in req["per"].items() if v not in (None, "")}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "goals.json").write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
    return g


# ---------- 대시보드 집계 ----------
FAKE_KINDS = ("sim", "demo")


def overview_payload(days=14, include_sim=False):
    """일별 생성·통과·탈락 사유, 시술별·조건별 통과율, 채택(사람)·검수 대기·게이트, 라이브러리 요약. dry_run 제외.
    include_sim=False 면 시뮬레이션·샘플 배치를 뺀다 — 홈의 통과율이 가짜 숫자로 오염되지 않게 (2026-09-09 홈 검토)."""
    import datetime as dt
    now = time.time(); today = dt.date.today()
    day_keys = [(today - dt.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    daily = {k: {"total": 0, "passed": 0, "picked": 0, "cost": 0.0, "fails": {}} for k in day_keys}
    picked_all, pending_batches, win_rv = {}, {}, {"reviewed": 0, "picked": 0, "rejected": 0}
    gates = {"identity": {}, "structure": {"ok": 0, "fail": 0, "n/a": 0}}
    prev = {"total": 0, "passed": 0, "cost": 0.0}
    hourly = [0] * 24; hourly_pass = [0] * 24
    by_treat = {}; by_axis = {a: {} for a in ("angle", "framing", "background", "lighting", "before_severity", "age", "country", "gender")}
    fails_total = {}; attempts = [0, 0]
    if OUT.exists():
        for d in OUT.iterdir():
            if not d.is_dir() or d.name == "exports":
                continue
            info = json.loads((d / "batch.json").read_text(encoding="utf-8")) if (d / "batch.json").exists() else {}
            if info.get("kind") == "dry_run":
                continue
            if not include_sim and (info.get("kind") in FAKE_KINDS or d.name.endswith(("-sim", "-demo"))):
                continue
            created = info.get("created_at") or d.stat().st_mtime
            key = dt.date.fromtimestamp(created).isoformat(); in_win = key in daily
            in_prev = not in_win and created >= now - 2 * days * 86400
            rvs = _reviews(d)
            for m in d.glob("*/meta.json"):
                it = json.loads(m.read_text(encoding="utf-8"))
                if it.get("dry_run"):
                    continue
                p = bool(it.get("passed")); c = float(it.get("cost") or 0)
                pick = (rvs.get(m.parent.name) or {}).get("pick")
                t_all = picked_all.setdefault(it.get("treatment"), {"picked": 0, "pending": 0, "reviewed": 0})
                if pick == "pick":
                    t_all["picked"] += 1
                if pick in ("pick", "reject"):
                    t_all["reviewed"] += 1
                elif p:
                    t_all["pending"] += 1; pending_batches.setdefault(d.name, 0); pending_batches[d.name] += 1
                g = (it.get("identity") or {}).get("gate")
                if g:
                    gates["identity"][g] = gates["identity"].get(g, 0) + 1
                sp = (it.get("structure") or {}).get("passed", "?")
                gates["structure"]["n/a" if sp is None else "ok" if sp else "fail"] += 1
                if in_win:
                    dd = daily[key]; dd["total"] += 1; dd["passed"] += p; dd["cost"] += c
                    dd["picked"] += pick == "pick"
                    win_rv["reviewed"] += pick in ("pick", "reject"); win_rv["picked"] += pick == "pick"; win_rv["rejected"] += pick == "reject"
                    for r in it.get("fail_reasons", []):
                        g = r.split(":")[0] if not r.startswith("vision") else r
                        dd["fails"][g] = dd["fails"].get(g, 0) + 1; fails_total[g] = fails_total.get(g, 0) + 1
                elif in_prev:
                    prev["total"] += 1; prev["passed"] += p; prev["cost"] += c
                if key == today.isoformat():
                    h = dt.datetime.fromtimestamp(created).hour; hourly[h] += 1; hourly_pass[h] += p
                t = by_treat.setdefault(it.get("treatment"), {"total": 0, "passed": 0, "cost": 0.0}); t["total"] += 1; t["passed"] += p; t["cost"] += c
                attempts[0] += int(it.get("attempt") or 0); attempts[1] += 1
                for a, dct in by_axis.items():
                    k = (it.get("variation") or {}).get(a, {}).get("key")
                    if k:
                        e = dct.setdefault(k, {"n": 0, "pass": 0}); e["n"] += 1; e["pass"] += p
    q = queue().snapshot(); lib = library_payload()
    tot = sum(v["total"] for v in daily.values()); pas = sum(v["passed"] for v in daily.values()); cost = sum(v["cost"] for v in daily.values())
    tk = today.isoformat()
    goals = goals_payload(); treatments = load("treatments.yaml")
    board = []
    for k, t in treatments.items():
        a = picked_all.get(k, {"picked": 0, "pending": 0, "reviewed": 0})
        board.append({"treatment": k, "name_ko": t.get("name_ko", k), "target": int((goals.get("per") or {}).get(k) or goals.get("default", 30)), **a})
    for k, a in picked_all.items():                     # 정의에서 빠진 옛 시술(예: 분할 전 filler)도 채택본이 있으면 보인다
        if k not in treatments and a["picked"]:
            board.append({"treatment": k, "name_ko": k, "target": int(goals.get("default", 30)), "legacy": True, **a})
    les = lessons.summarize(OUT); act = lessons.active(OUT)
    id_n = sum(gates["identity"].values()); st_n = sum(gates["structure"].values())
    newest_pending = max(pending_batches, key=lambda b: b) if pending_batches else None
    return {"days": days, "day_keys": day_keys, "daily": daily, "include_sim": include_sim,
            "window": {"total": tot, "passed": pas, "cost": round(cost, 3), **win_rv}, "prev": prev,
            "picked_total": sum(a["picked"] for a in picked_all.values()), "pending_total": sum(a["pending"] for a in picked_all.values()),
            "pending_batch": newest_pending, "board": board, "goals": goals,
            "gates": {"identity": {**gates["identity"], "n": id_n, "na_rate": round(gates["identity"].get("n/a", 0) / id_n, 3) if id_n else None},
                      "structure": {**gates["structure"], "n": st_n, "na_rate": round(gates["structure"]["n/a"] / st_n, 3) if st_n else None}},
            "lessons": {"top_tags": list(les.get("tags", {}).items())[:3], "active_tags": act.get("from_tags", []), "rejected": les.get("rejected", 0), "window_days": les.get("window_days")},
            "today": {**daily.get(tk, {"total": 0, "passed": 0, "cost": 0.0}), "hourly": hourly, "hourly_pass": hourly_pass},
            "by_treatment": by_treat, "by_axis": by_axis, "fails_total": fails_total, "avg_attempt": round(attempts[0] / attempts[1], 2) if attempts[1] else None,
            "queue": {"running": next((j for j in q["jobs"] if j["status"] == "running"), None), "queued": sum(1 for j in q["jobs"] if j["status"] == "queued"), "paused": q["paused"]},
            "library": {"total": lib["total"], "summary": lib["summary"]}}


# ---------- 라이브러리 · 내보내기 ----------
def library_payload():
    items = []
    if OUT.exists():
        for r in OUT.glob("*/*/review.json"):
            rv = json.loads(r.read_text(encoding="utf-8"))
            if rv.get("pick") != "pick":
                continue
            d = r.parent; m = d / "meta.json"
            if not m.exists():
                continue
            meta = json.loads(m.read_text(encoding="utf-8")); files = pair_files(d, meta)
            items.append({"batch_id": d.parent.name, "item_id": d.name, "treatment": meta.get("treatment"), "mode": meta.get("mode"),
                          "variation": meta.get("variation", {}), "review": rv, "passed": meta.get("passed"), "demo": meta.get("demo", False),
                          "before_file": next((f for f in files if f.endswith("_before.jpg")), None),
                          "after_file": last_after(files), "after_files": after_files_of(files), "picked_at": rv.get("updated_at"),
                          "drive": {"state": drivesync.state_of(d.parent.name, d.name), "files": drivesync.links_of(d.parent.name, d.name)}})
    items.sort(key=lambda x: x.get("picked_at") or 0, reverse=True)
    summary = {}
    for it in items:
        summary.setdefault(it["treatment"], {}).setdefault(it["mode"], 0); summary[it["treatment"]][it["mode"]] += 1
    return {"items": items, "summary": summary, "total": len(items)}


# 사용 범위 — 2026-09-10 파트장 확정 "내부만"(정본 docs/usage-policy.md).
# zip 은 결과물이 이 시스템을 떠나는 유일한 경로라, 파일만 받은 사람도 범위를 알아야 한다.
# 정책이 바뀌면 이 문구와 docs/usage-policy.md 를 같은 커밋에서 고친다.
USAGE_NOTICE = """B&A 생성 이미지 — 사용 범위: 회사 내부 참고용만 (2026-09-10 파트장 확정)

이 폴더의 이미지는 AI 로 생성한 시술 전후 예시입니다. 실제 환자 사진이 아닙니다.

허용: 사내 참고·검토·기획 자료
금지: 광고·SNS·홈페이지·인쇄물 등 대외 게시, 고객 대상 자료, 의료광고 심의 제출, 외부 공유

의료진 검토자는 아직 지정 전이라 시술 지시문은 초안 상태입니다.
정책 정본: docs/usage-policy.md · 문의: 티모(#team-lol)
"""


def export_payload(req):
    lib = library_payload()["items"]
    picked = set(req.get("items") or [])                 # ["<배치>/<아이템>", …] — 화면에서 체크한 것만 (2026-09-10 성연서님 "선택해서 내보내기")
    if picked:
        sel = [i for i in lib if f'{i["batch_id"]}/{i["item_id"]}' in picked]
    else:
        sel = [i for i in lib if (not req.get("treatment") or i["treatment"] == req["treatment"]) and (not req.get("mode") or i["mode"] == req["mode"])]
    if not sel:
        return {"error": "내보낼 선택 항목이 없습니다"}, 400
    name = time.strftime("%Y%m%d-%H%M%S") + "-" + (f"selected{len(sel)}" if picked else (req.get("treatment") or "all") + "-" + (req.get("mode") or "all"))
    root = OUT / "exports" / name; root.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in sel:
        sub = root / f'{i["treatment"]}_{i["mode"]}'; sub.mkdir(exist_ok=True); src = OUT / i["batch_id"] / i["item_id"]
        for f in [i["before_file"], *list((i.get("after_files") or {}).values())]:   # 시리즈는 시점 전부
            if f:
                shutil.copy2(src / f, sub / f)
        v = i["variation"]
        rows.append([i["treatment"], i["mode"], i["batch_id"], i["item_id"], i["before_file"], i["after_file"],
                     v.get("country", {}).get("key"), v.get("age", {}).get("key"), v.get("gender", {}).get("key"), v.get("angle", {}).get("key"),
                     v.get("framing", {}).get("key"), "|".join(i["review"].get("tags", [])), i["review"].get("note", "")])
    with (root / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["treatment", "mode", "batch", "item", "before", "after", "country", "age", "gender", "angle", "framing", "tags", "note"]); w.writerows(rows)
    (root / "사용범위-안내.txt").write_text(USAGE_NOTICE, encoding="utf-8")
    zip_path = shutil.make_archive(str(root), "zip", root_dir=root)
    return {"name": name, "count": len(sel), "dir": str(root), "zip": f"/exports/{name}.zip", "zip_bytes": Path(zip_path).stat().st_size}, 200


# ---------- 데모 배치 (키 없이 화면 확인용) ----------
def make_demo(treatment="nasolabial", mode="selfie", count=12, seed=7, series=None):
    """실제 생성 없이 PIL 로 그린 자리표시 이미지 + 무작위 검수 결과. 이름에 demo 가 붙는다."""
    from PIL import Image, ImageDraw
    rng = random.Random(seed)
    bid = time.strftime("%Y%m%d-%H%M%S") + "-demo"; d = OUT / bid; d.mkdir(parents=True, exist_ok=True)
    plans = plan_batch(mode, count, seed, treatment=treatment)
    checklist = list(load("qa_checklist.yaml")["items"]); items = []
    for i, v in enumerate(plans):
        spec = build_prompts(treatment, mode, v, seed * 1000 + i, series=series); iid = f"{i:04d}"; (d / iid).mkdir(exist_ok=True)
        passed = rng.random() < 0.6; attempt = 1 if passed and rng.random() < 0.7 else rng.randint(1, 3)
        fails = [] if passed else rng.sample(["structure", "identity", "vision:hair", "vision:ai_look", "vision:fingers", "duplicate"], rng.randint(1, 2))
        scores = {k: (rng.randint(7, 10) if passed else rng.randint(4, 9)) for k in checklist}
        stem = f'{treatment}_{mode}_{v["country"]["key"]}{v["age"]["key"]}{v["gender"]["key"][0]}_{iid}'
        hue = rng.randint(0, 360)
        _demo_images(d / iid, stem, hue, iid, spec.get("series"))
        idn, st = _fake_gates(rng, fails); _demo_mask(d / iid)
        meta = {**spec, "item_id": iid, "batch_id": bid, "prompt_version": "demo", "attempt": attempt, "passed": passed, "series": spec.get("series"),
                "fail_reasons": fails, "cost": round(0.085 * attempt, 3), "demo": True, "mask_file": "mask.png",
                "structure": st, "identity": idn,
                "vision": {"scores": scores, "failed_items": [f.split(":")[1] for f in fails if f.startswith("vision:")]}}
        (d / iid / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"); items.append(meta)
    (d / "stats.json").write_text(json.dumps(summarize(items), ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "batch.json").write_text(json.dumps({"batch_id": bid, "treatment": treatment, "mode": mode, "count": count, "kind": "demo",
                                              "seed": seed, "created_at": time.time()}, ensure_ascii=False))
    return bid


def sim_batch(treatment="nasolabial", mode="selfie", count=12, seed=None, item_seconds=2.0, concurrency=3, target_pass=None, cost_cap=None,
              fixed=None, on_batch=None, series=None):
    """실제 호출 없이 progress.json 을 시간에 따라 갱신하고, 끝난 항목은 make_demo 와 같은 자리표시 결과를 쓴다. 블로킹."""
    from PIL import Image, ImageDraw
    from concurrent.futures import ThreadPoolExecutor
    seed = seed if seed is not None else random.randint(0, 9999); rng = random.Random(seed)
    bid = time.strftime("%Y%m%d-%H%M%S") + "-sim"; d = OUT / bid; d.mkdir(parents=True, exist_ok=True)
    plans = plan_batch(mode, count, seed, fixed or {}, treatment=treatment); checklist = list(load("qa_checklist.yaml")["items"])
    (d / "batch.json").write_text(json.dumps({"batch_id": bid, "treatment": treatment, "mode": mode, "count": count, "kind": "sim", "seed": seed,
                                              "target_pass": target_pass, "cost_cap": cost_cap, "created_at": time.time()}, ensure_ascii=False))
    pgs = prog.Progress(d, count); RUNNING[bid] = {"status": "running", "started": time.time(), "error": None}
    if on_batch:
        on_batch(bid)
    stopped = [None]

    def should_stop():
        if stopped[0]:
            return True
        passed, cost = pgs.totals()
        if target_pass and passed >= target_pass:
            stopped[0] = f"target_pass:{passed}"
        elif cost_cap and cost >= cost_cap:
            stopped[0] = f"cost_cap:{cost:.2f}"
        return bool(stopped[0])

    def one(i, v):
        if should_stop():
            return None
        spec = build_prompts(treatment, mode, v, seed * 1000 + i, series=series); iid = f"{i:04d}"; (d / iid).mkdir(exist_ok=True)
        meta = None
        for attempt in range(1, 4):
            for stage in ("before", "after", "postprocess", "qa"):
                pgs.set(iid, stage, attempt=attempt); time.sleep(item_seconds / 4 * rng.uniform(0.6, 1.4))
            passed = rng.random() < 0.6
            fails = [] if passed else rng.sample(["structure", "identity", "vision:hair", "vision:ai_look", "vision:fingers"], rng.randint(1, 2))
            stem = f'{treatment}_{mode}_{v["country"]["key"]}{v["age"]["key"]}{v["gender"]["key"][0]}_{iid}'; hue = rng.randint(0, 360)
            _demo_images(d / iid, stem, hue, iid, spec.get("series"))
            _demo_mask(d / iid); idn, st = _fake_gates(rng, fails)
            meta = {**spec, "item_id": iid, "batch_id": bid, "prompt_version": "sim", "attempt": attempt, "passed": passed, "fail_reasons": fails,
                    "cost": round(0.085 * attempt, 3), "demo": True, "mask_file": "mask.png", "structure": st, "identity": idn, "series": spec.get("series"),
                    "vision": {"scores": {k: rng.randint(6, 10) for k in checklist}, "failed_items": [f.split(":")[1] for f in fails if f.startswith("vision:")]}}
            (d / iid / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            if passed:
                pgs.set(iid, "passed", passed=True, fail_reasons=[], cost=meta["cost"]); break
            pgs.set(iid, "retry" if attempt < 3 else "failed", passed=False, fail_reasons=fails, cost=meta["cost"])
        return meta

    try:
        with ThreadPoolExecutor(concurrency) as ex:
            items = [m for m in ex.map(lambda iv: one(*iv), enumerate(plans)) if m]
        st = summarize(items); st["stopped"] = stopped[0]
        (d / "stats.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        pgs.finish(stopped=stopped[0]); RUNNING[bid]["status"] = "done"
        return bid, st
    except Exception as e:                      # noqa
        pgs.finish(error=repr(e)); RUNNING[bid].update(status="error", error=repr(e)); raise


def demo_run(**kw):
    """sim_batch 를 백그라운드로. batch_id 는 폴더가 생기는 즉시 돌려준다."""
    got = threading.Event(); box = {}
    def on_batch(bid): box["bid"] = bid; got.set()
    threading.Thread(target=lambda: sim_batch(on_batch=on_batch, **kw), daemon=True).start()
    got.wait(10); return box.get("bid")


# ---------- 큐 ----------
def run_job(job, on_batch):
    common = dict(treatment=job["treatment"], mode=job["mode"], count=job["count"], seed=job["seed"], fixed=job["fixed"],
                  target_pass=job["target_pass"], cost_cap=job["cost_cap"], series=job.get("series"))
    if job["simulate"]:
        return sim_batch(on_batch=on_batch, **common)
    from .batch import Batch
    b = Batch(gen=job.get("gen") or None, edit=job.get("edit") or None, qa=job.get("qa") or None, **common)
    (b.dir / "batch.json").write_text(json.dumps({"batch_id": b.batch_id, "treatment": b.treatment, "mode": b.mode, "count": b.count, "kind": "run",
                                                  "target_pass": b.target_pass, "cost_cap": b.cost_cap, "series": b.series, "job_id": job["job_id"], "created_at": time.time()}, ensure_ascii=False))
    RUNNING[b.batch_id] = {"status": "running", "started": time.time(), "error": None}; on_batch(b.batch_id)
    try:
        st = asyncio.run(b.run()); RUNNING[b.batch_id]["status"] = "done"; return b.batch_id, st
    except Exception as e:                      # noqa
        RUNNING[b.batch_id].update(status="error", error=repr(e)); raise


QUEUE = None
def queue():
    global QUEUE
    if QUEUE is None:
        QUEUE = Queue(OUT, run_job)
    return QUEUE


def queue_payload():
    snap = queue().snapshot(); p = load("pricing.yaml")
    for j in snap["jobs"]:
        d = defaults_for(j["mode"]); g, e, q = j.get("gen") or d["gen"], j.get("edit") or d["edit"], j.get("qa") or d["qa"]
        j["providers"] = f"{g}/{e}/{q}"
        per_try = p[g]["generate"] + p[e]["edit" if j["mode"] == "clinical" else "generate"] + p[q]["qa"]
        j["est_cost"] = round(per_try * j["count"] * 2, 2)          # 통과율 50% 가정 (항목당 2회)
        if j["cost_cap"]:
            j["est_cost"] = min(j["est_cost"], j["cost_cap"])
        if j["batch_id"] and (OUT / j["batch_id"]).is_dir():
            pg = prog.read(OUT / j["batch_id"]); j["progress"] = pg["summary"] if pg else None
    snap["running"] = next((j for j in snap["jobs"] if j["status"] == "running"), None)
    snap["queued_count"] = sum(1 for j in snap["jobs"] if j["status"] == "queued")
    snap["est_total"] = round(sum(j["est_cost"] for j in snap["jobs"] if j["status"] in ("queued", "running")), 2)
    return snap


# ---------- HTTP ----------
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            return
        super().log_message(fmt, *args)

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store"); self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        p = urlparse(self.path).path
        try:
            if p == "/api/config":
                return self._json(config_payload())
            if p == "/api/batches":
                return self._json(batches_payload())
            if p == "/api/queue":
                return self._json(queue_payload())
            if p.startswith("/api/batches/") and p.endswith("/progress"):
                r = prog.read(OUT / p.split("/")[3]); return self._json(r or {"error": "no progress"}, 200 if r else 404)
            if p.startswith("/api/batches/"):
                r = batch_detail(p.split("/")[3]); return self._json(r or {"error": "not found"}, 200 if r else 404)
            if p == "/api/lessons":
                return self._json(lessons_payload())
            if p == "/api/library":
                return self._json(library_payload())
            if p.startswith("/api/overview"):
                from urllib.parse import parse_qs
                qs = parse_qs(urlparse(self.path).query)
                days = int(qs.get("days", ["14"])[0]); return self._json(overview_payload(days, include_sim=qs.get("sim", ["0"])[0] == "1"))
            if p == "/api/goals":
                return self._json(goals_payload())
            if p.startswith("/exports/") and p.endswith(".zip"):
                f = (OUT / "exports" / p[len("/exports/"):]).resolve()
                if (OUT / "exports").resolve() in f.parents and f.is_file():
                    data = f.read_bytes(); self.send_response(200); self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition", f'attachment; filename="{f.name}"'); self.send_header("Content-Length", str(len(data))); self.end_headers(); return self.wfile.write(data)
                return self._json({"error": "not found"}, 404)
            if p.startswith("/api/mask/"):
                _, _, _, bid, iid = p.split("/", 4)
                r = mask_payload(bid, iid); return self._json(r, 200 if r.get("ok") else 404)
            if p.startswith("/files/"):
                f = (OUT / p[len("/files/"):]).resolve()
                if OUT.resolve() in f.parents and f.is_file():
                    data = f.read_bytes(); self.send_response(200); self.send_header("Content-Type", "image/png" if f.suffix == ".png" else "image/jpeg")
                    self.send_header("Content-Length", str(len(data))); self.end_headers(); return self.wfile.write(data)
                return self._json({"error": "not found"}, 404)
            if p == "/favicon.ico":                # 브라우저가 매번 요청 — 500 대신 조용히 없음
                self.send_response(204); self.end_headers(); return
            if p == "/":
                self.path = "/index.html"
            return super().do_GET()
        except Exception as e:                     # noqa
            return self._json({"error": repr(e)}, 500)

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            req = self._body()
            if p == "/api/plan":
                return self._json(plan_payload(req))
            if p == "/api/estimate":
                return self._json(estimate_payload(req))
            if p == "/api/dryrun_save":
                return self._json(dryrun_save(req))
            if p == "/api/run":
                r, code = start_run(req); return self._json(r, code)
            if p == "/api/export":
                r, code = export_payload(req); return self._json(r, code)
            if p == "/api/goals":                  # ⚠ 본문은 위에서 이미 읽었다(req). 다시 읽으면 단일 스레드 서버가 통째로 멈춘다 (2026-09-09 실측)
                return self._json(goals_save(req))
            if p == "/api/version_name":           # {version, note} → outputs/version_names.json (별명 순번은 자동, 메모만 사람이)
                if not req.get("version"):
                    return self._json({"error": "version 이 필요합니다"}, 400)
                return self._json({"ok": True, "names": lessons.names_set(OUT, req["version"], req.get("note", ""))})
            if p == "/api/lessons/drafts":         # {limit?} → 새 메모만 AI 초안 호출 (push-cloud 회차·화면 버튼이 부른다). 돈 쓰는 자리 — GET 에 숨기지 않는다
                from . import notedraft
                before = len(notedraft.read_cache(OUT))
                cache = notedraft.ensure_drafts(OUT, lessons.summarize(OUT).get("notes") or [], limit=int(req.get("limit") or 20))
                return self._json({"ok": True, "made": max(0, len(cache) - before), **notedraft.totals(OUT)})
            if p == "/api/lessons/handoff":        # {note, en?, why?, kind?} → outputs/handoffs.jsonl — 승격감이 아닌 메모를 티모에게
                if not (req.get("note") or "").strip():
                    return self._json({"error": "메모가 비어 있습니다"}, 400)
                return self._json({"ok": True, "handoff": lessons.handoffs_add(OUT, req["note"], req.get("en", ""), req.get("why", ""), req.get("kind"), req.get("by"))})
            if p == "/api/lessons/promote":
                if not (req.get("en") or "").strip():
                    return self._json({"error": "프롬프트에 넣을 영어 문장이 필요합니다"}, 400)
                r = lessons.promote(req.get("note", ""), req["en"], req.get("where"))
                cloudpush.nudge("규칙 승격")   # 금지문이 바뀌면 학습 탭의 '지금 붙는 문장'이 달라진다
                return self._json(r)
            if p == "/api/review":
                r, code = save_review(req); return self._json(r, code)
            if p == "/api/demo_run":
                return self._json({"batch_id": demo_run(treatment=req.get("treatment", "nasolabial"), mode=req.get("mode", "selfie"), count=int(req.get("count", 12)),
                                                        target_pass=req.get("target_pass") or None, cost_cap=req.get("cost_cap") or None)})
            if p == "/api/queue/add":
                jobs = [queue().add(j) for j in (req.get("jobs") or [req])]; return self._json({"added": [j["job_id"] for j in jobs]})
            if p == "/api/queue/cancel":
                return self._json({"ok": bool(queue().cancel(req["job_id"]))})
            if p == "/api/queue/remove":
                return self._json({"ok": queue().remove(req["job_id"])})
            if p == "/api/queue/move":
                return self._json({"ok": queue().move(req["job_id"], req.get("direction", "up"))})
            if p == "/api/queue/pause":
                queue().set_paused(bool(req.get("paused", True))); return self._json({"paused": bool(req.get("paused", True))})
            if p == "/api/queue/clear_finished":
                queue().clear_finished(); return self._json({"ok": True})
            if p == "/api/demo":
                return self._json({"batch_id": make_demo(req.get("treatment", "nasolabial"), req.get("mode", "selfie"), int(req.get("count", 12)), series=req.get("series"))})
            return self._json({"error": "unknown"}, 404)
        except Exception as e:                     # noqa
            return self._json({"error": repr(e)}, 500)


def main():
    ap = argparse.ArgumentParser(description="B&A 로컬 대시보드")
    ap.add_argument("--port", type=int, default=8765); ap.add_argument("--demo", action="store_true", help="데모 배치 생성 후 실행")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    # 자동 업로드 훅(cloudpush)이 띄우는 node 가 '이미 떠 있는 로컬 API'를 못 찾고 헛돌지 않도록
    # 실제 포트를 자식에게 물려준다. 기본 포트가 아닐 때만 의미가 있지만, 조건을 두면 잊는다.
    os.environ["BNA_LOCAL_API_PORT"] = str(a.port)
    if a.demo:
        print("demo batch:", make_demo())
    queue()   # 러너 스레드 시작 (재시작 전 남은 작업 이어서 처리)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://localhost:{a.port}"; print("B&A dashboard:", url)
    if not a.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
