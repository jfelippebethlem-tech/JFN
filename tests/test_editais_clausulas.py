# -*- coding: utf-8 -*-
"""T3 — extração e rotulagem de cláusulas por eixo (Lei 14.133 arts. 62-70)."""
from compliance_agent.editais import clausulas


def test_rotular_eixo_por_tipo():
    assert clausulas.rotular_eixo({"tipo": "atestado"})[0] == "habilitacao_tecnica"
    assert clausulas.rotular_eixo({"tipo": "capital_social"})[0] == "habilitacao_econ_financeira"
    assert clausulas.rotular_eixo({"tipo": "patrimonio_liquido"})[0] == "habilitacao_econ_financeira"


def test_rotular_eixo_por_categoria():
    assert clausulas.rotular_eixo({"categoria": "tecnica"})[0] == "habilitacao_tecnica"
    assert clausulas.rotular_eixo({"categoria": "economica"})[0] == "habilitacao_econ_financeira"
    assert clausulas.rotular_eixo({"categoria": "geografico"})[0] == "condicao_participacao"
    assert clausulas.rotular_eixo({"categoria": "marca"})[0] == "condicao_participacao"


def test_assinatura_agrupa_por_faixa():
    a = clausulas.assinatura({"tipo": "atestado", "quantitativo_exigido_pct": 60})
    b = clausulas.assinatura({"tipo": "atestado", "quantitativo_exigido_pct": 65})
    c = clausulas.assinatura({"tipo": "atestado", "quantitativo_exigido_pct": 30})
    assert a == b        # mesma faixa (>50%)
    assert a != c        # faixa diferente (<=50%)
