"""Higgsfield 리얼 인물 생성. TODO: 키 수령 후 API 스펙 확인 후 구현."""
from .base import Provider


class HiggsfieldProvider(Provider):
    name, env_key, concurrency = "higgsfield", "HIGGSFIELD_API_KEY", 2
    supports_mask, supports_ref, supports_style_refs = False, True, False

    def adapt_prompt(self, prompt, kind):
        return prompt  # TODO: 키워드형 선호 시 변환

    def generate(self, prompt, aspect, ref=None, style_refs=None, seed=None):
        raise NotImplementedError("TODO")

    def edit(self, image, prompt, mask=None):
        raise NotImplementedError("Higgsfield 편집 미지원 가정 → 다른 프로바이더로 라우팅")

    def qa(self, before, after, items, mode):
        raise NotImplementedError("채점 미지원 → gemini/openai 사용")
