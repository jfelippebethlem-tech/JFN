# -*- coding: utf-8 -*-
"""O corte no teto de tokens tem que APARECER, e o teto tem que caber a ficha.

Defeito medido no acervo (31/07/2026): `data/sei_refichar.log` tinha 3.137 linhas e ZERO
sucessos — 1.633 delas `ERRO cdp_*.json: JSON inválido`. O cache estava íntegro; quem vinha
quebrado era a resposta do modelo. Instrumentando a fronteira do nous no processo real
`SEI-030001/109183/2024`:

    teto  8000 (o vigente) → finish_reason='length', content='', reasoning=26.407 chars → falha
    teto 16000            → finish_reason='stop',   completion_tokens=11.184 → parseia
    teto 20000            → finish_reason='stop',   completion_tokens=11.289 → parseia
    teto 32000            → finish_reason='stop',   completion_tokens=13.963 → parseia

O `stepfun` é modelo de RACIOCÍNIO: gastava os 8.000 tokens inteiros pensando e o `content`
nunca começava. Duas falhas somadas: (1) o teto não cabia a ficha — pagava-se 8.000 tokens por
ZERO resultado; (2) `_chamar_nous` caía no `reasoning` truncado e o erro final virava um
`"JSON inválido"` mudo, que culpa o cache e esconde o corte. O `finish_reason` existia na
resposta e era descartado.
"""
import asyncio

import pytest

import tools.sei_ficha as sf


class _RespFalsa:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _ClienteFalso:
    """Substitui `httpx.AsyncClient` — devolve sempre a mesma resposta."""

    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, *_a, **_kw):
        return self._resp


def _monta(monkeypatch, *, finish_reason, content, reasoning):
    import httpx

    resp = _RespFalsa({"choices": [{"finish_reason": finish_reason,
                                    "message": {"content": content, "reasoning": reasoning}}],
                       "usage": {"completion_tokens": 8000}})
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _ClienteFalso(resp))
    monkeypatch.setenv("NOUS_API_KEY", "chave-falsa-de-teste")


def test_corte_no_teto_vira_erro_falante_e_nao_json_invalido(monkeypatch):
    """finish_reason='length' com content vazio = corte no teto. Tem que dizer isso, não 'JSON inválido'."""
    _monta(monkeypatch, finish_reason="length", content="",
           reasoning="Vou analisar o processo. Primeiro o objeto, que parece ser {\"objeto\": \"limpeza")

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(sf._chamar_nous("texto qualquer", sf.STEPFUN))

    msg = str(exc.value)
    assert "teto" in msg.lower(), f"o erro precisa nomear o corte no teto: {msg!r}"
    assert "8000" in msg, f"o erro precisa trazer os tokens gastos: {msg!r}"
    assert "SEI_FICHA_MAX_TOKENS" in msg, f"o erro precisa dizer qual botão girar: {msg!r}"


def test_corte_no_teto_chega_ao_chamador_como_erro_falante(monkeypatch):
    """`extrair_ficha` é o que o sweep loga — o diagnóstico não pode morrer no caminho."""
    _monta(monkeypatch, finish_reason="length", content="", reasoning="pensando… {\"objeto\": \"limp")

    f = asyncio.run(sf.extrair_ficha("texto qualquer", sf.STEPFUN, provider="nous"))

    assert f.get("_erro"), "resposta cortada tem que virar _erro"
    assert "teto" in f["_erro"].lower(), f"o _erro logado ainda é mudo: {f['_erro']!r}"


def test_resposta_completa_continua_passando(monkeypatch):
    """Guarda-costas: com finish_reason='stop' nada muda — o caminho bom segue igual."""
    _monta(monkeypatch, finish_reason="stop", content='{"objeto": "limpeza"}', reasoning="pensei muito")

    assert asyncio.run(sf._chamar_nous("texto", sf.STEPFUN)) == '{"objeto": "limpeza"}'


def test_content_vazio_sem_corte_ainda_cai_no_reasoning(monkeypatch):
    """Salvamento antigo preservado: sem 'length', content vazio ainda tenta o reasoning."""
    _monta(monkeypatch, finish_reason="stop", content="", reasoning='{"objeto": "limpeza"}')

    assert asyncio.run(sf._chamar_nous("texto", sf.STEPFUN)) == '{"objeto": "limpeza"}'


def test_teto_padrao_cabe_a_ficha_medida():
    """13.963 tokens foi o maior gasto medido no processo real; o padrão precisa ter folga sobre isso."""
    assert sf._MAX_TOKENS >= 16_000, (
        f"teto padrão {sf._MAX_TOKENS} não cabe a ficha (medido: 11.184–13.963 tokens de completion)")
