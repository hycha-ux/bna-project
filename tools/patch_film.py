"""직후 패치 막 합성 — 손으로 돌리는 입구. 정본 = src/bna/patchfilm.py (배치와 같은 코드를 쓴다).

  python tools/patch_film.py <패치 없는 직후컷.jpg> <출력.jpg> [--seed N] [--debug]
  python tools/patch_film.py --tiles <사진.jpg> <출력.jpg>
  python tools/patch_film.py --compare <v57.jpg> <v58.jpg> <v59.jpg> <출력.png>
  python tools/patch_film.py --into-batch <배치ID> [--seed N]   # 이미 끝난 NO_PATCH 배치의 직후 After 에 얹기(원본은 _raw 로 보관)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PIL import Image  # noqa: E402
from bna import patchfilm as PF  # noqa: E402


def into_batch(bid, seed=None):
    """09-29 v59 배치(20260929-140515-3e05)는 배치 연결 전에 돌아서 대시보드에 원본이 떴다 — 그 자리에 합성본을 넣는다.
    직후 컷만(meta 의 when/experiment.no_patch 로 확인). 원본은 <stem>_after_raw.jpg 로 한 번만 남기고, 다시 돌리면 raw 에서 새로 만든다(겹쳐 얹기 방지)."""
    out = []
    for meta_p in sorted((ROOT / "outputs" / bid).glob("*/meta.json")):
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        if not (meta.get("experiment") or {}).get("no_patch"):
            out.append((meta_p.parent.name, "skip: no_patch 회차 아님")); continue
        whens = [x.get("when") for x in meta.get("afters") or []]
        # 단발 = <stem>_after.jpg (그 컷이 직후일 때만), 시리즈 = <stem>_after_immediate.jpg
        cands = list(meta_p.parent.glob("*_after_immediate.jpg")) if meta.get("series") else \
            (list(meta_p.parent.glob("*_after.jpg")) if whens == ["immediate"] else [])
        for a in cands:
            raw = a.with_name(a.stem + "_raw.jpg")
            if not raw.exists():
                raw.write_bytes(a.read_bytes())
            sd = seed if seed is not None else PF.seed_for(bid, meta_p.parent.name)
            res, rec = PF.apply(Image.open(raw), seed=sd)
            if rec["applied"]:
                res.save(a, quality=95)
            meta["patch_film"] = rec
            meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            out.append((a.name, rec.get("spots") if rec["applied"] else rec["why"]))
    return out


if __name__ == "__main__":
    A = sys.argv[1:]
    sd = int(A[A.index("--seed") + 1]) if "--seed" in A else None
    if A and A[0] == "--compare":
        PF.compare(A[1:4], ["v57 (모델이 그린 패치)", "v58 (점 문장 교체)", "v59 (패치 없이 생성 → 막 합성)"], A[4])
    elif A and A[0] == "--tiles":
        PF.tiles(A[1], A[2])
    elif A and A[0] == "--into-batch":
        for row in into_batch(A[1], sd):
            print(*row)
    else:
        print(json.dumps(PF.run(A[0], A[1], sd or 0, "--debug" in A), ensure_ascii=False, indent=1))
