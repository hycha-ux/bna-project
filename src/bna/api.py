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
  POST /api/review                 {batch, item, pick, tags, note} → outputs/<batch>/<item>/review.json
  GET  /files/<batch>/<item>/<f>   이미지
"""
import argparse, asyncio, json, random, threading, time, uuid, webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from .spec import ROOT, load, build_prompts, PERSON_AXES, SCENE_AXES
from .planner import plan_batch, distribution
from .stats import load_items, summarize
from . import progress as prog

OUT = ROOT / "outputs"
WEB = ROOT / "web"
RUNNING = {}   # batch_id → {"status", "started", "error"}


# ---------- 데이터 ----------
def config_payload():
    t = load("treatments.yaml"); v = load("variations.yaml")
    axes = {a: list(v[a]) for a in PERSON_AXES + SCENE_AXES}
    return {"treatments": {k: {"name_ko": x.get("name_ko", k), "modes": list(x.get("modes", {}))} for k, x in t.items()},
            "modes": ["selfie", "clinical"], "axes": axes, "mode_rules": v.get("mode_rules", {}),
            "pricing": load("pricing.yaml"), "checklist": list(load("qa_checklist.yaml")["items"])}


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
    return sorted((batch_summary(d) for d in OUT.iterdir() if d.is_dir()), key=lambda b: b["mtime"], reverse=True)


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


def demo_run(treatment="nasolabial", mode="selfie", count=12, seed=None, item_seconds=2.0, concurrency=3):
    """실제 호출 없이 progress.json 을 시간에 따라 갱신하고, 끝난 항목은 make_demo 와 같은 자리표시 결과를 쓴다."""
    from PIL import Image, ImageDraw
    seed = seed if seed is not None else random.randint(0, 9999); rng = random.Random(seed)
    bid = time.strftime("%Y%m%d-%H%M%S") + "-sim"; d = OUT / bid; d.mkdir(parents=True, exist_ok=True)
    plans = plan_batch(mode, count, seed); checklist = list(load("qa_checklist.yaml")["items"])
    (d / "batch.json").write_text(json.dumps({"batch_id": bid, "treatment": treatment, "mode": mode, "count": count, "kind": "sim", "seed": seed,
                                              "created_at": time.time()}, ensure_ascii=False))
    pgs = prog.Progress(d, count); RUNNING[bid] = {"status": "running", "started": time.time(), "error": None}

    def one(i, v):
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
                pgs.set(iid, "passed", passed=True, fail_reasons=[]); break
            pgs.set(iid, "retry" if attempt < 3 else "failed", passed=False, fail_reasons=fails)
        return meta

    def worker():
        from concurrent.futures import ThreadPoolExecutor
        try:
            with ThreadPoolExecutor(concurrency) as ex:
                items = list(ex.map(lambda iv: one(*iv), enumerate(plans)))
            (d / "stats.json").write_text(json.dumps(summarize(items), ensure_ascii=False, indent=1), encoding="utf-8")
            pgs.finish(); RUNNING[bid]["status"] = "done"
        except Exception as e:                      # noqa
            pgs.finish(error=repr(e)); RUNNING[bid].update(status="error", error=repr(e))
    threading.Thread(target=worker, daemon=True).start()
    return bid


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
            if p.startswith("/api/batches/") and p.endswith("/progress"):
                r = prog.read(OUT / p.split("/")[3]); return self._json(r or {"error": "no progress"}, 200 if r else 404)
            if p.startswith("/api/batches/"):
                r = batch_detail(p.split("/")[3]); return self._json(r or {"error": "not found"}, 200 if r else 404)
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
            if p == "/api/review":
                r, code = save_review(req); return self._json(r, code)
            if p == "/api/demo_run":
                return self._json({"batch_id": demo_run(req.get("treatment", "nasolabial"), req.get("mode", "selfie"), int(req.get("count", 12)))})
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
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://localhost:{a.port}"; print("B&A dashboard:", url)
    if not a.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
