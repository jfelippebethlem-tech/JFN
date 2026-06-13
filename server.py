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
import time
import argparse
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # só p/ anotações (o import real é lazy dentro das rotas) — resolve F821
    from compliance_agent.hermes_goal import HermesGoalAgent

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
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

# ── Guard de idle do browser (§6: evitar o leak de Chromium ocioso 24h) ────────
# O browser Playwright (SIAFE/SEI) é um singleton lançado no boot e reusado. Se ficar OCIOSO por muito tempo
# ele segura ~200MB numa VM sem swap à toa. O reaper abaixo o ENCERRA após N min sem uso e o `get_agent()`
# relança LAZY na próxima leitura. Seguro: as operações que dirigem o browser seguram `_agent_lock`; o reaper
# só fecha quando o lock está livre (e re-checa o ócio após adquiri-lo). Configurável por env
# `JFN_BROWSER_IDLE_MIN` (default 15; 0 = desliga o guard). Usa relógio monotônico (imune a ajuste de hora).
_browser_last_used: float = time.monotonic()
try:
    _BROWSER_IDLE_MIN = float(os.environ.get("JFN_BROWSER_IDLE_MIN", "15"))
except (TypeError, ValueError):
    _BROWSER_IDLE_MIN = 15.0
_BROWSER_REAP_INTERVAL = 120.0  # de quanto em quanto tempo o reaper checa o ócio (segundos)
_browser_reaper_task: Optional["asyncio.Task"] = None

# ── Reverse tunnel state ──────────────────────────────────────────────────────
_tunnel_ws: Optional["WebSocket"] = None          # Windows tunnel connection
_tunnel_lock = asyncio.Lock()
_tunnel_collect_event = asyncio.Event()           # signals a collect request
_tunnel_collect_args: dict = {}                   # {"anos": [...]}
_tunnel_results: list = []                        # accumulated OBs from Windows


async def get_agent():
    global _agent, _browser_last_used
    _browser_last_used = time.monotonic()  # marca uso p/ o guard de idle (toda requisição do browser passa aqui)
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
        # Login SIAFE best-effort em TODO launch fresco (boot OU relaunch após idle-reap) — gov-network only,
        # silencioso fora da rede; o SEI faz seu próprio login por operação. Mantém o boot e o relaunch idênticos.
        try:
            res = await _agent._tool_login_siafe(
                username=_agent._siafe_username, password=_agent._siafe_password,
                cliente=_agent._siafe_cliente, exercicio=_agent._siafe_exercicio,
            )
            if res.get("success"):
                print(f"[SIAFE] Login OK — {res.get('url', '')}")
            else:
                print("[SIAFE] Login não realizado (fora da rede do governo) — compliance funciona normalmente")
        except Exception as e:  # noqa: BLE001 — login é best-effort; browser sobe mesmo sem ele
            print(f"[SIAFE] Browser sem login ({e.__class__.__name__}) — compliance funciona normalmente")
    return _agent


async def _browser_idle_reaper():
    """Encerra o browser Playwright após `_BROWSER_IDLE_MIN` minutos SEM uso, liberando RAM numa VM sem swap.
    Relança LAZY no próximo `get_agent()`. Seguro contra fechar no meio de uma operação: só fecha quando
    `_agent_lock` está livre e, após adquiri-lo, re-confirma o ócio (operações de browser seguram esse lock)."""
    global _agent
    if _BROWSER_IDLE_MIN <= 0:
        return  # guard desligado por configuração
    while True:
        try:
            await asyncio.sleep(_BROWSER_REAP_INTERVAL)
            # NB: o Chrome 9222 NÃO é gerido aqui — é o `chrome-jfn.service` (systemd, Restart=always), ponte CDP
            # PERSISTENTE p/ coleta TFE/SIAFE ao vivo. Fechá-lo aqui brigaria com o systemd (churn + StartLimit).
            # Este reaper cuida só do browser Playwright on-demand do server.py (SIAFE via get_agent).
            if _agent is None:
                continue
            ocioso_s = time.monotonic() - _browser_last_used
            if ocioso_s < _BROWSER_IDLE_MIN * 60:
                continue
            if _agent_lock.locked():
                continue  # operação em andamento — não mexer; checa de novo no próximo ciclo
            async with _agent_lock:
                # re-checa sob o lock (evita corrida com um get_agent que acabou de marcar uso)
                if _agent is None or (time.monotonic() - _browser_last_used) < _BROWSER_IDLE_MIN * 60:
                    continue
                ag, _agent = _agent, None  # solta o singleton ANTES de fechar; próximo get_agent relança limpo
                try:
                    await ag.stop()
                    print(f"[browser] ocioso {ocioso_s/60:.0f}min — Chromium encerrado p/ liberar RAM "
                          f"(relança na próxima leitura SEI/SIAFE)", flush=True)
                except Exception as e:  # noqa: BLE001 — fechar é best-effort; nunca derruba o servidor
                    print(f"[browser] erro ao encerrar browser ocioso ({e.__class__.__name__}) — ignorado")
        except asyncio.CancelledError:
            raise  # shutdown: deixa propagar
        except Exception as e:  # noqa: BLE001 — o reaper NUNCA pode morrer por uma exceção pontual
            print(f"[browser] reaper: ciclo falhou ({e.__class__.__name__}) — continua")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tenta login no SIAFE — falha silenciosa se fora da rede do governo
    print("\n[Servidor] Iniciando... (login SIAFE só funciona na rede do governo)")
    try:
        await get_agent()  # lança o browser + login SIAFE best-effort (lógica única em get_agent)
    except Exception as e:
        print(f"[SIAFE] Browser não iniciado ({e.__class__.__name__}) — sistema de compliance funciona normalmente")

    # WARMUP do motor de relatório (contorna o "cold start": 1º relatório após boot levava ~78s por DNS/TLS
    # frios às fontes externas). Aquece em background ~6s após subir, sem atrasar o startup nem o usuário.
    async def _warmup_relatorio():
        try:
            await asyncio.sleep(6)
            from compliance_agent.reporting.inteligencia import _enriquecer
            await _enriquecer("19088605000104")  # MGS — prima DNS/TLS/pools de conexão (Receita/PNCP/sanções)
            print("[warmup] motor de relatório aquecido (fontes externas primadas)")
        except Exception as exc:  # noqa: BLE001
            print(f"[warmup] aquecimento falhou (não-fatal): {exc.__class__.__name__}")
    try:
        asyncio.create_task(_warmup_relatorio())
    except Exception:
        pass

    # Guard de idle: encerra o Chromium ocioso após N min (§6, evita o leak de browser 24h numa VM sem swap).
    global _browser_reaper_task
    if _BROWSER_IDLE_MIN > 0:
        try:
            _browser_reaper_task = asyncio.create_task(_browser_idle_reaper())
            print(f"[browser] guard de idle ativo: encerra o Chromium após {_BROWSER_IDLE_MIN:.0f}min sem uso "
                  f"(relança lazy; env JFN_BROWSER_IDLE_MIN, 0=off)", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[browser] guard de idle não iniciado ({e.__class__.__name__}) — não-fatal")

    yield

    if _browser_reaper_task:
        _browser_reaper_task.cancel()
        try:
            await _browser_reaper_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 — shutdown, best-effort
            pass

    if _agent:
        try:
            await _agent.stop()
        except Exception as e:
            print(f"[SIAFE] Erro no stop do agente ({e.__class__.__name__}): {e}")


app = FastAPI(lifespan=lifespan)

# JFN 2.0 Onda 0 — observabilidade: correlation-id por request + GET /api/trace/{id} (aditivo, best-effort)
try:
    from compliance_agent.obs_trace import register_trace
    register_trace(app)
except Exception as _e:  # nunca impedir o boot do servidor por causa do trace
    print(f"[obs_trace] não registrado: {_e}", flush=True)

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
@app.post("/api/hermes/parar")
async def api_hermes_parar(payload: Optional[dict] = None):
    """Para o ciclo 'trabalhar agora' em andamento."""
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.hermes_goal import HermesGoalAgent, mission_queue
    init_db()
    s = get_session()
    try:
        await _cancelar_loop_trabalhar()
        try:
            for _ in range(min(20, mission_queue.qsize())):
                try:
                    mission_queue.dequeue_nowait()
                except Exception:
                    break
            while not mission_queue.empty():
                mission_queue.dequeue_nowait()
        except Exception:
            pass
        HermesGoalAgent(session=s).limpar_missao()
        return JSONResponse({"ok": True, "status": "parado"})
    except Exception as e:
        return JSONResponse({"erro": f"{type(e).__name__}: {e}"}, status_code=500)
    finally:
        s.close()


@app.post("/api/hermes/chat")
async def api_hermes_chat(payload: dict):
    """Conversa com o Hermes (raciocínio profundo sobre os casos)."""


# ── Auditor 24 horas (auditoria automática e ininterrupta) ────────────────────

@app.post("/api/hermes/auditor24h/iniciar")
async def api_auditor24h_iniciar(payload: Optional[dict] = None):
    """Liga o modo Auditor 24 horas (botão da interface)."""
    from compliance_agent.hermes_goal import iniciar_auditor_24h
    objetivo = ((payload or {}).get("objetivo") or "").strip()
    intervalo = (payload or {}).get("intervalo_seg")
    try:
        intervalo = int(intervalo) if intervalo else None
    except (TypeError, ValueError):
        intervalo = None
    try:
        return JSONResponse(iniciar_auditor_24h(objetivo=objetivo, intervalo_seg=intervalo))
    except Exception as e:
        return JSONResponse({"ok": False, "erro": f"{type(e).__name__}: {e}"})


@app.post("/api/hermes/auditor24h/parar")
async def api_auditor24h_parar():
    """Desliga o modo Auditor 24 horas."""
    from compliance_agent.hermes_goal import parar_auditor_24h
    try:
        return JSONResponse(parar_auditor_24h())
    except Exception as e:
        return JSONResponse({"ok": False, "erro": f"{type(e).__name__}: {e}"})


@app.get("/api/hermes/auditor24h/status")
async def api_auditor24h_status():
    """Estado atual do Auditor 24 horas (ciclos, último resumo, etc.)."""
    from compliance_agent.hermes_goal import status_auditor_24h
    try:
        return JSONResponse(status_auditor_24h())
    except Exception as e:
        return JSONResponse({"ativo": False, "erro": f"{type(e).__name__}: {e}"})


@app.post("/api/hermes/relatorio")
async def api_hermes_relatorio(payload: Optional[dict] = None):
    from compliance_agent.reporting.export_relatorios import generate_report
    fmt = ((payload or {}).get("formato") or "txt").strip().lower()
    result = generate_report(fmt=fmt)
    return JSONResponse(result)


# ── Relatórios ASSÍNCRONOS: respondem rápido e o JFN EMPURRA os documentos ao Telegram ──
# Motivo: a ferramenta `terminal` do Yoda mata o curl em ~60s, mas o relatório leva 1–3 min
# (PNCP/Playwright + contenção dos sweeps) — o Yoda nunca recebia os caminhos. Agora o /relatorio
# devolve {status:"gerando"} na hora e o JFN envia o PDF+XLSX+Lex direto no chat quando ficam prontos.
_REL_EM_CURSO: set = set()

# Relatório do Mestre Jorge tem PRIORIDADE sobre os sweeps: 3 Chromium/Playwright concorrentes
# (2 sweeps + relatório) travavam a geração por contenção. Ao gerar, pausamos os sweeps (flags que os
# supervisores honram → não relançam) e matamos os em curso; quando não há mais relatório, retomamos.
_SWEEP_PAUSE_FLAGS = ("data/.pause_sweep_2", "data/.pause_sweep_1", "data/.pause_sei_sweep")


def _pausar_sweeps_para_relatorio() -> None:
    import subprocess
    try:
        for f in _SWEEP_PAUSE_FLAGS:
            Path(f).touch()
        # colchete no padrão evita casar o próprio comando (lição do auto-pkill); mata por padrão seguro
        subprocess.run(["pkill", "-f", "tools[.]sei_sweep"], check=False)
        subprocess.run(["pkill", "-f", "siafe[_]sweep_full"], check=False)
    except Exception:  # noqa: BLE001
        pass


def _retomar_sweeps_se_ocioso() -> None:
    if _REL_EM_CURSO:  # ainda há relatório gerando → mantém pausado
        return
    try:
        for f in _SWEEP_PAUSE_FLAGS:
            Path(f).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


async def _enviar_docs_telegram(result: dict, titulo: str) -> None:
    from compliance_agent.notifications import telegram as _tg
    # PDF primeiro (recebe a caption), depois MD (fonte legível/grep-ável p/ o Yoda), xlsx e parecer Lex.
    # path_md incluído p/ o Yoda mandar MD+PDF (antes só PDF/xlsx/lex iam — o MD ficava de fora).
    paths = [p for p in (result.get("path_pdf"), result.get("path_md"),
                         result.get("path_xlsx"), result.get("path_lex")) if p]
    if not paths:
        await _tg.enviar_mensagem(f"⚠️ {titulo}: gerado, mas sem arquivos para enviar.")
        return
    cap = (f"📄 {titulo}\n{result.get('resumo') or ''}")[:1024]
    for i, p in enumerate(paths):
        await _tg.enviar_arquivo(p, caption=(cap if i == 0 else ""))


async def _gerar_e_enviar_fornecedor(cnpj, empresa, anos, key) -> None:
    from compliance_agent.notifications import telegram as _tg
    from compliance_agent.reporting.inteligencia import montar
    _pausar_sweeps_para_relatorio()
    try:
        result = await montar(cnpj=cnpj, empresa=empresa, anos=anos)
        if not result.get("ok"):
            await _tg.enviar_mensagem(result.get("pergunta") if result.get("ambiguo")
                                      else f"⚠️ Não consegui gerar o relatório: {(result.get('erro') or '')[:300]}")
            return
        await _enviar_docs_telegram(result, f"Relatório de inteligência — {result.get('empresa') or empresa or cnpj}")
    except Exception as exc:  # noqa: BLE001
        await _tg.enviar_mensagem(f"⚠️ Erro ao gerar o relatório de {empresa or cnpj}: {str(exc)[:300]}")
    finally:
        _REL_EM_CURSO.discard(key)
        _retomar_sweeps_se_ocioso()


async def _gerar_e_enviar_orgao(orgao, ug, anos, key) -> None:
    from compliance_agent.notifications import telegram as _tg
    from compliance_agent.reporting.inteligencia_orgao import montar as montar_orgao
    _pausar_sweeps_para_relatorio()
    try:
        result = await asyncio.to_thread(montar_orgao, orgao=orgao, ug=ug, anos=anos)
        if not result.get("ok"):
            await _tg.enviar_mensagem(result.get("pergunta") if result.get("ambiguo")
                                      else f"⚠️ Não consegui gerar o relatório do órgão: {(result.get('erro') or '')[:300]}")
            return
        await _enviar_docs_telegram(result, f"Relatório de órgão — {result.get('orgao') or orgao or ug}")
    except Exception as exc:  # noqa: BLE001
        await _tg.enviar_mensagem(f"⚠️ Erro ao gerar o relatório do órgão {orgao or ug}: {str(exc)[:300]}")
    finally:
        _REL_EM_CURSO.discard(key)
        _retomar_sweeps_se_ocioso()


async def _gerar_e_enviar_dossie(alvo, key) -> None:
    from compliance_agent.dossie import dossie
    from compliance_agent.notifications import telegram as _tg
    _pausar_sweeps_para_relatorio()
    try:
        result = await dossie(alvo)
        if not result.get("ok"):
            await _tg.enviar_mensagem(result.get("pergunta") if result.get("ambiguo")
                                      else f"⚠️ Não consegui gerar o dossiê: {(result.get('erro') or '')[:300]}")
            return
        # O dossiê só tem path_pdf (sem xlsx/lex) — _enviar_docs_telegram envia o que houver.
        await _enviar_docs_telegram(result, f"Dossiê 360 — {alvo}")
    except Exception as exc:  # noqa: BLE001
        await _tg.enviar_mensagem(f"⚠️ Erro ao gerar o dossiê de {alvo}: {str(exc)[:300]}")
    finally:
        _REL_EM_CURSO.discard(key)
        _retomar_sweeps_se_ocioso()


@app.post("/api/relatorio/inteligencia")
async def api_relatorio_inteligencia(payload: Optional[dict] = None):
    """
    Relatório de INTELIGÊNCIA de fornecedor (motor do comando /relatorio do Yoda).
    Body JSON: {"empresa": "NOME"} OU {"cnpj": "..."} (parcial serve no nome), opcional {"anos": [2025,2026]}.
    Retorna {ok, cnpj, empresa, risco, score, resumo, path_md, path_pdf, fonte}.
    Se o nome for ambíguo, retorna {ok:false, ambiguo:true, pergunta, candidatos:[...]} para o Yoda
    repassar a dúvida ao Mestre Jorge.
    """
    from compliance_agent.reporting.inteligencia import montar
    payload = payload or {}
    cnpj = (payload.get("cnpj") or "").strip() or None
    empresa = (payload.get("empresa") or payload.get("nome") or "").strip() or None
    anos = payload.get("anos") or None
    if anos:
        try:
            anos = [int(a) for a in anos]
        except (TypeError, ValueError):
            anos = None
    if not cnpj and not empresa:
        return JSONResponse({"ok": False, "erro": "Informe 'empresa' (nome, parcial serve) ou 'cnpj'."},
                            status_code=400)
    # Geração ASSÍNCRONA: responde já e o JFN empurra os documentos quando prontos (ver helpers acima).
    if payload.get("sync"):  # modo síncrono ainda disponível (CLI/testes): {"sync": true}
        try:
            result = await montar(cnpj=cnpj, empresa=empresa, anos=anos)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "erro": f"Falha ao gerar relatório: {exc}"}, status_code=500)
        return JSONResponse(result)
    # Pré-check de ambiguidade SÍNCRONO (resolução é rápida; só a geração é lenta) → o Yoda trata a
    # dúvida normalmente (a resposta numérica do Mestre Jorge roteia certo), em vez de o JFN empurrar a
    # pergunta sem o Yoda saber. Erro/ambíguo voltam na hora; só o caso resolvido vai p/ background.
    try:
        pre = await montar(cnpj=cnpj, empresa=empresa, so_resolver=True)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": f"Falha ao resolver: {exc}"}, status_code=500)
    if not pre.get("ok") or pre.get("ambiguo"):
        return JSONResponse(pre)
    key = f"forn:{(cnpj or empresa or '').lower()}"
    if key in _REL_EM_CURSO:
        return JSONResponse({"ok": True, "status": "gerando",
                             "msg": "⏳ Já estou preparando esse relatório — te envio aqui em instantes."})
    _REL_EM_CURSO.add(key)
    asyncio.create_task(_gerar_e_enviar_fornecedor(cnpj, empresa, anos, key))
    return JSONResponse({"ok": True, "status": "gerando",
                         "msg": f"📥 Preparando o relatório de *{empresa or cnpj}* (PDF + planilha + parecer Lex). "
                                "Eu te envio aqui mesmo em ~1–2 min — não precisa repetir o comando."})


@app.post("/api/relatorio/orgao")
async def api_relatorio_orgao(payload: Optional[dict] = None):
    """
    Relatório de inteligência de ÓRGÃO (UG): quanto a unidade gestora pagou, a quem, por ano.
    Body: {"orgao":"NOME ou parcial"} OU {"ug":"133100"}, opcional {"anos":[2025,2026]}.
    Retorna {ok, ug, orgao, resumo, path_md, path_pdf, path_xlsx, path_lex, grau_lex, fonte}
    ou {ambiguo, pergunta, candidatos}. O path_lex é o PARECER LEX de órgão (grau 🟢🟡🔴).
    """
    from compliance_agent.reporting.inteligencia_orgao import montar as montar_orgao
    payload = payload or {}
    ug = (payload.get("ug") or "").strip() or None
    orgao = (payload.get("orgao") or payload.get("nome") or "").strip() or None
    anos = payload.get("anos") or None
    if anos:
        try:
            anos = [int(a) for a in anos]
        except (TypeError, ValueError):
            anos = None
    if not ug and not orgao:
        return JSONResponse({"ok": False, "erro": "Informe 'orgao' (nome, parcial serve) ou 'ug' (código)."},
                            status_code=400)
    if payload.get("sync"):  # modo síncrono (CLI/testes)
        try:
            result = montar_orgao(orgao=orgao, ug=ug, anos=anos)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "erro": f"Falha ao gerar relatório: {exc}"}, status_code=500)
        return JSONResponse(result)
    # Pré-check de ambiguidade SÍNCRONO (Yoda trata a dúvida/numérico); só o resolvido vai p/ background.
    try:
        pre = montar_orgao(orgao=orgao, ug=ug, so_resolver=True)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": f"Falha ao resolver: {exc}"}, status_code=500)
    if not pre.get("ok") or pre.get("ambiguo"):
        return JSONResponse(pre)
    key = f"orgao:{(ug or orgao or '').lower()}"
    if key in _REL_EM_CURSO:
        return JSONResponse({"ok": True, "status": "gerando",
                             "msg": "⏳ Já estou preparando esse relatório de órgão — te envio aqui em instantes."})
    _REL_EM_CURSO.add(key)
    asyncio.create_task(_gerar_e_enviar_orgao(orgao, ug, anos, key))
    return JSONResponse({"ok": True, "status": "gerando",
                         "msg": f"📥 Preparando o relatório do órgão *{orgao or ug}* (PDF + planilha + parecer Lex). "
                                "Eu te envio aqui mesmo em ~1–2 min — não precisa repetir o comando."})


# ── MASSARE (mercado/predição) — exposto no barramento para o Yoda ────────────

@app.get("/api/massare/focus")
async def api_massare_focus(ano: str = ""):
    """Onda 8 — Boletim Focus (BCB/Olinda): Selic/IPCA/PIB/câmbio (mediana), sem chave."""
    try:
        from massare.focus import boletim
        return JSONResponse(content=boletim(ano or None))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/massare/calendario")
async def api_massare_calendario(dias: int = 7):
    """Onda 8 — Agenda macro (CPI/NFP/FOMC/COPOM/PMI China) via Finnhub (chave grátis)."""
    try:
        from massare.calendar import agenda
        return JSONResponse(content=agenda(dias))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/massare/fundamentos")
async def api_massare_fundamentos(ticker: str):
    """Onda 8 — Fundamentos de ação BR (P/L, DY, ROE) via brapi.dev."""
    try:
        from massare.fundamentos import fundamentos
        return JSONResponse(content=fundamentos(ticker))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/massare/noticias")
async def api_massare_noticias(tema: str = "", janela: str = "2d"):
    """Onda 8 — Notícias/narrativas de mercado (GDELT, sem chave). Sem tema = boletim multi-tema."""
    try:
        from massare import news
        return JSONResponse(content=news.coletar(tema, janela) if tema else news.boletim_temas(janela=janela))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/massare/teses")
async def api_massare_teses(registrar: bool = True):
    """Onda 9 — Teses de mercado: narrativa→ativos→direção, registradas como previsão (OOS)."""
    try:
        from massare.theses import atual
        return JSONResponse(content=atual(registrar=registrar))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/massare/carteira")
async def api_massare_carteira():
    """Onda 9 — Carteira manual (data/carteira.json) valorizada + cruzada com teses. Sem broker."""
    try:
        from massare.carteira import carteira
        return JSONResponse(content=carteira())
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/massare/regime")
async def api_massare_regime(symbol: str = "^GSPC"):
    """Regime de mercado (clima) via HMM gaussiano sobre (retorno, vol): calmo-alta (bull) / calmo-baixa
    (bear) / estresse-alta-vol. Não prevê preço — classifica o ambiente p/ condicionar a leitura.
    Aceita NOME amigável (ibovespa, bitcoin, ouro…). Honesto: estados latentes, não certeza."""
    try:
        from massare import ml, market, store
        store.init_db()
        sym = market.resolver_symbol((symbol or "^GSPC").strip())
        try:
            market._refresh_precos([sym])
        except Exception:  # noqa: BLE001
            pass
        return JSONResponse(content={"ok": True, "symbol": sym, "regime": ml.regime_hmm(sym)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/massare/placar")
async def api_massare_placar():
    """Acurácia out-of-sample acumulada + sentimento de mercado (Fear&Greed/VIX)."""
    try:
        from massare import learning, behavior, store, backtest
        store.init_db()
        # HONESTIDADE: o diário de previsões logadas costuma estar pendente (alvo no futuro).
        # O backtest OOS (walk-forward em TODOS os pregões) é o track record honesto: hit-rate
        # vs. piso ingênuo (taxa-base) e o EDGE real. None se o backtest ainda não rodou.
        return JSONResponse({"ok": True, "placar": learning.scoreboard(),
                             "backtest_oos": backtest.resumo_overall(),
                             "sentimento": behavior.snapshot()})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@app.get("/api/massare/cenarios")
async def api_massare_cenarios(recalcular: bool = False):
    """
    Último snapshot multi-horizonte do pregão (curtíssimo/curto/médio/longo).
    Por padrão lê o snapshot salvo pelo `massare-market.timer` (rápido). `?recalcular=true` recomputa na hora.
    """
    try:
        from massare import market
        snap = market.cenarios() if recalcular else (market.ler_snapshot() or market.cenarios())
        return JSONResponse({"ok": True, "snapshot": snap, "briefing": market.briefing(snap)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@app.get("/api/briefing/dados")
async def api_briefing_dados():
    """Dados confiáveis para a rotina BOM DIA: clima (Open-Meteo) + mercado (Massare) + notícias (Google News
    RSS). O Yoda chama isto em vez de raspar HTML frágil (climatempo/g1/infomoney, que falhavam)."""
    try:
        from compliance_agent.briefing import dados
        return JSONResponse(dados())
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@app.get("/api/siafe/stats")
async def api_siafe_stats():
    """Resumo das OBs do SIAFE (tela OB Orçamentária) já coletadas/ingeridas na base (SIAFE preponderante)."""
    try:
        import sqlite3
        from pathlib import Path as _P
        db = _P(os.environ.get("JFN_DATA_DIR", _P(__file__).parent / "data")) / "compliance.db"
        con = sqlite3.connect(str(db))
        try:
            tem = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ob_orcamentaria_siafe'").fetchone()
            if not tem:
                return JSONResponse({"ok": True, "total": 0, "detail": "Tabela ainda não criada — rode a coleta SIAFE."})
            tot = con.execute("SELECT COUNT(*), COALESCE(SUM(valor),0) FROM ob_orcamentaria_siafe").fetchone()
            por_ano = [{"exercicio": r[0], "n": r[1], "valor": round(r[2] or 0, 2)}
                       for r in con.execute("SELECT exercicio, COUNT(*), COALESCE(SUM(valor),0) "
                                            "FROM ob_orcamentaria_siafe GROUP BY exercicio ORDER BY exercicio")]
            com_processo = con.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE processo IS NOT NULL AND processo!=''").fetchone()[0]
            # Frescor da coleta — responde "hoje coletou?": MAX do 1º timestamp existente na tabela.
            cols = {r[1] for r in con.execute("PRAGMA table_info(ob_orcamentaria_siafe)")}
            ts_col = next((c for c in ("coletado_em", "created_at", "updated_at", "ingerido_em") if c in cols), None)
            ultima = con.execute(f"SELECT MAX({ts_col}) FROM ob_orcamentaria_siafe").fetchone()[0] if ts_col else None
        finally:
            con.close()
        from datetime import date as _date
        coletou_hoje = bool(ultima and str(ultima)[:10] == _date.today().isoformat())
        return JSONResponse({"ok": True, "total": tot[0], "valor_total": round(tot[1] or 0, 2),
                             "por_ano": por_ano, "com_processo": com_processo,
                             "ultima_atualizacao": ultima, "coletou_hoje": coletou_hoje,
                             "fonte": "SIAFE-Rio 2 / OB Orçamentária (23 colunas: NL, PD, Processo, Credor...)"})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


def _siafe_spawn(args: list, quem: str):
    """Dispara a coleta SIAFE como subprocesso (não bloqueia a request); respeita o lockfile de sessão única."""
    import subprocess
    import sys as _sys
    from pathlib import Path as _P
    from compliance_agent import siafe_runner
    st = siafe_runner.lock_status()
    if st.get("locked"):
        return {"ok": False, "erro": "ocupado", "detail": "Já há uma coleta SIAFE em andamento.", "lock": st}
    log = open(_P(__file__).parent / "data" / f"siafe_{quem}.log", "a")
    subprocess.Popen([_sys.executable, "-m", "compliance_agent.siafe_runner", *args],
                     cwd=str(_P(__file__).parent), stdout=log, stderr=log, start_new_session=True)
    return {"ok": True, "iniciado": True, "comando": quem, "detail": "Coleta SIAFE iniciada em background."}


@app.post("/api/siafe/atualizar")
async def api_siafe_atualizar(payload: dict = None):
    """Atualização DIÁRIA incremental do SIAFE 2 (aba OB Orçamentária, OBs novas, sem filtro). Mantém a base
    fresca sem sweep. Body opcional {"exercicio": 2026}. Roda em background; veja /api/siafe/stats depois."""
    ano = (payload or {}).get("exercicio")
    args = ["diario"] + ([str(int(ano))] if ano else [])
    return JSONResponse(_siafe_spawn(args, "atualizar"))


@app.post("/api/siafe/sweep")
async def api_siafe_sweep(payload: dict = None):
    """SWEEP completo do SIAFE por UG (BACKFILL; fura o teto de 1000). Body {"sistema":"2"} (2=2024-26, 1=2016-23)
    ou {"ug":"133100","exercicio":2026} p/ uma UG. Longo — roda em background."""
    p = payload or {}
    if p.get("ug"):
        args = ["ug", str(p["ug"])] + ([str(int(p["exercicio"]))] if p.get("exercicio") else [])
        return JSONResponse(_siafe_spawn(args, "ug"))
    return JSONResponse(_siafe_spawn(["sweep", str(p.get("sistema", "2"))], "sweep"))


@app.get("/api/siafe/status")
async def api_siafe_status():
    """Estado da coleta SIAFE (lockfile: se há coleta rodando e qual)."""
    from compliance_agent import siafe_runner
    return JSONResponse({"ok": True, "lock": siafe_runner.lock_status()})


@app.get("/api/anomalias")
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


@app.get("/api/cartel")
@app.post("/api/cartel")  # aceita GET e POST: o Yoda às vezes chuta o método (evita 405 na integração)
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


@app.get("/api/rodizio")
@app.post("/api/rodizio")  # aceita GET e POST (o Yoda às vezes chuta o método)
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


@app.get("/api/lista")
async def api_lista():
    """Menu COMPLETO das funções do JFN (para o /lista do Yoda) — gerado da skilltree (capabilities.yaml,
    fonte única), agrupado por domínio. Fica sempre em sincronia com /capacidades; nada de menu fixo defasado."""
    try:
        from compliance_agent.skilltree import SKILLTREE
        texto = SKILLTREE.render_menu()
    except Exception as e:  # noqa: BLE001
        texto = f"🧭 *ECOSSISTEMA JFN* — menu indisponível ({str(e)[:60]}). Use /skills."
    return JSONResponse({"ok": True, "texto": texto})


@app.get("/api/cruzamento")
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


@app.get("/api/coendereco/clusters")
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


@app.get("/api/orgao/cidades")
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


@app.get("/api/sweeps/status")
async def api_sweeps_status():
    """Status dos SWEEPS (coleta contínua): SEI (lê processos SEI das OBs) + SIAFE 2 (OB Orçamentária).
    Para o Yoda responder 'como está o sweep' sem se perder — texto pronto p/ Telegram."""
    import subprocess
    base = Path(__file__).resolve().parent

    def _alive(pat: str) -> bool:
        try:
            return bool(subprocess.run(["pgrep", "-f", pat], capture_output=True).stdout.strip())
        except Exception:  # noqa: BLE001
            return False

    # SEI
    sei_feitos = 0
    try:
        sei_feitos = len(json.loads((base / "data/sei_cache/sei_sweep_progress.json").read_text()).get("feitos", {}))
    except Exception:  # noqa: BLE001
        pass
    sei_tail = ""
    try:
        _ls = [ln for ln in (base / "data/sei_cache/sei_sweep_loop.out").read_text().splitlines() if ln.strip()]
        sei_tail = _ls[-1][:170] if _ls else ""
    except Exception:  # noqa: BLE001
        pass
    sei_sup, sei_run = _alive("sei_supervisor.sh"), _alive("tools[.]sei_sweep")
    sia_sup, sia_run = _alive("siafe_supervisor.sh"), _alive("siafe[_]sweep_full")
    pausado = (base / "data/.pause_sei_sweep").exists() or (base / "data/.pause_sweep_2").exists()

    sia_total = 0
    try:
        import sqlite3
        _c = sqlite3.connect(base / "data/compliance.db")
        sia_total = _c.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe").fetchone()[0]
        _c.close()
    except Exception:  # noqa: BLE001
        pass

    # SIAFE 2: detecta varredura COMPLETA (o supervisor encerra ao concluir; não é "parado/quebrado")
    sia_completo = False
    try:
        _sl = [ln for ln in (base / "data/siafe_sweep_full_2.log").read_text().splitlines() if ln.strip()][-3:]
        sia_completo = any("SWEEP COMPLETO" in ln for ln in _sl)
    except Exception:  # noqa: BLE001
        pass

    def _ic(ok):
        return "🟢" if ok else "🔴"
    estado_sei = "pausado (relatório em curso tem prioridade)" if pausado else ("rodando" if sei_run else ("supervisionado" if sei_sup else "parado"))
    if pausado:
        estado_sia = "pausado"
    elif sia_run:
        estado_sia = "rodando"
    elif sia_completo:
        estado_sia = "✅ varredura completa (todas as UGs); reabre com nova coleta diária"
    elif sia_sup:
        estado_sia = "supervisionado"
    else:
        estado_sia = "ocioso (varredura concluída)"
    _sia_fmt = f"{sia_total:,}".replace(",", ".")
    texto = (
        "🛰️ **Sweeps (coleta contínua)**\n\n"
        f"{_ic(sei_sup or sei_run)} **SEI** — {estado_sei}\n"
        f"   {sei_feitos} processos lidos (checkpoint, resumível).\n"
        f"   _{sei_tail}_\n\n"
        f"{_ic(sia_sup or sia_run or sia_completo)} **SIAFE 2** — {estado_sia}\n"
        f"   base OB Orçamentária: {_sia_fmt} OBs ingeridas."
    )
    return JSONResponse({"ok": True, "texto": texto,
                         "sei": {"feitos": sei_feitos, "supervisor": sei_sup, "rodando": sei_run, "ultima": sei_tail},
                         "siafe": {"supervisor": sia_sup, "rodando": sia_run, "ob_orcamentaria": sia_total},
                         "pausado": pausado})


@app.get("/api/ugs")
async def api_ugs(filtro: Optional[str] = None, limite: int = 50):
    """Catálogo das UGs (órgãos) — o /UG do Yoda. Código + nome canônico + nº de OBs + total pago, para
    o Mestre Jorge saber quais existem e pedir o /orgao certo. Filtro acento-insensível por nome OU código."""
    try:
        from compliance_agent.reporting.inteligencia_orgao import listar_ugs
        limite = max(1, min(int(limite or 50), 151))
        dados = listar_ugs(filtro=filtro, limite=limite)
        return JSONResponse({"ok": dados.get("ok", True), "texto": dados.get("texto", ""),
                             "ugs": dados.get("ugs", []), "n": dados.get("n", 0), "n_total": dados.get("n_total", 0)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@app.post("/api/massare/prever")
async def api_massare_prever(payload: Optional[dict] = None):
    """Previsão direcional + estado atual de um ativo. Body: {"symbol":"prata|^BVSP|SI=F","horizon":5}.
    Aceita NOME amigável (prata, ouro, bitcoin…) — resolve p/ o símbolo certo (corrige o 'XAG=F' do Yoda)."""
    payload = payload or {}
    termo = (payload.get("symbol") or payload.get("ativo") or "^BVSP").strip()
    try:
        horizon = int(payload.get("horizon") or 5)
    except (TypeError, ValueError):
        horizon = 5
    try:
        from massare import engine, engine_regime4, store, market
        store.init_db()
        symbol = market.resolver_symbol(termo)  # prata→SI=F, ouro→GC=F, etc.
        try:
            market._refresh_precos([symbol])  # garante dados mesmo fora do núcleo diário (ex.: prata)
        except Exception:  # noqa: BLE001
            pass
        # motor 4-regimes+drift (edge OOS do universo ≥0); cai p/ o ensemble global se faltar dado
        p = engine_regime4.predict_today(symbol, horizon=horizon) or engine.predict_today(symbol, horizon=horizon)
        if not p:
            return JSONResponse({"ok": False, "erro": f"Sem dados para {termo} ({symbol}).",
                                 "dica": "símbolos: prata=SI=F, ouro=GC=F, bitcoin=BTC-USD, ibovespa=^BVSP"},
                                status_code=404)
        # estado ATUAL (preço + variação) para responder "como está hoje"
        atual = {}
        try:
            df = engine.load_prices(symbol)
            if df is not None and len(df) >= 2:
                ult, ant = float(df["close"].iloc[-1]), float(df["close"].iloc[-2])
                atual = {"preco": round(ult, 2), "var_pct": round((ult / ant - 1) * 100, 2) if ant else None}
        except Exception:  # noqa: BLE001
            pass
        return JSONResponse({"ok": True, "ativo": market.NOMES.get(symbol, termo), "symbol": symbol,
                             "atual": atual, "previsao": p})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


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


@app.get("/api/conflito")
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


@app.get("/api/pncp")
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


@app.get("/api/sobrepreco")
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


@app.get("/api/empresa")
async def api_empresa(cnpj: str):
    """Onda 12 (providers) — cadastro + sócios (QSA) por CNPJ, fonte hospedada (BrasilAPI→cnpj.pw).
    Sem baixar base: HTTP sob demanda + cache TTL. Resposta com proveniência (fonte+data+estado)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("registry", cnpj=cnpj).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/idoneidade")
async def api_idoneidade(cnpj: str = "", nome: str = ""):
    """Onda 12 (providers) — triagem em listas: CEIS/CNEP (BR) + sanções/PEP (OpenSanctions).
    lookup_all: consulta todos os backends disponíveis. Indício a confirmar, nunca acusação."""
    try:
        from compliance_agent.providers import get_providers
        res = get_providers().lookup_all("sanctions", cnpj=(cnpj or None), nome=(nome or None))
        return JSONResponse(content={"resultados": [r.__dict__ for r in res]})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/ownership")
async def api_ownership(nome: str = "", lei: str = ""):
    """Onda 12 (providers) — controle internacional (LEI + relações) via GLEIF (sem chave)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("ownership", nome=(nome or None), lei=(lei or None)).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/leaks")
async def api_leaks(termo: str):
    """Onda 12 (providers) — busca hospedada em vazamentos offshore (ICIJ; link MANUAL)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("leaks", termo=termo).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/links")
async def api_links(nome: str = "", cnpj: str = ""):
    """Onda 12 (providers) — pistas de investigação HOSPEDADA (Max Intel, OSINT-Brazuca, Bellingcat,
    RedeCNPJ, JusBrasil/Escavador). Deep-links já preenchidos com o alvo; uso MANUAL (o JFN só monta)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("links", nome=(nome or None), cnpj=(cnpj or None)).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/diario")
async def api_diario(querystring: str, territory_ids: str = "", desde: str = "", ate: str = "", size: int = 20):
    """Onda 12 (providers) — diários oficiais municipais (Querido Diário). Busca por palavra-chave +
    território IBGE (RJ capital = 3304557) + janela de datas. Sem chave; on-demand + cache."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("gazettes", querystring=querystring, territory_ids=territory_ids,
                                           desde=desde, ate=ate, size=size).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/doador_contrato")
async def api_doador_contrato(cnpj: str):
    """Onda 12 (providers) — TSE doador×contrato: sócios (QSA) do fornecedor que aparecem como
    doadores de campanha (RJ). Indício de conflito a CONFERIR, nunca acusação (CPF mascarado → casa
    por nome). Requer doacao_tse populado (carregar_doacoes_rj(ano))."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("eleitoral", cnpj=cnpj).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/grafo")
async def api_grafo(alvo: str, saltos: int = 2, so_contrato: bool = False):
    """Onda 4 — Grafo de Poder: vizinhança de um alvo (CNPJ/UG/nome) unindo
    sócios+OB+doações+folha+co-endereço, até `saltos`. so_contrato=true foca o fluxo
    de dinheiro (cnpj↔ug↔sócio). Vínculo = indício de relação, nunca prova."""
    try:
        from compliance_agent.grafo_poder import vizinhanca

        return JSONResponse(content=vizinhanca(alvo, saltos=saltos, so_contrato=so_contrato))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/grafo/ftm")
async def api_grafo_ftm(alvo: str, saltos: int = 2):
    """Onda 12 — Export do Grafo de Poder no modelo FollowTheMoney (interoperar c/ Aleph/Gephi)."""
    try:
        from compliance_agent.grafo_ftm import export
        return JSONResponse(content=export(alvo, saltos=saltos))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.post("/api/dossie")
async def api_dossie(payload: Optional[dict] = None):
    """Onda 4 — Dossiê 360 de um CNPJ: cadastro+sanções+OB+conflito+rede+score → PDF.
    Body JSON: {"alvo": "<CNPJ>"}. Indícios para apuração; nenhuma fonte indisponível é fabricada.
    Geração ASSÍNCRONA: responde {status:"gerando"} na hora e o JFN empurra o PDF no Telegram quando
    fica pronto (igual /api/relatorio/inteligencia). Modo síncrono p/ CLI/testes: {"sync": true}."""
    payload = payload or {}
    alvo = (payload.get("alvo") or payload.get("cnpj") or "").strip()
    if not alvo:
        return JSONResponse(content={"ok": False, "erro": "informe {'alvo': CNPJ}"}, status_code=400)
    if payload.get("sync"):  # modo síncrono (CLI/testes)
        try:
            from compliance_agent.dossie import dossie
            return JSONResponse(content=await dossie(alvo))
        except Exception as e:  # noqa: BLE001
            return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)
    key = f"dossie:{alvo.lower()}"
    if key in _REL_EM_CURSO:
        return JSONResponse({"ok": True, "status": "gerando",
                             "msg": "⏳ Já estou preparando esse dossiê — te envio aqui em instantes."})
    _REL_EM_CURSO.add(key)
    asyncio.create_task(_gerar_e_enviar_dossie(alvo, key))
    return JSONResponse({"ok": True, "status": "gerando",
                         "msg": f"📥 Preparando o Dossiê 360 de *{alvo}* (PDF). "
                                "Eu te envio aqui mesmo em ~1–2 min — não precisa repetir o comando."})


@app.get("/api/sei/direcionamento")
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


@app.post("/api/radar/vigiar")
async def api_radar_vigiar(payload: Optional[dict] = None):
    """Onda 6 — Radar: adiciona um alvo à watchlist 24/7. Body {"alvo","tipo":cnpj|ug|nome|objeto}.
    Ao surgir edital aberto restritivo / OB anômala do alvo, chega alerta no Telegram."""
    try:
        from compliance_agent.radar import vigiar

        p = payload or {}
        return JSONResponse(content=vigiar(p.get("alvo", ""), p.get("tipo", "cnpj")))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/radar/status")
async def api_radar_status():
    """Onda 6 — Radar: o que está sendo vigiado + últimos alertas."""
    try:
        from compliance_agent.radar import status as radar_status

        return JSONResponse(content=radar_status())
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.post("/api/radar/ciclo")
async def api_radar_ciclo():
    """Onda 6 — Radar: roda um ciclo de vigilância agora (o timer systemd chama isto)."""
    try:
        from compliance_agent.radar import ciclo

        return JSONResponse(content=await ciclo())
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.post("/api/mandato/minuta")
async def api_mandato_minuta(payload: Optional[dict] = None):
    """Onda 10 — Instrumento de mandato: gera minuta .docx (requerimento ALERJ / representação TCE /
    notícia de fato MP / post). Body {"tipo","base"}. Diligência/representação, NUNCA condenação."""
    try:
        from compliance_agent.mandato import gerar

        p = payload or {}
        return JSONResponse(content=gerar(p.get("tipo", ""), p.get("base", "")))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/memoria")
async def api_memoria(limite: int = 15):
    """Onda 11 — Memória consolidada do ecossistema (Massare/Lex/Hermes)."""
    try:
        from compliance_agent.memoria import consolidar
        return JSONResponse(content=consolidar(limite))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


# ---- Skilltree via HTTP (Onda 13, parte JFN — o comando /skills do Yoda chama estas rotas) ----
@app.get("/api/skills")
async def api_skills(filtro: str = ""):
    """Skilltree (capacidades) agrupada por domínio — texto p/ o /skills do Telegram."""
    try:
        from compliance_agent.skilltree import SKILLTREE
        return JSONResponse(content={"ok": True, "texto": SKILLTREE.render(filtro),
                                     "n": len(SKILLTREE.capacidades), "sha": SKILLTREE.sha})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/skill")
async def api_skill(id: str):
    """Detalhe de uma capacidade (rota, args, quando usar, status) — p/ o /skill <id>."""
    try:
        from compliance_agent.skilltree import SKILLTREE
        return JSONResponse(content={"ok": True, "texto": SKILLTREE.detalhe(id)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.post("/api/skills/reload")
async def api_skills_reload():
    """Recarrega capabilities.yaml do disco (fail-safe) — p/ o /skills_reload (admin no Yoda)."""
    try:
        from compliance_agent.skilltree import SKILLTREE
        return JSONResponse(content={"ok": True, **SKILLTREE.reload()})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/skills/validate")
async def api_skills_validate():
    """Valida o contrato (schema + rotas PRONTO existem) — p/ o /skills_validate (admin)."""
    try:
        from compliance_agent.skilltree import SKILLTREE
        probs = SKILLTREE.validate()
        return JSONResponse(content={"ok": not probs, "problemas": probs})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


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


# ── Reverse tunnel (Windows → Server) ────────────────────────────────────────

@app.get("/api/tunnel/status")
async def api_tunnel_status():
    """Retorna se o tunnel do Windows está conectado."""
    return JSONResponse({
        "connected": _tunnel_ws is not None,
        "obs_recebidas": len(_tunnel_results),
    })


@app.post("/api/tunnel/collect")
async def api_tunnel_collect(payload: dict = None):
    """Dispara coleta de OBs pelo tunnel Windows. Requer tunnel conectado."""
    global _tunnel_collect_args, _tunnel_results
    if _tunnel_ws is None:
        return JSONResponse({"erro": "Tunnel Windows não conectado"}, status_code=503)
    anos = (payload or {}).get("anos", [2023, 2024, 2025, 2026])
    _tunnel_collect_args = {"anos": anos}
    _tunnel_results = []
    _tunnel_collect_event.set()
    try:
        await _tunnel_ws.send_text(json.dumps({"type": "collect", "anos": anos}))
    except Exception as e:
        return JSONResponse({"erro": str(e)}, status_code=500)
    return JSONResponse({"ok": True, "anos": anos, "msg": "Comando enviado ao tunnel Windows"})


def _salvar_obs_no_db(obs: list[dict]):
    """Persiste OBs recebidas via tunnel no banco de dados."""
    try:
        from compliance_agent.database.models import init_db, get_session, OrdemBancaria
        init_db()
        session = get_session()
        try:
            salvos = 0
            for ob in obs:
                ano = ob.get("exercicio")
                if ano:
                    session.query(OrdemBancaria).filter(
                        OrdemBancaria.exercicio == str(ano),
                        OrdemBancaria.favorecido_cpf == "19.088.605/0001-04",
                        OrdemBancaria.categoria == "mgs_clean_auditoria",
                    ).delete(synchronize_session=False)
                novo = OrdemBancaria(
                    numero_ob       = ob.get("numero_ob", ""),
                    data_emissao    = ob.get("data_emissao"),
                    ug_codigo       = ob.get("ug_codigo", ""),
                    ug_nome         = ob.get("ug_nome", ""),
                    favorecido_cpf  = ob.get("favorecido_cpf", ""),
                    favorecido_banco= ob.get("favorecido_nome", ""),
                    valor           = float(ob.get("valor") or 0),
                    tipo_ob         = ob.get("tipo_ob", ""),
                    status          = ob.get("status", "PAGO"),
                    numero_processo = ob.get("numero_processo", ""),
                    exercicio       = str(ob.get("exercicio", "")),
                    categoria       = "mgs_clean_real",
                    raw_json        = ob.get("raw_json", "{}"),
                )
                session.add(novo)
                salvos += 1
            session.commit()
            return salvos
        finally:
            session.close()
    except Exception as e:
        print(f"[tunnel] erro ao salvar OBs: {e}")
        return 0


def _salvar_obs_json(obs: list[dict]):
    """Salva OBs em JSON por ano e consolidado."""
    cache_dir = Path(__file__).parent / "data" / "sei_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    por_ano: dict[int, list] = {}
    for ob in obs:
        ano = int(ob.get("exercicio", 0))
        por_ano.setdefault(ano, []).append(ob)

    for ano, lst in por_ano.items():
        (cache_dir / f"mgsclean_obs_{ano}.json").write_text(
            json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    consolidado = {
        "empresa": "MGS CLEAN SOLUCOES E SERVICOS LTDA",
        "cnpj": "19.088.605/0001-04",
        "fonte": "SIAFE via tunnel",
        "coleta": datetime.now().isoformat(),
        "total_obs": len(obs),
        "total_valor": sum(float(o.get("valor") or 0) for o in obs),
        "por_ano": {
            str(ano): {
                "count": len(lst),
                "valor": sum(float(o.get("valor") or 0) for o in lst),
            }
            for ano, lst in por_ano.items()
        },
        "obs": obs,
    }
    (cache_dir / "mgsclean_obs_todas.json").write_text(
        json.dumps(consolidado, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cache_dir / "mgsclean_obs_todas.json"


def _git_push_obs():
    """Commita e faz push dos arquivos de OBs coletados."""
    try:
        import subprocess
        root = str(Path(__file__).parent)
        subprocess.run(["git", "-C", root, "add",
                        "data/sei_cache/mgsclean_obs*.json",
                        "data/compliance.db"], check=False, capture_output=True)
        subprocess.run(["git", "-C", root, "commit", "-m",
                        "data: OBs MGS CLEAN coletadas via tunnel Windows"],
                       check=False, capture_output=True)
        subprocess.run(["git", "-C", root, "push", "-u", "origin",
                        "claude/rj-finance-agent-BYlhJ"],
                       check=False, capture_output=True, timeout=60)
        print("[tunnel] git push concluído")
    except Exception as e:
        print(f"[tunnel] git push falhou: {e}")


@app.websocket("/tunnel")
async def websocket_tunnel(ws: WebSocket):
    """WebSocket reverso: Windows conecta aqui para transmitir OBs do SIAFE."""
    global _tunnel_ws, _tunnel_results

    await ws.accept()
    async with _tunnel_lock:
        _tunnel_ws = ws

    print("[tunnel] Windows conectado!")
    total_obs_recebidas = 0

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            t   = msg.get("type", "")

            if t == "hello":
                print(f"[tunnel] hello de {msg.get('role', '?')}")
                await ws.send_text(json.dumps({"type": "ack", "msg": "JFN Server OK"}))

            elif t == "obs_batch":
                ano = msg.get("ano")
                obs = msg.get("obs", [])
                print(f"[tunnel] {len(obs)} OBs recebidas do ano {ano}")
                _tunnel_results.extend(obs)
                total_obs_recebidas += len(obs)
                # Salva no DB em tempo real
                salvos = _salvar_obs_no_db(obs)
                await ws.send_text(json.dumps({
                    "type": "ack_batch", "ano": ano,
                    "salvos": salvos, "total": total_obs_recebidas,
                }))

            elif t == "done":
                total = msg.get("total", total_obs_recebidas)
                print(f"[tunnel] Coleta finalizada: {total} OBs")
                # Salva JSON consolidado + git push
                json_path = _salvar_obs_json(_tunnel_results)
                _git_push_obs()
                await ws.send_text(json.dumps({
                    "type": "saved",
                    "total": total,
                    "json": str(json_path),
                    "msg": "OBs salvas no DB e JSON. Git push feito.",
                }))

            elif t == "progress":
                print(f"[tunnel] {msg.get('msg', '')}")

            elif t == "error":
                print(f"[tunnel] erro no Windows: {msg.get('msg', '')}")
                await ws.send_text(json.dumps({"type": "ack_error", "msg": msg.get("msg", "")}))

            elif t == "pong":
                pass

    except WebSocketDisconnect:
        print("[tunnel] Windows desconectou")
    except Exception as e:
        print(f"[tunnel] erro: {e}")
    finally:
        async with _tunnel_lock:
            if _tunnel_ws is ws:
                _tunnel_ws = None


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
