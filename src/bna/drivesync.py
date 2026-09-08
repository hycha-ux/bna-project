"""검수 → 드라이브 즉시 반영 (2026-09-08 성연서님 지시).

  채택 누름 → 그 사진 한 장만 드라이브 `채택본/` 으로 올린다.
  제외/판정 지움 → `채택본/` 에 있던 사본을 `_제외됨/` 으로 내린다(지우지 않는다).

왜 한 장만 쓰냐: 전량 스캔은 매일 23:00 예약 회차가 한다. 검수는 사람이 연달아 누르는
동작이라 회차마다 전량을 훑으면 화면이 굳는다. `--item <배치>/<아이템>` 이 그 한 장만 본다.

⚠ 이 훅은 **화면을 막지 않는다**(백그라운드 스레드). 드라이브가 느리거나 키가 아직 없어도
   검수는 그대로 저장된다 — 다음 정기 회차가 밀린 것을 이어받는다(fail-open).
"""
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops" / "drive-backup.mjs"
MANIFEST = ROOT / "ops" / ".drive-manifest.json"
LOG = ROOT / "outputs" / "drive-backup.log"
LANE_PICKED = "채택본/"

_lock = threading.Lock()
_off_logged = False


def _log(line: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 검수훅 {line}\n")
    except Exception:                                   # noqa: BLE001
        pass                                            # 로그 실패로 검수를 막지 않는다


def enabled() -> tuple[bool, str]:
    if os.environ.get("BNA_DRIVE_HOOK", "1").lower() in ("0", "off", "false", "no"):
        return False, "BNA_DRIVE_HOOK 로 꺼 둠"
    if not SCRIPT.exists():
        return False, f"{SCRIPT.name} 없음"
    if not shutil.which("node"):
        return False, "node 없음"
    return True, ""


def state_of(batch: str, item: str) -> str:
    """이 사진이 지금 드라이브 채택본에 있는가. 'uploaded' | 'pending'.

    원장은 `ops/.drive-manifest.json` 하나다 — 화면이 짐작하지 않게 실제로 올라간 것만 uploaded 다.
    """
    key = f"{batch}/{item}"
    try:
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:                                   # noqa: BLE001
        return "pending"
    for dest, m in man.items():
        if dest.startswith(LANE_PICKED) and m.get("key") == key and m.get("id"):
            return "uploaded"
    return "pending"


def _run(key: str) -> None:
    try:
        p = subprocess.run(
            [shutil.which("node") or "node", str(SCRIPT), "--item", key],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,   # CP949 로 읽으면 한글 요약에서 터진다(09-08 교훈)
        )
        tail = (p.stdout or p.stderr or "").strip().splitlines()
        _log(f"{key} → {'ok' if p.returncode == 0 else f'exit {p.returncode}'} · {tail[-1] if tail else '(출력 없음)'}")
    except subprocess.TimeoutExpired:
        _log(f"{key} → 3분 넘어 중단(23:00 정기 회차가 이어받는다)")
    except Exception as e:                              # noqa: BLE001
        _log(f"{key} → 실패 {e!r} (23:00 정기 회차가 이어받는다)")


def nudge(batch: str, item: str) -> bool:
    """이 사진의 드라이브 상태를 판정과 맞춰라. 즉시 반환한다(검수를 막지 않는다)."""
    global _off_logged
    on, why = enabled()
    if not on:
        with _lock:
            if not _off_logged:
                _off_logged = True
                _log(f"꺼짐 — {why}. 23:00 정기 회차만 돈다")
        return False
    threading.Thread(target=_run, args=(f"{batch}/{item}",), daemon=True).start()
    return True
