# -*- coding: utf-8 -*-
"""Dossiê compartilhado do contrato — o BARRAMENTO anti-monólito.

Junta num único dict, com proveniência por campo, tudo que os pensamentos
precisam: o contrato, os aditivos (PNCP termos), os pagamentos (pcrj_despesa),
os itens/preços (PNCP) e os sinais do fornecedor (emenda/sanção/rede). Cada
"cabeça" lê daqui e escreve seus achados; nenhuma refaz coleta.
"""
from __future__ import annotations

import sqlite3

import asyncio


def _tem_tabela(con, nome: str) -> bool:
    return bool(con.execute("select 1 from sqlite_master where type='table' and name=?",
                            (nome,)).fetchone())


def _sinais_fornecedor(con, doc: str, com_rede: bool) -> list[str]:
    sinais = []
    if not doc:
        return sinais
    # A VIGÊNCIA VIAJA COM O SINAL. "fornecedor sancionado (CEIS)" é atemporal, e o dossiê é sobre
    # um contrato que TEM data: sem o período, quem lê não distingue a sanção que já valia à época
    # daquela que começou anos depois. Medido em 2026-08-10 no detector irmão das emendas: 87,9%
    # dos casamentos favorecido×sanção eram de sanção POSTERIOR ao ato.
    if _tem_tabela(con, "sancoes_federais"):
        _s = con.execute("select cadastro, data_inicio, data_fim from sancoes_federais "
                         "where cpf_cnpj=? order by data_inicio desc limit 1", (doc,)).fetchone()
        if _s:
            _ini = str(_s[1] or "")[:10] or "início n/d"
            _fim = str(_s[2] or "")[:10] or "sem fim declarado"
            sinais.append(f"fornecedor sancionado ({_s[0] or 'CEIS'}, {_ini} a {_fim} — "
                          "conferir se vigia na data do contrato)")
    if _tem_tabela(con, "emenda_favorecidos") and con.execute(
            "select 1 from emenda_favorecidos where documento_favorecido=? limit 1", (doc,)).fetchone():
        sinais.append("favorecido de emenda federal")
    if com_rede and _tem_tabela(con, "rede_socios_fornecedores"):
        try:
            if con.execute("select 1 from rede_socios_fornecedores where raiz=? limit 1",
                           (doc[:8],)).fetchone():
                sinais.append("sócio liga ≥2 fornecedores (rede)")
        except sqlite3.Error:
            pass
    return sinais


def _itens_default(nc: str) -> list[dict]:
    from compliance_agent.collectors import pncp
    try:
        return asyncio.run(pncp.buscar_itens(nc))
    except Exception:
        return []


def montar_dossie(con, numero_controle_pncp: str, com_rede: bool = True, itens_fn=None) -> dict:
    """Retorna o dossiê {contrato, aditivos, pagamentos, itens, sinais_fornecedor, proveniencia}."""
    itens_fn = itens_fn or _itens_default
    c = con.execute(
        """select numero_controle_pncp, ano, orgao_cnpj, orgao_nome, fornecedor_documento,
                  fornecedor_nome, tipo, objeto, valor_inicial, valor_global, data_assinatura,
                  vigencia_ini, vigencia_fim, num_aditivos
           from pcrj_contratos where numero_controle_pncp=?""", (numero_controle_pncp,)).fetchone()
    contrato = dict(c) if c else {"numero_controle_pncp": numero_controle_pncp}
    aditivos = [dict(r) for r in con.execute(
        """select sequencial_termo, numero_termo, objeto, valor_acrescido, valor_global,
                  prazo_aditado_dias, vigencia_fim, qualif_acrescimo, qualif_vigencia, fundamento_legal
           from contrato_aditivo where numero_controle_pncp=? order by sequencial_termo""",
        (numero_controle_pncp,)).fetchall()]
    doc = contrato.get("fornecedor_documento")
    pag = con.execute(
        """select coalesce(sum(empenhado),0), coalesce(sum(liquidado),0), coalesce(sum(pago),0)
           from pcrj_despesa where credor_documento=?""", (doc,)).fetchone() if doc else None
    pagamentos = {"empenhado": pag[0], "liquidado": pag[1], "pago": pag[2]} if pag else {}
    return {
        "contrato": contrato,
        "aditivos": aditivos,
        "pagamentos": pagamentos,
        "itens": itens_fn(numero_controle_pncp),
        "sinais_fornecedor": _sinais_fornecedor(con, doc, com_rede),
        "proveniencia": {
            "contrato": "pcrj_contratos (PNCP)", "aditivos": "PNCP termos api/pncp/v1",
            "pagamentos": "pcrj_despesa (ContasRio)", "itens": "PNCP itens",
            "sinais_fornecedor": "CEIS/emendas/rede local"},
    }
