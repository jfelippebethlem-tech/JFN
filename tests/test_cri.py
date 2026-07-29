# -*- coding: utf-8 -*-
"""CRI — o índice que compara ÓRGÃOS, e as duas maneiras de ele mentir.

O `indice_certame` da casa é rico e incomparável entre órgãos: quem tem edital capturado pontua
diferente de quem não tem, e a diferença mede a COLETA, não o risco. O CRI usa só bandeiras
computáveis do registro básico, e por isso responde à pergunta que o outro não responde: qual
secretaria merece auditoria temática?

As duas mentiras que estes testes impedem:

  1. **Bandeira indisponível tratada como zero.** Órgão sem dado ficaria "limpo" — o oposto do que
     um índice de risco deve fazer. Bandeira não aferível sai da conta E da normalização, e a
     `confianca` cai para dizer isso.
  2. **Licitante único sem olhar o mercado.** Um proponente em mercado naturalmente concentrado
     não é bandeira nenhuma; a normalização por mercado é o que separa monopólio de vício.
"""
from __future__ import annotations

import pytest

from compliance_agent.editais.cri import BANDEIRAS, agregar, calcular

_COMPLETO = {
    "n_proponentes": 5, "proponentes_medios_mercado": 6, "modalidade": "pregao",
    "contratacao_direta": False, "dias_publicidade": 15, "criterio_julgamento": "menor preço",
    "aviso_publicado": True, "dias_ate_decisao": 30,
    "valor": 100_000.0, "valor_mediano_objeto": 95_000.0,
}


# ───────────────────────── bandeiras ──────────────────────────────────────────────────────────

def test_certame_limpo_tem_cri_zero_com_confianca_cheia():
    r = calcular(_COMPLETO)
    assert r["cri"] == pytest.approx(0.0) and r["confianca"] == pytest.approx(1.0)


def test_licitante_unico_em_mercado_competitivo_acende():
    r = calcular({**_COMPLETO, "n_proponentes": 1})
    assert "licitante_unico" in r["acesas"] and r["cri"] > 0


def test_licitante_unico_em_mercado_CONCENTRADO_nao_acende():
    """Monopólio natural não é vício — a normalização por mercado é o que separa os dois."""
    r = calcular({**_COMPLETO, "n_proponentes": 1, "proponentes_medios_mercado": 1.2})
    assert "licitante_unico" in r["apagadas"]


def test_sem_o_mercado_a_bandeira_e_INDISPONIVEL_nao_apagada():
    """O PNCP típico só traz o vencedor — 1 fornecedor distinto não prova licitante único."""
    r = calcular({**_COMPLETO, "n_proponentes": 1, "proponentes_medios_mercado": None})
    assert "licitante_unico" in r["indisponiveis"]


def test_prazo_abaixo_do_minimo_legal_acende():
    assert "prazo_curto" in calcular({**_COMPLETO, "dias_publicidade": 3})["acesas"]


def test_contratacao_direta_acende():
    assert "contratacao_direta" in calcular({**_COMPLETO, "contratacao_direta": True})["acesas"]


def test_criterio_por_tecnica_acende():
    assert "criterio_subjetivo" in calcular(
        {**_COMPLETO, "criterio_julgamento": "técnica e preço"})["acesas"]


def test_decisao_anomala_conta_nas_DUAS_pontas():
    assert "decisao_anomala" in calcular({**_COMPLETO, "dias_ate_decisao": 0})["acesas"]
    assert "decisao_anomala" in calcular({**_COMPLETO, "dias_ate_decisao": 400})["acesas"]


def test_valor_atipico_conta_nas_duas_pontas():
    assert "valor_atipico" in calcular({**_COMPLETO, "valor": 400_000.0})["acesas"]
    assert "valor_atipico" in calcular({**_COMPLETO, "valor": 5_000.0})["acesas"]


def test_toda_bandeira_declara_fundamento():
    for b in BANDEIRAS.values():
        assert b.fundamento, f"{b.id} sem fundamento"


# ───────────────────────── indisponível ≠ zero ────────────────────────────────────────────────

def test_registro_vazio_nao_produz_cri_zero():
    """Órgão sem dado não pode aparecer como o mais limpo da fila."""
    r = calcular({})
    assert r["cri"] is None and r["confianca"] == pytest.approx(0.0)
    assert "não é zero" in r["motivo"]


def test_confianca_cai_com_bandeira_faltante():
    r = calcular({"n_proponentes": 1, "proponentes_medios_mercado": 6})
    assert r["cri"] == pytest.approx(100.0)
    assert r["confianca"] < 0.3, "CRI 100 com 1 bandeira medida precisa declarar baixa confiança"


def test_cri_normaliza_sobre_o_que_foi_AFERIVEL():
    """2 bandeiras medidas, 1 acesa → 50%, não 1/7."""
    r = calcular({"n_proponentes": 1, "proponentes_medios_mercado": 6, "dias_publicidade": 30})
    assert r["cri"] == pytest.approx(50.0)


def test_bandeira_que_quebra_vira_indisponivel_nao_acesa():
    r = calcular({**_COMPLETO, "dias_publicidade": "quinze"})
    assert "prazo_curto" in r["indisponiveis"]


# ───────────────────────── agregação por órgão ────────────────────────────────────────────────

def test_agregado_ordena_a_fila_e_lista_as_bandeiras_frequentes():
    regs = [{**_COMPLETO, "n_proponentes": 1} for _ in range(12)]
    r = agregar(regs)
    assert r["cri_medio"] > 0 and r["n"] == 12 and r["comparavel"] is True
    assert r["bandeiras_mais_frequentes"]["licitante_unico"] == 12


def test_amostra_pequena_nao_ordena_fila_contra_orgao_grande():
    r = agregar([{**_COMPLETO, "n_proponentes": 1} for _ in range(3)])
    assert r["comparavel"] is False and "amostra pequena" in r["motivo"]


def test_conjunto_sem_bandeira_aferivel_devolve_none():
    r = agregar([{}, {}])
    assert r["cri_medio"] is None and r["comparavel"] is False


def test_resultado_traz_a_ressalva_de_priorizacao():
    assert "PRIORIZAÇÃO" in calcular(_COMPLETO)["ressalva"]
