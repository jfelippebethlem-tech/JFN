# -*- coding: utf-8 -*-
"""O parse do `groq_agent` sempre pede um OBJETO — e o que fazer quando vem lista.

O parser antigo procurava `{` ANTES de `[`, então em `[{"a":1},{"a":2}]` devolvia `{"a":1}`:
acertava por acidente o caso do modelo que embrulha o objeto numa lista de um item, e perdia o
resto em silêncio quando a lista tinha mais. O parse único da casa devolve o JSON verdadeiro;
o desembrulho fica aqui, explícito e limitado ao caso em que nada se perde.
"""
from compliance_agent.llm.groq_agent import _parse_json


def test_objeto_embrulhado_em_lista_de_um_item_e_desembrulhado():
    assert _parse_json('[{"action":"click","text":"OB"}]') == {"action": "click", "text": "OB"}


def test_lista_com_varios_itens_nao_vira_o_primeiro_item():
    """Devolver `{"a":1}` esconderia `{"a":2}`: o chamador trataria fragmento como resposta."""
    assert _parse_json('[{"a":1},{"a":2}]') == [{"a": 1}, {"a": 2}]


def test_objeto_direto_continua_objeto():
    assert _parse_json('{"action":"click"}') == {"action": "click"}


def test_lista_de_escalares_nao_e_desembrulhada():
    assert _parse_json("[1]") == [1]
