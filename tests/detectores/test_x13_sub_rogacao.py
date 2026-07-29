# -*- coding: utf-8 -*-
"""X13 — e a distinção que é toda a dificuldade: nem toda mudança societária é sub-rogação.

  · **Cessão do contrato** e **subcontratação total** transferem a execução a quem não venceu a
    licitação. É o que a lei veda (art. 137, §1º; art. 122).
  · **Fusão, cisão e incorporação** são sucessão empresarial ADMITIDA (art. 137, §2º, III).
    Tratá-las como vício produziria achado contra reorganização lícita.
  · **Troca de sócios não é sub-rogação** — a pessoa jurídica contratada é a mesma. O que informa
    é o MOMENTO: controle vendido logo depois de a empresa passar a receber volume relevante do
    erário. E isso é indício de apuração, nunca violação objetiva.
"""
from __future__ import annotations

from compliance_agent.detectores.x13_sub_rogacao import X13SubRogacao

D = X13SubRogacao()


def _ctx(**kw):
    base = {"processo": "P1", "contratado_cnpj": "11111111000191",
            "data_inicio_contrato": "2024-01-10"}
    base.update(kw)
    return base


# ─────────────────── o que a lei VEDA ─────────────────────────────────────────────────────────

def test_cessao_do_contrato_e_critico_e_objetivo():
    r = D.avaliar(_ctx(cessao_contratual=True))
    assert r.status == "confirmado" and r.score == 1.0
    assert r.valores["teste_objetivo"] == "violado"
    assert "art. 137" in r.evidencia[0]


def test_subcontratacao_TOTAL_sem_previsao_e_critico():
    r = D.avaliar(_ctx(subcontratacao={"fracao": 1.0, "prevista_no_edital": False}))
    assert r.score == 1.0 and "Subcontratação total" in r.evidencia[0]


def test_subcontratacao_da_parcela_PRINCIPAL_e_critico():
    r = D.avaliar(_ctx(subcontratacao={"fracao": 0.4, "prevista_no_edital": False,
                                       "parcela_principal": True}))
    assert r.score == 1.0 and "parcela PRINCIPAL" in r.evidencia[0]


def test_subcontratacao_parcial_sem_previsao_fica_em_medio():
    r = D.avaliar(_ctx(subcontratacao={"fracao": 0.2, "prevista_no_edital": False}))
    assert r.score == 0.6 and r.valores["teste_objetivo"] == "nao_aferivel"


def test_subcontratacao_PREVISTA_no_edital_nao_e_achado():
    r = D.avaliar(_ctx(subcontratacao={"fracao": 0.9, "prevista_no_edital": True},
                       alteracoes_controle=[]))
    assert r.status == "descartado"


# ─────────────────── o que a lei ADMITE ───────────────────────────────────────────────────────

def test_fusao_e_sucessao_admitida_e_nao_vicio():
    r = D.avaliar(_ctx(alteracoes_controle=[
        {"data": "2024-03-01", "fracao_transferida": 1.0, "tipo": "fusao",
         "habilitacao_mantida": True}], recebido_ate_alteracao=50_000_000.0))
    assert r.status == "descartado" and "art. 137, §2º, III" in r.motivo_refutacao


def test_incorporacao_com_habilitacao_NAO_mantida_recebe_o_alerta():
    r = D.avaliar(_ctx(alteracoes_controle=[
        {"data": "2024-03-01", "fracao_transferida": 1.0, "tipo": "incorporacao",
         "habilitacao_mantida": False}]))
    assert r.status == "descartado" and "habilitação NÃO mantida" in r.motivo_refutacao


def test_troca_de_socios_abaixo_do_controle_nao_e_achado():
    r = D.avaliar(_ctx(alteracoes_controle=[{"data": "2024-03-01", "fracao_transferida": 0.3}]))
    assert r.status == "descartado"


# ─────────────────── troca de controle: o momento é o argumento ───────────────────────────────

def test_controle_vendido_na_janela_com_receita_alta_e_FORTE():
    r = D.avaliar(_ctx(alteracoes_controle=[{"data": "2024-06-01", "fracao_transferida": 0.8}],
                       recebido_ate_alteracao=5_000_000.0))
    assert r.status == "confirmado" and r.score == 0.85
    assert "venda de contrato" in r.evidencia[0]


def test_forte_ainda_assim_NAO_e_teste_objetivo():
    """Troca de sócios nunca é violação de teto — a pessoa jurídica é a mesma."""
    r = D.avaliar(_ctx(alteracoes_controle=[{"data": "2024-06-01", "fracao_transferida": 0.8}],
                       recebido_ate_alteracao=5_000_000.0))
    assert r.valores["teste_objetivo"] == "nao_aferivel"
    assert "NÃO é sub-rogação" in r.evidencia[0]


def test_fora_da_janela_cai_para_medio_e_diz_por_que():
    r = D.avaliar(_ctx(alteracoes_controle=[{"data": "2026-06-01", "fracao_transferida": 0.8}],
                       recebido_ate_alteracao=5_000_000.0))
    assert r.score == 0.6 and "fora da janela" in r.evidencia[0]


def test_receita_baixa_cai_para_medio_e_diz_por_que():
    r = D.avaliar(_ctx(alteracoes_controle=[{"data": "2024-06-01", "fracao_transferida": 0.8}],
                       recebido_ate_alteracao=1_000.0))
    assert r.score == 0.6 and "piso de relevância" in r.evidencia[0]


def test_sem_data_de_inicio_do_contrato_a_janela_nao_e_presumida():
    ctx = _ctx(alteracoes_controle=[{"data": "2024-06-01", "fracao_transferida": 0.8}],
               recebido_ate_alteracao=5_000_000.0)
    ctx.pop("data_inicio_contrato")
    r = D.avaliar(ctx)
    assert r.score == 0.6 and "não há data de início" in r.evidencia[0]


def test_a_maior_transferencia_manda_quando_ha_varias():
    r = D.avaliar(_ctx(alteracoes_controle=[
        {"data": "2024-06-01", "fracao_transferida": 0.6},
        {"data": "2024-07-01", "fracao_transferida": 0.9}],
        recebido_ate_alteracao=5_000_000.0))
    assert r.valores["fracao_transferida"] == 0.9


# ─────────────────── honestidade ──────────────────────────────────────────────────────────────

def test_sem_nenhum_dado_e_nao_avaliavel_nunca_limpo():
    r = D.avaliar({"processo": "P1"})
    assert r.status == "nao_avaliavel" and "INDISPONÍVEL ≠ 0" in r.motivo_refutacao


def test_fracao_ilegivel_nao_quebra():
    r = D.avaliar(_ctx(alteracoes_controle=[{"data": "2024-06-01",
                                             "fracao_transferida": "metade"}]))
    assert r.status == "descartado"


def test_cessao_tem_precedencia_sobre_troca_de_controle():
    """O caso grave manda: cessão é vedação; troca de sócios é indício."""
    r = D.avaliar(_ctx(cessao_contratual=True,
                       alteracoes_controle=[{"data": "2024-06-01", "fracao_transferida": 0.9}]))
    assert r.score == 1.0 and "Cessão" in r.evidencia[0]
