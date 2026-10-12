"""기존 인물에 시점 추가 (2026-10-12 연서님 "이미 만든 사람에서 2주·4주 사진을 더 뽑고 싶어").

원리: 시리즈의 After 는 원래 전부 **같은 Before 한 장**을 기준으로 만든다(batch.run_item ② 머리말 —
After 를 다음 기준으로 쓰면 얼굴이 흘러간다). 그래서 저장된 Before 를 그대로 가져와 원하는 시점의 After 만
같은 길로 만들면 같은 사람의 다른 시점이 된다. Before 는 다시 그리지 않는다(비용 = 시점마다 After·검수만).

원본에서 그대로 가져오는 것: Before 사진 · 인물/장면 변주 · 임상 리그 · Before 강도 · 최종 효과 강도(pin).
새로 정하는 것: 지금 설정의 After 문장·금지문(그새 고친 규칙은 반영된다), 임상 1주~ 옷 추첨.

쓰는 법 (항목 폴더 = outputs/<회차>/<항목>, 또는 '<회차>/<항목>'):
  PYTHONPATH=src python -m bna.extend outputs/20261001-101500-ab12/0003 --when 2w --when 4w            # 미리보기(키·비용 0)
  PYTHONPATH=src python -m bna.extend 20261001-101500-ab12/0003 --when 2w --estimate                   # 예상 비용
  PYTHONPATH=src python -m bna.extend 20261001-101500-ab12/0003 --when 2w --run                        # 실생성(유료)
결과는 새 회차 폴더(outputs/<새 회차>/<같은 항목 번호>)에 Before + 새 After 로 남고 meta["extends"] 가 원본을 가리킨다.
"""
import argparse, asyncio, json
from pathlib import Path
from .spec import ROOT, load, build_prompts, defaults_for, rig_on, TIMELINE_ORDER

# 원본 meta 의 variation 에서 build_prompts 가 다시 만드는 칸 — 넘기지 않고 pin 으로 고정한다
DERIVED = ("rig", "before_severity", "effect_level", "timeline")


def load_item(path) -> dict:
    """항목 폴더에서 meta·Before 를 읽는다. 재시도 보존 컷(<id>-t<n>)도 같은 사람이라 받는다."""
    d = Path(path)
    if not d.is_dir():
        d = ROOT / "outputs" / path
    if not (d / "meta.json").exists():
        raise SystemExit(f"항목 폴더가 아니다(meta.json 없음): {path}")
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    befores = sorted(d.glob("*_before.jpg"))
    if not befores:
        raise SystemExit(f"Before 사진이 없다: {d}")
    if meta.get("demo"):
        raise SystemExit("데모 항목이다 — 가짜 사진이라 시점을 붙일 수 없다")
    return {"dir": d, "meta": meta, "before_path": befores[0]}


def plan(path, whens) -> dict:
    """시점 검증 + Batch 에 넘길 base·variation. 돈 쓰는 일은 여기서 하지 않는다."""
    it = load_item(path)
    m = it["meta"]
    tr, mode = m["treatment"], m["mode"]
    allowed = list(load("treatments.yaml")[tr].get("timeline") or ["2w"])
    bad = [w for w in whens if w not in allowed]
    if bad:
        raise SystemExit(f"{tr} 는 시점 {bad} 가 없다 (가능: {allowed}) — 늘리려면 treatments.yaml timeline 부터")
    whens = [w for w in TIMELINE_ORDER if w in whens]
    had = [a.get("when") for a in (m.get("afters") or [])] or [((m.get("variation") or {}).get("timeline") or {}).get("key")]
    v = m["variation"]
    iid = str(m.get("item_id") or it["dir"].name)
    num = iid.split("-")[0]                              # 재시도 보존 컷 '0003-t2' 도 번호는 0003
    base = {"before_b": it["before_path"].read_bytes(),
            "src": f'{m.get("batch_id") or it["dir"].parent.name}/{iid}',
            "item_id": iid, "idx": int(num) if num.isdigit() else 0,
            "pin": {k: (v.get(k) or {}).get("key") for k in ("rig", "before_severity", "effect_level") if v.get(k)}}
    variation = {k: x for k, x in v.items() if k not in DERIVED}
    return {"treatment": tr, "mode": mode, "whens": whens, "already": [w for w in whens if w in had],
            "had": [w for w in had if w], "base": base, "variation": variation, "before_path": str(it["before_path"])}


def estimate(pl, edit, qa, pass_rate=0.5) -> dict:
    """예상 호출·비용 — 키 없이 설정만 읽는다 (10-12 티모 흠 ① "돈 안 쓰는데 키 없으면 죽음").

    Batch.estimate 는 생성자가 공급자를 잡아야 해서 키가 필요하고, 시점마다 그리기 1장만 셌다.
    여기는 After 한 장에 실제로 나가는 호출을 다 센다: 그리기(편집/새로 그리기) + 임상 2단계 편집 + 골 메우기 뒤 재촬영 + 검수.
    '시도'(세트를 다시 하는 횟수)와 '호출'(공급자에 나가는 콜)을 따로 적는다 (흠 ② expected_calls 가 시도 수였다).
    빠진 것: 직후 컷 패치 위치 게이트의 재그리기(직후를 추가할 때만, 어림 불가) — 그래서 '최소'다."""
    from .batch import MAX_ATTEMPTS
    price, rig = load("pricing.yaml"), load("clinical_rig.yaml")
    spec = build_prompts(pl["treatment"], pl["mode"], pl["variation"], None, series=pl["whens"], pin=pl["base"]["pin"])
    clin = pl["mode"] == "clinical"
    main_key = "edit" if spec["generation"] == "edit" else "generate"
    ff, sp = rig.get("fold_fill") or {}, rig.get("second_pass") or {}
    per_when, img_calls, cost = {}, 0, 0.0
    for af in spec["afters"]:
        c = {main_key: 1}
        if clin and main_key == "edit" and rig_on(sp, pl["treatment"]) and af.get("second_pass_prompt"):
            c["2단계 편집"] = 1
        if clin and rig_on(ff, pl["treatment"]) and ff.get("retake"):
            c["재촬영"] = 1
        n = sum(c.values())
        usd = price[edit][main_key] + (n - 1) * price[edit]["edit"] + price[qa]["qa"]
        per_when[af["when"]] = {"이미지 호출": c, "검수 호출": 1, "1회 비용": round(usd, 3)}
        img_calls += n; cost += usd
    max_att = int(((rig.get("hires") or {}).get("max_attempts") or MAX_ATTEMPTS) if clin else MAX_ATTEMPTS)
    tries = min(max_att, 1 / max(pass_rate, 0.05))
    return {"시점별": per_when, "예상 시도(세트)": round(tries, 1), "최대 시도": max_att,
            "예상 이미지 호출": round(img_calls * tries), "예상 검수 호출": round(len(per_when) * tries),
            "예상 비용(USD, 최소)": round(cost * tries, 2), "최대 비용(USD)": round(cost * max_att, 2),
            "근거": f"통과율 {pass_rate:.0%} 가정 · 단가 pricing.yaml({edit}/{qa}, 추정치) · 직후 위치 게이트 재그리기 제외"}


def main():
    p = argparse.ArgumentParser(description="기존 인물에 시점 추가 (Before 재사용, After 만 생성)")
    p.add_argument("item", help="항목 폴더 — outputs/<회차>/<항목> 또는 <회차>/<항목>")
    p.add_argument("--when", action="append", required=True, choices=TIMELINE_ORDER, help="추가할 시점 (여러 번)")
    p.add_argument("--estimate", action="store_true", help="예상 호출·비용")
    p.add_argument("--run", action="store_true", help="실생성 (유료)")
    p.add_argument("--edit"); p.add_argument("--qa")
    a = p.parse_args()

    pl = plan(a.item, a.when)
    head = {"원본": pl["base"]["src"], "시술": pl["treatment"], "모드": pl["mode"], "원본 시점": pl["had"],
            "추가 시점": pl["whens"], "고정값": pl["base"]["pin"], "Before": pl["before_path"]}
    if pl["already"]:
        head["주의"] = f"원본에 이미 있는 시점 {pl['already']} — 같은 시점을 한 장 더 뽑는다"
    if not a.estimate and not a.run:
        # 미리보기 — 키·비용 0. seed 는 원본에 안 남아 있어 None(임상 옷 추첨이 매번 다를 수 있다).
        spec = build_prompts(pl["treatment"], pl["mode"], pl["variation"], None, series=pl["whens"], pin=pl["base"]["pin"])
        head["고정 확인"] = {k: (spec["variation"].get(k) or {}).get("key") for k in pl["base"]["pin"]}
        head["After"] = [{"시점": af["when"], "프롬프트": af["after_prompt"]} for af in spec["afters"]]
        print(json.dumps(head, ensure_ascii=False, indent=1)); return
    d = defaults_for(pl["mode"])
    if a.estimate:
        print(json.dumps({**head, **estimate(pl, a.edit or d["edit"], a.qa or d["qa"])}, ensure_ascii=False, indent=1)); return
    from .batch import Batch
    b = Batch(pl["treatment"], pl["mode"], 1, None, None, d["gen"], a.edit or d["edit"], a.qa or d["qa"],
              series=pl["whens"], base=pl["base"])
    print(json.dumps({**head, "회차": b.batch_id, **asyncio.run(b.extend(pl["variation"]))}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
