"""강남언니에 실제로 올라간 전후 사진(드라이브 공유 폴더) → 씨앗 은행 '업로드본' 폴더로 모은다 (2026-09-16 빌디, 연서님 요청).

무엇을 하나. 티모가 드라이브에 정리한 폴더(`강남언니 전후사진 (날짜)/<상품>/<번호>_<제목>_<전|후_D+n>.jpg` + `index.csv`)를
그대로 받는다. index.csv 가 정본이다 — 번호·상품·상태(게시중/중단)·시술 태그·성별·연령·경과일·원본 URL 이 다 거기 있어서
사진 이름을 다시 해석하지 않는다. manifest.json 에는 그 표를 그대로 싣고, 어느 파일이 어디 갔는지만 덧붙인다.

  python tools/drive_ba_pull.py --dry                                  # 무엇을 몇 장 받을지만 센다
  python tools/drive_ba_pull.py --out C:/Users/medib/teemo-raw/uploads/gangnamunni
  python tools/drive_ba_pull.py --folder <드라이브 폴더 URL 또는 id> ...  # 기본은 config/seedbank.yaml uploads.gangnamunni.drive

왜 이 사진이 따로 은행이 되나(연서님 2026-09-16): "이걸 바탕으로 학습할 거야" — 실제로 **게시가 된** 전후 사진이라
어떤 구도·경과일·강도가 앱에서 통하는지의 표본이다. 씨앗(얼굴 파생용)과 목적이 달라 `uploads` 로 따로 두고,
화면에선 시술 칩 밑에 '강남언니 업로드본'으로 붙는다(상품 → 우리 시술 키 대응은 seedbank.yaml `product_map`).

지키는 것.
  ① 사진은 리포 밖으로만(--out 이 리포 안이면 죽는다). 앱에 공개된 사진이지만 환자 사진인 건 같다.
  ② 토큰이 없다 — 링크 공유 폴더가 브라우저에 주는 것과 같은 경로(embeddedfolderview, uc?export=download)만 쓴다.
     폴더가 '링크가 있는 모든 사용자'가 아니면 목록이 비어 나온다 → 그때는 티모에게 공유 설정을 묻는다.
  ③ 파일이 index.csv 에 없거나, csv 에 있는데 폴더에 없으면 manifest 에 남긴다(조용히 넘기지 않는다).
"""
import argparse
import csv
import html
import io
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
sys.path.insert(0, str(ROOT / "src"))
UA = "Mozilla/5.0 (bna drive_ba_pull)"
SOURCE = "gangnamunni"

sys.stdout.reconfigure(encoding="utf-8")


def folder_id(s: str) -> str:
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", s)
    return m.group(1) if m else s.strip()


def fetch(url: str, tries: int = 4) -> bytes:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"user-agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError):
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))
    return b""


def list_folder(fid: str) -> list:
    """링크 공유 폴더의 (id, 이름, 폴더인가) — 브라우저 임베드 목록을 읽는다. 비공개면 빈 목록."""
    page = fetch(f"https://drive.google.com/embeddedfolderview?id={fid}#list").decode("utf-8", "ignore")
    out = []
    for m in re.finditer(r'<div class="flip-entry" id="entry-([^"]+)"(.*?)flip-entry-title">([^<]*)<', page, re.S):
        eid, body, name = m.group(1), m.group(2), m.group(3)
        out.append((eid, html.unescape(name).strip(), "folder" in body.lower()))   # '&amp;' → '&' (0916 실측 28건)
    return out


def download(fid: str) -> bytes:
    data = fetch(f"https://drive.google.com/uc?export=download&id={fid}")
    if data[:15].lower().startswith(b"<!doctype html") or b"<html" in data[:200].lower():
        # 큰 파일의 '바이러스 검사 못 함' 확인 페이지 — confirm 토큰을 붙여 한 번 더
        m = re.search(rb'confirm=([0-9A-Za-z_-]+)', data)
        if m:
            data = fetch(f"https://drive.google.com/uc?export=download&confirm={m.group(1).decode()}&id={fid}")
    return data


def default_folder() -> str:
    try:
        from bna.spec import load                                   # noqa: E402
        return (((load("seedbank.yaml") or {}).get("uploads") or {}).get(SOURCE) or {}).get("drive") or ""
    except Exception:                                                  # noqa: BLE001 — yaml 이 없어도 --folder 로 돌 수 있게
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default=None, help="드라이브 폴더 URL/id (기본: seedbank.yaml uploads.gangnamunni.drive)")
    ap.add_argument("--out")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 n 장만(연결 확인용)")
    a = ap.parse_args()

    folder = a.folder or default_folder()
    if not folder:
        sys.exit("--folder 가 필요하다(또는 config/seedbank.yaml uploads.gangnamunni.drive).")
    out = Path(a.out).resolve() if a.out else None
    if not a.dry:
        if not out:
            sys.exit("--out 이 필요하다(리포 밖 폴더).")
        if ROOT in out.parents or out == ROOT:
            sys.exit(f"--out 이 리포 안이다: {out} — 환자 사진은 리포에 두지 않는다.")

    fid = folder_id(folder)
    top = list_folder(fid)
    if not top:
        sys.exit("폴더 목록이 비었다 — 링크 공유('링크가 있는 모든 사용자')가 아니거나 id 가 틀렸다.")
    csv_entry = next((e for e in top if e[1] == "index.csv"), None)
    if not csv_entry:
        sys.exit("폴더에 index.csv 가 없다 — 티모의 정리 폴더가 아니다.")
    rows = list(csv.DictReader(io.StringIO(download(csv_entry[0]).decode("utf-8-sig"))))
    print(f"index.csv {len(rows)}줄 · 상품 폴더 {sum(1 for e in top if e[2])}개")

    # 폴더 안 파일 id — 이름으로 잇는다
    files_by_name = {}
    for eid, name, is_dir in top:
        if not is_dir:
            continue
        for fid2, fname, sub in list_folder(eid):
            if not sub:
                files_by_name[fname] = (fid2, name)
    print(f"사진 파일 {len(files_by_name)}개")

    plan, missing, orphan = [], [], []
    for r in rows:
        for side_key, side in (("파일(전)", "전"), ("파일(후)", "후")):
            fname = (r.get(side_key) or "").strip()
            if not fname:
                continue
            hit = files_by_name.pop(fname, None)
            if not hit:
                missing.append({"no": r["번호"], "file": fname})
                continue
            plan.append({"id": hit[0], "product": hit[1], "file": f"{hit[1]}/{fname}", "no": r["번호"], "side": side})
    orphan = sorted(files_by_name)                                  # csv 에 없는 파일

    by_product = {}
    for p in plan:
        by_product[p["product"]] = by_product.get(p["product"], 0) + 1
    cases = {p["no"] for p in plan}
    print(f"\n받을 것: {len(plan)}장 · 케이스 {len(cases)}건 · csv 에 있는데 파일 없음 {len(missing)} · 파일만 있고 csv 에 없음 {len(orphan)}")
    for k in sorted(by_product):
        print(f"  {k}: {by_product[k]}장")
    st = {}
    for r in rows:
        st[r.get("상태") or "?"] = st.get(r.get("상태") or "?", 0) + 1
    print(f"  상태: {st}")
    if a.dry:
        return

    out.mkdir(parents=True, exist_ok=True)
    todo = plan[:a.limit] if a.limit else plan
    done, fail = 0, []
    for i, p in enumerate(todo, 1):
        dst = out / p["file"]
        if dst.is_file() and dst.stat().st_size > 0:
            done += 1; continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            dst.write_bytes(download(p["id"]))
            done += 1
        except Exception as e:                                       # noqa: BLE001 — 한 장 실패로 전체를 안 멈춘다
            fail.append({"file": p["file"], "err": str(e)[:120]})
        if i % 25 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)} · 실패 {len(fail)}", flush=True)
    manifest = {
        "source": SOURCE, "drive": folder, "pulled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "rows": rows,                        # index.csv 그대로 (정본)
        "files": [{k: p[k] for k in ("file", "no", "side", "product")} for p in plan],
        "missing": missing, "orphan": orphan, "failed": fail,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n받음 {done}장 · 실패 {len(fail)}장 → {out}\nmanifest.json 저장")


if __name__ == "__main__":
    main()
