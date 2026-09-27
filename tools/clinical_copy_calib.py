"""임상 '너무 같음' 자 기준 잡기 (2026-09-28 빌디 요청 "참조 쌍 3개를 재서 기준 잡아 주세요").

  python tools/clinical_copy_calib.py

- 참조: samples/reference/clinical 의 실제 전·후 3쌍(진짜 다른 날 촬영) — '복사본이 아닌' 쪽 기준.
- 생성: outputs/ 의 임상 세트 최종 After(09-15 18장, 사람 판정 전부 reject 'AI 티') — '복사본' 쪽 표본.
- 재는 값: 닮음(ArcFace) · 정렬 오차 % · 눈 선 기울기 차(°) · 자세 벡터(표정·고개) · 얼굴 밖 픽셀 차.
- 결과: outputs/rescore/clinical_copy_calib.json (API 호출 0, 로컬 CPU).
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bna.qa import identity, landmarks as L, structure  # noqa: E402

OUT = ROOT / "outputs" / "rescore" / "clinical_copy_calib.json"
REF = ROOT / "samples" / "reference" / "clinical"
PAIRS = [("nasolabial_before_01.jpg", "nasolabial_after2w_01.jpg"),
         ("lifting_before_01.jpg", "lifting_after2w_01.jpg"),
         ("lifting_before_02.jpg", "lifting_after4w_02.jpg")]


def roll(pts):
    k = L.key_points(pts); d = k["eye_r"] - k["eye_l"]
    return float(np.degrees(np.arctan2(d[1], d[0])))


def pix_diff(b, a):
    """같은 크기로 맞춘 뒤 전체 평균 절대 차(0~1). 픽셀 복사면 0 근처."""
    a = a.resize(b.size)
    return float(np.abs(np.asarray(b.convert("L"), float) - np.asarray(a.convert("L"), float)).mean() / 255)


def measure(b, a):
    pb, pa = L.detect(b), L.detect(a)
    idn = identity.check(b, a)
    row = {"sim": None if idn.get("similarity") is None else round(float(idn["similarity"]), 3),
           "pix": round(pix_diff(b, a), 4)}
    if pb is not None and pa is not None:
        st = structure.check(b, a, "clinical", "nasolabial_marionette")
        vb, va = structure.pose_vector(pb), structure.pose_vector(pa)
        row.update({"align": round(st["align_err_pct"], 2), "luma": round(st["luma_diff"], 3),
                    "roll": round(abs((roll(pa) - roll(pb) + 180) % 360 - 180), 1),
                    "expr": round(float(np.abs(va[:4] - vb[:4]).mean()), 4),
                    "head": round(float(np.abs(va[4:] - vb[4:]).mean()), 4)})
    return row


def main():
    res = {"ref": [], "gen": []}
    for bf, af in PAIRS:
        r = measure(Image.open(REF / bf).convert("RGB"), Image.open(REF / af).convert("RGB"))
        res["ref"].append({"pair": bf, **r}); print("REF", bf, r)
    for mp in sorted((ROOT / "outputs").glob("*/*/meta.json")):
        m = json.loads(mp.read_text(encoding="utf-8"))
        if m.get("mode") != "clinical":
            continue
        # 재시도로 조건을 다시 뽑으면 옛 인물 파일이 폴더에 남는다 — 같은 이름 줄기(stem)끼리 짝짓고, 최신 파일 쌍을 쓴다.
        pairs = [(b, b.with_name(b.name.replace("_before.jpg", "_after.jpg"))) for b in mp.parent.glob("*_before.jpg")]
        pairs = sorted([p for p in pairs if p[1].exists()], key=lambda p: p[1].stat().st_mtime)
        if not pairs:
            continue
        rv = mp.parent / "review.json"
        pick = json.loads(rv.read_text(encoding="utf-8")).get("pick") if rv.exists() else None
        r = measure(Image.open(pairs[-1][0]).convert("RGB"), Image.open(pairs[-1][1]).convert("RGB"))
        row = {"set": f"{mp.parent.parent.name}/{mp.parent.name}", "pick": pick,
               "rig": ((m.get("variation") or {}).get("rig") or {}).get("key"), **r}
        res["gen"].append(row); print("GEN", row)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("->", OUT)


if __name__ == "__main__":
    main()
