"""중복 검사 (B5 포함): 얼굴 임베딩 레지스트리. 배치 내 + 과거 배치와 비교."""
import json
import numpy as np
from pathlib import Path
from .identity import embed

REGISTRY = Path(__file__).resolve().parents[3] / "outputs" / "face_registry.jsonl"
SIM_DUP = 0.75   # 이 이상이면 "너무 닮은 인물"로 간주


class Registry:
    def __init__(self, path: Path = REGISTRY):
        self.path = path
        self.items = []
        if path.exists():
            for line in path.read_text().splitlines():
                d = json.loads(line); self.items.append((d["item_id"], np.array(d["emb"])))

    def nearest(self, emb):
        if not self.items or emb is None:
            return None, 0.0
        sims = [(i, float(np.dot(emb, e))) for i, e in self.items]
        return max(sims, key=lambda x: x[1])

    def add(self, item_id: str, emb):
        if emb is None:
            return
        self.items.append((item_id, emb))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps({"item_id": item_id, "emb": emb.tolist()}) + "\n")


def check(img, item_id: str, registry: Registry) -> dict:
    e = embed(img)
    near_id, sim = registry.nearest(e)
    dup = sim >= SIM_DUP
    if not dup:
        registry.add(item_id, e)
    return {"duplicate_of": near_id if dup else None, "similarity": sim, "passed": not dup}
