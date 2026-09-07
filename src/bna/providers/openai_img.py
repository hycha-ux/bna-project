"""OpenAI 이미지 생성·마스크 편집·비전 채점. TODO: 키 수령 후 구현."""
from .base import Provider


class OpenAIProvider(Provider):
    name, env_key, concurrency = "openai", "OPENAI_API_KEY", 3
    supports_mask, supports_ref, supports_style_refs = True, True, True

    def adapt_prompt(self, prompt, kind):
        return prompt  # GPT 계열은 서술형 그대로

    def generate(self, prompt, aspect, ref=None, style_refs=None, seed=None):
        raise NotImplementedError("TODO: images.generate / images.edit(image=[ref, *style_refs])")

    def edit(self, image, prompt, mask=None):
        raise NotImplementedError("TODO: images.edit(image, mask, prompt)")

    def qa(self, before, after, items, mode):
        raise NotImplementedError("TODO: vision → JSON 점수")
