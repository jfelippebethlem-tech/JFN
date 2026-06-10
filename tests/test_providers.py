"""Testes do adaptador OpenAI-compatible (sem rede)."""

from __future__ import annotations

import json

import pytest

from mestre_yoda.providers import (
    OpenAICompatClient,
    ProviderConnectionError,
    ProviderError,
    _build_response,
    _to_openai_messages,
    _to_openai_tools,
)


# --- conversão de mensagens ---------------------------------------------
def test_system_lista_vira_string():
    system = [
        {"type": "text", "text": "Você é Yoda.", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "Fatos: nome=Jorge"},
    ]
    msgs = _to_openai_messages(system, [{"role": "user", "content": "oi"}])
    assert msgs[0]["role"] == "system"
    assert "Yoda" in msgs[0]["content"] and "Jorge" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "oi"}


def test_assistant_com_tool_use_vira_tool_calls():
    from mestre_yoda.providers import _ToolUseBlock

    messages = [
        {"role": "user", "content": "que horas são?"},
        {
            "role": "assistant",
            "content": [_ToolUseBlock(id="abc", name="get_current_time", input={})],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "abc", "content": "12:00"}
            ],
        },
    ]
    out = _to_openai_messages(None, messages)
    assistant = out[1]
    assert assistant["tool_calls"][0]["function"]["name"] == "get_current_time"
    assert assistant["tool_calls"][0]["id"] == "abc"
    tool_msg = out[2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "abc"
    assert tool_msg["content"] == "12:00"


def test_tools_descartam_server_tools():
    tools = [
        {
            "name": "get_market_data",
            "description": "cotações",
            "input_schema": {"type": "object", "properties": {}},
        },
        {"type": "web_search_20260209", "name": "web_search"},  # server-side
    ]
    converted = _to_openai_tools(tools)
    assert len(converted) == 1
    assert converted[0]["type"] == "function"
    assert converted[0]["function"]["name"] == "get_market_data"


# --- construção de resposta ---------------------------------------------
def test_build_response_texto():
    data = {
        "choices": [
            {"message": {"content": "Olá, padawan."}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7},
    }
    resp = _build_response(data)
    assert resp.stop_reason == "end_turn"
    assert resp.content[0].text == "Olá, padawan."
    assert resp.usage.input_tokens == 12
    assert resp.usage.output_tokens == 7


def test_build_response_tool_use():
    data = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "get_market_data",
                                "arguments": "{}",
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }
    resp = _build_response(data)
    assert resp.stop_reason == "tool_use"
    block = resp.content[0]
    assert block.type == "tool_use"
    assert block.name == "get_market_data"
    assert block.input == {}


def test_build_response_argumentos_invalidos_nao_quebram():
    data = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {"id": "x", "function": {"name": "f", "arguments": "NAO_JSON"}}
                    ]
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    resp = _build_response(data)
    assert resp.content[0].input == {}


# --- cliente: tradução de erros HTTP ------------------------------------
class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.posted = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json, headers):
        self.posted = {"url": url, "json": json, "headers": headers}
        if self._exc is not None:
            raise self._exc
        return self._response


@pytest.mark.asyncio
async def test_client_sucesso(monkeypatch):
    payload = {
        "choices": [{"message": {"content": "pronto"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }
    fake = _FakeAsyncClient(response=_FakeResponse(200, payload))
    monkeypatch.setattr(
        "mestre_yoda.providers.httpx.AsyncClient", lambda *a, **k: fake
    )
    client = OpenAICompatClient(base_url="http://x/v1", api_key="k")
    resp = await client.messages.create(
        model="m", messages=[{"role": "user", "content": "oi"}], max_tokens=50
    )
    assert resp.content[0].text == "pronto"
    assert fake.posted["url"] == "http://x/v1/chat/completions"
    assert fake.posted["headers"]["Authorization"] == "Bearer k"


@pytest.mark.asyncio
async def test_client_erro_http_carrega_status(monkeypatch):
    fake = _FakeAsyncClient(response=_FakeResponse(429, text="rate limit"))
    monkeypatch.setattr(
        "mestre_yoda.providers.httpx.AsyncClient", lambda *a, **k: fake
    )
    client = OpenAICompatClient(base_url="http://x/v1", api_key="k")
    with pytest.raises(ProviderError) as exc:
        await client.messages.create(
            model="m", messages=[{"role": "user", "content": "oi"}]
        )
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_client_timeout_vira_connection_error(monkeypatch):
    import httpx

    fake = _FakeAsyncClient(exc=httpx.ConnectTimeout("estourou"))
    monkeypatch.setattr(
        "mestre_yoda.providers.httpx.AsyncClient", lambda *a, **k: fake
    )
    client = OpenAICompatClient(base_url="http://x/v1", api_key="k")
    with pytest.raises(ProviderConnectionError):
        await client.messages.create(
            model="m", messages=[{"role": "user", "content": "oi"}]
        )


def test_connection_error_e_retryable():
    """O retry do hermes deve reconhecer ProviderConnectionError."""
    from mestre_yoda.hermes import _is_retryable

    assert _is_retryable(ProviderConnectionError("x")) is True
    assert _is_retryable(ProviderError("x", status_code=503)) is True
    assert _is_retryable(ProviderError("x", status_code=400)) is False
