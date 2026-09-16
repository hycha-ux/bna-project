"""원내 보관 B&A 사진(노션 공개 페이지) → 씨앗 은행 원본 폴더로 모은다 (2026-09-16 빌디, 연서님 요청).

무엇을 하나. 노션 공개 페이지(*.notion.site)의 토글/글머리 트리를 그대로 걸어 내려가서
사진마다 "어느 묶음 → 누구 → 전/후 → 몇 번 각도"인지를 붙여 한 폴더에 내려받고, 그 목록을
manifest.json 으로 남긴다. 씨앗 은행의 다음 단계(정제 → 씨앗 → 파생 → 측정, 티모 PC)는
이 폴더를 원본으로 읽는다.

  python tools/notion_ba_pull.py --dry                      # 무엇을 몇 장 받을지만 센다(다운로드 0)
  python tools/notion_ba_pull.py --out C:/Users/medib/teemo-raw/raw/nasolabial
  python tools/notion_ba_pull.py --include-ai --no-selfie ...

지키는 것.
  ① 사진은 리포 밖으로만 받는다 — `--out` 이 리포 안이면 죽는다(실제 환자 얼굴).
  ② AI 가 그린 묶음(토글 이름에 'AI', 파일명 grok-image…)은 기본 제외 — 씨앗은 실제 환자여야 한다.
     제외한 것도 manifest 에 skipped 로 남긴다(왜 빠졌는지가 보여야 다음 사람이 다시 안 센다).
  ③ '부분 모델'(눈 가리고 써야 하는 분) 표시를 사람 단위로 붙인다. 지금은 표시만 — 가리는 건 정제 단계.
  ④ 사람마다 '메디컬포토(M)'·'셀카(S)' 두 묶음이 있다 — 둘 다 실제 환자라 둘 다 받고 manifest 의
     shot(medical/selfie)로 가른다. 임상 씨앗만 원하면 --no-selfie.
  ⑤ 팔자가 아닌 것(눈밑필러·입술필러 대체 건)은 treatment 를 달리 적고 기본 제외.
  ⑥ 토큰이 없다 — 공개 페이지가 브라우저에 주는 것과 같은 경로(api/v3/loadPageChunk, /image/)만 쓴다.
     이미지 주소는 5분짜리 서명 URL 이라 저장하지 않고, 노션 블록 id 만 남긴다(다시 받을 때 그걸로 받는다).

폴더 구조(--out 아래):
  <used>/<batch>/<person>/<전|후>_<n>.jpg   예) 사용전/260623/정인좌/전_4.jpg
  manifest.json                             {treatment, source, pulled_at, files:[…], skipped:[…]}

⚠ 페이지 구조가 손으로 만든 거라 층이 고르지 않다(사용완료 쪽은 날짜 없이 번호만, 사용 전 쪽은
  날짜 글머리 아래 '부분 모델' 토글 아래 사람). 그래서 규칙이 아니라 **이름으로** 층을 알아본다 —
  '전'/'후'로 시작하면 전후, 'AI'가 들면 AI, 숫자만이면 각도(또는 사용완료의 사람 번호). 못 알아본
  이름은 그대로 폴더명이 된다(버리지 않는다).
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAGE = "https://bouncy-elderberry-4a8.notion.site/BA-361394e25dff807793fad1ebc43b06c6"
TREATMENT = "nasolabial"          # config/treatments.yaml 키. 페이지 제목이 '온볼라썸(팔자필러)'.
UA = "Mozilla/5.0 (bna notion_ba_pull)"

sys.stdout.reconfigure(encoding="utf-8")


# ── 노션 공개 API ────────────────────────────────────────────────────────────
def page_ref(url: str):
    """URL → (사이트 origin, 페이지 uuid)."""
    u = urllib.parse.urlparse(url)
    m = re.search(r"([0-9a-f]{32})", u.path)
    if not m:
        sys.exit(f"페이지 id 를 URL 에서 못 찾음: {url}")
    h = m.group(1)
    return f"{u.scheme}://{u.netloc}", f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def post(origin: str, path: str, body: dict, tries: int = 4) -> dict:
    req = urllib.request.Request(
        f"{origin}/api/v3/{path}", data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "user-agent": UA})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:            # 429 = 너무 빨리 부름 → 쉬었다 다시
                raise
            time.sleep(4 * (i + 1))
        except (urllib.error.URLError, TimeoutError):
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))
    return {}


def _chunks(origin: str, pid: str) -> dict:
    """한 블록을 페이지처럼 열어 커서가 끝날 때까지 받는다. 접힌 토글은 이 방법으로만 안이 나온다."""
    got, cursor, n = {}, {"stack": []}, 0
    while True:
        d = post(origin, "loadPageChunk", {"pageId": pid, "limit": 100, "cursor": cursor,
                                           "chunkNumber": n, "verticalColumns": False})
        for k, v in (d.get("recordMap") or {}).get("block", {}).items():
            vv = v.get("value") or {}
            got[k] = vv.get("value", vv)
        cursor, n = d.get("cursor") or {"stack": []}, n + 1
        if not cursor.get("stack") or n > 500:
            return got


def load_tree(origin: str, page_id: str, workers: int = 3) -> dict:
    """페이지 밑의 블록 전부 {id: value}. 한 번에 두 층쯤만 오므로, 자식이 비어 있는 블록을
    페이지처럼 다시 열기를 자식이 다 채워질 때까지 반복한다. 병렬 3 — 8 로 하면 429 를 맞는다(실측)."""
    from concurrent.futures import ThreadPoolExecutor
    blocks, opened = {}, set()
    todo = [page_id]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        while todo:
            opened.update(todo)
            for got in ex.map(lambda pid: _chunks(origin, pid), todo):
                blocks.update(got)
            # 있는 블록 중 자식이 빈 것만 연다 — 없는 id(사진·글 잎)를 하나씩 열면 1,300번을 부른다
            todo = [k for k, v in blocks.items()
                    if k not in opened and v.get("content") and any(c not in blocks for c in v["content"])]
            print(f"  블록 {len(blocks)}개 · 더 열 것 {len(todo)}개", flush=True)
    return blocks


def plain(v: dict) -> str:
    t = (v.get("properties") or {}).get("title") or []
    return "".join(seg[0] for seg in t if seg and isinstance(seg[0], str)).strip()


def image_src(v: dict):
    src = ((v.get("properties") or {}).get("source") or [[None]])[0][0]
    return src or (v.get("format") or {}).get("display_source")


def image_url(origin: str, block_id: str, src: str) -> str:
    # 브라우저가 쓰는 프록시 — 서명 URL 을 대신 만들어 준다. width 를 안 주면 원본 크기.
    return f"{origin}/image/{urllib.parse.quote(src, safe='')}?table=block&id={block_id}&cache=v2"


# ── 이름 → 뜻 ────────────────────────────────────────────────────────────────
def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def classify(path: list, src: str) -> dict:
    """조상 이름들 → {used, batch, person, side, angle, partial, kind, treatment}."""
    names = [norm(p) for p in path if norm(p)]
    out = {"used": None, "batch": None, "person": None, "side": None, "angle": None,
           "partial": False, "kind": "clinic", "shot": None, "treatment": TREATMENT}
    if "grok-image" in src.lower():
        out["kind"] = "ai"
    for n in names:
        low = n.lower()
        if n.startswith("사용완료"):
            out["used"] = "사용완료"; continue
        if n.startswith("사용 전") or n.startswith("사용전"):
            out["used"] = "사용전"; continue
        if re.match(r"^\d{6}", n):                        # 260623_64명(…) / 260811
            out["batch"] = n[:6]; continue
        if "부분" in n and "모델" in n:
            out["partial"] = True; continue
        if re.match(r"^ai( |$|_|이미지)", low) or low == "ai":
            out["kind"] = "ai"; continue
        if n.startswith("셀카"):
            out["shot"] = "selfie"; continue
        if n.startswith("메디컬포토"):
            out["shot"] = "medical"; continue
        if "눈밑" in n:
            out["treatment"] = "filler_undereye"; continue
        if "입술" in n:
            out["treatment"] = "filler_lip"; continue
        if re.match(r"^전($|[\s(_.])", n):                     # 전 / 전(B) / 전_3장 / 전.
            out["side"] = "전"; continue
        if re.match(r"^후($|[\s(_.])", n):
            out["side"] = "후"; continue
        if re.fullmatch(r"\d{1,2}", n):
            # 전/후 밑의 숫자는 각도, 그 위의 숫자는 사용완료 쪽 사람 번호
            if out["side"]:
                out["angle"] = int(n)
            elif out["person"] is None:
                out["person"] = f"p{int(n):02d}"
            continue
        if re.fullmatch(r"\d{4}_\d{2}", n):                # 0515_06 같은 예약번호
            out["person"] = n; continue
        if out["person"] is None and out["side"] is None:
            out["person"] = re.sub(r"[\\/:*?\"<>|]", "_", n)[:40]
    return out


def walk(blocks: dict, page_id: str, origin: str):
    """이미지마다 (조상 이름 목록, 블록 id, source) — 트리 순서 그대로."""
    rows = []

    def rec(bid, path):
        v = blocks.get(bid)
        if not v:
            return
        t = v.get("type")
        if t == "image":
            src = image_src(v)
            if src:
                rows.append((path, bid, src))
            return
        label = plain(v) if t in ("toggle", "bulleted_list", "numbered_list", "text",
                                  "header", "sub_header", "sub_sub_header", "page") else ""
        for c in v.get("content") or []:
            rec(c, path + ([label] if label and bid != page_id else []))

    rec(page_id, [])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default=DEFAULT_PAGE)
    ap.add_argument("--out", help="받을 폴더(리포 밖). --dry 면 생략 가능")
    ap.add_argument("--dry", action="store_true", help="세기만 한다 — 다운로드 0")
    ap.add_argument("--include-ai", action="store_true")
    ap.add_argument("--no-selfie", action="store_true", help="셀카(S) 묶음은 빼고 메디컬포토만")
    ap.add_argument("--include-other", action="store_true", help="팔자가 아닌 시술 건도 받는다")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 n 장만(연결 확인용)")
    a = ap.parse_args()

    out = Path(a.out).resolve() if a.out else None
    if not a.dry:
        if not out:
            sys.exit("--out 이 필요하다(리포 밖 폴더).")
        if ROOT in out.parents or out == ROOT:
            sys.exit(f"--out 이 리포 안이다: {out} — 얼굴 사진은 리포에 두지 않는다.")

    origin, pid = page_ref(a.page)
    print(f"페이지 {pid} 읽는 중…", flush=True)
    blocks = load_tree(origin, pid)
    rows = walk(blocks, pid, origin)
    print(f"블록 {len(blocks)}개 · 이미지 {len(rows)}장")

    files, skipped, counts = [], [], {}
    seen_names = set()
    for path, bid, src in rows:
        c = classify(path, src)
        why = None
        if c["kind"] == "ai" and not a.include_ai:
            why = "AI 생성물"
        elif c["shot"] == "selfie" and a.no_selfie:
            why = "셀카 묶음"
        elif c["treatment"] != TREATMENT and not a.include_other:
            why = f"다른 시술({c['treatment']})"
        if why:
            skipped.append({"block": bid, "path": path, "why": why})
            continue
        used, batch, person = c["used"] or "미분류", c["batch"] or "-", c["person"] or "-"
        side = c["side"] or "전후미상"                           # 전/후 표시 없이 사람 밑에 바로 놓인 사진
        ext = (re.search(r"\.(jpe?g|png|webp|heic)", src.lower()) or [None, "jpg"])[1]
        base = (("셀카_" if c["shot"] == "selfie" else "") + side
                + (f"_{c['angle']}" if c["angle"] is not None else ""))
        rel = f"{used}/{batch}/{person}/{base}.{ext}"
        k = 2
        while rel in seen_names:                                # 같은 각도 두 장이면 _2, _3
            rel = f"{used}/{batch}/{person}/{base}_{k}.{ext}"; k += 1
        seen_names.add(rel)
        files.append({"file": rel, "block": bid, "used": used, "batch": batch, "person": person,
                      "side": c["side"], "angle": c["angle"], "shot": c["shot"], "partial": c["partial"],
                      "path": path})
        key = (used, batch, "부분모델" if c["partial"] else "일반")
        counts[key] = counts.get(key, 0) + 1

    persons = {(f["used"], f["batch"], f["person"]) for f in files}
    print(f"\n받을 것: {len(files)}장 · {len(persons)}명 · 제외 {len(skipped)}장")
    for k in sorted(counts):
        print(f"  {k[0]}/{k[1]} {k[2]}: {counts[k]}장")
    by_why = {}
    for s in skipped:
        by_why[s["why"]] = by_why.get(s["why"], 0) + 1
    for w, n in sorted(by_why.items()):
        print(f"  제외 · {w}: {n}장")
    sides, shots = {}, {}
    for f in files:
        sides[f["side"] or "미상"] = sides.get(f["side"] or "미상", 0) + 1
        shots[f["shot"] or "미표시"] = shots.get(f["shot"] or "미표시", 0) + 1
    print(f"  전/후: {sides} · 촬영: {shots}")

    if a.dry:
        return

    out.mkdir(parents=True, exist_ok=True)
    todo = files[:a.limit] if a.limit else files
    done, fail = 0, []
    for i, f in enumerate(todo, 1):
        dst = out / f["file"]
        if dst.is_file() and dst.stat().st_size > 0:
            done += 1; continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        url = image_url(origin, f["block"], next(s for p, b, s in rows if b == f["block"]))
        try:
            req = urllib.request.Request(url, headers={"user-agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                dst.write_bytes(r.read())
            done += 1
        except Exception as e:                                   # noqa: BLE001 — 한 장 실패로 전체를 안 멈춘다
            fail.append({"file": f["file"], "err": str(e)[:120]})
        if i % 25 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)} · 실패 {len(fail)}", flush=True)
    manifest = {
        "treatment": TREATMENT, "source": {"kind": "notion", "page": a.page, "title": plain(blocks[pid])},
        "pulled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "files": files, "skipped": skipped, "failed": fail,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n받음 {done}장 · 실패 {len(fail)}장 → {out}\nmanifest.json 저장")
    if fail:
        print("실패 목록은 manifest.failed — 다시 돌리면 받은 건 건너뛰고 실패한 것만 받는다.")


if __name__ == "__main__":
    main()
