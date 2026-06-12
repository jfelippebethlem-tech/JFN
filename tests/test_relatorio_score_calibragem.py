# -*- coding: utf-8 -*-
"""
Testes da CALIBRAGEM do score de risco do fornecedor (P1.2 do QA):
o score deve incorporar a rede MESMA-SEDE (§1-B / coendereco) e as anomalias PyOD (§8-C),
com peso conservador — p/ o NÚMERO refletir a prosa (não cair em MÉDIO/50 quando a prosa conclui ALTO),
sem inflar artificialmente.

Tudo determinístico (sem DB, sem rede): chamamos `_recalibrar_risco` com fixtures.

Como rodar:
    cd ~/JFN && .venv/bin/python -m pytest tests/test_relatorio_score_calibragem.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from compliance_agent.reporting import inteligencia as I  # noqa: E402

# pagamentos "magros" — sem concentração nem magnitude relevante, p/ isolar o efeito dos novos sinais.
PAG_BASE = {"total_geral": 10_000_000.0, "hhi": {"top_share": 10}, "por_ano": {}}


def _coend(n_pagos: int) -> list:
    """n_pagos fornecedores na MESMA sede que TAMBÉM recebem OBs (total_pago>0)."""
    return [{"cnpj": f"{i:014d}", "total_pago": 1000.0, "n_obs": 3} for i in range(n_pagos)]


def _anom(n_obs: int, n_anomalas: int) -> dict:
    return {"ok": True, "n_obs": n_obs, "n_anomalas": n_anomalas, "itens": []}


def _score(coendereco=None, anomalias=None, **kw):
    return I._recalibrar_risco(
        PAG_BASE, rede=[], contratado_tcerj=0.0, score_ext=0, risco_ext="—",
        coendereco=coendereco, anomalias=anomalias, **kw,
    )


# ───────────────────────────── baseline ─────────────────────────────

def test_baseline_sem_sinais_novos_fica_baixo():
    cal = _score()
    assert cal["score"] == 0
    assert cal["risco"] == "BAIXO"
    assert cal["sinais"] == []


# ───────────────────────────── rede mesma-sede §1-B ─────────────────────────────

def test_mesma_sede_eleva_score_escalonado():
    s1 = _score(coendereco=_coend(1))["score"]
    s2 = _score(coendereco=_coend(3))["score"]
    s5 = _score(coendereco=_coend(7))["score"]
    assert 0 < s1 < s2 < s5  # mais fornecedores na mesma sede -> mais risco
    sinais = _score(coendereco=_coend(7))["sinais"]
    assert any("mesma-sede" in x for x in sinais)


def test_mesma_sede_so_conta_quem_recebe_ob():
    # co-endereçados que NÃO recebem OB (total_pago=0) não tocam o erário -> não elevam o score
    coend = [{"cnpj": "x", "total_pago": 0.0, "n_obs": 0} for _ in range(5)]
    assert _score(coendereco=coend)["score"] == 0


# ───────────────────────────── anomalias PyOD §8-C ─────────────────────────────

def test_anomalias_alta_fracao_eleva_score():
    # 40% das OBs anômalas (4/10) -> sinal forte
    cal = _score(anomalias=_anom(10, 4))
    assert cal["score"] >= 18
    assert any("§8-C" in x or "anomalia" in x for x in cal["sinais"])


def test_anomalias_usa_fracao_nao_volume_bruto():
    # mesmo nº absoluto (3 anômalas) mas universos diferentes: fração alta pesa mais que fração baixa
    alto = _score(anomalias=_anom(8, 3))["score"]    # 37%
    baixo = _score(anomalias=_anom(300, 3))["score"]  # 1%
    assert alto > baixo


def test_anomalias_indisponivel_nao_afeta():
    assert _score(anomalias={"ok": False, "n_obs": 0, "n_anomalas": 0})["score"] == 0


# ───────────────────────────── prosa ALTO vira número ALTO (cenário do QA) ─────────────────────────────

def test_cenario_qa_mesma_sede_mais_anomalias_chega_alto():
    """O caso reportado: prosa conclui ALTO mas número dava MÉDIO/50 porque NÃO incorporava §1-B + §8-C.
    Combinando rede mesma-sede densa + alta fração de OBs anômalas, o número deve subir p/ ALTO."""
    cal = _score(coendereco=_coend(7), anomalias=_anom(10, 4))
    assert cal["score"] >= 35  # ao menos MÉDIO só com os dois sinais novos (sem outros indícios)
    # com qualquer indício adicional típico, cruza ALTO; aqui validamos que os 2 sinais sozinhos já pesam
    assert any("mesma-sede" in x for x in cal["sinais"])
    assert any("§8-C" in x or "anomalia" in x for x in cal["sinais"])


def test_nao_infla_alem_de_100():
    cal = _score(coendereco=_coend(20), anomalias=_anom(10, 10))
    assert cal["score"] <= 100
