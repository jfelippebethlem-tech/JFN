# -*- coding: utf-8 -*-
"""Consolidação matriz+filiais por raiz no /relatorio (uma só PJ — CC 44/985/1.142; STJ REsp 1.286.122).

Integração contra compliance.db; pulam se a base não tiver o dado necessário (robustez)."""
from __future__ import annotations

import re
from collections import defaultdict

import pytest


def _raiz_multi():
    """Acha uma raiz (8 díg.) com >1 estabelecimento nas OBs; devolve (raiz, {cnpjs}) ou None."""
    from compliance_agent.reporting.inteligencia import _DB
    import sqlite3
    if not _DB.exists():
        return None
    con = sqlite3.connect(str(_DB))
    try:
        rows = con.execute("SELECT DISTINCT favorecido_cpf FROM ordens_bancarias "
                           "WHERE favorecido_cpf IS NOT NULL").fetchall()
    finally:
        con.close()
    re_d = re.compile(r"\D")
    raiz_estabs = defaultdict(set)
    for (c,) in rows:
        d = re_d.sub("", str(c or ""))
        if len(d) == 14:
            raiz_estabs[d[:8]].add(d)
    for r, v in raiz_estabs.items():
        if len(v) > 1:
            return r, v
    return None


def test_consolidacao_total_igual_soma_dos_estabelecimentos():
    from compliance_agent.reporting.inteligencia import consultar_pagamentos
    rm = _raiz_multi()
    if not rm:
        pytest.skip("sem raiz multi-estabelecimento na base")
    raiz, cnpjs = rm
    p = consultar_pagamentos(next(iter(cnpjs)))
    assert p["raiz"] == raiz
    assert p["n_estabelecimentos"] >= 2
    soma = round(sum(e["total"] for e in p["por_estabelecimento"]), 2)
    assert abs(p["total_geral"] - soma) < 0.01, (p["total_geral"], soma)


def test_qualquer_estabelecimento_da_raiz_da_o_mesmo_consolidado():
    """Pedir por qualquer filial OU pela matriz consolida o MESMO grupo (a PJ é una)."""
    from compliance_agent.reporting.inteligencia import consultar_pagamentos
    rm = _raiz_multi()
    if not rm:
        pytest.skip("sem raiz multi-estabelecimento na base")
    _, cnpjs = rm
    cnpjs = sorted(cnpjs)
    totais = {consultar_pagamentos(c)["total_geral"] for c in cnpjs[:3]}
    assert len(totais) == 1, f"consolidado divergiu por estabelecimento: {totais}"


def test_buscar_candidatos_colapsa_por_raiz():
    """Nenhum par de candidatos compartilha a mesma raiz (matriz+filiais = 1 candidato)."""
    from compliance_agent.reporting.inteligencia import buscar_candidatos, so_digitos
    cands = buscar_candidatos("ltda")
    if len(cands) < 2:
        pytest.skip("base sem candidatos suficientes p/ o termo")
    raizes = [so_digitos(c["cnpj"])[:8] for c in cands]
    assert len(raizes) == len(set(raizes)), "candidatos com raiz duplicada (não colapsou)"
