from __future__ import annotations

from typing import Any

from ..config import SecretStore, credential_scope
from .base import AIProvider
from .mock import MockProvider
from .openai_compatible import OpenAICompatibleProvider


DEFAULT_ENDPOINTS = {
    "smilyai": "https://apismilyai.pythonanywhere.com/v1",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://127.0.0.1:11434/v1",
    "llama.cpp": "http://127.0.0.1:8080/v1",
}


def create_provider(config: dict[str, Any], secrets: SecretStore) -> AIProvider:
    provider = config.get("provider", {})
    kind = str(provider.get("kind", "mock"))
    if kind == "mock":
        return MockProvider()
    endpoint = str(provider.get("endpoint") or DEFAULT_ENDPOINTS.get(kind, ""))
    if not endpoint:
        raise ValueError("This provider needs an API endpoint")
    return OpenAICompatibleProvider(
        endpoint=endpoint,
        model=str(provider.get("model") or ""),
        api_key=secrets.get(credential_scope({**provider, "endpoint": endpoint})),
        label=kind,
        streaming=provider.get("streaming", True),
    )
