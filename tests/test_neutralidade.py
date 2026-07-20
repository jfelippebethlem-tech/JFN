# -*- coding: utf-8 -*-
"""Gate de neutralidade — nenhum entregável ao dono pode carregar sigla/nome interno.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_neutralidade.py -q
"""
from __future__ import annotations

import pytest

from compliance_agent.reporting.neutralidade import (
    garantir_neutro,
    neutralizar_ctx,
    termos_proibidos,
)


def test_detecta_termos_internos():
    assert termos_proibidos("relatório do JFN via Yoda") == ["jfn", "yoda"]
    assert termos_proibidos("parecer Lex") == ["Lex"]


def test_nao_casa_substring_legitima():
    # "lex" dentro de Alexandre/Complexo/flexível NÃO pode disparar
    assert termos_proibidos("Alexandre da Silva, no Complexo do Alemão, contrato flexível") == []
    assert termos_proibidos("ITERJ") == ["iterj"]  # mas a sigla isolada, sim


def test_texto_limpo_passa():
    assert termos_proibidos("Relatório de Controle Externo — Estado do Rio de Janeiro") == []


def test_garantir_neutro_levanta_no_sujo():
    with pytest.raises(AssertionError):
        garantir_neutro("documento gerado pelo JFN")
    garantir_neutro("documento de controle externo")  # limpo: não levanta


def test_neutralizar_ctx_zera_analista_interno():
    ctx = {"analista": "Equipe JFN", "titulo": "X"}
    out = neutralizar_ctx(ctx)
    assert "jfn" not in out["analista"].lower()
    assert out["titulo"] == "X"  # não mexe no resto


def test_goldens_lex_sao_neutros():
    # o parecer jurídico vai ao dono junto do pacote — não pode carregar nome interno (Lex/paths)
    from pathlib import Path
    raiz = Path(__file__).resolve().parent / "golden"
    for nome in ("lex_parecer_fornecedor.md", "lex_parecer_orgao.md"):
        f = raiz / nome
        if f.exists():
            bad = termos_proibidos(f.read_text())
            assert bad == [], f"{nome} vazou termo interno: {bad}"


def test_dossie_mestre_ctx_e_neutro():
    # o produto que o dono recebe não pode conter termo interno em nenhuma seção
    import sqlite3

    from compliance_agent.editais.db import init_schema
    from compliance_agent.reporting.dossie_mestre import montar_ctx_orgao
    from compliance_agent.reporting.render_html import render_html

    con = sqlite3.connect(":memory:")
    init_schema(con)
    con.execute("CREATE TABLE pncp_resultado (certame TEXT, orgao_cnpj TEXT, orgao_nome TEXT, uf TEXT, "
                "unidade_nome TEXT, ordem_classificacao INTEGER)")
    con.close()
    # ctx puro (sem DB real) — basta checar que o texto-molde é neutro
    ctx = montar_ctx_orgao("42498600000171", db_path=":memory:")
    html = render_html(ctx)
    assert termos_proibidos(html) == [], f"dossiê mestre vazou termo interno: {termos_proibidos(html)}"
