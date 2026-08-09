# -*- coding: utf-8 -*-
"""O guard de fatia capada tem de disparar no platô MEDIDO, não no teto teórico.

`coletar_por_ug_grande` divide a UG em fatias por prefixo de número e subdivide a fatia que
"estourou". O limiar era `n >= 990`, escolhido pelo teto nominal de 1.000 registros por consulta
do SIAFE. Medido em 2026-08-09 sobre **5.893 fatias** já coletadas (checkpoints de junho):

    fatias com n >= 990 .......... 0      ← o guard NUNCA disparou
    fatias com n == 989 ......... 48      ← platô
    fatias com n == 984 ......... 28      ← platô
    fatias entre 950 e 989 ...... 124     ← aceitas como COMPLETAS

A colheita satura abaixo do teto teórico (a tabela é virtualizada e o scroller entrega ~989 antes
de parar), então nenhuma fatia truncada foi subdividida: 124 fatias entraram no banco como se
fossem o universo. Somado à PK que apagava OB de outra UG, é a explicação de por que a UG 180100
tem 1.000 linhas onde o log diz 10.046.

Subdividir uma fatia que por acaso tenha 980-989 registros VERDADEIROS custa consultas a mais e
nada de errado — os sub-prefixos devolvem as mesmas linhas e a ingestão é idempotente. Aceitar uma
fatia truncada custa dado que ninguém sabe que falta. O limiar erra para o lado barato.
"""
from __future__ import annotations

import pytest

from compliance_agent.siafe_ob_orcamentaria import _fatia_capou


@pytest.mark.parametrize("n", [989, 984, 986, 980, 1000])
def test_plato_medido_conta_como_capada(n):
    assert _fatia_capou(n, "2023OB1", 2023), f"fatia de {n} linhas passou como completa"


@pytest.mark.parametrize("n", [0, 100, 643, 979])
def test_fatia_pequena_e_completa(n):
    assert not _fatia_capou(n, "2023OB1", 2023)


def test_profundidade_maxima_para_de_subdividir():
    """Prefixo já longo não subdivide para sempre — o SIAFE tem 8 dígitos depois de 'OB'."""
    fundo = "2023OB" + "1" * 8
    assert not _fatia_capou(1000, fundo, 2023), "subdivisão infinita: o prefixo já esgotou"
