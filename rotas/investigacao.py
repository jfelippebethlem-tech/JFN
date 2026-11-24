# -*- coding: utf-8 -*-
"""Rotas de investigação do JFN (split de server.py em 2026-07-06; rede: tests/test_server_snapshot.py).

Também é a casa do cache do painel (`_cache_get`/`_cache_put`/`_cache_calc`, disco em `data/cache_painel`), que
outras rotas importam — ver docs/untangle/rotas.md, pendência 9.1."""
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


@router.get("/api/anomalias")
def api_anomalias(orgao: Optional[str] = None, fornecedor: Optional[str] = None, top: int = 20,
                        incluir_gov: bool = False):
    """Ranking de OBs suspeitas (Onda 1): score PyOD + red flags determinísticas. Filtros: ?orgao= &fornecedor= &top=.

    Honestidade: cada item é INDÍCIO para investigação interna, NUNCA acusação. Rode antes:
    `python -m compliance_agent.anomalias --rodar`."""
    try:
        from compliance_agent import anomalias
        top = max(1, min(int(top or 20), 200))
        rows = anomalias.top_anomalias(top, orgao, fornecedor, incluir_gov=incluir_gov)
        itens = [{
            "ob": r.get("numero_ob"), "data": r.get("data_emissao"),
            "ug": r.get("ug_codigo"), "ug_nome": r.get("ug_nome"),
            "fornecedor": r.get("favorecido_nome"), "cnpj": r.get("favorecido_cpf"),
            "valor": round(r.get("valor") or 0, 2), "score": round(r.get("score") or 0, 3),
            "regras": r.get("regras"), "parecer": r.get("pareceres"),
            "porque": anomalias.explicar_features(r.get("top_features")),
        } for r in rows]
        # Onda 3 — Benford sobre a população filtrada (UG/fornecedor); só quando há filtro
        # (o agregado global sempre conforma; o desvio aparece no recorte).
        benford = None
        if orgao or fornecedor:
            from compliance_agent.analysis.benford import benford_ob
            benford = benford_ob(orgao, fornecedor)
        modelo = anomalias.estado_modelo()   # INDISPONÍVEL (modelo não rodado sobre o SIAFE) ≠ "0 anomalias"
        return JSONResponse({"ok": True, "n": len(itens) if modelo["estado"] != "INDISPONÍVEL" else None,
                             "itens": itens, "benford": benford, "modelo": modelo,
                             "fonte": "OB paga do SIAFE (régua _ob_paga); TFE fora",
                             "aviso": "Indícios para apuração interna — não constituem acusação."})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/cartel")
@router.post("/api/cartel")  # aceita GET e POST: o Yoda às vezes chuta o método (evita 405 na integração)
def api_cartel(modo: str = "captura", cnpj: Optional[str] = None, top: int = 20):
    """Grafo fornecedor↔órgão (Onda 3). ?modo=captura (UGs concentradas) | dependencia (fornecedores
    presos a 1 órgão) | vizinhanca&cnpj=... (co-ocorrência/rodízio). Indício a verificar, nunca acusação."""
    try:
        from compliance_agent import grafo_cartel as G
        top = max(1, min(int(top or 20), 100))
        # captura/dependencia varrem a base inteira e não dependem de cnpj. Medido 21/11/2026 sob carga: 24 s e 51 s
        # (não ~3 s) → `_cache_calc` (um cálculo por chave + entrega o último valor enquanto recalcula), TTL 1 h:
        # a OB do SIAFE muda por dia, não por minuto.
        if modo in ("captura", "dependencia"):
            def _calc():
                dados = (G.dependencia_fornecedores(limite=top) if modo == "dependencia"
                         else G.captura_orgaos(limite=top))
                return {"ok": True, "modo": modo, "dados": dados,
                        "aviso": "Indícios de captura/cartel para apuração interna — não constituem acusação."}
            return JSONResponse(_cache_calc(f"cartel:{modo}:{top}", 3600, _calc))
        if modo == "vizinhanca":
            if not cnpj:
                return JSONResponse({"ok": False, "erro": "informe ?cnpj="}, status_code=400)
            dados = G.vizinhanca_cartel(cnpj, limite=top)
        elif modo == "rede":  # fornecedores com sócio em comum (Onda 4)
            if not cnpj:
                return JSONResponse({"ok": False, "erro": "informe ?cnpj="}, status_code=400)
            from compliance_agent import rede_societaria as R
            dados = R.rede_por_socio(cnpj)
        elif modo == "cruzado":  # co-ocorrência + sócio comum (persistido socios_fornecedor, top-300)
            if not cnpj:
                return JSONResponse({"ok": False, "erro": "informe ?cnpj="}, status_code=400)
            from compliance_agent import rede_societaria as R
            dados = R.cruzar_cartel(cnpj)
        elif modo == "qsa":  # vizinhança de cartel + QSA cruzado AO VIVO (cadeia BrasilAPI→OpenCNPJ→CNPJ.ws)
            if not cnpj:
                return JSONResponse({"ok": False, "erro": "informe ?cnpj="}, status_code=400)
            dados = G.cartel_com_qsa(cnpj, limite=top)
        else:
            dados = G.captura_orgaos(limite=top)
        out = {"ok": True, "modo": modo, "dados": dados,
               "aviso": "Indícios de captura/cartel para apuração interna — não constituem acusação."}
        return JSONResponse(out)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/rodizio")
@router.post("/api/rodizio")  # aceita GET e POST (o Yoda às vezes chuta o método)
def api_rodizio(ug: Optional[str] = None, top: int = 20, qsa: int = 0):
    """Rodízio temporal de cartel (bid rotation): vencedores que se revezam no topo de uma UG ano a ano.
    ?ug=036100 → analisa uma UG (&qsa=1 cruza sócios dos campeões = concorrência fictícia) | sem ug →
    varredura das UGs com indício. Indício a verificar, nunca acusação."""
    try:
        from compliance_agent import rodizio_temporal as RT
        top = max(1, min(int(top or 20), 100))
        if ug:
            dados = RT.rodizio_com_qsa(str(ug)) if qsa else RT.rodizio_orgao(str(ug))
        else:
            dados = RT.rodizio_varredura(limite=top)
        return JSONResponse({"ok": True, "ug": ug, "dados": dados,
                             "aviso": "Indício de rodízio de vencedores para apuração interna — "
                                      "OB é o pagamento, não a lista de licitantes; corroborar no SEI/PNCP."})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/cruzamento")
async def api_cruzamento(cnpj: str):
    """Cruzamento sócio × OB (SIAFE) × processo SEI × endereço de um fornecedor (Onda 4+).
    Retorna sócios, empresas com sócio em comum (com cidade/mesma sede), fornecedores no MESMO
    endereço (red flag de fachada, independe de sócio), processos SEI e indícios. Indício, nunca acusação."""
    try:
        from compliance_agent.cruzamento import cruzar_async
        dados = await cruzar_async(cnpj)
        return JSONResponse({"ok": True, "dados": dados,
                             "aviso": "Indícios de grupo econômico/fachada para apuração interna — não são acusação."})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/coendereco/clusters")
def api_coendereco_clusters(min_forn: int = 2, top: int = 50):
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


@router.get("/api/orgao/cidades")
def api_orgao_cidades(ug: Optional[str] = None, top: int = 20):
    """Concentração GEOGRÁFICA dos fornecedores de um órgão (ou de todo o Estado se ug ausente):
    em que cidades se sediam quem o órgão paga. Red flag de fachada/direcionamento (art. 337-F CP)."""
    try:
        from compliance_agent.cruzamento import cidades_de_orgao
        top = max(1, min(int(top or 20), 100))
        dados = cidades_de_orgao(ug=ug, limite=top)
        return JSONResponse({"ok": dados.get("ok", False), "dados": dados})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/compliance/painel")
def api_painel():
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


@router.get("/api/fachada/revisar")
def api_fachada_revisar(limite: int = 50):
    """Lista fachadas FLAGRADAS ainda sem veredito humano, p/ o validador do painel (revisão 1-a-1).
    Maior valor primeiro. Inclui motivo do flag, endereço e coordenada (link Street View no front)."""
    try:
        con = _ro(linhas=True)
        vetados = {r[0] for r in con.execute("SELECT cnpj FROM fachada_veredito WHERE status IN ('real','pular','fachada','indicio')")}
        rows = con.execute(
            "SELECT cnpj, razao, endereco, municipio, uf, total_recebido, nivel, evidencia, geo_lat, geo_lon, "
            "places_status, visual_classe FROM verificacao_sede "
            "WHERE nivel IN ('SEM_GOOGLE','FECHADO_GOOGLE','REVISAR_FACHADA') "
            "ORDER BY total_recebido DESC LIMIT ?", (max(1, min(int(limite), 500)),)).fetchall()
        con.close()
        out = [dict(r) for r in rows if r["cnpj"] not in vetados]
        return JSONResponse(content={"ok": True, "total": len(out), "fachadas": out})
    except Exception as e:
        return JSONResponse(content={"ok": False, "erro": str(e)})


@router.post("/api/fachada/veredito")
def api_fachada_veredito(payload: Optional[dict] = None):
    """Salva o veredito HUMANO do validador. Body: {cnpj, veredito: suspeito|ok|mais_info, nota?}.
    suspeito→fachada (mantém INDICIO); ok→real (volta AFASTADO); mais_info→pular (fica pendente)."""
    import datetime as _dt
    p = payload or {}
    cnpj = str(p.get("cnpj") or "").strip()
    ver = str(p.get("veredito") or "").strip().lower()
    nota = str(p.get("nota") or "")[:480]
    mapa = {"suspeito": ("fachada", "INDICIO"), "ok": ("real", "AFASTADO"), "mais_info": ("pular", None)}
    if not cnpj or ver not in mapa:
        return JSONResponse(content={"ok": False, "erro": "cnpj e veredito (suspeito|ok|mais_info) obrigatórios"})
    status_vd, novo_status = mapa[ver]
    try:
        con = sqlite3.connect(RAIZ / "data" / "compliance.db", timeout=30); con.execute("PRAGMA busy_timeout=30000")
        row = con.execute("SELECT razao, endereco, total_recebido FROM verificacao_sede WHERE cnpj=?", (cnpj,)).fetchone()
        razao, endereco, tr = (row or ("", "", 0))
        con.execute(
            "INSERT INTO fachada_veredito (cnpj, razao, endereco, total_recebido, status, veredito_raw, veredito_em) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(cnpj) DO UPDATE SET status=excluded.status, "
            "veredito_raw=excluded.veredito_raw, veredito_em=excluded.veredito_em",
            (cnpj, razao, endereco, tr, status_vd, nota, _dt.datetime.now().isoformat(timespec="seconds")))
        if novo_status:
            con.execute("UPDATE verificacao_sede SET status=? WHERE cnpj=?", (novo_status, cnpj))
        con.commit(); con.close()
        return JSONResponse(content={"ok": True, "cnpj": cnpj, "veredito": status_vd})
    except Exception as e:
        return JSONResponse(content={"ok": False, "erro": str(e)})


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


@router.get("/api/pncp")
async def api_pncp(uf: str = "RJ", orgao: str = "", cnpj: str = "", id: str = "",
                   abertos: bool = False, modalidade: int = 0, dias: int = 30,
                   esfera: str = ""):
    """Onda 2 — PNCP (API pública de consulta, sem login): licitação SEM depender do SEI.

    - id= : ANÁLISE PROFUNDA de uma contratação (numeroControlePNCP) — baixa o edital/TR
      (PDF/ZIP/DOCX) e roda os red flags R3/R5/R7/R9/R12 do Lex sobre o texto real (Onda 2c).
    - cnpj= : contratos de um FORNECEDOR (CNPJ) no período (API de gestão).
    - senão : contratações publicadas (histórico) ou com PROPOSTA EM ABERTO (abertos=true,
      fiscalização preventiva), filtráveis por uf/orgão(cnpj)/modalidade. modalidade=0 varre
      as de maior risco (pregão/dispensa/inexigibilidade/concorrência). dias = janela de busca.
    Retorno: {ok, modo, ...}. Indício, nunca acusação (presunção de legitimidade).
    """
    from datetime import date, timedelta

    try:
        from compliance_agent.collectors import pncp

        hoje = date.today()
        if id:
            from compliance_agent.lex import analisar_texto_edital

            docs = await pncp.baixar_documentos(id)
            texto = "\n".join(d.get("texto", "") for d in docs)
            analise = analisar_texto_edital(texto, numero=id)
            # não devolve o texto bruto (grande) — só metadados dos docs + os achados
            docs_meta = [{k: d[k] for k in ("titulo", "tipo", "url", "n_chars")} for d in docs]
            return JSONResponse(content={
                "ok": True, "modo": "analise", "id_pncp": id,
                "docs": docs_meta, "lido": analise["lido"],
                "red_flags": analise["achados"],
                "_fonte": "PNCP API (arquivos do edital) + motor Lex R1-R12",
                "_nota": "Indício a verificar (presunção de legitimidade); achados sobre o TEXTO "
                         "lido do edital. lido=false => download/extração não retornou texto."})
        if cnpj:
            contratos = await pncp.buscar_contratos_fornecedor(
                cnpj, hoje - timedelta(days=max(dias, 365)), hoje)
            return JSONResponse(content={"ok": True, "modo": "fornecedor", "cnpj": cnpj,
                                         "n": len(contratos), "contratos": contratos,
                                         "_fonte": "PNCP API consulta (sem login)"})
        ck = f"pncp:{uf}:{orgao}:{abertos}:{modalidade}:{dias}:{esfera}"
        if (cache := _cache_get(ck, 3600)) is not None:
            return JSONResponse(content=cache)
        contratacoes, nota = await _com_teto(pncp.buscar_contratacoes(
            uf=uf, data_ini=hoje - timedelta(days=dias), data_fim=hoje,
            modalidade=(modalidade or None), abertos=abertos,
            orgao_cnpj=(orgao or None)), "PNCP")
        if nota:  # indisponibilidade NÃO entra no cache: congelaria a aba vazia por 1 h
            return JSONResponse(content={
                "ok": True, "indisponivel": True, "uf": uf, "n": 0, "contratacoes": [],
                "_fonte": "PNCP API consulta (sem login)", "_nota": nota})
        if esfera and esfera != "todas":
            # esfera OFICIAL do ente (pncp_ente + exceções de unidade) — aba estanque no painel
            from compliance_agent.collectors.pncp_resultados import (
                classificar_esfera, esferas_por_ente)
            _c = _ro()
            try:
                oficial = esferas_por_ente(_c)
            finally:
                _c.close()
            contratacoes = [x for x in contratacoes if classificar_esfera(
                {"orgao_cnpj": x.get("orgao_cnpj"), "orgao_nome": x.get("orgao"),
                 "unidade_nome": x.get("unidade"), "municipio": x.get("municipio")},
                oficial) == esfera]
        return JSONResponse(content=_cache_put(ck, {
            "ok": True, "modo": "abertos" if abertos else "publicacao",
            "uf": uf, "n": len(contratacoes), "contratacoes": contratacoes,
            "_fonte": "PNCP API consulta (sem login)",
            "_nota": "Indício/triagem; red_flags do edital virão da Onda 2c. Proveniência: link+id_pncp."}))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/sobrepreco")
async def api_sobrepreco(codigo: int, valor: float = 0, servico: bool = False):
    """Onda 3 (R4) — Sobrepreço: preço pago vs mediana de referência de mercado.

    codigo = CATMAT (material) ou CATSER (servico=true). valor = preço pago a comparar.
    Fonte: Compras Dados Abertos. Honesto: sem amostra => mediana_ref=null/INDISPONÍVEL;
    o % é indício a verificar (especificação/quantidade/região podem justificar), nunca acusação.
    """
    try:
        from compliance_agent.sobrepreco import sobrepreco

        res = await sobrepreco(codigo, valor_pago=(valor or None), servico=servico)
        return JSONResponse(content=res)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/empresa")
def api_empresa(cnpj: str):
    """Onda 12 (providers) — cadastro + sócios (QSA) por CNPJ, fonte hospedada (BrasilAPI→cnpj.pw).
    Sem baixar base: HTTP sob demanda + cache TTL. Resposta com proveniência (fonte+data+estado)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("registry", cnpj=cnpj).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/idoneidade")
def api_idoneidade(cnpj: str = "", nome: str = ""):
    """Onda 12 (providers) — triagem em listas: CEIS/CNEP (BR) + sanções/PEP (OpenSanctions).
    lookup_all: consulta todos os backends disponíveis. Indício a confirmar, nunca acusação."""
    try:
        from compliance_agent.providers import get_providers
        res = get_providers().lookup_all("sanctions", cnpj=(cnpj or None), nome=(nome or None))
        return JSONResponse(content={"resultados": [r.__dict__ for r in res]})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/ownership")
def api_ownership(nome: str = "", lei: str = ""):
    """Onda 12 (providers) — controle internacional (LEI + relações) via GLEIF (sem chave)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("ownership", nome=(nome or None), lei=(lei or None)).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/leaks")
def api_leaks(termo: str):
    """Onda 12 (providers) — busca hospedada em vazamentos offshore (ICIJ; link MANUAL)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("leaks", termo=termo).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/links")
def api_links(nome: str = "", cnpj: str = ""):
    """Onda 12 (providers) — pistas de investigação HOSPEDADA (Max Intel, OSINT-Brazuca, Bellingcat,
    RedeCNPJ, JusBrasil/Escavador). Deep-links já preenchidos com o alvo; uso MANUAL (o JFN só monta)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("links", nome=(nome or None), cnpj=(cnpj or None)).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/diario")
def api_diario(querystring: str, territory_ids: str = "", desde: str = "", ate: str = "", size: int = 20):
    """Onda 12 (providers) — diários oficiais municipais (Querido Diário). Busca por palavra-chave +
    território IBGE (RJ capital = 3304557) + janela de datas. Sem chave; on-demand + cache."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("gazettes", querystring=querystring, territory_ids=territory_ids,
                                           desde=desde, ate=ate, size=size).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/doador_contrato")
def api_doador_contrato(cnpj: str):
    """Onda 12 (providers) — TSE doador×contrato: sócios (QSA) do fornecedor que aparecem como
    doadores de campanha (RJ). Indício de conflito a CONFERIR, nunca acusação (CPF mascarado → casa
    por nome). Requer doacao_tse populado (carregar_doacoes_rj(ano))."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("eleitoral", cnpj=cnpj).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/grafo")
def api_grafo(alvo: str, saltos: int = 2, so_contrato: bool = False):
    """Onda 4 — Grafo de Poder: vizinhança de um alvo (CNPJ/UG/nome) unindo
    sócios+OB+doações+folha+co-endereço, até `saltos`. so_contrato=true foca o fluxo
    de dinheiro (cnpj↔ug↔sócio). Vínculo = indício de relação, nunca prova."""
    try:
        from compliance_agent.grafo_poder import vizinhanca

        return JSONResponse(content=vizinhanca(alvo, saltos=saltos, so_contrato=so_contrato))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/grafo/ftm")
def api_grafo_ftm(alvo: str, saltos: int = 2):
    """Onda 12 — Export do Grafo de Poder no modelo FollowTheMoney (interoperar c/ Aleph/Gephi)."""
    try:
        from compliance_agent.grafo_ftm import export
        return JSONResponse(content=export(alvo, saltos=saltos))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/sei/acatamento")
async def api_sei_acatamento(processo: str = ""):
    """Auditoria de ACATAMENTO de pareceres (art. 53 Lei 14.133; dossiê mestre §4): a autoridade
    acolheu, contrariou motivadamente, silenciou ou ignorou os pareceres de PGE/PGM/CGE/CGM/jurídico?
    Lê o ARQUIVO compacto do processo (regra da casa: arquivo antes de browser). ?processo=SEI-.../nº."""
    if not (processo or "").strip():
        return JSONResponse({"ok": False, "erro": "informe ?processo=<nº SEI>"}, status_code=400)
    try:
        from compliance_agent.sei_recomendacoes import auditar_acatamento
        from tools.backfill_dossie_mestre import ARQUIVO, _leitura_do_arquivo

        slug = "".join(c if c.isalnum() else "_" for c in processo.replace("SEI-", "")).strip("_")
        pdir = ARQUIVO / slug
        leitura = await asyncio.to_thread(_leitura_do_arquivo, pdir)
        if not leitura:
            return JSONResponse({"ok": False, "erro": f"processo '{processo}' sem arquivo compacto em "
                                 "data/sei_arquivo (rode tools/sei_consultar primeiro) — INDISPONÍVEL ≠ 0"},
                                status_code=404)
        docs = [{"ref": d["doc"], "tipo": d["doc"], "texto": d["conteudo"]}
                for d in leitura["conteudo_documentos"]]
        r = await asyncio.to_thread(auditar_acatamento, docs)
        return JSONResponse({"ok": True, "processo": leitura["numero"], "n_docs": len(docs), **r})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/sei/direcionamento")
async def api_sei_direcionamento(ug: str = "", objeto: str = "", uf: str = "RJ", max_itens: int = 8):
    """Onda 5 — Varredor de direcionamento: busca editais (PNCP), extrai por schema, roda
    red flags do Lex e ranqueia por gravidade. ?ug= (cnpj órgão) &objeto= (filtro). Indício
    de restrição/direcionamento a verificar, nunca acusação."""
    try:
        from compliance_agent.sei_direcionamento import varrer_direcionamento

        ck = f"seidir:{uf}:{ug}:{objeto}:{max_itens}"
        if (cache := _cache_get(ck, 3600)) is not None:
            return JSONResponse(content=cache)
        res, nota = await _com_teto(
            varrer_direcionamento(uf=uf, ug=(ug or None), objeto=(objeto or None),
                                  max_itens=max(1, min(int(max_itens), 15))),
            "PNCP (varredura de direcionamento)")
        if nota:
            return JSONResponse(content={"ok": True, "indisponivel": True, "itens": [],
                                         "_nota": nota})
        return JSONResponse(content=_cache_put(ck, res))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.post("/api/radar/vigiar")
def api_radar_vigiar(payload: Optional[dict] = None):
    """Onda 6 — Radar: adiciona um alvo à watchlist 24/7. Body {"alvo","tipo":cnpj|ug|nome|objeto}.
    Ao surgir edital aberto restritivo / OB anômala do alvo, chega alerta no Telegram."""
    try:
        from compliance_agent.radar import vigiar

        p = payload or {}
        return JSONResponse(content=vigiar(p.get("alvo", ""), p.get("tipo", "cnpj")))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/radar/status")
def api_radar_status():
    """Onda 6 — Radar: o que está sendo vigiado + últimos alertas."""
    try:
        from compliance_agent.radar import status as radar_status

        return JSONResponse(content=radar_status())
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.post("/api/radar/ciclo")
async def api_radar_ciclo():
    """Onda 6 — Radar: roda um ciclo de vigilância agora (o timer systemd chama isto)."""
    try:
        from compliance_agent.radar import ciclo

        return JSONResponse(content=await ciclo())
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.post("/api/nucleo/comando")
async def api_nucleo_comando(payload: dict = None):
    """Núcleo de perícia INTERATIVO (/pericia, /veredito, /placar, /fantasma, /fases, /promover,
    /ciclo_nucleo, /fornecedor, /parametros, /evolucao) — religa o núcleo ao Yoda vivo (gateway).
    Os handlers só existiam no bot de comandos DESATIVADO (yoda.service, 2026-06-06); o lado batch
    (timer 06:30) vivia, mas o interativo/feedback humano estava inalcançável (achado 2026-07-11).

    payload: {comando: "/pericia", args: "..."} OU {texto: "pericia a MGS Clean"} (roteador
    determinístico interpretar_texto_livre, sem LLM). Retorno: {ok, comando, resposta(markdown)}."""
    try:
        from compliance_agent.nucleo import telegram_nucleo as tn

        p = payload or {}
        comando = str(p.get("comando") or "").strip().lower()
        args = str(p.get("args") or "").strip()
        if not comando:
            interp = tn.interpretar_texto_livre(str(p.get("texto") or "").strip())
            if not interp:
                return JSONResponse(content={"ok": False, "erro": "pedido não reconhecido pelo roteador "
                                             "determinístico — use {comando, args} explícito"}, status_code=422)
            comando, args = interp
        handlers = {"/pericia": lambda: tn.cmd_pericia(args), "/veredito": lambda: tn.cmd_veredito(args),
                    "/fantasma": lambda: tn.cmd_fantasma(args), "/fases": lambda: tn.cmd_fases(args),
                    "/certame": lambda: tn.cmd_certame(args),
                    "/promover": lambda: tn.cmd_promover(args), "/placar": tn.cmd_placar,
                    "/ciclo_nucleo": tn.cmd_ciclo_nucleo, "/fornecedor": lambda: tn.cmd_fornecedor(args),
                    "/parametros": tn.cmd_parametros, "/evolucao": tn.cmd_evolucao}
        fn = handlers.get(comando)
        if fn is None:
            return JSONResponse(content={"ok": False, "erro": f"comando desconhecido: {comando}",
                                         "comandos": sorted(handlers)}, status_code=422)
        resposta = await asyncio.to_thread(fn)
        return JSONResponse(content={"ok": True, "comando": comando, "args": args, "resposta": resposta})
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


@router.get("/api/laranjas")
def api_laranjas(limite: int = 100):
    """Sócios de fornecedores do Estado que RECEBEM benefício social de subsistência (bolsa família etc.)
    — indício clássico de LARANJA/interposição (art. 337-F CP): quem figura como dono de empresa que
    recebe do Estado não deveria depender de auxílio. Só os confirmados (recebe_beneficio=1)."""
    try:
        con = _ro(linhas=True)
        rows = con.execute(
            "SELECT socio_nome_norm, cpf_resolvido, beneficios_json, motivo, confianca "
            "FROM socio_beneficio WHERE recebe_beneficio=1 ORDER BY confianca DESC LIMIT ?",
            (max(10, min(int(limite or 100), 500)),)).fetchall()
        con.close()
        itens = []
        for r in rows:
            try:
                bens = json.loads(r["beneficios_json"] or "[]")
            except (ValueError, TypeError):
                bens = []
            cpf = re.sub(r"\D", "", r["cpf_resolvido"] or "")
            # fail-CLOSED: valor não-canônico (≠11 dígitos) vira "***" — nunca ecoar o bruto
            cpf_masc = f"***.{cpf[3:6]}.{cpf[6:9]}-**" if len(cpf) == 11 else ("***" if cpf else "")
            itens.append({"socio": r["socio_nome_norm"], "cpf": cpf_masc,  # LGPD: nunca CPF completo
                          "beneficios": bens if isinstance(bens, list) else [str(bens)],
                          "motivo": r["motivo"], "confianca": r["confianca"]})
        out = {"ok": True, "total": len(itens), "itens": itens,
               "aviso": "Indício de laranja/interposição (art. 337-F CP) a verificar — receber benefício "
                        "não é ilícito; o sinal é ser SÓCIO de empresa que recebe do Estado E depender de auxílio."}
        return JSONResponse(out)
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


# ── INTELIGÊNCIA 2026-07-17: sancionadas × contratadas, perdedoras contumazes, fantasmas ──

@router.get("/api/intel/sancionadas")
def api_intel_sancionadas(limite: int = 60):
    """Empresas com sanção IMPEDITIVA (CEIS/CNEP) que receberam OB do Estado ou venceram no PNCP —
    com o teste temporal "à época" (ato DENTRO da vigência da sanção). Cache materializado por
    tools/intel (cruzamentos_intel.gerar_cache_intel); fallback = computa na hora."""
    try:
        from compliance_agent.cruzamentos_intel import ler_cache_intel, sancionadas_contratadas
        d = ler_cache_intel("sancionadas_contratadas")
        if not d:
            d = _cache_calc("intel:sanc", 3600, lambda: sancionadas_contratadas())
        d = dict(d)
        # teto explícito 1000 > n atual (770): cobre a base inteira (~839 KB, leitura de cache)
        d["empresas"] = d.get("empresas", [])[:max(1, min(int(limite or 60), 1000))]
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/doerj/tac_recorrente")
def api_doerj_tac_recorrente(top: int = 20):
    """Termos de Ajuste de Contas publicados no DOERJ (PDF integral, desde 09/09/2026) — quem recebe
    sem cobertura contratual, quantas vezes, quanto. Materializado por tools/doerj_tac_recorrente
    (cruzador 23:00). Valores são os PUBLICADOS nos extratos, não OB; fornecedor '(não lido)' = extrato
    sem campo PARTES legível (conta na soma, não no ranking)."""
    con = _ro()
    try:
        try:
            tot = con.execute("SELECT count(*), count(valor), round(sum(valor),2), min(data_doe), max(data_doe), "
                              "count(DISTINCT fornecedor) FROM doerj_tac").fetchone()
        except sqlite3.OperationalError:
            return JSONResponse({"ok": True, "aviso": "doerj_tac ainda não materializada", "total": 0, "itens": []})
        itens = [dict(zip(("fornecedor", "n", "n_com_valor", "soma", "n_orgaos", "de", "ate", "processos"), r))
                 for r in con.execute(
                     "SELECT fornecedor, count(*), count(valor), round(sum(valor),2) AS soma, count(DISTINCT orgao), "
                     "min(data_doe), max(data_doe), count(DISTINCT processo) FROM doerj_tac "
                     "WHERE fornecedor IS NOT NULL GROUP BY fornecedor ORDER BY count(*) DESC, soma DESC LIMIT ?",
                     (max(1, min(int(top or 20), 200)),))]
        orgaos = [dict(zip(("orgao", "n", "soma"), r)) for r in con.execute(
            "SELECT coalesce(orgao,'(não lido)'), count(*), round(sum(valor),2) FROM doerj_tac GROUP BY 1 "
            "ORDER BY 2 DESC LIMIT 8")]
        # sinais de favorecimento por fornecedor (tools/doerj_tac_favorecimento, cruzador 1d) — 🔴 antes
        sinais: dict[str, list] = {}
        try:
            for f, grau, sinal, det in con.execute(
                    "SELECT fornecedor, grau, sinal, detalhe FROM doerj_tac_sinal WHERE sinal <> 'cnpj_nao_localizado'"):
                sinais.setdefault(f, []).append({"grau": grau, "sinal": sinal, "detalhe": det})
        except sqlite3.OperationalError:
            logger.debug("investigacao.py:1693: exceção ignorada (era except-pass mudo)", exc_info=True)
        for it in itens:
            it["sinais"] = sorted(sinais.get(it["fornecedor"], []), key=lambda x: x["grau"] != "🔴")
        nao_lidos = con.execute("SELECT count(*) FROM doerj_tac WHERE fornecedor IS NULL").fetchone()[0]
        edicoes = con.execute("SELECT count(DISTINCT data_publicacao) FROM publicacoes_doerj").fetchone()[0]
        # controle externo do extrator (10/09): processo do TAC → credor da OB no SIAFE; None = ainda não medido
        concordancia = None
        try:
            _m = con.execute("SELECT valor, texto, em FROM doerj_tac_meta WHERE chave='concordancia_siafe'").fetchone()
            if _m:
                concordancia = {"taxa": _m[0], "texto": _m[1], "em": _m[2]}
        except sqlite3.OperationalError:
            logger.debug("investigacao.py:1705: exceção ignorada (era except-pass mudo)", exc_info=True)
    finally:
        con.close()
    return JSONResponse({"ok": True, "total": tot[0], "com_valor": tot[1], "soma": tot[2] or 0, "de": tot[3],
                         "ate": tot[4], "fornecedores": tot[5], "nao_lidos": nao_lidos, "edicoes": edicoes,
                         "itens": itens, "orgaos": orgaos, "concordancia": concordancia,
                         "sinais_total": sum(len(v) for v in sinais.values()),
                         "sinais_vermelhos": sum(1 for v in sinais.values() for x in v if x["grau"] == "🔴"),
                         # fornecedores por sinal (o mecanismo "contrato venceu → TAC" tem KPI próprio no painel)
                         "por_sinal": {k: sum(1 for v in sinais.values() if any(x["sinal"] == k for x in v))
                                       for k in sorted({x["sinal"] for v in sinais.values() for x in v})}})


@router.get("/api/imprensa/orgaos")
def api_imprensa_orgaos(dias: int = 30, so_adversas: int = 1, limite: int = 120):
    """Imprensa sobre os ÓRGÃOS do Estado/Prefeitura (Google News RSS, sem chave; tools/noticias_orgaos, diário).
    Adversa = título com termo de risco (fraude, operação, TCE, MP…). Indício a confirmar na fonte — nunca prova."""
    import datetime as _dt
    con = _ro()
    try:
        try:
            desde = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=max(1, min(int(dias or 30), 365)))).isoformat(timespec="seconds")
            cond = " AND adversa=1" if so_adversas else ""
            itens = [dict(zip(("orgao", "titulo", "url", "fonte", "data", "adversa", "termos"), r)) for r in con.execute(
                f"SELECT orgao, titulo, url, fonte, data, adversa, termos FROM noticias_orgaos WHERE data >= ?{cond} ORDER BY data DESC LIMIT ?",
                (desde, max(1, min(int(limite or 120), 500))))]
            por_orgao = [dict(zip(("orgao", "n", "adversas"), r)) for r in con.execute(
                "SELECT orgao, count(*), sum(adversa) FROM noticias_orgaos WHERE data >= ? GROUP BY 1 ORDER BY 3 DESC, 2 DESC", (desde,))]
            tot = con.execute("SELECT count(*), sum(adversa), max(visto_em) FROM noticias_orgaos").fetchone()
        except sqlite3.OperationalError:
            return JSONResponse({"ok": True, "aviso": "noticias_orgaos ainda não coletada", "itens": [], "por_orgao": []})
    finally:
        con.close()
    return JSONResponse({"ok": True, "dias": dias, "itens": itens, "por_orgao": por_orgao, "total": tot[0], "adversas_total": tot[1] or 0,
                         "coletado_em": tot[2]})


@router.get("/api/intel/sancionadas_municipio")
def api_intel_sancionadas_municipio(limite: int = 60):
    """Empresas com sanção IMPEDITIVA contratadas pela PREFEITURA DO RIO (pcrj_contratos fonte='pncp'),
    com o teste "à época" (contrato ASSINADO dentro da vigência da sanção). Análogo municipal do
    /api/intel/sancionadas (competência TCM-RJ). Descarta órgão federal/estadual (contabiliza)."""
    try:
        from compliance_agent.cruzamentos_intel import sancionadas_municipio
        ck = "intel:sanc_mun"
        d = _cache_calc(ck, 3600, lambda: sancionadas_municipio())
        d = dict(d)
        d["empresas"] = d.get("empresas", [])[:max(1, min(int(limite or 60), 300))]
        d["explicacao"] = ("Contratação municipal do Rio de empresa sob sanção impeditiva vigente à "
                           "época da assinatura (vedação: Lei 14.133 art. 156 §1º). Competência de "
                           "controle externo: TCM-RJ. `descartados_outra_esfera` = órgãos federais "
                           "(ex.: Fiocruz) e estaduais excluídos por não serem do Município.")
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/concentracao_municipio")
def api_intel_concentracao_municipio(limite: int = 60):
    """Concentração de fornecedor por RAMO de objeto no município do Rio (HHI + top-share sobre
    pcrj_contratos, fonte='pncp'). Análogo municipal do cartel do Estado (que lê OB SIAFE).
    Base = valor CONTRATADO, não pago (ressalva no payload). Competência TCM-RJ."""
    try:
        from compliance_agent.cruzamentos_intel import concentracao_municipio
        ck = "intel:conc_mun"
        d = _cache_calc(ck, 3600, lambda: concentracao_municipio(limite=max(1, min(int(limite or 60), 200))))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001 — idioma-padrão das rotas (catch-and-return)
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/perdedoras")
def api_intel_perdedoras():
    """Perdedoras contumazes ("nunca ganharam"): participam de ≥K certames nas atas e nunca vencem —
    perfil de proposta de cobertura (OCDE). Sai do cache (varrer 8k atas não roda no request)."""
    try:
        from compliance_agent.cruzamentos_intel import ler_cache_intel
        d = ler_cache_intel("perdedoras_contumazes")
        if not d:
            return JSONResponse({"ok": False, "erro": "cache ainda não gerado — "
                                 "rodar: python -m compliance_agent.cruzamentos_intel cache"})
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/conluio_qsa")
def api_intel_conluio_qsa():
    """CONLUIO DIRETO: vencedor × perdedora do MESMO certame com sócio em comum (QSA Receita)
    ou matriz×filial concorrendo entre si. Cache do intel (com atas); fallback = só PNCP."""
    try:
        from compliance_agent.cruzamentos_intel import conluio_qsa, ler_cache_intel
        d = ler_cache_intel("conluio_qsa")
        if not d:
            d = _cache_calc("intel:conluio", 3600, lambda: conluio_qsa(incluir_atas=False))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/comunidades")
def api_intel_comunidades():
    """Comunidades (Louvain) do grafo família-empresa-órgão, ranqueadas por risco 0-100.
    Sai do cache (construir o grafo completo não roda no request)."""
    try:
        from compliance_agent.cruzamentos_intel import ler_cache_intel
        from compliance_agent.proveniencia_manchetes import anexar
        d = ler_cache_intel("comunidades")
        if not d:
            return JSONResponse({"ok": False, "erro": "cache ainda não gerado — "
                                 "rodar: python -m compliance_agent.cruzamentos_intel cache"})
        return JSONResponse(anexar("/api/intel/comunidades", d))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/radar")
def api_intel_radar(limite: int = 100):
    """RADAR composto: score 0-100 por fornecedor somando os sinais de todos os detectores —
    a fila de apuração priorizada. Cache do intel; fallback = computa na hora."""
    try:
        from compliance_agent.cruzamentos_intel import ler_cache_intel, radar_risco
        d = ler_cache_intel("radar_risco")
        if not d:
            lim = max(1, min(int(limite or 100), 300))
            d = _cache_calc(f"intel:radar:{lim}", 3600, lambda: radar_risco(limite=lim))
        from compliance_agent.proveniencia_manchetes import anexar
        return JSONResponse(anexar("/api/intel/radar", d))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/retro")
def api_intel_retro():
    """Retro-auditoria (hindsight): por detector, sanção POSTERIOR ao 1º sinal (corroboração
    independente) e R$ pagos/vitórias APÓS o alerta (custo da inação). Ledger diário no timer."""
    try:
        from compliance_agent.retro_auditoria import medir
        d = _cache_calc("intel:retro", 3600, lambda: medir())
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/buscar")
def api_comparador_buscar(termo: str = "", esfera: str = ""):
    """Grupos de item que casam o termo (ex.: 'aluguel carro', 'medicamento'), com dispersão de
    preço entre órgãos — abrir um grupo mostra quem paga mais/menos."""
    try:
        from compliance_agent.comparador_precos import buscar_grupos
        t = (termo or "").strip()[:60]
        if len(t) < 3:
            return JSONResponse({"ok": False, "erro": "termo muito curto (≥3 letras)"})
        ck = f"comp:busca:{t.lower()}:{esfera or 'todas'}"
        d = _cache_calc(ck, 600, lambda: buscar_grupos(t, esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/catalogo")
async def api_comparador_catalogo(esfera: str = ""):
    """Catálogo navegável: TODOS os grupos comparáveis por CATEGORIA (menu→submenu→item).
    Filtros/ordenação são do cliente; aqui só a estrutura, cacheada."""
    try:
        from compliance_agent.comparador_precos import catalogo
        ck = f"comp:catalogo:{esfera or 'todas'}"
        if not (d := _cache_get(ck, 1800)):
            d = _cache_put(ck, await asyncio.to_thread(catalogo, esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/item")
def api_comparador_item(grupo: str = "", unidade: str = "", esfera: str = ""):
    """Para um item (grupo normalizado), ranking de ÓRGÃOS e FORNECEDORES por preço unitário."""
    try:
        from compliance_agent.comparador_precos import comparar
        g = (grupo or "").strip()
        if not g:
            return JSONResponse({"ok": False, "erro": "grupo vazio"})
        ck = f"comp:item:{g}:{(unidade or '').lower()}:{esfera or 'todas'}"
        d = _cache_calc(ck, 600, lambda: comparar(g, unidade or None, esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/economia")
def api_comparador_economia(esfera: str = ""):
    """Economia potencial: quanto os cofres economizariam se cada compra acima da mediana tivesse
    pago a mediana de mercado do item. Total + quebra por item/órgão/fornecedor."""
    try:
        from compliance_agent.comparador_precos import economia_potencial
        ck = f"comp:economia:{esfera or 'todas'}"
        d = _cache_calc(ck, 1800, lambda: economia_potencial(esfera=esfera or None))
        from compliance_agent.proveniencia_manchetes import anexar
        return JSONResponse(anexar("/api/comparador/economia", d))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/vedada")
def api_comparador_vedada(esfera: str = ""):
    """O número mais forte: sobrepreço (acima da mediana) pago a fornecedor JURIDICAMENTE VEDADO
    de contratar com aquele ente comprador, VIGENTE à época. Inidoneidade veda todos."""
    try:
        from compliance_agent.comparador_precos import economia_vedada
        ck = f"comp:vedada:{esfera or 'todas'}"
        d = _cache_calc(ck, 1800, lambda: economia_vedada(esfera=esfera or None))
        from compliance_agent.proveniencia_manchetes import anexar
        return JSONResponse(anexar("/api/comparador/vedada", d))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/sancoes/detalhar")
def api_sancoes_detalhar(cnpj: str = "", esfera: str = "estadual", uf: str = "RJ"):
    """Detalha as sanções de um CNPJ: tipo, abrangência, órgão, vigência e se VEDA de fato o
    contrato com o ente-alvo (default Estado-RJ). Responde 'quais são e qual a abrangência'."""
    try:
        from compliance_agent.sancao_abrangencia import detalhar
        c = re.sub(r"\D", "", cnpj or "")
        if len(c) != 14:
            return JSONResponse({"ok": False, "erro": "CNPJ inválido"})
        con = _ro(linhas=True)
        try:
            return JSONResponse(detalhar(c, con, esfera, (uf or "RJ").upper()))
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/dossie")
def api_comparador_dossie(esfera: str = ""):
    """Dossiê automático: item pago muito acima da mediana por um órgão cujo FORNECEDOR já é
    sancionado/no radar/fantasma. Cruza o comparador de preços com o gabarito de risco."""
    try:
        from compliance_agent.comparador_precos import caro_e_suspeito
        ck = f"comp:dossie:{esfera or 'todas'}"
        d = _cache_calc(ck, 1800, lambda: caro_e_suspeito(esfera=esfera or None))
        from compliance_agent.proveniencia_manchetes import anexar
        return JSONResponse(anexar("/api/comparador/dossie", d))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/orgaos")
def api_comparador_orgaos(esfera: str = ""):
    """Ranking de órgãos por eficiência de gasto (razão preço/mercado ao longo de muitos itens)."""
    try:
        from compliance_agent.comparador_precos import ranking_orgaos
        ck = f"comp:orgaos:{esfera or 'todas'}"
        d = _cache_calc(ck, 1800, lambda: ranking_orgaos(esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/fornecedores")
def api_comparador_fornecedores(esfera: str = ""):
    """Ranking de fornecedores por preço relativo (mais caros / mais baratos vs mercado)."""
    try:
        from compliance_agent.comparador_precos import ranking_fornecedores
        ck = f"comp:forn:{esfera or 'todas'}"
        d = _cache_calc(ck, 1800, lambda: ranking_fornecedores(esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/lift")
def api_intel_lift():
    """Validação de cada detector contra o gabarito OBJETIVO (sanções impeditivas): LIFT = taxa de
    sancionados no que o detector marca ÷ taxa-base do universo. lift>1 = sinal; <1 = anti-sinal."""
    try:
        from compliance_agent.retro_auditoria import avaliar_lift
        d = _cache_calc("intel:lift", 3600, lambda: avaliar_lift())
        from compliance_agent.proveniencia_manchetes import anexar
        return JSONResponse(anexar("/api/intel/lift", d))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/fracionamento")
def api_intel_fracionamento(limite: int = 120):
    """Fracionamento de despesa pelo OBJETO (Lei 14.133 art. 75 §1º): unidade gestora × exercício ×
    natureza do objeto, soma das dispensas por valor contra o teto do ano, qualquer que seja o fornecedor.
    O agrupamento por CREDOR+UG+mês não é servido: mede pagamento de contrato contínuo, não fracionamento."""
    try:
        from compliance_agent.fracionamento_objeto import fracionamento_por_objeto
        lim = max(1, min(int(limite or 120), 300))
        d = fracionamento_por_objeto(limite=lim)
        # 23/11/2026: a lista "mesmo credor + UG + mês" SAIU da tela. Ela mede PAGAMENTO, não contratação:
        # enchia de serviço contínuo (luz, vigilância, publicidade, combustível — um contrato pago mês a mês)
        # e de transferência a ente público. Fracionamento é o MESMO OBJETO em contratações distintas.
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/pdf")
async def api_intel_pdf(tipo: str):
    """Gera o PDF Kroll do detector `tipo` e devolve a URL. Síncrono (detectores são rápidos/cache)."""
    try:
        from compliance_agent.intel_relatorio import gerar_pdf_intel
        d = await gerar_pdf_intel(tipo, db_path=str(RAIZ / "data" / "compliance.db"))
        return JSONResponse(d, status_code=200 if d.get("ok") else 400)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/capital_incompativel")
def api_intel_capital(limite: int = 120):
    """Capital irrisório (<R$50k) frente ao volume recebido (≥100× o capital) — subcapitalização/
    fachada (Lei 14.133 art. 5, 62-63). Fonte do capital: dump da Receita (empresas_cadastro)."""
    try:
        from compliance_agent.cruzamentos_intel import capital_incompativel
        lim = max(1, min(int(limite or 120), 300))
        d = _cache_calc(f"intel:capinc:{lim}", 600, lambda: capital_incompativel(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/prioridade_valor")
def api_intel_prioridade_valor(limite: int = 60, min_score: int = 10):
    """Fila priorizada por VALOR EM RISCO: interseção do RADAR (fornecedor arriscado) com a ECONOMIA
    POTENCIAL (R$ recuperável se tivesse pago a mediana). Cruza 'quem paga mais' com o radar."""
    try:
        from compliance_agent.cruzamentos_intel import prioridade_valor
        lim = max(1, min(int(limite or 60), 200))
        ms = max(0, min(int(min_score or 10), 100))
        d = _cache_calc(f"intel:prival:{lim}:{ms}", 900, lambda: prioridade_valor(min_score=ms, limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/fornecedor_dependente")
def api_intel_fornecedor_dependente(limite: int = 120):
    """Fornecedor comercial com ≥90% da receita do Estado numa única unidade gestora ('empresa do órgão')."""
    try:
        from compliance_agent.cruzamentos_intel import fornecedor_dependente
        lim = max(1, min(int(limite or 120), 300))
        d = _cache_calc(f"intel:dep:{lim}", 3600, lambda: fornecedor_dependente(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/corrida_dezembro")
def api_intel_corrida_dezembro(limite: int = 120):
    """Fornecedor comercial com ≥75% do valor do ano concentrado em dezembro (corrida do empenho)."""
    try:
        from compliance_agent.cruzamentos_intel import corrida_dezembro
        lim = max(1, min(int(limite or 120), 300))
        d = _cache_calc(f"intel:dez:{lim}", 600, lambda: corrida_dezembro(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/grafo_familias")
def api_intel_grafo_familias():
    """Grafo D3 (nodes/links) das famílias que ocupam cargo de confiança E fornecem ao Estado —
    consumido pelo graph.html em /graph?fonte=familias."""
    try:
        from compliance_agent.cruzamentos_intel import grafo_familias
        d = _cache_calc("intel:grafofam", 600, lambda: grafo_familias(db_path=str(RAIZ / "data" / "compliance.db")))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"nodes": [], "links": [], "erro": str(exc)}, status_code=500)


@router.get("/api/intel/comunidades_grafo")
def api_intel_comunidades_grafo():
    """Grafo D3 (nodes/links) das comunidades Louvain — consumido pelo graph.html em
    /graph?fonte=comunidades. Sai do cache do intel (construir o grafo não roda no request)."""
    try:
        from compliance_agent.cruzamentos_intel import ler_cache_intel
        d = ler_cache_intel("comunidades") or {}
        return JSONResponse(d.get("d3") or {"nodes": [], "links": []})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"nodes": [], "links": [], "erro": str(exc)}, status_code=500)


@router.get("/api/intel/fenix")
def api_intel_fenix(limite: int = 120):
    """Empresa fênix: BAIXADA/INAPTA que recebeu, ou aberta ≤12m antes do 1º pagamento."""
    try:
        from compliance_agent.cruzamentos_intel import empresa_fenix
        lim = max(1, min(int(limite or 120), 300))
        d = _cache_calc(f"intel:fenix:{lim}", 3600, lambda: empresa_fenix(limite=lim))
        from compliance_agent.proveniencia_manchetes import anexar
        return JSONResponse(anexar("/api/intel/fenix", d))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/socio_sancionada")
def api_intel_socio_sancionada():
    """Contratada cujo sócio é sócio de empresa sancionada (vedação que alcança o RJ), com OB SIAFE paga na
    janela em que as duas sociedades e a sanção coexistem. Força = critérios do TCU (Ac. 1831/2014-P)."""
    try:
        from compliance_agent.socio_de_sancionada import socio_de_sancionada
        return JSONResponse(_cache_calc("intel:socio_sancionada", 3600, socio_de_sancionada))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/competencia_futura")
def api_intel_competencia_futura():
    """OB SIAFE paga antes da competência que quita: antecipação (L.14.133 art. 145) ou ano registrado errado.
    Sem `except` genérico de propósito (catraca): erro aqui é 500 honesto, não `ok:false` mudo."""
    from compliance_agent.pagamento_competencia_futura import pagamento_competencia_futura
    return JSONResponse(_cache_calc("intel:competencia_futura", 3600, pagamento_competencia_futura))


@router.get("/api/intel/dea_recorrente")
def api_intel_dea_recorrente():
    """DEA (elemento 92) repetida ao mesmo fornecedor em processos distintos — serviço sem empenho prévio
    (L.4320 arts. 37 e 60). Só UGs com Nota de Empenho coletada. Sem `except` genérico (catraca)."""
    from compliance_agent.dea_recorrente import dea_recorrente
    return JSONResponse(_cache_calc("intel:dea_recorrente", 3600, dea_recorrente))


@router.get("/api/intel/ordem_cronologica")
def api_intel_ordem_cronologica():
    """Quebra da ordem cronológica medida no SIAFE (Dec. RJ 49.134/2024 art. 9º: data da NL por fonte).
    Só UGs com NE e NL coletadas. Sem `except` genérico (catraca)."""
    from compliance_agent.ordem_cronologica_siafe import ordem_cronologica
    return JSONResponse(_cache_calc("intel:ordem_cronologica", 3600, ordem_cronologica))


@router.get("/api/intel/porta_giratoria")
def api_intel_porta_giratoria(limite: int = 120):
    """Porta giratória: ex-servidor (inativo/exonerado) que virou sócio de fornecedor do Estado."""
    try:
        from compliance_agent.cruzamentos_intel import porta_giratoria
        lim = max(1, min(int(limite or 120), 300))
        d = _cache_calc(f"intel:porta:{lim}", 3600, lambda: porta_giratoria(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/nepotismo_cruzado")
def api_intel_nepotismo_cruzado(limite: int = 60):
    """Nepotismo cruzado: colocação recíproca de parentes entre dois órgãos (dribla a SV13)."""
    try:
        from compliance_agent.cruzamentos_intel import nepotismo_cruzado
        lim = max(1, min(int(limite or 60), 200))
        d = _cache_calc(f"intel:nepcruz:{lim}", 3600, lambda: nepotismo_cruzado(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/nepotismo")
def api_intel_nepotismo(limite: int = 120):
    """Nepotismo (SV13 STF): ≥2 pessoas de nomes distintos, mesmo sobrenome de família raro, ambas
    em cargo de confiança no mesmo órgão. Fragmento de CPF corrobora pessoas distintas."""
    try:
        from compliance_agent.cruzamentos_intel import nepotismo
        lim = max(1, min(int(limite or 120), 300))
        d = _cache_calc(f"intel:nep:{lim}", 3600, lambda: nepotismo(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/socio_oculto")
def api_intel_socio_oculto(limite: int = 120):
    """Pessoa/holding sócia de ≥3 empresas fornecedoras do Estado (empresário oculto / grupo familiar)."""
    try:
        from compliance_agent.cruzamentos_intel import socio_oculto
        lim = max(1, min(int(limite or 120), 300))
        d = _cache_calc(f"intel:ocult:{lim}", 600, lambda: socio_oculto(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/aditivos")
def api_intel_aditivos(limite: int = 120, esfera: str = ""):
    """Aditivos que estouram o limite legal de acréscimo (25%/50%, Lei 14.133 art. 125) e change
    orders em série (≥3 aditivos). Fonte: pcrj_contratos + contrato_aditivo."""
    try:
        from compliance_agent.cruzamentos_intel import aditivos_estouro
        lim = max(1, min(int(limite or 120), 300))
        ck = f"intel:adit:{lim}:{esfera or 'todas'}"
        d = _cache_calc(ck, 600, lambda: aditivos_estouro(limite=lim, esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/socio_servidor")
def api_intel_socio_servidor(limite: int = 1000):
    """Sócio na folha: servidor público que é sócio-dono de fornecedor pago pelo Estado — uma linha por
    PESSOA, identidade desambiguada em camadas (`identidade_pessoa`: CPF na janela de cada folha,
    prevalência do nome, faixa etária). Lista principal = VERIFICADO + PROVÁVEL; indeterminados e
    homônimos vêm à parte. Chave `socserv2`: o formato mudou em 19/11/2026 (cache antigo não serve)."""
    try:
        from compliance_agent.cruzamentos_intel import socio_servidor
        lim = max(1, min(int(limite or 1000), 2000))
        d = _cache_calc(f"intel:socserv2:{lim}", 6 * 3600, lambda: socio_servidor(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/escalada")
def api_intel_escalada(limite: int = 120, esfera: str = ""):
    """Escalada de preço unitário: MESMO fornecedor vende o MESMO item por preços cada vez maiores
    ao longo do tempo (≥3 compras, ≥45 dias, alta ≥3×). Preço dirigido/captura. Fonte: PNCP."""
    try:
        from compliance_agent.cruzamentos_intel import escalada_preco
        lim = max(1, min(int(limite or 120), 300))
        ck = f"intel:escal:{lim}:{esfera or 'todas'}"
        d = _cache_calc(ck, 3600, lambda: escalada_preco(limite=lim, esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/sobrepreco")
def api_intel_sobrepreco(limite: int = 120, esfera: str = ""):
    """Sobrepreço por mediana de item: mesmo produto (descrição normalizada) comprado por vários
    órgãos; sinaliza preço unitário ≥2× a mediana (e fora de mediana+3·MAD). Fonte: PNCP."""
    try:
        from compliance_agent.cruzamentos_intel import sobrepreco
        lim = max(1, min(int(limite or 120), 300))
        ck = f"intel:sobre:{lim}:{esfera or 'todas'}"
        d = _cache_calc(ck, 3600, lambda: sobrepreco(limite=lim, esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/fantasmas")
def api_intel_fantasmas(limite: int = 50):
    """Ranking de risco de empresa-fantasma (8 sinais determinísticos do /fantasma) no conjunto-alvo
    (capturas, rodízios, perdedoras contumazes, sancionadas, top favorecidos)."""
    try:
        from compliance_agent.cruzamentos_intel import ranking_fantasmas
        lim = max(1, min(int(limite or 50), 200))
        d = _cache_calc(f"intel:fant:{lim}", 3600, lambda: ranking_fantasmas(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/ninho_sala")
def api_intel_ninho_sala(limite: int = 120):
    """Ninho pela SALA (endereço + complemento) e por CONJUNTO de fatores.

    Dividir o PRÉDIO não diz nada — 'Rua da Assembleia 10' tem 318 CNPJs e é edifício
    comercial. Dividir a SALA, com dois ou mais recebendo dinheiro público, é a assinatura
    de interposição. O grau vem do acúmulo de fatores, nunca de um sinal só.
    """
    try:
        # cache primeiro (o cálculo a frio leva ~16 s e o painel corta em 30 s); sem cache,
        # calcula ao vivo e diz que veio ao vivo — nunca fica mudo.
        from compliance_agent.cruzamentos_intel import ler_cache_intel
        from compliance_agent.proveniencia_manchetes import anexar
        c = ler_cache_intel("ninho_sala")
        if c and c.get("ok"):
            c["do_cache"] = True
            c["grupos"] = (c.get("grupos") or [])[:limite]
            return JSONResponse(anexar("/api/intel/ninho_sala", c))
        from compliance_agent.ninho_sala import ninhos_por_sala
        d = ninhos_por_sala(limite=limite)
        d["do_cache"] = False
        return JSONResponse(anexar("/api/intel/ninho_sala", d))
    except Exception as exc:  # noqa: BLE001 — degrada honesto, nunca lista vazia
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/hub_compartilhado")
def api_intel_hub_compartilhado(chave: str = "endereco", min: int = 5):
    """Hub compartilhado: 1 âncora física (endereço/telefone/e-mail) usada por N CNPJs — assinatura
    de 'ninho de fantasmas'. Guarda anti-FP rebaixa massa legítima (contador, galeria, coworking)."""
    from datetime import datetime as _dt
    try:
        from compliance_agent.cruzamentos_intel import hub_compartilhado, ler_cache_intel
        ch = chave if chave in ("endereco", "telefone", "email") else "endereco"
        mn = int(min or 5)
        mn = 2 if mn < 2 else (100 if mn > 100 else mn)
        d = _cache_get(f"intel:hub:{ch}:{mn}", 600)
        # O cálculo ao vivo cruza o dump da Receita (6,1 mi de estabelecimentos) com as OB:
        # medido, NÃO responde em 90 s enquanto o sweep escreve no compliance.db — e era por
        # isso que o card "ninhos de fachada" ficava eternamente em "—". O cache em disco
        # gerado por `gerar_cache_intel` já existe e usa EXATAMENTE estes parâmetros
        # (endereco/5); a rota só não o lia. Fora desses parâmetros não há cache: aí sim
        # calcula ao vivo, mas isso é caminho de exceção, não o do painel.
        if d is None and ch == "endereco" and mn == 5:
            if (c := ler_cache_intel("hub_compartilhado")) and c.get("grupos"):
                c["do_cache"] = True
                d = _cache_put(f"intel:hub:{ch}:{mn}", c)
        if d is None:
            d = _cache_put(f"intel:hub:{ch}:{mn}", hub_compartilhado(chave=ch, min_cnpjs=mn))
        return JSONResponse({"ok": d.get("ok", True), "grupos": d.get("grupos", []),
                             "erro": d.get("erro"), "explicacao": d.get("explicacao"),
                             "ressalva": d.get("ressalva"),
                             # honestidade de frescor: dado de cache não se apresenta como de agora
                             "do_cache": bool(d.get("do_cache")),
                             "gerado_em": d.get("gerado_em") or _dt.now().strftime("%Y-%m-%d %H:%M")})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pcrj/comissionados_candidatos")
def api_pcrj_comissionados_candidatos(limite: int = 300):
    """Comissionados da PREFEITURA do Rio que foram CANDIDATOS (TSE) — tabela
    pcrj_comissionado_candidato (data/pcrj.db, coletor pcrj/comissionados_candidatos).
    Agregado por PESSOA (nome_norm): 1 entrada por pessoa com a lista de postos
    (nomeações) e candidaturas no histórico — a tabela tem 1 linha por (pessoa, órgão,
    cargo, admissão), e a variação textual de orgao_pcrj entre coletas mensais duplicava
    o mesmo vínculo em várias linhas (achado 2026-07-21); `limite` agora é por PESSOA,
    não por linha bruta. Padrão de agrupamento espelha pericia.py::_tabela_comissionados_cand."""
    try:
        lim = max(1, min(int(limite or 300), 1000))
        ck = f"pcrj:comis_cand:v3:{lim}"  # v3: identidade (homônimo visível no TSE/folha)
        if d := _cache_get(ck, 600):
            return JSONResponse(d)
        con = _ro("pcrj.db", linhas=True)
        try:
            rows = [dict(r) for r in con.execute(
                "SELECT nome_norm, nome_pcrj, cargo_pcrj, orgao_pcrj, admissao, exoneracao, "
                "matricula, cand_ano, cand_cargo, cand_cidade FROM pcrj_comissionado_candidato")]
            n_linhas = len(rows)
        finally:
            con.close()

        from compliance_agent.pcrj.comissionados_candidatos import agrupar_por_pessoa, pessoas_tse_por_nome
        out_pessoas = agrupar_por_pessoa(rows, pessoas_tse_por_nome())
        n_pessoas = len(out_pessoas)
        truncado = len(out_pessoas) > lim
        out_pessoas = out_pessoas[:lim]

        out = {"ok": True, "n": n_linhas, "n_pessoas": n_pessoas, "truncado": truncado,
               "comissionados": out_pessoas,
               "explicacao": ("Cruzamento por nome entre a folha de comissionados da Prefeitura do "
                              "Rio e as candidaturas do TSE. Comissionado que concorreu (ou concorre) "
                              "a cargo eletivo é sinal de aparelhamento político do cargo de confiança. "
                              "Cada pessoa aparece uma vez, com o histórico de nomeações abaixo."),
               "identidade": ("INDETERMINADO — a folha da Prefeitura não publica CPF; só o nome liga as bases. "
                              "Quando o TSE mostra candidatos DIFERENTES (CPF/título) com o mesmo nome, o item "
                              "sai marcado como homônimo."),
               "n_homonimo_visivel": sum(1 for p in out_pessoas if p.get("homonimo_provavel")),
               "ressalva": "Match por NOME (homônimo possível) — confirmar por CPF antes de citar. Não é achado."}
        return JSONResponse(_cache_put(ck, out))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pcrj/fantasmas")
def api_pcrj_fantasmas(faixa: str = "", limite: int = 200):
    """Servidor-fantasma na folha da Câmara/PCRJ — 8 sinais determinísticos (pcrj/fantasma_servidor),
    cache materializado em pcrj_fantasma_servidor. ?faixa=forte|verificar|fraco filtra."""
    try:
        lim = max(1, min(int(limite or 200), 800))
        fx = faixa if faixa in ("forte", "verificar", "fraco") else ""
        ck = f"pcrj:fantasma:{fx}:{lim}"
        if d := _cache_get(ck, 600):
            return JSONResponse(d)
        con = _ro("pcrj.db", linhas=True)
        try:
            cond = "WHERE faixa=?" if fx else ""
            args = ([fx] if fx else []) + [lim]
            rows = [dict(r) for r in con.execute(
                f"""SELECT nome, gabinetes, cargos_camara, sinais, score, faixa, homonimo, gerado_em
                    FROM pcrj_fantasma_servidor {cond}
                    ORDER BY CASE faixa WHEN 'forte' THEN 0 WHEN 'verificar' THEN 1 ELSE 2 END,
                             score DESC LIMIT ?""", args)]
            faixas = dict(con.execute(
                "SELECT faixa, COUNT(*) FROM pcrj_fantasma_servidor GROUP BY faixa").fetchall())
            gerado = con.execute("SELECT MAX(gerado_em) FROM pcrj_fantasma_servidor").fetchone()[0]
        finally:
            con.close()
        if not rows and not faixas:
            return JSONResponse({"ok": False, "erro": "detector ainda não rodou — "
                                 "rodar: python -m compliance_agent.pcrj.fantasma_servidor"})
        out = {"ok": True, "n": sum(faixas.values()), "faixas": faixas, "itens": rows,
               "gerado_em": gerado,
               "explicacao": ("Sinais objetivos de servidor-fantasma (múltiplos gabinetes, cargo "
                              "incompatível, vínculo concomitante, geografia impossível…) somados em "
                              "escore. Faixa FORTE exige identidade conferida por documento; as folhas "
                              "da Prefeitura e da Câmara não publicam CPF e os sinais ligam as bases só "
                              "pelo NOME, então o teto é VERIFICAR (fila de diligência, não achado)."),
               "identidade": "INDETERMINADO — só o nome liga as bases (sem CPF na folha municipal)",
               "ressalva": ("Indício ≠ acusação. `homonimo`=1 marca nome presente em ≥3 municípios "
                            "(ambiguidade — confirmar por CPF/matrícula antes de qualquer citação).")}
        return JSONResponse(_cache_put(ck, out))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pcrj/gastos_achados")
def api_pcrj_gastos_achados(limite_por_detector: int = 40):
    """Achados da perícia de gastos da PREFEITURA (D7 fracionamento · D8 recém-aberta · D9 sócio na
    folha · D10 rede de sócios entre concorrentes · aditivo estourado) — lê os alertas gravados pela
    última corrida de tools/pcrj_pericia_gastos.py (dedup por título, mais recente vence)."""
    try:
        lim = max(5, min(int(limite_por_detector or 40), 200))
        ck = f"pcrj:gastos:{lim}"
        if d := _cache_get(ck, 600):
            return JSONResponse(d)
        con = _ro(linhas=True)
        try:
            rows = con.execute(
                """SELECT tipo, severidade, titulo, descricao, evidencias, MAX(id) id
                   FROM alertas WHERE tipo LIKE 'pcrj_d%' GROUP BY titulo
                   ORDER BY CASE severidade WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END, id DESC
                """).fetchall()
        finally:
            con.close()
        # Agrupamento, filtro de esfera e contagem moram em `pericia_gastos.agrupar_alertas` (testável):
        # só alerta de órgão PROVADO municipal do Rio; `detectores` é o total real, não o tamanho da lista cortada.
        from compliance_agent.pcrj.pericia_gastos import agrupar_alertas
        g = agrupar_alertas([dict(r) for r in rows], lim)
        por_det = g["achados"]
        out = {"ok": True, "detectores": g["detectores"], "exibidos": g["exibidos"], "achados": por_det,
               "esfera": "municipal-rio", "fora_da_esfera": g["fora_da_esfera"],
               "nota_esfera": g["nota_esfera"],
               "explicacao": ("Perícia determinística sobre despesa por credor (CGM 2019-2023) + "
                              "contratos/licitações municipais (PNCP 2024+): fracionamento colado no "
                              "teto de dispensa, credor recém-aberto, sócio de credor na folha, rede "
                              "societária entre concorrentes e aditivo acima do art. 125."),
               "ressalva": "Indício ≠ acusação; match por NOME vem sinalizado; só a apuração fecha."}
        return JSONResponse(_cache_put(ck, out))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pcrj/aditivos")
def api_pcrj_aditivos():
    """D11 da Prefeitura contrato a contrato — acréscimos computáveis por termo × teto do art. 125,
    estado (VERIFICADO = provado no termo; PENDENTE = sinal sem prova, com o motivo) e a COBERTURA
    de termos coletados, que é o "de quantos?" do zero. Mesma régua do alerta (só leitura)."""
    try:
        ck = "pcrj:aditivos"
        if d := _cache_get(ck, 600):
            return JSONResponse(d)
        from compliance_agent.pcrj.pericia_gastos import d11_avaliacao
        con = _ro(linhas=True, timeout=30)
        try:
            av = d11_avaliacao(con)
        finally:
            con.close()
        cob = av["cobertura"]
        out = {"ok": True, **av,
               "estado_cobertura": ("VERIFICADO" if cob["com_aditivo_declarado"] and
                                    cob["termos_consultados"] >= cob["com_aditivo_declarado"]
                                    else "PENDENTE"),
               "explicacao": ("Soma dos acréscimos quantitativos NOS TERMOS ADITIVOS publicados no "
                              "PNCP sobre o valor inicial, contra o teto do art. 125 da Lei "
                              "14.133/2021 (25%; 50% só para reforma de edifício ou equipamento; "
                              "até o teto é lícito). Reajuste, repactuação, reequilíbrio (arts. 124 "
                              "II-d, 134 e 135), prorrogação e supressão ficam fora. Só VERIFICADO "
                              "vira alerta."),
               "ressalva": ("Base = valor inicial publicado, não o atualizado que a lei manda usar. "
                            "Valor global maior que o inicial NÃO é acréscimo (o global do PNCP "
                            "cobre o período). Pagamento por contrato: INDISPONÍVEL — a despesa "
                            "CGM é por credor e cobre 2019–2023. Indício ≠ acusação.")}
        return JSONResponse(_cache_put(ck, out))
    except (sqlite3.Error, OSError, KeyError, ValueError) as exc:  # base travada/ausente ou dado torto
        logger.warning("api_pcrj_aditivos: %s", exc)
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pcrj/beneficios_vinculo")
def api_pcrj_beneficios_vinculo():
    """Comissionados/servidores municipais × benefício social (Bolsa Família etc.) DURANTE o vínculo
    (fairness: só o mês dentro da janela de vínculo conta). Lê o cache materializado — a perícia
    cruza 7,3 mi de registros e NUNCA roda no request."""
    try:
        from compliance_agent.cruzamentos_intel import ler_cache_intel
        d = ler_cache_intel("beneficios_vinculo")
        if not d:
            return JSONResponse({"ok": False, "erro": "cache ainda não gerado — "
                                 "rodar: python -m compliance_agent.cruzamentos_intel cache"})
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pcrj/doe_concentracao")
def api_pcrj_doe_concentracao(min_atas: int = 2, min_valor: float = 100_000.0):
    """Concentração de vencedor nas Atas de Registro de Preços mineradas do D.O. RIO
    (pcrj_doe_materia → eventos). CNPJ que vence ≥min_atas atas com valor material —
    sinal de concentração/captura na fonte municipal. Determinístico, roda em ms."""
    try:
        ck = f"pcrj:doe_conc:{int(min_atas)}:{int(min_valor)}"
        if d := _cache_get(ck, 900):
            return JSONResponse(d)
        from compliance_agent.pcrj.doe_minerador import concentracao_vencedor
        out = concentracao_vencedor(min_atas=int(min_atas), min_valor=float(min_valor))
        out["explicacao"] = ("Vencedor recorrente de atas de registro de preços no D.O. do "
                             "Município (fonte OCR). Cobertura = matérias já colhidas pelo doweb; "
                             "INDISPONÍVEL ≠ 0 — a cobertura cresce com o harvest do Diário.")
        return JSONResponse(_cache_put(ck, out))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pcrj/doe_canal_informal")
def api_pcrj_doe_canal_informal():
    """Canais @gmail.com usados como via de compra por órgão municipal (pesquisa de mercado /
    retirada de empenho por e-mail pessoal) — minerado do D.O. RIO. Baixa transparência,
    vetor de direcionamento (contorna o processo formal SIGA/SEI)."""
    try:
        ck = "pcrj:doe_gmail"
        if d := _cache_get(ck, 900):
            return JSONResponse(d)
        from compliance_agent.pcrj.doe_minerador import canal_informal
        out = canal_informal()
        out["explicacao"] = ("Compra pública conduzida por e-mail pessoal @gmail.com (gratuito, "
                             "sem rastro institucional). Indício de fragilidade de controle interno "
                             "e de canal informal fora do processo administrativo formal.")
        return JSONResponse(_cache_put(ck, out))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


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


# ── Acervo de íntegras dos contratos do Município do Rio ────────────────────────────────────
# Capturado do PNCP (o SEI público municipal indexa só cadastro de representação — medido em
# 2026-09-02, 0/9 processos de contratação com controle positivo 1/1). O texto vem do PDF
# assinado; `fonte_texto` distingue nativo de OCR, porque OCR erra e o achado precisa saber.
_CNPJ_MUNICIPIO_RIO = "42498733000148"


def _con_integras():
    """sqlite3 nativo: pcrj_contratos tem linhas de outros entes com colunas deslocadas que
    derrubam o scanner do DuckDB na LEITURA, antes de qualquer cast."""
    return _ro()


@router.get("/api/pcrj/integras")
def api_pcrj_integras(q: str = "", modalidade: str = "", fonte: str = "",
                      ordem: str = "valor", limite: int = 200):
    """Lista as íntegras capturadas. `q` casa fornecedor, objeto do contrato ou nº de processo."""
    con = _con_integras()
    try:
        con.execute("SELECT 1 FROM contrato_integra LIMIT 1")
    except sqlite3.OperationalError:
        return JSONResponse({"itens": [], "total": 0, "aviso": "acervo ainda não capturado"})
    where, args = ["1=1"], []
    if q:
        where.append("(upper(fornecedor_nome) LIKE ? OR upper(titulo) LIKE ? "
                     "OR processos_sei LIKE ? OR numero_controle_pncp LIKE ?)")
        args += [f"%{q.upper()}%", f"%{q.upper()}%", f"%{q}%", f"%{q}%"]
    if fonte in ("nativo", "ocr"):
        where.append("coalesce(fonte_texto,'nativo') = ?")
        args.append(fonte)
    ordens = {"valor": "CAST(valor_global AS REAL) DESC",
              "recente": "coletado_em DESC", "texto": "n_chars DESC"}
    sql = (f"SELECT numero_controle_pncp, fornecedor_nome, valor_global, titulo, url, n_chars, "
           f"processos_sei, estado, coalesce(fonte_texto,'nativo'), ano "
           f"FROM contrato_integra WHERE {' AND '.join(where)} "
           f"ORDER BY {ordens.get(ordem, ordens['valor'])} LIMIT ?")
    linhas = con.execute(sql, args + [max(1, min(limite, 2000))]).fetchall()
    total = con.execute("SELECT count(*) FROM contrato_integra").fetchone()[0]
    legiveis = con.execute("SELECT count(*) FROM contrato_integra WHERE estado='TEXTO_OK'").fetchone()[0]
    # ERRO_REDE é fila, NÃO é processado: contá-lo na cobertura infla o placar — foi o que
    # transformou 46,7% em "69,4%" antes. Cobertura mede o que foi de fato lido ou decidido.
    processados = con.execute(
        "SELECT count(*) FROM contrato_integra WHERE estado <> 'ERRO_REDE'").fetchone()[0]
    na_fila = con.execute(
        "SELECT count(*) FROM contrato_integra WHERE estado = 'ERRO_REDE'").fetchone()[0]
    universo = con.execute("SELECT count(*) FROM pcrj_contratos WHERE orgao_cnpj=?",
                           [_CNPJ_MUNICIPIO_RIO]).fetchone()[0]
    # SINAIS do cruzamento íntegra × D.O. (tools/pcrj_integra_x_doe, noturno no cruzador.sh). Só sinal
    # positivo; contrato sem sinal é contrato sem sinal, não contrato limpo — a cobertura do D.O. é parcial.
    sinais_por: dict[str, list] = {}
    sinais_total = 0
    try:
        for num, grau, sinal, det in con.execute(
                "SELECT numero_controle_pncp, grau, sinal, detalhe FROM contrato_doe_sinal"):
            sinais_por.setdefault(num, []).append({"grau": grau, "sinal": sinal, "detalhe": det})
            sinais_total += 1
    except sqlite3.OperationalError:       # tabela ainda não materializada: sem sinais, sem erro
        logger.debug("investigacao.py:2724: exceção ignorada (era except-pass mudo)", exc_info=True)
    con.close()
    itens = [{
        "numero": r[0], "fornecedor": r[1], "valor": float(r[2] or 0), "titulo": r[3],
        "url_pncp": r[4], "n_chars": r[5] or 0,
        "processos_sei": json.loads(r[6] or "[]"), "estado": r[7], "fonte_texto": r[8],
        "ano": r[9],
    } for r in linhas]
    for it in itens:
        it["sinais"] = sorted(sinais_por.get(it["numero"], []), key=lambda s: s["grau"] != "🔴")
    return JSONResponse({
        "itens": itens, "mostrando": len(itens), "sinais_total": sinais_total,
        # cobertura DECLARADA: o painel nunca deve sugerir que o acervo é o universo
        "acervo": total, "legiveis": legiveis, "universo_municipio": universo,
        "processados": processados, "na_fila_rede": na_fila,
        "cobertura_pct": round(100 * processados / universo, 1) if universo else None,
    })


@router.get("/api/pcrj/integra/{numero:path}")
def api_pcrj_integra(numero: str):
    """Íntegra de um contrato: texto completo, processos SEI citados e link do original."""
    con = _con_integras()
    r = con.execute(
        "SELECT numero_controle_pncp, orgao_cnpj, ano, seq, fornecedor_nome, valor_global, "
        "titulo, url, n_chars, texto, processos_sei, estado, coalesce(fonte_texto,'nativo'), "
        "coletado_em FROM contrato_integra WHERE numero_controle_pncp = ?", [numero]).fetchone()
    reg = con.execute("SELECT objeto, orgao_nome, unidade, data_assinatura, tipo, vigencia_ini, "
                      "vigencia_fim FROM pcrj_contratos WHERE numero_controle_pncp = ?",
                      [numero]).fetchone()
    con.close()
    if not r:
        return JSONResponse({"erro": "não capturado", "numero": numero}, status_code=404)
    cnpj, ano, seq = r[1], r[2], r[3]
    return JSONResponse({
        "numero": r[0], "fornecedor": r[4], "valor": float(r[5] or 0),
        "titulo": r[6], "url_pncp": r[7], "n_chars": r[8] or 0, "texto": r[9] or "",
        "processos_sei": json.loads(r[10] or "[]"), "estado": r[11], "fonte_texto": r[12],
        "coletado_em": r[13],
        # o registro do PNCP, ao lado da íntegra: objeto e vigência não estão no PDF
        "objeto": reg[0] if reg else None, "orgao": reg[1] if reg else None,
        "unidade": reg[2] if reg else None, "assinatura": reg[3] if reg else None,
        "tipo": reg[4] if reg else None,
        "vigencia": [reg[5], reg[6]] if reg else None,
        # links para a FONTE original — o painel tem de levar ao documento, não só ao resumo
        "url_pncp_contrato": f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/contratos/{ano}/{seq}/arquivos",
        "url_pncp_web": f"https://pncp.gov.br/app/contratos/{cnpj}/{ano}/{seq}",
    })


# numero em QUERY, não em path: o número de controle do PNCP contém barra
# ("…-2-000708/2026") e um {numero:path} é guloso — engolia o "/download" do fim e a rota
# devolvia 404. Medido no painel, não presumido.
@router.get("/api/pcrj/download")
def api_pcrj_integra_download(numero: str, formato: str = "txt"):
    """Baixa a íntegra. `txt` = texto extraído; `md` = texto com cabeçalho de procedência.

    A procedência vai NO ARQUIVO, não só na tela: quem abrir o .md depois precisa saber se o
    texto veio nativo do PDF ou de OCR (que erra), e de qual URL do PNCP.
    """
    from fastapi.responses import PlainTextResponse
    con = _con_integras()
    r = con.execute("SELECT fornecedor_nome, valor_global, titulo, url, texto, processos_sei, "
                    "coalesce(fonte_texto,'nativo'), coletado_em, n_chars "
                    "FROM contrato_integra WHERE numero_controle_pncp = ?", [numero]).fetchone()
    con.close()
    if not r:
        return JSONResponse({"erro": "não capturado", "numero": numero}, status_code=404)
    nome = re.sub(r"[^A-Za-z0-9._-]", "_", numero)
    if formato != "md":
        return PlainTextResponse(r[4] or "", headers={
            "Content-Disposition": f'attachment; filename="{nome}.txt"'})
    seis = json.loads(r[5] or "[]")
    val = f"R$ {float(r[1] or 0):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    corpo = (
        f"# Contrato {numero}\n\n"
        f"| campo | valor |\n|---|---|\n"
        f"| Fornecedor | {r[0] or '—'} |\n| Valor global | {val} |\n"
        f"| Arquivo | {r[2] or '—'} |\n| Caracteres | {r[8] or 0} |\n"
        f"| Processos SEI citados | {', '.join(seis) if seis else '—'} |\n"
        f"| Origem do texto | {'OCR (pode conter erro de leitura)' if r[6] == 'ocr' else 'nativo do PDF'} |\n"
        f"| Capturado em | {r[7] or '—'} |\n| Fonte | {r[3] or '—'} |\n\n"
        f"---\n\n{r[4] or ''}\n")
    return PlainTextResponse(corpo, headers={
        "Content-Disposition": f'attachment; filename="{nome}.md"'})
