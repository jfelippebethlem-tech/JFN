# -*- coding: utf-8 -*-
"""O parse da resposta do LLM — os casos REAIS em que os três parsers da casa desistiam.

Cada teste aqui nasceu de uma forma de resposta que o modelo produz e que caía como
"não-parseável": 16% das pesquisas OSINT terminavam assim (sessão 2026-07-28). Resposta
descartada é evidência coletada e jogada fora — o custo já foi pago.
"""
import pytest

from compliance_agent.llm.json_resposta import parse_json_llm


def test_cerca_no_meio_da_prosa():
    """O modelo explica antes e depois do bloco; a cerca não está no início do texto."""
    raw = 'Claro! Segue a análise:\n\n```json\n{"grau":"amarelo"}\n```\n\nEspero ter ajudado.'
    assert parse_json_llm(raw) == {"grau": "amarelo"}


def test_chave_solta_na_prosa_antes_do_objeto():
    """Prosa que contém `{...}` que não é JSON — a busca gulosa começava no lugar errado."""
    raw = 'Responderei no formato {chave: valor} pedido: {"grau":"vermelho","n":2}'
    assert parse_json_llm(raw) == {"grau": "vermelho", "n": 2}


def test_chave_fechando_dentro_de_string_nao_encerra_o_objeto():
    """Contar `{`/`}` sem respeitar string corta o objeto no meio de um texto legítimo."""
    raw = '{"resumo":"o custo } por item destoa","grau":"amarelo"}'
    assert parse_json_llm(raw) == {"resumo": "o custo } por item destoa", "grau": "amarelo"}


def test_virgula_sobrando_antes_do_fechamento():
    raw = '{"achados":[{"duvida":"x"},],"grau":"verde",}'
    assert parse_json_llm(raw) == {"achados": [{"duvida": "x"}], "grau": "verde"}


def test_resposta_cortada_por_limite_de_tokens_preserva_o_que_veio():
    """`finish_reason == "length"`: fechar as estruturas abertas salva os achados já escritos."""
    raw = '{"resumo":"tres achados","achados":[{"duvida":"socio comum","veredito":"agrava"},{"duvida":"end'
    dados = parse_json_llm(raw)
    assert dados["resumo"] == "tres achados"
    assert dados["achados"][0]["veredito"] == "agrava"


def test_resposta_cortada_se_declara_truncada():
    """Reparar sem avisar seria apresentar leitura parcial como completa — o pecado da casa."""
    raw = '{"resumo":"tres achados","achados":[{"duvida":"socio comum"'
    assert parse_json_llm(raw)["_truncado"] is True


def test_resposta_inteira_nao_se_declara_truncada():
    assert "_truncado" not in parse_json_llm('{"grau":"verde"}')


def test_lista_no_topo():
    assert parse_json_llm('```json\n[{"a":1},{"a":2}]\n```') == [{"a": 1}, {"a": 2}]


@pytest.mark.parametrize("raw", ["", None, "não há nada de JSON nesta frase", "{", "}{"])
def test_sem_json_devolve_none_em_vez_de_inventar(raw):
    assert parse_json_llm(raw) is None
