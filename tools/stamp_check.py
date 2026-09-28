"""15차 도장 점검 (2026-09-28 연서님 v55 검수 "모공이 도장 찍은 듯 같은 무늬가 반복돼") — 비용 0.

  python tools/stamp_check.py <batch_id> [<id>,<id>…] [--save]

배치 각 항목의 **메우기 직전 B**(fold_b_<시점>_a<마지막 회차>.jpg)를
  OLD = 14차 결 옮기기(한 방향 통째 복사) / NEW = 15차 조각 섞기+노이즈 모공 으로 같은 목표까지 다시 메우고,
반복 무늬 자(foldlift.repeat_stats — 띠 안·얼굴 전체)를 Before · B · OLD · NEW · 배치 최종 컷에 같이 잰다.
--save 면 띠 확대 비교(B | OLD | NEW | 최종) PNG 를 outputs/_stamp_check/ 에 남긴다(눈 확인용).
기준선 = samples/reference/clinical 실제 사진도 같이 잰다.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bna import foldlift as fl  # noqa: E402
from bna.api import stem_of  # noqa: E402
from bna.qa import landmarks as L  # noqa: E402
from bna.spec import load  # noqa: E402

OUT = ROOT / "outputs" / "_stamp_check"


def fill(B, eb, ff, mix):
    fl.STAMP_MIX = mix
    try:
        sp = ff.get("shade_pct")
        o, fi = fl.fill_to(B, eb * (1 + float(ff["edge_pct"]) / 100.0), None)
        return o, fi.pop("_wm", None), fi
    finally:
        fl.STAMP_MIX = True


def crop_band(img, wm, pad=0.04):
    ys, xs = np.nonzero(wm > 0.3)
    w = img.size[0]
    p = int(w * pad)
    return img.crop((max(0, xs.min() - p), max(0, ys.min() - p), min(w, xs.max() + p), min(img.size[1], ys.max() + p)))


def main():
    a = sys.argv[1:]
    save = "--save" in a
    pos = [x for x in a if not x.startswith("--")]
    ff = load("clinical_rig.yaml").get("fold_fill") or {}
    res = {"reference": {}}
    for p in sorted((ROOT / "samples" / "reference" / "clinical").glob("*.jpg")):
        res["reference"][p.name] = fl.repeat_stats(Image.open(p))
    bd = ROOT / "outputs" / pos[0]
    only = set(pos[1].split(",")) if len(pos) > 1 else None
    OUT.mkdir(parents=True, exist_ok=True)
    for d in sorted(x for x in bd.iterdir() if x.is_dir() and "-" not in x.name):
        if only and d.name not in only:
            continue
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        st = stem_of(m)
        when = next(iter(m.get("fold_fill") or {"2w": 0}))
        fbs = sorted(d.glob(f"fold_b_{when}_a*.jpg"), key=lambda p: int(p.stem.rsplit("_a", 1)[1]))
        if not fbs:
            print(d.name, "메우기 직전 B 없음"); continue
        before = Image.open(d / f"{st}_before.jpg").convert("RGB")
        final = Image.open(d / f"{st}_after.jpg").convert("RGB")
        B = Image.open(fbs[-1]).convert("RGB")
        eb = ((m.get("fold_fill") or {}).get(when) or {}).get("edge_before_img") or fl.edge_ratio(before)
        o_old, wm, i_old = fill(B, eb, ff, False)
        o_new, wm2, i_new = fill(B, eb, ff, True)
        if wm is None:
            print(d.name, "메우기 실패"); continue
        row = {"before": fl.repeat_stats(before, fl.line_map(before, L.detect(before))),
               "B": fl.repeat_stats(B, wm), "old": fl.repeat_stats(o_old, wm), "new": fl.repeat_stats(o_new, wm2),
               "final": fl.repeat_stats(final, wm),
               "band_old": fl.band_stats(o_old, wm), "band_new": fl.band_stats(o_new, wm2),
               "edge_old": i_old.get("edge_after"), "edge_new": i_new.get("edge_after"), "edge_goal": i_new.get("edge_goal")}
        res[d.name] = row
        print(d.name, {k: (v.get("band_p90"), v.get("band_hit"), v.get("face_p90"), v.get("face_hit")) for k, v in row.items() if isinstance(v, dict) and "face_n" in v},
              "edge", row["edge_old"], row["edge_new"], "/", row["edge_goal"])
        if save:
            tiles = [crop_band(x, wm) for x in (B, o_old, o_new, final)]
            tw, th = tiles[0].size
            z = max(1, int(600 / max(th, 1)))
            sheet = Image.new("RGB", (tw * z * 4 + 30, th * z), "white")
            for i, t in enumerate(tiles):
                sheet.paste(t.resize((tw * z, th * z), Image.NEAREST), (i * (tw * z + 10), 0))
            sheet.save(OUT / f"{pos[0]}_{d.name}.png")
            o_new.save(OUT / f"{pos[0]}_{d.name}_new.jpg", quality=95)
    (OUT / f"{pos[0]}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
