"""임상 첫 실회차 슬랙용 이미지 (2026-09-15 티모, 성연서님 "세트당 1장씩 스레드에").

입력: tools/_ab_after_refs_0915.py 가 쓴 outputs/_ab_0915/<batch>/report.json (게이트 수치를 여기서 다시 재지 않는다 — 두 벌이 되면 갈린다)
출력: outputs/_ab_0915/<batch>/post/
  - set_<item>.jpg  : Before | After 한 장 + 머리글(리그·시점·결과·정렬·밝기·동일인·편집 몰림)
  - ab_<item>.jpg   : 같은 Before 에서 참조 끔 | 켬 (있을 때만)
  - table.png       : 세트별 수치 표 (표 수치는 이미지로 — 팀 규칙)
AI 생성 인물이라 PII 없음.
사용: python tools/_sheet_0915.py <batch_id>
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
FONT = "C:/Windows/Fonts/malgun.ttf"          # 기본 PIL 글꼴엔 한글이 없다 — 네모로 조용히 깨진다
RIG = {"grey_studio": "회색 스튜디오", "blue_backdrop": "파란 배경", "clinic_wall": "병원 벽"}
WHEN = {"immediate": "직후", "1w": "1주", "2w": "2주", "4w": "4주"}
LIMIT = {"align": 4.0, "luma": 0.05}           # clinical_rig.yaml tolerance 와 같은 값 — 표에서 넘은 칸만 빨갛게 칠하는 용도


def font(size):
    return ImageFont.truetype(FONT, size)


def fmt(v, nd=2, suffix=""):
    return "—" if v is None else f"{v:.{nd}f}{suffix}"


def verdict(r):
    if r.get("passed") is True:
        return "통과"
    return "탈락 · " + ", ".join(r.get("fail_reasons") or []) if r.get("fail_reasons") else "판정 없음"


def pair(left, right, labels, header, out, h=640):
    tl = left.resize((int(left.width * h / left.height), h))
    tr = right.resize((int(right.width * h / right.height), h))
    top = 70
    s = Image.new("RGB", (tl.width + tr.width + 12, h + top + 34), "white")
    s.paste(tl, (0, top)); s.paste(tr, (tl.width + 12, top))
    d = ImageDraw.Draw(s)
    d.text((10, 8), header[0], fill=(0, 0, 0), font=font(22))
    d.text((10, 38), header[1], fill=(70, 70, 70), font=font(17))
    d.text((10, h + top + 6), labels[0], fill=(0, 0, 0), font=font(18))
    d.text((tl.width + 22, h + top + 6), labels[1], fill=(0, 0, 0), font=font(18))
    s.save(out, quality=88)
    return out


def table(rows, cols, out, title, notes):
    f, fb = font(18), font(19)
    # 칸 폭은 글자 수가 아니라 **글꼴로 잰 실제 너비**로 — 한글은 영문의 약 2배라 글자 수로 어림하면
    # 옆 칸과 겹치고 머리글이 잘린다(2026-09-15 시험 렌더에서 '파란 배경'이 '2주'를 덮었다).
    widths = [int(max([fb.getlength(c[0])] + [f.getlength(str(r[i][0])) for r in rows])) + 24 for i, c in enumerate(cols)]
    rh, top = 38, 56
    W, H = sum(widths) + 20, top + rh * (len(rows) + 1) + 30 + 26 * len(notes)
    s = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(s)
    d.text((10, 12), title, fill=(0, 0, 0), font=font(22))
    x = 10
    for i, (name, _) in enumerate(cols):
        d.rectangle([x, top, x + widths[i], top + rh], fill=(235, 238, 242))
        d.text((x + 8, top + 8), name, fill=(0, 0, 0), font=fb)
        x += widths[i]
    for j, r in enumerate(rows):
        y, x = top + rh * (j + 1), 10
        for i, (val, bad) in enumerate(r):
            if bad:
                d.rectangle([x, y, x + widths[i], y + rh], fill=(253, 226, 226))
            d.text((x + 8, y + 8), str(val), fill=(160, 20, 20) if bad else (0, 0, 0), font=f)
            x += widths[i]
        d.line([10, y + rh, W - 10, y + rh], fill=(225, 225, 225))
    for k, n in enumerate(notes):                     # 접으면 안 되는 경고는 표 아래에 그대로 둔다
        d.text((10, top + rh * (len(rows) + 1) + 14 + 26 * k), n, fill=(90, 90, 90), font=font(16))
    s.save(out)
    return out


def main():
    bid = sys.argv[1]
    base = ROOT / "outputs" / "_ab_0915" / bid
    rep = json.loads((base / "report.json").read_text(encoding="utf-8"))
    post = base / "post"
    post.mkdir(exist_ok=True)
    bdir = next(p for p in (ROOT / "outputs").glob(bid) if p.is_dir())
    rows = []
    for r in rep["items"]:
        d = bdir / r["item"]
        bf, af = next(d.glob("*_before.jpg")), next(d.glob("*_after*.jpg"), None)
        loc = r.get("locality")
        ratio = loc[2] if loc else None
        head = (f"세트 {r['item']} · {RIG.get(r['rig'], r['rig'])} · {WHEN.get(r['when'], r['when'])} · {verdict(r)}",
                f"정렬 {fmt(r.get('align_pct'), 2, '%')} (허용 4%) · 밝기차 {fmt(r.get('luma'), 3)} (허용 0.05) · "
                f"동일인 {fmt(r.get('identity'), 3)} · 편집 몰림(팔자÷나머지 얼굴) {fmt(ratio)} · 참조 {len(r.get('refs') or [])}장")
        if af:
            print(pair(Image.open(bf).convert("RGB"), Image.open(af).convert("RGB"), ("Before", "After"), head, post / f"set_{r['item']}.jpg"))
        rows.append([(r["item"], False), (RIG.get(r["rig"], r["rig"]), False), (WHEN.get(r["when"], r["when"]), False),
                     (verdict(r), r.get("passed") is not True),
                     (fmt(r.get("align_pct"), 2, "%"), (r.get("align_pct") or 0) > LIMIT["align"]),
                     (fmt(r.get("luma"), 3), (r.get("luma") or 0) > LIMIT["luma"]),
                     (fmt(r.get("identity"), 3), False), (fmt(ratio), False),
                     (len(r.get("refs") or []), False), ("$" + fmt(r.get("cost"), 2) if r.get("cost") is not None else "—", False)])
    ab = [x for x in rep.get("ab") or [] if "error" not in x]
    for item in sorted({x["item"] for x in ab}):
        off = next((x for x in ab if x["item"] == item and x["refs"] == "off"), None)
        on = next((x for x in ab if x["item"] == item and x["refs"] == "on"), None)
        if not (off and on):
            continue
        d = bdir / item
        head = (f"세트 {item} · 같은 Before 에서 참조 끔 vs 켬",
                f"동일인 끔 {fmt(off['identity'], 3)} / 켬 {fmt(on['identity'], 3)} · 정렬 끔 {fmt(off['align_pct'], 2, '%')} / 켬 {fmt(on['align_pct'], 2, '%')}")
        print(pair(Image.open(base / f"{item}_off.jpg").convert("RGB"), Image.open(base / f"{item}_on.jpg").convert("RGB"),
                   ("참조 끔", "참조 켬"), head, post / f"ab_{item}.jpg"))
    cols = [("세트", 0), ("리그", 0), ("시점", 0), ("결과", 0), ("정렬", 0), ("밝기차", 0), ("동일인", 0), ("편집 몰림", 0), ("참조", 0), ("비용", 0)]
    notes = ["빨간 칸 = 허용 넘음(정렬 4% · 밝기차 0.05). 결과·수치는 마지막 회차 기준.",
             "편집 몰림 = 얼굴을 랜드마크로 맞춘 뒤 팔자 안 변화 ÷ 나머지 얼굴 변화. 1보다 작으면 편집이 팔자에 몰리지 않았다.",
             "밝기차는 사진 전체 평균 — 옷 색이 바뀌어도 오른다."]
    print(table(rows, cols, post / "table.png", f"임상 첫 실회차 {bid} · 팔자 6세트", notes))


if __name__ == "__main__":
    main()
