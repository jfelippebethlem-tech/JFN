# -*- coding: utf-8 -*-
"""Rotas de investigação do JFN (split de server.py em 2026-07-06; rede: tests/test_server_snapshot.py).

Também é a casa do cache do painel (`_cache_get`/`_cache_put`/`_cache_calc`, disco em `data/cache_painel`), que
outras rotas importam — ver docs/untangle/rotas.md, pendência 9.1.

O7.6 (2026-11-25): 81 das 106 rotas saíram, sem mudar comportamento, para `rotas/intel_contratacao.py`,
`rotas/intel_pessoas.py`, `rotas/comparador.py`, `rotas/pcrj.py`, `rotas/consultas.py` e `rotas/radar.py`; aqui ficaram
o painel, as rotas com visão materializada (E15), o cache e os ajudantes que aqueles módulos importam. Paridade de
rotas e de ordem de registro: tests/test_rotas_investigacao_paridade.py."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


router = APIRouter()

# Raiz do repo (~/JFN) — após o split de server.py p/ rotas/ (2026-07-06), os caminhos por
# __file__ apontavam p/ rotas/data (inexistente) e grafo/fachada-revisar/fachada-veredito
# quebraram em silêncio. Fix 2026-07-10 (mesmo fix do rotas/sistema.py).
RAIZ = Path(__file__).resolve().parent.parent


def _ro(banco: str = "compliance.db", *, linhas: bool = False, **kw) -> sqlite3.Connection:
    """Conexão SÓ LEITURA a `data/<banco>` do repo. `RAIZ` é lido na chamada (os testes o redirecionam)."""
    con = sqlite3.connect(f"file:{RAIZ / 'data' / banco}?mode=ro", uri=True, **kw)
    if linhas:
        con.row_factory = sqlite3.Row
    return con


def _visao(nome: str):
    """Visão materializada pelo E15 (O7.1) ou None. `RAIZ` lido na chamada: teste que o redireciona cai no legado."""
    from compliance_agent.aplicacao.estagios import materializar as M
    return M.resposta(nome, RAIZ)


def _legado(nome: str, resp):
    from compliance_agent.aplicacao.estagios import materializar as M
    return M.marcar_ausente(resp, nome)


async def _grafo_rede_completa(limite: int = 120):
    """Rede de relacionamento COMPLETA (não só MGS): top-N fornecedores por valor PAGO ↔ órgãos (UGs).
    Fornecedor vira severidade='alta' se for INDICIO em verificacao_sede.
    Formato D3 que o graph.html consome: {nodes:[{id,label,tipo,...}], links:[{source,target,...}]}.

    24/11/2026: a tela diz "REDE DE PAGAMENTOS · SIAFE", mas somava o espelho TFE (`ordens_bancarias`). Agora é OB
    PAGA do SIAFE (régua `_ob_paga`, 2021 em diante, credor CNPJ/CPF): os fornecedores saem do ranking já calculado
    por `_siafe_pago_total` (mesma varredura do painel, em cache) e as arestas, de uma consulta pelo índice de credor.
    Roda numa thread — a varredura não pode travar o event loop."""
    return await asyncio.to_thread(_grafo_rede_completa_sync, limite)


def _grafo_rede_completa_sync(limite: int = 120):
    try:
        from compliance_agent.cruzamentos_intel import _ob_paga
        from compliance_agent.ugs import nome_canonico
        n_forn = max(10, min(int(limite), 400))
        tot = _siafe_pago_total()
        if tot.get("_top400") is None:
            return JSONResponse(content={"nodes": [], "links": [], "error": tot.get("fonte_total") or "SIAFE indisponível",
                                         "estado": "INDISPONÍVEL"})
        forn = tot["_top400"][:n_forn]
        con = _ro(timeout=30)
        try:
            susp = {r[0] for r in con.execute("SELECT cnpj FROM verificacao_sede WHERE status='INDICIO'")}
            nodes, links, orgaos = [], [], {}
            fid_de = {}
            for f in forn:
                fid = "empresa:" + f["doc"][:24]
                fid_de[f["doc"]] = fid
                nodes.append({"id": fid, "label": (f["nome"] or "")[:40], "tipo": "empresa",
                              "valor": f["total"], "n_obs": f["n"],
                              "severidade": "alta" if f["doc"] in susp else ""})
            docs = list(fid_de)
            if docs:
                ph = ",".join("?" * len(docs))
                for cred, ug, v in con.execute(
                        f"SELECT credor, ug_emitente, SUM(valor) FROM ob_orcamentaria_siafe WHERE credor IN ({ph}) "
                        f"AND {_ob_paga(con)} AND CAST(substr(data_emissao,7,4) AS INTEGER) >= 2021 "
                        "AND ug_emitente IS NOT NULL GROUP BY credor, ug_emitente", docs).fetchall():
                    oid = "orgao:" + str(ug)
                    if oid not in orgaos:
                        orgaos[oid] = {"id": oid, "label": nome_canonico(ug, f"UG {ug}")[:36], "tipo": "orgao"}
                    links.append({"source": fid_de[cred], "target": oid, "tipo": "pagamento", "valor": float(v or 0)})
        finally:
            con.close()
        nodes.extend(orgaos.values())
        return JSONResponse(content={"nodes": nodes, "links": links,
                                     "fonte": "OB paga no SIAFE (régua _ob_paga), 2021 em diante; TFE fora"})
    except Exception as e:
        return JSONResponse(content={"nodes": [], "links": [], "error": str(e)})


@router.get("/api/coendereco/clusters")
def api_coendereco_clusters(min_forn: int = 2, top: int = 50):
    """Padrão do painel (2, 50): visão materializada `coendereco_clusters` (E15). Outro recorte → cálculo legado."""
    if min_forn == 2 and top == 50:
        return _visao("coendereco_clusters") or _legado("coendereco_clusters", _api_coendereco_clusters_legado())
    return _api_coendereco_clusters_legado(min_forn, top)


def _api_coendereco_clusters_legado(min_forn: int = 2, top: int = 50):
    """Descoberta proativa: grupos de fornecedores que dividem a MESMA sede e recebem do Estado.
    Red flag de fachada/laranja (art. 337-F CP). Varre a base de endereços ingeridos."""
    try:
        from compliance_agent.cruzamento import clusters_mesmo_endereco
        top = max(1, min(int(top or 50), 200))
        dados = clusters_mesmo_endereco(min_forn=max(2, int(min_forn or 2)), limite=top)
        return JSONResponse({"ok": dados.get("ok", False), "dados": dados,
                             "aviso": "Indícios de fachada/co-localização para apuração interna — não são acusação."})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/compliance/painel")
def api_painel():
    """Visão materializada `compliance_painel` (E15, sem TTL); ausente → cálculo legado."""
    return _visao("compliance_painel") or _legado("compliance_painel", _api_painel_legado())


def _api_painel_legado():
    """Snapshot completo para o painel: stats, OBs do dia, top, alertas, lições.
    Cacheado 3600s (TTL analítico da casa; o prewarm de 30 min o mantém quente) — com 120s o prewarm
    expirava antes da visita e o panorama abria frio: 30,8 s medidos em 24/09/2026."""
    from compliance_agent.proveniencia_manchetes import anexar as _prov
    if cache := _cache_get("painel:snapshot:v3", 3600):
        return JSONResponse(content=_prov("/api/compliance/painel", cache))
    try:
        from datetime import date
        import sqlalchemy as sa
        from sqlalchemy import desc
        from compliance_agent.database.models import (
            get_session, init_db, OrdemBancaria, Alerta, SessaoAuditoria
        )
        init_db()
        s = get_session()
        try:
            hoje = date.today()
            # espelho TFE: só CONFRONTO (tfe_total/tfe_valor_total, rotulados) — nunca "pago" (24/11/2026)
            total_obs = s.query(sa.func.count(OrdemBancaria.id)).scalar() or 0
            valor_total = s.query(sa.func.sum(OrdemBancaria.valor)).scalar() or 0
            # "OBs hoje" era quase sempre 0 — o espelho chega com atraso, e 0 parecia "nenhum pagamento".
            # O número honesto é o do ÚLTIMO dia que tem OB coletada, com a data ao lado (24/09/2026).
            # O espelho TFE é publicado com ~3 semanas de atraso (fonte, não coleta: jfn-tfe-ob ingere toda segunda);
            # o dia a dia vem do SIAFE, coletado diariamente — só OB Contabilizado. data_emissao do SIAFE é DD/MM/AAAA.
            tfe_ultimo_dia = s.query(sa.func.max(OrdemBancaria.data_emissao)).filter(OrdemBancaria.data_emissao <= hoje).scalar()
            try:
                from sqlalchemy import text as _t
                _iso = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"
                from compliance_agent.cruzamentos_intel import _ob_paga
                paga = _ob_paga(s.connection().connection.driver_connection)
                ultimo_dia, n_ultimo_dia, v_ultimo_dia = s.execute(_t(
                    f"SELECT {_iso} d, count(*), round(sum(valor),2) FROM ob_orcamentaria_siafe WHERE {paga} "
                    f"AND {_iso} <= :h GROUP BY d ORDER BY d DESC LIMIT 1"), {"h": str(hoje)}).one()
            except (sa.exc.SQLAlchemyError, ValueError, TypeError) as exc:  # sem SIAFE o KPI diz INDISPONÍVEL, não 0
                logger.warning("último dia do SIAFE indisponível: %s", exc)
                ultimo_dia, n_ultimo_dia, v_ultimo_dia = None, 0, 0.0
            # "OBs hoje"/"valor hoje" saem do MESMO SIAFE (24/11/2026: vinham do espelho TFE, que publica com ~3
            # semanas de atraso — era sempre 0). Sem SIAFE: None (INDISPONÍVEL), nunca 0.
            if ultimo_dia is None:
                obs_hoje, valor_hoje = None, None
            elif ultimo_dia == str(hoje):
                obs_hoje, valor_hoje = n_ultimo_dia, v_ultimo_dia
            else:
                obs_hoje, valor_hoje = 0, 0.0
            # As 25 OB PAGAS mais recentes do SIAFE (mesma régua `_ob_paga`); o exercício do último dia usa o
            # índice de exercício em vez de varrer as 1,3 mi linhas. Antes: as 25 últimas linhas do espelho TFE.
            obs_recentes = []
            if ultimo_dia:
                try:
                    obs_recentes = [
                        {"numero": r[0], "data": r[1], "favorecido": r[2] or "—", "valor": float(r[3] or 0),
                         "processo": r[4] or "—", "status": r[5] or "—", "ug": r[6]}
                        for r in s.execute(_t(
                            f"SELECT numero_ob, {_iso} d, nome_credor, valor, processo, "
                            "COALESCE(status_envio, status), ug_emitente FROM ob_orcamentaria_siafe "
                            f"WHERE exercicio=:a AND {paga} AND {_iso} <= :h ORDER BY d DESC, numero_ob DESC LIMIT 25"),
                            {"a": int(ultimo_dia[:4]), "h": str(hoje)}).all()]
                except (sa.exc.SQLAlchemyError, ValueError, TypeError) as exc:
                    logger.warning("OB recentes do SIAFE indisponíveis: %s", exc)

            # Só alerta NÃO descartado (13/11/2026): os 58.253 de emprego múltiplo por CPF mascarado foram
            # descartados, mas o card seguia contando a tabela inteira ("59.024 de gravidade alta").
            ativo = sa.or_(Alerta.status.is_(None), Alerta.status != "descartado")
            # ESFERAS ESTANQUES (20/11/2026): a tabela `alertas` junta o motor de regras do Estado, a perícia de
            # gastos da Prefeitura (pcrj_*) e a de emendas federais (emendas_*). O card é do Estado: alta/media/
            # baixa/total passam a ser SÓ dele; as outras duas saem em `por_esfera`, contadas à parte, nunca somadas.
            from compliance_agent.alertas_persistencia import contagem_por_esfera, esfera_do_tipo
            por_esfera = contagem_por_esfera(
                s.query(Alerta.tipo, Alerta.severidade, sa.func.count(Alerta.id)).filter(ativo)
                .group_by(Alerta.tipo, Alerta.severidade).all())
            do_estado = por_esfera.get("estado", {"alta": 0, "media": 0, "baixa": 0, "total": 0})
            alta, media, total_ativos = do_estado["alta"], do_estado["media"], do_estado["total"]
            # De que produtor vem cada alerta aberto e quando ele criou o último (17/11/2026: 1.300+ abertos eram de
            # produtores parados desde 10/08 — emendas, PCRJ D7/D10 — e o card os somava como se fossem de hoje).
            por_tipo = [
                {"tipo": r[0], "esfera": esfera_do_tipo(r[0]), "n": r[1], "alta": int(r[2] or 0),
                 "ultima_criacao": str(r[3])[:16] if r[3] else None}
                for r in (s.query(Alerta.tipo, sa.func.count(Alerta.id),
                                  sa.func.sum(sa.case((Alerta.severidade == "alta", 1), else_=0)),
                                  sa.func.max(Alerta.created_at))
                          .filter(ativo).group_by(Alerta.tipo).order_by(sa.desc(sa.func.count(Alerta.id))).all())
            ]

            alertas = [
                {"tipo": a.tipo, "esfera": esfera_do_tipo(a.tipo), "severidade": a.severidade, "titulo": a.titulo,
                 "descricao": (a.descricao or "")[:300], "data": str(a.data_referencia or ""),
                 "criado": str(a.created_at)[:16]}
                for a in s.query(Alerta).filter(ativo).order_by(desc(Alerta.created_at)).limit(40).all()
            ]
            # verdade = a própria tabela de OBs (SessaoAuditoria parou de ser escrita pelo runner
            # atual e congelava um erro de jun/2026 no painel — desinformação)
            try:
                from sqlalchemy import text as _text
                _ult = s.execute(_text(
                    "SELECT MAX(coletado_em) FROM ob_orcamentaria_siafe")).scalar()
                ultima_coleta = f"{_ult} [siafe_ob] ok" if _ult else "nenhuma ainda"
            except Exception:
                ult = s.query(SessaoAuditoria).order_by(desc(SessaoAuditoria.created_at)).first()
                ultima_coleta = (f"{ult.data_sessao} [{ult.tipo}] {ult.status}"
                                 if ult else "nenhuma ainda")

            licoes = []
            try:
                from compliance_agent.llm.memoria import lembrar
                licoes = [m["valor"][:200] for m in lembrar("licao", session=s)[:8]]
            except Exception as exc:
                logger.warning("lições da memória indisponíveis p/ a investigação: %s", exc)

            siafe = dict(_siafe_pago_total())   # cópia: o dict vem do cache em memória
            top = siafe.pop("top", None)
            top_outros = siafe.pop("top_outros", None)
            credores = siafe.pop("credores", None)
            siafe.pop("_top400", None)
            return JSONResponse(content=_cache_put("painel:snapshot:v3", _prov("/api/compliance/painel", {
                "atualizado": str(hoje),
                "obs": {**_prov("/api/compliance/painel#obs", {"atualizado": str(hoje)}), **siafe, "hoje": obs_hoje, "ultimo_dia": ultimo_dia, "n_ultimo_dia": n_ultimo_dia,
                        "valor_ultimo_dia": v_ultimo_dia,
                        "tfe_ultimo_dia": str(tfe_ultimo_dia) if tfe_ultimo_dia else None,
                        "valor_hoje": valor_hoje,
                        # espelho TFE (cobertura parcial) — rotulado, nunca o número principal (regra OB = SIAFE)
                        "tfe_total": total_obs, "tfe_valor_total": float(valor_total)},
                "alertas": {"alta": alta, "media": media, "baixa": total_ativos - alta - media,
                            "total": total_ativos, "esfera": "estado",
                            "criterio": ("não descartados (status ≠ descartado), só do Estado do RJ; Prefeitura do "
                                         "Rio e emendas federais (fora do escopo) estão em por_esfera, sem somar"),
                            "por_esfera": por_esfera, "por_tipo": por_tipo},
                "ultima_coleta": ultima_coleta,
                "lista_alertas": alertas,
                # None = INDISPONÍVEL (SIAFE não respondeu), nunca lista vazia fingindo "sem favorecido"
                "top_favorecidos": top,
                "top_favorecidos_recorte": ("FORNECEDORES — OB paga no SIAFE (régua _ob_paga), 2021 em diante, credor "
                                            "CNPJ/CPF; tributo, folha, encargo, repasse e ente público em "
                                            "top_outros_credores (peneira canônica: natureza 1xxx da Receita + "
                                            "entidades_gov + encargo/ente do fracionamento)"),
                "top_outros_credores": top_outros,
                "totais_credores": credores,
                "obs_recentes": obs_recentes,
                "obs_recentes_total": siafe.get("total"),   # COR-07: as 25 mais recentes DE quantas OB pagas (SIAFE 2021+)
                "fonte_ob": "OB do SIAFE é a fonte; TFE é espelho e pode ter erro (tfe_* = só confronto)",
                "licoes": licoes,
            })))
        finally:
            s.close()
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/api/compliance/investigar")
async def api_investigar(nome: str = "", cnpj: str = ""):
    """Investiga uma pessoa/empresa na internet (web research)."""
    if not nome:
        return JSONResponse(content={"error": "nome obrigatório"}, status_code=400)
    try:
        from compliance_agent.collectors.web_research import investigar
        dossie = await investigar(nome, cnpj)
        return JSONResponse(content=dossie)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/api/compliance/relatorio_30d")
def api_relatorio_30d():
    """Gera relatório estruturado das OBs dos últimos 30 dias em Markdown."""
    try:
        from datetime import date, timedelta
        from pathlib import Path

        hoje = date.today()
        inicio = hoje - timedelta(days=30)

        # OB PAGA do SIAFE (régua `_ob_paga`) — até 24/11/2026 este relatório lia o espelho TFE, que publica com
        # ~3 semanas de atraso (a janela de 30 dias saía quase vazia) e não tem o status real da OB.
        from compliance_agent.cruzamentos_intel import _ob_paga
        from compliance_agent.reporting.cobertura_siafe import ISO_EMISSAO_SIAFE as _iso
        con = _ro(timeout=30)
        try:
            rows = con.execute(
                f"SELECT numero_ob, processo, credor, nome_credor, ug_emitente, tipo_ob, "
                f"COALESCE(status_envio, status), tipo, {_iso} d, valor FROM ob_orcamentaria_siafe "
                f"WHERE exercicio IN (?, ?) AND {_ob_paga(con)} AND {_iso} BETWEEN ? AND ? "
                "ORDER BY d DESC, numero_ob DESC",
                (inicio.year, hoje.year, str(inicio), str(hoje))).fetchall()
        finally:
            con.close()

        obs_list = []
        erros = []
        for numero, proc, credor, nome, ug, tipo_ob, status, tipo, d, valor in rows:
            ob_info = {
                "id": numero,
                "numero_ob": numero,
                "numero_sei": proc or "—",
                "numero_processo": proc or "—",
                "credor": credor or "",
                "favorecido": nome or "—",
                "ug": ug or "—",
                "tipo": tipo_ob or "—",
                "status": status or "—",
                "categoria": tipo or "outros",
                "data_emissao": d or "—",
                "data_pagamento": "—",
                "valor": float(valor) if valor is not None else 0.0,
            }
            obs_list.append(ob_info)

            if not proc:
                erros.append({
                    "tipo": "processo ausente",
                    "OB": numero,
                    "favorecido": ob_info["favorecido"],
                    "valor": ob_info["valor"],
                })
            elif "SEI" not in proc.upper():
                erros.append({
                    "tipo": "processo fora do formato SEI",
                    "OB": numero,
                    "favorecido": ob_info["favorecido"],
                    "valor": ob_info["valor"],
                    "detalhe": proc,
                })

        resumo = {}
        for ob in obs_list:
            cat = ob["categoria"]
            resumo[cat] = {
                "qtd": resumo.get(cat, {}).get("qtd", 0) + 1,
                "total": resumo.get(cat, {}).get("total", 0.0) + ob["valor"],
            }

        fav_map = {}
        for ob in obs_list:
            key = ob["favorecido"] or "—"
            fav_map[key] = {
                "qtd": fav_map.get(key, {}).get("qtd", 0) + 1,
                "total": fav_map.get(key, {}).get("total", 0.0) + ob["valor"],
                "documento": ob["credor"],
            }
        top_fav = sorted(
            [{"nome": k, **v} for k, v in fav_map.items()],
            key=lambda x: x["total"],
            reverse=True,
        )[:20]

        linhas = []
        linhas.append("# Relatório de Auditoria — Últimos 30 dias")
        linhas.append(f"Gerado em {hoje} | Janela {inicio} a {hoje} | Fonte: OB PAGA do SIAFE (régua _ob_paga); "
                      "o espelho TFE não entra")
        linhas.append("")
        linhas.append(f"- OBs analisadas: {len(obs_list)}")
        linhas.append(f"- Erros coletados: {len(erros)}")
        linhas.append("")

        linhas.append("## Resumo por tipo de OB (SIAFE)")
        for cat, vals in sorted(resumo.items(), key=lambda x: x[1]["total"], reverse=True):
            linhas.append(f"- **{cat}**: {vals['qtd']} OBs | R$ {vals['total']:,.2f}")
        linhas.append("")

        linhas.append("## Top favorecidos")
        linhas.append("| Favorecido | Documento | QTD | Total |")
        linhas.append(" | -- | -- | --: | --: |")
        for f in top_fav:
            linhas.append(
                f"| {f['nome']} | {f['documento']} | {f['qtd']} | R$ {f['total']:,.2f} |"
            )
        linhas.append("")

        if obs_list:
            linhas.append("## OBs")
            linhas.append("| OB | SEI | Processo | Documento | Favorecido | UG | Categoria | Data | Valor |")
            linhas.append(" | -- | -- | -- | -- | -- | -- | -- | -- | --: |")
            for ob in obs_list[:200]:
                linhas.append(
                    f"| {ob['numero_ob'] or ob['id']} | {ob['numero_sei']} | {ob['numero_processo']} | {ob['credor']} | {ob['favorecido']} | {ob['ug']} | {ob['categoria']} | {ob['data_emissao']} | R$ {ob['valor']:,.2f} |"
                )
            linhas.append("")

        if erros:
            linhas.append("## Erros / Pendências (para enviar ao Claude Code)")
            linhas.append("```")
            for er in erros[:200]:
                linhas.append(
                    f"- [{er['tipo']}] OB {er['OB']} | {er['favorecido']} | R$ {er.get('valor', 0):,.2f}"
                    + (f" | {er.get('detalhe', '')}" if er.get('detalhe') else "")
                )
            linhas.append("```")

        relatorio = "\n".join(linhas)
        Path("reports").mkdir(exist_ok=True)
        out = Path(f"reports/relatorio_30d_{hoje}.md")
        out.write_text(relatorio, encoding="utf-8")
        return JSONResponse(content={"ok": True, "path": str(out), "erros_coletados": len(erros)})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/api/compliance/graph")
async def api_compliance_graph():
    """Visão materializada `compliance_graph` (E15); ausente → cálculo legado."""
    return _visao("compliance_graph") or _legado("compliance_graph", await _api_compliance_graph_legado())


async def _api_compliance_graph_legado():
    return await _grafo_rede_completa()


@router.get("/api/compliance/alerts")
def api_compliance_alerts(
    tipo: Optional[str] = None,
    severidade: Optional[str] = None,
    limite: int = 50,
):
    """
    Return list of compliance alerts.

    Query params:
        tipo:       Filter by alert type.
        severidade: Filter by severity (alta | média | baixa).
        limite:     Max results (default 50).
    """
    try:
        from compliance_agent.database.models import Alerta, get_session, init_db

        init_db()
        session = get_session()
        q = session.query(Alerta)
        if tipo:
            q = q.filter(Alerta.tipo == tipo)
        if severidade:
            q = q.filter(Alerta.severidade == severidade)
        alertas = q.order_by(Alerta.created_at.desc()).limit(limite).all()
        result = [
            {
                "id": a.id,
                "tipo": a.tipo,
                "severidade": a.severidade,
                "titulo": a.titulo,
                "descricao": a.descricao,
                "criado_em": str(a.created_at),
            }
            for a in alertas
        ]
        session.close()
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/api/compliance/stats")
def api_compliance_stats():
    """
    Return summary statistics: alerts by tipo/severidade, totals, budget status.
    """
    try:
        from sqlalchemy import func
        from compliance_agent.database.models import (
            Alerta, Contrato, Empresa, Pessoa, get_session, init_db,
        )
        from compliance_agent.llm.router import LLMRouter

        init_db()
        session = get_session()

        from sqlalchemy import or_
        ativo = or_(Alerta.status.is_(None), Alerta.status != "descartado")   # descartado não é alerta

        # Alert counts by severity
        sev_counts = {}
        for row in (session.query(Alerta.severidade, func.count(Alerta.id)).filter(ativo)
                    .group_by(Alerta.severidade).all()):
            sev_counts[row[0] or "desconhecida"] = row[1]

        # Alert counts by tipo
        tipo_counts = {}
        for row in session.query(Alerta.tipo, func.count(Alerta.id)).filter(ativo).group_by(Alerta.tipo).all():
            tipo_counts[row[0] or "outros"] = row[1]

        total_alertas   = session.query(Alerta).filter(ativo).count()
        total_contratos = session.query(Contrato).count()
        total_empresas  = session.query(Empresa).count()
        total_pessoas   = session.query(Pessoa).count()
        session.close()

        # Budget status
        try:
            router = LLMRouter()
            budget = router.status()
        except Exception:
            budget = {}

        return JSONResponse(content={
            "alertas": {
                "total": total_alertas,
                "por_severidade": sev_counts,
                "por_tipo": tipo_counts,
            },
            "contratos": total_contratos,
            "empresas": total_empresas,
            "pessoas": total_pessoas,
            "orcamento": budget,
        })
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/api/compliance/reports")
def api_compliance_reports():
    """List PDF and JSON report files in the reports/ directory."""
    try:
        reports_dir = Path("reports")
        if not reports_dir.exists():
            return JSONResponse(content=[])
        files = []
        for f in sorted(reports_dir.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True):
            stt = f.stat()
            files.append({"name": f.name, "type": "pdf", "size": stt.st_size, "mtime": stt.st_mtime, "url": f"/reports/{f.name}"})
        for f in sorted(reports_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            stt = f.stat()
            files.append({"name": f.name, "type": "json", "size": stt.st_size, "mtime": stt.st_mtime, "url": f"/reports/{f.name}"})
        return JSONResponse(content=files)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/api/compliance/reports/limpar")
def api_compliance_reports_limpar(payload: Optional[dict] = None):
    """Apaga relatórios EFÊMEROS gerados pela sessão web (chamado no page-leave via sendBeacon)
    para não acumular relatórios duplicados na VM. Segurança: só apaga basenames DENTRO de reports/."""
    nomes = (payload or {}).get("nomes") or []
    reports_dir = Path("reports").resolve()
    apagados = []
    for nome in nomes:
        fp = Path("reports") / Path(str(nome)).name  # basename — evita path traversal
        try:
            if fp.resolve().is_relative_to(reports_dir) and fp.exists():
                fp.unlink()
                apagados.append(fp.name)
        except Exception as exc:
            logger.debug("não apagou %s: %s", fp.name, exc)
    return JSONResponse(content={"ok": True, "apagados": apagados})


@router.post("/api/compliance/tse/{ano}")
async def api_tse_download(ano: int):
    """
    Trigger TSE electoral donation download for a given year.
    Returns count of records imported.
    """
    try:
        from compliance_agent.database.models import get_session, init_db
        from compliance_agent.collectors.tse import baixar_doacoes_ano

        init_db()
        session = get_session()
        count = await baixar_doacoes_ano(ano, session)
        session.close()
        return JSONResponse(content={"ano": ano, "registros_importados": count})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


try:                                            # SQLAlchemy embrulha o erro do sqlite3
    from sqlalchemy.exc import DatabaseError as _SADatabaseError
    _ErroDeBanco: tuple = (sqlite3.DatabaseError, _SADatabaseError)
except Exception:                               # pragma: no cover
    _ErroDeBanco = (sqlite3.DatabaseError,)

_FTS_PRONTO = False


def _buscar_fts(q: str, tabela: str) -> dict:
    """Uma passada da busca. Separado da rota para poder ser repetido depois de um erro de banco."""
    global _FTS_PRONTO
    from compliance_agent.database.fts import buscar_contratos_fts, buscar_doerj_fts, buscar_alertas_fts

    if not _FTS_PRONTO:
        # `init_db()` = create_all + migrações + criação dos índices FTS. Rodava a CADA busca:
        # dezenas de DDL por requisição contra o mesmo arquivo que os sweeps escrevem. Isso só
        # precisa acontecer uma vez por processo.
        from compliance_agent.database.models import init_db
        init_db()
        _FTS_PRONTO = True

    result: dict = {}
    if tabela in ("contratos", "todos"):
        result["contratos"] = buscar_contratos_fts(q)
    if tabela in ("doerj", "todos"):
        result["doerj"] = buscar_doerj_fts(q)
    if tabela in ("alertas", "todos"):
        result["alertas"] = buscar_alertas_fts(q)
    if tabela in ("fornecedores", "todos"):
        # Favorecidos de OB (ordens_bancarias) NÃO entram no FTS acima — reusa o
        # resolver do /relatorio (empresas+OB, LIKE + fallback sem-espaço), que
        # casa nomes como "MGS". Sem isto, buscar fornecedor sempre vinha vazio.
        from compliance_agent.reporting.inteligencia import buscar_candidatos
        result["fornecedores"] = buscar_candidatos(q)
    return result


@router.get("/api/compliance/buscar")
def api_compliance_buscar(q: str = "", tabela: str = "todos"):
    """
    FTS5 full-text search across contracts, DOERJ, and alerts.

    Query params:
        q:      Search term.
        tabela: contratos | doerj | alertas | fornecedores | todos (default: todos).
    """
    if not q:
        return JSONResponse(content={"error": "Parâmetro 'q' é obrigatório"}, status_code=400)
    try:
        return JSONResponse(content=_buscar_fts(q, tabela))
    except _ErroDeBanco:
        # "database disk image is malformed" DENTRO do processo do servidor com o arquivo
        # ÍNTEGRO no disco (PRAGMA quick_check=ok, processo novo busca normal): é conexão
        # envenenada, mesma família do WAL-index sumido (fcdf9949). Todo caminho de busca
        # abre conexão sqlite3 nova, então repetir UMA vez já descarta a conexão ruim.
        logger.exception("busca falhou com erro de banco (q=%r, tabela=%r) — tentando de novo", q, tabela)
        try:
            return JSONResponse(content=_buscar_fts(q, tabela))
        except Exception:
            logger.exception("busca falhou de novo (q=%r, tabela=%r)", q, tabela)
            return JSONResponse(
                content={"error": "A busca não respondeu agora — o banco está sendo escrito por um "
                                  "sweep. Tente de novo em alguns segundos."},
                status_code=503)
    except Exception:
        # Nunca devolver str(e) ao cliente: era o traceback do SQLAlchemy (com link do
        # sqlalche.me) estampado na tela do usuário.
        logger.exception("busca falhou (q=%r, tabela=%r)", q, tabela)
        return JSONResponse(content={"error": "A busca não respondeu agora."}, status_code=500)


@router.get("/api/sugestoes")
def api_sugestoes(q: str = "", limite: int = 8):
    """Autocomplete leve: empresas (favorecido_resumo, prefixo no nome ou no CNPJ) +
    nomeados (registros_folha=estado, pcrj_comissionado_candidato=prefeitura). Prefixo
    de ≥2 caracteres (por palavra, não só início do nome inteiro) — sugestão enquanto
    digita, não busca completa (isso é o /api/compliance/buscar, no Enter)."""
    termo = (q or "").strip().upper()
    if len(termo) < 2:
        return JSONResponse({"ok": True, "empresas": [], "nomeados": []})
    lim = max(1, min(int(limite or 8), 20))
    prefixo, meio = f"{termo}%", f"% {termo}%"
    digitos = "".join(c for c in termo if c.isdigit())
    empresas: list[dict] = []
    nomeados: list[dict] = []
    try:
        con = _ro(linhas=True)
        if digitos:
            rows = con.execute(
                "SELECT favorecido_nome nome, favorecido_cpf cnpj, total_pago FROM favorecido_resumo "
                "WHERE favorecido_cpf LIKE ? ORDER BY total_pago DESC LIMIT ?", (digitos + "%", lim)).fetchall()
        else:
            rows = con.execute(
                "SELECT favorecido_nome nome, favorecido_cpf cnpj, total_pago FROM favorecido_resumo "
                "WHERE favorecido_nome LIKE ? OR favorecido_nome LIKE ? "
                "ORDER BY total_pago DESC LIMIT ?", (prefixo, meio, lim)).fetchall()
        empresas = [{"nome": r["nome"], "cnpj": r["cnpj"], "total_pago": r["total_pago"]} for r in rows]
        rows2 = con.execute(
            "SELECT DISTINCT nome, cargo, orgao_nome FROM registros_folha "
            "WHERE nome LIKE ? OR nome LIKE ? LIMIT ?", (prefixo, meio, lim)).fetchall()
        nomeados = [{"nome": r["nome"], "cargo": r["cargo"], "orgao": r["orgao_nome"], "esfera": "estado"}
                    for r in rows2]
        con.close()
    except Exception as e:  # noqa: BLE001 — best-effort: não quebra a caixa de busca
        logger.debug("busca de nomeados do estado falhou (%s) — sugestão segue sem eles", e)
    try:
        conp = _ro("pcrj.db", linhas=True)
        rows3 = conp.execute(
            "SELECT DISTINCT nome_pcrj nome, cargo_pcrj cargo, orgao_pcrj orgao "
            "FROM pcrj_comissionado_candidato WHERE nome_pcrj LIKE ? OR nome_pcrj LIKE ? LIMIT ?",
            (prefixo, meio, lim)).fetchall()
        nomeados += [{"nome": r["nome"], "cargo": r["cargo"], "orgao": r["orgao"], "esfera": "prefeitura"}
                     for r in rows3]
        conp.close()
    except Exception as e:  # noqa: BLE001
        logger.debug("busca de nomeados da prefeitura falhou (%s) — sugestão segue sem eles", e)
    return JSONResponse({"ok": True, "empresas": empresas[:lim], "nomeados": nomeados[:lim]})


@router.get("/api/conflito")
def api_conflito(cnpj: str = "", candidato: str = "", limite: int = 200):
    """Varredura geral (sem filtro): visão materializada `conflito` (E15, sem TTL). Filtro → cálculo legado."""
    if not cnpj and not candidato and limite == 200:
        return _visao("conflito") or _legado("conflito", _api_conflito_legado(cnpj, candidato, limite))
    return _api_conflito_legado(cnpj, candidato, limite)


def _api_conflito_legado(cnpj: str = "", candidato: str = "", limite: int = 200):
    """Onda 2 — Conflito de interesse: doador TSE ↔ (empresa | SÓCIO da empresa) ↔ OB.

    Cruza `doacoes_eleitorais` (TSE) com OBs (TFE/SIAFE) e QSA (`socios_fornecedor`).
    O doador pode ser a contratada OU sócio dela (via='direto'|'socio'). Indício, nunca
    acusação (presunção de legitimidade). Query: cnpj= (foca empresa) | candidato= (foca
    quem recebeu) | nenhum (varredura geral por valor de OB).
    """
    try:
        from compliance_agent.lex_conflito import conflito

        # CACHE (2026-07-24): medido no painel, esta rota levava 13 s TAMBÉM na segunda chamada — era a
        # mais lenta de todas, e sem cache, ao contrário das vizinhas. O cruzamento varre doações do TSE
        # (GROUP BY) e monta o índice de sócios; as duas bases mudam por coleta, não por requisição.
        # TTL de 1 h acompanha o das outras rotas pesadas deste arquivo.
        ck = f"conflito:{cnpj}:{candidato}:{limite}"
        if (cache := _cache_get(ck, 3600)) is not None:
            return JSONResponse(content=cache)
        res = conflito(cnpj=cnpj or None, candidato=candidato or None, limite=limite)
        if res.get("ok"):
            _cache_put(ck, res)
        return JSONResponse(content=res)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


# ─────────────────────────────────────────────────────────────────────────────
# CONTROLE: processos SEI restritos (alimentado pelos sweeps) + flags vermelhos graves
# Endpoints /api/restritos e /api/flags + página /controle (autocontida, dark). 2026-07-14.
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/api/restritos")
def api_restritos(todos: int = 0):
    """Lista de controle dos processos SEI de acesso RESTRITO (data/sei_restritos.json)."""
    try:
        from tools import sei_restritos as _R
        itens = _R.listar(todos=bool(todos))
        return JSONResponse({"ok": True, "n": len(itens), "itens": itens})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(e), "itens": []}, status_code=500)


@router.get("/api/flags")
def api_flags():
    """Flags vermelhos GRAVES da fiscalização (data/flags_graves.json)."""
    try:
        from tools import flags_graves as _F
        itens = _F.listar()
        return JSONResponse({"ok": True, "n": len(itens), "itens": itens})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(e), "itens": []}, status_code=500)


@router.get("/controle")
async def pagina_controle():
    """Pagina de CONTROLE: flags graves + processos SEI restritos. Consome /api/flags e /api/restritos.

    v58: o HTML saiu daqui para `static/jfn-controle.html`. Eram 60 linhas de markup e 40 de CSS
    embutidas numa string Python — um SEGUNDO sistema de design para manter, invisivel para o
    `painel_bump_versao`, para o `auditar_contraste` e para qualquer ferramenta que le `static/`.
    Como arquivo, a tela passa a herdar o CSS do painel e entra no alcance das catracas.
    """
    from fastapi.responses import HTMLResponse
    alvo = RAIZ / "static" / "jfn-controle.html"
    if not alvo.exists():                      # INDISPONIVEL nao e 500: diz o que falta e onde
        return HTMLResponse(
            "<h1>Controle indisponivel</h1><p>O arquivo <code>static/jfn-controle.html</code> "
            "nao esta neste ambiente.</p>", status_code=503)
    return HTMLResponse(alvo.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# CENTRAL DE INTELIGÊNCIA (painel v2) — conluio PNCP, nomeados×candidatos, laranjas
# ─────────────────────────────────────────────────────────────────────────────
import threading as _threading
import time as _time

_cache: dict = {}
# O cache vivia só na memória: cada restart do jfn zerava tudo e o prewarm pagava ~10 min de CPU a load 5
# (03/11/2026: intel/retro 359 s, nepotismo_cruzado 46 s, conflito 44 s). Persistido em disco, o painel
# volta do restart com o último valor; o TTL e o recálculo em 2º plano seguem valendo (o tempo gravado é o original).
_CACHE_DIR = RAIZ / "data" / "cache_painel"


def _cache_arquivo(chave: str) -> Path:
    import hashlib as _hl
    return _CACHE_DIR / (_hl.sha1(chave.encode()).hexdigest() + ".json")


def _cache_carregar_disco() -> None:
    if not _CACHE_DIR.is_dir():
        return
    for f in _CACHE_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            _cache.setdefault(d["k"], (float(d["t"]), d["v"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue                                  # arquivo truncado/alheio: ignora, o cálculo refaz


_cache_carregar_disco()


# Teto de espera por fonte VIVA (PNCP). Health-check de 2026-08-02: /api/pncp e
# /api/sei/direcionamento devolviam `000` — conexão pendurada, sem resposta em 25 s. Fonte
# externa sem teto trava a aba do painel; com teto, ela diz "não respondeu" e o usuário decide.
_TETO_FONTE_VIVA = 20.0


async def _com_teto(coro, rotulo: str):
    """Aguarda `coro` até o teto. Estourou → (None, nota honesta); senão → (valor, None)."""
    teto = _TETO_FONTE_VIVA
    try:
        return await asyncio.wait_for(coro, timeout=teto), None
    except (TimeoutError, asyncio.TimeoutError):
        return None, (f"{rotulo} não respondeu em {teto:.0f}s — INDISPONÍVEL, "
                      "não é ausência de resultado. Tente de novo ou reduza o período.")


# Propagação automática (14/11/2026): o despachante (`compliance_agent/propagacao.py`, FORA deste processo) grava
# em `_invalidar.json` {prefixo da chave: instante}. Valor calculado ANTES da marca conta como vencido — o
# `_cache_calc` entrega o anterior na hora e recalcula em 2º plano (SWR). Sem o arquivo, nada muda.
_INVALIDAR = {"mtime": None, "marcas": {}}


def _cache_invalidado_em(chave: str) -> float:
    arq = _CACHE_DIR / "_invalidar.json"
    try:
        mt = arq.stat().st_mtime_ns
        if mt != _INVALIDAR["mtime"]:
            marcas = json.loads(arq.read_text(encoding="utf-8"))
            _INVALIDAR.update(mtime=mt, marcas={str(p): float(t) for p, t in marcas.items()})
    except (OSError, ValueError, TypeError, AttributeError):
        return 0.0                                    # marca ausente/ilegível: vale só o TTL
    return max((t for p, t in _INVALIDAR["marcas"].items() if chave.startswith(p)), default=0.0)


def _cache_get(chave: str, ttl: int):
    v = _cache.get(chave)
    if v and (_time.time() - v[0]) < ttl and v[0] >= _cache_invalidado_em(chave):
        return v[1]
    return None


def _cache_put(chave: str, val):
    agora = _time.time()
    _cache[chave] = (agora, val)
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        f = _cache_arquivo(chave)
        tmp = f.with_suffix(f".{_threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"k": chave, "t": agora, "v": val}, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(f)
    except (OSError, TypeError, ValueError):
        logger.debug("cache %s: não persistido em disco", chave, exc_info=True)
    return val


_cache_travas: dict = {}
_cache_travas_mestra = _threading.Lock()
# Idade máxima do valor vencido que o `_cache_calc` ainda entrega enquanto recalcula (stale-while-revalidate).
_CACHE_VELHO_MAX_S = 6 * 3600


def _cache_calc(chave: str, ttl: int, calcular):
    """Cache com UM cálculo por chave (single-flight). Sem isto, N visitas com o cache frio disparavam N cálculos
    iguais em paralelo: em 24/09/2026 eram 25 threads refazendo `fornecedor_dependente` ao mesmo tempo, carga 29 em
    2 vCPU e o painel inteiro sem responder por mais de 120 s. Quem chega durante o cálculo espera o resultado.
    Só para rota SÍNCRONA (roda no pool de threads) — em `async def` a trava bloquearia o event loop."""
    if d := _cache_get(chave, ttl):
        return d
    with _cache_travas_mestra:
        trava = _cache_travas.setdefault(chave, _threading.Lock())
    # VENCIDO mas existente: entrega o último valor JÁ e recalcula em segundo plano (stale-while-revalidate).
    # Sem isto, quem chegava logo após o TTL esperava o cálculo inteiro — a fênix, 72,6 s (03/11/2026).
    # …mas só enquanto o "último valor" for RECENTE. O cache vive em disco e volta no restart: em 20/11/2026 a aba
    # Prefeitura › Sancionadas serviu "427 empresas, 5 à época, R$ 143.342,03" — número de antes da régua de esfera
    # de 19/11, calculado por código que já não existia — e a visita seguinte, 83 / 0 / R$ 0,00. Velho demais não é
    # "último valor", é número parado: aí o visitante espera o cálculo (um só, pela trava).
    if (velho := _cache.get(chave)) is not None and _time.time() - velho[0] <= max(_CACHE_VELHO_MAX_S, 4 * ttl):
        if trava.acquire(blocking=False):
            def _renovar():
                try:                                 # falha sobe ao threading.excepthook (logada) e o
                    _cache_put(chave, calcular())    # valor anterior fica; o finally libera a trava
                finally:
                    trava.release()
            _threading.Thread(target=_renovar, daemon=True, name=f"cache:{chave}").start()
        return velho[1]
    with trava:
        if d := _cache_get(chave, ttl):
            return d
        return _cache_put(chave, calcular())


@router.get("/api/certames/lista")
def api_certames_lista(esfera: str = "prefeitura", limite: int = 600, q: str = ""):
    """Recorte do painel (esfera estado|prefeitura, 600, sem busca): visão `certames_<esfera>` (E15, sem TTL)."""
    if esfera in ("estado", "prefeitura") and limite == 600 and not q:
        return (_visao(f"certames_{esfera}")
                or _legado(f"certames_{esfera}", _api_certames_lista_legado(esfera, limite, q)))
    return _api_certames_lista_legado(esfera, limite, q)


def _api_certames_lista_legado(esfera: str = "prefeitura", limite: int = 600, q: str = ""):
    """Certames da base LOCAL, cada um com a SUA análise (Índice de Direcionamento + temas).

    A aba Contratos do painel deixa de depender do PNCP ao vivo (lento/instável) — lê
    edital_documento + certame_indice. `temas` = famílias com sinal (valor>0) do
    familias_json; certame com confiança 0 sai como analisado=False (INDISPONÍVEL ≠ 0,
    nunca "score 0"). Ordena: analisados por prioridade desc, depois os demais por ano."""
    # ESFERA É OBRIGATÓRIA E FECHADA (20/11/2026). Rótulo fora do vocabulário ("estadual", "todas", vazio) caía no
    # `.get()` e a rota devolvia a tabela INTEIRA — 14.015 certames, dos quais mais de 9 mil de órgão federal — na
    # aba de quem pediu. E "estado" era só a raiz 42498600: ALERJ, TJRJ, DETRAN e outros 393 certames de órgão
    # estadual com CNPJ próprio ficavam de fora. A esfera vem do mapa materializado pela régua única (orgao_esfera).
    _ESFERA = {"prefeitura": ("municipal-rio", "42498733"), "estado": ("estadual-rj", "42498600")}
    if esfera not in _ESFERA:
        return JSONResponse(status_code=400, content={
            "ok": False, "erro": f"esfera '{esfera}' não existe — use 'estado' ou 'prefeitura' (esferas estanques; "
                                 "lista vazia ou misturada aqui seria número errado, não resposta)"})
    esfera_regua, raiz_cnpj = _ESFERA[esfera]
    lim = max(1, min(int(limite or 600), 2000))
    termo = f"%{q.strip()}%" if q.strip() else None
    try:
        con = _ro(linhas=True)
        tem_mapa = bool(con.execute("SELECT 1 FROM sqlite_master WHERE name='orgao_esfera'").fetchone())
        # raiz do ente (regra 1 da régua) + órgão com CNPJ próprio que o mapa prova ser da esfera
        onde_esfera = ("(substr(ed.orgao_cnpj,1,8) = ?" + (
            " OR ed.orgao_cnpj IN (SELECT cnpj FROM orgao_esfera WHERE esfera = ?))" if tem_mapa else ")"))
        par_esfera = [raiz_cnpj] + ([esfera_regua] if tem_mapa else [])
        sql = ("SELECT ed.numero_controle_pncp nc, ed.ano, ed.objeto, ed.valor_estimado, "
               "ci.score, ci.faixa, ci.confianca, ci.prioridade, ci.familias_json "
               "FROM edital_documento ed LEFT JOIN certame_indice ci "
               "ON ci.certame = ed.numero_controle_pncp WHERE 1=1")
        params: list = list(par_esfera)
        sql += " AND " + onde_esfera
        if termo:
            sql += " AND ed.objeto LIKE ?"
            params.append(termo)
        sql += (" ORDER BY (ci.confianca IS NULL OR ci.confianca<=0), ci.prioridade DESC, "
                "ed.ano DESC, ed.numero_controle_pncp DESC LIMIT ?")
        params.append(lim)
        rows = con.execute(sql, params).fetchall()
        total = con.execute(
            "SELECT COUNT(*), SUM(EXISTS(SELECT 1 FROM certame_indice ci WHERE "
            "ci.certame=ed.numero_controle_pncp AND ci.confianca>0)) "
            "FROM edital_documento ed WHERE " + onde_esfera, par_esfera).fetchone()
        con.close()
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)
    itens = []
    for r in rows:
        analisado = (r["confianca"] or 0) > 0
        temas = []
        if analisado and r["familias_json"]:
            try:
                fams = json.loads(r["familias_json"])
                temas = sorted(
                    ({"familia": nome, "valor": round(f["valor"], 2)}
                     for nome, f in fams.items() if f.get("apuravel") and (f.get("valor") or 0) > 0),
                    key=lambda t: -t["valor"])
            except (ValueError, TypeError) as e:
                logger.debug("temas por família não somaram (%s) — seção fica vazia, não zerada", e)
        itens.append({"nc": r["nc"], "ano": r["ano"], "objeto": r["objeto"],
                      "valor_estimado": r["valor_estimado"], "analisado": analisado,
                      "score": r["score"] if analisado else None,
                      "faixa": r["faixa"] if analisado else None,
                      "confianca": r["confianca"], "temas": temas})
    return JSONResponse(content={
        "ok": True, "itens": itens, "esfera": esfera,
        "resumo": {"total": total[0], "analisados": total[1] or 0},
        "ressalva": "Índice determinístico e auditável (indício ≠ acusação). Certame sem família "
                    "analisável = INDISPONÍVEL, não zero; a cobertura cresce com o enxame."})


@router.get("/api/pncp/conluio")
def api_pncp_conluio(min_certames: int = 4, esfera: str = ""):
    """Esfera estado com o padrão do painel: visão materializada `pncp_conluio_estado` (E15, sem TTL)."""
    if esfera == "estado" and min_certames == 4:
        return _visao("pncp_conluio_estado") or _legado("pncp_conluio_estado",
                                                        _api_pncp_conluio_legado(min_certames, esfera))
    return _api_pncp_conluio_legado(min_certames, esfera)


def _api_pncp_conluio_legado(min_certames: int = 4, esfera: str = ""):
    """Conluio a partir dos RESULTADOS estruturados do PNCP (vencedor homologado por item):
    CAPTURA (1 fornecedor domina o órgão) e RODÍZIO DE VENCEDORES (poucos se revezam) — com
    nome de fornecedor, nome de órgão e amostra de OBJETOS. ?esfera=estado|prefeitura|municipios|
    federal|outros filtra pela esfera OFICIAL do ente (pncp_ente). Indício OCDE a verificar, não acusação."""
    esf = esfera if esfera in ("estado", "prefeitura", "municipios", "federal", "outros") else None
    ck = f"conluio:{esf or 'todos'}"
    cache = _cache_get(ck, 3600)
    if cache:
        return JSONResponse(cache)
    try:
        from compliance_agent.collectors.pncp_resultados import conluio_enriquecido
        con = _ro()
        try:
            dados = conluio_enriquecido(con, min_certames=max(3, int(min_certames or 4)), esfera=esf)
        finally:
            con.close()
        out = {"ok": True, **dados,
               "esfera": esf or "todos",
               "aviso": "Indício OCDE (bid rigging) para apuração interna — objetos diversos enfraquecem "
                        "a hipótese; corroborar propostas, QSA e cronologia. Não é acusação."}
        return JSONResponse(_cache_put(ck, out))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


_NC_CORPO: dict = {}   # corpo JSON pronto de /api/poder/nomeados_candidatos, por (geração da base, esfera, limite)


@router.get("/api/poder/nomeados_candidatos")
def api_nomeados_candidatos(request: Request, esfera: str = "estado", limite: int = 50000):
    """Servidor/nomeado (folha) × candidato (TSE consulta_cand) — UMA linha por pessoa, com a verificação
    declarada: VERIFICADO (CPF parcial da folha confere com o do TSE) ou PENDENTE ("possível homônimo — não
    verificado"). `total` é o total REAL do recorte; `truncado` diz se o `limite` cortou. Esfera pela fonte da
    folha (Câmara Municipal = municipal). Lógica e motivo em `compliance_agent/nomeados_candidatos.py`."""
    from compliance_agent import nomeados_candidatos as _N

    def _calc():
        con = _ro()
        try:
            return _N.cruzar(con)
        finally:
            con.close()

    try:
        base = _cache_calc("nomcand:v2", 3600, _calc)   # single-flight + SWR; o prewarm de 30 min o mantém quente
        lim = max(1, min(int(limite or 50000), 50000))
        # ~4 MB de JSON: serializar a cada visita custava 3 s a load 20. O corpo pronto fica guardado enquanto a
        # base for a MESMA — chave = instante em que a base foi calculada (o que o cache grava), nunca id() de
        # objeto, que o Python reaproveita depois do GC.
        geracao = (_cache.get("nomcand:v2") or (0.0,))[0]
        ck = (geracao, esfera, lim)
        if (corpo := _NC_CORPO.get(ck)) is None:
            out = _N.recortar(base, esfera)
            out["truncado"] = len(out["itens"]) > lim
            out["itens"] = out["itens"][:lim]
            out["ok"] = True
            out["aviso"] = ("VERIFICADO = os 6 dígitos centrais do CPF publicados na folha conferem com o CPF da "
                            "candidatura no TSE. PENDENTE = só o nome coincide (possível homônimo — não verificado). "
                            "Ser candidato é direito político; o cruzamento é indício de relação "
                            "político-administrativa, não irregularidade.")
            import gzip as _gz
            bruto = json.dumps(out, ensure_ascii=False).encode("utf-8")
            # gzip também pronto: o middleware recomprimia os ~4 MB a cada visita (1,2 s a load 21). Resposta com
            # Content-Encoding já definido o middleware deixa passar.
            corpo = (bruto, _gz.compress(bruto, 6))
            for k in [k for k in _NC_CORPO if k[0] != geracao]:   # guarda só a geração atual da base
                _NC_CORPO.pop(k, None)
            _NC_CORPO[ck] = corpo
        if "gzip" in (request.headers.get("accept-encoding") or "").lower():
            return Response(corpo[1], media_type="application/json",
                            headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
        return Response(corpo[0], media_type="application/json")
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pericias")
def api_pericias(q: str = "", grau: str = "", limite: int = 60, ordem: str = "score"):
    """Ranking pesquisável de perícias de fornecedor (pericia_fornecedor). ?q=nome/cnpj &grau=🟡/🟢/⚪
    &ordem=score|total. Cada fornecedor é agregado (maior grau, soma de OB, achados). Indício."""
    try:
        con = _ro(linhas=True)
        col = "total" if ordem == "total" else "score"
        params: list = []
        where = "WHERE 1=1"
        if q:
            where += " AND (favorecido LIKE ? OR cnpj LIKE ?)"
            params += [f"%{q}%", f"%{q.replace('.', '').replace('/', '').replace('-', '')}%"]
        # O filtro de grau vale sobre o grau AGREGADO do fornecedor (HAVING), não por linha (21/11/2026): com `WHERE
        # grau=?` o chip "Atenção" mostrava como 🟡 quem é 🔴 noutra UG, "Não verificável" listava quem tem 🟡 noutra
        # unidade, e total pago/indícios somavam só as linhas do grau pedido — o fornecedor aparecia menor do que é.
        having = ""
        if grau:
            having = "HAVING grau = ?"
        # ⚪ (nada verificável) é estado próprio: o antigo `ELSE '🟢'` pintava de "limpo" o não-determinado.
        rows = con.execute(
            f"SELECT cnpj, MAX(favorecido) favorecido, "
            f"       CASE WHEN SUM(CASE WHEN grau='🔴' THEN 1 ELSE 0 END)>0 THEN '🔴' "
            f"            WHEN SUM(CASE WHEN grau='🟡' THEN 1 ELSE 0 END)>0 THEN '🟡' "
            f"            WHEN SUM(CASE WHEN grau='🟢' THEN 1 ELSE 0 END)>0 THEN '🟢' ELSE '⚪' END grau, "
            f"       MAX(score) score, SUM(total_pago) total, SUM(n_obs) n_obs, "
            f"       SUM(n_confirmados) confirmados, SUM(n_indicios) indicios, COUNT(DISTINCT ug) ugs "
            f"FROM pericia_fornecedor {where} GROUP BY cnpj {having} "
            f"ORDER BY {col} DESC LIMIT ?", (*params, *([grau] if grau else []),
                                             max(10, min(int(limite or 60), 300)))).fetchall()
        # quantos fornecedores há em cada grau (agregado, mesma busca `q`, sem o filtro de grau) — os chips da aba dizem
        # o tamanho de cada fila em vez de só a página de 80
        por_grau = {g: n for g, n in con.execute(
            "SELECT g, COUNT(*) FROM (SELECT CASE WHEN SUM(grau='🔴')>0 THEN '🔴' WHEN SUM(grau='🟡')>0 THEN '🟡' "
            f"WHEN SUM(grau='🟢')>0 THEN '🟢' ELSE '⚪' END g FROM pericia_fornecedor {where} GROUP BY cnpj) GROUP BY g",
            params).fetchall()}
        con.close()
        itens = [dict(r) for r in rows]
        return JSONResponse({"ok": True, "total": len(itens), "itens": itens,
                             "por_grau": {g: por_grau.get(g, 0) for g in ("🔴", "🟡", "🟢", "⚪")}})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/perfil")
def api_perfil(cnpj: str):
    """Dossiê 360 INSTANTÂNEO de um CNPJ, montado do banco local (sem rede): perícia (grau/achados),
    pagamento (OB total, órgãos), QSA (sócios), sede/fachada, vitórias no PNCP e sinal de laranja.
    O motor da tela de drill-down do painel. Indício a verificar, nunca acusação."""
    dig = "".join(c for c in (cnpj or "") if c.isdigit())
    if len(dig) != 14:
        return JSONResponse({"ok": False, "erro": "informe um CNPJ de 14 dígitos"}, status_code=400)
    try:
        con = _ro(linhas=True)
        out: dict = {"ok": True, "cnpj": dig, "cnpj_fmt": f"{dig[:2]}.{dig[2:5]}.{dig[5:8]}/{dig[8:12]}-{dig[12:]}"}
        # perícia (agrega por CNPJ)
        per = con.execute(
            "SELECT MAX(favorecido) nome, MAX(score) score, SUM(total_pago) total, SUM(n_obs) n_obs, "
            "SUM(n_confirmados) confirmados, SUM(n_indicios) indicios, COUNT(DISTINCT ug) ugs, "
            "CASE WHEN SUM(CASE WHEN grau='🔴' THEN 1 ELSE 0 END)>0 THEN '🔴' "
            "WHEN SUM(CASE WHEN grau='🟡' THEN 1 ELSE 0 END)>0 THEN '🟡' "
            "WHEN SUM(CASE WHEN grau='🟢' THEN 1 ELSE 0 END)>0 THEN '🟢' ELSE '⚪' END grau "
            "FROM pericia_fornecedor WHERE cnpj=?", (dig,)).fetchone()
        out["pericia"] = dict(per) if per and per["nome"] else None
        # achados detalhados (do maior score)
        det = con.execute("SELECT achados_json, resumo FROM pericia_fornecedor WHERE cnpj=? "
                          "ORDER BY score DESC LIMIT 1", (dig,)).fetchone()
        if det:
            try:
                out["achados"] = json.loads(det["achados_json"] or "[]")[:12]
            except (ValueError, TypeError):
                out["achados"] = []
            out["resumo"] = det["resumo"]
        # pagamento + órgãos: OB PAGA do SIAFE (`_ob_paga`), nunca o espelho TFE (21/11/2026: o 360 lia `ordens_bancarias`
        # e mostrava a MGS Clean com R$ 164,9 mi "pagos pelo Estado" — o SIAFE paga R$ 192,4 mi). Sem a tabela do SIAFE o
        # bloco é INDISPONÍVEL (`ob_indisponivel`), nunca zero.
        from compliance_agent.cruzamentos_intel import _ob_paga
        ob = None
        out["orgaos"] = []
        try:
            paga = _ob_paga(con)
            ob = con.execute(f"SELECT COUNT(*) n, COALESCE(SUM(valor),0) v, COUNT(DISTINCT ug_emitente) ugs, "
                             f"MAX(nome_credor) nome FROM ob_orcamentaria_siafe WHERE credor=? AND {paga}",
                             (dig,)).fetchone()
            from compliance_agent import ugs as _ugs
            top_org = con.execute(f"SELECT ug_emitente, SUM(valor) v FROM ob_orcamentaria_siafe "
                                  f"WHERE credor=? AND valor>0 AND {paga} GROUP BY ug_emitente ORDER BY v DESC LIMIT 8",
                                  (dig,)).fetchall()
            out["orgaos"] = [{"ug": r["ug_emitente"], "nome": _ugs.nome_canonico(str(r["ug_emitente"]), fallback=""),
                              "total": r["v"]} for r in top_org]
        except sqlite3.Error as exc:
            out["ob_indisponivel"] = f"SIAFE indisponível: {exc}"
        out["ob"] = {"n": ob["n"], "total": ob["v"], "orgaos": ob["ugs"],
                     "fonte": "SIAFE — OB paga (ob_orcamentaria_siafe, _ob_paga)"} if ob and ob["n"] else None
        out["nome"] = (out.get("pericia") or {}).get("nome") or (ob["nome"] if ob else None) or "—"
        # QSA
        soc = con.execute("SELECT socio_nome, qualificacao, socio_servidor FROM socios_fornecedor "
                          "WHERE cnpj=? LIMIT 12", (dig,)).fetchall()
        out["socios"] = [{"nome": r["socio_nome"], "qualificacao": r["qualificacao"],
                          "servidor": bool(r["socio_servidor"])} for r in soc]
        # sede/fachada
        sede = con.execute("SELECT razao, endereco, municipio, uf, status, nivel, evidencia, "
                           "geo_lat, geo_lon, addr_residencial FROM verificacao_sede WHERE cnpj=? LIMIT 1",
                           (dig,)).fetchone()
        if sede:
            out["sede"] = {"endereco": sede["endereco"], "municipio": sede["municipio"], "uf": sede["uf"],
                           "status": sede["status"], "nivel": sede["nivel"], "evidencia": sede["evidencia"],
                           "residencial": bool(sede["addr_residencial"]),
                           "lat": sede["geo_lat"], "lon": sede["geo_lon"]}
        # vitórias no PNCP
        pncp = con.execute("SELECT COUNT(DISTINCT certame) certames, COALESCE(SUM(valor_homologado),0) v, "
                           "COUNT(DISTINCT orgao_cnpj) orgaos FROM pncp_resultado "
                           "WHERE fornecedor_cnpj=? AND ordem_classificacao=1", (dig,)).fetchone()
        out["pncp"] = {"certames": pncp["certames"], "total": pncp["v"], "orgaos": pncp["orgaos"]} if pncp and pncp["certames"] else None
        # contato/hub (Receita Estabelecimentos) — telefone/e-mail/endereço compartilhados = ninho de fantasmas.
        # ATTACH readonly do DB separado; se não ingerido, campo ausente (INDISPONÍVEL ≠ 0).
        try:
            estab_fp = RAIZ / "data" / "receita_estab.db"
            if estab_fp.exists():
                con.execute(f"ATTACH DATABASE 'file:{estab_fp}?mode=ro' AS estab")
                e = con.execute("SELECT endereco_norm, telefone1, correio_eletronico, situacao_cadastral, cnae_principal "
                                "FROM estab.estabelecimentos WHERE cnpj=? LIMIT 1", (dig,)).fetchone()
                if e:
                    hub = {}
                    for chave, col in (("endereco", "endereco_norm"), ("telefone", "telefone1"), ("email", "correio_eletronico")):
                        val = e[col]
                        if val:
                            n = con.execute(f"SELECT COUNT(DISTINCT cnpj) c FROM estab.estabelecimentos WHERE {col}=?", (val,)).fetchone()["c"]
                            if n >= 5:
                                hub[chave] = n
                    out["estab"] = {"situacao": e["situacao_cadastral"], "cnae": e["cnae_principal"],
                                    "tem_telefone": bool(e["telefone1"]), "tem_email": bool(e["correio_eletronico"]),
                                    "hub_compartilhado": hub or None}
        except Exception as e:  # noqa: BLE001 — enriquecimento opcional; nunca derruba o dossiê
            logger.debug("enriquecimento cadastral do dossiê falhou (%s) — segue sem ele", e)
        # ── MUNICÍPIO DO RIO ──────────────────────────────────────────────────────────────
        # Sem este bloco o dossiê mente por omissão: a empresa clicada numa lente MUNICIPAL
        # abriria uma tela que só fala do Estado ("Pago pelo Estado", órgãos estaduais, perícia
        # estadual) e pareceria não ter movimento algum. Clicável e incompleto é pior que não
        # clicável — o leitor conclui ausência onde há R$ 30,6 bi de universo não consultado.
        out["municipio"] = _perfil_municipio(con, dig)
        # Empresa que só existe no acervo MUNICIPAL vinha com nome "—": o nome era buscado apenas
        # na perícia e na OB estaduais. O dossiê abria mudo justamente para quem chegou por uma
        # lente da Prefeitura — o caminho novo era o que mais precisava do nome.
        if (not out.get("nome") or out["nome"] == "—") and out["municipio"]:
            razoes = out["municipio"].get("razoes_sociais") or []
            if razoes:
                out["nome"] = razoes[0]
        con.close()
        return JSONResponse(out)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


def _perfil_municipio(con, dig: str) -> dict | None:
    """O que o Município do Rio pagou a este CNPJ, e quais lentes municipais o marcaram.

    Agrupa por RAIZ de CNPJ (8 dígitos): 0,96% das raízes do acervo aparecem com mais de uma
    razão social, e agrupar pelo documento inteiro perderia a filial. Devolve `None` quando não
    há pagamento — ausência de dado, que a tela declara em vez de imprimir zero."""
    raiz = dig[:8]
    try:
        from compliance_agent.pcrj.natureza_despesa import ELEMENTOS
        from compliance_agent.pcrj.universo import filtro_sql
    except ImportError:
        return None
    try:
        tot = con.execute(
            f"SELECT count(*) n, sum(pago) v, count(DISTINCT orgao) orgaos, "
            f"min(exercicio) de_, max(exercicio) ate FROM pcrj_despesa "
            f"WHERE substr(replace(replace(replace(credor_documento,'.',''),'/',''),'-',''),1,8)=? "
            f"AND {filtro_sql()}", (raiz,)).fetchone()
        if not tot or not tot["n"]:
            return None
        orgs = con.execute(
            f"SELECT orgao, sum(pago) v FROM pcrj_despesa "
            f"WHERE substr(replace(replace(replace(credor_documento,'.',''),'/',''),'-',''),1,8)=? "
            f"AND {filtro_sql()} GROUP BY 1 ORDER BY 2 DESC LIMIT 6", (raiz,)).fetchall()
        elems = con.execute(
            f"SELECT substr(natureza,5,2) el, sum(pago) v FROM pcrj_despesa "
            f"WHERE substr(replace(replace(replace(credor_documento,'.',''),'/',''),'-',''),1,8)=? "
            f"AND {filtro_sql()} GROUP BY 1 ORDER BY 2 DESC LIMIT 5", (raiz,)).fetchall()
        razoes = [r["n"] for r in con.execute(
            "SELECT DISTINCT credor_nome n FROM pcrj_despesa "
            "WHERE substr(replace(replace(replace(credor_documento,'.',''),'/',''),'-',''),1,8)=?",
            (raiz,))]
    except sqlite3.Error:
        return None
    return {
        "pago": tot["v"] or 0.0, "linhas": tot["n"], "orgaos": tot["orgaos"],
        "periodo": f"{tot['de_']}–{tot['ate']}",
        "razoes_sociais": sorted(x for x in razoes if x),
        "por_orgao": [{"orgao": r["orgao"], "total": r["v"]} for r in orgs],
        "por_elemento": [{"codigo": r["el"], "nome": ELEMENTOS.get(r["el"]), "total": r["v"]}
                         for r in elems],
        "lentes": _lentes_que_marcaram(raiz),
        "_nota": "universo CONTRATUAL (grupo 3/4, aplicação direta, sem folha/dívida/precatório) — "
                 "34,2% do bruto pago pelo Município. Agrupado por RAIZ de CNPJ.",
    }


def _lentes_que_marcaram(raiz: str) -> list:
    """Quais lentes municipais apontaram este CNPJ, lendo o JSON materializado.

    É o que fecha o ciclo do clique: o usuário chega ao dossiê por UMA lente e vê se OUTRAS
    também o marcaram — a convergência entre réguas independentes, que é o sinal forte."""
    caminho = RAIZ / "data" / "lentes_estado.json"
    try:
        estado = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    def _raizes_do_item(item) -> set:
        """As raízes de CNPJ que o item cita — inclusive as aninhadas.

        Cada lente guarda o documento num campo próprio (`cnpj`, `raiz`) e algumas o escondem
        numa lista (`fornecedores`, `raizes`). Varrer só o nível de cima faria a empresa aparecer
        na lista da lente e sumir do próprio dossiê — clicável para um lado, mudo para o outro."""
        achadas = set()
        pilha = [item]
        while pilha:
            no = pilha.pop()
            if isinstance(no, dict):
                for chave, valor in no.items():
                    if chave in ("cnpj", "raiz", "cnpj_basico", "documento") and valor:
                        d = re.sub(r"\D", "", str(valor))
                        if len(d) >= 8:
                            achadas.add(d[:8])
                    elif isinstance(valor, (dict, list)):
                        pilha.append(valor)
            elif isinstance(no, list):
                for v in no:
                    if isinstance(v, (dict, list)):
                        pilha.append(v)
                    elif isinstance(v, str) and len(re.sub(r"\D", "", v)) in (8, 14):
                        achadas.add(re.sub(r"\D", "", v)[:8])
        return achadas

    achados = []
    for nome, bloco in ((estado.get("pcrj") or {}).get("lentes") or {}).items():
        for item in (bloco.get("topo") or []):
            if raiz not in _raizes_do_item(item):
                continue
            achados.append({"lente": nome, "titulo": bloco.get("titulo"),
                            "prevalencia": bloco.get("prevalencia"),
                            "n_na_lente": bloco.get("n"), "item": item})
            break
    return achados


@router.get("/api/fontes/limites")
def api_fontes_limites(fonte: str = ""):
    """O que cada fonte NÃO tem, e o que já foi tentado e não funciona.

    Irmã de `/api/fontes/frescor`: aquela diz se o dado está VELHO, esta diz se ele sequer EXISTE.
    Até agora esse conhecimento vivia só em prosa de handoff — quem não leu o handoff certo retentava
    pelo mesmo caminho bloqueado. Pior: fonte que falha calada devolve `[]`, e `[]` vira "nada
    encontrado" no parecer, que é afirmação falsa por omissão. INDISPONÍVEL ≠ 0.
    """
    from compliance_agent.limites_de_fonte import limites as _limites
    itens = _limites(fonte)
    return JSONResponse({
        "ok": True, "total": len(itens),
        "bloqueios": sum(1 for x in itens if x["tipo"] == "bloqueio"),
        "limites_de_dado": sum(1 for x in itens if x["tipo"] == "limite_de_dado"),
        "itens": itens,
    })


def _idade_dias(ultimo, agora=None):
    """Idade em dias inteiros de um carimbo de coleta. `None` quando não há data legível.

    O `[:19]` da versão anterior DECEPAVA o fuso: quem grava em UTC (`…+00:00`) era lido como hora
    local (UTC−3) e parecia 3 h mais novo — na virada do dia a conta ficava negativa e o painel
    exibia `-1d`. Aqui o carimbo com fuso é respeitado, o sem fuso vale como hora da casa, e o piso
    é 0 (INDISPONÍVEL ≠ 0: data ilegível devolve `None`, nunca "fresquinho").
    """
    import datetime as _d

    agora = agora or _d.datetime.now().astimezone()
    try:
        d = _d.datetime.fromisoformat(str(ultimo).strip())
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=agora.tzinfo)
    return max(0, (agora - d).days)


def _estado_frescor(idade, detalhe: str = "") -> str:
    """ok (≤3 d) · atencao (≤10 d) · critico. Coleta cuja ÚLTIMA tentativa falhou (detalhe com ⛔, ver
    `siafe_runner.detalhe_frescor`) nunca sai 'ok': o dado ainda é novo, mas a coleta está parada (17/11/2026:
    SIAFE com senha recusada aparecia verde)."""
    est = "ok" if idade is not None and idade <= 3 else "atencao" if idade is not None and idade <= 10 else "critico"
    if est == "ok" and str(detalhe or "").startswith("⛔"):
        est = "atencao"
    return est


def _siafe_pago_total() -> dict:
    """KPI de cabeçalho do painel: OB PAGA pelo SIAFE (Contabilizada, sem a devolvida pelo banco) de 2021 em diante,
    o período com coleta completa. Até 18/11/2026 o painel somava o espelho TFE inteiro como "valor fiscalizado"
    (R$ 141,5 bi em 1,2 mi OB) — regra da casa é OB = SIAFE; o pago de 2021–2026 no SIAFE é ~3,5× o do espelho.
    Cache de 30 min (soma de 1,3 mi linhas). INDISPONÍVEL ≠ 0: sem a tabela, total None e o motivo.

    24/11/2026: a MESMA varredura (GROUP BY credor, ~22 s medidos com a VM em carga 14) dá também o `top` de
    credores TERCEIROS (CNPJ/CPF — `SQL_CREDOR_TERCEIRO_SIAFE`, o universo que o espelho sempre listou; folha,
    previdência e repasse entre UGs ficam fora do ranking, mas dentro do total). Até aqui `top_favorecidos` do
    painel somava o espelho TFE inteiro — o 1º lugar era 'Banco do Brasil' com R$ 6,06 bi de linhas TFE."""
    if d := _cache_get("obs:siafe_pago_total:v3", 1800):
        return d
    out = {"total": None, "valor_total": None, "fonte_total": "SIAFE indisponível", "top": None}
    try:
        from compliance_agent.cruzamentos_intel import _ob_paga
        from compliance_agent.reporting.intel_base import SQL_CREDOR_TERCEIRO_SIAFE
        con = _ro(timeout=30)
        try:
            # `+credor`: varre a tabela em ordem física (o índice de credor faria uma leitura aleatória por linha —
            # 154 s medidos contra 22 s, 24/11/2026)
            linhas = con.execute(
                f"SELECT credor, MAX(nome_credor), COUNT(*), COALESCE(SUM(valor),0), ({SQL_CREDOR_TERCEIRO_SIAFE}) "
                f"FROM ob_orcamentaria_siafe WHERE {_ob_paga(con)} "
                "AND CAST(substr(data_emissao,7,4) AS INTEGER) >= 2021 GROUP BY +credor").fetchall()
        finally:
            con.close()
        # 24/11/2026: o ranking de credores TERCEIROS punha em 1º 'MINISTÉRIO DA FAZENDA' (R$ 7,46 bi — tributo
        # retido) e em 2º 'Banco do Brasil' (R$ 5,93 bi — repasse/consignado). Não são fornecedores: a peneira
        # canônica (`classificador_credor`: natureza 1xxx da Receita + entidades_gov + encargo/ente do
        # fracionamento) separa FORNECEDORES de OUTROS CREDORES — rotulados, os dois totais na tela, nada escondido.
        from compliance_agent.cruzamentos_intel import classificador_credor
        con = _ro(timeout=30)
        try:
            motivo_de = classificador_credor(con)
        finally:
            con.close()
        forn, outros = [], []
        cod_interno = [0, 0.0, 0]   # credor que não é CNPJ/CPF: UG (repasse entre unidades), folha/encargo ('CG…')
        for r in linhas:
            if not r[4]:
                cod_interno[0] += r[2]; cod_interno[1] += float(r[3]); cod_interno[2] += 1
                continue
            m = motivo_de(r[1], r[0])
            (outros if m else forn).append((r, m))
        forn.sort(key=lambda x: x[0][3], reverse=True)
        outros.sort(key=lambda x: x[0][3], reverse=True)
        top = [{"nome": r[1] or r[0], "doc": r[0], "total": round(float(r[3]), 2), "n": r[2]} for r, _ in forn[:400]]
        top_outros = [{"nome": r[1] or r[0], "doc": r[0], "total": round(float(r[3]), 2), "n": r[2], "motivo": m}
                      for r, m in outros[:12]]

        def _tot(xs):
            return {"valor": round(float(sum(r[3] for r, _ in xs)), 2), "n_ob": sum(r[2] for r, _ in xs),
                    "n_credores": len(xs)}
        out = {"total": sum(r[2] for r in linhas), "valor_total": round(float(sum(r[3] for r in linhas)), 2),
               "fonte_total": "OB paga no SIAFE (Contabilizada, sem devolvida pelo banco), 2021 em diante",
               "top": top[:12], "_top400": top,   # `_top400`: a rede de pagamentos (/api/compliance/graph), só fornecedor
               "top_outros": top_outros,
               "credores": {
                   "fornecedores": _tot(forn),
                   "outros_credores": {**_tot(outros), "rotulo": "tributos, folha, encargos, repasses e entes públicos "
                                       "(CNPJ/CPF)"},
                   "codigo_interno": {"valor": round(cod_interno[1], 2), "n_ob": cod_interno[0],
                                      "n_credores": cod_interno[2],
                                      "rotulo": "credor-código do SIAFE (UG, folha, encargos) — repasse/folha, "
                                                "não fornecedor"}}}
    except sqlite3.Error as exc:
        out["fonte_total"] = f"SIAFE indisponível: {exc}"
    return _cache_put("obs:siafe_pago_total:v3", out)


@router.get("/api/fontes/frescor")
def api_fontes_frescor():
    """Visão materializada `fontes_frescor` (E15, SLO 1 h); ausente → cálculo legado."""
    return _visao("fontes_frescor") or _legado("fontes_frescor", _api_fontes_frescor_legado())


def _api_fontes_frescor_legado():
    """Frescor de CADA fonte de dados (última coleta + último dado). O painel mostra em verde/âmbar/
    vermelho — defasagem nunca mais passa despercebida (lição SIAFE 16-17/07: MFA quebrou a coleta
    e nada avisava)."""
    from datetime import datetime as _dt
    try:
        from compliance_agent.proveniencia_manchetes import anexar
        if d := _cache_get("fontes:frescor", 3600):
            return JSONResponse(anexar("/api/fontes/frescor", d))
        fontes = []

        def _add(nome, q, con, fmt="iso", detalhe=""):
            try:
                v = con.execute(q).fetchone()[0]
                if fmt == "br" and v:  # DD/MM/AAAA → ISO p/ ordenar
                    v = f"{v[6:10]}-{v[3:5]}-{v[0:2]}"
                fontes.append({"fonte": nome, "ultimo": v, "detalhe": detalhe})
            except Exception as exc:  # noqa: BLE001
                fontes.append({"fonte": nome, "ultimo": None, "detalhe": f"erro: {exc}"})

        con = _ro()
        try:
            from compliance_agent.siafe_runner import detalhe_frescor as _siafe_detalhe
            _add("SIAFE · OB orçamentária (coleta)", "SELECT MAX(coletado_em) FROM ob_orcamentaria_siafe", con,
                 detalhe=_siafe_detalhe("coletor diário 05:00 (MFA mensal)"))
            _add("SIAFE · OB orçamentária (dado)",
                 "SELECT MAX(substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)) "
                 "FROM ob_orcamentaria_siafe WHERE exercicio=(SELECT MAX(exercicio) FROM ob_orcamentaria_siafe)", con,
                 detalhe="data da OB mais nova")
            _add("PNCP · resultados", "SELECT MAX(coletado_em) FROM pncp_resultado", con,
                 detalhe="timer semanal (dom 01:40)")
            # sancoes/folha não têm coletado_em: proxy = data da sanção mais nova / competência mais nova
            _add("Sanções CEIS/CNEP", "SELECT MAX(data_inicio) FROM sancoes_federais", con,
                 detalhe="sanção mais nova · timer semanal (dom 05:40)")
            # folhas: uma linha por FONTE, com esfera (a Câmara do Rio é municipal) e estado próprio — o MAX da
            # tabela inteira encobria Defensoria e TJRJ parados atrás do GESPERJ (20/11/2026)
            from compliance_agent.nomeados_candidatos import frescor_folhas as _frescor_folhas
            folhas = _frescor_folhas(con)
        finally:
            con.close()
        try:
            con2 = _ro("pcrj.db")
            try:
                # MAX(coletado_em) varria 13,7 mi linhas (53 s, 30/10/2026). Cada competência é carregada de uma
                # vez (DELETE + INSERT com o mesmo coletado_em): salta pelo índice de competência, 1 linha por mês.
                _add("PCRJ · folha Prefeitura",
                     "WITH RECURSIVE m(c) AS (SELECT MIN(competencia) FROM pcrj_folha_pref UNION ALL "
                     "SELECT (SELECT MIN(competencia) FROM pcrj_folha_pref WHERE competencia > m.c) FROM m "
                     "WHERE m.c IS NOT NULL) SELECT MAX((SELECT coletado_em FROM pcrj_folha_pref "
                     "WHERE competencia = m.c LIMIT 1)) FROM m WHERE m.c IS NOT NULL", con2)
                _add("PCRJ · comissionados×candidatos",
                     "SELECT MAX(coletado_em) FROM pcrj_comissionado_candidato", con2)
            finally:
                con2.close()
        except Exception as exc:  # noqa: BLE001
            fontes.append({"fonte": "PCRJ", "ultimo": None, "detalhe": f"erro: {exc}"})
        hoje = _dt.now().astimezone()
        for f in fontes:
            idade = _idade_dias(f["ultimo"], hoje)
            f["idade_dias"] = idade
            f["estado"] = _estado_frescor(idade, f.get("detalhe"))
        # as folhas já vêm com idade e estado na régua mensal; entram depois das sanções, onde ficava a linha única
        pos = next((i + 1 for i, f in enumerate(fontes) if f["fonte"].startswith("Sanções")), len(fontes))
        fontes[pos:pos] = [{k: v for k, v in f.items() if k != "chave"} for f in folhas]
        out = {"ok": True, "fontes": fontes, "gerado": hoje.strftime("%Y-%m-%d %H:%M")}
        return JSONResponse(anexar("/api/fontes/frescor", _cache_put("fontes:frescor", out)))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pericia/bateria")
def api_pericia_bateria(so_mortos: bool = False):
    """Cobertura da BATERIA: quais dos 24 testes de perícia REALMENTE rodam, e o que falta.

    ⚠️ Distinta de `/api/pericia/cobertura` (em `rotas/sistema.py`), que mede **quanto do acervo
    já recebeu juízo**. Aqui se mede **quantos testes têm insumo**. Um acervo pode estar
    inteiramente periciado e ainda assim ter 83% dos itens sem exame — é o caso.

    Esta rota existe porque o painel, sem ela, **afirma um trabalho que não houve**. Ele mostra
    31.017 fornecedores periciados e 27.846 "com indício", e isso parece um sistema em pleno
    funcionamento. Medido: **620.108 dos 744.259 itens (83,3%) são INDISPONÍVEL**, **20 dos 24
    testes estão 95%+ indisponíveis** e **nenhum item chega a CONFIRMADO em todo o acervo**.

    A perícia é honesta — cada indisponível traz o motivo por extenso. O que falta é INSUMO, e
    `insumos_que_destravam` diz qual captura resolve quantos testes: a planilha de custos do
    contrato sozinha destrava 6 dos 20.

    ⚠️ INDISPONÍVEL **não é** ausência de irregularidade. É ausência de exame.

    `?so_mortos=1` devolve apenas os testes sem insumo.
    """
    try:
        from tools.bateria_pericia import cobertura
        # 28,8 s medido no percurso do painel (21/11/2026) — varre os 744 mil itens da bateria; o acervo muda por
        # rodada de perícia, não por minuto: 10 min de cache, um cálculo por vez
        r = _cache_calc("pericia:bateria", 600, cobertura)
    except ImportError as exc:
        return JSONResponse({"ok": False, "erro": f"módulo indisponível: {exc}"}, status_code=503)
    except sqlite3.Error as exc:
        return JSONResponse({"ok": False, "erro": f"perícia não disponível: {exc}",
                             "dica": "a tabela pericia_fornecedor pode não ter sido gerada"},
                            status_code=503)
    testes = [x for x in r["testes"] if not x["roda"]] if so_mortos else r["testes"]
    return JSONResponse({
        "ok": True,
        "periciados": r["periciados"],
        "n_testes": r["n_testes"],
        "testes_que_rodam": r["testes_que_rodam"],
        "testes_sem_insumo": r["testes_sem_insumo"],
        # BUG que a conferência ao vivo pegou: estes campos nasceram no módulo DEPOIS da rota, e
        # ela não os repassava — o painel recebia `undefined` e imprimia vazio. Rodar não basta:
        # o teste precisa apontar algo e não apontar quase tudo.
        "testes_uteis": r.get("testes_uteis"),
        "uteis": r.get("uteis"),
        "inertes": r.get("inertes"),
        "nao_discriminam": r.get("nao_discriminam"),
        "itens": r["itens"],
        "itens_indisponiveis": r["itens_indisponiveis"],
        "fracao_indisponivel": r["fracao_indisponivel"],
        "confirmados_no_acervo": r["confirmados_no_acervo"],
        "insumos_que_destravam": r["insumos_que_destravam"],
        "testes": testes,
        "aviso": "INDISPONÍVEL é ausência de EXAME, não de irregularidade. "
                 + str(r.get("_nota") or ""),
    })


@router.get("/api/lentes")
def api_lentes(lente: Optional[str] = None, top: int = 20, esfera: str = "estadual"):
    """Lentes de detecção materializadas: convergência, dependência mútua, sanção, porte.

    Lê `data/lentes_estado.json` (gravado por `tools/lentes_materializar.py`) — NÃO calcula na
    rota: as quatro lentes varrem a OB inteira e somam ~31 s, o que travaria o painel.

    Honestidade: cada lente ORDENA fila de apuração, nenhuma acusa. Lente que falhou na
    materialização volta com `n: null` (INDISPONÍVEL), nunca com zero.
    Filtros: `?lente=convergencia&top=20`.

    `esfera=municipal` devolve as lentes da despesa da PREFEITURA do Rio, que trazem junto o
    `universo_contratual` — o denominador. Sem ele, contagem de lente municipal não se lê: os
    R$ 89,62 bi brutos incluem folha, dívida e precatório, e só R$ 30,64 bi (34,2%) são
    contratação. As municipais também devolvem `prevalencia`, `n_ressalvados` e
    `n_inconclusivos`, porque o que foi qualificado não pode sumir da conta."""
    caminho = RAIZ / "data" / "lentes_estado.json"
    try:
        estado = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return JSONResponse({"ok": False, "erro": f"lentes não materializadas: {exc}",
                             "dica": "rode tools/lentes_materializar.py"}, status_code=503)
    top = max(1, min(int(top or 20), 200))
    if str(esfera).lower().startswith("municip"):
        bloco = estado.get("pcrj") or {}
        lentes = bloco.get("lentes", {})
        if lente:
            if lente not in lentes:
                return JSONResponse({"ok": False, "erro": f"lente municipal desconhecida: {lente}",
                                     "disponiveis": sorted(lentes)}, status_code=404)
            lentes = {lente: lentes[lente]}
        saida = {k: {**v, "topo": (v.get("topo") or [])[:top]} for k, v in lentes.items()}
        return JSONResponse({"ok": True, "esfera": "municipal",
                             "gerado_em": estado.get("gerado_em"),
                             "universo_contratual": bloco.get("universo_contratual"),
                             "lentes": saida, "aviso": estado.get("aviso")})
    lentes = estado.get("lentes", {})
    if lente:
        if lente not in lentes:
            return JSONResponse({"ok": False, "erro": f"lente desconhecida: {lente}",
                                 "disponiveis": sorted(lentes)}, status_code=404)
        lentes = {lente: lentes[lente]}
    saida = {k: {**v, "topo": (v.get("topo") or [])[:top]} for k, v in lentes.items()}
    return JSONResponse({"ok": True, "esfera": "estadual",
                         "gerado_em": estado.get("gerado_em"), "lentes": saida,
                         "aviso": estado.get("aviso")})
