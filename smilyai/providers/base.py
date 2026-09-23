from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator


@dataclass(frozen=True)
class ModelCapabilities:
    text: bool = True
    streaming: bool = False
    tool_calling: bool = False
    vision: bool = False
    audio_input: bool = False
    audio_output: bool = False
    reasoning_controls: bool = False
    context_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str = ""


@dataclass
class ProviderResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class AIProvider(ABC):
    name = "base"

    @abstractmethod
    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ProviderResponse:
        raise NotImplementedError

    async def stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AsyncIterator[str]:
        response = await self.chat(messages, tools)
        yield response.text

    @abstractmethod
    async def models(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def capabilities(self) -> ModelCapabilities:
        raise NotImplementedError

    async def test_connection(self) -> dict[str, Any]:
        return {"ok": True, "provider": self.name, "models": await self.models()}

