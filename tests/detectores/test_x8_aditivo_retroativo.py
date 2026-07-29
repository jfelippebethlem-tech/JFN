# -*- coding: utf-8 -*-
"""X8 — o termo assinado depois que o contrato já tinha morrido.

Contrato extinto pela fluência do prazo não se prorroga: não há o que aditar (ON AGU 3/2009;
art. 107 da Lei 14.133/2021). O aditivo retroativo é o disfarce administrativo de dois problemas
distintos, e o card serve justamente para separá-los: execução sem cobertura contratual (o serviço
continuou e foi pago no vácuo) ou contratação nova sem certame.

Duas armadilhas travadas aqui:

  · **Publicação tardia não é assinatura tardia.** Publicar fora do prazo é irregularidade de
    outra natureza e muito menos grave; sem data de assinatura o card se recusa a julgar.
  · **A vigência AVANÇA.** O terceiro termo se afere contra a vigência que os dois primeiros
    deixaram, não contra a original — comparar tudo com a data inicial acusaria como retroativo
    todo contrato longo e prorrogado regularmente.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores import REGISTRO

X8 = REGISTRO["X8"]


def _ctx(**kw):
    base = {"processo": "P-1", "vigencia_fim": "2024-12-31", "aditivos": []}
    base.update(kw)
    return base


# ───────────────────────── honestidade ────────────────────────────────────────────────────────

def test_sem_vigencia_e_nao_avaliavel():
    r = X8.avaliar(_ctx(vigencia_fim=None, aditivos=[{"data_assinatura": "2025-02-01"}]))
    assert r.status == "nao_avaliavel" and r.score == 0.0


def test_so_data_de_publicacao_nao_serve_e_o_card_diz_por_que():
    r = X8.avaliar(_ctx(aditivos=[{"data_publicacao": "2025-03-01"}]))
    assert r.status == "nao_avaliavel"
    assert "publicar tarde" in r.motivo_refutacao
    assert r.valores["so_publicacao"] == 1


def test_sem_aditivos_e_nao_avaliavel():
    assert X8.avaliar(_ctx()).status == "nao_avaliavel"


# ───────────────────────── T1 · retroativo ────────────────────────────────────────────────────

def test_termo_dentro_da_vigencia_e_descartado():
    r = X8.avaliar(_ctx(aditivos=[{"data_assinatura": "2024-11-30",
                                   "vigencia_fim": "2025-12-31"}]))
    assert r.status == "descartado" and r.score == 0.0


@pytest.mark.parametrize("assinatura,esperado", [
    ("2025-01-20", 0.6),    # 20 dias  → medio
    ("2025-03-01", 0.85),   # 60 dias  → forte
    ("2025-09-01", 1.0),    # 244 dias → critico
])
def test_gravidade_cresce_com_o_atraso(assinatura, esperado):
    r = X8.avaliar(_ctx(aditivos=[{"data_assinatura": assinatura}]))
    assert r.status == "confirmado" and r.score == pytest.approx(esperado)


def test_a_vigencia_AVANCA_a_cada_prorrogacao():
    """Sem isso, todo contrato longo e regularmente prorrogado viraria achado."""
    r = X8.avaliar(_ctx(aditivos=[
        {"numero_termo": "1", "data_assinatura": "2024-12-01", "vigencia_fim": "2025-12-31"},
        {"numero_termo": "2", "data_assinatura": "2025-12-01", "vigencia_fim": "2026-12-31"},
    ]))
    assert r.status == "descartado", f"prorrogações regulares acusadas: {r.valores}"


def test_termo_apos_vigencia_JA_prorrogada_e_critico():
    """Deixar expirar um prazo que já havia sido estendido é o caso mais grave da faixa."""
    r = X8.avaliar(_ctx(aditivos=[
        {"numero_termo": "1", "data_assinatura": "2024-12-01", "vigencia_fim": "2025-06-30"},
        {"numero_termo": "2", "data_assinatura": "2025-07-10"},
    ]))
    assert r.score == pytest.approx(1.0)
    assert r.valores["retroativos"][0]["ja_prorrogado"] is True


def test_data_em_formato_brasileiro_tambem_e_lida():
    r = X8.avaliar(_ctx(vigencia_fim="31/12/2024", aditivos=[{"data_assinatura": "01/03/2025"}]))
    assert r.status == "confirmado"


# ───────────────────────── T2 · reiteração ────────────────────────────────────────────────────

def test_dois_termos_retroativos_agravam():
    r = X8.avaliar(_ctx(aditivos=[
        {"numero_termo": "1", "data_assinatura": "2025-01-10"},
        {"numero_termo": "2", "data_assinatura": "2025-01-20"},
    ]))
    assert r.valores["n_retroativos"] == 2
    assert any("REITERAÇÃO" in e["trecho"] for e in r.evidencia)
    assert r.score > 0.6, "o agravamento por reiteração não subiu o nível"


# ───────────────────────── T3 · vácuo pago ────────────────────────────────────────────────────

def test_pagamento_no_periodo_descoberto_e_critico():
    r = X8.avaliar(_ctx(
        aditivos=[{"numero_termo": "1", "data_assinatura": "2025-03-01"}],
        pagamentos=[{"data": "2025-01-15", "valor": 250_000.0}]))
    assert r.score == pytest.approx(1.0)
    assert r.valores["pagamentos_no_vacuo"]
    assert any("VÁCUO PAGO" in e["trecho"] for e in r.evidencia)


def test_valor_do_vacuo_sai_no_padrao_brasileiro():
    r = X8.avaliar(_ctx(
        aditivos=[{"data_assinatura": "2025-03-01"}],
        pagamentos=[{"data": "2025-01-15", "valor": 1_234_567.89}]))
    trechos = " ".join(e["trecho"] for e in r.evidencia)
    assert "1.234.567,89" in trechos


def test_pagamento_fora_do_vacuo_nao_conta():
    r = X8.avaliar(_ctx(
        aditivos=[{"data_assinatura": "2025-03-01"}],
        pagamentos=[{"data": "2024-06-01", "valor": 100.0}]))
    assert "pagamentos_no_vacuo" not in r.valores


# ───────────────────────── contrato de saída ──────────────────────────────────────────────────

def test_explicacao_inocente_separa_falha_de_instrucao_de_contratacao_irregular():
    r = X8.avaliar(_ctx(aditivos=[{"data_assinatura": "2025-03-01"}]))
    assert "falha de instrução" in r.explicacao_inocente
    assert "data do PEDIDO" in r.explicacao_inocente


def test_evidencia_tem_hash_e_fonte():
    r = X8.avaliar(_ctx(aditivos=[{"data_assinatura": "2025-03-01"}]))
    for e in r.evidencia:
        assert e["hash"] and e["fonte"] and e["capturado_em"]
