"""프롬프트 버전 (A6): git 커밋 + config 해시. 모든 item 메타에 기록."""
import hashlib, subprocess
from .spec import CFG, ROOT


def prompt_version() -> str:
    h = hashlib.sha1()
    for p in sorted(CFG.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(CFG).as_posix().encode()); h.update(p.read_bytes())
    try:
        git = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        git = "nogit"
    return f"{git}-{h.hexdigest()[:8]}"
