"""저장된 similarity 로 동일인 게이트만 다시 판정한다 (재생성·재임베딩 없음 = 비용 0).

문턱을 재캘리브레이션하면 새로 뽑는 장부터만 새 판정을 받는다 — 이미 뽑아 둔 장은
옛 문턱으로 굳은 채 검수 화면에 남는다. 그 화면이 곧 사람이 보는 근거이므로 같이 고친다.

⚠ 되돌릴 수 있다: `similarity`(실측값)는 건드리지 않고 `gate`/`passed`/`hard_fail` 만 다시 만든다.
   상수를 옛 값으로 되돌려 다시 돌리면 그대로 복원된다.
⚠ 못 잼(n/a)은 이 도구가 못 고친다 — 잰 적이 없어서 다시 판정할 원재료가 없다.
   그건 문턱 문제가 아니라 검출 문제다.
"""
import argparse, json
from pathlib import Path
import sys
sys.path.insert(0, "src")
# 이 PC 콘솔은 CP949 라 한글·em dash 가 UnicodeEncodeError 로 죽는다(도구가 아니라 출력이 죽는다)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                   # noqa: BLE001
    pass
from bna.qa import identity as I


def regate(out_dir: Path, apply: bool) -> dict:
    changed, same, na = [], 0, 0
    for m in sorted(out_dir.glob("*/*/meta.json")):
        try:
            d = json.loads(m.read_text(encoding="utf-8"))
        except Exception:                               # noqa: BLE001
            continue
        idn = d.get("identity") or {}
        s = idn.get("similarity")
        if s is None:
            na += 1
            continue
        old = idn.get("gate")
        new = "ok" if s >= I.THRESHOLD else ("review" if s >= I.REVIEW_BAND else "fail")
        if new == old:
            same += 1
            continue
        changed.append({"item": f'{d.get("batch_id")}/{d.get("item_id")}', "sim": round(s, 3),
                        "from": old, "to": new, "demo": bool(d.get("demo"))})
        if apply:
            idn.update({"gate": new, "hard_fail": new == "fail",
                        "passed": True if new == "ok" else (False if new == "fail" else None)})
            d["identity"] = idn
            m.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"threshold": I.THRESHOLD, "review_band": I.REVIEW_BAND,
            "unchanged": same, "not_measured": na, "changed": changed}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--apply", action="store_true", help="실제로 meta.json 을 고친다(기본은 미리보기)")
    a = ap.parse_args()
    r = regate(Path(a.out), a.apply)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    print(("적용함" if a.apply else "미리보기(--apply 로 반영)") + f" — 바뀜 {len(r['changed'])}건")
