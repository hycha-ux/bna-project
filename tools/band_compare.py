"""14차 두 벌 비교 (2026-09-28 연서님 v54 검수 "같은 B 위에 두 벌 나란히 — ① 재촬영 없이 띠 안 되얹기만 ② 재촬영 유지 + 1번 보완").

  python tools/band_compare.py <batch_id> [<id>,<id>…] [--dry]

배치 각 항목의 **메우기 직전 B**(fold_b_<시점>_a<마지막 회차>.jpg — 최종 컷과 같은 회차)를 14차 메우기
(bna.foldlift: 그늘 밝히기 끔 · 옆 피부 결 옮겨 오기 · 주변 평균 이하로 밝기 묶기)로 다시 메우고
  -P1 = 재촬영 없음(비용 0) / -P2 = 같은 메운 사진을 편집 모델 '그대로 다시 촬영'(retake_clinical.md, 장당 편집 1회)
형제 항목으로 저장한다(검수함 한 줄씩). 두 벌 모두 배치와 같은 후처리(quality 키)를 거친다.
수치(띠 안팎 자 bna.foldlift.band_stats, 골 선 선명도 Before 대비 %, 좌우 차)는 옛 최종 컷(v54)과 함께 out JSON 에.
⚠ --dry 면 P2(유료)를 건너뛴다.
"""
import io
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bna import foldlift as fl, postprocess, providers  # noqa: E402
from bna.api import stem_of  # noqa: E402
from bna.qa import landmarks as L  # noqa: E402
from bna.spec import load  # noqa: E402

PROMPT = " ".join((ROOT / "config" / "prompts" / "retake_clinical.md").read_text(encoding="utf-8").split())


def pct(a, b):
    return None if not (a and b) else round((a - b) / b * 100, 1)


def main():
    a = sys.argv[1:]
    dry = "--dry" in a
    pos = [x for x in a if not x.startswith("--")]
    bd = ROOT / "outputs" / pos[0]
    only = set(pos[1].split(",")) if len(pos) > 1 else None
    ff = load("clinical_rig.yaml").get("fold_fill") or {}
    prov = None if dry else providers.get("openai")
    price = load("pricing.yaml")["openai"]["edit"]
    rows = {}
    for d in sorted(p for p in bd.iterdir() if p.is_dir() and "-" not in p.name):
        if only and d.name not in only:
            continue
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        st = stem_of(m)
        when = m["afters"][0]["when"] if m.get("afters") else next(iter(m["fold_fill"]))
        fbs = sorted(d.glob(f"fold_b_{when}_a*.jpg"), key=lambda p: int(p.stem.rsplit("_a", 1)[1]))
        if not fbs:
            print(d.name, "메우기 직전 B 없음 — 건너뜀"); continue
        bp, ap = d / f"{st}_before.jpg", d / f"{st}_after.jpg"
        before, B, old = Image.open(bp).convert("RGB"), Image.open(fbs[-1]).convert("RGB"), Image.open(ap).convert("RGB")
        rec = (m.get("fold_fill") or {}).get(when) or {}
        eb = rec.get("edge_before_img") or fl.edge_ratio(before)
        sb = fl.shade(before)
        sp = ff.get("shade_pct")
        filled, fi = fl.fill_to(B, eb * (1 + float(ff["edge_pct"]) / 100.0), None if sp is None else sb * (1 + float(sp) / 100.0))
        wm = fi.pop("_wm", None)
        if fi.get("applied") and ff.get("side_gap_max") is not None:
            filled, bi = fl.balance_sides(before, filled, float(ff["side_gap_max"]))
            fi["side_fill"] = bi
            filled, ci = fl.clamp_dark(filled, wm)
            fi["clamp2"] = ci
        qk = (m.get("after_variation") or {}).get("quality", {}).get("key") or m["afters"][0]["after_variation"]["quality"]["key"]
        seed = sum(map(ord, d.name + when)) & 0xFFFF
        pp = lambda im: Image.open(io.BytesIO(postprocess.apply(im, qk, m["mode"], seed))).convert("RGB")  # noqa: E731
        outs = {"P1": pp(filled)}
        if not dry:
            buf = io.BytesIO(); filled.save(buf, "PNG")
            rb = prov.edit(buf.getvalue(), PROMPT, None, [], m.get("aspect") or "4:5")
            r = Image.open(io.BytesIO(rb)).convert("RGB")
            r = r if r.size == filled.size else r.resize(filled.size, Image.LANCZOS)
            outs["P2"] = pp(r)
        pb = L.detect(before)
        row = {"when": when, "B_attempt": fbs[-1].name, "fill": {k: v for k, v in fi.items() if k != "band"},
               "before": {"band": fl.band_stats(before, fl.line_map(before, pb), pb)}}
        for tag, im in (("v54", old), *outs.items()):
            e = fl.edge_ratio(im)
            row[tag] = {"band": fl.band_stats(im, wm), "edge_pct": pct(e, eb), "sides": fl.side_drop(before, im)}
        for tag, im in outs.items():
            sid = f"{d.name}-{tag}"
            sd = bd / sid; sd.mkdir(exist_ok=True)
            shutil.copy2(bp, sd / bp.name.replace(f"_{d.name}_", f"_{sid}_"))
            im.save(sd / ap.name.replace(f"_{d.name}_", f"_{sid}_"), quality=94)
            if (d / "mask.png").exists():
                shutil.copy2(d / "mask.png", sd / "mask.png")
            snap = {**m, "item_id": sid, "band_compare_of": d.name, "band_variant": tag, "band_result": row[tag],
                    "cost": price if tag == "P2" else 0.0, "attempts_log": [], "fold_lift": True,
                    "note": {"P1": "14차 메우기(결 옮기기·밝기 묶기·그늘 밝히기 끔), 재촬영 없음",
                             "P2": "14차 메우기 + 재촬영(편집 1회)"}[tag]}
            (sd / "meta.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        rows[d.name] = row
        print(d.name, json.dumps({k: row[k] for k in row if k in ("before", "v54", "P1", "P2")}, ensure_ascii=False))
    out = bd / "band_compare.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("→", out, "비용", 0 if dry else round(price * len(rows), 2))


if __name__ == "__main__":
    main()
