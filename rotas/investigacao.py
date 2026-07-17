# -*- coding: utf-8 -*-
"""Rotas investigacao do JFN — extraído de server.py (split 2026-07-06; rede: tests/test_server_snapshot.py).
Handlers idênticos aos originais; só o decorador mudou de @app p/ @router."""
from __future__ import annotations

import logging
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
async def api_anomalias(orgao: Optional[str] = None, fornecedor: Optional[str] = None, top: int = 20,
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
async def api_cartel(modo: str = "captura", cnpj: Optional[str] = None, top: int = 20):
    """Grafo fornecedor↔órgão (Onda 3). ?modo=captura (UGs concentradas) | dependencia (fornecedores
    presos a 1 órgão) | vizinhanca&cnpj=... (co-ocorrência/rodízio). Indício a verificar, nunca acusação."""
    try:
        from compliance_agent import grafo_cartel as G
        top = max(1, min(int(top or 20), 100))
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
        return JSONResponse({"ok": True, "modo": modo, "dados": dados,
                             "aviso": "Indícios de captura/cartel para apuração interna — não constituem acusação."})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/rodizio")
@router.post("/api/rodizio")  # aceita GET e POST (o Yoda às vezes chuta o método)
async def api_rodizio(ug: Optional[str] = None, top: int = 20, qsa: int = 0):
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
async def api_coendereco_clusters(min_forn: int = 2, top: int = 50):
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
async def api_orgao_cidades(ug: Optional[str] = None, top: int = 20):
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
async def api_painel():
    """Snapshot completo para o painel: stats, OBs do dia, top, alertas, lições."""
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
            ult = s.query(SessaoAuditoria).order_by(desc(SessaoAuditoria.created_at)).first()
            ultima_coleta = (f"{ult.data_sessao} [{ult.tipo}] {ult.status}"
                             if ult else "nenhuma ainda")

            licoes = []
            try:
                from compliance_agent.llm.memoria import lembrar
                licoes = [m["valor"][:200] for m in lembrar("licao", session=s)[:8]]
            except Exception as exc:
                logger.warning("lições da memória indisponíveis p/ a investigação: %s", exc)

            return JSONResponse(content={
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
            })
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
async def api_relatorio_30d():
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
async def api_compliance_alerts(
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
async def api_compliance_stats():
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
async def api_compliance_reports():
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
async def api_compliance_reports_limpar(payload: Optional[dict] = None):
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
async def api_fachada_revisar(limite: int = 50):
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
async def api_fachada_veredito(payload: Optional[dict] = None):
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
async def api_compliance_buscar(q: str = "", tabela: str = "todos"):
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


@router.get("/api/conflito")
async def api_conflito(cnpj: str = "", candidato: str = "", limite: int = 200):
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
                   abertos: bool = False, modalidade: int = 0, dias: int = 30):
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
async def api_empresa(cnpj: str):
    """Onda 12 (providers) — cadastro + sócios (QSA) por CNPJ, fonte hospedada (BrasilAPI→cnpj.pw).
    Sem baixar base: HTTP sob demanda + cache TTL. Resposta com proveniência (fonte+data+estado)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("registry", cnpj=cnpj).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/idoneidade")
async def api_idoneidade(cnpj: str = "", nome: str = ""):
    """Onda 12 (providers) — triagem em listas: CEIS/CNEP (BR) + sanções/PEP (OpenSanctions).
    lookup_all: consulta todos os backends disponíveis. Indício a confirmar, nunca acusação."""
    try:
        from compliance_agent.providers import get_providers
        res = get_providers().lookup_all("sanctions", cnpj=(cnpj or None), nome=(nome or None))
        return JSONResponse(content={"resultados": [r.__dict__ for r in res]})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/ownership")
async def api_ownership(nome: str = "", lei: str = ""):
    """Onda 12 (providers) — controle internacional (LEI + relações) via GLEIF (sem chave)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("ownership", nome=(nome or None), lei=(lei or None)).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/leaks")
async def api_leaks(termo: str):
    """Onda 12 (providers) — busca hospedada em vazamentos offshore (ICIJ; link MANUAL)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("leaks", termo=termo).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/links")
async def api_links(nome: str = "", cnpj: str = ""):
    """Onda 12 (providers) — pistas de investigação HOSPEDADA (Max Intel, OSINT-Brazuca, Bellingcat,
    RedeCNPJ, JusBrasil/Escavador). Deep-links já preenchidos com o alvo; uso MANUAL (o JFN só monta)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("links", nome=(nome or None), cnpj=(cnpj or None)).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/diario")
async def api_diario(querystring: str, territory_ids: str = "", desde: str = "", ate: str = "", size: int = 20):
    """Onda 12 (providers) — diários oficiais municipais (Querido Diário). Busca por palavra-chave +
    território IBGE (RJ capital = 3304557) + janela de datas. Sem chave; on-demand + cache."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("gazettes", querystring=querystring, territory_ids=territory_ids,
                                           desde=desde, ate=ate, size=size).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/doador_contrato")
async def api_doador_contrato(cnpj: str):
    """Onda 12 (providers) — TSE doador×contrato: sócios (QSA) do fornecedor que aparecem como
    doadores de campanha (RJ). Indício de conflito a CONFERIR, nunca acusação (CPF mascarado → casa
    por nome). Requer doacao_tse populado (carregar_doacoes_rj(ano))."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("eleitoral", cnpj=cnpj).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/grafo")
async def api_grafo(alvo: str, saltos: int = 2, so_contrato: bool = False):
    """Onda 4 — Grafo de Poder: vizinhança de um alvo (CNPJ/UG/nome) unindo
    sócios+OB+doações+folha+co-endereço, até `saltos`. so_contrato=true foca o fluxo
    de dinheiro (cnpj↔ug↔sócio). Vínculo = indício de relação, nunca prova."""
    try:
        from compliance_agent.grafo_poder import vizinhanca

        return JSONResponse(content=vizinhanca(alvo, saltos=saltos, so_contrato=so_contrato))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/grafo/ftm")
async def api_grafo_ftm(alvo: str, saltos: int = 2):
    """Onda 12 — Export do Grafo de Poder no modelo FollowTheMoney (interoperar c/ Aleph/Gephi)."""
    try:
        from compliance_agent.grafo_ftm import export
        return JSONResponse(content=export(alvo, saltos=saltos))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


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
async def api_radar_vigiar(payload: Optional[dict] = None):
    """Onda 6 — Radar: adiciona um alvo à watchlist 24/7. Body {"alvo","tipo":cnpj|ug|nome|objeto}.
    Ao surgir edital aberto restritivo / OB anômala do alvo, chega alerta no Telegram."""
    try:
        from compliance_agent.radar import vigiar

        p = payload or {}
        return JSONResponse(content=vigiar(p.get("alvo", ""), p.get("tipo", "cnpj")))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/radar/status")
async def api_radar_status():
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
async def api_restritos(todos: int = 0):
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
async def api_flags():
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
</style></head><body>
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


@router.get("/api/pncp/conluio")
async def api_pncp_conluio(min_certames: int = 4, esfera: str = ""):
    """Conluio a partir dos RESULTADOS estruturados do PNCP (vencedor homologado por item):
    CAPTURA (1 fornecedor domina o órgão) e RODÍZIO DE VENCEDORES (poucos se revezam) — com
    nome de fornecedor, nome de órgão e amostra de OBJETOS. ?esfera=estado|prefeitura filtra por
    natureza do órgão. Indício OCDE a verificar, não acusação."""
    import sqlite3 as _sq
    esf = esfera if esfera in ("estado", "prefeitura", "outros") else None
    ck = f"conluio:{esf or 'todos'}"
    cache = _cache_get(ck, 300)
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
async def api_nomeados_candidatos(limite: int = 200):
    """Cruzamento SERVIDOR/NOMEADO (registros_folha) × CANDIDATO (doacoes_eleitorais/TSE) por nome.
    Servidor público — sobretudo cargo em comissão — que foi candidato a cargo eletivo. Match por
    NOME (verificar homônimo). Indício de relação político-administrativa, não irregularidade."""
    import sqlite3 as _sq
    cache = _cache_get("nomcand", 600)
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
            "ORDER BY f.nome LIMIT ?", (max(10, min(int(limite or 200), 1000)),)).fetchall()
        con.close()
        comissao = [r for r in rows if "comiss" in (r["cargo"] or "").lower()]
        itens = [{"nome": r["nome"], "cargo_folha": r["cargo"], "orgao": r["orgao_nome"],
                  "cargo_disputado": r["cargo_candidato"], "partido": r["partido"],
                  "ano": r["ano_eleicao"],
                  "comissionado": "comiss" in (r["cargo"] or "").lower()} for r in rows]
        out = {"ok": True, "total": len(itens), "n_comissionados": len(comissao), "itens": itens,
               "aviso": "Match por NOME (homônimos possíveis) — indício de relação político-administrativa "
                        "a verificar, não irregularidade. Ser candidato é direito; o foco é conflito de interesse."}
        return JSONResponse(_cache_put("nomcand", out))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/laranjas")
async def api_laranjas(limite: int = 100):
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
            itens.append({"socio": r["socio_nome_norm"], "cpf": r["cpf_resolvido"],
                          "beneficios": bens if isinstance(bens, list) else [str(bens)],
                          "motivo": r["motivo"], "confianca": r["confianca"]})
        out = {"ok": True, "total": len(itens), "itens": itens,
               "aviso": "Indício de laranja/interposição (art. 337-F CP) a verificar — receber benefício "
                        "não é ilícito; o sinal é ser SÓCIO de empresa que recebe do Estado E depender de auxílio."}
        return JSONResponse(out)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pericias")
async def api_pericias(q: str = "", grau: str = "", limite: int = 60, ordem: str = "score"):
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
async def api_perfil(cnpj: str):
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
        con.close()
        return JSONResponse(out)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)
