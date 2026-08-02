# -*- coding: utf-8 -*-
"""Quem pede prosa tem que receber prosa — o `responseMimeType` vencia o prompt calado.

Defeito medido (31/07/2026) testando o chat do Hermes/Yoda como usuário. Duas perguntas reais,
`POST /api/hermes/chat`, ambas HTTP 200 e com o conteúdo CORRETO — mas assim na tela:

    "resposta": "{\\n  \\"resposta\\": \\"O teto de capital social … é de até 10% …\\"\\n}"
    "resposta": "\\"A diferença entre empenho e ordem bancária reside …\\""

Ou seja: a caixa de chat mostra chave, aspas escapadas e `\\n` ao auditor. O prompt da rota manda,
literalmente, *"Responda em pt-BR, texto corrido (nunca JSON)"* — e não adianta: `gerar_gemini`
fixava `generationConfig.responseMimeType = "application/json"`, e a configuração da API vence o
texto do prompt. O modelo obedecia o mime type e embrulhava a prosa.

CUIDADO QUE JUSTIFICA A FORMA DESTA CORREÇÃO. `gerar_gemini` tem 34 símbolos a montante e risco
CRITICAL no `gitnexus_impact`: quase todo consumidor de LLM da casa passa por ele — detectores,
coletores, pareceres — e a maioria PARSEIA o JSON de volta. Por isso a mudança é estritamente
ADITIVA: o padrão continua JSON, byte a byte como hoje, e só quem quer prosa pede.
"""
from __future__ import annotations

import asyncio

import pytest

import compliance_agent.direcionamento_cerebro as DC


class _RespFalsa:
    status_code = 200

    def __init__(self, corpo):
        self._corpo = corpo

    def json(self):
        return self._corpo

    def raise_for_status(self):
        return None


class _ClienteFalso:
    """Captura o body enviado ao Gemini para que o teste possa inspecioná-lo."""

    def __init__(self, capturados):
        self._cap = capturados

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, _url, json=None, **_kw):
        self._cap.append(json)
        return _RespFalsa({"candidates": [{"content": {"parts": [{"text": "resposta em prosa"}]}}]})


@pytest.fixture()
def corpos(monkeypatch):
    """Intercepta a chamada HTTP e devolve a lista de bodies enviados."""
    import httpx

    cap: list[dict] = []
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _ClienteFalso(cap))
    monkeypatch.setattr(DC, "_gemini_keys", lambda: ["chave-falsa-de-teste"])
    return cap


_MSGS = [{"role": "user", "content": "Qual o teto de capital social?"}]


def test_padrao_continua_pedindo_json(corpos):
    """Os 34 consumidores a montante parseiam JSON — o padrão não pode mudar."""
    asyncio.run(DC.gerar_gemini(_MSGS))

    assert corpos, "nenhuma chamada capturada"
    assert corpos[0]["generationConfig"]["responseMimeType"] == "application/json"


def test_prosa_nao_manda_response_mime_type(corpos):
    """Pedindo prosa, o campo some do body — não vira 'text/plain' nem fica vazio."""
    asyncio.run(DC.gerar_gemini(_MSGS, json_saida=False))

    assert "responseMimeType" not in corpos[0]["generationConfig"], (
        f"o body ainda força um mime type: {corpos[0]['generationConfig']}")


def test_prosa_nao_mexe_no_resto_do_body(corpos):
    """Guarda-costas: só o mime type muda — temperatura, teto e contents seguem iguais."""
    asyncio.run(DC.gerar_gemini(_MSGS))
    com_json = corpos[0]
    corpos.clear()
    asyncio.run(DC.gerar_gemini(_MSGS, json_saida=False))
    em_prosa = corpos[0]

    assert em_prosa["contents"] == com_json["contents"]
    assert {k: v for k, v in em_prosa["generationConfig"].items()} == {
        k: v for k, v in com_json["generationConfig"].items() if k != "responseMimeType"}


def test_gerar_sync_repassa_o_pedido_de_prosa(monkeypatch):
    """A rota de chat chama `gerar_sync`; o pedido não pode morrer no meio da cadeia."""
    visto: dict = {}

    async def _falso(messages, json_saida=True):
        visto["json_saida"] = json_saida
        return "prosa"

    monkeypatch.setattr(DC, "_gerar_default", _falso)

    assert DC.gerar_sync("pergunta", json_saida=False) == "prosa"
    assert visto["json_saida"] is False


def test_gerar_sync_continua_em_json_por_padrao(monkeypatch):
    """Quem já usava `gerar_sync` não muda de comportamento."""
    visto: dict = {}

    async def _falso(messages, json_saida=True):
        visto["json_saida"] = json_saida
        return "{}"

    monkeypatch.setattr(DC, "_gerar_default", _falso)

    DC.gerar_sync("pergunta")
    assert visto["json_saida"] is True
