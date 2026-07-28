# -*- coding: utf-8 -*-
"""Rede de proteção do detector X6 — entrega fantasma / atesto de fachada.

Pagou-se sem comprovante de entrega? O fornecedor tem estrutura para o volume contratado? As
medições são todas idênticas? Três perguntas objetivas antes de qualquer juízo subjetivo.

O guard que separa este detector de um acusador automático: **objeto de valor fixo mensal**
(locação, assinatura, licença) tem medições idênticas por natureza — é legítimo. Sem ele, todo
contrato de aluguel viraria achado.

Sem rede, sem banco.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.x6_entrega_fantasma import X6EntregaFantasma, _is_valor_fixo

_P = {"processo": "SEI-TESTE/000020/2026"}


def _pag(valor: float, nf: bool | None = True, receb: bool | None = True) -> dict:
    d = {"valor": valor, "data": "2026-03-10"}
    if nf is not None:
        d["tem_nf"] = nf
    if receb is not None:
        d["tem_recebimento"] = receb
    return d


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_sem_pagamentos_e_sem_atestos_e_nao_avaliavel():
    res = X6EntregaFantasma().avaliar({**_P})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_campo_ausente_nao_e_o_mesmo_que_false():
    """Não saber se houve NF ≠ saber que não houve. O detector distingue os dois."""
    res = X6EntregaFantasma().avaliar({**_P, "pagamentos": [{"valor": 1000.0}]})
    assert res.valores["triade_avaliavel"] is False
    assert res.valores["pagamentos_sem_nf"] == 0
    assert res.score == 0.0


# ───────────────────────────── tríade documental ──────────────────────────────────────────────

def test_pagamento_sem_nota_fiscal_e_forte():
    res = X6EntregaFantasma().avaliar({**_P, "pagamentos": [_pag(50_000.0, nf=False)]})
    assert res.score >= ANCORAS["forte"]
    assert res.valores["pagamentos_sem_nf"] == 1
    assert res.evidencia


def test_pagamento_sem_registro_de_recebimento_e_forte():
    res = X6EntregaFantasma().avaliar({**_P, "pagamentos": [_pag(50_000.0, receb=False)]})
    assert res.score >= ANCORAS["forte"]
    assert res.valores["pagamentos_sem_recebimento"] == 1


def test_triade_completa_nao_pontua():
    res = X6EntregaFantasma().avaliar({**_P, "pagamentos": [_pag(50_000.0)]})
    assert res.valores["triade_avaliavel"] is True
    assert res.score == 0.0


# ───────────────────────────── capacidade do fornecedor ───────────────────────────────────────

def test_volume_incompativel_com_fornecedor_sem_estrutura():
    """Empresa sem funcionário nem frota executando volume relevante — cruza com o C2."""
    res = X6EntregaFantasma().avaliar({**_P, "pagamentos": [_pag(50_000.0)],
                                       "volume_contratado": 5000,
                                       "capacidade_fornecedor": {"funcionarios": 0, "frota": 0}})
    assert res.score >= ANCORAS["forte"]
    assert "CAPACIDADE" in res.motivo_refutacao


def test_fornecedor_com_estrutura_nao_pontua():
    res = X6EntregaFantasma().avaliar({**_P, "pagamentos": [_pag(50_000.0)],
                                       "volume_contratado": 5000,
                                       "capacidade_fornecedor": {"funcionarios": 40, "frota": 12}})
    assert res.score == 0.0


def test_sem_dado_de_capacidade_a_regra_nao_roda():
    res = X6EntregaFantasma().avaliar({**_P, "pagamentos": [_pag(50_000.0)],
                                       "volume_contratado": 5000})
    assert res.score == 0.0


# ───────────────────────────── cadência das medições ──────────────────────────────────────────

@pytest.mark.parametrize("tipo,fixo", [
    ("locação de veículos", True),
    ("assinatura de software", True),
    ("obra de reforma", False),
    (None, False),
])
def test_reconhece_objeto_de_valor_fixo(tipo, fixo):
    assert _is_valor_fixo(tipo) is fixo


def test_medicoes_identicas_em_objeto_variavel_sao_indicio_fraco():
    res = X6EntregaFantasma().avaliar({**_P, "pagamentos": [_pag(1000.0)],
                                       "medicoes": [{"valor": 1000.0} for _ in range(4)],
                                       "tipo_objeto": "obra de reforma"})
    assert res.valores["medicoes_identicas"] is True
    assert res.score == pytest.approx(ANCORAS["fraco"])


def test_medicoes_identicas_em_valor_fixo_sao_legitimas():
    """Aluguel é o mesmo valor todo mês. Acusar aqui seria não entender o objeto."""
    res = X6EntregaFantasma().avaliar({**_P, "pagamentos": [_pag(1000.0)],
                                       "medicoes": [{"valor": 1000.0} for _ in range(4)],
                                       "tipo_objeto": "locação de veículos"})
    assert res.score == 0.0
    assert "legítima" in res.motivo_refutacao


def test_menos_de_tres_medicoes_nao_caracteriza_cadencia():
    res = X6EntregaFantasma().avaliar({**_P, "pagamentos": [_pag(1000.0)],
                                       "medicoes": [{"valor": 1000.0}, {"valor": 1000.0}],
                                       "tipo_objeto": "obra"})
    assert res.valores["medicoes_identicas"] is False


def test_medicoes_variadas_nao_pontuam():
    res = X6EntregaFantasma().avaliar({**_P, "pagamentos": [_pag(1000.0)],
                                       "medicoes": [{"valor": v} for v in (900.0, 1100.0, 1000.0)],
                                       "tipo_objeto": "obra"})
    assert res.valores["medicoes_identicas"] is False
    assert res.score == 0.0


def test_schema_de_saida_conforme_spec():
    d = X6EntregaFantasma().avaliar({**_P, "pagamentos": [_pag(50_000.0, nf=False)]}).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "X6"
    assert d["status"] in STATUS_VALIDOS
