# -*- coding: utf-8 -*-
"""Campo declarado na PEÇA tem de existir na EVIDÊNCIA do detector.

O quadro de evidência da perícia é montado por um mapa `(chave, rótulo, tipo)`. Chave que não
existe no achado não quebra nada: renderiza vazio, e o leitor conclui que não havia dado. Foi o que
acontecia com `d8_credor_recem_aberto.valor` — a chave real é `total`, e o VALOR RECEBIDO, que dá
tamanho ao achado de credor recém-aberto, nunca aparecia na peça.

Este teste é de CONTRATO entre as duas pontas: cada chave declarada precisa ser produzida por
algum detector. Nasceu ao levar aos entregáveis as correções de vigência de 2026-08-10 — e a
primeira coisa que achou foi um defeito anterior.
"""
from __future__ import annotations

import sqlite3

import pytest

import compliance_agent.reporting.pericia_fisc_rico as PECA
from compliance_agent.emendas.pericia import _DETECTORES as DET_EMENDAS
from compliance_agent.pcrj.pericia_gastos import _DETECTORES as DET_PCRJ


def _mapa_da_peca() -> dict:
    for v in vars(PECA).values():
        if isinstance(v, dict) and "d3_favorecido_sancionado" in v:
            return v
    pytest.skip("mapa de detectores da peça não encontrado")
    return {}


def _chaves_reais() -> dict[str, set[str]]:
    """Chaves de evidência que cada detector realmente produz, medidas no acervo."""
    con = sqlite3.connect("file:data/compliance.db?mode=ro", uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    saida: dict[str, set[str]] = {}
    try:
        for dets in (DET_PCRJ, DET_EMENDAS):
            for fn in dets.values():
                try:
                    res = fn(con)
                except (sqlite3.Error, KeyError, TypeError, ValueError, OSError):
                    continue           # detector sem fonte não invalida os outros
                for a in res[:200]:
                    saida.setdefault(a["detector"], set()).update(a["evidencias"])
    finally:
        con.close()
    return saida


def test_toda_chave_da_peca_existe_na_evidencia():
    reais = _chaves_reais()
    if not reais:
        pytest.skip("sem acervo local para medir (roda na VM, não no runner)")
    faltando = []
    for det, cfg in _mapa_da_peca().items():
        if det not in reais:
            continue                       # detector sem achado hoje — não julga
        for chave, rotulo, _tipo in cfg.get("evid", ()):
            if chave not in reais[det]:
                faltando.append(f"{det}.{chave} ({rotulo})")
    assert not faltando, (
        "campo declarado na peça que o detector NÃO produz — renderiza vazio e o leitor lê como "
        "ausência de dado:\n  " + "\n  ".join(faltando))
