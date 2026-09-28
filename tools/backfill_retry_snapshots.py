"""재시도 전 컷 되살리기 (2026-09-28 연서님 "그 배치 1·2번 시도 사진 PC에 있으면 검수함에 올려줘").

  python tools/backfill_retry_snapshots.py <batch_id> [--dry]

재시도로 조건을 다시 뽑으면 옛 인물 파일이 폴더에 남는다(파일 이름 앞부분이 달라서 안 덮인다). 화면은 meta 가 가리키는
마지막 쌍만 보여서 그 파일들이 안 보였다. 이 도구는 **최종 쌍이 아닌 파일 쌍**을 형제 항목 `<id>-t<n>`(시간순 번호)으로
옮겨 담는다(원본은 복사 — 지우지 않는다). 그 회차 meta 는 덮어써져 없으므로 구조·닮음은 지금 로컬로 다시 잰다(API 0).
⚠ 같은 인물 이름으로 다시 뽑힌 회차는 파일이 덮어써져 되살릴 수 없다 — 몇 번째가 없는지는 attempts_log 와 대 본다.
배치가 스스로 남기는 경로(batch.py `retry_snapshot`)는 09-28 이후 회차부터다.
"""
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bna.api import stem_of  # noqa: E402
from bna.spec import load  # noqa: E402
from bna.qa import identity, structure  # noqa: E402

A = sys.argv[1:]
DRY = "--dry" in A
BID = [a for a in A if not a.startswith("--")][0]


def main():
    bd = ROOT / "outputs" / BID
    for mp in sorted(bd.glob("*/meta.json")):
        m = json.loads(mp.read_text(encoding="utf-8"))
        if m.get("retry_snapshot"):
            continue
        d, iid = mp.parent, m["item_id"]
        cur = stem_of(m)
        olds = sorted([b for b in d.glob("*_before.jpg") if not b.name.startswith(cur + "_")
                       and b.with_name(b.name.replace("_before.jpg", "_after.jpg")).exists()],
                      key=lambda b: b.stat().st_mtime)
        n_fail = len(m.get("attempts_log") or [])
        print(f"{iid}: 시도 {m.get('attempt')}회 · 재시도 전 실패 {n_fail} · 남은 옛 쌍 {len(olds)}")
        logs = m.get("attempts_log") or []
        for k0, b in enumerate(olds, 1):
            a = b.with_name(b.name.replace("_before.jpg", "_after.jpg"))
            # 몇 번째 시도인지 = 파일 저장 시각과 가장 가까운 attempts_log 시각(같은 회차는 초 단위로 붙는다). 못 찾으면 시간순 번호.
            near = min(logs, key=lambda x: abs(x["at"] - b.stat().st_mtime)) if logs else None
            k = near["attempt"] if near and abs(near["at"] - b.stat().st_mtime) < 10 else k0
            sid = f"{iid}-t{k}"
            bi, ai = Image.open(b).convert("RGB"), Image.open(a).convert("RGB")
            st = structure.check(bi, ai, m.get("mode"), "nasolabial_marionette")
            idn = identity.check(bi, ai)
            st["copy"] = structure.clinical_copy_check(st, idn.get("similarity"), {"sim_max": 0.82, "align_min_pct": 1.0, "roll_deg": 10})
            tag = b.name[len(f"{m['treatment']}_{m['mode']}_"):-len(f"_{iid}_before.jpg")]   # 예: korea50sf · kolate_20sf
            snap = {**m, "item_id": sid, "retry_snapshot": True, "snapshot_of": iid, "backfilled": True,
                    "passed": False, "cost": 0.0, "structure": st, "identity": idn, "after_results": {},
                    "person_tag": tag, "fail_reasons": [], "vision": None,
                    "note": "재시도 전 컷(되살림) — 그 회차 프롬프트·검수는 원장에 없고, 구조·닮음은 다시 잰 값"}
            v = dict(m["variation"])                   # 화면 카드·파일 짝(stem_of)이 이 쌍을 가리키게 인물 칸(나라·나이·성별)을 맞춘다
            vv = load("variations.yaml")
            for c in vv["country"]:
                for ag in vv["age"]:
                    for g in vv["gender"]:
                        if f"{c}{ag}{g[0]}" == tag:
                            v["country"] = {"key": c, "text": vv["country"][c]}
                            v["age"] = {"key": ag, "text": vv["age"][ag]}
                            v["gender"] = {"key": g, "text": vv["gender"][g]}
            snap["variation"] = v
            print(f"   → {sid} {b.name}  닮음 {idn.get('similarity') and round(idn['similarity'], 3)} "
                  f"폭 {st.get('face_ratio_diff') and round(st['face_ratio_diff'], 3)} 밝기 {st.get('luma_diff') and round(st['luma_diff'], 3)}")
            if DRY:
                continue
            sd = d.parent / sid
            sd.mkdir(exist_ok=True)
            shutil.copy2(b, sd / b.name.replace(f"_{iid}_", f"_{sid}_"))
            shutil.copy2(a, sd / a.name.replace(f"_{iid}_", f"_{sid}_"))
            if (d / "mask.png").exists():
                shutil.copy2(d / "mask.png", sd / "mask.png")
            snap["mask_file"] = "mask.png" if (sd / "mask.png").exists() else None
            (sd / "meta.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
