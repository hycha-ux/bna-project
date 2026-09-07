"""통과율 통계 (A6): 축별·검수 항목별·프롬프트 버전별. manifest 를 읽어 집계."""
import csv, json
from collections import Counter, defaultdict
from pathlib import Path


def load_items(batch_dir: Path) -> list:
    items = []
    for m in batch_dir.glob("*/meta.json"):
        items.append(json.loads(m.read_text(encoding="utf-8")))
    return items


def summarize(items: list) -> dict:
    n = len(items); passed = [i for i in items if i.get("passed")]
    out = {"total": n, "passed": len(passed), "pass_rate": round(len(passed) / n, 3) if n else 0,
           "attempts_per_pass": round(sum(i.get("attempt", 1) for i in items) / max(len(passed), 1), 2),
           "cost_per_pass": round(sum(i.get("cost", 0) for i in items) / max(len(passed), 1), 4),
           "by_axis": {}, "fail_reasons": Counter(), "by_prompt_version": defaultdict(lambda: [0, 0])}
    for it in items:
        for axis, val in it.get("variation", {}).items():
            d = out["by_axis"].setdefault(axis, defaultdict(lambda: [0, 0]))
            d[val["key"]][0] += 1; d[val["key"]][1] += bool(it.get("passed"))
        for r in it.get("fail_reasons", []):
            out["fail_reasons"][r] += 1
        pv = out["by_prompt_version"][it.get("prompt_version", "?")]
        pv[0] += 1; pv[1] += bool(it.get("passed"))
    out["by_axis"] = {a: {k: {"n": v[0], "pass": round(v[1] / v[0], 2)} for k, v in d.items()} for a, d in out["by_axis"].items()}
    out["by_prompt_version"] = {k: {"n": v[0], "pass": round(v[1] / v[0], 2)} for k, v in out["by_prompt_version"].items()}
    out["fail_reasons"] = dict(out["fail_reasons"])
    return out


def write_manifest(batch_dir: Path, items: list):
    cols = ["item_id", "treatment", "mode", "attempt", "passed", "fail_reasons", "prompt_version", "cost"]
    with (batch_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(cols + ["country", "age", "gender"])
        for it in items:
            v = it.get("variation", {})
            w.writerow([it.get(c, "") if c != "fail_reasons" else "|".join(it.get(c, [])) for c in cols]
                       + [v.get("country", {}).get("key"), v.get("age", {}).get("key"), v.get("gender", {}).get("key")])
