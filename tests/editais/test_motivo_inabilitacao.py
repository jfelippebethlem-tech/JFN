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


# ── rubrica LLM (só o resíduo ambíguo; citação literal obrigatória; abstenção honesta) ──

def test_rubrica_nao_roda_quando_gabarito_decide():
    from compliance_agent.editais.motivo_inabilitacao import classificar_com_rubrica
    chamado = []
    r = classificar_com_rubrica("ausência de assinatura na proposta",
                                gerar=lambda *a: chamado.append(1) or "{}")
    assert r["classe"] == "trivial" and not chamado  # determinístico decidiu; LLM nem foi chamada


def test_rubrica_exige_citacao_literal():
    from compliance_agent.editais.motivo_inabilitacao import classificar_com_rubrica
    motivo = "a empresa não demonstrou aderência à visão estratégica"
    fake = lambda sys, p: '{"classe":"substancial","trecho":"texto que não está no motivo original"}'  # noqa: E731
    assert classificar_com_rubrica(motivo, gerar=fake)["classe"] == "ambiguo"  # citação falsa → descarta


def test_rubrica_valida_promove_com_origem_llm():
    from compliance_agent.editais.motivo_inabilitacao import classificar_com_rubrica
    motivo = "a empresa não demonstrou aderência à visão estratégica do órgão"
    fake = lambda sys, p: '{"classe":"trivial","trecho":"não demonstrou aderência à visão"}'  # noqa: E731
    r = classificar_com_rubrica(motivo, gerar=fake)
    assert r["classe"] == "trivial" and r["origem_llm"] is True
    assert "SUSPEITO" in r["fundamento"]


def test_rubrica_llm_caida_segue_ambiguo():
    from compliance_agent.editais.motivo_inabilitacao import classificar_com_rubrica
    def quebra(*a):
        raise RuntimeError("nous fora")
    assert classificar_com_rubrica("motivo estranho qualquer", gerar=quebra)["classe"] == "ambiguo"
