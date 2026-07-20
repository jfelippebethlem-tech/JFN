# -*- coding: utf-8 -*-
"""Dossiê COMPLETO de fornecedor — montar_ctx_completo agrega 360 + capítulos novos, neutro.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_dossie_completo.py -q
"""
from __future__ import annotations

import asyncio

from compliance_agent import dossie as D
from compliance_agent.reporting.neutralidade import termos_proibidos


def test_ctx_completo_agrega_capitulos_e_e_neutro(monkeypatch):
    # dossie() mockado (sem rede): d mínimo honesto
    async def _fake_dossie(cnpj, gerar_pdf=True):
        return {"ok": True, "alvo": cnpj, "cadastro": {"razao_social": "EMPRESA TESTE LTDA"},
                "ob": {"total_ob": 0.0, "n_ob": 0, "ugs": []}, "score": {}, "red_flags": [],
                "red_flags_estruturais": []}
    monkeypatch.setattr(D, "dossie", _fake_dossie)
    # sem DB real, o veredito de fachada entra INDISPONÍVEL; capítulos de cláusula degradam honesto
    ctx = asyncio.run(D.montar_ctx_completo("58229293000163"))
    assert ctx["ok"] and ctx["titulo"] == "Dossiê Completo — Fornecedor"
    titulos = [s["titulo"] for s in ctx["secoes"]]
    assert "Veredito de empresa-fachada" in titulos
    from compliance_agent.reporting.render_html import render_html
    assert termos_proibidos(render_html(ctx)) == []


def test_ctx_completo_cnpj_invalido():
    async def _fake(cnpj, gerar_pdf=True):
        return {"ok": False, "erro": "informe um CNPJ (14 dígitos)"}
    import compliance_agent.dossie as D2
    orig = D2.dossie
    D2.dossie = _fake
    try:
        ctx = asyncio.run(D2.montar_ctx_completo("123"))
        assert ctx["ok"] is False
    finally:
        D2.dossie = orig
