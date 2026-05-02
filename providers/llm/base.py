from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(slots=True)
class ProviderHealth:
    state: str
    detail: str


@dataclass(slots=True)
class ChatResult:
    text: str
    model: str
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    provider_name = "LLM"
    requires_network = False

    @abstractmethod
    async def healthcheck(self) -> ProviderHealth:
        raise NotImplementedError

    @abstractmethod
    async def chat(self, messages: list[ChatMessage], system_prompt: str) -> ChatResult:
        raise NotImplementedError

    async def warm_start(self) -> ProviderHealth:
        return await self.healthcheck()

    async def close(self) -> None:
        return None
