"""프로바이더 공통 인터페이스 + 모델별 프롬프트 어댑터(B1) 훅."""
import os


class NotConfigured(RuntimeError):
    pass


class Provider:
    name = "base"
    env_key = ""
    concurrency = 2
    supports_mask = False        # 마스크 편집 지원 여부 (A4). 미지원이면 후단에서 composite 로 대체
    supports_ref = False         # 인물 참조 생성 지원 여부 (셀카 After)
    supports_style_refs = False  # 스타일 참조 이미지 입력 (A1)

    def __init__(self):
        self.key = os.getenv(self.env_key, "")
        if not self.key:
            raise NotConfigured(f"{self.name}: {self.env_key} not set in .env")

    # --- 프롬프트 어댑터 (B1): 공통 스펙 → 모델 방언. 기본은 그대로 ---
    def adapt_prompt(self, prompt: str, kind: str) -> str:
        return prompt

    # --- 생성/편집/채점 ---
    def generate(self, prompt: str, aspect: str, ref: bytes = None, style_refs: list = None, seed=None) -> bytes:
        raise NotImplementedError

    def edit(self, image: bytes, prompt: str, mask: bytes = None) -> bytes:
        raise NotImplementedError

    def qa(self, before: bytes, after: bytes, items: dict, mode: str) -> dict:
        """{item_key: {"score": 0-10, "note": str}}"""
        raise NotImplementedError

    def chat_json(self, prompt: str, images=(), *, purpose: str = "chat", model: str = None) -> dict:
        """텍스트(+이미지) → JSON 한 덩이. {"data": dict, "usage": dict, "model": str}

        검수 채점(qa)이 아닌 텍스트 판단용(예: 메모 → 규칙 초안). 벤더마다 응답 모양이 달라
        공통 계약을 여기 못박는다 — 미지원 벤더는 부르는 쪽이 fail-open 으로 폴백해야 한다."""
        raise NotImplementedError
