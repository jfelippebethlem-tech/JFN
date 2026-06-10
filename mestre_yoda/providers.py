"""Provedores de modelo do Mestre Yoda.

O `hermes.py` foi escrito para a API da Anthropic (blocos de conteúdo,
`stop_reason`, ferramentas com `input_schema`). Para usar provedores gratuitos
que falam o dialeto OpenAI (OpenRouter, Nous, Ollama, etc.) sem reescrever o
agente, este módulo expõe um **adaptador**: um cliente com a mesma interface
`client.messages.create(...)` que o `hermes.py` espera, traduzindo requisição e
resposta de/para o formato OpenAI `chat/completions` nos bastidores.

Assim o agente continua agnóstico: troca-se só o transporte.

Limitações dos provedores OpenAI-compatible (vs. Anthropic):
- Sem busca na web server-side (`web_search`) — o `__main__` desliga isso.
- Sem blocos de *thinking* nem *prompt caching* — ignorados silenciosamente.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


# --- exceções (classificáveis pelo retry do hermes) ----------------------
class ProviderError(RuntimeError):
    """Falha de um provedor OpenAI-compatible. Carrega `status_code` se houver."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProviderConnectionError(ProviderError):
    """Falha de rede (timeout/conexão). O nome casa com o retry do hermes."""


# --- blocos de resposta (imitam os objetos da Anthropic) -----------------
@dataclass
class _TextBlock:
    text: str
    type: str = "text"


@dataclass
class _ToolUseBlock:
    name: str
    input: dict
    id: str = ""
    type: str = "tool_use"


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None


@dataclass
class _Response:
    content: list
    stop_reason: str = "end_turn"
    usage: _Usage = field(default_factory=_Usage)


# --- conversão de tipos --------------------------------------------------
def _block_type(block) -> str | None:
    if isinstance(block, dict):
        return block.get("type")
    return getattr(block, "type", None)


def _block_get(block, key, default=None):
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _stringify(content) -> str:
    """Conteúdo de tool_result pode ser str ou lista de blocos; vira texto."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            else:
                parts.append(str(b))
        return "\n".join(parts)
    return str(content)


def _system_text(system) -> str:
    """A Anthropic aceita system como lista de blocos; OpenAI quer uma string."""
    if system is None:
        return ""
    if isinstance(system, str):
        return system
    parts = [
        _block_get(b, "text", "")
        for b in system
        if _block_type(b) == "text" or isinstance(b, dict)
    ]
    return "\n\n".join(p for p in parts if p)


def _to_openai_messages(system, messages: list) -> list[dict]:
    """Traduz system + mensagens estilo Anthropic para o formato OpenAI."""
    out: list[dict] = []
    sys_text = _system_text(system)
    if sys_text:
        out.append({"role": "system", "content": sys_text})

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            for block in content:
                btype = _block_type(block)
                if btype == "text":
                    text_parts.append(_block_get(block, "text", "") or "")
                elif btype == "tool_use":
                    tool_calls.append(
                        {
                            "id": _block_get(block, "id") or _gen_id(),
                            "type": "function",
                            "function": {
                                "name": _block_get(block, "name"),
                                "arguments": json.dumps(
                                    _block_get(block, "input") or {}
                                ),
                            },
                        }
                    )
            out_msg: dict = {
                "role": "assistant",
                "content": "\n".join(p for p in text_parts if p) or None,
            }
            if tool_calls:
                out_msg["tool_calls"] = tool_calls
            out.append(out_msg)
            continue

        # role == "user": blocos de tool_result viram mensagens role="tool";
        # blocos de texto viram uma mensagem de usuário.
        pending_text: list[str] = []
        for block in content:
            btype = _block_type(block)
            if btype == "tool_result":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": _block_get(block, "tool_use_id"),
                        "content": _stringify(_block_get(block, "content", "")),
                    }
                )
            elif btype == "text":
                pending_text.append(_block_get(block, "text", "") or "")
        if pending_text:
            out.append(
                {"role": "user", "content": "\n".join(p for p in pending_text if p)}
            )

    return out


def _to_openai_tools(tools) -> list[dict]:
    """Converte ferramentas Anthropic em ferramentas OpenAI (function calling).

    Ferramentas server-side (ex.: web_search, que têm `type` e não
    `input_schema`) são descartadas — provedores compat não as executam.
    """
    if not tools:
        return []
    converted: list[dict] = []
    for tool in tools:
        schema = tool.get("input_schema") if isinstance(tool, dict) else None
        name = tool.get("name") if isinstance(tool, dict) else None
        if not schema or not name:
            continue  # ferramenta de servidor — ignora
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.get("description", ""),
                    "parameters": schema,
                },
            }
        )
    return converted


def _gen_id() -> str:
    return "call_" + uuid.uuid4().hex[:16]


def _build_response(data: dict) -> _Response:
    """Monta um objeto estilo-Anthropic a partir do JSON OpenAI."""
    choices = data.get("choices") or [{}]
    choice = choices[0]
    message = choice.get("message") or {}
    finish = choice.get("finish_reason")

    blocks: list = []
    text = message.get("content")
    if text:
        blocks.append(_TextBlock(text=text))

    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        raw_args = fn.get("arguments") or "{}"
        try:
            parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except (json.JSONDecodeError, TypeError):
            parsed = {}
        blocks.append(
            _ToolUseBlock(
                id=call.get("id") or _gen_id(),
                name=fn.get("name"),
                input=parsed or {},
            )
        )

    has_tool = any(_block_type(b) == "tool_use" for b in blocks)
    stop_reason = "tool_use" if (finish == "tool_calls" or has_tool) else "end_turn"

    u = data.get("usage") or {}
    usage = _Usage(
        input_tokens=int(u.get("prompt_tokens", 0) or 0),
        output_tokens=int(u.get("completion_tokens", 0) or 0),
    )
    return _Response(content=blocks, stop_reason=stop_reason, usage=usage)


# --- cliente adaptador ---------------------------------------------------
class _MessagesEndpoint:
    """Imita `client.messages` da Anthropic."""

    def __init__(self, client: "OpenAICompatClient") -> None:
        self._client = client

    async def create(self, **kwargs):
        return await self._client._create(**kwargs)


class OpenAICompatClient:
    """Cliente para qualquer endpoint OpenAI-compatible (OpenRouter, Nous...).

    Expõe `.messages.create(...)` com a mesma assinatura usada pelo Hermes,
    para entrar no lugar do `AsyncAnthropic` sem mudar o agente.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        extra_headers: dict | None = None,
        timeout: float = 120.0,
        temperature: float = 0.4,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            self._headers.update(extra_headers)
        self._timeout = timeout
        self._temperature = temperature
        self.messages = _MessagesEndpoint(self)

    async def _create(
        self,
        *,
        model: str,
        messages: list,
        system=None,
        tools=None,
        max_tokens: int = 4096,
        **_ignored,  # thinking, output_config, cache_control — não suportados
    ):
        payload: dict = {
            "model": model,
            "messages": _to_openai_messages(system, messages),
            "max_tokens": max_tokens,
            "temperature": self._temperature,
        }
        oai_tools = _to_openai_tools(tools)
        if oai_tools:
            payload["tools"] = oai_tools

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=self._headers,
                )
        except httpx.TimeoutException as exc:
            raise ProviderConnectionError(f"Timeout do provedor: {exc}") from exc
        except httpx.TransportError as exc:
            raise ProviderConnectionError(f"Falha de conexão: {exc}") from exc

        if resp.status_code >= 400:
            raise ProviderError(
                f"Provedor retornou {resp.status_code}: {resp.text[:300]}",
                status_code=resp.status_code,
            )

        return _build_response(resp.json())


def build_client(settings):
    """Devolve o cliente certo conforme o provedor configurado."""
    if settings.provider == "anthropic":
        from anthropic import AsyncAnthropic

        return AsyncAnthropic(api_key=settings.llm_api_key)

    extra: dict[str, str] = {}
    if settings.provider == "openrouter":
        # Cabeçalhos opcionais que o OpenRouter usa para atribuição.
        extra = {
            "HTTP-Referer": "https://github.com/jfelippebethlem-tech/JFN",
            "X-Title": "Mestre Yoda",
        }
    logger.info(
        "Provedor: %s | modelo: %s | endpoint: %s",
        settings.provider,
        settings.model,
        settings.llm_base_url,
    )
    return OpenAICompatClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        extra_headers=extra,
    )
