"""배치 큐: outputs/queue.json 에 작업을 쌓고 러너 스레드가 한 번에 하나씩 순서대로 실행한다.

job: {job_id, treatment, mode, count, seed, fixed, gen, edit, qa, target_pass, cost_cap, simulate,
      status: queued|running|done|error|cancelled, batch_id, created_at, started_at, finished_at, result, error}
큐 상태: paused 면 진행 중인 작업은 끝까지 가고 다음 작업을 집지 않는다.
"""
import json, os, threading, time, uuid
from pathlib import Path

ACTIVE = ("queued", "running")


class Queue:
    def __init__(self, out_dir: Path, run_job):
        """run_job(job, on_batch) -> (batch_id, result_dict). 블로킹. on_batch(batch_id) 는 배치 폴더가 생기면 즉시 호출."""
        self.path = out_dir / "queue.json"; out_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock(); self.run_job = run_job
        self.data = {"paused": False, "jobs": []}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        for j in self.data["jobs"]:                     # 서버 재시작 전 돌던 작업은 오류로 정리
            if j["status"] == "running":
                j.update(status="error", error="서버 재시작으로 중단됨", finished_at=time.time())
        self._flush(); self.wake = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    # ---------- 조작 ----------
    def add(self, spec: dict) -> dict:
        job = {"job_id": uuid.uuid4().hex[:8], "status": "queued", "batch_id": None, "created_at": time.time(),
               "started_at": None, "finished_at": None, "result": None, "error": None,
               "treatment": spec["treatment"], "mode": spec["mode"], "count": int(spec.get("count", 10)),
               "seed": spec.get("seed") or None, "fixed": {k: v for k, v in (spec.get("fixed") or {}).items() if v},
               "gen": spec.get("gen") or None, "edit": spec.get("edit") or None, "qa": spec.get("qa") or None,   # None = 모드 기본값(providers.yaml)
               "target_pass": int(spec["target_pass"]) if spec.get("target_pass") else None,
               "cost_cap": float(spec["cost_cap"]) if spec.get("cost_cap") else None,
               "simulate": bool(spec.get("simulate", False)), "label": spec.get("label", "")}
        with self.lock:
            self.data["jobs"].append(job); self._flush()
        self.wake.set(); return job

    def cancel(self, job_id):
        with self.lock:
            j = self._get(job_id)
            if j and j["status"] == "queued":
                j.update(status="cancelled", finished_at=time.time()); self._flush(); return j
        return None

    def remove(self, job_id):
        with self.lock:
            j = self._get(job_id)
            if j and j["status"] != "running":
                self.data["jobs"].remove(j); self._flush(); return True
        return False

    def move(self, job_id, direction):
        with self.lock:
            jobs = self.data["jobs"]; j = self._get(job_id)
            if not j or j["status"] != "queued":
                return False
            i = jobs.index(j); k = i + (-1 if direction == "up" else 1)
            while 0 <= k < len(jobs) and jobs[k]["status"] != "queued":
                k += (-1 if direction == "up" else 1)
            if 0 <= k < len(jobs):
                jobs[i], jobs[k] = jobs[k], jobs[i]; self._flush(); return True
        return False

    def set_paused(self, paused: bool):
        with self.lock:
            self.data["paused"] = bool(paused); self._flush()
        if not paused:
            self.wake.set()

    def clear_finished(self):
        with self.lock:
            self.data["jobs"] = [j for j in self.data["jobs"] if j["status"] in ACTIVE]; self._flush()

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.data))

    # ---------- 러너 ----------
    def _next(self):
        with self.lock:
            if self.data["paused"] or any(j["status"] == "running" for j in self.data["jobs"]):
                return None
            return next((j for j in self.data["jobs"] if j["status"] == "queued"), None)

    def _loop(self):
        while True:
            j = self._next()
            if not j:
                self.wake.wait(2); self.wake.clear(); continue
            with self.lock:
                j.update(status="running", started_at=time.time()); self._flush()
            try:
                bid, result = self.run_job(j, lambda bid: self._set_bid(j, bid))
                with self.lock:
                    j.update(status="done", batch_id=bid, result=result, finished_at=time.time())
            except Exception as e:                      # noqa
                with self.lock:
                    j.update(status="error", error=repr(e), finished_at=time.time())
            with self.lock:
                self._flush()

    def _set_bid(self, j, bid):
        with self.lock:
            j["batch_id"] = bid; self._flush()

    def _get(self, job_id):
        return next((j for j in self.data["jobs"] if j["job_id"] == job_id), None)

    def _flush(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8"); os.replace(tmp, self.path)
