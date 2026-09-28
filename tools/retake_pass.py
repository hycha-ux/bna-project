"""A 보정 결과를 편집 모델로 '그대로 다시 촬영' (2026-09-28 10차 연서님 — 골은 메워진 채로 모공 결만 모델이 되살리게).

  python tools/retake_pass.py <batch_id> <suffix> [<suffix> …] [--dry]

각 항목 `<id>-<suffix>`(예: -E44)의 After 를 편집 모델에 한 번 넣어 `<id>-<suffix>R` 로 저장한다(검수함 한 줄).
재촬영 전·후 골 선 선명도(bna.foldlift.edge_ratio, 볼 맨살 대비)를 같이 적는다 — 모델이 골을 되살리면 여기서 드러난다.
⚠ 유료: 한 장 = 편집 1회(pricing.yaml openai.edit, 추정 $0.19). --dry 면 호출 없이 대상만 출력.
"""
import io
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bna import providers  # noqa: E402
from bna.api import stem_of  # noqa: E402
from bna.foldlift import edge_ratio, shade  # noqa: E402
from bna.spec import load  # noqa: E402

# 문안 정본 = config/prompts/retake_clinical.md (12차부터 배치도 같은 파일을 읽는다 — 두 벌로 갈리지 않게)
PROMPT = " ".join((ROOT / "config" / "prompts" / "retake_clinical.md").read_text(encoding="utf-8").split())


def main():
    a = sys.argv[1:]
    dry = "--dry" in a
    bid, sufs = a[0], [x for x in a[1:] if not x.startswith("--")]
    bd = ROOT / "outputs" / bid
    prov = None if dry else providers.get("openai")
    price = load("pricing.yaml")["openai"]["edit"]
    for d in sorted(bd.iterdir()):
        if not d.is_dir() or not any(d.name.endswith("-" + s) for s in sufs):
            continue
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        st = stem_of(m)
        b, af = d / f"{st}_before.jpg", d / f"{st}_after.jpg"
        if not (b.exists() and af.exists()):
            print(d.name, "파일 짝 없음 — 건너뜀"); continue
        src = Image.open(af).convert("RGB")
        e_in = edge_ratio(src)
        if dry:
            print("[dry]", d.name, "→", d.name + "R", "선명도", round(e_in, 3)); continue
        buf = io.BytesIO(); src.save(buf, "PNG")
        out_b = prov.edit(buf.getvalue(), PROMPT, None, [], "4:5")
        out = Image.open(io.BytesIO(out_b)).convert("RGB")
        if out.size != src.size:
            out = out.resize(src.size, Image.LANCZOS)
        e_out, bi = edge_ratio(out), Image.open(b)
        sid = f"{m['item_id']}R"
        sd = bd / sid; sd.mkdir(exist_ok=True)
        shutil.copy2(b, sd / b.name.replace(f"_{m['item_id']}_", f"_{sid}_"))
        out.save(sd / af.name.replace(f"_{m['item_id']}_", f"_{sid}_"), quality=94)
        if (d / "mask.png").exists():
            shutil.copy2(d / "mask.png", sd / "mask.png")
        info = {"edge_before_img": round(edge_ratio(bi), 3), "edge_in": round(e_in, 3), "edge_out": round(e_out, 3),
                "shade_in": round(shade(src), 3), "shade_out": round(shade(out), 3)}
        snap = {**m, "item_id": sid, "retake_of": m["item_id"], "retake": info, "cost": price,
                "note": "A 보정본을 편집 모델로 '그대로 다시 촬영'(골은 메워진 채 모공 결 복원) — 10차"}
        (sd / "meta.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(d.name, "→", sid, info)


if __name__ == "__main__":
    main()
