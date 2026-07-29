# -*- coding: utf-8 -*-
"""Patrimônio incompatível — a acusação mais fácil de errar, e as travas que impedem o erro.

"Patrimônio a descoberto" é a espinha dorsal de investigação financeira e também o lugar onde um
módulo mal desenhado vira manchete sem prova. Renda não é só salário; bem declarado tem valor de
aquisição, não de mercado; e faturamento de empresa NÃO é renda do sócio — cobre custo, folha,
tributo e capital de giro.

Quatro travas, e a razão de cada uma:

  1. **Ausência de renda conhecida não é renda zero.** Quem não está na folha pública pode ter
     renda privada inteira — é o caso da maioria das pessoas.
  2. **Faturamento não é renda.** A explicação inocente vai junto, sempre.
  3. **Capital ínfimo é FACHADA, não enriquecimento.** Confundir as duas famílias produz acusação
     errada contra micro-empresa legítima.
  4. **A base é anual.** Comparar quatro anos de contrato com um ano de salário infla o resultado
     por aritmética, não por achado.
"""
from __future__ import annotations

import pytest

from compliance_agent.osint.patrimonio import avaliar_empresa, avaliar_pessoa


# ───────────────────────── pessoa ─────────────────────────────────────────────────────────────

def test_sem_fonte_de_renda_conhecida_e_INDISPONIVEL_nao_renda_zero():
    r = avaliar_pessoa(nome="Fulano", recebido_via_empresas=5_000_000.0)
    assert r["aferivel"] is False and r["nivel"] is None
    assert "renda privada inteira" in r["motivo"]
    assert "COAF" in r["diligencia_sugerida"]


def test_sem_valor_recebido_nao_afere():
    r = avaliar_pessoa(remuneracao_publica_anual=100_000.0)
    assert r["aferivel"] is False and "ausente ≠ zero" in r["motivo"]


def test_desproporcao_moderada_nao_dispara():
    r = avaliar_pessoa(recebido_via_empresas=500_000.0, remuneracao_publica_anual=120_000.0)
    assert r["aferivel"] is True and r["nivel"] is None


@pytest.mark.parametrize("recebido,esperado", [
    (1_500_000.0, "medio"),      # 15×
    (7_000_000.0, "forte"),      # 70×
    (30_000_000.0, "critico"),   # 300×
])
def test_gravidade_cresce_com_a_razao(recebido, esperado):
    r = avaliar_pessoa(recebido_via_empresas=recebido, remuneracao_publica_anual=100_000.0)
    assert r["nivel"] == esperado


def test_periodo_e_normalizado_para_a_mesma_base():
    """Comparar 4 anos de contrato com 1 ano de salário infla por aritmética, não por achado."""
    um = avaliar_pessoa(recebido_via_empresas=4_000_000.0, remuneracao_publica_anual=100_000.0)
    quatro = avaliar_pessoa(recebido_via_empresas=4_000_000.0,
                            remuneracao_publica_anual=100_000.0, anos=4)
    assert quatro["razao"] == pytest.approx(um["razao"] / 4)


def test_varias_fontes_de_renda_somam():
    r = avaliar_pessoa(recebido_via_empresas=1_000_000.0, remuneracao_publica_anual=100_000.0,
                       bens_declarados=400_000.0, outras_rendas_conhecidas=500_000.0)
    assert r["n_fontes"] == 3 and r["capacidade_no_periodo"] == pytest.approx(1_000_000.0)
    assert r["nivel"] is None


def test_achado_traz_a_explicacao_de_que_faturamento_NAO_e_renda():
    r = avaliar_pessoa(recebido_via_empresas=30_000_000.0, remuneracao_publica_anual=100_000.0)
    assert "NÃO é renda do sócio" in r["explicacao_inocente"]
    assert "priorização de diligência" in r["ressalva"]


def test_achado_diz_qual_diligencia_pedir():
    """O produto útil a quem tem prerrogativa de requisitar."""
    r = avaliar_pessoa(recebido_via_empresas=30_000_000.0, remuneracao_publica_anual=100_000.0)
    assert "declaração de bens" in r["diligencia_sugerida"]


# ───────────────────────── empresa ────────────────────────────────────────────────────────────

def test_capital_infimo_e_FACHADA_e_o_modulo_diz_isso():
    r = avaliar_empresa(razao_social="Alfa", capital_social=1_000.0,
                        valor_contratado=10_000_000.0)
    assert r["nivel"] == "forte" and r["familia"] == "perfil_contratado"
    assert "NÃO de enriquecimento" in r["nota"]


def test_capital_usual_nao_dispara():
    r = avaliar_empresa(capital_social=500_000.0, valor_contratado=1_000_000.0)
    assert r["nivel"] is None and "dentro do usual" in r["motivo"]


def test_faixa_intermediaria_e_medio():
    r = avaliar_empresa(capital_social=50_000.0, valor_contratado=10_000_000.0)
    assert r["nivel"] == "medio"


def test_usa_o_pago_em_OB_quando_nao_ha_valor_contratado():
    r = avaliar_empresa(capital_social=1_000.0, valor_pago_ob=5_000_000.0)
    assert r["aferivel"] is True and r["valor_referencia"] == pytest.approx(5_000_000.0)


def test_dado_faltante_nao_vira_zero():
    assert avaliar_empresa(capital_social=None, valor_contratado=1_000.0)["aferivel"] is False
    assert avaliar_empresa(capital_social=1_000.0)["aferivel"] is False


def test_capital_desatualizado_e_a_explicacao_inocente():
    r = avaliar_empresa(capital_social=1_000.0, valor_contratado=10_000_000.0)
    assert "desatualizado" in r["explicacao_inocente"]
