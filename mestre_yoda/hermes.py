"""Hermes — o agente de raciocínio por trás do Mestre Yoda.

O Hermes não sabe o que é Telegram. Ele recebe um `AgentRequest`, conversa com
o Claude (com ferramentas, *adaptive thinking* e *prompt caching*), atualiza a
memória e devolve um `AgentResponse`. Também serve de resumidor para a memória.
"""

from __future__ import annotations

import logging

from .config import WEB_SEARCH_TOOL
from .memory import ConversationMemory, ConversationContext
from .protocol import AgentRequest, AgentResponse
from .tools import build_registry

logger = logging.getLogger(__name__)

# Erro tratado, na voz do Yoda — nunca vaza traceback para o usuário.
_FALLBACK = (
    "Hmm. Nublado pela Força, meu pensamento está agora. "
    "Tente de novo em um instante, você deve."
)

_SUMMARY_SYSTEM = (
    "Você condensa trechos de conversa em um resumo curto e fiel, em português. "
    "Preserve fatos, decisões, nomes e o estado atual do assunto. "
    "Escreva em 3ª pessoa, sem floreios. Não invente nada."
)


def _context_block(ctx: ConversationContext) -> str | None:
    """Texto com a memória dinâmica (resumo + fatos) desta conversa."""
    parts: list[str] = []
    if ctx.summary:
        parts.append(f"Resumo da conversa até aqui:\n{ctx.summary}")
    if ctx.facts:
        fatos = "\n".join(f"- {k}: {v}" for k, v in ctx.facts.items())
        parts.append(f"Fatos que você já sabe sobre o usuário:\n{fatos}")
    if not parts:
        return None
    return "\n\n".join(parts)


def _text_from_content(content: list) -> str:
    chunks = [
        block.text
        for block in content
        if getattr(block, "type", None) == "text" and getattr(block, "text", "")
    ]
    return "\n".join(chunks).strip()


def _usage_dict(resp) -> dict[str, int]:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return {}
    fields = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    return {
        f: int(getattr(usage, f))
        for f in fields
        if getattr(usage, f, None) is not None
    }


class HermesAgent:
    def __init__(
        self,
        client,
        memory: ConversationMemory,
        *,
        model: str,
        system_prompt: str,
        effort: str = "high",
        max_tokens: int = 8192,
        max_tool_iterations: int = 5,
        enable_web_search: bool = True,
    ) -> None:
        self._client = client
        self._memory = memory
        self._model = model
        self._system_prompt = system_prompt
        self._effort = effort
        self._max_tokens = max_tokens
        self._max_tool_iterations = max_tool_iterations
        self._enable_web_search = enable_web_search

    # ------------------------------------------------------------------
    async def respond(self, request: AgentRequest) -> AgentResponse:
        """Processa um pedido e devolve a resposta do Yoda."""
        chat_id = request.chat_id

        self._memory.record_user(chat_id, request.user_text)
        ctx = self._memory.build_context(chat_id)
        registry = build_registry(self._memory, chat_id)

        system = [
            {
                "type": "text",
                "text": self._system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        block = _context_block(ctx)
        if block:
            system.append({"type": "text", "text": block})

        messages = [
            {"role": m.role, "content": m.content} for m in ctx.messages
        ]
        tools = registry.schemas()
        if self._enable_web_search:
            tools = [*tools, dict(WEB_SEARCH_TOOL)]

        tools_used: list[str] = []
        last_usage: dict[str, int] = {}
        final_text = ""

        try:
            for _ in range(self._max_tool_iterations):
                resp = await self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=system,
                    messages=messages,
                    tools=tools,
                    thinking={"type": "adaptive"},
                    output_config={"effort": self._effort},
                )
                last_usage = _usage_dict(resp) or last_usage
                stop = getattr(resp, "stop_reason", None)

                # Servidor pausou um loop de ferramenta server-side (ex.: web_search).
                # Reenvia para retomar de onde parou — sem mensagem extra.
                if stop == "pause_turn":
                    for blk in resp.content:
                        if getattr(blk, "type", None) == "server_tool_use":
                            tools_used.append(blk.name)
                    messages.append({"role": "assistant", "content": resp.content})
                    continue

                if stop == "tool_use":
                    messages.append({"role": "assistant", "content": resp.content})
                    results = []
                    for blk in resp.content:
                        btype = getattr(blk, "type", None)
                        if btype == "server_tool_use":
                            tools_used.append(blk.name)  # executada no servidor
                        elif btype == "tool_use":
                            tools_used.append(blk.name)
                            out = registry.execute(blk.name, blk.input)
                            results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": blk.id,
                                    "content": out,
                                }
                            )
                    if not results:
                        # Só ferramentas de servidor nesta rodada; retoma.
                        continue
                    messages.append({"role": "user", "content": results})
                    continue

                # Registra busca na web mesmo quando termina na mesma resposta.
                for blk in resp.content:
                    if getattr(blk, "type", None) == "server_tool_use":
                        tools_used.append(blk.name)

                final_text = _text_from_content(resp.content)
                break
            else:
                # Estourou o limite de iterações de ferramenta.
                logger.warning("Hermes atingiu o limite de iterações no chat %s", chat_id)
        except Exception:  # noqa: BLE001 - qualquer falha vira resposta amigável
            logger.exception("Falha do Hermes no chat %s", chat_id)
            return AgentResponse.failure(_FALLBACK)

        if not final_text:
            final_text = (
                "Em silêncio fiquei. Reformular sua pergunta, você poderia?"
            )

        self._memory.record_assistant(chat_id, final_text)
        await self._memory.maybe_summarize(chat_id)

        return AgentResponse(
            text=final_text,
            ok=True,
            tools_used=tuple(tools_used),
            usage=last_usage,
        )

    # ------------------------------------------------------------------
    async def summarize(self, text: str) -> str:
        """Resumidor injetado na memória. Chamada simples, sem ferramentas."""
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=_SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": text}],
            output_config={"effort": "low"},
        )
        return _text_from_content(resp.content)
