"""Cliente Claude falso para testes — nenhuma chamada de rede."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeToolUseBlock:
    name: str
    input: dict
    id: str = "toolu_1"
    type: str = "tool_use"


@dataclass
class FakeThinkingBlock:
    thinking: str
    type: str = "thinking"


@dataclass
class FakeServerToolUseBlock:
    name: str = "web_search"
    id: str = "srvtoolu_1"
    input: dict = field(default_factory=dict)
    type: str = "server_tool_use"


@dataclass
class FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 5
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None


@dataclass
class FakeResponse:
    content: list
    stop_reason: str = "end_turn"
    usage: FakeUsage = field(default_factory=FakeUsage)


class FakeMessages:
    def __init__(self, owner: "FakeAnthropic") -> None:
        self._owner = owner

    async def create(self, **kwargs):
        self._owner.calls.append(kwargs)
        if not self._owner.scripted:
            return FakeResponse(content=[FakeTextBlock("...")])
        return self._owner.scripted.pop(0)


class FakeAnthropic:
    """Devolve respostas pré-roteadas, na ordem. Registra cada chamada."""

    def __init__(self, scripted: list[FakeResponse] | None = None) -> None:
        self.scripted = list(scripted or [])
        self.calls: list[dict] = []
        self.messages = FakeMessages(self)
