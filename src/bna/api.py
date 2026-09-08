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
  GET  /api/library                선택(pick)된 항목 전체 (배치 무관), 시술·유형 요약
  GET  /api/overview?days=14       대시보드 집계 (일별 생성·통과·탈락 사유, 시술·조건별 통과율, 오늘 시간대별)
  POST /api/export                 {treatment?, mode?} → outputs/exports/<ts>/ 에 선택 항목 복사 + manifest.csv + zip
  GET  /exports/<name>.zip         내보낸 zip 다운로드
  GET  /files/<batch>/<item>/<f>   이미지
"""
import argparse, asyncio, csv, json, random, shutil, threading, time, uuid, webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from .spec import ROOT, load, build_prompts, PERSON_AXES, SCENE_AXES
from .planner import plan_batch, distribution
from .stats import load_items, summarize
from . import progress as prog
from .queue import Queue

OUT = ROOT / "outputs"
WEB = ROOT / "web"
RUNNING = {}   # batch_id → {"status", "started", "error"}


# ---------- 데이터 ----------
def config_payload():
    t = load("treatments.yaml"); v = load("variations.yaml")
    axes = {a: list(v[a]) for a in PERSON_AXES + SCENE_AXES}
    return {"treatments": {k: {"name_ko": x.get("name_ko", k), "modes": list(x.get("modes", {}))} for k, x in t.items()},
            "modes": ["selfie", "clinical"], "axes": axes, "mode_rules": v.get("mode_rules", {}),
            "pricing": load("pricing.yaml"), "checklist": list(load("qa_checklist.yaml")["items"]), "out_dir": str(OUT)}


def _plans(req):
    fixed = {k: val for k, val in (req.get("fixed") or {}).items() if val}
    seed = req.get("seed"); seed = int(seed) if seed not in (None, "") else None
    return plan_batch(req["mode"], int(req.get("count", 4)), seed, fixed), seed, fixed


def plan_payload(req):
    plans, seed, fixed = _plans(req)
    specs = [build_prompts(req["treatment"], req["mode"], v, None if seed is None else seed * 1000 + i) for i, v in enumerate(plans)]
    return {"count": len(plans), "distribution": distribution(plans), "items": specs}


def estimate_payload(req, expected_pass_rate=0.5):
    p = load("pricing.yaml"); gen, edit, qa = req.get("gen", "gemini"), req.get("edit", "gemini"), req.get("qa", "gemini")
    per_try = p[gen]["generate"] + p[edit]["edit" if req["mode"] == "clinical" else "generate"] + p[qa]["qa"]
    n = int(req.get("count", 1)); tries = n * min(3, 1 / max(expected_pass_rate, 0.05))
    return {"items": n, "expected_calls": round(tries), "expected_cost_usd": round(per_try * tries, 2), "per_try_usd": round(per_try, 4)}


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
                  req.get("gen", "gemini"), req.get("edit", "gemini"), req.get("qa", "gemini"))
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
    return sorted((batch_summary(d) for d in OUT.iterdir() if d.is_dir() and d.name != "exports"), key=lambda b: b["mtime"], reverse=True)


def batch_detail(bid: str):
    d = OUT / bid
    if not d.is_dir():
        return None
    rv = _reviews(d); items = []
    for m in sorted(load_items(d), key=lambda x: x.get("item_id", "")):
        iid = m["item_id"]; files = sorted(p.name for p in (d / iid).glob("*.jpg"))
        m["before_file"] = next((f for f in files if f.endswith("_before.jpg")), None)
        m["after_file"] = next((f for f in files if f.endswith("_after.jpg")), None)
        m["review"] = rv.get(iid, {})
        items.append(m)
    return {**batch_summary(d), "items": items}


def save_review(req):
    d = OUT / req["batch"] / req["item"]
    if not d.is_dir():
        return {"error": "item not found"}, 404
    rv = {"pick": req.get("pick"), "tags": req.get("tags", []), "note": req.get("note", ""), "updated_at": time.time()}
    (d / "review.json").write_text(json.dumps(rv, ensure_ascii=False, indent=1), encoding="utf-8")
    return rv, 200


# ---------- 대시보드 집계 ----------
def overview_payload(days=14):
    """일별 생성·통과·탈락 사유, 시술별·조건별 통과율, 오늘 시간대별, 라이브러리 요약. dry_run 제외."""
    import datetime as dt
    now = time.time(); today = dt.date.today()
    day_keys = [(today - dt.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    daily = {k: {"total": 0, "passed": 0, "cost": 0.0, "fails": {}} for k in day_keys}
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
            created = info.get("created_at") or d.stat().st_mtime
            key = dt.date.fromtimestamp(created).isoformat(); in_win = key in daily
            in_prev = not in_win and created >= now - 2 * days * 86400
            for m in d.glob("*/meta.json"):
                it = json.loads(m.read_text(encoding="utf-8"))
                if it.get("dry_run"):
                    continue
                p = bool(it.get("passed")); c = float(it.get("cost") or 0)
                if in_win:
                    dd = daily[key]; dd["total"] += 1; dd["passed"] += p; dd["cost"] += c
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
    return {"days": days, "day_keys": day_keys, "daily": daily, "window": {"total": tot, "passed": pas, "cost": round(cost, 3)}, "prev": prev,
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
            meta = json.loads(m.read_text(encoding="utf-8")); files = sorted(p.name for p in d.glob("*.jpg"))
            items.append({"batch_id": d.parent.name, "item_id": d.name, "treatment": meta.get("treatment"), "mode": meta.get("mode"),
                          "variation": meta.get("variation", {}), "review": rv, "passed": meta.get("passed"), "demo": meta.get("demo", False),
                          "before_file": next((f for f in files if f.endswith("_before.jpg")), None),
                          "after_file": next((f for f in files if f.endswith("_after.jpg")), None), "picked_at": rv.get("updated_at")})
    items.sort(key=lambda x: x.get("picked_at") or 0, reverse=True)
    summary = {}
    for it in items:
        summary.setdefault(it["treatment"], {}).setdefault(it["mode"], 0); summary[it["treatment"]][it["mode"]] += 1
    return {"items": items, "summary": summary, "total": len(items)}


def export_payload(req):
    lib = library_payload()["items"]
    sel = [i for i in lib if (not req.get("treatment") or i["treatment"] == req["treatment"]) and (not req.get("mode") or i["mode"] == req["mode"])]
    if not sel:
        return {"error": "내보낼 선택 항목이 없습니다"}, 400
    name = time.strftime("%Y%m%d-%H%M%S") + "-" + (req.get("treatment") or "all") + "-" + (req.get("mode") or "all")
    root = OUT / "exports" / name; root.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in sel:
        sub = root / f'{i["treatment"]}_{i["mode"]}'; sub.mkdir(exist_ok=True); src = OUT / i["batch_id"] / i["item_id"]
        for f in (i["before_file"], i["after_file"]):
            if f:
                shutil.copy2(src / f, sub / f)
        v = i["variation"]
        rows.append([i["treatment"], i["mode"], i["batch_id"], i["item_id"], i["before_file"], i["after_file"],
                     v.get("country", {}).get("key"), v.get("age", {}).get("key"), v.get("gender", {}).get("key"), v.get("angle", {}).get("key"),
                     v.get("framing", {}).get("key"), "|".join(i["review"].get("tags", [])), i["review"].get("note", "")])
    with (root / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["treatment", "mode", "batch", "item", "before", "after", "country", "age", "gender", "angle", "framing", "tags", "note"]); w.writerows(rows)
    zip_path = shutil.make_archive(str(root), "zip", root_dir=root)
    return {"name": name, "count": len(sel), "dir": str(root), "zip": f"/exports/{name}.zip", "zip_bytes": Path(zip_path).stat().st_size}, 200


# ---------- 데모 배치 (키 없이 화면 확인용) ----------
def make_demo(treatment="nasolabial", mode="selfie", count=12, seed=7):
    """실제 생성 없이 PIL 로 그린 자리표시 이미지 + 무작위 검수 결과. 이름에 demo 가 붙는다."""
    from PIL import Image, ImageDraw
    rng = random.Random(seed)
    bid = time.strftime("%Y%m%d-%H%M%S") + "-demo"; d = OUT / bid; d.mkdir(parents=True, exist_ok=True)
    plans = plan_batch(mode, count, seed)
    checklist = list(load("qa_checklist.yaml")["items"]); items = []
    for i, v in enumerate(plans):
        spec = build_prompts(treatment, mode, v, seed * 1000 + i); iid = f"{i:04d}"; (d / iid).mkdir(exist_ok=True)
        passed = rng.random() < 0.6; attempt = 1 if passed and rng.random() < 0.7 else rng.randint(1, 3)
        fails = [] if passed else rng.sample(["structure", "identity", "vision:hair", "vision:ai_look", "vision:fingers", "duplicate"], rng.randint(1, 2))
        scores = {k: (rng.randint(7, 10) if passed else rng.randint(4, 9)) for k in checklist}
        stem = f'{treatment}_{mode}_{v["country"]["key"]}{v["age"]["key"]}{v["gender"]["key"][0]}_{iid}'
        hue = rng.randint(0, 360)
        for kind in ("before", "after"):
            img = Image.new("RGB", (400, 500), f"hsl({hue},{35 if kind == 'before' else 50}%,{70 if kind == 'before' else 78}%)")
            dr = ImageDraw.Draw(img); dr.ellipse((100, 90, 300, 330), fill=f"hsl({hue},30%,88%)")
            dr.text((20, 460), f"DEMO {kind.upper()} #{iid}", fill="black"); dr.text((20, 20), "placeholder — no real generation", fill="black")
            img.save(d / iid / f"{stem}_{kind}.jpg", quality=80)
        meta = {**spec, "item_id": iid, "batch_id": bid, "prompt_version": "demo", "attempt": attempt, "passed": passed,
                "fail_reasons": fails, "cost": round(0.085 * attempt, 3), "demo": True,
                "structure": {"passed": "structure" not in fails, "align_err": round(rng.uniform(0, 12), 1)},
                "identity": {"hard_fail": "identity" in fails, "sim": round(rng.uniform(0.35, 0.8), 2)},
                "vision": {"scores": scores, "failed_items": [f.split(":")[1] for f in fails if f.startswith("vision:")]}}
        (d / iid / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"); items.append(meta)
    (d / "stats.json").write_text(json.dumps(summarize(items), ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "batch.json").write_text(json.dumps({"batch_id": bid, "treatment": treatment, "mode": mode, "count": count, "kind": "demo",
                                              "seed": seed, "created_at": time.time()}, ensure_ascii=False))
    return bid


def sim_batch(treatment="nasolabial", mode="selfie", count=12, seed=None, item_seconds=2.0, concurrency=3, target_pass=None, cost_cap=None,
              fixed=None, on_batch=None):
    """실제 호출 없이 progress.json 을 시간에 따라 갱신하고, 끝난 항목은 make_demo 와 같은 자리표시 결과를 쓴다. 블로킹."""
    from PIL import Image, ImageDraw
    from concurrent.futures import ThreadPoolExecutor
    seed = seed if seed is not None else random.randint(0, 9999); rng = random.Random(seed)
    bid = time.strftime("%Y%m%d-%H%M%S") + "-sim"; d = OUT / bid; d.mkdir(parents=True, exist_ok=True)
    plans = plan_batch(mode, count, seed, fixed or {}); checklist = list(load("qa_checklist.yaml")["items"])
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
        spec = build_prompts(treatment, mode, v, seed * 1000 + i); iid = f"{i:04d}"; (d / iid).mkdir(exist_ok=True)
        meta = None
        for attempt in range(1, 4):
            for stage in ("before", "after", "postprocess", "qa"):
                pgs.set(iid, stage, attempt=attempt); time.sleep(item_seconds / 4 * rng.uniform(0.6, 1.4))
            passed = rng.random() < 0.6
            fails = [] if passed else rng.sample(["structure", "identity", "vision:hair", "vision:ai_look", "vision:fingers"], rng.randint(1, 2))
            stem = f'{treatment}_{mode}_{v["country"]["key"]}{v["age"]["key"]}{v["gender"]["key"][0]}_{iid}'; hue = rng.randint(0, 360)
            for kind in ("before", "after"):
                img = Image.new("RGB", (400, 500), f"hsl({hue},{35 if kind == 'before' else 50}%,{70 if kind == 'before' else 78}%)")
                dr = ImageDraw.Draw(img); dr.ellipse((100, 90, 300, 330), fill=f"hsl({hue},30%,88%)"); dr.text((20, 460), f"SIM {kind.upper()} #{iid}", fill="black")
                img.save(d / iid / f"{stem}_{kind}.jpg", quality=80)
            meta = {**spec, "item_id": iid, "batch_id": bid, "prompt_version": "sim", "attempt": attempt, "passed": passed, "fail_reasons": fails,
                    "cost": round(0.085 * attempt, 3), "demo": True, "structure": {"passed": "structure" not in fails}, "identity": {"hard_fail": "identity" in fails},
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
                  target_pass=job["target_pass"], cost_cap=job["cost_cap"])
    if job["simulate"]:
        return sim_batch(on_batch=on_batch, **common)
    from .batch import Batch
    b = Batch(gen=job["gen"], edit=job["edit"], qa=job["qa"], **common)
    (b.dir / "batch.json").write_text(json.dumps({"batch_id": b.batch_id, "treatment": b.treatment, "mode": b.mode, "count": b.count, "kind": "run",
                                                  "target_pass": b.target_pass, "cost_cap": b.cost_cap, "job_id": job["job_id"], "created_at": time.time()}, ensure_ascii=False))
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
        per_try = p[j["gen"]]["generate"] + p[j["edit"]]["edit" if j["mode"] == "clinical" else "generate"] + p[j["qa"]]["qa"]
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
            if p == "/api/library":
                return self._json(library_payload())
            if p.startswith("/api/overview"):
                from urllib.parse import parse_qs
                days = int(parse_qs(urlparse(self.path).query).get("days", ["14"])[0]); return self._json(overview_payload(days))
            if p.startswith("/exports/") and p.endswith(".zip"):
                f = (OUT / "exports" / p[len("/exports/"):]).resolve()
                if (OUT / "exports").resolve() in f.parents and f.is_file():
                    data = f.read_bytes(); self.send_response(200); self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition", f'attachment; filename="{f.name}"'); self.send_header("Content-Length", str(len(data))); self.end_headers(); return self.wfile.write(data)
                return self._json({"error": "not found"}, 404)
            if p.startswith("/files/"):
                f = (OUT / p[len("/files/"):]).resolve()
                if OUT.resolve() in f.parents and f.is_file():
                    data = f.read_bytes(); self.send_response(200); self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data))); self.end_headers(); return self.wfile.write(data)
                return self._json({"error": "not found"}, 404)
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
                return self._json({"batch_id": make_demo(req.get("treatment", "nasolabial"), req.get("mode", "selfie"), int(req.get("count", 12)))})
            return self._json({"error": "unknown"}, 404)
        except Exception as e:                     # noqa
            return self._json({"error": repr(e)}, 500)


def main():
    ap = argparse.ArgumentParser(description="B&A 로컬 대시보드")
    ap.add_argument("--port", type=int, default=8765); ap.add_argument("--demo", action="store_true", help="데모 배치 생성 후 실행")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
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
