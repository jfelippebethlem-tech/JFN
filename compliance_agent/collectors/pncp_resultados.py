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
            unidade_codigo TEXT,                  -- unidadeOrgao.codigoUnidade (órgão REAL do ente)
            unidade_nome  TEXT,                   -- unidadeOrgao.nomeUnidade
            item_descricao TEXT,                  -- descrição do ITEM (ex.: "Ventilador") — base do sobrepreço
            unidade_medida TEXT,                  -- unidadeMedida (ex.: "Unidade", "Caixa")
            valor_unitario REAL,                  -- valorUnitarioHomologado (preço unitário pago)
            quantidade    REAL,                   -- quantidadeHomologada
            coletado_em   TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (certame, item, fornecedor_cnpj)
        )""")
    # migração: bases antigas não têm unidadeOrgao (orgao_nome = razão social do ENTE —
    # p/ contratação estadual é sempre "Estado do Rio de Janeiro", colapsando os órgãos),
    # nem os campos de item (descrição/preço unitário) usados na detecção de sobrepreço
    cols = {r[1] for r in con.execute("PRAGMA table_info(pncp_resultado)")}
    for c in ("unidade_codigo", "unidade_nome", "item_descricao", "unidade_medida"):
        if c not in cols:
            con.execute(f"ALTER TABLE pncp_resultado ADD COLUMN {c} TEXT")
    for c in ("valor_unitario", "quantidade"):
        if c not in cols:
            con.execute(f"ALTER TABLE pncp_resultado ADD COLUMN {c} REAL")
    con.execute("CREATE INDEX IF NOT EXISTS ix_pncpres_orgao ON pncp_resultado(orgao_cnpj)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_pncpres_forn ON pncp_resultado(fornecedor_cnpj)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_pncpres_data ON pncp_resultado(data_pub)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_pncpres_desc ON pncp_resultado(item_descricao)")
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
        "unidade_codigo": uni.get("codigoUnidade"), "unidade_nome": uni.get("nomeUnidade"),
    }
    itens = await _consulta_itens(client, cnpj, ano, seq)
    gravados = 0
    for it in itens:
        num = it.get("numeroItem")
        if num is None:
            continue
        # descrição/unidade do item vêm do /itens (base do sobrepreço: "Ventilador", "Caixa"...)
        desc = (it.get("descricao") or "")[:200]
        unid = (it.get("unidadeMedida") or "").strip()
        res = await _resultado_item(client, cnpj, ano, seq, num)
        if res:
            tot["itens_com_resultado"] += 1
        for rr in res:
            forn = re.sub(r"\D", "", rr.get("niFornecedor", "") or "")
            if not forn:
                continue
            # UPSERT: linha nova entra completa; linha já existente ganha os campos de item
            # (descrição/preço unitário/qtd) — permite o backfill de sobrepreço sobre a base atual.
            con.execute("""INSERT INTO pncp_resultado
                (certame, orgao_cnpj, orgao_nome, uf, municipio, modalidade, objeto, data_pub,
                 item, fornecedor_cnpj, fornecedor_nome, valor_homologado, ordem_classificacao,
                 porte_fornecedor, unidade_codigo, unidade_nome,
                 item_descricao, unidade_medida, valor_unitario, quantidade)
                VALUES (:certame,:orgao_cnpj,:orgao_nome,:uf,:municipio,:modalidade,:objeto,:data_pub,
                        :item,:forn,:nome,:valor,:ordem,:porte,:unidade_codigo,:unidade_nome,
                        :desc,:unid,:vunit,:qtd)
                ON CONFLICT(certame, item, fornecedor_cnpj) DO UPDATE SET
                    item_descricao=COALESCE(excluded.item_descricao, item_descricao),
                    unidade_medida=COALESCE(excluded.unidade_medida, unidade_medida),
                    valor_unitario=COALESCE(excluded.valor_unitario, valor_unitario),
                    quantidade=COALESCE(excluded.quantidade, quantidade),
                    unidade_codigo=COALESCE(excluded.unidade_codigo, unidade_codigo),
                    unidade_nome=COALESCE(excluded.unidade_nome, unidade_nome)""",
                        {**meta, "item": num, "forn": forn,
                         "nome": rr.get("nomeRazaoSocialFornecedor"),
                         "valor": rr.get("valorTotalHomologado"),
                         "ordem": rr.get("ordemClassificacaoSrp"),
                         "porte": rr.get("porteFornecedorId"),
                         "desc": desc, "unid": unid,
                         "vunit": rr.get("valorUnitarioHomologado"),
                         "qtd": rr.get("quantidadeHomologada")})
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


async def backfill_precos_unitarios(con, limite: int = 3000, pausa: float = 0.25) -> dict:
    """Repopula item_descricao/valor_unitario/quantidade nas linhas JÁ existentes (a base antiga só
    guardava o total). Re-busca itens+resultados dos certames que ainda não têm preço unitário,
    mais RECENTES primeiro (onde o sobrepreço interessa). Idempotente (upsert), educado com a API."""
    init_schema(con)
    certames = [r[0] for r in con.execute(
        "SELECT DISTINCT certame FROM pncp_resultado "
        "WHERE ordem_classificacao=1 AND valor_unitario IS NULL AND certame IS NOT NULL "
        "ORDER BY data_pub DESC LIMIT ?", (limite,))]
    tot = {"certames": 0, "linhas_completadas": 0, "sem_id": 0}
    async with httpx.AsyncClient(timeout=40) as client:
        for idp in certames:
            pr = _parse_id_pncp(idp or "")
            if not pr:
                tot["sem_id"] += 1
                continue
            cnpj, ano, seq = pr
            itens = await _consulta_itens(client, cnpj, ano, seq)
            for it in itens:
                num = it.get("numeroItem")
                if num is None:
                    continue
                desc = (it.get("descricao") or "")[:200]
                unid = (it.get("unidadeMedida") or "").strip()
                res = await _resultado_item(client, cnpj, ano, seq, num)
                for rr in res:
                    forn = re.sub(r"\D", "", rr.get("niFornecedor", "") or "")
                    if not forn:
                        continue
                    con.execute("""UPDATE pncp_resultado SET
                            item_descricao=COALESCE(:desc, item_descricao),
                            unidade_medida=COALESCE(:unid, unidade_medida),
                            valor_unitario=COALESCE(:vunit, valor_unitario),
                            quantidade=COALESCE(:qtd, quantidade)
                        WHERE certame=:certame AND item=:item AND fornecedor_cnpj=:forn""",
                        {"desc": desc, "unid": unid, "vunit": rr.get("valorUnitarioHomologado"),
                         "qtd": rr.get("quantidadeHomologada"), "certame": idp, "item": num, "forn": forn})
                    tot["linhas_completadas"] += con.total_changes and 1 or 0
                await asyncio.sleep(pausa)
            tot["certames"] += 1
            if tot["certames"] % 50 == 0:
                con.commit()
                print(f"[backfill precos] {tot['certames']}/{len(certames)} certames · "
                      f"{tot['linhas_completadas']} linhas", flush=True)
    con.commit()
    return tot


def _chave_orgao(orgao_cnpj: str | None, unidade_codigo: str | None) -> str:
    """Chave do órgão COMPRADOR real: CNPJ do ente + código da unidade (só dígitos — o detector
    normaliza com _so_digitos). O PNCP registra contratação estadual no CNPJ do ENTE ("Estado do
    Rio de Janeiro"); sem a unidade, todos os órgãos do Estado colapsariam num só. Os 14 primeiros
    dígitos são sempre o CNPJ (linha sem unidade — pré-backfill — mantém a chave = CNPJ puro)."""
    cnpj = re.sub(r"\D", "", orgao_cnpj or "").zfill(14)
    uni = re.sub(r"\D", "", unidade_codigo or "")
    return cnpj + uni


def registros_vencedores(con, uf: str | None = "RJ") -> list[dict]:
    """Lê pncp_resultado e devolve UM registro por certame com seu(s) vencedor(es) — insumo do
    detector de rodízio de vencedores (rodizio_grafo.detectar_rodizio_vencedores).
    `orgao` = chave composta ente+unidade (_chave_orgao); `orgao_nome` = razão social do ENTE
    (esfera/compat); `unidade_nome` = o órgão real para exibição."""
    con.row_factory = sqlite3.Row
    # base pré-migração (conexão mode=ro nunca roda init_schema): degrada p/ unidade NULL
    tem_uni = {r[1] for r in con.execute("PRAGMA table_info(pncp_resultado)")} >= {"unidade_codigo"}
    sel_uni = ("unidade_codigo, unidade_nome" if tem_uni
               else "NULL AS unidade_codigo, NULL AS unidade_nome")
    q = (f"SELECT certame, orgao_cnpj, orgao_nome, {sel_uni}, municipio, objeto, data_pub, "
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
            "certame": r["certame"], "orgao": _chave_orgao(r["orgao_cnpj"], r["unidade_codigo"]),
            "orgao_cnpj": r["orgao_cnpj"], "orgao_nome": r["orgao_nome"],
            "unidade_codigo": r["unidade_codigo"], "unidade_nome": r["unidade_nome"],
            "municipio": r["municipio"],
            "objeto": r["objeto"], "data": r["data_pub"], "vencedores": []})
        c["vencedores"].append({"cnpj": r["fornecedor_cnpj"], "nome": r["fornecedor_nome"], "valor": r["v"]})
    return list(por_certame.values())


def conluio_do_orgao(nome_orgao: str, db_path: str = "data/compliance.db", min_certames: int = 3) -> dict:
    """Conluio (captura/rodízio de vencedores do PNCP) filtrado por NOME de órgão — insumo do /orgao.
    Match best-effort por LIKE no orgao_nome OU unidade_nome (contratação estadual tem orgao_nome =
    ente "Estado do Rio de Janeiro"; o órgão real é a unidade). Retorna {captura, rodizio_vencedores,
    n_certames} ou {n_certames:0} se não houver resultado."""
    import sqlite3 as _sq

    from compliance_agent.rodizio_grafo import detectar_rodizio_vencedores
    termo = re.sub(r"\s+", " ", (nome_orgao or "").strip()).upper()
    if len(termo) < 4:
        return {"captura": [], "rodizio_vencedores": [], "n_certames": 0}
    con = _sq.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = _sq.Row
    try:
        # base pré-migração (mode=ro não migra): degrada p/ unidade NULL em vez de 500
        tem_uni = {r[1] for r in con.execute("PRAGMA table_info(pncp_resultado)")} >= {"unidade_codigo"}
        sel_uni = ("unidade_codigo, unidade_nome" if tem_uni
                   else "NULL AS unidade_codigo, NULL AS unidade_nome")
        cond_uni = "OR UPPER(COALESCE(unidade_nome,'')) LIKE ? " if tem_uni else ""
        params = (f"%{termo}%",) * (2 if tem_uni else 1)
        rows = con.execute(
            f"SELECT certame, orgao_cnpj, orgao_nome, {sel_uni}, objeto, data_pub, "
            "fornecedor_cnpj, fornecedor_nome, SUM(valor_homologado) v FROM pncp_resultado "
            f"WHERE ordem_classificacao=1 AND (UPPER(orgao_nome) LIKE ? {cond_uni})"
            "GROUP BY certame, fornecedor_cnpj", params).fetchall()
    finally:
        con.close()
    por: dict[str, dict] = {}
    for r in rows:
        c = por.setdefault(r["certame"], {
            "certame": r["certame"], "orgao": _chave_orgao(r["orgao_cnpj"], r["unidade_codigo"]),
            "orgao_nome": r["orgao_nome"], "unidade_nome": r["unidade_nome"], "objeto": r["objeto"],
            "data": r["data_pub"], "vencedores": []})
        c["vencedores"].append({"cnpj": r["fornecedor_cnpj"], "nome": r["fornecedor_nome"], "valor": r["v"]})
    regs = list(por.values())
    pad = detectar_rodizio_vencedores(regs, min_certames=min_certames)
    pad["n_certames"] = len(regs)
    return pad


_RX_MUNICIPAL = __import__("re").compile(
    # sinais de ENTIDADE municipal — não a mera substring "MUNICIP" (uma "SECRETARIA DE ESTADO DE
    # APOIO AOS MUNICÍPIOS" é estadual e não pode cair em prefeitura)
    r"\bMUNIC[IÍ]PIO DE\b|PREF(EITURA|\.)|\bMUN\.|C[ÂA]MARA MUNICIPAL|FUNDO MUNICIPAL|"
    r"SECRETARIA MUNICIPAL", __import__("re").I)
_RX_FEDERAL = __import__("re").compile(
    # federais têm "DO ESTADO DO RIO DE JANEIRO" no nome (UNIRIO, conselhos regionais) — checar
    # ANTES do estadual, senão viram "estado" (bug real: DNIT/IBGE/Exército no módulo Estado)
    r"FEDERAL|MINIST[ÉE]RIO|COMANDO D[OA]|CONSELHO (REGIONAL|NACIONAL)|TRIBUNAL REGIONAL|"
    r"JUSTI[ÇC]A FEDERAL|\bDNIT\b|\bIBGE\b|\bIBAMA\b|\bSEBRAE\b|\bSENAI\b|\bSENAC\b|"
    r"FUNDA[ÇC][AÃ]O OSWALDO CRUZ|\bFIOCRUZ\b|\bINSS\b|\bUFRJ\b|\bUFF\b", __import__("re").I)
_RX_ESTADUAL = __import__("re").compile(
    r"\bESTAD|SECRETARIA DE ESTADO|GOVERNO DO ESTADO|FUNDO ESTADUAL|ASSEMBLEIA LEGISLATIVA|"
    r"TRIBUNAL DE JUSTI|DETRAN|POL[ÍI]CIA (MILITAR|CIVIL)|CORPO DE BOMBEIROS", __import__("re").I)


def esfera_do_orgao(nome: str) -> str:
    """FALLBACK por nome: 'prefeitura' | 'estado' | 'outros' (federal/autarquia). Usado só quando o
    ente não está em pncp_ente (esfera OFICIAL do PNCP) — ver classificar_esfera()."""
    n = nome or ""
    if _RX_MUNICIPAL.search(n):
        return "prefeitura"
    if _RX_FEDERAL.search(n):
        return "outros"
    if _RX_ESTADUAL.search(n):
        return "estado"
    return "outros"


def init_ente_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS pncp_ente (
            cnpj        TEXT PRIMARY KEY,        -- 14 dígitos
            nome        TEXT,
            esfera_id   TEXT,                    -- F=federal E=estadual M=municipal (oficial PNCP)
            poder_id    TEXT,                    -- E=executivo L=legislativo J=judiciário N=n/a
            natureza_juridica TEXT,
            coletado_em TEXT DEFAULT (datetime('now'))
        )""")
    con.commit()


def coletar_entes(con, pausa: float = 0.25) -> dict:
    """Esfera OFICIAL de cada ente com resultado no PNCP (GET /orgaos/{cnpj} → esferaId F/E/M).
    1 requisição por CNPJ ainda não coletado (~centenas, roda 1×; incremental depois)."""
    import time as _t
    init_ente_schema(con)
    tem = {r[0] for r in con.execute("SELECT cnpj FROM pncp_ente WHERE esfera_id IS NOT NULL")}
    todos = {re.sub(r"\D", "", r[0] or "").zfill(14)
             for r in con.execute("SELECT DISTINCT orgao_cnpj FROM pncp_resultado "
                                  "WHERE orgao_cnpj IS NOT NULL")}
    falta = sorted(todos - tem)
    n_ok = n_err = 0
    with httpx.Client(headers=_H, timeout=20) as cli:
        for cnpj in falta:
            try:
                r = cli.get(f"{PNCP_BASE}/orgaos/{cnpj}")
                if r.status_code == 200:
                    d = r.json()
                    con.execute("INSERT OR REPLACE INTO pncp_ente(cnpj,nome,esfera_id,poder_id,"
                                "natureza_juridica) VALUES(?,?,?,?,?)",
                                (cnpj, d.get("razaoSocial"), d.get("esferaId"), d.get("poderId"),
                                 d.get("codigoNaturezaJuridica")))
                    n_ok += 1
                else:
                    n_err += 1
            except Exception:
                n_err += 1
            _t.sleep(pausa)
    con.commit()
    return {"ok": True, "novos": n_ok, "erros": n_err, "faltavam": len(falta), "entes": len(todos)}


def esferas_por_ente(con) -> dict[str, str]:
    """cnpj(14) → esfera_id oficial ('F'/'E'/'M'). Vazio se a tabela pncp_ente não existe (fallback regex)."""
    try:
        return {r[0]: (r[1] or "") for r in con.execute("SELECT cnpj, esfera_id FROM pncp_ente")}
    except sqlite3.OperationalError:
        return {}


def classificar_esfera(registro: dict, oficial: dict[str, str]) -> str:
    """Esfera de UM certame: 'estado' | 'prefeitura' (município do Rio) | 'municipios' (demais
    municípios) | 'federal' | 'outros'. Fonte 1 = esferaId OFICIAL do ente no PNCP; exceção real:
    ente estadual com UNIDADE municipal (acontece no PNCP) segue a unidade. Fallback = nome."""
    nome_uni = f"{registro.get('unidade_nome') or ''} {registro.get('orgao_nome') or ''}"
    muni = (registro.get("municipio") or "").strip().lower()
    eh_rio = muni in ("rio de janeiro", "")
    cnpj14 = re.sub(r"\D", "", registro.get("orgao_cnpj") or (registro.get("orgao") or ""))[:14].zfill(14)
    esf = oficial.get(cnpj14)
    if esf == "M":
        return "prefeitura" if eh_rio else "municipios"
    if esf == "E":
        uni = registro.get("unidade_nome") or ""
        # exceção 1: unidade explicitamente municipal dentro do ente estadual
        if _RX_MUNICIPAL.search(uni):
            return "prefeitura" if eh_rio else "municipios"
        # exceção 2 (dado real do PNCP): autarquia MUNICIPAL do interior cadastrada como unidade do
        # ente "Estado do RJ" (ex.: Instituto de Seguridade Social de Maricá). Sem marcador estadual
        # no nome E fora da capital → é municipal; unidades estaduais do interior têm marcador
        # (SECRETARIA DE ESTADO, DETRAN, POLÍCIA, HOSPITAL ESTADUAL...).
        if uni and muni and not eh_rio and not _RX_ESTADUAL.search(uni):
            return "municipios"
        return "estado"
    if esf == "F":
        return "federal"
    e = esfera_do_orgao(nome_uni)
    if e == "prefeitura":
        return "prefeitura" if eh_rio else "municipios"
    return e


def conluio_enriquecido(con, uf: str | None = "RJ", min_certames: int = 5,
                        esfera: str | None = None) -> dict:
    """Roda detectar_rodizio_vencedores sobre os resultados do PNCP e DECORA com nome de fornecedor,
    nome de órgão e amostra de OBJETOS — pronto para o painel/relatório (user-friendly).
    ``esfera`` ∈ {'estado','prefeitura','municipios','federal','outros'} filtra pela esfera OFICIAL
    do ente no PNCP (pncp_ente.esferaId; fallback nome) — 'prefeitura' = município do Rio;
    'municipios' = demais municípios do RJ; 'outros' = tudo que não é estado/prefeitura."""
    from compliance_agent.rodizio_grafo import detectar_rodizio_vencedores
    regs = registros_vencedores(con, uf=uf)
    oficial = esferas_por_ente(con)
    contagem_esferas: dict[str, int] = {}
    for r in regs:
        r["_esfera"] = classificar_esfera(r, oficial)
        contagem_esferas[r["_esfera"]] = contagem_esferas.get(r["_esfera"], 0) + 1
    if esfera == "outros":
        regs = [r for r in regs if r["_esfera"] not in ("estado", "prefeitura")]
    elif esfera in ("estado", "prefeitura", "municipios", "federal"):
        regs = [r for r in regs if r["_esfera"] == esfera]
    pad = detectar_rodizio_vencedores(regs, min_certames=min_certames)
    pad["esferas"] = contagem_esferas  # transparência da segregação (Estado ≠ prefeituras ≠ federal)
    # índices auxiliares: cnpj→nome, orgao→(nome exibível, ente), orgao→objetos, (orgao,cnpj)→objetos
    nome_forn: dict[str, str] = {}
    nome_org: dict[str, str] = {}
    ente_org: dict[str, str] = {}
    obj_org: dict[str, list] = {}
    obj_org_forn: dict[tuple, list] = {}
    for r in regs:
        org = re.sub(r"\D", "", r.get("orgao") or "")
        if org and (r.get("unidade_nome") or r.get("orgao_nome")):
            # nome exibível = a UNIDADE (órgão real); o ente fica em ente_org p/ contexto
            nome_org[org] = r.get("unidade_nome") or r["orgao_nome"]
            ente_org[org] = r.get("orgao_nome") or ""
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
        cap["ente_nome"] = ente_org.get(org, "")
        cap["orgao_cnpj_fmt"] = _fmt_cnpj(org[:14])  # chave = CNPJ do ente (14) + cód. unidade
        cap["nome"] = nome_forn.get(fc, cap.get("nome") or "—")
        cap["fornecedor_cnpj_fmt"] = _fmt_cnpj(fc)
        cap["objetos"] = (obj_org_forn.get((org, fc)) or obj_org.get(org) or [])[:5]
    for rod in pad.get("rodizio_vencedores", []):
        org = rod["orgao"]
        rod["orgao_nome"] = nome_org.get(org, "—")
        rod["ente_nome"] = ente_org.get(org, "")
        rod["orgao_cnpj_fmt"] = _fmt_cnpj(org[:14])
        rod["membros_nome"] = [{"cnpj": _fmt_cnpj(c), "nome": nome_forn.get(c, "—"),
                                "vitorias": rod["reparticao"].get(c, 0)} for c in rod["grupo"]]
        rod["objetos"] = (obj_org.get(org) or [])[:5]
    sem_uni = sum(1 for r in regs if not r.get("unidade_codigo"))
    pad["cobertura"] = {"certames_com_resultado": len(regs), "orgaos": pad.get("n_orgaos", 0),
                        # transparência do backfill: certame sem unidade fica agrupado no ENTE —
                        # grupos do mesmo órgão real podem estar fragmentados até a cobertura fechar
                        "certames_sem_unidade": sem_uni}
    return pad


if __name__ == "__main__":
    import json
    import sys
    args = sys.argv[1:]
    # timeout alto: compliance.db é compartilhado com o jfn.service vivo — numa carga de horas o
    # busy_timeout de 5s (default) estouraria em contenção de escrita. WAL + 60s absorve.
    con = sqlite3.connect("data/compliance.db", timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    if "--backfill-precos" in args:
        # repopula preço unitário/descrição nas linhas antigas (sobrepreço). [N] = teto de certames.
        n = next((int(a) for a in args if a.isdigit()), 3000)
        r = asyncio.run(backfill_precos_unitarios(con, limite=n))
    elif "--incremental" in args:
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
