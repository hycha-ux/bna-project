"""24차 확인 배치 결과 (2026-09-29 연서님 "세트별 골 수치(메운 직후 / 최종), 배경 밝기, 두 겹 검사 값, 잡티 개수(전/후) 같이").

  PYTHONPATH=src python tools/round24_check.py <출력폴더> <배치ID> [<배치ID> …]

돈 0. 값은 전부 meta 원장에서 읽는다(골·두 겹·잡티). 배경 밝기만 사진에서 잰다(round22_check 와 같은 자).
원장 = <출력>/round24.json, 표 스펙 = <출력>/table.json(tools/render-table.mjs 로 굽는다), 세트 판 = <출력>/<배치>_<세트>.jpg
"""
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import round22_check as R  # noqa: E402

WHEN_KO = {"immediate": "직후", "1w": "1주", "2w": "2주", "4w": "4주"}
ANG_KO = {"front": "정면", "three_quarter": "3/4", "side": "측면"}


def fmt(v, suf="%"):
    return "–" if v is None else f"{v}{suf}"


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    res, rows = {}, []
    for bid in sys.argv[2:]:
        for d in sorted(p for p in (Path("outputs") / bid).iterdir() if p.is_dir() and p.name.isdigit()):
            m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            v = m["variation"]
            bef = Image.open(next(d.glob("*_before.jpg"))).convert("RGB")
            aft = Image.open(next(d.glob("*_after.jpg"))).convert("RGB")
            ffd = m.get("fold_fill") or {}
            when = next(iter(ffd), None) or (m.get("timeline") or {}).get("key")
            ff = ffd.get(when) or {}
            eb = ff.get("edge_before_img")
            fbs = sorted(d.glob(f"filled_{when}_a*.jpg")) or sorted(d.glob("fold_b_*_a*.jpg"))
            fb = Image.open(fbs[-1]).convert("RGB") if fbs else None
            mg = ff.get("retake_merge") or {}
            pg = m.get("pigment") or {}
            pb, pa = (pg.get("before") or {}), (pg.get(when) or {})
            r = {"when": when, "angle": v["angle"]["key"], "who": f'{v["age"]["key"]}{v["gender"]["key"][0]}',
                 "passed": m.get("passed"), "attempt": m.get("attempt"), "cost": m.get("cost"),
                 "attempts_log": m.get("attempts_log"),
                 "fold_pct": {"B": R.pct(ff.get("edge_before"), eb), "filled": R.pct(ff.get("edge_after"), eb),
                              "final": R.pct(ff.get("edge_final"), eb)},
                 "bg_L": {"pre_retake": R.bg_L(fb) if fb else None, "final": R.bg_L(aft)},
                 "merge": {"applied": mg.get("applied"), "skip": mg.get("skip"), "ghost": mg.get("ghost")},
                 "pigment": {"before": pb.get("n") if pb.get("measured") else None,
                             "after": pa.get("n") if pa.get("measured") else None},
                 "fail_reasons": m.get("fail_reasons")}
            res[f"{bid}/{d.name}"] = r
            gh = r["merge"]["ghost"]
            mtxt = (f'{gh:.4f}' if gh is not None else "–") + ("" if r["merge"]["applied"] else f' (건너뜀:{r["merge"]["skip"]})')
            rows.append([f'{bid[-4:]}', WHEN_KO.get(when, when), ANG_KO.get(r["angle"], r["angle"]), r["who"],
                         {"t": "통과", "em": "ok"} if r["passed"] else {"t": "탈락 " + ",".join(r["fail_reasons"] or []), "em": "warn"},
                         f'{r["attempt"]}회 · ${r["cost"]:.2f}' if r["cost"] is not None else f'{r["attempt"]}회',
                         f'{fmt(r["fold_pct"]["filled"])} → {fmt(r["fold_pct"]["final"])}',
                         f'{fmt(r["bg_L"]["pre_retake"], "")} → {fmt(r["bg_L"]["final"], "")}',
                         mtxt,
                         f'{fmt(r["pigment"]["before"], "")} → {fmt(r["pigment"]["after"], "")}'])
            ims, cols = ([bef, fb, aft], ["Before", "메운 B(재촬영 전)", "최종 After"]) if fb else ([bef, aft], ["Before", "최종 After"])
            R.board(ims, cols, f"24차 {WHEN_KO.get(when, when)} {ANG_KO.get(r['angle'])} {r['who']} — 골 {r['fold_pct']} · 잡티 {r['pigment']}").save(
                out / f"{bid}_{d.name}.jpg", quality=90)
    (out / "round24.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    spec = {"title": "24차 확인 배치 — 세트별 수치",
            "subtitle": "골 선 = Before 대비 % (메운 직후 → 최종) · 배경 밝기 L = 재촬영 전 → 최종 · 두 겹 상한 0.02 · 잡티 = 개수(전 → 후, 기록 전용)",
            "columns": [{"label": "배치"}, {"label": "시점"}, {"label": "각도"}, {"label": "인물"}, {"label": "기계 판정"},
                        {"label": "시도·비용", "align": "right"}, {"label": "골 선", "align": "right"},
                        {"label": "배경 밝기", "align": "right"}, {"label": "두 겹", "align": "right"},
                        {"label": "잡티 전→후", "align": "right"}],
            "rows": rows, "out": str((out / "table.png").resolve())}
    (out / "table.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
