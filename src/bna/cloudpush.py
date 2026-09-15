"""생성이 끝나는 *순간* 클라우드로 밀어 올리는 훅 (2026-09-08 성연서님 "최대한 즉각적으로").

왜 필요한가: 화면(Vercel)은 인터넷에 있고 사진·원장은 이 PC 안에 있다. 밖에서 이 PC로 들어올
길이 없으니 이쪽에서 내보내는 수밖에 없고, 종전엔 그 내보내기가 10분 주기 예약작업 하나뿐이라
"방금 뽑은 사진이 남의 화면에 뜨기까지" 최대 10분이 비었다. 이 모듈은 그 공백을 없앤다 —
사진 한 장이 판정될 때마다 `cloud/push-cloud.mjs` 를 한 번 깨운다.

예약작업(10분)은 *지우지 않는다*. 이 훅은 파이썬이 살아 있을 때만 돌므로, 세션이 죽은 뒤의
누락분·수동 편집(선택/제외)은 여전히 주기 회차가 데려간다. 즉 훅=속도, 주기=안전망이다.

설계 원칙 셋:
 1) **생성을 절대 막지 않는다** — 자식 프로세스로 던지고 기다리지 않으며, 실패는 로그로만 남긴다
    (fail-open). 업로드가 안 된 건 다음 회차가 고치지만, 생성이 멈추면 돈과 시간이 날아간다.
 2) **겹쳐 돌리지 않는다** — 한 번에 하나만. 도는 동안 들어온 요청은 '한 번 더'로 접어 두었다가
    끝난 뒤 1회만 실행한다(leading + trailing). 10장을 뽑아도 업로드는 몇 회로 접힌다.
 3) **끌 수 있다** — `BNA_AUTO_PUSH=0` 이면 통째로 멈춘다. 토큰(`cloud/.env.local`)이 없거나
    node 가 없으면 스스로 조용히 꺼진다(이 PC 밖에서 파이프라인을 돌릴 때 시끄럽지 않게).

호출 자리는 넷이고 전부 '완료 지점'이다 — `progress.Progress.set`(사진 1장 판정)·
`queue.Queue._loop`(배치 1건 종료)·`api.save_review`(사람이 검수 판정)·`/api/lessons/promote`
(규칙 승격). 다른 데서 부르지 마라: 중간 단계마다 부르면 같은 스냅샷을 반복해 올리기만 한다.
검수 둘은 2026-09-10 추가 — 생성 완료에만 걸려 있던 탓에 *사람이 실제로 기다리는* 검수→학습 반영이
주기 회차(최대 10분)에만 얹혀 있었다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]        # …/bna-project
SCRIPT = ROOT / "cloud" / "push-cloud.mjs"
ENVFILE = ROOT / "cloud" / ".env.local"           # BLOB_READ_WRITE_TOKEN 이 여기 있다(gitignore)
LOG = ROOT / "outputs" / "push.log"
MIN_INTERVAL = float(os.environ.get("BNA_PUSH_MIN_INTERVAL", "15"))  # 초 — 이보다 촘촘히는 안 올린다

_lock = threading.Lock()
_running = False        # 지금 자식 프로세스가 도는가
_pending = False        # 도는 동안 새 요청이 들어왔는가
_last = 0.0             # 마지막 실행 시작 시각
_off_logged = False


def _log(line: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {line}\n")
    except Exception:                                   # noqa: BLE001 — 로그 실패로 생성을 막지 않는다
        pass


def enabled() -> tuple[bool, str]:
    """(켜졌는가, 이유). 이유는 꺼진 경우에만 의미가 있다."""
    if os.environ.get("BNA_AUTO_PUSH", "1").lower() in ("0", "off", "false", "no"):
        return False, "BNA_AUTO_PUSH 로 꺼 둠"
    if not SCRIPT.exists():
        return False, f"{SCRIPT.name} 없음"
    if not ENVFILE.exists():
        return False, "cloud/.env.local(업로드 토큰) 없음"
    if not shutil.which("node"):
        return False, "node 없음"
    return True, ""


def _node() -> str:
    return shutil.which("node") or "node"


def _run_once(reason: str) -> None:
    started = time.time()
    try:
        p = subprocess.run(
            [_node(), str(SCRIPT)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            # ⚠ Windows 기본 인코딩(CP949)으로 읽으면 node 가 뱉는 한글 요약에서 터진다.
            #   결과 요약을 잃는 정도가 아니라 예외로 새어 '실패'로 둔갑했다(09-08 실측).
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        tail = (p.stdout or p.stderr or "").strip().splitlines()
        msg = tail[-1] if tail else "(출력 없음)"
        _log(f"{reason} → {'ok' if p.returncode == 0 else f'exit {p.returncode}'} · {round(time.time()-started,1)}s · {msg}")
    except subprocess.TimeoutExpired:
        _log(f"{reason} → 10분 넘어 중단(주기 회차가 이어받는다)")
    except Exception as e:                              # noqa: BLE001
        _log(f"{reason} → 실패 {e!r} (주기 회차가 이어받는다)")


def _worker(reason: str) -> None:
    global _running, _pending, _last
    while True:
        # 너무 촘촘하면 잠깐 쉬었다 간다 — 사진 10장이 연달아 끝나도 업로드는 몇 회로 접힌다
        wait = MIN_INTERVAL - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        with _lock:
            _last = time.time()
        _run_once(reason)
        with _lock:
            if not _pending:
                _running = False
                return
            _pending = False
            reason = "밀린 요청"


def nudge(reason: str = "생성 완료") -> bool:
    """지금 올려라. 즉시 반환한다(생성 흐름을 막지 않는다). 실제로 던졌으면 True."""
    global _running, _pending, _off_logged
    on, why = enabled()
    if not on:
        if not _off_logged:
            _off_logged = True
            _log(f"자동 업로드 꺼짐 — {why}. 10분 주기 예약작업만 돈다")
        return False
    with _lock:
        if _running:
            _pending = True                             # 도는 중이면 '한 번 더'로 접어 둔다
            return False
        _running = True
    threading.Thread(target=_worker, args=(reason,), daemon=True).start()
    return True


# ── 진행 기록만 따로 (2026-09-15 티모, 빌디 제안 5번 · 성연서님 "진행해볼까?") ─────────────
# 위 nudge 는 '완료 지점'에만 8~20초짜리 전체 올리기를 한다. 그래서 한 장이 그려지는 몇 분 동안
# 클라우드 화면이 멈춰 보여 "멈춤 vs 그리는 중"을 못 가렸다(09-15 재부팅 1시간 무응답이 화면에 안 보임).
# 이쪽은 **progress 요약 한 파일**만 PUT 1건으로 올린다 — 단계가 바뀔 때 PROG_MIN_INTERVAL 간격,
# 변화가 없어도 Progress 가 HEARTBEAT_S 마다 부른다. 화면은 cloud/lib/liveprog.mjs 가 더 새 쪽을 고른다.
# 원칙은 위와 같다 — 막지 않고(fire-and-forget), 겹치지 않고(배치별 leading+trailing), 같은 스위치로 꺼진다.
PROG_SCRIPT = ROOT / "cloud" / "push-progress.mjs"
PROG_MIN_INTERVAL = float(os.environ.get("BNA_PROGRESS_MIN_INTERVAL", "30"))
HEARTBEAT_S = 60          # cloud/lib/liveprog.mjs 의 HEARTBEAT_S 와 한 쌍 (화면의 멈춤 판정 = 5번 놓침)
_plock = threading.Lock()
_pstate: dict = {}        # 배치 폴더 → {"running", "pending", "last"}


def _progress_payload(batch_dir: Path):
    """로컬 API 와 같은 요약(progress.read) + pushed_at 을 파일로 쓴다. 산식은 progress.py 가 정본."""
    from . import progress as prog                   # 순환 import 회피(progress 가 이 모듈을 먼저 부른다)
    d = prog.read(batch_dir)
    if d is None:
        return None
    d["pushed_at"] = round(time.time(), 3)
    out = batch_dir / "progress.push.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(__import__("json").dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out)
    return out


def _run_progress_once(batch_dir: Path) -> None:
    try:
        f = _progress_payload(batch_dir)
        if f is None:
            return
        p = subprocess.run([_node(), str(PROG_SCRIPT), str(f), batch_dir.name], cwd=str(ROOT),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        # 성공은 적지 않는다 — 배치 하나에 수십 번이라 push.log 가 이것으로 덮인다. 실패만 남긴다.
        if p.returncode != 0:
            tail = (p.stderr or p.stdout or "").strip().splitlines()
            _log(f"진행 올리기 {batch_dir.name} → exit {p.returncode} · {tail[-1] if tail else '(출력 없음)'}")
    except Exception as e:                              # noqa: BLE001
        _log(f"진행 올리기 {batch_dir.name} → 실패 {e!r}")


def _progress_worker(key: str, batch_dir: Path) -> None:
    while True:
        with _plock:
            wait = PROG_MIN_INTERVAL - (time.time() - _pstate[key]["last"])
        if wait > 0:
            time.sleep(wait)
        with _plock:
            _pstate[key]["last"] = time.time()
            _pstate[key]["pending"] = False
        _run_progress_once(batch_dir)
        with _plock:
            if not _pstate[key]["pending"]:
                _pstate[key]["running"] = False
                return


def nudge_progress(batch_dir) -> bool:
    """이 배치의 진행 요약을 올려라. 즉시 반환. 실제로 작업자를 띄웠으면 True(도는 중이면 '한 번 더'로 접고 False)."""
    on, _why = enabled()
    if not on or not PROG_SCRIPT.exists():
        return False
    batch_dir = Path(batch_dir)
    key = str(batch_dir)
    with _plock:
        st = _pstate.setdefault(key, {"running": False, "pending": False, "last": 0.0})
        if st["running"]:
            st["pending"] = True
            return False
        st["running"] = True
    threading.Thread(target=_progress_worker, args=(key, batch_dir), daemon=True).start()
    return True
