"""씨앗 은행 파생 얼굴의 통과 여부 + 성별·나이 추정표 (2026-09-15 저녁 티모). 로컬 insightface 만 — 업로드 없음.

통과 = measure.py 의 `제씨앗과` 유사도 ≤ 대조군(서로 다른 실제 환자끼리) p90 ∧ 씨앗이 '같은 사람 의심' 묶음에 없음 ∧ 얼굴이 잡힘.
  p90 은 seed-measure.json 에서 읽는다(2026-09-09 실측 0.168) — 숫자를 코드에 박지 않는다.
산출: config/seedbank.yaml 의 `attrs` 경로(teemo/out/seed-attrs.json) — 숫자·익명 파일명만. 얼굴은 teemo-raw 밖으로 안 나간다.
사용: .venv/Scripts/python.exe tools/seedbank_attrs.py [은행키]      # 기본 pilot. 2026-09-16 은행이 시술별로 갈려 키를 받는다
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8")
from bna.qa import identity  # noqa: E402
from bna.seedbank import age_bucket  # noqa: E402
from bna.spec import load  # noqa: E402


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else "pilot"
    c = dict(load("seedbank.yaml"))
    b = (c.get("banks") or {}).get(key)
    if b:                                          # 은행별 경로가 옛 키(pool_dir/attrs)를 대신한다
        c.update({"pool_dir": b["derived"], "measure": b["measure"], "prep": b["prep"], "attrs": b["attrs"]})
    elif key != "pilot":
        sys.exit(f"config/seedbank.yaml banks 에 '{key}' 가 없다")
    meas = json.loads(Path(c["measure"]).read_text(encoding="utf-8"))
    prep = json.loads(Path(c["prep"]).read_text(encoding="utf-8"))
    p90 = meas["대조군_씨앗끼리(서로 다른 실제 사람)"]["p90"]
    dup = {x for pr in (prep.get("씨앗끼리_같은사람_의심(≥0.45)") or []) for x in (pr["a"], pr["b"])}
    app = identity._model()
    if app is None:
        sys.exit("insightface 없음 — 속성을 못 잰다")
    pdir, rows = Path(c["pool_dir"]), []
    for r in meas["건별"]:
        f = pdir / r["파생"]
        faces = app.get(np.asarray(Image.open(f).convert("RGB"))[:, :, ::-1]) if f.is_file() else []
        face = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1])) if faces else None
        row = {"file": r["파생"], "seed_mode": r["강도"], "own_sim": r["제씨앗과"], "p90": p90,
               "dup_seed": r["씨앗"] in dup, "face": face is not None,
               "gender": None if face is None else ("male" if int(face.gender) == 1 else "female"),
               "age": None if face is None else int(face.age),
               "age_bucket": None if face is None else age_bucket(float(face.age))}
        row["passed"] = bool(r["제씨앗과"] <= p90 and not row["dup_seed"] and row["face"])
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    out = Path(c["attrs"])
    out.write_text(json.dumps({"p90": p90, "pool": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", out, "· 통과", sum(r["passed"] for r in rows), "/", len(rows))


if __name__ == "__main__":
    main()
