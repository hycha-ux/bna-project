"""Gemini 이미지 생성·편집·비전 채점. TODO: 키 수령 후 구현 (google-genai SDK)."""
from .base import Provider


class GeminiProvider(Provider):
    name, env_key, concurrency = "gemini", "GEMINI_API_KEY", 4
    supports_mask, supports_ref, supports_style_refs = False, True, True

    def generate(self, prompt, aspect, ref=None, style_refs=None, seed=None):
        raise NotImplementedError("TODO: genai.Client().models.generate_content(image model, contents=[prompt, ref, *style_refs])")

    def edit(self, image, prompt, mask=None):
        raise NotImplementedError("TODO: 이미지 입력 + 편집 지시")

    def qa(self, before, after, items, mode):
        raise NotImplementedError("TODO: 두 이미지 + 체크리스트 → JSON 점수")
