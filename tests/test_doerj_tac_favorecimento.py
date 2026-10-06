# -*- coding: utf-8 -*-
"""Partes puras do detector TAC × favorecimento: chave de casamento por nome e grau do agente público."""
from __future__ import annotations

from tools.doerj_tac_favorecimento import grau_agente, tokens


def test_tokens_ignora_forma_juridica_e_acentos():
    assert tokens("BRAVO ASSESSORIA E SERVIÇOS EMPRESARIAIS LTDA") == ["BRAVO", "ASSESSORIA"]
    assert tokens("LEFE EMERGÊNCIAS MÉDICAS LTDA") == ["LEFE", "EMERGENCIAS"]
    assert tokens("LTDA") == []


def test_agente_da_saude_e_vermelho_outros_amarelo():
    assert grau_agente("FUNDACAO SAUDE DO ESTADO DO RIO DE JANEIRO") == "🔴"
    assert grau_agente("Secretaria de Estado de Saúde") == "🔴"
    assert grau_agente("SECRETARIA DE ESTADO DE POLICIA MILITAR") == "🟡"
    assert grau_agente(None) == "🟡"
    assert grau_agente("PREFEITURA DO RIO — RioSaúde (RS/PRE)") == "🟡"   # saúde municipal não é o contratante do TAC


# ── 10/09/2026: contrato venceu → TAC no mês seguinte (TUISE × HETO: contrato até 13/01/2026, TAC desde 14/01/2026) ──
from tools.doerj_tac_favorecimento import contrato_vencido_para_tac, periodos_dos_tacs


def test_periodos_dos_tacs_le_o_periodo_indenizado():
    objs = ["indenização … no período de 14/01/2026 a 31/01/2026, conforme", "sem período", "no período de 01/02/2026 a 28/02/2026."]
    assert periodos_dos_tacs(objs) == [("2026-01-14", "2026-01-31"), ("2026-02-01", "2026-02-28")]


def test_contrato_vencido_no_dia_anterior_ao_tac_e_vermelho_quando_nada_mais_vige():
    ctr = [("2025-01-13", "2026-01-13", 30839124.84)]
    r = contrato_vencido_para_tac(ctr, [("2026-01-14", "2026-01-31"), ("2026-02-01", "2026-02-28")])
    assert r["grau"] == "🔴" and r["n"] == 2 and r["casos"][0]["dias"] == 1   # jan e fev caem na janela de 45 dias
    # outro contrato ainda vigente na data → 🟡 (pode ser outra unidade)
    ctr2 = ctr + [("2025-06-01", "2026-06-01", 9e6)]
    assert contrato_vencido_para_tac(ctr2, [("2026-01-14", "2026-01-31")])["grau"] == "🟡"
    # TAC 200 dias depois do fim: não é "o dia seguinte" — sem sinal
    assert contrato_vencido_para_tac(ctr, [("2026-08-01", "2026-08-31")]) is None
    assert contrato_vencido_para_tac([], [("2026-01-14", "2026-01-31")]) is None


def test_chaves_do_objeto_e_ug_do_orgao():
    from tools.doerj_tac_favorecimento import chaves_objeto, ug_do_orgao
    assert chaves_objeto("Tem por objeto a indenização pela prestação de serviços de apoio técnico assistencial, para UPA 24h Penha") == ["APOIO", "TECNICO", "ASSISTENCIAL"]
    assert chaves_objeto("Tem por objeto a indenização pela prestação de serviços médicos, para UPA 24h Campos") == ["MEDICOS"]
    assert ug_do_orgao("Fundação Saúde do Estado do Rio de Janeiro") == "294200" and ug_do_orgao("Secretaria de Estado de Educação") == "180100"
    assert ug_do_orgao("INSTITUTO VITAL BRAZIL S/A") is None
