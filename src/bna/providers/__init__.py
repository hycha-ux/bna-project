from .base import Provider, NotConfigured
from .gemini import GeminiProvider
from .openai_img import OpenAIProvider
from .higgsfield import HiggsfieldProvider

REGISTRY = {"gemini": GeminiProvider, "openai": OpenAIProvider, "higgsfield": HiggsfieldProvider}


def get(name: str) -> Provider:
    return REGISTRY[name]()
