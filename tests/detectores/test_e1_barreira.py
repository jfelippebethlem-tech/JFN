# -*- coding: utf-8 -*-
"""Rede de proteção do detector E1 — barreira de entrada na qualificação (art. 67/69).

Duas réguas com teto LEGAL explícito, que é o que torna o achado defensável em peça:
· atestado acima de 50% do quantitativo licitado contraria a Súmula TCU 263; acima de 100% é
  violação objetiva;
· capital social ou patrimônio líquido acima de 10% do valor estimado estoura o teto do
  art. 69 §3º.

O guard estrutural: baseline de "exigência sob medida" exige n≥3 análogos. Com um ou dois
editais de comparação não se afirma praxe — e o detector declara isso em vez de fingir base.

Sem rede, sem banco, sem LLM.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.e1_barreira import E1Barreira

_P = {"processo": "SEI-TESTE/000015/2026"}


def _atestado(qexig: float) -> dict:
    return {"tipo": "atestado", "exigencia": "atestado de capacidade técnica",
            "quantitativo_exigido": qexig}


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_sem_secao_de_habilitacao_e_nao_avaliavel():
    res = E1Barreira().avaliar({**_P})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_sem_nenhuma_base_objetiva_e_nao_avaliavel():
    """Exigências sem valor estimado, sem quantitativo e sem análogos suficientes: nada a medir."""
    res = E1Barreira().avaliar({**_P, "exigencias_habilitacao": [_atestado(100)]})
    assert res.status == "nao_avaliavel"
    assert "nenhuma base" in res.motivo_refutacao


# ───────────────────────────── atestado × quantitativo ────────────────────────────────────────

def test_atestado_acima_de_100_por_cento_e_violacao_objetiva():
    res = E1Barreira().avaliar({**_P, "exigencias_habilitacao": [_atestado(1200)],
                                "quantitativos": 1000})
    assert res.score >= ANCORAS["critico"] or res.score == pytest.approx(1.0)
    assert "violação objetiva" in res.motivo_refutacao


def test_atestado_acima_de_50_por_cento_contraria_a_sumula_263():
    res = E1Barreira().avaliar({**_P, "exigencias_habilitacao": [_atestado(700)],
                                "quantitativos": 1000})
    assert res.score >= ANCORAS["forte"]
    assert "263" in res.motivo_refutacao


def test_atestado_dentro_do_limite_nao_pontua():
    res = E1Barreira().avaliar({**_P, "exigencias_habilitacao": [_atestado(400)],
                                "quantitativos": 1000})
    assert res.score == 0.0
    assert res.status == "descartado"
    assert res.explicacao_inocente


def test_sem_quantitativo_licitado_a_regra_do_atestado_nao_roda():
    """Sem o denominador não há razão — e inventar um produziria percentual falso."""
    res = E1Barreira().avaliar({**_P, "exigencias_habilitacao": [_atestado(700)],
                                "valor_estimado": 1_000_000.0})
    assert res.valores["quantitativo_licitado"] is None
    assert res.score == 0.0


# ───────────────────────────── capital / patrimônio líquido ───────────────────────────────────

def test_capital_acima_de_10_por_cento_estoura_o_teto_do_art_69():
    exig = [{"tipo": "capital", "exigencia": "capital social mínimo", "valor": 200_000.0}]
    res = E1Barreira().avaliar({**_P, "exigencias_habilitacao": exig,
                                "valor_estimado": 1_000_000.0})
    assert res.score >= ANCORAS["forte"]
    assert "69" in res.motivo_refutacao


def test_capital_dentro_do_teto_legal_nao_pontua():
    exig = [{"tipo": "capital", "exigencia": "capital social mínimo", "valor": 80_000.0}]
    res = E1Barreira().avaliar({**_P, "exigencias_habilitacao": exig,
                                "valor_estimado": 1_000_000.0})
    assert res.score == 0.0


def test_patrimonio_liquido_e_reconhecido_pelo_texto():
    exig = [{"exigencia": "patrimônio líquido mínimo de", "valor": 300_000.0}]
    res = E1Barreira().avaliar({**_P, "exigencias_habilitacao": exig,
                                "valor_estimado": 1_000_000.0})
    assert res.score >= ANCORAS["forte"]


# ───────────────────────────── baseline de análogos ───────────────────────────────────────────

def test_baseline_com_menos_de_tres_analogos_e_declarado_insuficiente():
    """Praxe do setor não se afirma com dois editais. O detector diz que não avaliou."""
    exig = [{"exigencia": "certificação ISO 9001 específica"}]
    res = E1Barreira().avaliar({**_P, "exigencias_habilitacao": exig,
                                "valor_estimado": 1_000_000.0,
                                "editais_analogos": [{"exigencias_habilitacao": []},
                                                     {"exigencias_habilitacao": []}]})
    assert "sob_medida_nao_avaliavel" in res.valores
    assert "< 3" in res.valores["sob_medida_nao_avaliavel"]


def test_exigencia_ausente_nos_analogos_e_candidata_a_sob_medida():
    exig = [{"exigencia": "certificação XPTO específica"}]
    analogos = [{"exigencias_habilitacao": [{"exigencia": "regularidade fiscal"}]} for _ in range(4)]
    res = E1Barreira().avaliar({**_P, "exigencias_habilitacao": exig,
                                "valor_estimado": 1_000_000.0, "editais_analogos": analogos})
    assert res.score >= ANCORAS["medio"]
    assert res.valores["exigencias_sob_medida"]


# ───────────────────────────── corroboração pelo resultado ────────────────────────────────────

def test_poucos_licitantes_corrobora_a_barreira():
    base = E1Barreira().avaliar({**_P, "exigencias_habilitacao": [_atestado(700)],
                                 "quantitativos": 1000})
    corrob = E1Barreira().avaliar({**_P, "exigencias_habilitacao": [_atestado(700)],
                                   "quantitativos": 1000,
                                   "resultado": {"licitantes": 1, "inabilitados": 3}})
    assert corrob.score >= base.score
    assert corrob.valores["resultado_inabilitados"] == 3


def test_poucos_licitantes_sozinho_nao_cria_achado():
    """Mercado pequeno não é barreira. O resultado agrava o que já é indício."""
    res = E1Barreira().avaliar({**_P, "exigencias_habilitacao": [_atestado(200)],
                                "quantitativos": 1000, "resultado": {"licitantes": 1}})
    assert res.score == 0.0


def test_schema_de_saida_conforme_spec():
    d = E1Barreira().avaliar({**_P, "exigencias_habilitacao": [_atestado(700)],
                              "quantitativos": 1000}).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "E1"
    assert d["status"] in STATUS_VALIDOS
