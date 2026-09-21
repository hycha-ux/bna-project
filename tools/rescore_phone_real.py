"""판정 끝난 컷에 **새 문항 하나만** 다시 채점한다 (2026-09-21, 빌디 제안 → 티모 구현).

왜: 자동 검수 `ai_look`("AI 같아 보이지 않나")이 사람 탈락 사유 1위인데 한 장도 못 걸렀다.
  실측(전 회차 원장) — vision 미달 사유 누계: effect_visible 23 · drift 7 · fingers 3 · hair 1 ·
  hands_absent 1 · **ai_look 0**. 사람이 'AI 티'로 버린 31장의 기계 점수는 10점 15 · 9점 13 · 8점 3 이고,
  사람이 채택한 39장은 9점 30 · 10점 5 · 8점 2 · 7점 2 다 — **버린 쪽이 오히려 더 높다.** 변별력이 없다.

고치는 축 (빌디 초안 `docs/ai-look-item-0921-buildy.md`):
  ① 문항을 "결함이 있나"에서 **"폰으로 찍은 사진으로 믿기나"(phone_real)** 로 뒤집는다.
  ② **점수를 모델에게 묻지 않는다.** 모델은 '티'를 *짚기만* 하고 점수는 코드가 뺀다(티 하나당 -2).
     이게 핵심이다 — 0~10 을 물으면 모델은 9 에 눌러앉는다(위 실측이 그 증거다). 09-18 교훈
     "비전 모델은 세게 말고 짚게"와 같은 처방이다.
  ③ 강도(obvious/subtle)를 같이 받아 둔다 — 감점 폭(-2 고정 / obvious -2·subtle -1)을 **재호출 없이**
     오프라인에서 갈아 끼워 비교하려는 것이다. 한 번 부른 값으로 여러 규칙을 잰다.
  ④ 모델이 스스로 매긴 0~10(`model_score`)도 같이 적는다 — "코드가 빼는 게 정말 나은가"의 대조군.

⚠ 이건 **실검수 경로가 아니다.** 여기서 컷을 정한 뒤에야 qa_checklist.yaml 을 고친다.
   그때 키 이름은 `ai_look` 이 아니라 `phone_real` 이어야 한다 — 같은 이름으로 뜻만 바꾸면
   옛 회차 점수와 새 점수가 한 열에 섞여 비교가 조용히 무의미해진다(`fingers`→`hands_absent` 때 배운 것).

쓰기:
  python tools/rescore_phone_real.py --model gpt      [--limit N] [--dry]
  python tools/rescore_phone_real.py --model gemini   [--limit N] [--dry]
  python tools/rescore_phone_real.py --report                 # 두 원장 대조 + 컷 후보
원장: outputs/rescore/phone_real-<model>.jsonl  (append, item_key 로 멱등 — 다시 돌려도 이미 잰 건 건너뛴다)
"""
import argparse, base64, io, json, os, re, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "outputs"
LEDGER_DIR = OUT / "rescore"

GEMINI_MODEL = "gemini-3.8-flash"     # 09-18 패치 게이트에서 고른 짚기 모델과 같은 것
KEYS = Path(os.environ.get("TEEMO_KEYS", r"C:\Users\medib\teemo\keys.env"))


def load_keys():
    """keys.env → 환경변수. 값은 절대 출력하지 않는다(이름만). 이미 들어 있으면 덮지 않는다."""
    if not KEYS.exists():
        return
    for line in KEYS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# ── 문항 ───────────────────────────────────────────────────────────────────────
# 읽는 사람이 아니라 **후기 앱을 넘기는 낯선 사람**의 눈으로 묻는다. "결함을 찾아라"가 아니라
# "믿기나"라고 물어야 하는 이유: 결함을 물으면 모델이 "약간의 매끈함이 있지만 전반적으로 사진 같다"고
# 적고 9 점을 준다(실측 note 가 전부 그 문형이다). 믿음은 한 군데만 어긋나도 깨지므로 티를 짚게 된다.
PROMPT_V1 = """These two photos are about to be published by a clinic as one real patient's before/after.
Image 1 = BEFORE, image 2 = AFTER. Both are supposed to be ordinary smartphone snapshots the patient took herself.

Answer ONE question: if a stranger scrolling a review app saw these, would they believe they are real phone photos of a real person?

Do NOT grade quality and do NOT give an overall impression first. Instead, hunt for TELLS.
A tell is one concrete thing you can point at that gives away the image was generated or heavily retouched. For example:
- skin that is too even: no pores, no fine lines where a real face has them, uniform tone across cheek and jaw
- an airbrushed or waxy sheen, a glow that no phone camera produces
- left and right side of the face too symmetric, or teeth/eyes/nostrils too perfect
- hair that melts into the background, strands that merge, a hairline that is painted rather than grown
- edges or textures that go soft or repeat where they should not (ears, earrings, collar, glasses, fabric weave)
- lighting or shadows that do not agree with each other, or a background that is blurred in a way a phone lens does not blur
- jewellery, text, buttons, patterns that are warped or nonsensical
- the two photos look like the same rendered face pasted twice rather than one person photographed twice
- anything else that made you hesitate

Rules:
- Report every tell you actually see, in either image. If you see none, return an empty list — that is a valid and expected answer.
- One entry per tell. Do not merge two different tells into one sentence, and do not repeat the same tell for both images; if it is in both, say "both".
- "strength": "obvious" if an ordinary viewer would notice it without being told; "subtle" if only someone looking for it would.
- Do not list the treatment effect itself as a tell, and do not list things that are normal in phone photos (jpeg noise, motion blur, bad framing, harsh flash, uneven lighting, a messy room).
- Do not invent a tell to seem thorough. An empty list is better than a made-up one.

Reply with JSON only:
{"tells": [{"tell": "<what you see, short>", "where": "before|after|both", "part": "<face part or object>", "strength": "obvious|subtle"}],
 "believable": true|false,
 "model_score": 0-10,
 "note": "<one short sentence>"}
"model_score" is your own 0-10 for "would a stranger believe this is a real phone photo" (10 = fully believable)."""

# v2 — v1 실측 뒤에 만든 변형 (2026-09-21).
# v1(빌디 초안 그대로)은 사람이 'AI 티'로 버린 6장에 **전부 티 0개**를 냈다. 사진 자체의 질감·아티팩트를
# 물었기 때문인데, 사람이 남긴 'AI 티' 메모 6건은 한 건도 질감 얘기가 아니었다:
#   "동일한 각도, 구도, 표정"(2) · "주름·각도·입모양·눈뜸 정도가 모두 비포와 동일" · "시술 부위 중앙이 잘림"
#   · "패치 위치 이상, 중앙만 보정" · "수염이 갑작스럽게 생김"
# 전부 **두 장을 나란히 놓았을 때**만 보이는 것이다. 그래서 v2 는 질문을 한 장에서 한 쌍으로 옮긴다 —
# "이 사진이 AI 같나"가 아니라 "이 두 장이 같은 사람을 다른 날 두 번 찍은 것으로 믿기나".
# ⚠ v1 과 섞어 세지 마라(원장 파일이 갈려 있다) — 같은 이름 다른 자다.
PROMPT_V2 = """A clinic is about to publish these two photos as one real patient's before/after.
Image 1 = BEFORE, image 2 = AFTER. They are supposed to be two separate photographs of the same real person, taken on two different days, weeks apart.

Answer ONE question: would a stranger believe that these are two real photographs of one real person, rather than one picture that was generated and then edited?

Hunt for TELLS. A tell is one concrete thing you can point at. Look at the PAIR first, then each image:
- the two are too identical to be two separate photographs: same head angle, same gaze, same eyelid opening, same mouth shape, same stray hairs, same folds in the clothing, same shadow on the wall. Two real photos taken weeks apart never line up that exactly.
- only part of the face changed while everything else is pixel-identical, so it reads as an eraser stroke rather than a new photograph
- something appeared or vanished that a treatment cannot explain: facial hair, a mole, a scar, an earring, redness or spots, a different neckline
- the treated area is cut off, cropped out, or hidden in one of the two photos
- the face changed shape, age or proportions between the two, so they read as two different people
- a dressing, sticker, mark or bruise sits somewhere the treatment was not
- single-image giveaways: skin with no pores where a real face has them, a waxy or airbrushed sheen, too-perfect symmetry, hair melting into the background, warped jewellery/text/patterns

Rules:
- Report every tell you actually see. If you see none, return an empty list.
- One entry per tell; do not merge two into one sentence.
- "strength": "obvious" if an ordinary viewer would notice without being told; "subtle" if only someone looking would.
- Do NOT count as tells: the treatment effect itself, jpeg noise, motion blur, framing, harsh flash, a messy room, or the two photos simply having similar lighting because they were taken in the same clinic room.
- Do not invent a tell to seem thorough.

Reply with JSON only:
{"tells": [{"tell": "<what you see, short>", "where": "before|after|both|pair", "part": "<face part or object>", "strength": "obvious|subtle"}],
 "believable": true|false,
 "model_score": 0-10,
 "note": "<one short sentence>"}
"model_score" is your own 0-10 for "would a stranger believe these are two real photos of one real person" (10 = fully believable)."""

PROMPTS = {"v1": PROMPT_V1, "v2": PROMPT_V2}


# ── 채점 ───────────────────────────────────────────────────────────────────────
def score_of(tells, rule="flat2"):
    """티 목록 → 점수. **모델이 아니라 코드가 뺀다.**

    rule="flat2"  티 하나당 -2 (빌디 초안 그대로)
    rule="weight" obvious -2 · subtle -1 (강도를 쓰는 변형 — 재호출 없이 같은 원장으로 잰다)
    0 아래로는 안 내려간다(음수는 '얼마나 더 나쁜가'를 재지 못하고 평균만 흐린다).
    """
    if rule == "weight":
        pen = sum(2 if (t.get("strength") == "obvious") else 1 for t in tells)
    else:
        pen = 2 * len(tells)
    return max(0.0, 10.0 - pen)


def _norm(data):
    """모델 응답 → {tells, believable, model_score, note}. 모양이 틀리면 예외(원장에 None 을 적지 않는다)."""
    tells = data.get("tells")
    if not isinstance(tells, list):
        raise ValueError(f"tells 가 리스트가 아니다: {type(tells).__name__}")
    out = []
    for t in tells:
        if not isinstance(t, dict):
            raise ValueError("tells 원소가 객체가 아니다")
        st = str(t.get("strength", "")).lower()
        out.append({"tell": str(t.get("tell", ""))[:200], "where": str(t.get("where", ""))[:16],
                    "part": str(t.get("part", ""))[:60],
                    "strength": st if st in ("obvious", "subtle") else "subtle"})
    ms = data.get("model_score")
    ms = float(ms) if isinstance(ms, (int, float)) and not isinstance(ms, bool) else None
    return {"tells": out, "believable": bool(data.get("believable")),
            "model_score": ms, "note": str(data.get("note", ""))[:200]}


# ── 모델 호출 ──────────────────────────────────────────────────────────────────
def ask_gpt(before, after, prompt):
    from bna.providers import get
    p = get("openai")
    r = p.chat_json(prompt, images=(before, after), purpose="rescore_phone_real")
    return _norm(r["data"]), r.get("usage") or {}, r.get("model")


def ask_gemini(before, after, prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY 없음")
    parts = [{"text": prompt}]
    for b in (before, after):
        mime = "image/png" if b[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(b).decode()}})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"response_mime_type": "application/json", "temperature": 0}}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    j = json.load(urllib.request.urlopen(req, timeout=180))
    txt = j["candidates"][0]["content"]["parts"][0]["text"]
    # 원장 — 다른 Gemini 용도(patch_gate)와 한 파일이라 purpose 로 칸을 가른다
    try:
        with open(OUT / "usage.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": round(time.time(), 3), "path": "gemini:generateContent",
                                "model": GEMINI_MODEL, "usage": j.get("usageMetadata") or {},
                                "purpose": "rescore_phone_real"}) + "\n")
    except Exception:
        pass
    return _norm(json.loads(txt)), (j.get("usageMetadata") or {}), GEMINI_MODEL


ASK = {"gpt": ask_gpt, "gemini": ask_gemini}


# ── 대상 고르기 ────────────────────────────────────────────────────────────────
def candidates():
    """사람 판정이 끝났고 그림 두 장이 다 있는 컷. 사람이 본 **그 파일**을 그대로 채점한다
    (후처리된 저장본이 사람이 본 화면이다 — 다시 만들지 마라)."""
    rows = []
    for rv in sorted(OUT.glob("*/*/review.json")):
        d = rv.parent
        mp = d / "meta.json"
        if not mp.exists():
            continue
        m = json.loads(mp.read_text(encoding="utf-8"))
        r = json.loads(rv.read_text(encoding="utf-8"))
        # 기계 점수가 붙은 시점 = after_results 의 마지막 키(batch.py 가 meta["vision"] 에 싣는 그 컷).
        # 옛 회차는 after_results 도 `_after_<시점>` 접미도 없다(파일이 그냥 `_after.jpg`) — 없을 때만
        # 쓰는 폴백임을 분명히 둔다. '마지막 시점'의 정의가 두 갈래가 되면 안 된다.
        when = (list((m.get("after_results") or {}).keys()) or [None])[-1]
        order = {"immediate": 0, "1w": 1, "2w": 2, "4w": 3}
        afters = sorted(p for p in d.iterdir() if "_after" in p.stem and p.suffix in (".jpg", ".png"))
        pick = None
        if when:
            pick = next((p for p in afters if p.stem.endswith(f"_after_{when}")), None)
        if pick is None and afters:
            pick = sorted(afters, key=lambda p: order.get(p.stem.split("_after_")[-1], -1))[-1]
        if pick is None:
            continue
        # ⚠ Before 가 여러 장인 폴더가 35개 있다 — 재시도로 Before 를 다시 그린 회차다(REDO_BEFORE).
        #   아무거나 집으면 **다른 사람의 Before 와 짝지어 채점**하게 된다(동일인 문항이 아니어도
        #   "같은 얼굴 두 번"을 묻는 이 문항이 통째로 틀린 짝을 본다). 고른 After 와 **접두가 같은** 것만 쓴다.
        stem = pick.stem.split("_after")[0]
        befores = [p for p in d.iterdir()
                   if p.suffix in (".jpg", ".png") and p.stem == f"{stem}_before"]
        if not befores:
            continue
        v = ((m.get("vision") or {}).get("scores") or {}).get("ai_look") or {}
        rows.append({"key": f"{d.parent.name}/{d.name}", "dir": str(d),
                     "before": str(befores[0]), "after": str(pick), "when": when,
                     "mode": m.get("mode"), "treatment": m.get("treatment"),
                     "passed": m.get("passed"), "prompt_version": m.get("prompt_version"),
                     "pick": r.get("pick"), "tags": r.get("tags") or [],
                     "ai_look": v.get("score"), "ai_look_note": v.get("note", "")})
    return rows


def run(model, limit, dry, tag=None, only_passed=False, variant="v1"):
    rows = candidates()
    # 좁히기 — 전수 전에 "이 문항이 목표를 잡기는 하나"를 싸게 확인하려는 용도다.
    # ⚠ 좁혀서 잰 값으로 컷을 정하지 마라(걸린 것 중 사람도 버린 비율이 분모째 부풀어 100% 로 보인다).
    if tag:
        rows = [r for r in rows if tag in (r["tags"] or [])]
    if only_passed:
        rows = [r for r in rows if r["passed"] is True]
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    led = LEDGER_DIR / (f"phone_real-{model}.jsonl" if variant == "v1" else f"phone_real-{model}-{variant}.jsonl")
    done = set()
    if led.exists():
        for ln in led.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                try:
                    done.add(json.loads(ln)["key"])
                except Exception:
                    pass
    todo = [r for r in rows if r["key"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"대상 {len(rows)}장 · 이미 잰 것 {len(done)} · 이번에 {len(todo)}장 ({model})")
    if dry:
        for r in todo[:5]:
            print("  ", r["key"], r["mode"], r["pick"], "ai_look", r["ai_look"], "|", Path(r["after"]).name)
        return
    ask = ASK[model]
    ok = err = 0
    for i, r in enumerate(todo, 1):
        try:
            b = Path(r["before"]).read_bytes()
            a = Path(r["after"]).read_bytes()
            res, usage, mname = ask(b, a, PROMPTS[variant])
        except Exception as e:                       # 한 장 실패가 회차를 죽이지 않는다. 원장엔 에러로 남긴다
            err += 1
            rec = {**{k: r[k] for k in ("key", "mode", "treatment", "passed", "pick", "tags", "ai_look", "when")},
                   "model": model, "error": f"{type(e).__name__}: {e}"[:300], "at": round(time.time(), 3)}
            with open(led, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"  [{i}/{len(todo)}] {r['key']} ✗ {rec['error'][:90]}")
            continue
        rec = {**{k: r[k] for k in ("key", "mode", "treatment", "passed", "pick", "tags", "ai_look",
                                    "ai_look_note", "when", "prompt_version")},
               "model": model, "vendor_model": mname, "variant": variant, "at": round(time.time(), 3),
               **res, "score_flat2": score_of(res["tells"], "flat2"),
               "score_weight": score_of(res["tells"], "weight"), "usage": usage}
        with open(led, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        ok += 1
        print(f"  [{i}/{len(todo)}] {r['key']} {r['mode']} 사람={r['pick']} 옛ai_look={r['ai_look']} "
              f"→ 티 {len(res['tells'])}개 flat2={rec['score_flat2']} model={res['model_score']}")
    print(f"완료 — 성공 {ok} · 실패 {err} · 원장 {led}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=list(ASK))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--tag", help="이 사람 태그가 달린 컷만 (예: \"AI 티\")")
    ap.add_argument("--passed", action="store_true", help="기계가 통과시킨 컷만")
    ap.add_argument("--variant", choices=list(PROMPTS), default="v1", help="문항 판(v1=빌디 초안 · v2=한 쌍 질문)")
    a = ap.parse_args()
    load_keys()
    if a.report:
        import rescore_report
        rescore_report.main()
        return
    if not a.model:
        ap.error("--model gpt|gemini 또는 --report")
    run(a.model, a.limit, a.dry, a.tag, a.passed, a.variant)


if __name__ == "__main__":
    main()
