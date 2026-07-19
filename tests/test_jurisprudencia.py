# -*- coding: utf-8 -*-
"""Teste do índice cláusula→jurisprudência (fundamentar_clausula) e da base ampliada.

Verifica: (a) cada tipo de cláusula do E7 tem entrada no INDICE_CLAUSULA; (b) fundamentar_clausula devolve
súmula/acórdão/dispositivo/teste para tipos conhecidos e {} para desconhecidos; (c) itens de fonte secundária
carregam a flag `verificar_antes_de_citar` (honestidade — nada não-confirmado vira citação definitiva).
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_jurisprudencia.py -q
"""
from __future__ import annotations

from compliance_agent.knowledge.jurisprudencia import (
    INDICE_CLAUSULA,
    SUMULAS,
    buscar_acordaos,
    fundamentar_clausula,
)

# tipos canônicos que o E7/coletor_edital produzem
_TIPOS_E7 = {
    "atestado_quantitativo", "atestado_identico", "visita_tecnica", "vinculo_profissional",
    "capital_patrimonio", "indices_contabeis", "garantia_proposta", "recorte_geografico",
    "recorte_temporal", "marca_dirigida", "amostra_poc", "pontuacao_dirigida",
}


def test_todo_tipo_de_clausula_tem_indice():
    faltando = _TIPOS_E7 - set(INDICE_CLAUSULA)
    assert not faltando, f"tipos de cláusula sem entrada no INDICE_CLAUSULA: {faltando}"


def test_fundamentar_marca_traz_sumula_270():
    f = fundamentar_clausula("marca_dirigida")
    assert any("270" in s for s in f["sumulas"])
    assert f["dispositivos_legais"]
    assert f["teste_finalistico"]


def test_fundamentar_capital_traz_sumula_275():
    f = fundamentar_clausula("capital_patrimonio")
    assert any("275" in s for s in f["sumulas"])


def test_fundamentar_tipo_desconhecido_vazio():
    assert fundamentar_clausula("xpto_inexistente") == {}


def test_flag_verificar_presente_em_fonte_secundaria():
    # visita técnica: âncoras TCU (trio 3.831/2012…) só confirmadas em fonte secundária + data da Súmula
    # TCE-RJ nº 01 em aberto → marcada para verificação antes de citar como definitiva
    f = fundamentar_clausula("visita_tecnica")
    assert f.get("verificar_antes_de_citar") is True


def test_clausula_com_ancora_primaria_nao_pede_verificacao():
    # capital/PL: Súmula TCU 275 conferida em fonte primária → não pede verificação
    f = fundamentar_clausula("capital_patrimonio")
    assert f.get("verificar_antes_de_citar") is False


def test_acordaos_paradigma_ampliados_presentes():
    # a ampliação da base trouxe os paradigmas recentes (Anexo A)
    numeros = " ".join(a.numero for a in buscar_acordaos())
    assert "1.604/2025" in numeros  # atestado > 50%
    assert "1.065/2024" in numeros  # direcionamento por dano concreto


def test_sumulas_carregam_orgao_e_numero():
    assert SUMULAS
    for sid, s in SUMULAS.items():
        assert s["orgao"] and s["numero"]


# ── normalização de chave de súmula (obter_sumula) — mata o match frágil por string ──

def test_obter_sumula_forma_canonica():
    from compliance_agent.knowledge.jurisprudencia import obter_sumula
    s = obter_sumula("Súmula TCU 263")
    assert s and s["orgao"] == "TCU" and "263" in s["numero"]


def test_obter_sumula_com_no_e_ordinal():
    from compliance_agent.knowledge.jurisprudencia import obter_sumula
    assert obter_sumula("Súmula TCU nº 263") is not None
    assert obter_sumula("Súmula nº 275 do TCU") is not None


def test_obter_sumula_tcerj_zero_a_esquerda():
    from compliance_agent.knowledge.jurisprudencia import obter_sumula
    # "TCE-RJ 01" está gravada com zero à esquerda; "nº 1" tem de achar a mesma
    assert obter_sumula("Súmula TCE-RJ nº 1") is not None
    assert obter_sumula("Súmula TCERJ 01") is not None


def test_obter_sumula_desconhecida_none():
    from compliance_agent.knowledge.jurisprudencia import obter_sumula
    assert obter_sumula("Súmula TCU 999") is None
    assert obter_sumula("") is None
