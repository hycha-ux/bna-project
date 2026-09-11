"""시리즈 배치를 오프라인 대역으로 1세트 끝까지 돌려 본다 (2026-09-11, API 0콜·$0).

왜 selftest 로 안 끝냈나: selftest 는 `spec` 이 낸 값과 `vision.score` 를 따로 확인할 뿐,
그 사이를 잇는 `batch.run_item` 의 **튜플 언패킹**은 안 탄다. 그 자리를 이번에 4칸으로 늘렸고
(when, bytes, img, ungate), 거기서 나는 오류는 첫 유료 시리즈 회차에서 터진다.

대역 = 단색 이미지 생성 + effect_visible 3점(컷 미달)·나머지 만점 채점.
기대 = 직후 컷은 effect_visible 로 안 떨어지고, 2주 컷은 떨어진다.
"""
import asyncio, io, json, os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("OPENAI_API_KEY", "stub")

from PIL import Image
from bna import providers
from bna.providers.base import Provider


def _png(color):
    b = io.BytesIO()
    Image.new("RGB", (512, 640), color).save(b, "PNG")
    return b.getvalue()


class Stub(Provider):
    name = "openai"
    supports_ref = True
    concurrency = 1

    def __init__(self):
        pass

    def generate(self, prompt, aspect, ref=None, style_refs=None, seed=None):
        return _png((200, 170, 160))

    def edit(self, image, prompt, mask=None):
        return _png((200, 170, 160))

    def qa(self, before, after, items, mode):
        return {k: {"score": 3.0 if k == "effect_visible" else 10.0, "note": "stub"} for k in items}


providers.get = lambda name: Stub()          # noqa: E731  (레지스트리 전체를 대역으로)

from bna.batch import Batch                  # providers.get 을 바꾼 뒤에 import 해야 한다
from bna.planner import plan_batch


async def main():
    b = Batch("nasolabial", "selfie", 1, seed=5, series=["immediate", "2w"])
    # ⚠ 산출물을 임시 폴더로 돌린다 — 안 그러면 이 대역 회차가 `outputs/` 에 진짜 배치로 남아
    #   통과율·프레이밍 실측의 모수에 섞인다(2026-09-11 실제로 한 번 섞였고 지웠다).
    #   배치 id 에 'sim' 이 없어서 기존 시뮬 제외 규칙에도 안 걸린다.
    #   ⚠ 생성자가 이미 `outputs/<id>` 를 만들어 둔다 — 비어 있어도 남으면 배치 목록에 뜨므로 같이 치운다.
    tmp = Path(tempfile.mkdtemp(prefix="bna_probe_"))
    made = b.dir
    b.dir = tmp
    b.state_path = tmp / "state.json"
    try:
        made.rmdir()
    except OSError:                       # 비어 있지 않으면 손대지 않는다(남의 배치일 수 있다)
        pass
    v = plan_batch("selfie", 1, 5, {}, None, treatment="nasolabial")[0]
    meta = await b.run_item(0, v)
    ar = meta["after_results"]
    out = {
        "series": meta["series"],
        "fail_reasons": meta["fail_reasons"],
        "immediate": {"ungated": ar["immediate"]["vision"]["ungated"],
                      "failed": ar["immediate"]["vision"]["failed_items"],
                      "score": ar["immediate"]["vision"]["scores"]["effect_visible"]["score"]},
        "2w": {"ungated": ar["2w"]["vision"]["ungated"],
               "failed": ar["2w"]["vision"]["failed_items"]},
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    bad = []
    if "vision:effect_visible@immediate" in meta["fail_reasons"]:
        bad.append("직후 컷이 effect_visible 로 떨어졌다 — 게이트 수정이 안 먹었다")
    if "vision:effect_visible@2w" not in meta["fail_reasons"]:
        bad.append("2주 컷은 여전히 걸려야 한다 — 전 시점이 통째로 면제됐다")
    if ar["immediate"]["vision"]["scores"]["effect_visible"]["score"] != 3.0:
        bad.append("직후 컷 점수가 안 남았다 — 안 묻는 게 아니라 안 거는 것이어야 한다")
    print("\n" + ("PASS: series gate ok" if not bad else "FAIL:\n  " + "\n  ".join(bad)))
    return 1 if bad else 0


sys.exit(asyncio.run(main()))
