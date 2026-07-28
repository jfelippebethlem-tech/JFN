# -*- coding: utf-8 -*-
"""Resposta OpenAI-compatible com erro embutido em HTTP 200.

CAUSA-RAIZ medida em 2026-07-28. O OpenRouter responde **HTTP 200** com corpo de erro quando o
provedor upstream falha:

    {"error": {"message": "Upstream error from Nvidia: ResourceExhausted:
                Worker local total request limit reached (16/16)", "code": 502}}

Cadeia do estrago, que é bem maior que o `KeyError` visível:

    1. `raise_for_status()` passa — o status É 200;
    2. `data["choices"]` estoura `KeyError: 'choices'`;
    3. `except (httpx.HTTPError, RuntimeError)` NÃO pega KeyError → escapa do laço de retry,
       sem UMA retentativa, num erro que é de capacidade e portanto transitório;
    4. lá em cima o `except Exception` marca cooldown do provedor;
    5. `_classificar_erro` recebe `KeyError('choices')`, não casa nada e devolve o genérico.

Resultado: um soluço passageiro do upstream derruba o degrau OpenRouter inteiro.

Estes testes travam as duas propriedades que importam: o erro embutido vira exceção
CLASSIFICÁVEL (e não KeyError), e um erro de capacidade é reconhecido como retentável.
"""
from __future__ import annotations

import pytest

from compliance_agent.llm.free_llm import (
    RespostaProvedorErro, _classificar_erro, conteudo_da_resposta,
)

_ERRO_502 = {"error": {"message": "Upstream error from Nvidia: ResourceExhausted: "
                                  "Worker local total request limit reached (16/16)",
                       "code": 502}}
_OK = {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}


def test_resposta_normal_devolve_o_conteudo():
    assert conteudo_da_resposta(_OK) == "OK"


def test_erro_embutido_em_200_vira_excecao_classificavel_e_nao_KeyError():
    """O ponto do conserto: `KeyError` escapava do laço de retry porque não é HTTPError."""
    with pytest.raises(RespostaProvedorErro) as exc:
        conteudo_da_resposta(_ERRO_502)
    assert "ResourceExhausted" in str(exc.value)
    assert exc.value.codigo == 502


def test_erro_de_capacidade_e_reconhecido_como_transitorio():
    """ResourceExhausted é cota/capacidade — retentar resolve. Tratar como falha dura tirava
    o provedor da cadeia por um soluço passageiro."""
    with pytest.raises(RespostaProvedorErro) as exc:
        conteudo_da_resposta(_ERRO_502)
    assert exc.value.retentavel is True


def test_classificador_reconhece_o_erro_embutido_pelo_codigo():
    """Antes: `KeyError('choices')` não casava nada e caía no genérico de 15 s."""
    try:
        conteudo_da_resposta(_ERRO_502)
    except RespostaProvedorErro as e:
        motivo, _segundos = _classificar_erro(e)
    assert motivo == "server", f"502 embutido devia classificar como server, veio {motivo}"


def test_erro_de_autenticacao_embutido_nao_e_retentavel():
    """Chave ruim não melhora esperando — e o cooldown longo depende dessa distinção."""
    with pytest.raises(RespostaProvedorErro) as exc:
        conteudo_da_resposta({"error": {"message": "invalid api key", "code": 401}})
    assert exc.value.retentavel is False


def test_choices_vazio_tambem_nao_pode_virar_IndexError():
    """Lista vazia é a outra forma de a resposta não trazer conteúdo."""
    with pytest.raises(RespostaProvedorErro):
        conteudo_da_resposta({"choices": []})


def test_conteudo_nulo_e_tratado_como_ausencia_e_nao_como_a_string_None():
    """Um provedor devolveu `content: null`; virar a string 'None' contaminaria o dossiê."""
    assert conteudo_da_resposta(
        {"choices": [{"message": {"content": None}}]}) == ""


def test_corpo_que_nao_e_dicionario_nao_quebra_com_AttributeError():
    with pytest.raises(RespostaProvedorErro):
        conteudo_da_resposta(["isto não é uma resposta"])
