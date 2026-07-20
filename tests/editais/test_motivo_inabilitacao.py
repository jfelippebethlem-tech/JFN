# -*- coding: utf-8 -*-
"""Classificador trivial × substancial — editais/motivo_inabilitacao.py.
Complementa J7: mede a TRIVIALIDADE do motivo em si (art. 64 §1º + art. 12 III), não a seletividade.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/editais/test_motivo_inabilitacao.py -q
"""
from __future__ import annotations

from compliance_agent.editais.motivo_inabilitacao import classificar, taxa_trivialidade


def test_assinatura_faltante_e_trivial_sem_diligencia_viola():
    r = classificar("inabilitada por ausência de assinatura na proposta comercial")
    assert r["classe"] == "trivial"
    assert r["violacao_saneamento"] is True
    assert "64" in r["fundamento"]


def test_trivial_com_diligencia_nao_viola():
    r = classificar("certidão de regularidade fiscal vencida", houve_diligencia=True)
    assert r["classe"] == "trivial"
    assert r["violacao_saneamento"] is False


def test_atestado_insuficiente_e_substancial():
    r = classificar("atestado de capacidade técnica não atende o quantitativo mínimo exigido no item 10.2")
    assert r["classe"] == "substancial"
    assert r["violacao_saneamento"] is False


def test_capital_insuficiente_e_substancial():
    assert classificar("patrimônio líquido insuficiente frente ao exigido")["classe"] == "substancial"


def test_preco_acima_do_estimado_e_substancial():
    assert classificar("proposta desclassificada por permanecer acima do orçamento estimado")["classe"] == "substancial"


def test_substancial_vence_trivial_quando_ambos_casam():
    # contém "declaração" (trivial) mas o cerne é sanção vigente (substancial) — precisão > cobertura
    r = classificar("declaração de inidoneidade vigente impede a participação")
    assert r["classe"] == "substancial"


def test_motivo_vazio_nao_aferivel():
    r = classificar("")
    assert r["classe"] == "nao_aferivel"
    assert r["violacao_saneamento"] is False


def test_motivo_estranho_e_ambiguo_vai_para_rubrica():
    r = classificar("a empresa não demonstrou aderência à visão estratégica do órgão")
    assert r["classe"] == "ambiguo"
    assert "rubrica" in r["fundamento"]


def test_taxa_trivialidade_agrega():
    rs = [classificar("ausência de rubrica na página 3"),
          classificar("atestado não atende quantitativo"),
          classificar("certidão vencida", houve_diligencia=True),
          classificar("")]
    t = taxa_trivialidade(rs)
    assert t["n"] == 4 and t["triviais"] == 2
    assert t["violacoes_saneamento"] == 1
    assert t["substanciais"] == 1 and t["nao_aferiveis"] == 1
    assert t["taxa_trivial"] == 0.5


def test_taxa_vazia_honesta():
    assert taxa_trivialidade([])["taxa_trivial"] is None
