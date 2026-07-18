# -*- coding: utf-8 -*-
"""Backfill de unidadeOrgao em pncp_resultado.

O coletor original só gravava orgaoEntidade.razaoSocial — para contratação ESTADUAL isso é o ente
("Estado do Rio de Janeiro"), colapsando todos os órgãos do Estado num só no conluio do painel.
O órgão comprador REAL vem em unidadeOrgao (codigoUnidade/nomeUnidade).

Duas estratégias, ambas idempotentes (só linha com unidade_codigo IS NULL):
  • ``bulk``     — repagina /contratacoes/publicacao mês a mês (50 certames/request; barato,
                   mas a API de consulta bulk fica instável em certas janelas — 500/timeout).
  • ``certame``  — GET /orgaos/{cnpj}/compras/{ano}/{seq} por certame pendente (1 request cada;
                   lento porém resiliente). Ordena pelos ENTES com mais certames (Estado do RJ
                   primeiro — é onde o colapso dói no painel). É o modo default.

Uso: .venv/bin/python -m tools.pncp_backfill_unidade [certame|bulk] [limite]
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys

import httpx

from compliance_agent.collectors.pncp import CONSULTA_BASE, _parse_id_pncp
from compliance_agent.collectors.pncp_resultados import (
    MODALIDADES_PADRAO, PNCP_PRIMEIRO_ANO_DENSO, _consulta, _meses, init_schema,
)

_H = {"User-Agent": "JFN-Compliance/2.0"}


def _aplicar(con, certame: str, uni: dict) -> int:
    # unidade ausente no payload → sentinela '' (≠ NULL): sai da fila de pendências em vez de
    # ser re-consultado para sempre; _chave_orgao trata '' como "sem unidade" (chave = CNPJ puro)
    cod, nome = uni.get("codigoUnidade") or "", uni.get("nomeUnidade")
    cur = con.execute("UPDATE pncp_resultado SET unidade_codigo=?, unidade_nome=? "
                      "WHERE certame=? AND unidade_codigo IS NULL", (cod, nome, certame))
    return cur.rowcount


async def backfill_certame(con, limite: int = 0, pausa: float = 0.4) -> dict:
    """1 request por certame pendente — entes com mais certames primeiro."""
    init_schema(con)
    # prioridade: entes cujo nome COLAPSA órgãos no painel (Estado do RJ, Município do Rio)
    # primeiro; depois os demais entes com mais certames
    rows = con.execute(
        "SELECT p.certame, MIN(CASE WHEN p.orgao_nome LIKE 'ESTADO DO RIO%' THEN 0 "
        "  WHEN p.orgao_nome LIKE 'MUNICIPIO DE RIO DE JANEIRO%' THEN 1 ELSE 2 END) pri, "
        "  MAX(o.n) peso FROM pncp_resultado p "
        "JOIN (SELECT orgao_cnpj, COUNT(DISTINCT certame) n FROM pncp_resultado "
        "      GROUP BY orgao_cnpj) o ON o.orgao_cnpj = p.orgao_cnpj "
        "WHERE p.unidade_codigo IS NULL GROUP BY p.certame ORDER BY pri, peso DESC").fetchall()
    pend = [r[0] for r in rows]
    if limite:
        pend = pend[:limite]
    tot = {"pendentes": len(pend), "ok": 0, "linhas": 0, "falhas": 0}
    async with httpx.AsyncClient(timeout=45) as client:  # a API de consulta chega a 15-25s/request
        for i, certame in enumerate(pend, 1):
            pr = _parse_id_pncp(certame)
            if not pr:
                tot["falhas"] += 1
                continue
            cnpj, ano, seq = pr
            j, sumido = None, False
            for tent in range(3):
                try:
                    r = await client.get(f"{CONSULTA_BASE}/orgaos/{cnpj}/compras/{ano}/{seq}", headers=_H)
                except httpx.HTTPError:
                    await asyncio.sleep(2 * (tent + 1))
                    continue
                if r.status_code == 200:
                    j = r.json()
                    break
                if r.status_code in (204, 404):
                    sumido = True  # permanente: sem sentinela, seria re-consultado p/ sempre
                    break
                if r.status_code == 429:
                    await asyncio.sleep(5 * (tent + 1))
                    continue
                break
            if j or sumido:
                n = _aplicar(con, certame, (j or {}).get("unidadeOrgao") or {})
                tot["ok"] += 1
                tot["linhas"] += n
            else:
                tot["falhas"] += 1  # erro transitório: fica NULL e volta no próximo round
            if i % 10 == 0:
                con.commit()  # commit curto: a API anda a segundos/request — não perder progresso
                print(f"[backfill] {i}/{len(pend)} ok={tot['ok']} falhas={tot['falhas']}", flush=True)
            await asyncio.sleep(pausa)
    con.commit()
    return tot


async def backfill_bulk(con, uf: str = "RJ", ano_ini: int = PNCP_PRIMEIRO_ANO_DENSO, mes_ini: int = 1,
                        max_paginas: int = 40, pausa: float = 0.4) -> dict:
    """Repagina /contratacoes/publicacao — barato quando a API bulk está saudável."""
    from datetime import date
    hoje = date.today()
    init_schema(con)
    pend = {r[0] for r in con.execute(
        "SELECT DISTINCT substr(data_pub,1,7) FROM pncp_resultado "
        "WHERE unidade_codigo IS NULL AND data_pub >= '2020'")}
    tot = {"meses": 0, "paginas": 0, "atualizados": 0, "pulados": 0}
    async with httpx.AsyncClient(timeout=40) as client:
        for d_ini, d_fim in _meses(ano_ini, mes_ini, hoje.year, hoje.month):
            mes = f"{d_ini[:4]}-{d_ini[4:6]}"
            if mes not in pend:
                tot["pulados"] += 1
                continue
            tot["meses"] += 1
            for mod in MODALIDADES_PADRAO:
                for pagina in range(1, max_paginas + 1):
                    j = await _consulta(client, "/contratacoes/publicacao", {
                        "dataInicial": d_ini, "dataFinal": d_fim, "uf": uf.upper(),
                        "codigoModalidadeContratacao": mod, "pagina": pagina, "tamanhoPagina": 50})
                    data = (j or {}).get("data") or []
                    if not data:
                        break
                    tot["paginas"] += 1
                    for ct in data:
                        idp = ct.get("numeroControlePNCP")
                        if idp:
                            tot["atualizados"] += _aplicar(con, idp, ct.get("unidadeOrgao") or {})
                    con.commit()
                    if pagina >= ((j or {}).get("totalPaginas") or 1):
                        break
                    await asyncio.sleep(pausa)
                await asyncio.sleep(pausa)
            print(f"[backfill] {mes}: atualizados={tot['atualizados']}", flush=True)
    con.commit()
    return tot


if __name__ == "__main__":
    args = sys.argv[1:]
    modo = args[0] if args and args[0] in ("bulk", "certame") else "certame"
    limite = int(args[1]) if len(args) > 1 and args[1].isdigit() else 0
    # compliance.db compartilhado com o jfn.service vivo — busy_timeout alto absorve contenção
    con = sqlite3.connect("data/compliance.db", timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    try:
        if modo == "bulk":
            r = asyncio.run(backfill_bulk(con))
        else:
            r = asyncio.run(backfill_certame(con, limite=limite))
    finally:
        con.close()
    print(r, flush=True)
