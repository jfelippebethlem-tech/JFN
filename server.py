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
import hashlib
import hmac
import json
import os
import secrets
import time
import argparse
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # só p/ anotações (o import real é lazy dentro das rotas) — resolve F821
    from compliance_agent.hermes_goal import HermesGoalAgent

import uvicorn
from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
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


# ── login_jfn — gate de acesso ao dashboard (ISOLADO do Bond/:3000) ───────────────────────────────
# Filosofia: o JFN expõe dados sensíveis de auditoria (CPF/casos). Quando o servidor é exposto à rede
# (host 0.0.0.0 + Security List Oracle, igual ao Bond), TUDO passa a exigir login_jfn — EXCETO chamadas
# de localhost (o Yoda chama 127.0.0.1:8000 internamente e NÃO pode quebrar). Cookie HMAC-assinado, sem deps.
# `secure` é gated por env COOKIE_SECURE (lição do Bond: secure=true descarta o cookie em HTTP puro).
_DASH_SENHA = os.environ.get("JFN_DASH_PASSWORD", "")
# Sem JFN_DASH_SECRET/JFN_DASH_PASSWORD, gera secret ALEATÓRIO por processo (não mais o literal
# "jfn-dev-secret", que tornava o cookie de sessão forjável por quem conhecesse o default).
_DASH_SECRET = (os.environ.get("JFN_DASH_SECRET") or _DASH_SENHA or secrets.token_hex(32)).encode()
_DASH_COOKIE = "jfn_session"
_DASH_TTL = int(os.environ.get("JFN_DASH_TTL", str(30 * 24 * 3600)))  # 30 dias
_DASH_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "").lower() in ("1", "true", "yes")
_DASH_LOCAL = {"127.0.0.1", "::1", "localhost", "testclient", None, ""}  # "testclient" = TestClient in-process (testes/Yoda)


def _dash_token() -> str:
    exp = str(int(time.time()) + _DASH_TTL)
    sig = hmac.new(_DASH_SECRET, exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def _dash_token_ok(tok: str | None) -> bool:
    if not tok or "." not in tok:
        return False
    exp, sig = tok.rsplit(".", 1)
    good = hmac.new(_DASH_SECRET, exp.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return False
    try:
        return int(exp) > int(time.time())
    except ValueError:
        return False


@app.middleware("http")
async def _auth_jfn(request: Request, call_next):
    # Sem senha configurada → gate DESLIGADO (modo dev/local, comportamento legado preservado).
    if not _DASH_SENHA:
        return await call_next(request)
    cliente = request.client.host if request.client else ""
    path = request.url.path
    if (cliente in _DASH_LOCAL                      # Yoda interno (127.0.0.1) nunca é barrado
            or path == "/login_jfn"
            or path == "/favicon.ico"
            or path.startswith("/static/login")):
        return await call_next(request)
    if _dash_token_ok(request.cookies.get(_DASH_COOKIE)):
        return await call_next(request)
    if path.startswith("/api/") or path.startswith("/ws"):
        return JSONResponse({"erro": "não autenticado — faça login em /login_jfn"}, status_code=401)
    return RedirectResponse("/login_jfn", status_code=303)


_LOGIN_HTML = """<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>JFN — Acesso</title>
<style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;
background:#0b1020;color:#e8edf7;font:16px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
.card{background:#141b30;border:1px solid #243049;border-radius:16px;padding:34px 30px;width:330px;
box-shadow:0 18px 50px rgba(0,0,0,.45)}h1{margin:0 0 4px;font-size:21px;letter-spacing:.3px}
p{margin:0 0 20px;color:#8a97b3;font-size:13px}input{width:100%;padding:12px 14px;border-radius:10px;
border:1px solid #2a3650;background:#0d1424;color:#e8edf7;font-size:15px;margin-bottom:12px}
button{width:100%;padding:12px;border:0;border-radius:10px;background:#3b82f6;color:#fff;font-size:15px;
font-weight:600;cursor:pointer}button:hover{background:#2f6fe0}.err{color:#f87171;font-size:13px;
margin:-4px 0 12px;min-height:18px}.foot{margin-top:16px;color:#5d6a87;font-size:11px;text-align:center}</style>
</head><body><form class=card method=post action=/login_jfn>
<h1>🔐 JFN</h1><p>Motor de auditoria/compliance — RJ</p>
<div class=err>{{ERRO}}</div>
<input type=password name=senha placeholder="Senha de acesso" autofocus autocomplete=current-password>
<button type=submit>Entrar</button>
<div class=foot>Acesso restrito · dados de auditoria (LGPD art. 7º,II/23)</div>
</form></body></html>"""


@app.get("/login_jfn", response_class=HTMLResponse)
async def login_jfn_form(erro: int = 0):
    msg = "Senha incorreta." if erro else ""
    return HTMLResponse(_LOGIN_HTML.replace("{{ERRO}}", msg))


@app.post("/login_jfn")
async def login_jfn_post(senha: str = Form("")):
    if _DASH_SENHA and hmac.compare_digest(senha, _DASH_SENHA):
        resp = RedirectResponse("/painel", status_code=303)
        resp.set_cookie(_DASH_COOKIE, _dash_token(), max_age=_DASH_TTL,
                        httponly=True, samesite="lax", secure=_DASH_COOKIE_SECURE)
        return resp
    return RedirectResponse("/login_jfn?erro=1", status_code=303)


@app.get("/logout_jfn")
async def logout_jfn():
    resp = RedirectResponse("/login_jfn", status_code=303)
    resp.delete_cookie(_DASH_COOKIE)
    return resp


@app.get("/", response_class=HTMLResponse)
async def index():
    """Painel JFN unificado (mobile-first, dark): visão geral, alertas, SIAFE, sweeps + atalhos. Antigo hub em static/painel.html (aposentado)."""
    return FileResponse("static/jfn-painel.html")


@app.get("/auditoria", response_class=HTMLResponse)
async def auditoria_ui():
    """Painel de Auditoria Financeira (KPIs, alertas, OBs, favorecidos, /relatorio + Lex)."""
    return FileResponse("static/dashboard.html")


@app.get("/painel", response_class=HTMLResponse)
async def painel_fiscalizacao():
    """Painel de fiscalização unificado (leve, Tailwind): visão geral, auditoria/alertas, SIAFE, sweeps, cartel."""
    return FileResponse("static/jfn-painel.html")


@app.get("/chat", response_class=HTMLResponse)
async def chat_ui():
    """Serve the legacy chat UI."""
    return FileResponse("static/index.html")


@app.get("/hermes", response_class=HTMLResponse)
async def hermes_ui():
    """Serve a interface do Hermes — auditor autônomo guiado por missão."""
    return FileResponse("static/hermes.html")


# ── Hermes Goal Agent (missão autônoma + chat) ────────────────────────────────







# ── Multi-missão paralela (pool limitado + histórico no banco) ────────────────





















# ── Auditor 24 horas (auditoria automática e ininterrupta) ────────────────────









# ── Relatórios ASSÍNCRONOS: respondem rápido e o JFN EMPURRA os documentos ao Telegram ──
# Motivo: a ferramenta `terminal` do Yoda mata o curl em ~60s, mas o relatório leva 1–3 min
# (PNCP/Playwright + contenção dos sweeps) — o Yoda nunca recebia os caminhos. Agora o /relatorio
# devolve {status:"gerando"} na hora e o JFN envia o PDF+XLSX+Lex direto no chat quando ficam prontos.

# Relatório do Mestre Jorge tem PRIORIDADE sobre os sweeps: 3 Chromium/Playwright concorrentes
# (2 sweeps + relatório) travavam a geração por contenção. Ao gerar, pausamos os sweeps (flags que os
# supervisores honram → não relançam) e matamos os em curso; quando não há mais relatório, retomamos.


















# ── MASSARE (mercado/predição) — exposto no barramento para o Yoda ────────────





























































@app.get("/graph", response_class=HTMLResponse)
async def graph_page():
    """Serve the D3.js graph visualization page."""
    return FileResponse("static/graph.html")




















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












































# ---- Skilltree via HTTP (Onda 13, parte JFN — o comando /skills do Yoda chama estas rotas) ----










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


# ── Split 2026-07-06: rotas por domínio (ver rotas/*.py; rede de segurança em tests/test_server_snapshot.py) ──
from rotas import hermes as _r_hermes, produtos as _r_produtos, massare as _r_massare,     sistema as _r_sistema, investigacao as _r_investigacao  # noqa: E402

for _r in (_r_hermes, _r_produtos, _r_massare, _r_sistema, _r_investigacao):
    app.include_router(_r.router)


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

