"""임상 2회차 점검 (2026-09-15 저녁 티모, 성연서님 확인 3가지).

① 겹쳤을 때 잔머리·눈/입·옷 매무새가 다른가 — After 를 랜드마크 468점 아핀으로 Before 에 맞춘 뒤,
   부위별 평균 밝기 변화(0~255)를 잰다. 머리 위치 drift 를 지웠으므로 남는 값이 '살짝 다름'이다.
   ⚠ 0 에 가까우면 복사본(첫 실회차 지적), 너무 크면 다른 사진. 기준선: 같은 부스 실사진 쌍이 아니라 이 회차 안 비교다.
② 팔자 변화가 보이는가 — 팔자 마스크 안 변화 + 확대 크롭(눈 확인용).
③ 마스크 없이 편집이 팔자 밖으로 번지나 — (a) 편집 몰림 = 팔자 안 ÷ 얼굴 나머지 피부 (b) 게이트 탈락률 =
   모든 회차의 동일인·구조 탈락 수(attempts_log + 마지막 회차). 번지면 '부위 밖 변형 자' 후보.

부위 영역(이미지 좌표, Before 랜드마크 기준):
  잔머리 = 이마 위 띠(10번 점 위로 얼굴 높이 25%) · 눈 = 양눈 윤곽 상자 · 입 = 입술 상자 · 옷 매무새 = 턱(152) 아래 목·깃 띠
산출: outputs/_ab_0915/<batch>/run2/ — set_<item>.jpg(세트당 1장) · table.png · report.json
사용: python tools/_clinical_run2_0915.py <batch_id>
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")
from bna.qa import landmarks  # noqa: E402
from bna.spec import load  # noqa: E402
from _ab_after_refs_0915 import align, locality  # noqa: E402  (정렬·편집 몰림 정의는 한 벌)
from _sheet_0915 import table, font, fmt, RIG, WHEN  # noqa: E402

LEFT_EYE_RING = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
RIGHT_EYE_RING = [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466]
LIPS = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]


def boxes(pts, size):
    """부위 상자 (x0,y0,x1,y1). 얼굴 높이 = 이마(10)~턱(152)."""
    W, H = size
    fh = float(np.linalg.norm(pts[152] - pts[10]))
    xs, ys = pts[:, 0], pts[:, 1]
    cx0, cx1 = float(xs.min()), float(xs.max())

    def pad(b, p):
        return (max(0, int(b[0] - p)), max(0, int(b[1] - p)), min(W, int(b[2] + p)), min(H, int(b[3] + p)))

    def bb(idx):
        q = pts[idx]
        return (q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max())

    le, re_ = bb(LEFT_EYE_RING), bb(RIGHT_EYE_RING)
    eyes = pad((min(le[0], re_[0]), min(le[1], re_[1]), max(le[2], re_[2]), max(le[3], re_[3])), fh * 0.06)
    mouth = pad(bb(LIPS), fh * 0.06)
    top = float(pts[10][1])
    hair = (max(0, int(cx0 - fh * 0.1)), max(0, int(top - fh * 0.35)), min(W, int(cx1 + fh * 0.1)), max(1, int(top + fh * 0.02)))
    chin = float(pts[152][1])
    collar = (max(0, int(cx0 - fh * 0.3)), min(H - 1, int(chin + fh * 0.25)), min(W, int(cx1 + fh * 0.3)), min(H, int(chin + fh * 0.75)))
    naso = bb(landmarks.REGIONS["nasolabial"])
    return {"잔머리": hair, "눈": eyes, "입": mouth, "옷 매무새": collar, "팔자": pad(naso, fh * 0.04)}


def region_diff(before, aligned, box):
    x0, y0, x1, y1 = box
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    a = np.asarray(before.convert("L").crop(box), dtype=float)
    b = np.asarray(aligned.convert("L").crop(box), dtype=float)
    return round(float(np.abs(a - b).mean()), 1)


def gate_counts(meta):
    """모든 회차의 탈락 사유 수. attempts_log = 탈락 회차들, 마지막 회차는 meta['fail_reasons']."""
    reasons = [r for a in (meta.get("attempts_log") or []) for r in a.get("fail_reasons") or []]
    if meta.get("passed") is False:
        reasons += list(meta.get("fail_reasons") or [])
    tries = len(meta.get("attempts_log") or []) + 1
    idn = sum(1 for r in reasons if str(r).split("@")[0] in ("identity", "identity_review", "vision:identity"))
    st = sum(1 for r in reasons if str(r).split("@")[0] == "structure")
    return tries, idn, st, reasons


def sheet(item, meta, before, after, aligned, bx, row, out):
    H = 560
    tb = before.resize((int(before.width * H / before.height), H))
    ta = after.resize((int(after.width * H / after.height), H))
    crop_h, gap = 150, 8
    names = list(bx)
    cw = int((tb.width + ta.width + gap) / len(names)) - gap
    W = tb.width + ta.width + gap
    top = 78
    total_h = top + H + 30 + (crop_h * 2 + 40)
    s = Image.new("RGB", (W, total_h), "white")
    s.paste(tb, (0, top)); s.paste(ta, (tb.width + gap, top))
    d = ImageDraw.Draw(s)
    d.text((10, 8), f"세트 {item} · {RIG.get(row['rig'], row['rig'])} · {WHEN.get(row['when'], row['when'])} · "
                    f"Before {row['severity']} → 효과 {row['effect']} · {'통과' if row['passed'] else '탈락'}", fill=(0, 0, 0), font=font(22))
    d.text((10, 40), f"동일인 {fmt(row['identity'], 3)} · 정렬 {fmt(row['align_pct'], 2, '%')} · 밝기차 {fmt(row['luma'], 3)} · "
                     f"편집 몰림 {fmt(row['spread'])} · 시도 {row['tries']}회(동일인 탈락 {row['idn_fail']} · 구조 탈락 {row['st_fail']})",
           fill=(70, 70, 70), font=font(16))
    d.text((10, top + H + 4), "Before", fill=(0, 0, 0), font=font(17))
    d.text((tb.width + gap + 10, top + H + 4), "After", fill=(0, 0, 0), font=font(17))
    y0 = top + H + 32
    for i, n in enumerate(names):
        x = i * (cw + gap)
        box = bx[n]
        for j, img in enumerate((before, aligned)):          # 위 = Before, 아래 = 맞춘 After (겹쳐 보는 자리 그대로)
            c = img.crop(box)
            c = c.resize((cw, int(c.height * cw / max(1, c.width)))) if c.width else c
            c = c.crop((0, max(0, (c.height - crop_h) // 2), cw, max(0, (c.height - crop_h) // 2) + crop_h))
            s.paste(c, (x, y0 + j * (crop_h + 4)))
        d.text((x + 4, y0 + crop_h * 2 + 10), f"{n} 변화 {fmt(row['regions'].get(n), 1)}", fill=(0, 0, 0), font=font(16))
    s.save(out, quality=88)
    return out


def main():
    bid = sys.argv[1]
    bdir = ROOT / "outputs" / bid
    out = ROOT / "outputs" / "_ab_0915" / bid / "run2"
    out.mkdir(parents=True, exist_ok=True)
    region_key = None
    rows, table_rows = [], []
    for d in sorted(p for p in bdir.iterdir() if (p / "meta.json").exists()):
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        region_key = load("treatments.yaml")[meta["treatment"]]["mask_region"]
        w = meta["afters"][0]["when"]
        res = (meta.get("after_results") or {}).get(w) or {}
        st, idn = res.get("structure") or {}, res.get("identity") or {}
        bf, af = next(d.glob("*_before.jpg")), next(d.glob("*_after*.jpg"), None)
        before = Image.open(bf).convert("RGB")
        after = Image.open(af).convert("RGB").resize(before.size) if af else None
        pb = landmarks.detect(before)
        pa = landmarks.detect(after) if after is not None else None
        tries, n_idn, n_st, reasons = gate_counts(meta)
        v = meta["variation"]
        row = {"item": d.name, "rig": v["rig"]["key"], "when": w, "passed": bool(meta.get("passed")),
               "severity": v.get("before_severity", {}).get("key"), "effect": v.get("effect_level", {}).get("key"),
               "age": v.get("age", {}).get("key"), "identity": idn.get("similarity"), "align_pct": st.get("align_err_pct"),
               "luma": st.get("luma_diff"), "tries": tries, "idn_fail": n_idn, "st_fail": n_st, "reasons": reasons,
               "cost": meta.get("cost"), "redrawn": meta.get("redrawn"), "regions": {}, "spread": None}
        if pb is not None and pa is not None:
            aligned = align(before, after, pb, pa)
            bx = boxes(pb, before.size)
            row["regions"] = {n: region_diff(before, aligned, b) for n, b in bx.items()}
            loc = locality(before, after, region_key)
            row["spread"] = loc[2] if loc else None
            print(sheet(d.name, meta, before, after, aligned, bx, row, out / f"set_{d.name}.jpg"))
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("item", "rig", "when", "passed", "severity", "effect", "tries", "idn_fail", "st_fail", "regions", "spread")}, ensure_ascii=False))
        r = row["regions"]
        table_rows.append([(row["item"], False), (RIG.get(row["rig"], row["rig"]), False), (WHEN.get(w, w), False),
                           ("통과" if row["passed"] else "탈락", not row["passed"]),
                           (f"{row['tries']}회", row["tries"] > 1), (f"{n_idn}/{n_st}", (n_idn + n_st) > 0),
                           (fmt(r.get("잔머리"), 1), False), (fmt(r.get("눈"), 1), False), (fmt(r.get("입"), 1), False),
                           (fmt(r.get("옷 매무새"), 1), False), (fmt(r.get("팔자"), 1), False), (fmt(row["spread"]), False),
                           ("$" + fmt(row["cost"], 2) if row["cost"] is not None else "—", False)])
    tot_tries = sum(r["tries"] for r in rows)
    tot_idn, tot_st = sum(r["idn_fail"] for r in rows), sum(r["st_fail"] for r in rows)
    cols = [("세트", 0), ("리그", 0), ("시점", 0), ("결과", 0), ("시도", 0), ("동일인/구조 탈락", 0),
            ("잔머리", 0), ("눈", 0), ("입", 0), ("옷 매무새", 0), ("팔자", 0), ("편집 몰림", 0), ("비용", 0)]
    notes = [f"전체 시도 {tot_trie_s(tot_tries)} 중 동일인 탈락 {tot_idn}회 · 구조 탈락 {tot_st}회 (마스크 없이 번졌는지의 1차 신호).",
             "부위 숫자 = After 를 랜드마크로 Before 에 맞춘 뒤 그 부위 평균 밝기 변화(0~255). 0에 가까우면 겹쳤을 때 복사본.",
             "편집 몰림 = 팔자 안 변화 ÷ 얼굴 나머지 피부 변화. 1보다 작으면 편집이 팔자에만 머물지 않았다.",
             "결과·부위 수치는 마지막 회차 기준. 탈락 회차는 원장(attempts_log)에서 사유만 센다."]
    print(table(table_rows, cols, out / "table.png", f"임상 2회차 {bid} · 팔자 6세트", notes))
    (out / "report.json").write_text(json.dumps({"batch": bid, "items": rows, "tries": tot_tries, "identity_fail": tot_idn,
                                                  "structure_fail": tot_st}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def tot_trie_s(n):
    return f"{n}회"


if __name__ == "__main__":
    main()
