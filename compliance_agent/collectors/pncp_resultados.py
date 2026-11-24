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

from compliance_agent.collectors.arquivos import abrir_banco, caminho_db
from compliance_agent.collectors.pncp import (
    CONSULTA_BASE, MODALIDADES_PADRAO, PNCP_BASE, PncpIndisponivel, _parse_id_pncp,
)

_H = {"User-Agent": "JFN-Compliance/2.0"}
# menor data com dado estruturado útil no PNCP (ver docstring — 2024 é o 1º ano denso).
PNCP_PRIMEIRO_ANO_DENSO = 2024
_LOCK_TENTATIVAS, _LOCK_ESPERA = 10, 120      # até ~20 min de banco travado por página


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


# Chamada que a API NÃO respondeu (5xx, erro de rede esgotado, 429 esgotado). Até 20/11/2026 isso voltava como
# lista vazia, igual a "certame sem resultado": na coleta semanal de 15/11 o PNCP devolveu 503 em tudo, o resumo
# saiu {"certames": 7573, "itens_com_resultado": 0, "gravados": 0}, o serviço terminou com sucesso e a base
# ficou parada em 10/11 sem aviso. INDISPONÍVEL ≠ 0: a falha é contada e decide o código de saída.
_FALHAS = {"api": 0}


def veredito_da_coleta(tot: dict) -> tuple[bool, str]:
    """(ok, motivo). Falha quando a API falhou e NADA foi lido — zero aí é fonte fora do ar, não mês sem resultado."""
    falhas = int(tot.get("falhas_api") or 0)
    if falhas and not tot.get("itens_com_resultado"):
        return False, (f"PNCP INDISPONÍVEL: {falhas} chamada(s) sem resposta e nenhum item lido em "
                       f"{tot.get('certames', 0)} certame(s) — a base NÃO foi atualizada nesta corrida")
    if falhas:
        return True, f"coleta parcial: {falhas} chamada(s) sem resposta do PNCP (o que respondeu foi gravado)"
    return True, ""


async def _get_medido(client: httpx.AsyncClient, url: str, params: dict | None, tentativas: int,
                      espera_rede: float, espera_429: float, vazio: tuple[int, ...]):
    """GET com backoff linear (rede e 429). Status em `vazio` → None ("a fonte diz que não há"); 5xx, 4xx
    inesperado ou tentativas esgotadas → `PncpIndisponivel`. As três cópias anteriores devolviam o MESMO
    None/[] do "não há": página de contratações que falhou encerrava o mês calada, e item cujo resultado
    falhou entrava como item sem vencedor."""
    motivo = "sem resposta"
    for tent in range(tentativas):
        try:
            r = await client.get(url, params=params, headers=_H)
        except httpx.HTTPError as exc:
            motivo = f"{type(exc).__name__}"
            await asyncio.sleep(espera_rede * (tent + 1))
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError as exc:   # 200 com HTML (WAF): indisponível, não derruba a carga inteira
                _FALHAS["api"] += 1
                raise PncpIndisponivel(f"{url}: HTTP 200 sem JSON") from exc
        if r.status_code in vazio:
            return None
        if r.status_code == 429:
            motivo = "HTTP 429"
            await asyncio.sleep(espera_429 * (tent + 1))
            continue
        _FALHAS["api"] += 1
        raise PncpIndisponivel(f"{url}: HTTP {r.status_code}")
    _FALHAS["api"] += 1
    raise PncpIndisponivel(f"{url}: {motivo} após {tentativas} tentativas")


async def _consulta(client: httpx.AsyncClient, endpoint: str, params: dict) -> dict | None:
    """API de consulta; 204 = sem dado na janela (honesto: não é erro)."""
    return await _get_medido(client, f"{CONSULTA_BASE}{endpoint}", params, 5, 2, 5, vazio=(204,))


async def _resultado_item(client: httpx.AsyncClient, cnpj: str, ano: str, seq: int, item: int) -> list[dict]:
    return await _get_medido(client, f"{PNCP_BASE}/orgaos/{cnpj}/compras/{ano}/{seq}/itens/{item}/resultados",
                             None, 4, 1.5, 4, vazio=(204, 404)) or []


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
    _FALHAS["api"] = 0
    async with httpx.AsyncClient(timeout=40) as client:
        for d_ini, d_fim in _meses(ano_ini, mes_ini, ano_fim, mes_fim):
            tot["meses"] += 1
            for mod in modalidades:
                for pagina in range(1, max_paginas + 1):
                    try:
                        j = await _consulta(client, "/contratacoes/publicacao", {
                            "dataInicial": d_ini, "dataFinal": d_fim, "uf": uf.upper(),
                            "codigoModalidadeContratacao": mod, "pagina": pagina, "tamanhoPagina": 50})
                    except PncpIndisponivel as exc:
                        # o resto deste mês × modalidade NÃO foi lido — contado, não "acabou o dado"
                        tot.setdefault("paginas_indisponiveis", []).append(f"{d_ini} mod {mod} pág {pagina}: {exc}")
                        break
                    data = (j or {}).get("data") or []
                    if not data:
                        break
                    # O VACUUM de domingo (5 GB) segura o banco além do busy_timeout de 60 s: em
                    # 01/11/2026 a coleta morreu com "database is locked" e perdeu a semana. Trava
                    # passageira → desfaz a página, espera e refaz (upsert é idempotente).
                    for tentativa in range(_LOCK_TENTATIVAS):
                        antes = dict(tot)
                        try:
                            for ct in data:
                                n = await _gravar_certame(con, client, ct, tot)
                                tot["gravados"] += n
                                await asyncio.sleep(pausa)
                            con.commit()
                            break
                        except sqlite3.OperationalError as exc:
                            if "locked" not in str(exc) or tentativa == _LOCK_TENTATIVAS - 1:
                                raise
                            con.rollback()
                            tot.clear()
                            tot.update(antes)
                            await asyncio.sleep(_LOCK_ESPERA)
                    if pagina >= ((j or {}).get("totalPaginas") or 1):
                        break
                    await asyncio.sleep(pausa)
    con.commit()
    tot["falhas_api"] = _FALHAS["api"]
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
    try:
        itens = await _consulta_itens(client, cnpj, ano, seq)
    except PncpIndisponivel:
        tot["certames_itens_indisponiveis"] = tot.get("certames_itens_indisponiveis", 0) + 1
        return 0
    gravados = 0
    for it in itens:
        num = it.get("numeroItem")
        if num is None:
            continue
        # descrição/unidade do item vêm do /itens (base do sobrepreço: "Ventilador", "Caixa"...)
        desc = (it.get("descricao") or "")[:200]
        unid = (it.get("unidadeMedida") or "").strip()
        try:
            res = await _resultado_item(client, cnpj, ano, seq, num)
        except PncpIndisponivel:
            tot["itens_resultado_indisponivel"] = tot.get("itens_resultado_indisponivel", 0) + 1
            continue
        if res:
            tot["itens_com_resultado"] += 1
        for rr in res:
            forn = re.sub(r"\D", "", rr.get("niFornecedor", "") or "")
            if not forn:
                continue
            # UPSERT: linha nova entra completa; linha já existente ganha os campos de item
            # (descrição/preço unitário/qtd) — permite o backfill de sobrepreço sobre a base atual.
            cur = con.execute("""INSERT INTO pncp_resultado
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
            # `con.total_changes` é cumulativo da conexão: depois da 1ª escrita contava TODA linha lida
            gravados += cur.rowcount > 0
    return gravados


async def _consulta_itens(client, cnpj: str, ano: str, seq: int) -> list[dict]:
    return await _get_medido(client, f"{PNCP_BASE}/orgaos/{cnpj}/compras/{ano}/{seq}/itens",
                             None, 4, 1.5, 4, vazio=(204, 404)) or []


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
            try:
                itens = await _consulta_itens(client, cnpj, ano, seq)
            except PncpIndisponivel:
                tot["indisponiveis"] = tot.get("indisponiveis", 0) + 1
                continue
            for it in itens:
                num = it.get("numeroItem")
                if num is None:
                    continue
                desc = (it.get("descricao") or "")[:200]
                unid = (it.get("unidadeMedida") or "").strip()
                try:
                    res = await _resultado_item(client, cnpj, ano, seq, num)
                except PncpIndisponivel:
                    tot["indisponiveis"] = tot.get("indisponiveis", 0) + 1
                    continue
                for rr in res:
                    forn = re.sub(r"\D", "", rr.get("niFornecedor", "") or "")
                    if not forn:
                        continue
                    cur = con.execute("""UPDATE pncp_resultado SET
                            item_descricao=COALESCE(:desc, item_descricao),
                            unidade_medida=COALESCE(:unid, unidade_medida),
                            valor_unitario=COALESCE(:vunit, valor_unitario),
                            quantidade=COALESCE(:qtd, quantidade)
                        WHERE certame=:certame AND item=:item AND fornecedor_cnpj=:forn""",
                        {"desc": desc, "unid": unid, "vunit": rr.get("valorUnitarioHomologado"),
                         "qtd": rr.get("quantidadeHomologada"), "certame": idp, "item": num, "forn": forn})
                    tot["linhas_completadas"] += cur.rowcount > 0
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


def conluio_do_orgao(nome_orgao: str, db_path: str | None = None, min_certames: int = 3) -> dict:
    """Conluio (captura/rodízio de vencedores do PNCP) filtrado por NOME de órgão — insumo do /orgao.
    Match best-effort por LIKE no orgao_nome OU unidade_nome (contratação estadual tem orgao_nome =
    ente "Estado do Rio de Janeiro"; o órgão real é a unidade). Retorna {captura, rodizio_vencedores,
    n_certames} ou {n_certames:0} se não houver resultado."""
    import sqlite3 as _sq

    from compliance_agent.rodizio_grafo import detectar_rodizio_vencedores
    termo = re.sub(r"\s+", " ", (nome_orgao or "").strip()).upper()
    if len(termo) < 4:
        return {"captura": [], "rodizio_vencedores": [], "n_certames": 0}
    con = _sq.connect(f"file:{caminho_db(db_path)}?mode=ro", uri=True)
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


# 19/11/2026: as regex de nome que moravam aqui (federal/estadual/municipal) foram para a FONTE ÚNICA
# `compliance_agent/esfera_orgao.py` — a estadual casava órgão de QUALQUER estado ("SECRETARIA DE ESTADO",
# "TRIBUNAL DE JUSTI", "POLÍCIA CIVIL"). Aqui só se traduz o rótulo canônico para o vocabulário do PNCP.
from compliance_agent import esfera_orgao as _eo  # noqa: E402

_PARA_PNCP = {"estadual-rj": "estado", "municipal-rio": "prefeitura", "outro-municipio": "municipios",
              "federal": "federal", "outro-estado": "outros", "indefinido": "outros"}
# Escopo do JFN (dono, 19/11/2026: "esquece a parte federal"): sem aba escolhida, o filtro canônico é o RJ.
ESFERAS_RJ = tuple(sorted({_PARA_PNCP[e] for e in _eo.NO_RJ}))   # ('estado', 'prefeitura')


def esfera_do_orgao(nome: str) -> str:
    """FALLBACK só por nome: 'prefeitura' | 'estado' | 'outros' (federal/outro estado/sem sinal).
    'estado' exige marca do RJ no nome (regra da fonte única). Ver classificar_esfera()."""
    e = _eo.classificar("", nome or "", fatos={})["esfera"]
    if e in ("municipal-rio", "outro-municipio"):
        return "prefeitura"
    return "estado" if e == "estadual-rj" else "outros"


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


# VOCABULÁRIO FECHADO da esfera. Existe porque um valor errado não dá erro: `esfera="estadual"`
# (que parece certo em português) não casa com nada e a varredura devolve **zero achados** — li
# "0 aditivo irregular no Estado" numa base que tinha 260, em 2026-08-10. Filtro que erra o rótulo
# mente com cara de resposta. Quem recebe `esfera` do usuário valida contra isto ANTES de filtrar.
ESFERAS = ("estado", "prefeitura", "municipios", "federal", "outros")


def classificar_esfera(registro: dict, oficial: dict[str, str]) -> str:
    """Esfera de UM certame: 'estado' (Estado do RJ) | 'prefeitura' (município do Rio) | 'municipios'
    (demais municípios) | 'federal' | 'outros' (outro estado / sem sinal). Delega à fonte única
    `esfera_orgao.classificar_unidade` (raiz CNPJ → natureza jurídica + UF da sede → nome com marca do RJ);
    `oficial` (esferaId do ente no PNCP) completa o que a base não tiver. Exceção do PNCP preservada lá:
    unidade municipal sob o ente "Estado do RJ" segue a unidade; município vazio ≠ Rio."""
    cnpj14 = re.sub(r"\D", "", registro.get("orgao_cnpj") or (registro.get("orgao") or ""))[:14]
    cnpj14 = cnpj14.zfill(14) if cnpj14 else ""
    r = _eo.classificar_unidade(cnpj14, registro.get("orgao_nome") or "", registro.get("unidade_nome") or "",
                                registro.get("municipio") or "", registro.get("uf") or "",
                                (oficial or {}).get(cnpj14))
    return _PARA_PNCP[r["esfera"]]


def certames_da_esfera(con, esfera: str | None) -> set | None:
    """Set de `certame` cuja esfera oficial (classificar_esfera) é `esfera`
    ('estado'|'prefeitura'|'municipios'|'federal'|'outros'). None/'' = escopo RJ (estado+prefeitura);
    'todas' = sem filtro (opt-in explícito).
    É O filtro canônico das abas do painel: aba Estado passa 'estado', Prefeitura 'prefeitura' —
    nenhum detector deve reinventar a classificação (exceções de unidade vivem no classificar_esfera)."""
    if esfera == "todas":            # opt-in explícito de quem pesquisa fora do escopo
        return None
    if not esfera:                   # 19/11/2026: sem aba = escopo do JFN (Estado do RJ + Prefeitura do Rio)
        return certames_das_esferas(con, set(ESFERAS_RJ))
    # Rótulo fora do vocabulário devolveria um SET VAZIO, e set vazio filtra tudo: o detector some
    # com zero achados sobre uma base cheia. Medido em 2026-08-10 com `esfera="estadual"` (o
    # português natural) em vez de `"estado"` — 0 achados numa base com 260. Erro é melhor que
    # silêncio: quem chama tem de saber que não mediu.
    if esfera not in ESFERAS:
        raise ValueError(f"esfera '{esfera}' não existe — use uma de {list(ESFERAS)} ou 'todas'")
    return certames_das_esferas(con, {esfera})


def certames_das_esferas(con, esferas) -> set | None:
    """Como certames_da_esfera, mas aceita um CONJUNTO de esferas numa única passada.
    Usado pelo achado de sobrepreço restrito aos entes fiscalizados ({estado, prefeitura}).
    Conjunto vazio/None → sem filtro (None)."""
    alvo = {e for e in (esferas or ()) if e and e != "todas"}
    if not alvo:
        return None
    oficial = esferas_por_ente(con)
    certs: set = set()
    for r in con.execute(
            "SELECT certame, MAX(orgao_cnpj) orgao_cnpj, MAX(orgao_nome) orgao_nome, "
            "MAX(unidade_nome) unidade_nome, MAX(municipio) municipio "
            "FROM pncp_resultado GROUP BY certame"):
        if classificar_esfera(dict(r), oficial) in alvo:
            certs.add(r["certame"])
    return certs


def conluio_enriquecido(con, uf: str | None = "RJ", min_certames: int = 5,
                        esfera: str | None = None) -> dict:
    """Roda detectar_rodizio_vencedores sobre os resultados do PNCP e DECORA com nome de fornecedor,
    nome de órgão e amostra de OBJETOS — pronto para o painel/relatório (user-friendly).
    ``esfera`` ∈ {'estado','prefeitura','municipios','federal','outros'} filtra pela esfera OFICIAL
    do ente no PNCP (pncp_ente.esferaId; fallback nome) — 'prefeitura' = município do Rio;
    'municipios' = demais municípios; 'outros' = tudo que não é estado/prefeitura; None/'' = só o RJ
    (estado+prefeitura); 'todas' = sem filtro."""
    from compliance_agent.rodizio_grafo import detectar_rodizio_vencedores
    regs = registros_vencedores(con, uf=uf)
    oficial = esferas_por_ente(con)
    contagem_esferas: dict[str, int] = {}
    for r in regs:
        r["_esfera"] = classificar_esfera(r, oficial)
        contagem_esferas[r["_esfera"]] = contagem_esferas.get(r["_esfera"], 0) + 1
    if esfera == "outros":
        regs = [r for r in regs if r["_esfera"] not in ESFERAS_RJ]
    elif esfera in ("estado", "prefeitura", "municipios", "federal"):
        regs = [r for r in regs if r["_esfera"] == esfera]
    elif esfera != "todas":          # 19/11/2026: sem aba = só o RJ (federal/outros entes fora do escopo)
        regs = [r for r in regs if r["_esfera"] in ESFERAS_RJ]
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
        # objetos DO GRUPO (o que os membros venceram), não do órgão inteiro — em ente
        # mono-unidade (PCRJ publica tudo sob 986001) o fallback órgão-level mostrava
        # objetos alheios ao grupo (TI/locação num rodízio de medicamentos)
        obj_grupo: list = []
        for c in rod["grupo"]:
            for o in obj_org_forn.get((org, c), []):
                if o not in obj_grupo:
                    obj_grupo.append(o)
        rod["objetos"] = (obj_grupo or obj_org.get(org) or [])[:5]
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
    con = abrir_banco()
    con.execute("PRAGMA busy_timeout=60000")
    if "--atas" in args:
        # coleta as ATAS DE JULGAMENTO reais (perdedoras) dos próximos N certames competitivos.
        # OCR nas escaneadas — CARO; [N] modesto no timer. Alimenta conluio_qsa/rodízio.
        from compliance_agent.collectors.atas_julgamento import coletar_atas_julgamento
        n = next((int(a) for a in args if a.isdigit()), 300)
        r = asyncio.run(coletar_atas_julgamento(con, limite=n))
    elif "--backfill-precos" in args:
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
    if "itens_com_resultado" in r:           # coleta de resultados (incremental/backfill): zero por API fora do ar
        ok, motivo = veredito_da_coleta(r)   # sai ≠ 0 — o systemd marca falha e o OnFailure avisa
        if motivo:
            print(motivo, file=sys.stderr, flush=True)
        if not ok:
            sys.exit(1)
        if r.get("itens_com_resultado"):     # evento de verdade (24/11/2026); a sonda (pncp_resultado) segue como rede
            from compliance_agent import propagacao
            propagacao.avisar("contratos_tcerj", f"PNCP: {r['itens_com_resultado']} item(ns) com resultado coletado(s)")
