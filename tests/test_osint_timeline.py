# -*- coding: utf-8 -*-
"""Linha do tempo — a história que só a SEQUÊNCIA conta, e o que ela não pode inventar.

Cada peça já é detectada isolada: empresa recém-aberta, sócio servidor, pagamento a empresa
baixada, sanção vigente. Sozinha, cada uma é fraca e explicável. Em ORDEM, contam outra coisa —
e é essa leitura que faltava.

Duas honestidades travadas aqui, ambas vindas de erro já pago nesta casa:

  · **Evento sem data não recebe posição inventada.** `cadeia_processo` usa o ID sequencial do SEI
    como proxy de ordem e DECLARA que é proxy; inventar posição é pior que admitir a lacuna.
  · **Toda regra traz a explicação inocente ao lado.** Proximidade temporal é coincidência até
    prova em contrário, e a peça que ignora isso é atacável na origem.
"""
from __future__ import annotations

import pytest

from compliance_agent.osint.timeline import TIPOS, analisar, montar


def _ev(tipo, data, **kw):
    return {"tipo": tipo, "data": data, "fonte": kw.pop("fonte", "Receita Federal"), **kw}


# ───────────────────────────── montagem ───────────────────────────────────────────────────────

def test_ordena_por_data():
    r = montar([_ev("homologacao", "2024-06-01"), _ev("edital_publicado", "2024-04-01")])
    assert [e.tipo for e in r["linha"]] == ["edital_publicado", "homologacao"]


def test_evento_sem_data_vai_para_lacunas_nao_para_a_linha():
    r = montar([_ev("homologacao", None, descricao="homologação sem data nos autos")])
    assert r["linha"] == [] and len(r["lacunas"]) == 1
    assert "sem data" in r["lacunas"][0]["motivo"]


def test_data_em_formato_brasileiro_e_aceita():
    assert montar([_ev("edital_publicado", "01/04/2024")])["linha"]


def test_tipo_desconhecido_entra_na_linha_mas_e_declarado():
    """Regra que dispara sobre tipo não previsto é regra que ninguém revisou."""
    r = montar([_ev("evento_inventado", "2024-01-01")])
    assert r["linha"] and r["tipos_desconhecidos"] == ["evento_inventado"]


def test_entrada_suja_nao_quebra():
    assert montar([None, "lixo", 42, {}])["linha"] == []


# ───────────────────────── 1 · empresa às vésperas ────────────────────────────────────────────

def test_empresa_aberta_pouco_antes_do_edital():
    r = analisar([_ev("empresa_aberta", "2024-01-01"), _ev("edital_publicado", "2024-02-15")])
    a = next(x for x in r["achados"] if x["regra"] == "empresa_criada_as_vesperas")
    assert a["dias"] == 45 and a["nivel"] == "forte"
    assert "lícito" in a["explicacao_inocente"]


def test_empresa_antiga_nao_dispara():
    r = analisar([_ev("empresa_aberta", "2015-01-01"), _ev("edital_publicado", "2024-02-15")])
    assert not [x for x in r["achados"] if x["regra"] == "empresa_criada_as_vesperas"]


def test_empresa_aberta_DEPOIS_do_edital_e_achado_proprio():
    r = analisar([_ev("empresa_aberta", "2024-03-01"), _ev("edital_publicado", "2024-02-01")])
    a = next(x for x in r["achados"] if x["regra"] == "empresa_aberta_apos_o_edital")
    assert a["dias"] == 29 and "SPE" in a["explicacao_inocente"]


# ───────────────────────── 2 · QSA após homologação ───────────────────────────────────────────

def test_troca_de_socio_logo_apos_vencer():
    r = analisar([_ev("homologacao", "2024-05-01"), _ev("alteracao_qsa", "2024-05-20")])
    a = next(x for x in r["achados"] if x["regra"] == "qsa_alterado_apos_homologacao")
    assert a["dias"] == 19
    assert "não congela o QSA" in a["explicacao_inocente"]


def test_troca_de_socio_ANTES_da_homologacao_nao_dispara():
    r = analisar([_ev("homologacao", "2024-05-01"), _ev("alteracao_qsa", "2024-01-10")])
    assert not [x for x in r["achados"] if x["regra"] == "qsa_alterado_apos_homologacao"]


# ───────────────────────── 3 · pagamento após a baixa ─────────────────────────────────────────

def test_ordem_bancaria_apos_a_baixa_do_cnpj_e_critico():
    r = analisar([_ev("empresa_baixada", "2024-01-31"),
                  _ev("ordem_bancaria", "2024-06-10", valor=120000.0),
                  _ev("ordem_bancaria", "2024-08-10", valor=80000.0)])
    a = next(x for x in r["achados"] if x["regra"] == "pagamento_apos_baixa")
    assert a["nivel"] == "critico" and a["valor"] == pytest.approx(200000.0)


def test_pagamento_ANTES_da_baixa_nao_dispara():
    """R$ 4 bi 'pagos a empresa morta' eram 218× demais: o que conta é o que veio DEPOIS."""
    r = analisar([_ev("empresa_baixada", "2024-12-31"),
                  _ev("ordem_bancaria", "2024-06-10", valor=999999.0)])
    assert not [x for x in r["achados"] if x["regra"] == "pagamento_apos_baixa"]


# ───────────────────────── 4 · sanção vigente ─────────────────────────────────────────────────

def test_sancao_vigente_na_data_da_homologacao():
    r = analisar([_ev("sancao_inicio", "2023-01-01"), _ev("sancao_fim", "2025-01-01"),
                  _ev("homologacao", "2024-05-01")])
    a = next(x for x in r["achados"] if x["regra"] == "sancao_vigente_na_homologacao")
    assert a["nivel"] == "critico" and "abrangência" in a["explicacao_inocente"]


def test_sancao_encerrada_antes_nao_dispara():
    r = analisar([_ev("sancao_inicio", "2020-01-01"), _ev("sancao_fim", "2021-01-01"),
                  _ev("homologacao", "2024-05-01")])
    assert not [x for x in r["achados"] if x["regra"] == "sancao_vigente_na_homologacao"]


def test_sancao_sem_termo_final_conta_como_vigente():
    r = analisar([_ev("sancao_inicio", "2023-01-01"), _ev("homologacao", "2024-05-01")])
    assert [x for x in r["achados"] if x["regra"] == "sancao_vigente_na_homologacao"]


# ───────────────────────── 5 e 6 · execução ───────────────────────────────────────────────────

def test_aditivo_precoce():
    r = analisar([_ev("contrato_assinado", "2024-01-10"), _ev("aditivo", "2024-02-20")])
    a = next(x for x in r["achados"] if x["regra"] == "aditivo_precoce")
    assert a["dias"] == 41


def test_pagamento_antes_do_atesto():
    r = analisar([_ev("atesto", "2024-06-01"), _ev("ordem_bancaria", "2024-05-01", valor=10.0)])
    a = next(x for x in r["achados"] if x["regra"] == "pagamento_antes_do_atesto")
    assert "data do recebimento" in a["explicacao_inocente"]


# ───────────────────────── contrato de saída ──────────────────────────────────────────────────

def test_achados_saem_do_mais_grave_para_o_menos():
    r = analisar([_ev("contrato_assinado", "2024-01-10"), _ev("aditivo", "2024-02-20"),
                  _ev("empresa_baixada", "2024-03-01"),
                  _ev("ordem_bancaria", "2024-06-01", valor=1.0)])
    niveis = [a["nivel"] for a in r["achados"]]
    assert niveis[0] == "critico"


def test_toda_regra_traz_explicacao_inocente_e_fontes():
    r = analisar([_ev("empresa_aberta", "2024-01-01"), _ev("edital_publicado", "2024-02-15"),
                  _ev("homologacao", "2024-04-01"), _ev("alteracao_qsa", "2024-04-20")])
    assert r["achados"]
    for a in r["achados"]:
        assert a["explicacao_inocente"] and a["fontes"]


def test_periodo_e_declarado():
    r = analisar([_ev("empresa_aberta", "2020-01-01"), _ev("ordem_bancaria", "2024-01-01")])
    assert r["periodo"] == {"de": "2020-01-01", "ate": "2024-01-01"}


def test_linha_vazia_nao_quebra_nem_inventa_periodo():
    r = analisar([])
    assert r["achados"] == [] and r["periodo"] is None


def test_ressalva_sempre_presente():
    assert "INDÍCIO" in analisar([])["ressalva"]


def test_vocabulario_documentado():
    for t in ("empenho", "ordem_bancaria"):
        assert t in TIPOS
    assert "NÃO é pagamento" in TIPOS["empenho"]
