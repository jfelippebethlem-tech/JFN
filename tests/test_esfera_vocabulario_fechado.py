# -*- coding: utf-8 -*-
"""Rótulo de esfera fora do vocabulário não pode virar lista vazia.

`esfera="estadual"` — o português natural — não existe: o vocabulário é `estado`. O filtro casava
zero certames, o set vazio filtrava tudo, e a varredura devolvia **0 achados sobre uma base com
260** (medido em 2026-08-10). Zero por rótulo errado é NÃO MEDIDO, e ler isso como "nada a apurar"
é a afirmação mais perigosa que um motor de fiscalização pode fazer.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.collectors.pncp_resultados import ESFERAS, certames_da_esfera
from compliance_agent.cruzamentos_intel import aditivos_estouro


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c


def test_vocabulario_tem_estado_e_nao_estadual():
    assert "estado" in ESFERAS and "estadual" not in ESFERAS


@pytest.mark.parametrize("ruim", ["estadual", "municipal", "ESTADO", "uniao"])
def test_rotulo_invalido_levanta_em_vez_de_devolver_vazio(con, ruim):
    with pytest.raises(ValueError, match="não existe"):
        certames_da_esfera(con, ruim)


def test_sem_filtro_continua_sendo_None(con):
    assert certames_da_esfera(con, "todas") is None
    assert certames_da_esfera(con, "") is None
    assert certames_da_esfera(con, None) is None


def test_aditivos_estouro_recusa_esfera_invalida(tmp_path):
    p = tmp_path / "v.db"
    sqlite3.connect(p).close()
    r = aditivos_estouro(db_path=str(p), esfera="estadual")
    assert r["ok"] is False and "não existe" in r["erro"]
