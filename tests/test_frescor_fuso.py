# -*- coding: utf-8 -*-
"""Frescor de fonte não pode ser negativo — cortar o fuso fazia UTC parecer futuro.

Defeito visto na tela (31/07/2026), no cartão "FONTES DE DADOS · FRESCOR AO VIVO" do painel:

    PCRJ · comissionados×candidatos    -1d

Idade negativa é impossível. A conta era `(_dt.now() - _dt.fromisoformat(str(ultimo)[:19])).days`:
`_dt.now()` é hora LOCAL ingênua (UTC−3) e o `[:19]` **decepa o offset** de quem grava em UTC
(`2026-07-31T09:43:22.390048+00:00` vira `2026-07-31T09:43:22`, lido como se fosse local). Resultado:
toda fonte gravada em UTC aparece 3 h mais nova do que é — e, na janela das primeiras horas do dia,
a subtração fica negativa e `timedelta.days` arredonda para −1.

Não é cosmético: este cartão é o que avisa quando uma coleta morre (lição do SIAFE 16-17/07, em que
o MFA quebrou a captura e nada alertava). Uma fonte que se mostra mais fresca do que é atrasa
exatamente o alarme que o cartão existe para dar.
"""
from __future__ import annotations

import datetime as dt

import pytest

from rotas.investigacao import _idade_dias

UTC = dt.timezone.utc
BRT = dt.timezone(dt.timedelta(hours=-3))
AGORA = dt.datetime(2026, 7, 31, 9, 20, 0, tzinfo=BRT)  # 12:20 UTC


def test_utc_recente_nunca_vira_negativo():
    """O caso exato da tela: gravado em UTC há poucas horas, mostrado como −1d."""
    assert _idade_dias("2026-07-31T09:43:22.390048+00:00", AGORA) == 0


def test_utc_e_local_do_mesmo_instante_dao_a_mesma_idade():
    """O fuso do registro não pode mudar a idade — 3 h de erro sistemático vinha daqui."""
    mesmo_instante_utc = "2026-07-29T15:00:00+00:00"
    mesmo_instante_brt = "2026-07-29T12:00:00-03:00"
    assert _idade_dias(mesmo_instante_utc, AGORA) == _idade_dias(mesmo_instante_brt, AGORA)


def test_data_sem_fuso_continua_valendo_como_hora_local():
    """`MAX(competencia)||'-01'` e datas ISO cruas não têm fuso: seguem sendo hora da casa."""
    assert _idade_dias("2026-06-01", AGORA) == 60


def test_idade_em_dias_inteiros_de_uma_fonte_parada():
    assert _idade_dias("2026-07-24", AGORA) == 7


@pytest.mark.parametrize("ruim", [None, "", "nao-e-data", "2026-13-45"])
def test_valor_impossivel_vira_none_e_nao_zero(ruim):
    """INDISPONÍVEL ≠ 0: sem data legível a idade é None, nunca 'fresquinho'."""
    assert _idade_dias(ruim, AGORA) is None


def test_relogio_adiantado_da_fonte_satura_em_zero():
    """Se o registro vier do futuro por desvio de relógio, o piso é 0 — negativo não existe."""
    assert _idade_dias("2026-08-02T00:00:00+00:00", AGORA) == 0
