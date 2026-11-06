# -*- coding: utf-8 -*-
"""Uma leitura que passa do prazo é cancelada e vira LeituraExcedeuPrazo — o laço segue (10/09/2026: as fases
pais/recaptura morriam com SIGKILL sem completar um único processo porque uma leitura passava de 20 min)."""
from __future__ import annotations

import asyncio

import pytest

from tools.sei_sweep import LeituraExcedeuPrazo, _com_prazo


async def _lenta():
    await asyncio.sleep(5)
    return {"documentos": [1]}


async def _rapida():
    return {"documentos": [1, 2]}


def test_leitura_lenta_e_abandonada_no_prazo():
    with pytest.raises(LeituraExcedeuPrazo, match="SEI-1: leitura passou de 0s"):
        asyncio.run(_com_prazo(_lenta(), "SEI-1", prazo_s=0.05))


def test_leitura_rapida_passa_e_prazo_zero_desliga():
    assert asyncio.run(_com_prazo(_rapida(), "SEI-2", prazo_s=1))["documentos"] == [1, 2]
    assert asyncio.run(_com_prazo(_rapida(), "SEI-3", prazo_s=0))["documentos"] == [1, 2]
