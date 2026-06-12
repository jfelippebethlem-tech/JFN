# -*- coding: utf-8 -*-
"""
Testes do eixo "risco de PUNIÇÃO" + quadrante achado×punição (compliance_agent.priorizacao).

TARGETED, em memória — sem rede, sem DuckDB, sem DB de 1,2GB. Cobre:
  • materialidade alta vs. baixa (faixas de valor / OB),
  • conluio → tipificação forte (CP 337-F + Lei 12.529) e competência MP+CADE,
  • honestidade: componente sem dado fica INDISPONÍVEL e não infla o score,
  • classificação de quadrante (priorizar o alto-alto).

Rodar SÓ este arquivo:
    .venv/bin/pytest tests/test_priorizacao.py -q
"""
from __future__ import annotations

from compliance_agent import priorizacao as P


# ───────────────────────── materialidade ─────────────────────────

def test_materialidade_alta_vs_baixa():
    achados = [{"codigo": "H-CAPITAL", "cnpj": "11444777000161"}]
    alto = P.risco_punicao(achados, total_pago=20_000_000.0)
    baixo = P.risco_punicao(achados, total_pago=10_000.0)
    assert alto["materialidade"]["score"] == 90      # ≥ R$ 10 mi
    assert baixo["materialidade"]["score"] == 15      # < R$ 50 mil
    assert alto["score"] > baixo["score"]             # valor maior → punição mais viável


def test_materialidade_indisponivel_nao_zera_nem_infla():
    achados = [{"codigo": "H-CONLUIO", "cnpj": "11444777000161"}]
    com = P.risco_punicao(achados, total_pago=2_000_000.0)
    sem = P.risco_punicao(achados, total_pago=None)
    assert sem["materialidade"]["score"] == P._INDISPONIVEL
    assert "3/4" in sem["cobertura"]                  # materialidade fora da conta
    # sem o valor, o score sai dos OUTROS componentes — não vira 0 nem é inflado
    assert 0 < sem["score"] <= 100
    assert com["cobertura"].startswith("4/4")


# ───────────────────────── tipificação (conluio = forte) ─────────────────────────

def test_conluio_tipificacao_forte_e_competencia():
    achados = [{"codigo": "H-CONLUIO", "cnpj": "11444777000161",
                "socios": [{"nome": "FULANO"}]}]
    r = P.risco_punicao(achados, total_pago=5_000_000.0)
    tip = r["tipificacao"]
    assert tip["score"] == 90                          # enquadramento forte
    assert "337-F" in tip["nota"] and "12.529" in tip["nota"]
    assert r["competencia"]["destinatarios"] == ["MP", "CADE"]
    assert r["competencia"]["score"] == 100            # foro múltiplo robusto


def test_familia_desconhecida_tipificacao_indisponivel():
    achados = [{"codigo": "H-XPTO-INEXISTENTE"}]
    r = P.risco_punicao(achados, total_pago=1_000_000.0)
    assert r["tipificacao"]["score"] == P._INDISPONIVEL
    assert r["competencia"]["score"] == P._INDISPONIVEL  # competência deriva da tipificação


def test_familia_explicita_tem_precedencia_sobre_codigo():
    achados = [{"codigo": "H-CAPITAL", "familia": "sobrepreco", "cnpj": "11444777000161"}]
    r = P.risco_punicao(achados, total_pago=1_000_000.0)
    assert r["tipificacao"]["familia_dominante"] == "sobrepreco"


# ───────────────────────── autoria ─────────────────────────

def test_autoria_identificavel_vs_ausente():
    com = P.risco_punicao([{"codigo": "H-CONLUIO", "cnpj": "11444777000161"}], total_pago=1_000_000.0)
    sem = P.risco_punicao([{"codigo": "H-CONLUIO"}], total_pago=1_000_000.0)
    assert com["autoria"]["score"] == 100               # 1/1 com CNPJ
    assert sem["autoria"]["score"] == P._INDISPONIVEL    # sem CNPJ/CPF/sócio → indisponível, não 0


# ───────────────────────── prescrição (honestidade) ─────────────────────────

def test_prescricao_consumada_zera_o_score():
    achados = [{"codigo": "H-CONLUIO", "cnpj": "11444777000161"}]
    r = P.risco_punicao(achados, total_pago=20_000_000.0, prescricao_anos=0)
    assert r["score"] == 0.0
    assert "PRESCRITO" in r["cobertura"]


def test_prescricao_nao_informada_nao_penaliza():
    achados = [{"codigo": "H-CONLUIO", "cnpj": "11444777000161"}]
    r = P.risco_punicao(achados, total_pago=20_000_000.0)
    assert r["prescricao"]["score"] == P._INDISPONIVEL
    assert r["score"] > 0


# ───────────────────────── quadrante ─────────────────────────

def test_quadrante_alto_alto_prioritario():
    assert P.quadrante(72.0, 80.0) == "alto-alto"
    assert "PRIORIT" in P.rotulo_quadrante("alto-alto").upper()


def test_quadrante_todos_os_casos():
    assert P.quadrante(90, 90) == "alto-alto"
    assert P.quadrante(90, 10) == "alto-baixo"
    assert P.quadrante(10, 90) == "baixo-alto"
    assert P.quadrante(10, 10) == "baixo-baixo"
    assert P.quadrante(50, 50) == "alto-alto"   # limiar é inclusivo


def test_score_total_alto_para_conluio_milionario():
    achados = [{"codigo": "H-CONLUIO", "cnpj": "11444777000161",
                "socios": [{"nome": "X"}]}]
    r = P.risco_punicao(achados, total_pago=20_000_000.0)
    assert r["eixo"] == "alto"
    assert r["score"] >= 70
    assert P.quadrante(80.0, r["score"]) == "alto-alto"
