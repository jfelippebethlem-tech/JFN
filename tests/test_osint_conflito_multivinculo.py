# -*- coding: utf-8 -*-
"""Conflito pelo processo tem de olhar TODOS os vínculos da pessoa na folha.

Medido em 2026-08-08: PAULO MARTINS SOARES é TEN-CEL PM (o vínculo que `semente()` elege —
"cargo mais forte vence") E médico CLT da FUNDAÇÃO SAÚDE. Os 12 autos da LIFECARE (R$ 20,6 mi,
sócio desde 09/2022) correm NA FSERJ — mas o conflito era testado só contra o vínculo eleito
(PM), e o achado entrava na fila com peso 1 ("agente no QSA") em vez de 3 ("autos no PRÓPRIO
órgão"). A cura consulta `registros_folha` por nome na hora do cotejo.
"""
from __future__ import annotations

import sqlite3

from tools.agente_publico_reverso import conflito_de_orgao, norm


def _conflito_multivinculo(orgaos: set[str], ug: str) -> str:
    """Espelha o laço de `osint_x_processos.correlacionar` — primeiro vínculo que casa vence."""
    for org in sorted(orgaos):
        c = conflito_de_orgao(org, {ug})
        if c:
            return c
    return ""


def test_segundo_vinculo_acende_o_conflito():
    ug_dos_autos = "FUNDACAO SAUDE DO ESTADO DO RIO DE JANEIRO"
    so_pm = {"SECRETARIA DE ESTADO DE POLICIA MILITAR"}
    ambos = so_pm | {"FUNDACAO SAUDE DO ESTADO DO RIO DE JANEIRO"}
    assert not _conflito_multivinculo(so_pm, ug_dos_autos), (
        "PM sozinho não pode casar com a FSERJ — senão o teste não prova nada")
    assert _conflito_multivinculo(ambos, ug_dos_autos), (
        "o vínculo CLT/FSERJ não acendeu o conflito — multivínculo continua cego")


def test_correlacionar_consulta_todos_os_vinculos_da_folha():
    """O laço real usa `orgaos_por_nome` construído de registros_folha (DISTINCT nome × órgão)."""
    import inspect

    from tools import osint_x_processos as OXP

    fonte = inspect.getsource(OXP.correlacionar)
    assert "orgaos_por_nome" in fonte and "registros_folha" in fonte, (
        "correlacionar voltou a testar conflito só contra o vínculo eleito pela fila curada")


def test_norm_estavel_para_o_casamento():
    assert norm("PAULO MARTINS SOARES") == norm("Paulo Martins Soares")
