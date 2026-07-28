# -*- coding: utf-8 -*-
"""O mapa do `base.py` não pode mentir sobre o que existe.

Medido em 2026-07-28: o mapa declarava **9 cards como "⬜ a construir"** quando eles estavam no
REGISTRO e funcionando (P5, E2, E3, E4, E5, J5, X2, X4, X5), e **omitia outros 6** que também
existiam (C, C7, E7, E8, J8, P6). Um mapa errado custa caro dos dois lados: manda reconstruir o
que já existe, e esconde o que poderia estar sendo usado.

Este teste trava as duas direções da mentira.
"""
from __future__ import annotations

import pathlib
import re

from compliance_agent.detectores import REGISTRO

_MAPA = pathlib.Path("compliance_agent/detectores/base.py").read_text()


def _linhas_do_mapa() -> dict[str, str]:
    """id → linha do mapa, para os ids que aparecem como entrada de card."""
    out = {}
    for m in re.finditer(r"^  ([A-Z]\d?)\s{2,}(.+)$", _MAPA, re.M):
        out.setdefault(m.group(1), m.group(2))
    return out


def test_todo_detector_do_registro_aparece_no_mapa():
    faltando = sorted(set(REGISTRO) - set(_linhas_do_mapa()))
    assert not faltando, f"detectores no REGISTRO e ausentes do mapa: {faltando}"


def test_nenhum_detector_existente_e_declarado_a_construir():
    linhas = _linhas_do_mapa()
    mentira = sorted(did for did in REGISTRO if "⬜" in linhas.get(did, ""))
    assert not mentira, f"existem no REGISTRO mas o mapa diz '⬜ a construir': {mentira}"
