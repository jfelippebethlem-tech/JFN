# -*- coding: utf-8 -*-
"""Rotas investigacao do JFN — extraído de server.py (split 2026-07-06; rede: tests/test_server_snapshot.py).
Handlers idênticos aos originais; só o decorador mudou de @app p/ @router."""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


router = APIRouter()

# Raiz do repo (~/JFN) — após o split de server.py p/ rotas/ (2026-07-06), os caminhos por
# __file__ apontavam p/ rotas/data (inexistente) e grafo/fachada-revisar/fachada-veredito
# quebraram em silêncio. Fix 2026-07-10 (mesmo fix do rotas/sistema.py).
RAIZ = Path(__file__).resolve().parent.parent

async def _grafo_rede_completa(limite: int = 120):
    """Rede de relacionamento COMPLETA (não só MGS): top-N fornecedores por valor pago ↔ órgãos (UGs),
    a partir de ordens_bancarias. Fornecedor vira severidade='alta' se for INDICIO em verificacao_sede.
    Formato D3 que o graph.html consome: {nodes:[{id,label,tipo,...}], links:[{source,target,...}]}."""
    import sqlite3 as _sq
    import re as _re
    DB = str(RAIZ / "data" / "compliance.db")
    try:
        con = _sq.connect(f"file:{DB}?mode=ro", uri=True)
        con.row_factory = _sq.Row
        n_forn = max(10, min(int(limite), 400))
        # 1 scan: top fornecedores por valor
        forn = con.execute(
            "SELECT favorecido_nome nome, MAX(favorecido_cpf) doc, SUM(valor) v, COUNT(*) n "
            "FROM ordens_bancarias WHERE favorecido_nome IS NOT NULL AND favorecido_nome!='' "
            "GROUP BY favorecido_nome ORDER BY v DESC LIMIT ?", (n_forn,)).fetchall()
        top_nomes = [f["nome"] for f in forn]
        susp = {r[0] for r in con.execute("SELECT cnpj FROM verificacao_sede WHERE status='INDICIO'")}
        nodes, links, orgaos, fid_de = [], [], {}, {}
        for f in forn:
            fid = "empresa:" + ((f["doc"] or f["nome"]) or "?")[:24]
            fid_de[f["nome"]] = fid
            cnpj = _re.sub(r"\D", "", f["doc"] or "")
            nodes.append({"id": fid, "label": (f["nome"] or "")[:40], "tipo": "empresa",
                          "valor": float(f["v"] or 0), "n_obs": f["n"],
                          "severidade": "alta" if cnpj in susp else ""})
        # 1 scan filtrado: arestas fornecedor→órgão (só dos top), agregadas
        ph = ",".join("?" * len(top_nomes))
        if top_nomes:
            for u in con.execute(
                f"SELECT favorecido_nome nome, ug_nome org, SUM(valor) v FROM ordens_bancarias "
                f"WHERE favorecido_nome IN ({ph}) AND ug_nome IS NOT NULL AND ug_nome!='' "
                f"GROUP BY favorecido_nome, ug_nome", top_nomes).fetchall():
                oid = "orgao:" + (u["org"] or "?")[:34]
                if oid not in orgaos:
                    orgaos[oid] = {"id": oid, "label": (u["org"] or "?")[:36], "tipo": "orgao"}
                links.append({"source": fid_de.get(u["nome"]), "target": oid, "tipo": "pagamento", "valor": float(u["v"] or 0)})
        con.close()
        nodes.extend(orgaos.values())
        return JSONResponse(content={"nodes": nodes, "links": links})
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
        return JSONResponse({"ok": True, "n": len(itens), "itens": itens, "benford": benford,
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
        # captura/dependencia varrem a base inteira (~3s) e não dependem de cnpj → cache curto
        ck = f"cartel:{modo}:{top}" if modo in ("captura", "dependencia") else None
        if ck and (cache := _cache_get(ck, 300)):
            return JSONResponse(cache)
        if modo == "vizinhanca":
            if not cnpj:
                return JSONResponse({"ok": False, "erro": "informe ?cnpj="}, status_code=400)
            dados = G.vizinhanca_cartel(cnpj, limite=top)
        elif modo == "dependencia":
            dados = G.dependencia_fornecedores(limite=top)
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
        if ck:
            _cache_put(ck, out)
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
    Cacheado 120s — as agregações varrem ~1,1M de OBs (~3s) e o panorama abre em toda visita."""
    if cache := _cache_get("painel:snapshot", 120):
        return JSONResponse(content=cache)
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
            total_obs = s.query(sa.func.count(OrdemBancaria.id)).scalar() or 0
            obs_hoje = s.query(sa.func.count(OrdemBancaria.id)).filter(
                OrdemBancaria.data_emissao == hoje).scalar() or 0
            valor_hoje = s.query(sa.func.sum(OrdemBancaria.valor)).filter(
                OrdemBancaria.data_emissao == hoje).scalar() or 0
            valor_total = s.query(sa.func.sum(OrdemBancaria.valor)).scalar() or 0

            sev = {}
            for r in s.query(Alerta.severidade, sa.func.count(Alerta.id)).group_by(Alerta.severidade).all():
                sev[r[0] or "baixa"] = r[1]
            alta = sev.get("alta", 0)
            media = sev.get("média", 0) + sev.get("media", 0)

            alertas = [
                {"tipo": a.tipo, "severidade": a.severidade, "titulo": a.titulo,
                 "descricao": (a.descricao or "")[:300], "data": str(a.data_referencia or ""),
                 "criado": str(a.created_at)[:16]}
                for a in s.query(Alerta).order_by(desc(Alerta.created_at)).limit(40).all()
            ]
            top = [
                {"nome": r[0], "total": float(r[1] or 0), "n": r[2]}
                for r in s.query(
                    OrdemBancaria.favorecido_nome,
                    sa.func.sum(OrdemBancaria.valor),
                    sa.func.count(OrdemBancaria.id),
                ).filter(OrdemBancaria.favorecido_nome.isnot(None))
                .group_by(OrdemBancaria.favorecido_nome)
                .order_by(sa.desc(sa.func.sum(OrdemBancaria.valor)))
                .limit(12).all()
            ]
            obs_recentes = [
                {"numero": o.numero_ob, "data": str(o.data_emissao),
                 "favorecido": o.favorecido_nome or "—",
                 "valor": float(o.valor) if o.valor else 0,
                 "processo": o.numero_processo or "—", "status": o.status or "—"}
                for o in s.query(OrdemBancaria)
                .order_by(desc(OrdemBancaria.data_emissao), desc(OrdemBancaria.id))
                .limit(25).all()
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

            return JSONResponse(content=_cache_put("painel:snapshot", {
                "atualizado": str(hoje),
                "obs": {"total": total_obs, "hoje": obs_hoje,
                        "valor_hoje": float(valor_hoje), "valor_total": float(valor_total)},
                "alertas": {"alta": alta, "media": media,
                            "total": s.query(Alerta).count()},
                "ultima_coleta": ultima_coleta,
                "lista_alertas": alertas,
                "top_favorecidos": top,
                "obs_recentes": obs_recentes,
                "licoes": licoes,
            }))
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
        import sqlalchemy as sa
        from datetime import date, timedelta
        from pathlib import Path
        from compliance_agent.database.models import (
            get_session, init_db, OrdemBancaria,
        )

        init_db()
        session = get_session()
        try:
            hoje = date.today()
            inicio = hoje - timedelta(days=30)

            rows = (
                session.query(OrdemBancaria)
                .filter(OrdemBancaria.data_emissao >= inicio)
                .order_by(
                    sa.desc(OrdemBancaria.data_emissao),
                    sa.desc(OrdemBancaria.id),
                )
                .all()
            )

            obs_list = []
            erros = []
            for o in rows:
                credor = (o.favorecido_cpf or "").strip() or (o.favorecido_banco or "").strip()
                ob_info = {
                    "id": o.id,
                    "numero_ob": o.numero_ob,
                    "numero_sei": o.numero_sei or "—",
                    "numero_processo": o.numero_processo or "—",
                    "credor": credor,
                    "favorecido": o.favorecido_nome or "—",
                    "ug": o.ug_codigo or "—",
                    "tipo": o.tipo_ob or "—",
                    "status": o.status or "—",
                    "categoria": o.categoria or "outros",
                    "data_emissao": str(o.data_emissao) if getattr(o, "data_emissao", None) else "—",
                    "data_pagamento": str(o.data_pagamento) if getattr(o, "data_pagamento", None) else "—",
                    "valor": float(o.valor) if o.valor is not None else 0.0,
                }
                obs_list.append(ob_info)

                if not o.numero_sei:
                    erros.append({
                        "tipo": "SEI ausente",
                        "OB": o.numero_ob or str(o.id),
                        "favorecido": ob_info["favorecido"],
                        "valor": ob_info["valor"],
                    })
                if o.status and o.status.lower() in {"anulada", "cancelada"}:
                    erros.append({
                        "tipo": f"OB {o.status.lower()}",
                        "OB": o.numero_ob or str(o.id),
                        "favorecido": ob_info["favorecido"],
                        "valor": ob_info["valor"],
                    })
                if o.numero_sei and "SEI-" not in (o.numero_sei or ""):
                    erros.append({
                        "tipo": "SEI em formato suspeito",
                        "OB": o.numero_ob or str(o.id),
                        "favorecido": ob_info["favorecido"],
                        "valor": ob_info["valor"],
                        "detalhe": o.numero_sei,
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
            linhas.append(f"Gerado em {hoje} | Janela {inicio} a {hoje}")
            linhas.append("")
            linhas.append(f"- OBs analisadas: {len(obs_list)}")
            linhas.append(f"- Erros coletados: {len(erros)}")
            linhas.append("")

            linhas.append("## Resumo por categoria")
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
        finally:
            session.close()
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

        # Alert counts by severity
        sev_counts = {}
        for row in session.query(Alerta.severidade, func.count(Alerta.id)).group_by(Alerta.severidade).all():
            sev_counts[row[0] or "desconhecida"] = row[1]

        # Alert counts by tipo
        tipo_counts = {}
        for row in session.query(Alerta.tipo, func.count(Alerta.id)).group_by(Alerta.tipo).all():
            tipo_counts[row[0] or "outros"] = row[1]

        total_alertas   = session.query(Alerta).count()
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
    import sqlite3 as _sq
    DB = str(RAIZ / "data" / "compliance.db")
    try:
        con = _sq.connect(f"file:{DB}?mode=ro", uri=True); con.row_factory = _sq.Row
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
    import sqlite3 as _sq
    import datetime as _dt
    p = payload or {}
    cnpj = str(p.get("cnpj") or "").strip()
    ver = str(p.get("veredito") or "").strip().lower()
    nota = str(p.get("nota") or "")[:480]
    mapa = {"suspeito": ("fachada", "INDICIO"), "ok": ("real", "AFASTADO"), "mais_info": ("pular", None)}
    if not cnpj or ver not in mapa:
        return JSONResponse(content={"ok": False, "erro": "cnpj e veredito (suspeito|ok|mais_info) obrigatórios"})
    status_vd, novo_status = mapa[ver]
    DB = str(RAIZ / "data" / "compliance.db")
    try:
        con = _sq.connect(DB, timeout=30); con.execute("PRAGMA busy_timeout=30000")
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
        from compliance_agent.database.fts import buscar_contratos_fts, buscar_doerj_fts, buscar_alertas_fts
        from compliance_agent.database.models import init_db

        init_db()
        result = {}
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
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/api/sugestoes")
def api_sugestoes(q: str = "", limite: int = 8):
    """Autocomplete leve: empresas (favorecido_resumo, prefixo no nome ou no CNPJ) +
    nomeados (registros_folha=estado, pcrj_comissionado_candidato=prefeitura). Prefixo
    de ≥2 caracteres (por palavra, não só início do nome inteiro) — sugestão enquanto
    digita, não busca completa (isso é o /api/compliance/buscar, no Enter)."""
    import sqlite3 as _sq
    termo = (q or "").strip().upper()
    if len(termo) < 2:
        return JSONResponse({"ok": True, "empresas": [], "nomeados": []})
    lim = max(1, min(int(limite or 8), 20))
    prefixo, meio = f"{termo}%", f"% {termo}%"
    digitos = "".join(c for c in termo if c.isdigit())
    empresas: list[dict] = []
    nomeados: list[dict] = []
    try:
        con = _sq.connect(f"file:{RAIZ / 'data' / 'compliance.db'}?mode=ro", uri=True)
        con.row_factory = _sq.Row
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
    except Exception:  # noqa: BLE001
        pass  # sugestão é best-effort — indisponibilidade não deve quebrar a caixa de busca
    try:
        conp = _sq.connect(f"file:{RAIZ / 'data' / 'pcrj.db'}?mode=ro", uri=True)
        conp.row_factory = _sq.Row
        rows3 = conp.execute(
            "SELECT DISTINCT nome_pcrj nome, cargo_pcrj cargo, orgao_pcrj orgao "
            "FROM pcrj_comissionado_candidato WHERE nome_pcrj LIKE ? OR nome_pcrj LIKE ? LIMIT ?",
            (prefixo, meio, lim)).fetchall()
        nomeados += [{"nome": r["nome"], "cargo": r["cargo"], "orgao": r["orgao"], "esfera": "prefeitura"}
                     for r in rows3]
        conp.close()
    except Exception:  # noqa: BLE001
        pass
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

        res = conflito(cnpj=cnpj or None, candidato=candidato or None, limite=limite)
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
        contratacoes = await pncp.buscar_contratacoes(
            uf=uf, data_ini=hoje - timedelta(days=dias), data_fim=hoje,
            modalidade=(modalidade or None), abertos=abertos,
            orgao_cnpj=(orgao or None))
        if esfera and esfera != "todas":
            # esfera OFICIAL do ente (pncp_ente + exceções de unidade) — aba estanque no painel
            import sqlite3 as _sq
            from compliance_agent.collectors.pncp_resultados import (
                classificar_esfera, esferas_por_ente)
            _c = _sq.connect(f"file:{RAIZ / 'data' / 'compliance.db'}?mode=ro", uri=True)
            try:
                oficial = esferas_por_ente(_c)
            finally:
                _c.close()
            contratacoes = [x for x in contratacoes if classificar_esfera(
                {"orgao_cnpj": x.get("orgao_cnpj"), "orgao_nome": x.get("orgao"),
                 "unidade_nome": x.get("unidade"), "municipio": x.get("municipio")},
                oficial) == esfera]
        return JSONResponse(content={
            "ok": True, "modo": "abertos" if abertos else "publicacao",
            "uf": uf, "n": len(contratacoes), "contratacoes": contratacoes,
            "_fonte": "PNCP API consulta (sem login)",
            "_nota": "Indício/triagem; red_flags do edital virão da Onda 2c. Proveniência: link+id_pncp."})
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

        res = await varrer_direcionamento(uf=uf, ug=(ug or None), objeto=(objeto or None),
                                          max_itens=max(1, min(int(max_itens), 15)))
        return JSONResponse(content=res)
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
    import asyncio as _aio
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
        resposta = await _aio.to_thread(fn)
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
        import sys as _sys
        _sys.path.insert(0, str(RAIZ))
        from tools import sei_restritos as _R
        itens = _R.listar(todos=bool(todos))
        return JSONResponse({"ok": True, "n": len(itens), "itens": itens})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(e), "itens": []}, status_code=500)


@router.get("/api/flags")
def api_flags():
    """Flags vermelhos GRAVES da fiscalização (data/flags_graves.json)."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(RAIZ))
        from tools import flags_graves as _F
        itens = _F.listar()
        return JSONResponse({"ok": True, "n": len(itens), "itens": itens})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(e), "itens": []}, status_code=500)


@router.get("/controle")
async def pagina_controle():
    """Página de CONTROLE (dark, mobile): flags graves + processos SEI restritos. Consome /api/flags e /api/restritos."""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_CONTROLE_HTML)


_CONTROLE_HTML = r"""<!doctype html><html lang=pt-BR><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>JFN — Controle</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--bd:#272b34;--tx:#e6e8ec;--mut:#9aa2ad;--crit:#e5484d;--alta:#e08a2b;--med:#d9c33a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;padding:16px;max-width:1000px;margin:auto}
h1{font-size:18px;margin:.2em 0}h2{font-size:15px;color:var(--mut);margin:1.4em 0 .5em;border-bottom:1px solid var(--bd);padding-bottom:4px}
.card{background:var(--card);border:1px solid var(--bd);border-left:4px solid var(--bd);border-radius:8px;padding:10px 12px;margin:8px 0}
.card.CRÍTICA{border-left-color:var(--crit)}.card.ALTA{border-left-color:var(--alta)}.card.MÉDIA{border-left-color:var(--med)}
.g{display:inline-block;font-size:11px;font-weight:700;padding:1px 7px;border-radius:10px;background:#222;color:#fff}
.g.CRÍTICA{background:var(--crit)}.g.ALTA{background:var(--alta)}.g.MÉDIA{background:var(--med);color:#111}
.caso{font-weight:600}.tit{margin:4px 0}.meta{color:var(--mut);font-size:12.5px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--bd)}
th{color:var(--mut);font-weight:600}.pill{font-size:11px;font-weight:700;padding:1px 7px;border-radius:10px}
.pill.RESTRITO{background:var(--crit);color:#fff}.pill.RESTRITO\?{background:var(--alta);color:#fff}.pill.PARCIAL{background:var(--med);color:#111}
.upd{color:var(--mut);font-size:12px;margin-top:2em}code{background:#222;padding:1px 5px;border-radius:4px}
.voltar{display:inline-flex;align-items:center;gap:7px;text-decoration:none;color:var(--tx);
  background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:8px 14px;
  font-weight:600;font-size:13.5px;margin-bottom:12px;transition:.15s}
.voltar:hover{border-color:var(--mut);background:#1d212a}
.voltar .a{font-size:16px;line-height:1}
</style></head><body>
<a class=voltar href="/painel" aria-label="Voltar ao painel"><span class=a>←</span> Voltar ao painel</a>
<h1>🛡️ JFN — Controle de fiscalização</h1>
<div class=meta>Flags vermelhos graves e processos SEI restritos. Atualiza sozinho ao longo dos sweeps.</div>
<h2 id=hf>🚩 Flags vermelhos graves</h2><div id=flags>carregando…</div>
<h2 id=hr>🔒 Processos SEI restritos <span class=meta id=rct></span></h2><div id=restr>carregando…</div>
<div class=upd id=upd></div>
<script>
const brl=v=>{v=+v;return !v?'':'R$ '+v.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})};
async function j(u){try{const r=await fetch(u);return await r.json()}catch(e){return{ok:false,itens:[]}}}
(async()=>{
 const f=await j('/api/flags');
 document.getElementById('flags').innerHTML = (f.itens||[]).map(e=>`
   <div class="card ${e.gravidade}"><span class="g ${e.gravidade}">${e.gravidade||''}</span>
   <span class=caso> ${e.caso||''}</span><div class=tit>${e.titulo||''}</div>
   <div class=meta>${e.valor>0?('💰 '+brl(e.valor)+' · '):''}${e.base_legal?('⚖️ '+e.base_legal):''}${e.status?(' · 📌 '+e.status):''}</div></div>`).join('') || '<div class=meta>sem flags</div>';
 const r=await j('/api/restritos');
 document.getElementById('rct').textContent = '('+(r.itens||[]).length+')';
 document.getElementById('restr').innerHTML = (r.itens||[]).length ? `<table><tr><th>Status</th><th>Processo</th><th>Unidade</th><th>Existe</th><th>Leit.</th><th>Última</th></tr>`+
   r.itens.map(e=>`<tr><td><span class="pill ${e.status}">${e.status||''}</span></td><td><code>${e.numero||''}</code></td><td>${e.unidade||'—'}</td><td>${e.fonte_existencia||e.existe||'—'}</td><td>${e.n_leituras||0}</td><td>${e.ultima||''}</td></tr>`).join('')+`</table>` : '<div class=meta>Nenhum restrito ainda — a lista se alimenta ao longo dos sweeps.</div>';
 document.getElementById('upd').textContent = 'atualizado '+new Date().toLocaleString('pt-BR');
})();
</script></body></html>"""


# ─────────────────────────────────────────────────────────────────────────────
# CENTRAL DE INTELIGÊNCIA (painel v2) — conluio PNCP, nomeados×candidatos, laranjas
# ─────────────────────────────────────────────────────────────────────────────
import time as _time

_cache: dict = {}


def _cache_get(chave: str, ttl: int):
    v = _cache.get(chave)
    if v and (_time.time() - v[0]) < ttl:
        return v[1]
    return None


def _cache_put(chave: str, val):
    _cache[chave] = (_time.time(), val)
    return val


@router.get("/api/certames/lista")
def api_certames_lista(esfera: str = "prefeitura", limite: int = 600, q: str = ""):
    """Certames da base LOCAL, cada um com a SUA análise (Índice de Direcionamento + temas).

    A aba Contratos do painel deixa de depender do PNCP ao vivo (lento/instável) — lê
    edital_documento + certame_indice. `temas` = famílias com sinal (valor>0) do
    familias_json; certame com confiança 0 sai como analisado=False (INDISPONÍVEL ≠ 0,
    nunca "score 0"). Ordena: analisados por prioridade desc, depois os demais por ano."""
    import json as _json
    import sqlite3 as _sq
    raiz_cnpj = {"prefeitura": "42498733", "estado": "42498600"}.get(esfera)
    lim = max(1, min(int(limite or 600), 2000))
    termo = f"%{q.strip()}%" if q.strip() else None
    try:
        con = _sq.connect(f"file:{RAIZ / 'data' / 'compliance.db'}?mode=ro", uri=True)
        con.row_factory = _sq.Row
        sql = ("SELECT ed.numero_controle_pncp nc, ed.ano, ed.objeto, ed.valor_estimado, "
               "ci.score, ci.faixa, ci.confianca, ci.prioridade, ci.familias_json "
               "FROM edital_documento ed LEFT JOIN certame_indice ci "
               "ON ci.certame = ed.numero_controle_pncp WHERE 1=1")
        params: list = []
        if raiz_cnpj:
            sql += " AND substr(ed.orgao_cnpj,1,8) = ?"
            params.append(raiz_cnpj)
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
            "FROM edital_documento ed" + (" WHERE substr(ed.orgao_cnpj,1,8)=?" if raiz_cnpj else ""),
            ([raiz_cnpj] if raiz_cnpj else [])).fetchone()
        con.close()
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)
    itens = []
    for r in rows:
        analisado = (r["confianca"] or 0) > 0
        temas = []
        if analisado and r["familias_json"]:
            try:
                fams = _json.loads(r["familias_json"])
                temas = sorted(
                    ({"familia": nome, "valor": round(f["valor"], 2)}
                     for nome, f in fams.items() if f.get("apuravel") and (f.get("valor") or 0) > 0),
                    key=lambda t: -t["valor"])
            except (ValueError, TypeError):
                pass
        itens.append({"nc": r["nc"], "ano": r["ano"], "objeto": r["objeto"],
                      "valor_estimado": r["valor_estimado"], "analisado": analisado,
                      "score": r["score"] if analisado else None,
                      "faixa": r["faixa"] if analisado else None,
                      "confianca": r["confianca"], "temas": temas})
    return JSONResponse(content={
        "ok": True, "itens": itens,
        "resumo": {"total": total[0], "analisados": total[1] or 0},
        "ressalva": "Índice determinístico e auditável (indício ≠ acusação). Certame sem família "
                    "analisável = INDISPONÍVEL, não zero; a cobertura cresce com o enxame."})


@router.get("/api/pncp/conluio")
def api_pncp_conluio(min_certames: int = 4, esfera: str = ""):
    """Conluio a partir dos RESULTADOS estruturados do PNCP (vencedor homologado por item):
    CAPTURA (1 fornecedor domina o órgão) e RODÍZIO DE VENCEDORES (poucos se revezam) — com
    nome de fornecedor, nome de órgão e amostra de OBJETOS. ?esfera=estado|prefeitura|municipios|
    federal|outros filtra pela esfera OFICIAL do ente (pncp_ente). Indício OCDE a verificar, não acusação."""
    import sqlite3 as _sq
    esf = esfera if esfera in ("estado", "prefeitura", "municipios", "federal", "outros") else None
    ck = f"conluio:{esf or 'todos'}"
    cache = _cache_get(ck, 3600)
    if cache:
        return JSONResponse(cache)
    try:
        from compliance_agent.collectors.pncp_resultados import conluio_enriquecido
        con = _sq.connect(f"file:{RAIZ / 'data' / 'compliance.db'}?mode=ro", uri=True)
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


@router.get("/api/poder/nomeados_candidatos")
def api_nomeados_candidatos(limite: int = 200):
    """Cruzamento SERVIDOR/NOMEADO (registros_folha) × CANDIDATO (doacoes_eleitorais/TSE) por nome.
    Servidor público — sobretudo cargo em comissão — que foi candidato a cargo eletivo. Match por
    NOME (verificar homônimo). Indício de relação político-administrativa, não irregularidade."""
    import sqlite3 as _sq
    lim = max(10, min(int(limite or 200), 1000))
    ck = f"nomcand:{lim}"  # o payload varia com o limite — chave fixa congelava o tamanho p/ todos
    cache = _cache_get(ck, 600)
    if cache:
        return JSONResponse(cache)
    try:
        con = _sq.connect(f"file:{RAIZ / 'data' / 'compliance.db'}?mode=ro", uri=True)
        con.row_factory = _sq.Row
        con.execute("CREATE TEMP TABLE _cand AS SELECT DISTINCT UPPER(TRIM(nome_candidato)) nc, "
                    "cargo_candidato, partido, ano_eleicao FROM doacoes_eleitorais")
        con.execute("CREATE INDEX _tc ON _cand(nc)")
        rows = con.execute(
            "SELECT f.nome, f.cargo, f.orgao_nome, c.cargo_candidato, c.partido, c.ano_eleicao "
            "FROM (SELECT DISTINCT nome, cargo, orgao_nome FROM registros_folha) f "
            "JOIN _cand c ON UPPER(TRIM(f.nome))=c.nc "
            "ORDER BY f.nome LIMIT ?", (lim,)).fetchall()
        con.close()
        comissao = [r for r in rows if "comiss" in (r["cargo"] or "").lower()]
        itens = [{"nome": r["nome"], "cargo_folha": r["cargo"], "orgao": r["orgao_nome"],
                  "cargo_disputado": r["cargo_candidato"], "partido": r["partido"],
                  "ano": r["ano_eleicao"],
                  "comissionado": "comiss" in (r["cargo"] or "").lower()} for r in rows]
        out = {"ok": True, "total": len(itens), "n_comissionados": len(comissao), "itens": itens,
               "aviso": "Match por NOME (homônimos possíveis) — indício de relação político-administrativa "
                        "a verificar, não irregularidade. Ser candidato é direito; o foco é conflito de interesse."}
        return JSONResponse(_cache_put(ck, out))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/laranjas")
def api_laranjas(limite: int = 100):
    """Sócios de fornecedores do Estado que RECEBEM benefício social de subsistência (bolsa família etc.)
    — indício clássico de LARANJA/interposição (art. 337-F CP): quem figura como dono de empresa que
    recebe do Estado não deveria depender de auxílio. Só os confirmados (recebe_beneficio=1)."""
    import json as _json
    import sqlite3 as _sq
    try:
        con = _sq.connect(f"file:{RAIZ / 'data' / 'compliance.db'}?mode=ro", uri=True)
        con.row_factory = _sq.Row
        rows = con.execute(
            "SELECT socio_nome_norm, cpf_resolvido, beneficios_json, motivo, confianca "
            "FROM socio_beneficio WHERE recebe_beneficio=1 ORDER BY confianca DESC LIMIT ?",
            (max(10, min(int(limite or 100), 500)),)).fetchall()
        con.close()
        itens = []
        for r in rows:
            try:
                bens = _json.loads(r["beneficios_json"] or "[]")
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
    """Ranking pesquisável de perícias de fornecedor (pericia_fornecedor). ?q=nome/cnpj &grau=🟡/🟢
    &ordem=score|total. Cada fornecedor é agregado (maior grau, soma de OB, achados). Indício."""
    import sqlite3 as _sq
    try:
        con = _sq.connect(f"file:{RAIZ / 'data' / 'compliance.db'}?mode=ro", uri=True)
        con.row_factory = _sq.Row
        col = "total" if ordem == "total" else "score"
        params: list = []
        where = "WHERE 1=1"
        if q:
            where += " AND (favorecido LIKE ? OR cnpj LIKE ?)"
            params += [f"%{q}%", f"%{q.replace('.', '').replace('/', '').replace('-', '')}%"]
        if grau:
            where += " AND grau = ?"
            params.append(grau)
        rows = con.execute(
            f"SELECT cnpj, MAX(favorecido) favorecido, "
            f"       CASE WHEN SUM(CASE WHEN grau='🔴' THEN 1 ELSE 0 END)>0 THEN '🔴' "
            f"            WHEN SUM(CASE WHEN grau='🟡' THEN 1 ELSE 0 END)>0 THEN '🟡' ELSE '🟢' END grau, "
            f"       MAX(score) score, SUM(total_pago) total, SUM(n_obs) n_obs, "
            f"       SUM(n_confirmados) confirmados, SUM(n_indicios) indicios, COUNT(DISTINCT ug) ugs "
            f"FROM pericia_fornecedor {where} GROUP BY cnpj "
            f"ORDER BY {col} DESC LIMIT ?", (*params, max(10, min(int(limite or 60), 300)))).fetchall()
        con.close()
        itens = [dict(r) for r in rows]
        return JSONResponse({"ok": True, "total": len(itens), "itens": itens})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/perfil")
def api_perfil(cnpj: str):
    """Dossiê 360 INSTANTÂNEO de um CNPJ, montado do banco local (sem rede): perícia (grau/achados),
    pagamento (OB total, órgãos), QSA (sócios), sede/fachada, vitórias no PNCP e sinal de laranja.
    O motor da tela de drill-down do painel. Indício a verificar, nunca acusação."""
    import json as _json
    import sqlite3 as _sq
    dig = "".join(c for c in (cnpj or "") if c.isdigit())
    if len(dig) != 14:
        return JSONResponse({"ok": False, "erro": "informe um CNPJ de 14 dígitos"}, status_code=400)
    try:
        con = _sq.connect(f"file:{RAIZ / 'data' / 'compliance.db'}?mode=ro", uri=True)
        con.row_factory = _sq.Row
        out: dict = {"ok": True, "cnpj": dig, "cnpj_fmt": f"{dig[:2]}.{dig[2:5]}.{dig[5:8]}/{dig[8:12]}-{dig[12:]}"}
        # perícia (agrega por CNPJ)
        per = con.execute(
            "SELECT MAX(favorecido) nome, MAX(score) score, SUM(total_pago) total, SUM(n_obs) n_obs, "
            "SUM(n_confirmados) confirmados, SUM(n_indicios) indicios, COUNT(DISTINCT ug) ugs, "
            "CASE WHEN SUM(CASE WHEN grau='🔴' THEN 1 ELSE 0 END)>0 THEN '🔴' "
            "WHEN SUM(CASE WHEN grau='🟡' THEN 1 ELSE 0 END)>0 THEN '🟡' ELSE '🟢' END grau "
            "FROM pericia_fornecedor WHERE cnpj=?", (dig,)).fetchone()
        out["pericia"] = dict(per) if per and per["nome"] else None
        # achados detalhados (do maior score)
        det = con.execute("SELECT achados_json, resumo FROM pericia_fornecedor WHERE cnpj=? "
                          "ORDER BY score DESC LIMIT 1", (dig,)).fetchone()
        if det:
            try:
                out["achados"] = _json.loads(det["achados_json"] or "[]")[:12]
            except (ValueError, TypeError):
                out["achados"] = []
            out["resumo"] = det["resumo"]
        # pagamento (OB TFE) + órgãos
        ob = con.execute("SELECT COUNT(*) n, COALESCE(SUM(valor),0) v, COUNT(DISTINCT ug_codigo) ugs, "
                         "MAX(favorecido_nome) nome FROM ordens_bancarias WHERE favorecido_cpf=?",
                         (dig,)).fetchone()
        out["ob"] = {"n": ob["n"], "total": ob["v"], "orgaos": ob["ugs"]} if ob and ob["n"] else None
        out["nome"] = (out.get("pericia") or {}).get("nome") or (ob["nome"] if ob else None) or "—"
        top_org = con.execute("SELECT ug_codigo, COALESCE(ug_nome,'') nome, SUM(valor) v FROM ordens_bancarias "
                              "WHERE favorecido_cpf=? AND valor>0 GROUP BY ug_codigo ORDER BY v DESC LIMIT 8",
                              (dig,)).fetchall()
        out["orgaos"] = [{"ug": r["ug_codigo"], "nome": r["nome"], "total": r["v"]} for r in top_org]
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
        except Exception:  # noqa: BLE001 — enriquecimento opcional; nunca derruba o dossiê
            pass
        con.close()
        return JSONResponse(out)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


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
            if not (d := _cache_get("intel:sanc", 3600)):
                d = _cache_put("intel:sanc", sancionadas_contratadas())
        d = dict(d)
        d["empresas"] = d.get("empresas", [])[:max(1, min(int(limite or 60), 300))]
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/sancionadas_municipio")
def api_intel_sancionadas_municipio(limite: int = 60):
    """Empresas com sanção IMPEDITIVA contratadas pela PREFEITURA DO RIO (pcrj_contratos fonte='pncp'),
    com o teste "à época" (contrato ASSINADO dentro da vigência da sanção). Análogo municipal do
    /api/intel/sancionadas (competência TCM-RJ). Descarta órgão federal/estadual (contabiliza)."""
    try:
        from compliance_agent.cruzamentos_intel import sancionadas_municipio
        ck = "intel:sanc_mun"
        if not (d := _cache_get(ck, 3600)):
            d = _cache_put(ck, sancionadas_municipio())
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
        if not (d := _cache_get(ck, 3600)):
            d = _cache_put(ck, concentracao_municipio(limite=max(1, min(int(limite or 60), 200))))
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
            if not (d := _cache_get("intel:conluio", 3600)):
                d = _cache_put("intel:conluio", conluio_qsa(incluir_atas=False))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/comunidades")
def api_intel_comunidades():
    """Comunidades (Louvain) do grafo família-empresa-órgão, ranqueadas por risco 0-100.
    Sai do cache (construir o grafo completo não roda no request)."""
    try:
        from compliance_agent.cruzamentos_intel import ler_cache_intel
        d = ler_cache_intel("comunidades")
        if not d:
            return JSONResponse({"ok": False, "erro": "cache ainda não gerado — "
                                 "rodar: python -m compliance_agent.cruzamentos_intel cache"})
        return JSONResponse(d)
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
            if not (d := _cache_get(f"intel:radar:{lim}", 3600)):
                d = _cache_put(f"intel:radar:{lim}", radar_risco(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/retro")
def api_intel_retro():
    """Retro-auditoria (hindsight): por detector, sanção POSTERIOR ao 1º sinal (corroboração
    independente) e R$ pagos/vitórias APÓS o alerta (custo da inação). Ledger diário no timer."""
    try:
        from compliance_agent.retro_auditoria import medir
        if not (d := _cache_get("intel:retro", 3600)):
            d = _cache_put("intel:retro", medir())
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
        if not (d := _cache_get(ck, 600)):
            d = _cache_put(ck, buscar_grupos(t, esfera=esfera or None))
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
        if not (d := _cache_get(ck, 600)):
            d = _cache_put(ck, comparar(g, unidade or None, esfera=esfera or None))
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
        if not (d := _cache_get(ck, 1800)):
            d = _cache_put(ck, economia_potencial(esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/vedada")
def api_comparador_vedada(esfera: str = ""):
    """O número mais forte: sobrepreço (acima da mediana) pago a fornecedor JURIDICAMENTE VEDADO
    de contratar com aquele ente comprador, VIGENTE à época. Inidoneidade veda todos."""
    try:
        from compliance_agent.comparador_precos import economia_vedada
        ck = f"comp:vedada:{esfera or 'todas'}"
        if not (d := _cache_get(ck, 1800)):
            d = _cache_put(ck, economia_vedada(esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/sancoes/detalhar")
def api_sancoes_detalhar(cnpj: str = "", esfera: str = "estadual", uf: str = "RJ"):
    """Detalha as sanções de um CNPJ: tipo, abrangência, órgão, vigência e se VEDA de fato o
    contrato com o ente-alvo (default Estado-RJ). Responde 'quais são e qual a abrangência'."""
    try:
        import sqlite3 as _sq
        from compliance_agent.sancao_abrangencia import detalhar
        c = re.sub(r"\D", "", cnpj or "")
        if len(c) != 14:
            return JSONResponse({"ok": False, "erro": "CNPJ inválido"})
        con = _sq.connect(f"file:{RAIZ / 'data' / 'compliance.db'}?mode=ro", uri=True)
        con.row_factory = _sq.Row
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
        if not (d := _cache_get(ck, 1800)):
            d = _cache_put(ck, caro_e_suspeito(esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/orgaos")
def api_comparador_orgaos(esfera: str = ""):
    """Ranking de órgãos por eficiência de gasto (razão preço/mercado ao longo de muitos itens)."""
    try:
        from compliance_agent.comparador_precos import ranking_orgaos
        ck = f"comp:orgaos:{esfera or 'todas'}"
        if not (d := _cache_get(ck, 1800)):
            d = _cache_put(ck, ranking_orgaos(esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/fornecedores")
def api_comparador_fornecedores(esfera: str = ""):
    """Ranking de fornecedores por preço relativo (mais caros / mais baratos vs mercado)."""
    try:
        from compliance_agent.comparador_precos import ranking_fornecedores
        ck = f"comp:forn:{esfera or 'todas'}"
        if not (d := _cache_get(ck, 1800)):
            d = _cache_put(ck, ranking_fornecedores(esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/lift")
def api_intel_lift():
    """Validação de cada detector contra o gabarito OBJETIVO (sanções impeditivas): LIFT = taxa de
    sancionados no que o detector marca ÷ taxa-base do universo. lift>1 = sinal; <1 = anti-sinal."""
    try:
        from compliance_agent.retro_auditoria import avaliar_lift
        if not (d := _cache_get("intel:lift", 3600)):
            d = _cache_put("intel:lift", avaliar_lift())
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/fracionamento")
def api_intel_fracionamento(limite: int = 120):
    """Possível fracionamento de despesa: favorecido+UG+mês com várias OBs coladas no teto de
    dispensa (fatiar p/ não licitar, Lei 14.133 art. 75 §1º). Ordena por concentração colada."""
    try:
        from compliance_agent.cruzamentos_intel import fracionamento
        lim = max(1, min(int(limite or 120), 300))
        if not (d := _cache_get(f"intel:frac:{lim}", 600)):
            d = _cache_put(f"intel:frac:{lim}", fracionamento(limite=lim))
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
        if not (d := _cache_get(f"intel:capinc:{lim}", 600)):
            d = _cache_put(f"intel:capinc:{lim}", capital_incompativel(limite=lim))
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
        if not (d := _cache_get(f"intel:prival:{lim}:{ms}", 900)):
            d = _cache_put(f"intel:prival:{lim}:{ms}", prioridade_valor(min_score=ms, limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/fornecedor_dependente")
def api_intel_fornecedor_dependente(limite: int = 120):
    """Fornecedor comercial com ≥90% da receita do Estado numa única unidade gestora ('empresa do órgão')."""
    try:
        from compliance_agent.cruzamentos_intel import fornecedor_dependente
        lim = max(1, min(int(limite or 120), 300))
        if not (d := _cache_get(f"intel:dep:{lim}", 3600)):
            d = _cache_put(f"intel:dep:{lim}", fornecedor_dependente(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/corrida_dezembro")
def api_intel_corrida_dezembro(limite: int = 120):
    """Fornecedor comercial com ≥75% do valor do ano concentrado em dezembro (corrida do empenho)."""
    try:
        from compliance_agent.cruzamentos_intel import corrida_dezembro
        lim = max(1, min(int(limite or 120), 300))
        if not (d := _cache_get(f"intel:dez:{lim}", 600)):
            d = _cache_put(f"intel:dez:{lim}", corrida_dezembro(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/grafo_familias")
def api_intel_grafo_familias():
    """Grafo D3 (nodes/links) das famílias que ocupam cargo de confiança E fornecem ao Estado —
    consumido pelo graph.html em /graph?fonte=familias."""
    try:
        from compliance_agent.cruzamentos_intel import grafo_familias
        if not (d := _cache_get("intel:grafofam", 600)):
            d = _cache_put("intel:grafofam", grafo_familias(db_path=str(RAIZ / "data" / "compliance.db")))
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
        if not (d := _cache_get(f"intel:fenix:{lim}", 600)):
            d = _cache_put(f"intel:fenix:{lim}", empresa_fenix(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/porta_giratoria")
def api_intel_porta_giratoria(limite: int = 120):
    """Porta giratória: ex-servidor (inativo/exonerado) que virou sócio de fornecedor do Estado."""
    try:
        from compliance_agent.cruzamentos_intel import porta_giratoria
        lim = max(1, min(int(limite or 120), 300))
        if not (d := _cache_get(f"intel:porta:{lim}", 3600)):
            d = _cache_put(f"intel:porta:{lim}", porta_giratoria(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/nepotismo_cruzado")
def api_intel_nepotismo_cruzado(limite: int = 60):
    """Nepotismo cruzado: colocação recíproca de parentes entre dois órgãos (dribla a SV13)."""
    try:
        from compliance_agent.cruzamentos_intel import nepotismo_cruzado
        lim = max(1, min(int(limite or 60), 200))
        if not (d := _cache_get(f"intel:nepcruz:{lim}", 3600)):
            d = _cache_put(f"intel:nepcruz:{lim}", nepotismo_cruzado(limite=lim))
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
        if not (d := _cache_get(f"intel:nep:{lim}", 3600)):
            d = _cache_put(f"intel:nep:{lim}", nepotismo(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/socio_oculto")
def api_intel_socio_oculto(limite: int = 120):
    """Pessoa/holding sócia de ≥3 empresas fornecedoras do Estado (empresário oculto / grupo familiar)."""
    try:
        from compliance_agent.cruzamentos_intel import socio_oculto
        lim = max(1, min(int(limite or 120), 300))
        if not (d := _cache_get(f"intel:ocult:{lim}", 600)):
            d = _cache_put(f"intel:ocult:{lim}", socio_oculto(limite=lim))
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
        if not (d := _cache_get(ck, 600)):
            d = _cache_put(ck, aditivos_estouro(limite=lim, esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/socio_servidor")
def api_intel_socio_servidor(limite: int = 150):
    """Servidor público (folha) que é sócio de fornecedor do Estado — conflito de interesse
    (Lei 14.133 art. 9) e, se administrador, vedação estatutária de gerência. Nome + fragmento de CPF."""
    try:
        from compliance_agent.cruzamentos_intel import socio_servidor
        lim = max(1, min(int(limite or 150), 300))
        if not (d := _cache_get(f"intel:socserv:{lim}", 3600)):
            d = _cache_put(f"intel:socserv:{lim}", socio_servidor(limite=lim))
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
        if not (d := _cache_get(ck, 600)):
            d = _cache_put(ck, escalada_preco(limite=lim, esfera=esfera or None))
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
        if not (d := _cache_get(ck, 600)):
            d = _cache_put(ck, sobrepreco(limite=lim, esfera=esfera or None))
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
        if not (d := _cache_get(f"intel:fant:{lim}", 600)):
            d = _cache_put(f"intel:fant:{lim}", ranking_fantasmas(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/hub_compartilhado")
def api_intel_hub_compartilhado(chave: str = "endereco", min: int = 5):
    """Hub compartilhado: 1 âncora física (endereço/telefone/e-mail) usada por N CNPJs — assinatura
    de 'ninho de fantasmas'. Guarda anti-FP rebaixa massa legítima (contador, galeria, coworking)."""
    from datetime import datetime as _dt
    try:
        from compliance_agent.cruzamentos_intel import hub_compartilhado
        ch = chave if chave in ("endereco", "telefone", "email") else "endereco"
        mn = int(min or 5)
        mn = 2 if mn < 2 else (100 if mn > 100 else mn)
        if not (d := _cache_get(f"intel:hub:{ch}:{mn}", 600)):
            d = _cache_put(f"intel:hub:{ch}:{mn}", hub_compartilhado(chave=ch, min_cnpjs=mn))
        return JSONResponse({"ok": d.get("ok", True), "grupos": d.get("grupos", []),
                             "erro": d.get("erro"), "explicacao": d.get("explicacao"),
                             "ressalva": d.get("ressalva"),
                             "gerado_em": _dt.now().strftime("%Y-%m-%d %H:%M")})
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
    import sqlite3 as _sq
    try:
        lim = max(1, min(int(limite or 300), 1000))
        ck = f"pcrj:comis_cand:v2:{lim}"  # v2: payload agora é por pessoa, não por linha
        if d := _cache_get(ck, 600):
            return JSONResponse(d)
        con = _sq.connect(f"file:{RAIZ / 'data' / 'pcrj.db'}?mode=ro", uri=True)
        con.row_factory = _sq.Row
        try:
            rows = [dict(r) for r in con.execute(
                "SELECT nome_norm, nome_pcrj, cargo_pcrj, orgao_pcrj, admissao, exoneracao, "
                "matricula, cand_ano, cand_cargo, cand_cidade FROM pcrj_comissionado_candidato")]
            n_linhas = len(rows)
        finally:
            con.close()

        from compliance_agent.pcrj.comissionados_candidatos import agrupar_por_pessoa
        out_pessoas = agrupar_por_pessoa(rows)
        n_pessoas = len(out_pessoas)
        truncado = len(out_pessoas) > lim
        out_pessoas = out_pessoas[:lim]

        out = {"ok": True, "n": n_linhas, "n_pessoas": n_pessoas, "truncado": truncado,
               "comissionados": out_pessoas,
               "explicacao": ("Cruzamento por nome entre a folha de comissionados da Prefeitura do "
                              "Rio e as candidaturas do TSE. Comissionado que concorreu (ou concorre) "
                              "a cargo eletivo é sinal de aparelhamento político do cargo de confiança. "
                              "Cada pessoa aparece uma vez, com o histórico de nomeações abaixo."),
               "ressalva": "Match por NOME (homônimo possível) — confirmar por CPF antes de citar."}
        return JSONResponse(_cache_put(ck, out))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pcrj/fantasmas")
def api_pcrj_fantasmas(faixa: str = "", limite: int = 200):
    """Servidor-fantasma na folha da Câmara/PCRJ — 8 sinais determinísticos (pcrj/fantasma_servidor),
    cache materializado em pcrj_fantasma_servidor. ?faixa=forte|verificar|fraco filtra."""
    import sqlite3 as _sq
    try:
        lim = max(1, min(int(limite or 200), 800))
        fx = faixa if faixa in ("forte", "verificar", "fraco") else ""
        ck = f"pcrj:fantasma:{fx}:{lim}"
        if d := _cache_get(ck, 600):
            return JSONResponse(d)
        con = _sq.connect(f"file:{RAIZ / 'data' / 'pcrj.db'}?mode=ro", uri=True)
        con.row_factory = _sq.Row
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
                              "escore; faixa FORTE = convergência de sinais independentes."),
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
    import json as _json
    import sqlite3 as _sq
    try:
        lim = max(5, min(int(limite_por_detector or 40), 200))
        ck = f"pcrj:gastos:{lim}"
        if d := _cache_get(ck, 600):
            return JSONResponse(d)
        con = _sq.connect(f"file:{RAIZ / 'data' / 'compliance.db'}?mode=ro", uri=True)
        con.row_factory = _sq.Row
        try:
            rows = con.execute(
                """SELECT tipo, severidade, titulo, descricao, evidencias, MAX(id) id
                   FROM alertas WHERE tipo LIKE 'pcrj_d%' GROUP BY titulo
                   ORDER BY CASE severidade WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END, id DESC
                """).fetchall()
        finally:
            con.close()
        # o detector de EXIBIÇÃO vem do subtipo da evidência quando houver — corrige o histórico
        # em que aditivo_estourado saía sob o código d10 (duas análises num rótulo, pré-split D11)
        _sub2det = {"fracionamento": "d7_fracionamento", "recem_aberta": "d8_credor_recem_aberto",
                    "socio_folha": "d9_socio_na_folha", "rede_socios": "d10_rede_concorrentes",
                    "aditivo_estourado": "d11_aditivo_estourado",
                    "coendereco": "d12_coendereco_concorrentes"}
        por_det: dict[str, list] = {}
        for r in rows:
            ev = {}
            try:
                ev = _json.loads(r["evidencias"] or "{}")
            except ValueError:
                pass
            det = _sub2det.get(ev.get("subtipo") or "", r["tipo"].replace("pcrj_", ""))
            if len(por_det.setdefault(det, [])) >= lim:
                continue
            por_det[det].append({"detector": det, "severidade": r["severidade"],
                                 "titulo": r["titulo"], "descricao": r["descricao"], "evidencias": ev})
        contagem = {d_: len(v) for d_, v in por_det.items()}
        out = {"ok": True, "detectores": contagem, "achados": por_det,
               "explicacao": ("Perícia determinística sobre despesa por credor (CGM 2019-2023) + "
                              "contratos/licitações municipais (PNCP 2024+): fracionamento colado no "
                              "teto de dispensa, credor recém-aberto, sócio de credor na folha, rede "
                              "societária entre concorrentes e aditivo acima do art. 125."),
               "ressalva": "Indício ≠ acusação; match por NOME vem sinalizado; só a apuração fecha."}
        return JSONResponse(_cache_put(ck, out))
    except Exception as exc:  # noqa: BLE001
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


@router.get("/api/fontes/frescor")
def api_fontes_frescor():
    """Frescor de CADA fonte de dados (última coleta + último dado). O painel mostra em verde/âmbar/
    vermelho — defasagem nunca mais passa despercebida (lição SIAFE 16-17/07: MFA quebrou a coleta
    e nada avisava)."""
    import sqlite3 as _sq
    from datetime import datetime as _dt
    try:
        if d := _cache_get("fontes:frescor", 3600):
            return JSONResponse(d)
        fontes = []

        def _add(nome, q, con, fmt="iso", detalhe=""):
            try:
                v = con.execute(q).fetchone()[0]
                if fmt == "br" and v:  # DD/MM/AAAA → ISO p/ ordenar
                    v = f"{v[6:10]}-{v[3:5]}-{v[0:2]}"
                fontes.append({"fonte": nome, "ultimo": v, "detalhe": detalhe})
            except Exception as exc:  # noqa: BLE001
                fontes.append({"fonte": nome, "ultimo": None, "detalhe": f"erro: {exc}"})

        con = _sq.connect(f"file:{RAIZ / 'data' / 'compliance.db'}?mode=ro", uri=True)
        try:
            _add("SIAFE · OB orçamentária (coleta)", "SELECT MAX(coletado_em) FROM ob_orcamentaria_siafe", con,
                 detalhe="coletor diário 05:00 (MFA mensal)")
            _add("SIAFE · OB orçamentária (dado)",
                 "SELECT MAX(substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)) "
                 "FROM ob_orcamentaria_siafe WHERE exercicio=(SELECT MAX(exercicio) FROM ob_orcamentaria_siafe)", con,
                 detalhe="data da OB mais nova")
            _add("PNCP · resultados", "SELECT MAX(coletado_em) FROM pncp_resultado", con,
                 detalhe="timer semanal (dom 01:40)")
            # sancoes/folha não têm coletado_em: proxy = data da sanção mais nova / competência mais nova
            _add("Sanções CEIS/CNEP", "SELECT MAX(data_inicio) FROM sancoes_federais", con,
                 detalhe="sanção mais nova · timer semanal (dom 05:40)")
            _add("Folhas (Estado)", "SELECT MAX(competencia)||'-01' FROM registros_folha", con,
                 detalhe="competência mais nova · DPE + CMRJ + TJRJ")
        finally:
            con.close()
        try:
            con2 = _sq.connect(f"file:{RAIZ / 'data' / 'pcrj.db'}?mode=ro", uri=True)
            try:
                _add("PCRJ · folha Prefeitura", "SELECT MAX(coletado_em) FROM pcrj_folha_pref", con2)
                _add("PCRJ · comissionados×candidatos",
                     "SELECT MAX(coletado_em) FROM pcrj_comissionado_candidato", con2)
            finally:
                con2.close()
        except Exception as exc:  # noqa: BLE001
            fontes.append({"fonte": "PCRJ", "ultimo": None, "detalhe": f"erro: {exc}"})
        hoje = _dt.now()
        for f in fontes:
            try:
                idade = (hoje - _dt.fromisoformat(str(f["ultimo"])[:19])).days
            except Exception:
                idade = None
            f["idade_dias"] = idade
            f["estado"] = ("ok" if idade is not None and idade <= 3 else
                           "atencao" if idade is not None and idade <= 10 else "critico")
        out = {"ok": True, "fontes": fontes, "gerado": hoje.strftime("%Y-%m-%d %H:%M")}
        return JSONResponse(_cache_put("fontes:frescor", out))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)
