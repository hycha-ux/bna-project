"""임상 첫 실회차 점검 + After 참조 켬/끔 비교 (2026-09-15 티모, 성연서님 지시 "같은 seed로 동일인 점수 비교").

1단계(무료, 기본) — 배치의 세트마다
  - 편집 국소성(확인 1): After 를 랜드마크로 Before 에 맞춰 놓고, 팔자 마스크 안 vs 얼굴 나머지 피부의
    평균 밝기 변화를 잰다. 비율 > 1 이면 편집이 팔자 쪽에 몰렸다.
    ⚠ 맞추지 않고 재면 머리 위치 drift(v1 이 일부러 요구한다) 때문에 얼굴 전체가 '바뀐' 것으로 나와 비율이 1 로 뭉개진다.
  - 배치 원장의 구조(정렬·밝기)·동일인 결과를 한 줄로(확인 2)
2단계(유료, --ab) — 참조가 실제로 붙는 세트(현 재고 = 회색 스튜디오·2주)에서 **같은 Before** 로 After 를 켬·끔 두 장 새로 편집.
  GPT 이미지는 seed 가 없어 같은 seed 로 배치를 두 번 돌리면 Before 부터 달라진다 — 그래서 한 Before 에서 갈라 뽑는다.
  배치의 After 는 후처리 전 원본 Before 로 편집됐고 저장본은 후처리 뒤라 입력이 다르다 → 켬·끔 **둘 다** 저장본으로 새로 뽑는다.
  비용: 세트당 2장 ≈ $0.40 (gpt-image-2 실측 $0.198/장).

사용: python tools/_ab_after_refs_0915.py <batch_id> [--ab]
산출: outputs/_ab_0915/<batch_id>/ (AI 생성 인물이라 PII 없음, outputs/ 는 gitignore)
"""
import argparse
import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8")
from bna import postprocess, refs  # noqa: E402
from bna.qa import identity, landmarks, structure  # noqa: E402
from bna.spec import load  # noqa: E402

KEYS = Path(os.environ.get("BNA_KEYS_FILE", r"C:\Users\medib\teemo\keys.env"))


def load_key():
    """OPENAI_API_KEY 만 이 프로세스 환경에 넣는다. 값은 어디에도 출력하지 않는다."""
    for line in KEYS.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("OPENAI_API_KEY="):
            os.environ.setdefault("OPENAI_API_KEY", line.split("=", 1)[1].strip().strip('"'))


def png(img):
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def align(before, after, pb, pa):
    """After 를 Before 좌표로 맞춘다(랜드마크 468점 최소제곱 아핀). 머리 위치 drift 를 지우고 편집만 남긴다."""
    coef, *_ = np.linalg.lstsq(np.c_[pb, np.ones(len(pb))], pa, rcond=None)     # before 좌표 → after 좌표
    data = (coef[0, 0], coef[1, 0], coef[2, 0], coef[0, 1], coef[1, 1], coef[2, 1])
    return after.transform(before.size, Image.AFFINE, data, resample=Image.BILINEAR)


def locality(before, after, region):
    """(마스크 안 평균 변화, 얼굴 나머지 피부 평균 변화, 비율). 얼굴 미검출이면 None."""
    pb, pa = landmarks.detect(before), landmarks.detect(after)
    if pb is None or pa is None:
        return None
    al = align(before, after.resize(before.size), pb, landmarks.detect(after.resize(before.size)))
    m = np.asarray(landmarks.region_mask(before, pb, region), dtype=float) / 255
    face = np.asarray(landmarks.region_mask(before, pb, "full_face_skin"), dtype=float) / 255
    rest = np.clip(face - m, 0, 1)
    d = np.abs(np.asarray(before.convert("L"), dtype=float) - np.asarray(al.convert("L"), dtype=float))
    inside = float((d * m).sum() / max(m.sum(), 1))
    other = float((d * rest).sum() / max(rest.sum(), 1))
    return round(inside, 2), round(other, 2), (round(inside / other, 2) if other else None)


def item_dirs(batch_id):
    hits = [p for p in (ROOT / "outputs").rglob(batch_id) if p.is_dir()]
    if not hits:
        sys.exit(f"배치 폴더 없음: {batch_id}")
    return hits[0], sorted(d for d in hits[0].iterdir() if (d / "meta.json").exists())


def gate_row(meta, when):
    r = (meta.get("after_results") or {}).get(when) or {}
    st, idn = r.get("structure") or {}, r.get("identity") or {}
    return {"align_pct": st.get("align_err_pct"), "luma": st.get("luma_diff"), "structure_passed": st.get("passed"),
            "identity": idn.get("similarity"), "identity_gate": idn.get("gate"), "fail_reasons": r.get("fail_reasons")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_id")
    ap.add_argument("--ab", action="store_true", help="유료: 참조가 붙는 세트에서 같은 Before 로 켬/끔 After 새로 편집")
    a = ap.parse_args()
    bdir, dirs = item_dirs(a.batch_id)
    out = ROOT / "outputs" / "_ab_0915" / a.batch_id
    out.mkdir(parents=True, exist_ok=True)
    report = {"batch": a.batch_id, "items": [], "ab": []}

    todo = []
    for d in dirs:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        region = load("treatments.yaml")[meta["treatment"]]["mask_region"]
        af0 = meta["afters"][0]
        v_after = af0.get("after_variation") or meta["variation"]
        bf, aft = next(d.glob("*_before.jpg")), next(d.glob("*_after*.jpg"), None)
        before = Image.open(bf).convert("RGB")
        row = {"item": d.name, "rig": meta["variation"]["rig"]["key"], "when": af0["when"],
               "angle": meta["variation"]["angle"]["key"], "passed": meta.get("passed"),
               "fail_reasons": meta.get("fail_reasons"), "cost": meta.get("cost"),
               "refs": refs.pick_files("clinical", v_after, treatment=meta["treatment"], when=af0["when"]),
               **gate_row(meta, af0["when"]),
               "locality": locality(before, Image.open(aft).convert("RGB"), region) if aft else None}
        report["items"].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if a.ab and row["refs"]:
            todo.append((d, meta, region, af0, v_after, bf, before))

    if a.ab and todo:
        load_key()
        from bna.providers.openai_img import OpenAIProvider
        prov = OpenAIProvider()
        style = " ".join((ROOT / "config" / "prompts" / "edit_style_refs.md").read_text(encoding="utf-8").split())

        def one(job, tag):
            d, meta, region, af0, v_after, bf, before = job
            pb = landmarks.detect(before)
            mask_b = png(landmarks.region_mask(before, pb, region)) if pb is not None else None
            prompt = prov.adapt_prompt(af0["after_prompt"], "after")
            rb = refs.pick("clinical", v_after, treatment=meta["treatment"], when=af0["when"]) if tag == "on" else []
            raw = prov.edit(bf.read_bytes(), prompt + (" " + style if rb else ""), mask_b, rb, meta["aspect"])
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            pp = Image.open(io.BytesIO(postprocess.apply(img, v_after["quality"]["key"], "clinical", 7))).convert("RGB")
            pp.save(out / f"{d.name}_{tag}.jpg", quality=92)
            idn, st = identity.check(before, pp), structure.check(before, pp, "clinical", region)
            return {"item": d.name, "refs": tag, "size": list(img.size), "identity": idn.get("similarity"),
                    "identity_gate": idn.get("gate"), "align_pct": st.get("align_err_pct"), "luma": st.get("luma_diff"),
                    "structure_passed": st.get("passed"), "locality": locality(before, pp, region)}

        with ThreadPoolExecutor(4) as ex:
            futs = [ex.submit(one, job, tag) for job in todo for tag in ("off", "on")]
            for f in futs:
                try:
                    r = f.result()
                except Exception as e:                       # noqa: BLE001 — 한 장 실패가 나머지 비교를 지우지 않게
                    r = {"error": repr(e)[:300]}
                report["ab"].append(r)
                print("[AB] " + json.dumps(r, ensure_ascii=False), flush=True)

    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("saved", out / "report.json")


if __name__ == "__main__":
    main()
