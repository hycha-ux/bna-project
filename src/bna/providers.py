"""이미지 생성/편집/검수 프로바이더. 키 수령 후 구현 채움."""
import os


class NotConfigured(RuntimeError):
    pass


def generate_before(prompt: str, provider: str = "gemini") -> bytes:
    key = os.getenv({"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "higgsfield": "HIGGSFIELD_API_KEY"}[provider])
    if not key:
        raise NotConfigured(f"{provider} key missing in .env")
    raise NotImplementedError("TODO: 키 수령 후 구현")


def edit_after(before_image: bytes, prompt: str, provider: str = "gemini") -> bytes:
    raise NotImplementedError("TODO: 키 수령 후 구현")


def qa_score(before_image: bytes, after_image: bytes, checklist: dict, provider: str = "gemini") -> dict:
    raise NotImplementedError("TODO: 키 수령 후 구현")
