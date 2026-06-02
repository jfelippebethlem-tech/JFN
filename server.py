"""
SIAFE2 Finance Agent — Web Server

FastAPI server que expõe o agente via chat web.
Acesse do celular usando o IP do seu PC na rede local.

Uso:
    python server.py
    python server.py --port 8080 --visible   # browser visível no PC
    python server.py --host 0.0.0.0          # acessível na rede local (padrão)

No celular: http://<IP-DO-SEU-PC>:8000
"""

import asyncio
import json
import os
import sys
import argparse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


# ── Load .env ─────────────────────────────────────────────────────────────────

def _load_env():
    # Carregador unificado: aceita .env e .env.txt (fallback do Windows).
    try:
        from compliance_agent.envfile import carregar_env
        carregar_env()
        return
    except Exception:
        pass
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path, override=False)
    except ImportError:
        # fallback: lê com utf-8-sig para remover BOM do Windows
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() and key.strip() not in os.environ:
                os.environ[key.strip()] = value.strip()

_load_env()


# ── Global agent instance ─────────────────────────────────────────────────────

_agent = None
_agent_lock = asyncio.Lock()
_otp_queue: Optional[asyncio.Queue] = None  # for passing OTP from web UI to agent


async def get_agent():
    global _agent
    if _agent is None:
        from siafe_agent.agent import SIAFEAgent
        headless = not getattr(_args, "visible", False)
        _agent = SIAFEAgent(
            headless=headless,
            output_dir="output",
            default_username=os.environ.get("SIAFE_USER", ""),
            default_password=os.environ.get("SIAFE_PASS", ""),
            default_cliente=os.environ.get("SIAFE_CLIENTE") or None,
            default_exercicio=os.environ.get("SIAFE_EXERCICIO") or None,
        )
        await _agent.start()
    return _agent


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tenta login no SIAFE — falha silenciosa se fora da rede do governo
    print("\n[Servidor] Iniciando... (login SIAFE só funciona na rede do governo)")
    try:
        agent = await get_agent()
        result = await agent._tool_login_siafe(
            username=agent._siafe_username,
            password=agent._siafe_password,
            cliente=agent._siafe_cliente,
            exercicio=agent._siafe_exercicio,
        )
        if result.get("success"):
            print(f"[SIAFE] Login OK — {result.get('url', '')}")
        else:
            print(f"[SIAFE] Login não realizado (fora da rede do governo) — sistema de compliance funciona normalmente")
    except Exception as e:
        print(f"[SIAFE] Browser não iniciado ({e.__class__.__name__}) — sistema de compliance funciona normalmente")

    yield

    if _agent:
        try:
            await _agent.stop()
        except Exception as e:
            print(f"[SIAFE] Erro no stop do agente ({e.__class__.__name__}): {e}")


app = FastAPI(lifespan=lifespan)

# Serve static files (screenshots, exports)
screenshots_dir = Path("screenshots")
output_dir = Path("output")
screenshots_dir.mkdir(exist_ok=True)
output_dir.mkdir(exist_ok=True)

app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")
app.mount("/output", StaticFiles(directory="output"), name="output")


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the professional compliance dashboard."""
    return FileResponse("static/dashboard.html")


@app.get("/chat", response_class=HTMLResponse)
async def chat_ui():
    """Serve the legacy chat UI."""
    return FileResponse("static/index.html")


@app.get("/hermes", response_class=HTMLResponse)
async def hermes_ui():
    """Serve a interface do Hermes — auditor autônomo guiado por missão."""
    return FileResponse("static/hermes.html")


# ── Hermes Goal Agent (missão autônoma + chat) ────────────────────────────────

@app.get("/api/hermes/estado")
async def api_hermes_estado():
    """Estado do Hermes: missão, Chrome 9222, contagens e aprendizados recentes."""
    from compliance_agent.database.models import get_session, init_db, OrdemBancaria, Alerta
    from compliance_agent.hermes_goal import HermesGoalAgent, chrome_disponivel
    from compliance_agent.llm.free_llm import openrouter_available, groq_available
    from compliance_agent.llm.memoria import lembrar
    init_db()
    s = get_session()
    try:
        ag = HermesGoalAgent(session=s)
        aprendizados = [m["valor"][:140] for m in lembrar("licao", session=s)[:6]]
        return JSONResponse({
            "missao": ag.missao_atual(),
            "chrome_9222": await chrome_disponivel(),
            "llm_ok": bool(openrouter_available() or groq_available()),
            "n_obs": s.query(OrdemBancaria).count(),
            "n_alertas": s.query(Alerta).count(),
            "aprendizados": aprendizados,
        })
    finally:
        s.close()


@app.post("/api/hermes/missao")
async def api_hermes_definir_missao(payload: dict):
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.hermes_goal import HermesGoalAgent, mission_queue
    init_db()
    s = get_session()
    try:
        texto = (payload or {}).get("missao", "").strip()
        if not texto:
            return JSONResponse({"erro": "missão vazia"}, status_code=400)
        HermesGoalAgent(session=s).definir_missao(texto)
        try:
            import asyncio
            asyncio.create_task(mission_queue.enqueue({"tipo": "missao", "texto": texto}))
        except Exception:
            pass
        return JSONResponse({"ok": True, "missao": texto, "queue_size": mission_queue.qsize()})
    finally:
        s.close()


@app.delete("/api/hermes/missao")
async def api_hermes_limpar_missao():
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.hermes_goal import HermesGoalAgent
    init_db()
    s = get_session()
    try:
        HermesGoalAgent(session=s).limpar_missao()
        return JSONResponse({"ok": True})
    finally:
        s.close()


# ── Multi-missão paralela (pool limitado + histórico no banco) ────────────────

@app.post("/api/hermes/missoes")
async def api_hermes_criar_missao(payload: dict):
    """Cria uma missão paralela e dispara a execução em background."""
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.hermes_goal import criar_missao_paralela
    init_db()
    s = get_session()
    try:
        objetivo = (payload or {}).get("objetivo", "").strip()
        if not objetivo:
            return JSONResponse({"erro": "objetivo vazio"}, status_code=400)
        titulo = (payload or {}).get("titulo", "").strip()
        prioridade = (payload or {}).get("prioridade", "media").strip()
        dados = criar_missao_paralela(objetivo, titulo=titulo,
                                      prioridade=prioridade, session=s)
        return JSONResponse({"ok": True, "missao": dados})
    finally:
        s.close()


@app.get("/api/hermes/missoes")
async def api_hermes_listar_missoes():
    """Lista missões (em execução + histórico), mais recentes primeiro."""
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.hermes_goal import listar_missoes, HermesGoalAgent
    init_db()
    s = get_session()
    try:
        return JSONResponse({
            "ok": True,
            "missoes": listar_missoes(session=s),
            "em_execucao": HermesGoalAgent.running_missions(),
        })
    finally:
        s.close()


@app.get("/api/hermes/missoes/{missao_id}")
async def api_hermes_detalhe_missao(missao_id: int):
    """Detalhe de uma missão específica."""
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.hermes_goal import detalhe_missao
    init_db()
    s = get_session()
    try:
        d = detalhe_missao(missao_id, session=s)
        if not d:
            return JSONResponse({"erro": "missão não encontrada"}, status_code=404)
        return JSONResponse({"ok": True, "missao": d})
    finally:
        s.close()


_agent_loop_trabalhar_task: Optional[asyncio.Task] = None
_agent_loop_lock = asyncio.Lock()
_agent_loop_queue: Optional[asyncio.Queue] = None  # SSE stream


async def _trabalhar_loop_until_done(ag: "HermesGoalAgent"):
    loop_fim = asyncio.Event()
    n_passos = 0
    ultimo_aprendizado = ""
    while not loop_fim.is_set():
        ciclo = await ag.trabalhar()
        n_passos += len(ciclo.get("passos", []))
        for item in ciclo.get("passos", []):
            payload = {
                "acao": item.get("acao"),
                "pensamento": item.get("pensamento"),
                "resultado": item.get("resultado"),
            }
            if _agent_loop_queue:
                await _agent_loop_queue.put(payload)
        if ciclo.get("resumo"):
            ultimo_aprendizado = str(ciclo.get("resumo"))
        if ciclo.get("concluido") or ciclo.get("erro"):
            break
        await asyncio.sleep(1)
    if _agent_loop_queue:
        await _agent_loop_queue.put({
            "acao": "concluir",
            "pensamento": "Ciclo autônomo finalizado",
            "resultado": {"resumo": ultimo_aprendizado or "Missão processada."},
        })


async def _cancelar_loop_trabalhar():
    global _agent_loop_trabalhar_task
    async with _agent_loop_lock:
        if _agent_loop_trabalhar_task and not _agent_loop_trabalhar_task.done():
            _agent_loop_trabalhar_task.cancel()
            try:
                await _agent_loop_trabalhar_task
            except asyncio.CancelledError:
                pass
            _agent_loop_trabalhar_task = None


@app.post("/api/hermes/trabalhar")
async def api_hermes_trabalhar():
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.hermes_goal import HermesGoalAgent
    init_db()
    s = get_session()
    try:
        ag = HermesGoalAgent(session=s)
        if not ag.missao_atual():
            return JSONResponse({"erro": "Defina uma missão antes de trabalhar."})
        await _cancelar_loop_trabalhar()
        _agent_loop_queue = asyncio.Queue()
        loop_task = asyncio.create_task(_trabalhar_loop_until_done(ag))
        _agent_loop_trabalhar_task = loop_task
        return JSONResponse({"ok": True, "status": "trabalhando"})
    except Exception as e:
        return JSONResponse({"erro": f"{type(e).__name__}: {e}"})
    finally:
        s.close()


@app.get("/api/hermes/stream")
async def api_hermes_stream():
    async def event_stream():
        while True:
            if _agent_loop_queue is None:
                await asyncio.sleep(0.25)
                continue
            try:
                item = await _agent_loop_queue.get()
            except asyncio.CancelledError:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/hermes/parar")
async def api_hermes_parar():


    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.hermes_goal import HermesGoalAgent
    init_db()
    s = get_session()
    try:
        pergunta = (payload or {}).get("pergunta", "").strip()
        if not pergunta:
            return JSONResponse({"erro": "pergunta vazia"}, status_code=400)
        resposta = await HermesGoalAgent(session=s).conversar(pergunta)
        return JSONResponse({"resposta": resposta})
    except Exception as e:
        return JSONResponse({"erro": f"{type(e).__name__}: {e}"})
    finally:
        s.close()


@app.post("/api/hermes/relatorio")
async def api_hermes_relatorio(payload: Optional[dict] = None):
    from compliance_agent.reporting.export_relatorios import generate_report
    fmt = ((payload or {}).get("formato") or "txt").strip().lower()
    result = generate_report(fmt=fmt)
    return JSONResponse(result)


@app.get("/api/compliance/painel")
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
            except Exception:
                pass

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


@app.get("/api/compliance/investigar")
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


@app.get("/graph", response_class=HTMLResponse)
async def graph_page():
    """Serve the D3.js graph visualization page."""
    return FileResponse("static/graph.html")


@app.get("/api/compliance/relatorio_30d")
async def api_relatorio_30d():
    """Gera relatório estruturado das OBs dos últimos 30 dias em Markdown."""
    try:
        import sqlalchemy as sa
        from datetime import date, timedelta
        from pathlib import Path
        from compliance_agent.database.models import (
            get_session, init_db, OrdemBancaria, Alerta,
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


@app.get("/api/compliance/graph")
async def api_compliance_graph():
    """
    Return graph data from GrafoRelacionamentos.exportar_json().
    Initializes compliance DB and builds the relationship graph.
    """
    try:
        from compliance_agent.database.models import get_session, init_db
        from compliance_agent.graph import GrafoRelacionamentos

        init_db()
        session = get_session()
        grafo = GrafoRelacionamentos(session)
        grafo.construir()
        data = grafo.exportar_json()
        session.close()
        return JSONResponse(content=data)
    except Exception as e:
        return JSONResponse(content={"nodes": [], "links": [], "error": str(e)})


@app.get("/api/compliance/alerts")
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
    import json as _json
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


@app.get("/api/compliance/stats")
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


@app.get("/api/compliance/reports")
async def api_compliance_reports():
    """List PDF and JSON report files in the reports/ directory."""
    try:
        reports_dir = Path("reports")
        if not reports_dir.exists():
            return JSONResponse(content=[])
        files = []
        for f in sorted(reports_dir.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True):
            files.append({"name": f.name, "type": "pdf", "size": f.stat().st_size, "url": f"/reports/{f.name}"})
        for f in sorted(reports_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            files.append({"name": f.name, "type": "json", "size": f.stat().st_size, "url": f"/reports/{f.name}"})
        return JSONResponse(content=files)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/reports/{filename}")
async def serve_report(filename: str):
    """Serve a report file (PDF or JSON) from the reports/ directory."""
    reports_dir = Path("reports")
    file_path = reports_dir / filename
    # Security: prevent path traversal
    if not file_path.resolve().is_relative_to(reports_dir.resolve()):
        return JSONResponse(content={"error": "Access denied"}, status_code=403)
    if not file_path.exists():
        return JSONResponse(content={"error": "File not found"}, status_code=404)
    return FileResponse(str(file_path))


@app.post("/api/compliance/tse/{ano}")
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


@app.get("/api/compliance/buscar")
async def api_compliance_buscar(q: str = "", tabela: str = "todos"):
    """
    FTS5 full-text search across contracts, DOERJ, and alerts.

    Query params:
        q:      Search term.
        tabela: contratos | doerj | alertas | todos (default: todos).
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
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/status")
async def status():
    """Check agent status."""
    agent = await get_agent()
    return {
        "logged_in": agent._siafe._logged_in,
        "username": agent._siafe_username,
        "exercicio": agent._siafe_exercicio or str(__import__('datetime').date.today().year),
        "extracted_records": len(agent._extracted_data),
    }


@app.get("/screenshots")
async def list_screenshots():
    """List available screenshots."""
    files = sorted(Path("screenshots").glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [f.name for f in files[:20]]


@app.get("/exports")
async def list_exports():
    """List exported files."""
    files = sorted(Path("output").glob("*"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [{"name": f.name, "size": f.stat().st_size} for f in files[:20]]


# ── OTP endpoint (called by the web UI when user submits the email code) ──────

_otp_futures: dict[str, asyncio.Future] = {}


@app.post("/otp")
async def submit_otp(payload: dict):
    """Receive OTP code from user and deliver it to the waiting login flow."""
    code = payload.get("code", "").strip()
    # Signal all waiting OTP futures
    for fut in list(_otp_futures.values()):
        if not fut.done():
            fut.set_result(code)
    return {"ok": True}


# ── WebSocket chat ────────────────────────────────────────────────────────────

class StreamingCallbacks:
    """Bridges agent tool execution events to WebSocket messages."""

    def __init__(self, ws: WebSocket):
        self.ws = ws

    async def send(self, msg_type: str, content: str):
        try:
            await self.ws.send_text(json.dumps({"type": msg_type, "content": content}))
        except Exception:
            pass


@app.websocket("/ws")
async def websocket_chat(ws: WebSocket):
    await ws.accept()

    async def otp_callback():
        """Called by the agent when it needs the email OTP code."""
        await ws.send_text(json.dumps({
            "type": "otp_request",
            "content": "Digite o código recebido por e-mail:",
        }))
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        _otp_futures["pending"] = fut
        try:
            code = await asyncio.wait_for(fut, timeout=120)
        except asyncio.TimeoutError:
            code = ""
        _otp_futures.pop("pending", None)
        return code

    try:
        agent = await get_agent()
        # Inject web OTP callback
        agent._siafe._web_otp_callback = otp_callback

        async with _agent_lock:
            # Inject web OTP callback into the browser so that if 2FA is triggered
            # during login the code goes through the WebSocket instead of stdin.
            # The stored credentials (_siafe_username / _siafe_password) are used as-is.
            agent._siafe._web_otp_callback = otp_callback

            while True:
                try:
                    data = await ws.receive_text()
                except WebSocketDisconnect:
                    break

                msg = json.loads(data)

                if msg.get("type") == "otp":
                    # OTP submitted via WebSocket (alternative to POST /otp)
                    code = msg.get("code", "")
                    for fut in list(_otp_futures.values()):
                        if not fut.done():
                            fut.set_result(code)
                    continue

                if msg.get("type") != "message":
                    continue

                user_text = msg.get("content", "").strip()
                if not user_text:
                    continue

                await ws.send_text(json.dumps({"type": "thinking"}))

                try:
                    # Monkey-patch tool execution to stream progress
                    original_execute = agent._execute_tool

                    async def streaming_execute(name, inputs):
                        safe_inputs = inputs if isinstance(inputs, dict) else {}
                        await ws.send_text(json.dumps({
                            "type": "tool_call",
                            "content": f"→ {name}({', '.join(f'{k}={v!r}' for k, v in safe_inputs.items())})",
                        }))
                        result = await original_execute(name, inputs)
                        # If a screenshot was taken, send its path
                        if isinstance(result, dict) and "path" in result:
                            await ws.send_text(json.dumps({
                                "type": "screenshot",
                                "content": result["path"],
                            }))
                        return result

                    agent._execute_tool = streaming_execute

                    response = await agent.chat(user_text)

                    agent._execute_tool = original_execute
                except Exception as e:
                    response = f"Erro interno: {e}"

                await ws.send_text(json.dumps({"type": "response", "content": response}))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_text(json.dumps({"type": "error", "content": str(e)}))
        except Exception:
            pass


def parse_args():
    parser = argparse.ArgumentParser(description="SIAFE2 Finance Agent — Servidor Web")
    parser.add_argument("--host", default="0.0.0.0", help="Host (padrão: 0.0.0.0 = acessível na rede)")
    parser.add_argument("--port", type=int, default=8000, help="Porta (padrão: 8000)")
    parser.add_argument("--visible", action="store_true", help="Browser visível no PC")
    return parser.parse_args()


def main():
    global _args
    _args = parse_args()

    # Print access info
    import socket
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "SEU-IP"

    print(f"""
╔══════════════════════════════════════════════════════╗
║         SIAFE2 Finance Agent — Servidor Web          ║
╠══════════════════════════════════════════════════════╣
║  PC (local):   http://localhost:{_args.port}               ║
║  Celular:      http://{local_ip}:{_args.port}         ║
║                                                      ║
║  Abra o link acima no browser do seu celular.        ║
║  Certifique-se que o celular está no mesmo WiFi.     ║
╚══════════════════════════════════════════════════════╝
""")

    uvicorn.run(
        app,
        host=_args.host,
        port=_args.port,
        reload=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
