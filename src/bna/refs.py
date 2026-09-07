"""참조 이미지 라이브러리 (A1). samples_index.yaml 태그로 모드·조명·화소가 맞는 참조를 고른다."""
from pathlib import Path
from .spec import load, ROOT

REF_DIR = ROOT / "samples" / "reference"


def pick(mode: str, variation: dict, k: int = 2) -> list:
    refs = [r for r in load("samples_index.yaml").get("refs", []) if r.get("mode") == mode]
    want = {a: variation[a]["key"] for a in ("lighting", "quality", "background") if a in variation}
    scored = sorted(refs, key=lambda r: -sum(r.get("tags", {}).get(a) == v for a, v in want.items()))
    return [(REF_DIR / r["file"]).read_bytes() for r in scored[:k] if (REF_DIR / r["file"]).exists()]
