"""배치 진행 기록: outputs/<batch>/progress.json. 대시보드가 2초 간격으로 읽는다.

스키마: {planned, started_at, finished_at, error, items: {item_id: {stage, attempt, passed, fail_reasons, updated_at, elapsed}}}
stage: queued → before → after → postprocess → qa → (retry → before …) → passed | failed | skipped(정지 조건 도달로 미실행)
"""
import json, os, threading, time
from pathlib import Path

from . import cloudpush   # 사진 1장이 판정될 때마다 클라우드로 밀어 올린다(막지 않는 fire-and-forget)

STAGES = ["queued", "before", "after", "postprocess", "qa", "retry", "passed", "failed", "skipped"]


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
        # 락 밖에서 부른다 — 훅은 즉시 반환하지만, 락 안에서 부르는 습관은 언젠가 생성을 멈춘다.
        if stage in ("passed", "failed"):
            cloudpush.nudge(f"사진 판정 {item_id} {stage}")

    def finish(self, error=None, stopped=None):
        with self.lock:
            for it in self.data["items"].values():
                if it["stage"] == "queued":
                    it["stage"] = "skipped"
            self.data["finished_at"] = time.time(); self.data["error"] = error; self.data["stopped"] = stopped; self._flush()
        cloudpush.nudge("배치 종료")

    def totals(self):
        with self.lock:
            its = self.data["items"].values()
            return sum(1 for i in its if i["stage"] == "passed"), sum(float(i.get("cost") or 0) for i in its)

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
    done = counts["passed"] + counts["failed"] + counts["skipped"]
    active = [it for it in items if it["stage"] not in ("queued", "passed", "failed")]
    elapsed = (d["finished_at"] or time.time()) - d["started_at"]
    per_item = elapsed / done if done else None
    remaining = d["planned"] - done
    d["summary"] = {"counts": counts, "done": done, "planned": d["planned"], "active": len(active), "retries": sum(max(0, it["attempt"] - 1) for it in items),
                    "elapsed_s": round(elapsed), "eta_s": round(per_item * remaining / max(1, len(active) or 1)) if per_item and remaining else None,
                    "running": d["finished_at"] is None, "stopped": d.get("stopped"), "cost": round(sum(float(i.get("cost") or 0) for i in items), 4), "pass_rate": round(counts["passed"] / (counts["passed"] + counts["failed"]), 3) if (counts["passed"] + counts["failed"]) else None}
    return d
