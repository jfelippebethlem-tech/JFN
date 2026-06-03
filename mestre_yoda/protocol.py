"""Contrato entre a camada de persona (Yoda/Telegram) e o agente (Hermes).

Reavaliar protocolos significa tornar explícita a fronteira entre as camadas.
O Telegram fala com o Hermes *somente* por estes objetos — nunca passando
detalhes da plataforma (objetos de update, etc.) para dentro do agente, nem
deixando o agente saber o que é "Telegram".
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentRequest:
    """Pedido enviado ao Hermes.

    Atributos:
        chat_id: identificador estável da conversa (chave de memória).
        user_text: a mensagem do usuário, já em texto puro.
        user_name: nome de exibição do usuário, se conhecido.
        metadata: campos extras e opcionais para futuros canais.
    """

    chat_id: int
    user_text: str
    user_name: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.chat_id, int):
            raise TypeError("chat_id deve ser int")
        if not self.user_text or not self.user_text.strip():
            raise ValueError("user_text não pode ser vazio")


@dataclass(frozen=True)
class AgentResponse:
    """Resposta produzida pelo Hermes.

    Atributos:
        text: o que mostrar ao usuário.
        ok: False quando houve falha tratada (o texto vira mensagem amigável).
        thinking: resumo do raciocínio, quando disponível (uso interno/log).
        tools_used: nomes das ferramentas chamadas nesta rodada.
        usage: contadores de tokens, para observabilidade.
    """

    text: str
    ok: bool = True
    thinking: str | None = None
    tools_used: tuple[str, ...] = ()
    usage: dict[str, int] = field(default_factory=dict)

    @classmethod
    def failure(cls, text: str) -> "AgentResponse":
        """Resposta de falha já formatada para o usuário."""
        return cls(text=text, ok=False)
