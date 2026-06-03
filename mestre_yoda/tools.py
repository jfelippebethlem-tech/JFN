"""Ferramentas do agente Hermes.

Cada ferramenta é um esquema (para o Claude) mais um executor (para o nosso
lado). O conjunto é montado por pedido, já amarrado ao `chat_id` e à memória,
de modo que o Claude nunca recebe ou manipula identificadores diretamente.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from .market import MarketDataUnavailable, fetch_quotes, format_quotes
from .memory import ConversationMemory

ToolHandler = Callable[[dict], str]

# Mensagem quando a fonte real falha: orienta a usar a web, jamais inventar.
_MARKET_UNAVAILABLE = (
    "Cotações em tempo real indisponíveis agora (fonte yfinance fora do ar). "
    "Busque os valores na web e cite a fonte; números não invente."
)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: ToolHandler

    def schema(self) -> dict:
        """Definição no formato esperado pela API do Claude."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    """Conjunto de ferramentas disponíveis em um pedido."""

    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {t.name: t for t in tools}

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def execute(self, name: str, tool_input: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Erro: ferramenta desconhecida {name!r}."
        try:
            return tool.handler(tool_input or {})
        except Exception as exc:  # noqa: BLE001 - erro vira tool_result, não derruba o loop
            return f"Erro ao executar {name}: {exc}"


def market_tool() -> Tool:
    """Ferramenta de cotações reais (dólar, Ibovespa, ouro, petróleo).

    Independente de chat ou memória, então serve tanto à conversa quanto à
    rotina diária "BOM DIA".
    """

    def _get_market_data(_: dict) -> str:
        try:
            quotes = fetch_quotes()
        except MarketDataUnavailable:
            return _MARKET_UNAVAILABLE
        return format_quotes(quotes)

    return Tool(
        name="get_market_data",
        description=(
            "Retorna cotações reais e atuais de dólar (USD/BRL), Ibovespa, "
            "ouro e petróleo WTI. Use sempre que o usuário pedir mercado ou "
            "ao montar a rotina diária. Nunca invente cotações."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_get_market_data,
    )


def build_registry(memory: ConversationMemory, chat_id: int) -> ToolRegistry:
    """Monta as ferramentas amarradas a este chat."""

    def _get_current_time(_: dict) -> str:
        agora = datetime.now(timezone.utc).astimezone()
        return agora.strftime("%A, %d/%m/%Y %H:%M:%S %Z")

    def _remember_fact(args: dict) -> str:
        key = str(args.get("key", "")).strip()
        value = str(args.get("value", "")).strip()
        if not key or not value:
            return "Erro: 'key' e 'value' são obrigatórios."
        memory.remember_fact(chat_id, key, value)
        return f"Guardado: {key} = {value}"

    def _recall_facts(_: dict) -> str:
        facts = memory.facts(chat_id)
        if not facts:
            return "Nenhum fato guardado ainda sobre este usuário."
        return "\n".join(f"- {k}: {v}" for k, v in facts.items())

    return ToolRegistry(
        [
            Tool(
                name="get_current_time",
                description=(
                    "Retorna a data e a hora atuais. Use quando o usuário "
                    "perguntar que dia/hora é, ou quando a resposta depender "
                    "do momento presente."
                ),
                input_schema={"type": "object", "properties": {}},
                handler=_get_current_time,
            ),
            Tool(
                name="remember_fact",
                description=(
                    "Guarda um fato duradouro sobre o usuário (nome, "
                    "preferência, meta, projeto). Chame sempre que aprender "
                    "algo estável que valha lembrar em conversas futuras."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Rótulo curto do fato, ex.: 'nome'.",
                        },
                        "value": {
                            "type": "string",
                            "description": "Conteúdo do fato.",
                        },
                    },
                    "required": ["key", "value"],
                },
                handler=_remember_fact,
            ),
            Tool(
                name="recall_facts",
                description=(
                    "Lista os fatos já guardados sobre o usuário. Use quando "
                    "precisar confirmar o que sabe antes de responder."
                ),
                input_schema={"type": "object", "properties": {}},
                handler=_recall_facts,
            ),
            market_tool(),
        ]
    )
