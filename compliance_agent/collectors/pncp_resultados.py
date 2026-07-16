# -*- coding: utf-8 -*-
"""pncp_resultados — coletor de RESULTADOS estruturados do PNCP (vencedor por item).

O endpoint `/orgaos/{cnpj}/compras/{ano}/{seq}/itens/{n}/resultados` publica o FORNECEDOR
HOMOLOGADO de cada item (niFornecedor, valorHomologado, ordemClassificacaoSrp=1). Ele NÃO
traz os perdedores (só o vencedor) — os perdedores/cover vêm do parser de ata
(`rodizio_grafo.extrair_participantes_ata`). Juntos: vencedor estruturado + perdedores do texto.

COBERTURA TEMPORAL (medida em 2026-07, RJ, pregão eletrônico, API de consulta):
  2021-2022 → 204 (sem dado); 2023 → esparso (dezenas); 2024 → denso (centenas/mês);
  2025+ → ~900/mês. A adesão obrigatória ao PNCP fechou em 2023-12-30 (fim da transição da
  Lei 8.666 → 14.133). Padrão: coletar de **2024-01** em diante; 2023 opcional (parcial).

LIMITE DE REQUISIÇÃO: janela de 1 ANO estoura 429. Varre-se MÊS A MÊS com pausa; 429 → backoff.
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
from datetime import date

import httpx

from compliance_agent.collectors.pncp import (
    CONSULTA_BASE, MODALIDADES_PADRAO, PNCP_BASE, _parse_id_pncp,
)

_H = {"User-Agent": "JFN-Compliance/2.0"}
# menor data com dado estruturado útil no PNCP (ver docstring — 2024 é o 1º ano denso).
PNCP_PRIMEIRO_ANO_DENSO = 2024


def init_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS pncp_resultado (
            certame       TEXT NOT NULL,          -- numeroControlePNCP
            orgao_cnpj    TEXT,
            orgao_nome    TEXT,
            uf            TEXT,
            municipio     TEXT,
            modalidade    INTEGER,
            objeto        TEXT,
            data_pub      TEXT,                   -- AAAA-MM-DD (publicação da contratação)
            item          INTEGER NOT NULL,
            fornecedor_cnpj TEXT,                 -- niFornecedor (vencedor homologado)
            fornecedor_nome TEXT,
            valor_homologado REAL,
            ordem_classificacao INTEGER,          -- 1 = vencedor
            porte_fornecedor INTEGER,
            coletado_em   TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (certame, item, fornecedor_cnpj)
        )""")
    con.execute("CREATE INDEX IF NOT EXISTS ix_pncpres_orgao ON pncp_resultado(orgao_cnpj)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_pncpres_forn ON pncp_resultado(fornecedor_cnpj)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_pncpres_data ON pncp_resultado(data_pub)")
    con.commit()


def _meses(ano_ini: int, mes_ini: int, ano_fim: int, mes_fim: int):
    a, m = ano_ini, mes_ini
    while (a, m) <= (ano_fim, mes_fim):
        d_ini = f"{a:04d}{m:02d}01"
        # último dia do mês (sem calendar p/ manter determinismo simples: usa 1º do mês seguinte -1)
        if m == 12:
            fa, fm = a + 1, 1
        else:
            fa, fm = a, m + 1
        d_fim = date(fa, fm, 1).toordinal() - 1
        yield d_ini, date.fromordinal(d_fim).strftime("%Y%m%d")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)


async def _consulta(client: httpx.AsyncClient, endpoint: str, params: dict) -> dict | None:
    """GET na API de consulta com backoff em 429 (limite de requisição)."""
    for tent in range(5):
        try:
            r = await client.get(f"{CONSULTA_BASE}{endpoint}", params=params, headers=_H)
        except httpx.HTTPError:
            await asyncio.sleep(2 * (tent + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 204:
            return None  # sem dado na janela (honesto: não é erro)
        if r.status_code == 429:
            await asyncio.sleep(5 * (tent + 1))  # backoff do rate-limit
            continue
        return None
    return None


async def _resultado_item(client: httpx.AsyncClient, cnpj: str, ano: str, seq: int, item: int) -> list[dict]:
    for tent in range(4):
        try:
            r = await client.get(f"{PNCP_BASE}/orgaos/{cnpj}/compras/{ano}/{seq}/itens/{item}/resultados",
                                 headers=_H)
        except httpx.HTTPError:
            await asyncio.sleep(1.5 * (tent + 1))
            continue
        if r.status_code == 200:
            return r.json() or []
        if r.status_code in (204, 404):
            return []
        if r.status_code == 429:
            await asyncio.sleep(4 * (tent + 1))
            continue
        return []
    return []


async def coletar_resultados(con, uf: str = "RJ", ano_ini: int = PNCP_PRIMEIRO_ANO_DENSO,
                             mes_ini: int = 1, ano_fim: int | None = None, mes_fim: int | None = None,
                             modalidades=None, max_paginas: int = 40, pausa: float = 0.3) -> dict:
    """Varre contratações publicadas (mês a mês) e grava o vencedor de cada item em pncp_resultado.

    Idempotente (PRIMARY KEY certame+item+fornecedor; usa INSERT OR IGNORE). Serial e educado com a
    API (pausa + backoff 429). Retorna {meses, certames, itens_com_resultado, gravados}."""
    init_schema(con)
    hoje = date.today()
    ano_fim = ano_fim or hoje.year
    mes_fim = mes_fim or hoje.month
    modalidades = modalidades or MODALIDADES_PADRAO
    tot = {"meses": 0, "certames": 0, "itens_com_resultado": 0, "gravados": 0}
    async with httpx.AsyncClient(timeout=40) as client:
        for d_ini, d_fim in _meses(ano_ini, mes_ini, ano_fim, mes_fim):
            tot["meses"] += 1
            for mod in modalidades:
                for pagina in range(1, max_paginas + 1):
                    j = await _consulta(client, "/contratacoes/publicacao", {
                        "dataInicial": d_ini, "dataFinal": d_fim, "uf": uf.upper(),
                        "codigoModalidadeContratacao": mod, "pagina": pagina, "tamanhoPagina": 50})
                    data = (j or {}).get("data") or []
                    if not data:
                        break
                    for ct in data:
                        n = await _gravar_certame(con, client, ct, tot)
                        tot["gravados"] += n
                        await asyncio.sleep(pausa)
                    con.commit()
                    if pagina >= ((j or {}).get("totalPaginas") or 1):
                        break
                    await asyncio.sleep(pausa)
    con.commit()
    return tot


async def _gravar_certame(con, client, ct: dict, tot: dict) -> int:
    idp = ct.get("numeroControlePNCP")
    pr = _parse_id_pncp(idp or "")
    if not pr:
        return 0
    cnpj, ano, seq = pr
    tot["certames"] += 1
    org = ct.get("orgaoEntidade") or {}
    uni = ct.get("unidadeOrgao") or {}
    meta = {
        "certame": idp, "orgao_cnpj": re.sub(r"\D", "", org.get("cnpj", "") or ""),
        "orgao_nome": org.get("razaoSocial"), "uf": uni.get("ufSigla"),
        "municipio": uni.get("municipioNome"), "modalidade": ct.get("modalidadeId"),
        "objeto": (ct.get("objetoCompra") or "")[:500],
        "data_pub": (ct.get("dataPublicacaoPncp") or ct.get("dataInclusao") or "")[:10],
    }
    itens = await _consulta_itens(client, cnpj, ano, seq)
    gravados = 0
    for it in itens:
        num = it.get("numeroItem")
        if num is None:
            continue
        res = await _resultado_item(client, cnpj, ano, seq, num)
        if res:
            tot["itens_com_resultado"] += 1
        for rr in res:
            forn = re.sub(r"\D", "", rr.get("niFornecedor", "") or "")
            if not forn:
                continue
            con.execute("""INSERT OR IGNORE INTO pncp_resultado
                (certame, orgao_cnpj, orgao_nome, uf, municipio, modalidade, objeto, data_pub,
                 item, fornecedor_cnpj, fornecedor_nome, valor_homologado, ordem_classificacao,
                 porte_fornecedor)
                VALUES (:certame,:orgao_cnpj,:orgao_nome,:uf,:municipio,:modalidade,:objeto,:data_pub,
                        :item,:forn,:nome,:valor,:ordem,:porte)""",
                        {**meta, "item": num, "forn": forn,
                         "nome": rr.get("nomeRazaoSocialFornecedor"),
                         "valor": rr.get("valorTotalHomologado"),
                         "ordem": rr.get("ordemClassificacaoSrp"),
                         "porte": rr.get("porteFornecedorId")})
            gravados += con.total_changes and 1 or 0
    return gravados


async def _consulta_itens(client, cnpj: str, ano: str, seq: int) -> list[dict]:
    for tent in range(4):
        try:
            r = await client.get(f"{PNCP_BASE}/orgaos/{cnpj}/compras/{ano}/{seq}/itens", headers=_H)
        except httpx.HTTPError:
            await asyncio.sleep(1.5 * (tent + 1))
            continue
        if r.status_code == 200:
            return r.json() or []
        if r.status_code in (204, 404):
            return []
        if r.status_code == 429:
            await asyncio.sleep(4 * (tent + 1))
            continue
        return []
    return []


def registros_vencedores(con, uf: str | None = "RJ") -> list[dict]:
    """Lê pncp_resultado e devolve UM registro por certame com seu(s) vencedor(es) — insumo do
    detector de rodízio de vencedores (rodizio_grafo.detectar_rodizio_vencedores)."""
    con.row_factory = sqlite3.Row
    q = ("SELECT certame, orgao_cnpj, orgao_nome, objeto, data_pub, "
         "fornecedor_cnpj, fornecedor_nome, SUM(valor_homologado) v "
         "FROM pncp_resultado WHERE ordem_classificacao=1 ")
    params: tuple = ()
    if uf:
        q += "AND uf=? "
        params = (uf,)
    q += "GROUP BY certame, fornecedor_cnpj"
    por_certame: dict[str, dict] = {}
    for r in con.execute(q, params):
        c = por_certame.setdefault(r["certame"], {
            "certame": r["certame"], "orgao": r["orgao_cnpj"], "orgao_nome": r["orgao_nome"],
            "objeto": r["objeto"], "data": r["data_pub"], "vencedores": []})
        c["vencedores"].append({"cnpj": r["fornecedor_cnpj"], "nome": r["fornecedor_nome"], "valor": r["v"]})
    return list(por_certame.values())


def conluio_do_orgao(nome_orgao: str, db_path: str = "data/compliance.db", min_certames: int = 3) -> dict:
    """Conluio (captura/rodízio de vencedores do PNCP) filtrado por NOME de órgão — insumo do /orgao.
    Match best-effort por LIKE no orgao_nome (o relatório identifica por UG/nome, o PNCP por CNPJ).
    Retorna {captura, rodizio_vencedores, n_certames} ou {n_certames:0} se não houver resultado."""
    import sqlite3 as _sq

    from compliance_agent.rodizio_grafo import detectar_rodizio_vencedores
    termo = re.sub(r"\s+", " ", (nome_orgao or "").strip()).upper()
    if len(termo) < 4:
        return {"captura": [], "rodizio_vencedores": [], "n_certames": 0}
    con = _sq.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = _sq.Row
    try:
        rows = con.execute(
            "SELECT certame, orgao_cnpj, orgao_nome, objeto, data_pub, fornecedor_cnpj, "
            "fornecedor_nome, SUM(valor_homologado) v FROM pncp_resultado "
            "WHERE ordem_classificacao=1 AND UPPER(orgao_nome) LIKE ? GROUP BY certame, fornecedor_cnpj",
            (f"%{termo}%",)).fetchall()
    finally:
        con.close()
    por: dict[str, dict] = {}
    for r in rows:
        c = por.setdefault(r["certame"], {"certame": r["certame"], "orgao": r["orgao_cnpj"],
                                          "orgao_nome": r["orgao_nome"], "objeto": r["objeto"],
                                          "data": r["data_pub"], "vencedores": []})
        c["vencedores"].append({"cnpj": r["fornecedor_cnpj"], "nome": r["fornecedor_nome"], "valor": r["v"]})
    regs = list(por.values())
    pad = detectar_rodizio_vencedores(regs, min_certames=min_certames)
    pad["n_certames"] = len(regs)
    return pad


def conluio_enriquecido(con, uf: str | None = "RJ", min_certames: int = 5) -> dict:
    """Roda detectar_rodizio_vencedores sobre os resultados do PNCP e DECORA com nome de fornecedor,
    nome de órgão e amostra de OBJETOS — pronto para o painel/relatório (user-friendly)."""
    from compliance_agent.rodizio_grafo import detectar_rodizio_vencedores
    regs = registros_vencedores(con, uf=uf)
    pad = detectar_rodizio_vencedores(regs, min_certames=min_certames)
    # índices auxiliares: cnpj→nome, orgao→nome, orgao→objetos, (orgao,cnpj)→objetos
    nome_forn: dict[str, str] = {}
    nome_org: dict[str, str] = {}
    obj_org: dict[str, list] = {}
    obj_org_forn: dict[tuple, list] = {}
    for r in regs:
        org = re.sub(r"\D", "", r.get("orgao") or "")
        if org and r.get("orgao_nome"):
            nome_org[org] = r["orgao_nome"]
        obj = (r.get("objeto") or "").strip()
        if org and obj:
            obj_org.setdefault(org, [])
            if obj not in obj_org[org]:
                obj_org[org].append(obj)
        for v in r.get("vencedores") or []:
            c = re.sub(r"\D", "", v.get("cnpj") or "")
            if c and v.get("nome"):
                nome_forn[c] = v["nome"]
            if c and org and obj:
                obj_org_forn.setdefault((org, c), [])
                if obj not in obj_org_forn[(org, c)]:
                    obj_org_forn[(org, c)].append(obj)

    def _fmt_cnpj(c: str) -> str:
        c = (c or "").zfill(14)
        return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}" if len(c) == 14 else c

    for cap in pad.get("captura", []):
        org, fc = cap["orgao"], cap["vencedor"]
        cap["orgao_nome"] = nome_org.get(org, "—")
        cap["orgao_cnpj_fmt"] = _fmt_cnpj(org)
        cap["nome"] = nome_forn.get(fc, cap.get("nome") or "—")
        cap["fornecedor_cnpj_fmt"] = _fmt_cnpj(fc)
        cap["objetos"] = (obj_org_forn.get((org, fc)) or obj_org.get(org) or [])[:5]
    for rod in pad.get("rodizio_vencedores", []):
        org = rod["orgao"]
        rod["orgao_nome"] = nome_org.get(org, "—")
        rod["orgao_cnpj_fmt"] = _fmt_cnpj(org)
        rod["membros_nome"] = [{"cnpj": _fmt_cnpj(c), "nome": nome_forn.get(c, "—"),
                                "vitorias": rod["reparticao"].get(c, 0)} for c in rod["grupo"]]
        rod["objetos"] = (obj_org.get(org) or [])[:5]
    pad["cobertura"] = {"certames_com_resultado": len(regs), "orgaos": pad.get("n_orgaos", 0)}
    return pad


if __name__ == "__main__":
    import json
    import sys
    args = sys.argv[1:]
    # timeout alto: compliance.db é compartilhado com o jfn.service vivo — numa carga de horas o
    # busy_timeout de 5s (default) estouraria em contenção de escrita. WAL + 60s absorve.
    con = sqlite3.connect("data/compliance.db", timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    if "--incremental" in args:
        # timer: só os 2 meses mais recentes (idempotente — reprocessa o que fechou/foi homologado agora)
        hoje = date.today()
        ano_ant, mes_ant = (hoje.year - 1, 12) if hoje.month == 1 else (hoje.year, hoje.month - 1)
        r = asyncio.run(coletar_resultados(con, ano_ini=ano_ant, mes_ini=mes_ant,
                                           ano_fim=hoje.year, mes_fim=hoje.month))
    else:
        # backfill: [ano_ini] [mes_ini] (default 2024-01 → hoje)
        ai = int(args[0]) if len(args) > 0 and args[0].isdigit() else PNCP_PRIMEIRO_ANO_DENSO
        mi = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
        r = asyncio.run(coletar_resultados(con, ano_ini=ai, mes_ini=mi))
    con.close()
    print(json.dumps(r, ensure_ascii=False), flush=True)
