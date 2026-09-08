"""배치 진행 기록: outputs/<batch>/progress.json. 대시보드가 2초 간격으로 읽는다.

스키마: {planned, started_at, finished_at, error, items: {item_id: {stage, attempt, passed, fail_reasons, updated_at, elapsed}}}
stage: queued → before → after → postprocess → qa → (retry → before …) → passed | failed
"""
import json, os, threading, time
from pathlib import Path

STAGES = ["queued", "before", "after", "postprocess", "qa", "retry", "passed", "failed"]


class Progress:
    def __init__(self, batch_dir: Path, planned: int):
        self.path = batch_dir / "progress.json"
        self.lock = threading.Lock()
        self.data = {"planned": planned, "started_at": time.time(), "finished_at": None, "error": None,
                     "items": {f"{i:04d}": {"stage": "queued", "attempt": 0, "passed": None, "fail_reasons": [], "updated_at": None, "elapsed": 0.0}
                               for i in range(planned)}}
        self._t0 = {}
        self._flush()

    def set(self, item_id: str, stage: str, **kw):
        with self.lock:
            it = self.data["items"].setdefault(item_id, {"stage": "queued", "attempt": 0, "passed": None, "fail_reasons": [], "elapsed": 0.0})
            now = time.time()
            if stage == "before" and it["stage"] in ("queued", "retry"):
                self._t0[item_id] = now
            it.update(stage=stage, updated_at=now, **kw)
            if stage in ("passed", "failed") and item_id in self._t0:
                it["elapsed"] = round(now - self._t0[item_id], 1)
            self._flush()

    def finish(self, error=None):
        with self.lock:
            self.data["finished_at"] = time.time(); self.data["error"] = error; self._flush()

    def _flush(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)


def read(batch_dir: Path):
    p = batch_dir / "progress.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    items = d["items"].values()
    counts = {s: 0 for s in STAGES}
    for it in items:
        counts[it["stage"]] = counts.get(it["stage"], 0) + 1
    done = counts["passed"] + counts["failed"]
    active = [it for it in items if it["stage"] not in ("queued", "passed", "failed")]
    elapsed = (d["finished_at"] or time.time()) - d["started_at"]
    per_item = elapsed / done if done else None
    remaining = d["planned"] - done
    d["summary"] = {"counts": counts, "done": done, "planned": d["planned"], "active": len(active), "retries": sum(max(0, it["attempt"] - 1) for it in items),
                    "elapsed_s": round(elapsed), "eta_s": round(per_item * remaining / max(1, len(active) or 1)) if per_item and remaining else None,
                    "running": d["finished_at"] is None, "pass_rate": round(counts["passed"] / done, 3) if done else None}
    return d
