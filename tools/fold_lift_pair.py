"""B+A 나란히 만들기 (2026-09-28 7차 연서님 "B 결과 위에 A를 얹은 버전을 같이 — B만 / B+A 나란히").

  python tools/fold_lift_pair.py <batch_id> [--strength 1.0]

배치의 각 항목(재시도 전 컷 `-t<n>`·이미 만든 `-BA` 제외)의 최종 After 에 팔자 그림자 들어올리기(bna.foldlift, 비용 0)를
얹어 형제 항목 `<id>-BA` 로 저장한다 — 검수함에 한 줄로 뜬다. Before 는 같은 파일, 원 항목은 그대로 둔다.
비교 그림은 tools/fold_zoom.py 로 "<id>=B만" "<id>-BA=B+A" 를 나란히 준다.
"""
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bna.api import stem_of  # noqa: E402
from bna.foldlift import lift  # noqa: E402

A = sys.argv[1:]
BID = A[0]
STRENGTH = float(A[A.index("--strength") + 1]) if "--strength" in A else 1.0


def main():
    bd = ROOT / "outputs" / BID
    for mp in sorted(bd.glob("*/meta.json")):
        m = json.loads(mp.read_text(encoding="utf-8"))
        if m.get("retry_snapshot") or m.get("fold_lift"):
            continue
        d, iid = mp.parent, m["item_id"]
        st = stem_of(m)
        b = d / f"{st}_before.jpg"
        a = d / f"{st}_after.jpg"
        if not (b.exists() and a.exists()):
            print(iid, "파일 짝 없음 — 건너뜀"); continue
        res, info = lift(Image.open(a), strength=STRENGTH)
        sid = f"{iid}-BA"
        sd = bd / sid; sd.mkdir(exist_ok=True)
        shutil.copy2(b, sd / b.name.replace(f"_{iid}_", f"_{sid}_"))
        res.save(sd / a.name.replace(f"_{iid}_", f"_{sid}_"), quality=94)
        if (d / "mask.png").exists():
            shutil.copy2(d / "mask.png", sd / "mask.png")
        snap = {**m, "item_id": sid, "fold_lift": info, "fold_lift_of": iid, "cost": 0.0,
                "note": "B+A — B(새로 그린 After) 위에 팔자 그림자 들어올리기(bna.foldlift, 모델 호출 0)"}
        (sd / "meta.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(iid, "→", sid, info)


if __name__ == "__main__":
    main()
