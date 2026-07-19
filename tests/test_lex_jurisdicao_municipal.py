# -*- coding: utf-8 -*-
"""Gate de esfera do Lex: órgão municipal-Rio roteia p/ TCM-RJ; estadual preserva TCE-RJ."""
from compliance_agent.lex_orgao import _parecer_orgao_md
from compliance_agent.lex_redflags import jurisdicao

_ANALISE = {
    "achados": [{"rf": "R8", "obs": "concentração relevante", "grav": 4}],
    "emoji": "🟡", "rotulo": "ATENÇÃO", "just": "indícios a apurar",
}


def test_jurisdicao_helper():
    j = jurisdicao("municipal-rio")
    assert j["contas"] == "TCM-RJ"
    assert j["representacao"] == "TCM-RJ/MP-RJ"
    assert j["controle_interno"] == "CGM-Rio"
    # default preserva o comportamento estadual atual
    for e in ("estadual-rj", "federal", "indefinido", ""):
        assert jurisdicao(e)["contas"] == "TCE-RJ"
        assert jurisdicao(e)["representacao"] == "TCE-RJ/MP-RJ"


def test_parecer_orgao_estadual_preserva_tce():
    md = _parecer_orgao_md({"nome": "Secretaria de Estado de Saúde", "ug": "295100"}, _ANALISE)
    assert "TCE-RJ/MP-RJ" in md
    assert "TCM-RJ" not in md
    assert "Competência (esfera municipal-Rio)" not in md


def test_parecer_orgao_municipal_roteia_tcm():
    md = _parecer_orgao_md(
        {"nome": "Secretaria Municipal de Saúde", "orgao_cnpj": "42498733000147"}, _ANALISE)
    assert "TCM-RJ/MP-RJ" in md          # encaminhamento ajustado
    assert "Tribunal de Contas do Município" in md   # nota de competência
    assert "CGM-Rio" in md
    # não deve mandar a despesa municipal ao TCE-RJ no encaminhamento
    assert "representação ao TCE-RJ/MP-RJ" not in md


def test_parecer_orgao_municipal_por_nome_prefeitura():
    md = _parecer_orgao_md({"nome": "Prefeitura da Cidade do Rio de Janeiro"}, _ANALISE)
    assert "TCM-RJ/MP-RJ" in md
