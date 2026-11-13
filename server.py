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
import logging
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
    pass

import uvicorn
from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)


# ── Load .env ─────────────────────────────────────────────────────────────────

def _load_env():
    # Carregador unificado: aceita .env e .env.txt (fallback do Windows).
    try:
        from compliance_agent.envfile import carregar_env
        carregar_env()
        return
    except Exception as exc:
        logger.debug("carregar_env indisponível, usando fallback .env: %s", exc)
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
    # Conexão GUARDIÃ do WAL-index. Medido em 31/07/26: em janela ociosa este processo chegava a
    # ZERO conexões abertas, outro processo fechava por último e o SQLite desvinculava -wal/-shm;
    # daí em diante o painel devolvia "database disk image is malformed" com o ARQUIVO íntegro,
    # 7-14x por dia, e a cura era reiniciar o serviço (derrubando browser e login SIAFE junto).
    from compliance_agent.database.guarda_wal import segurar as _segurar_wal
    _ok_wal = _segurar_wal(Path(__file__).parent / "data" / "compliance.db")
    print(f"[guarda-wal] conexão guardiã {'ATIVA' if _ok_wal else 'AUSENTE'} — "
          f"{'-wal/-shm não serão desvinculados' if _ok_wal else 'painel volta a depender do guardião de restart'}")

    # Promessa feita ao Mestre não pode morrer com o processo: o que o run anterior prometeu e não
    # entregou volta à fila agora (o Yoda diz "te envio em ~1–2 min" e a geração é um create_task).
    try:
        from rotas.produtos import retomar_promessas
        _n_prom = await retomar_promessas()
        if _n_prom:
            print(f"[promessas] {_n_prom} entrega(s) do run anterior recolocada(s) na fila")
    except Exception as _e:  # noqa: BLE001
        print(f"[promessas] não consegui retomar ({type(_e).__name__}: {_e}) — nada foi perdido do disco")

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
    except Exception as exc:
        logger.debug("warmup do motor de relatório não agendado: %s", exc)

    # WARMUP DAS TELAS DE PADRÃO da fila do fiscal. Elas varrem o acervo e têm cache de 1 h; na
    # PRIMEIRA visita depois de um restart o cache está frio, e como a API é single-process os oito
    # cards entram em fila — medido em 2026-08-09, um deles não chegava à tela e o verificador
    # reprovava. Aquecer em background resolve para quem abre o painel, sem atrasar o boot: cada
    # tela roda uma vez, em série, com o servidor já respondendo.
    async def _warmup_padroes():
        try:
            await asyncio.sleep(20)          # deixa o boot e o warmup de relatório passarem
            import anyio
            from tools.screen_aditivo_precoce import medir as _adit
            from tools.screen_consorcio_veiculo import medir as _consv
            from tools.screen_coparticipacao_relacionados import medir as _copa
            from tools.screen_fim_de_exercicio import medir as _fim
            from tools.screen_recuperacao_judicial import medir as _recj
            for nome, fn in (("fim_de_exercicio", _fim), ("coparticipacao", _copa),
                             ("recuperacao_judicial", _recj), ("aditivo_precoce", _adit),
                             ("consorcio_veiculo", _consv)):
                await anyio.to_thread.run_sync(fn)   # fora do event loop: não trava as rotas
                await asyncio.sleep(1)
            print("[warmup] telas de padrão aquecidas (fila do fiscal abre instantânea)")
        except (ImportError, OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            # aquecimento é conforto, nunca requisito — mas o motivo tem de sair, senão a tela
            # lenta na primeira visita vira mistério
            print(f"[warmup] telas de padrão não aquecidas (não-fatal): {exc.__class__.__name__}")
    try:
        asyncio.create_task(_warmup_padroes())
    except RuntimeError as exc:              # sem event loop rodando — só isso pode falhar aqui
        logger.debug("warmup das telas de padrão não agendado: %s", exc)

    # Guard de idle: encerra o Chromium ocioso após N min (§6, evita o leak de browser 24h numa VM sem swap).
    global _browser_reaper_task
    if _BROWSER_IDLE_MIN > 0:
        try:
            _browser_reaper_task = asyncio.create_task(_browser_idle_reaper())
            print(f"[browser] guard de idle ativo: encerra o Chromium após {_BROWSER_IDLE_MIN:.0f}min sem uso "
                  f"(relança lazy; env JFN_BROWSER_IDLE_MIN, 0=off)", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[browser] guard de idle não iniciado ({e.__class__.__name__}) — não-fatal")

    # Batimento da guardiã do WAL-index: a conexão viva impede o caminho "última conexão fechou",
    # mas NÃO impede que outro processo desvincule o `-shm` por baixo dela (no Linux isso é
    # permitido, e conexão ociosa não segura lock). Quando o arquivo some, a guardiã fica com
    # mapeamento morto e as conexões NOVAS deste processo passam a falhar com "malformed" — foi o
    # que derrubou o painel às 17:42 e 19:24 de 31/07/26, já com a guardiã ativa. O ciclo troca a
    # guardiã assim que percebe o sumiço, antes de o auditor levar um HTTP 500.
    async def _bater_wal():
        from compliance_agent.database.guarda_wal import bater
        while True:
            try:
                await asyncio.sleep(30)
                await asyncio.to_thread(bater)
            except asyncio.CancelledError:
                raise
            # sem captura genérica: `bater()` já trata a família específica e devolve bool. Se algo
            # escapar dali é bug real e precisa aparecer, não virar log morno num laço infinito.

    if _ok_wal:
        asyncio.create_task(_bater_wal())

    yield

    if _browser_reaper_task:
        _browser_reaper_task.cancel()
        try:
            await _browser_reaper_task
        except (asyncio.CancelledError, Exception) as exc:  # noqa: BLE001 — shutdown, best-effort
            logger.debug("browser reaper encerrado no shutdown: %s", exc)

    if _agent:
        try:
            await _agent.stop()
        except Exception as e:
            # TargetClosedError no shutdown = página/browser já fechados (reaper de ócio ou o
            # próprio Chromium caiu antes) — resultado desejado alcançado; só ruído no journal.
            if "TargetClosed" in e.__class__.__name__ or "has been closed" in str(e):
                logger.debug("[SIAFE] stop no shutdown: browser já estava fechado (%s)", e.__class__.__name__)
            else:
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
# v49: o CSS e o JS do painel saíram de dentro do HTML (eram 178 KB + 337 KB inline, num arquivo de
# 519 KB que ia inteiro pela rede a cada carga, sem compressão e sem cache). Servidos daqui, ganham
# gzip (abaixo) e cache longo — o `?v=<hash>` no link é que invalida quando o conteúdo muda.
# `StaticFiles` levanta RuntimeError no IMPORT se o diretório não existe — montar antes de a
# extração rodar derrubava o servidor inteiro. Criar é idempotente e torna a ordem das etapas
# irrelevante (o CSS pode sair numa sessão e o JS na seguinte).
Path("static/css").mkdir(parents=True, exist_ok=True)
Path("static/js").mkdir(parents=True, exist_ok=True)

class _StaticVersionado(StaticFiles):
    """Cache imutável SÓ para quem veio com `?v=<hash>`.

    O `?v=` torna a URL única por conteúdo: o arquivo pode ficar no navegador para
    sempre, porque o link muda quando o conteúdo muda. Sem `?v=` (acesso direto,
    ferramenta, curl) mantém-se o padrão do Starlette — etag/last-modified.
    """

    def file_response(self, full_path, stat_result, scope, status_code=200):
        resp = super().file_response(full_path, stat_result, scope, status_code)
        if b"v=" in scope.get("query_string", b""):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


class _StaticAssets(_StaticVersionado):
    """Fontes, vídeos e ícones: sem `?v=`, um dia de cache e depois revalida pelo etag.

    Sem isto o navegador revalidava cada vídeo/fonte a cada visita (medido em 04/11/2026)."""

    def file_response(self, full_path, stat_result, scope, status_code=200):
        resp = super().file_response(full_path, stat_result, scope, status_code)
        resp.headers.setdefault("Cache-Control", "public, max-age=86400")
        return resp


app.mount("/static/assets", _StaticAssets(directory="static/assets"), name="assets")  # fontes/libs self-hosted do painel
app.mount("/static/css", _StaticVersionado(directory="static/css"), name="css")
app.mount("/static/js", _StaticVersionado(directory="static/js"), name="js")

# GZIP — não havia nenhum. O painel mandava 519 KB de texto sem compressão em TODA carga; HTML, CSS
# e JS comprimem 4-6× nesse tipo de conteúdo. `minimum_size` evita gastar CPU com resposta pequena,
# que numa VM de 2 vCPU importa.
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402 — junto do mount que ele serve

_JA_COMPRIMIDO = (".mp4", ".webm", ".jpg", ".jpeg", ".png", ".webp", ".woff2", ".pdf", ".zip", ".gz")


class _GZipSemMidia(GZipMiddleware):
    """Vídeo/imagem/fonte já vêm comprimidos: o gzip ganhava 0,15% num MP4 de 1,3 MB, gastava CPU
    a cada visita e devolvia 206 com `content-encoding: gzip` e `content-range` dos bytes crus —
    resposta inválida para o player que pede Range (medido em 04/11/2026)."""

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path", "").lower().endswith(_JA_COMPRIMIDO):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


app.add_middleware(_GZipSemMidia, minimum_size=1024)


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
# Os dois túneis (Cloudflare e Tailscale Funnel) entregam o visitante da INTERNET pela porta 127.0.0.1.
# Hoje quem salva é o uvicorn reescrever request.client a partir do X-Forwarded-For — padrão implícito
# (proxy_headers), que um upgrade ou flag muda sem aviso e abriria o painel inteiro. Por isso a isenção
# de localhost exige também que NÃO haja cabeçalho de proxy: o Yoda nunca manda nenhum.
_DASH_PROXY_HDRS = ("x-forwarded-for", "x-real-ip", "forwarded", "cf-connecting-ip", "tailscale-user-login")
# Login sem limite de tentativa = senha adivinhável pela internet. 5 erros em 15 min por IP → 429.
_LOGIN_FALHAS: dict[str, list[float]] = {}
_LOGIN_MAX, _LOGIN_JANELA = 5, 15 * 60
_SEC_HDRS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
             "Referrer-Policy": "same-origin", "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
             "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"}


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
    via_proxy = any(h in request.headers for h in _DASH_PROXY_HDRS)
    if ((cliente in _DASH_LOCAL and not via_proxy)  # Yoda interno (127.0.0.1) nunca é barrado
            or path == "/login_jfn"
            or path == "/favicon.ico"
            or path.startswith("/static/login")):
        return await call_next(request)
    if _dash_token_ok(request.cookies.get(_DASH_COOKIE)):
        return await call_next(request)
    if path.startswith("/api/") or path.startswith("/ws"):
        return JSONResponse({"erro": "não autenticado — faça login em /login_jfn"}, status_code=401)
    return RedirectResponse("/login_jfn", status_code=303)


# ── A PORTA DE ENTRADA SERVE A SI MESMA (2026-11-09) ────────────────────────────────────────────
# Para quem chega pela INTERNET (Funnel/Cloudflare = sem cookie e com cabeçalho de proxy), tudo fora
# de `/login_jfn` e `/static/login*` é 303 para o próprio login. A página citava
# `/static/assets/portal-hero.jpg` e as fontes em `/static/assets/fonts/` — e as quatro voltavam 303:
# o visitante de verdade via o login SEM fundo e SEM fonte; só o localhost via a página inteira.
# A correção NÃO alarga a isenção: tudo o que esta página cita mora em `static/login/`, que a
# isenção `/static/login*` já cobria e onde nada estava publicado. Teste: `test_painel_seguranca`.
Path("static/login").mkdir(parents=True, exist_ok=True)
app.mount("/static/login", _StaticAssets(directory="static/login"), name="login")

_LOGIN_HTML = """<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name=color-scheme content=dark><meta name=robots content="noindex,nofollow">
<meta name=theme-color content="#02040a">
<title>Acesso — Controle Externo</title>
<script src=/static/login/v61.js></script>
<link rel=preload href=/static/login/fonts/IBMPlexSans-Regular.woff2 as=font type=font/woff2 crossorigin>
<link rel=preload href=/static/login/fonts/IBMPlexSans-SemiBold.woff2 as=font type=font/woff2 crossorigin>
<style>
  /* Tudo o que esta pagina cita vem de /static/login/ — a UNICA pasta que um visitante sem
     sessao consegue baixar. Citar a pasta de assets do painel aqui e 303 para quem vem da internet. */
  @font-face{font-family:"Plex";src:url(/static/login/fonts/IBMPlexSans-Regular.woff2) format("woff2");
    font-weight:400;font-display:swap}
  @font-face{font-family:"Plex";src:url(/static/login/fonts/IBMPlexSans-SemiBold.woff2) format("woff2");
    font-weight:600;font-display:swap}
  @font-face{font-family:"PlexMono";src:url(/static/login/fonts/IBMPlexMono-Medium.woff2) format("woff2");
    font-weight:500;font-display:swap}
  :root{
    --bg:oklch(0.035 0.014 265); --surf:oklch(0.108 0.021 265);
    --bd:oklch(0.30 0.031 265);  --bd2:oklch(0.24 0.026 265);
    --tx:oklch(0.95 0.008 265);  --tx2:oklch(0.82 0.014 265);
    --mut:oklch(0.72 0.019 265);            /* >=4.5:1 sobre o vidro escurecido */
    --ion:oklch(0.78 0.14 220); --ion2:oklch(0.62 0.16 250);
    --flame:oklch(0.78 0.16 55); --flame2:oklch(0.70 0.18 45); --flame-ink:oklch(0.21 0.05 50);
    --rose:oklch(0.66 0.20 18);
    --mono:"PlexMono",ui-monospace,Menlo,Consolas,monospace}
  *{box-sizing:border-box}
  html{background:var(--bg)}
  body{margin:0;min-height:100svh;display:grid;place-items:center;padding:24px;
    background:transparent;color:var(--tx);
    font:400 16px/1.5 "Plex",system-ui,Segoe UI,Roboto,sans-serif;
    -webkit-font-smoothing:antialiased}

  /* == O FUNDO VIVO ======================================================
     Camadas, de baixo para cima: poster (a imagem chega primeiro e sozinha
     ja e a cena) -> video em loop (so entra quando REALMENTE toca, por cima
     do poster, sem piscar) -> veu escuro (contraste do texto nao depende do
     quadro do video). Retrato usa a peca 9:16; paisagem, a 16:9.          */
  .fundo{position:fixed;inset:0;z-index:-1;overflow:hidden;pointer-events:none;background:var(--bg)}
  .fundo img,.fundo video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;
    object-position:50% 30%}
  .fundo video{opacity:0;transition:opacity .9s cubic-bezier(.2,.7,.2,1)}
  .fundo video.on{opacity:1}
  .fundo::after{content:"";position:absolute;inset:0;
    background:
      radial-gradient(ellipse 120% 70% at 50% 30%,transparent 0,oklch(0.035 0.014 265/.28) 55%,oklch(0.035 0.014 265/.70) 100%),
      linear-gradient(180deg,oklch(0.035 0.014 265/.30) 0%,oklch(0.035 0.014 265/.18) 30%,oklch(0.035 0.014 265/.62) 62%,oklch(0.035 0.014 265/.90) 100%)}
  /* sem a peca nova (arquivo ainda nao publicado): volta a vinheta de antes */
  .sem-poster .fundo img{display:none}
  .sem-poster .fundo{background:var(--bg) url(/static/login/portal-hero.jpg) 50% 42%/cover no-repeat}
  .sem-poster .fundo::after{background:oklch(0.035 0.014 265/.74)}

  /* == O CARTAO DE VIDRO (visionOS) =====================================
     Vidro de verdade: o fundo passa borrado e ESCURECIDO (brightness) — e
     o escurecimento que segura o texto acima de 4.5:1 mesmo quando o anel
     incandescente do video passa atras do cartao. Highlight especular no
     topo, borda-hairline, sombra de profundidade.                          */
  .card{position:relative;width:min(380px,100%);padding:30px 28px 24px;border-radius:22px;
    border:1px solid oklch(1 0 0/.12);
    background:linear-gradient(180deg,oklch(1 0 0/.075),oklch(1 0 0/.015) 38%,transparent 70%),
      oklch(0.095 0.022 262/.62);
    -webkit-backdrop-filter:blur(22px) saturate(1.5) brightness(.72);
    backdrop-filter:blur(22px) saturate(1.5) brightness(.72);
    box-shadow:inset 0 1px 0 oklch(1 0 0/.20),inset 0 0 0 1px oklch(1 0 0/.025),
      inset 0 -18px 40px -30px color-mix(in oklch,var(--ion) 60%,transparent),
      0 30px 80px oklch(0 0 0/.55),0 0 0 .5px oklch(0 0 0/.6)}
  /* a lamina: um fio de luz ion no topo do vidro, como o conduite do painel */
  .card::before{content:"";position:absolute;left:22px;right:22px;top:-1px;height:1px;border-radius:1px;
    background:linear-gradient(90deg,transparent,color-mix(in oklch,var(--ion) 85%,white) 30%,
      color-mix(in oklch,var(--ion) 85%,white) 70%,transparent);
    box-shadow:0 0 10px color-mix(in oklch,var(--ion) 70%,transparent)}
  .marca{display:flex;align-items:center;gap:11px;margin-bottom:20px}
  /* o selo do painel, nao um emoji: a marca tem que ser a mesma dos dois lados */
  .selo{width:36px;height:36px;flex:0 0 auto;border-radius:10px;display:grid;place-items:center;
    font:600 13px/1 var(--mono);letter-spacing:.5px;color:oklch(0.98 0.01 265);
    background:linear-gradient(150deg,var(--ion),var(--ion2));
    box-shadow:inset 0 1px 0 oklch(1 0 0/.35),0 0 18px color-mix(in oklch,var(--ion) 50%,transparent)}
  h1{margin:0;font-size:17px;font-weight:600;letter-spacing:-.1px}
  .sub{margin:2px 0 0;font-family:var(--mono);font-size:10.5px;letter-spacing:2px;
    text-transform:uppercase;color:var(--ion)}
  label{display:block;font-size:12.5px;color:var(--tx2);margin-bottom:7px}
  /* campo nao herda fonte por padrao: sem `font-family:inherit` o texto e o placeholder
     saiam na fonte do sistema, e so ali a pagina deixava de ser Plex */
  input{width:100%;padding:13px 14px;border-radius:12px;font-family:inherit;font-size:16px;
    border:1px solid oklch(1 0 0/.14);background:oklch(0.05 0.016 265/.72);color:var(--tx);
    box-shadow:inset 0 1px 2px oklch(0 0 0/.5);
    transition:border-color .16s,box-shadow .16s}
  input::placeholder{color:var(--mut);font-family:inherit;opacity:1}
  input:focus-visible{outline:0;border-color:var(--ion);
    box-shadow:inset 0 1px 2px oklch(0 0 0/.5),0 0 0 3px color-mix(in oklch,var(--ion) 28%,transparent)}
  /* acao = chama (DESIGN v9): o unico laranja da tela, sobre uma cena toda ion */
  button{width:100%;margin-top:14px;padding:14px;border:0;border-radius:12px;cursor:pointer;
    font:600 15px/1 "Plex",system-ui,sans-serif;color:var(--flame-ink);
    background:linear-gradient(180deg,var(--flame),var(--flame2));
    box-shadow:inset 0 1px 0 oklch(1 0 0/.40),0 8px 22px color-mix(in oklch,var(--flame) 30%,transparent);
    transition:filter .16s,transform .1s,box-shadow .16s}
  button:hover{filter:brightness(1.06);box-shadow:inset 0 1px 0 oklch(1 0 0/.40),0 10px 30px color-mix(in oklch,var(--flame) 45%,transparent)}
  button:active{transform:translateY(1px)}
  button:focus-visible{outline:2px solid var(--flame);outline-offset:3px}
  button[aria-busy=true]{pointer-events:none;filter:saturate(.6) brightness(.9)}
  button[aria-busy=true] .rot{display:inline-block;width:12px;height:12px;margin-right:8px;
    vertical-align:-1px;border:2px solid oklch(0.21 0.05 50/.35);border-top-color:var(--flame-ink);border-radius:50%;
    animation:gira .7s linear infinite}
  @keyframes gira{to{transform:rotate(1turn)}}
  /* erro com borda inteira e tinta — sem faixa lateral, sem cor sozinha */
  .err{margin:14px 0 0;padding:9px 12px;border-radius:10px;font-size:13px;line-height:1.4;
    border:1px solid color-mix(in oklch,var(--rose) 50%,transparent);
    background:color-mix(in oklch,var(--rose) 16%,oklch(0.08 0.02 265/.6));color:oklch(0.86 0.10 18)}
  .err:empty{display:none}                      /* sem espaco reservado a vazio */
  .foot{margin:18px 0 0;font-size:11.5px;line-height:1.5;color:var(--mut);text-align:center}
  .vh{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
    clip-path:inset(50%);white-space:nowrap}

  /* sem vidro (preferencia do sistema ou navegador sem backdrop-filter): cartao solido */
  @media (prefers-reduced-transparency:reduce){
    .card{-webkit-backdrop-filter:none;backdrop-filter:none;background:var(--surf)}}
  @supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){
    .card{background:oklch(0.10 0.021 265/.94)}}
  @media (prefers-reduced-motion:reduce){
    *{animation-duration:.01ms!important;transition-duration:.01ms!important}
    .fundo video{display:none}
    button:active{transform:none}}

  /* == PAISAGEM / DESKTOP ===============================================
     Na peca 16:9 o reator mora a DIREITA e a esquerda e escuro: o cartao
     vai para a esquerda e a cena fica inteira a vista.                   */
  @media (min-aspect-ratio:1/1) and (min-width:820px){
    body{justify-items:start;padding:24px clamp(24px,9vw,170px)}
    .fundo img,.fundo video{object-position:62% 40%}
    .fundo::after{background:
      linear-gradient(90deg,oklch(0.035 0.014 265/.80) 0%,oklch(0.035 0.014 265/.55) 32%,oklch(0.035 0.014 265/.12) 62%,oklch(0.035 0.014 265/.28) 100%),
      linear-gradient(180deg,transparent 55%,oklch(0.035 0.014 265/.55) 100%)}}

  /* == TELEFONE (retrato) ===============================================
     Na peca 9:16 o reator ocupa o terco de cima: o cartao desce para a
     metade de baixo, onde a peca e o chao escuro do grid, e o reator fica
     inteiro acima dele — a abertura e o assunto, o cartao e o pouso.    */
  @media (max-aspect-ratio:1/1){
    body{align-items:end;padding:24px 16px max(28px,env(safe-area-inset-bottom))}
    .card{padding:26px 22px 22px}
    .sub{font-size:9.5px;letter-spacing:1.3px;text-wrap:balance}}
  @media (max-aspect-ratio:1/1) and (max-height:640px){body{align-items:center}}
</style></head><body>
<div class=fundo aria-hidden=true>
  <picture>
    <source media="(min-aspect-ratio:1/1)" srcset=/static/login/login-169.jpg>
    <img src=/static/login/login-916.jpg alt="" decoding=async fetchpriority=high
      onerror="document.documentElement.classList.add('sem-poster')">
  </picture>
  <video muted loop playsinline disablepictureinpicture preload=none tabindex=-1></video>
</div>
<form class=card method=post action=/login_jfn>
  <div class=marca><div class=selo aria-hidden=true>CE</div>
    <div><h1>Controle Externo</h1><p class=sub>Central de Inteligência · RJ</p></div></div>
  <label for=senha>Senha de acesso</label>
  <input id=senha type=password name=senha autofocus autocomplete=current-password
    required aria-describedby=lgpd placeholder="digite para entrar">
  <div class=err role=alert>{{ERRO}}</div>
  <button type=submit><span class=rot aria-hidden=true></span>Entrar</button>
  <p class=foot id=lgpd>Acesso restrito · dados de auditoria
    <span class=vh>conforme</span> LGPD art. 7º, II</p>
</form>
<script>
  /* o botao dizia "Entrar" durante os segundos da checagem e parecia travado.
     aria-busy vira o estado, o texto conta o que esta acontecendo.            */
  document.querySelector('form').addEventListener('submit',e=>{
    const b=e.currentTarget.querySelector('button');
    b.setAttribute('aria-busy','true');
    b.lastChild.textContent='Verificando…';
  });
  /* O VIDEO DE FUNDO. Poster primeiro, sempre. O video so e pedido quando ha permissao para
     movimento E para gastar dados: reduced-motion e Save-Data ficam no poster, sem baixar um
     byte de video. Arquivo ausente (ainda nao publicado) = erro silencioso, fica o poster. */
  (function(){
    var raiz=document.documentElement,img=document.querySelector('.fundo img'),
        v=document.querySelector('.fundo video');
    if(img&&img.complete&&!img.naturalWidth)raiz.classList.add('sem-poster');
    if(!v||!window.matchMedia)return;
    var rm=matchMedia('(prefers-reduced-motion: reduce)'),larga=matchMedia('(min-aspect-ratio: 1/1)'),
        c=navigator.connection,
        poupa=!!(c&&c.saveData)||matchMedia('(prefers-reduced-data: reduce)').matches;
    function parar(){v.classList.remove('on');v.pause();v.removeAttribute('src');try{v.load()}catch(_){}}
    function ligar(){
      if(rm.matches||poupa){parar();return;}
      var src=window.JFN_LOGIN_V61?'/static/login/v61/fluxo'+(matchMedia('(max-width:760px)').matches?'-m':'')+'.mp4'
              :'/static/login/login-'+(larga.matches?'169':'916')+'.mp4';
      if(v.getAttribute('src')===src)return;
      v.classList.remove('on');v.src=src;
      var p=v.play();if(p&&p.catch)p.catch(function(){});
    }
    v.addEventListener('playing',function(){v.classList.add('on')});
    v.addEventListener('error',function(){v.classList.remove('on')});
    function ouvir(m){if(m.addEventListener)m.addEventListener('change',ligar);else if(m.addListener)m.addListener(ligar);}
    ouvir(rm);ouvir(larga);
    document.addEventListener('visibilitychange',function(){
      if(document.hidden)v.pause();else if(v.getAttribute('src')){var p=v.play();if(p&&p.catch)p.catch(function(){});}});
    ligar();
  })();
</script></body></html>"""


@app.get("/login_jfn", response_class=HTMLResponse)
async def login_jfn_form(erro: int = 0):
    msg = "Senha incorreta." if erro else ""
    return HTMLResponse(_LOGIN_HTML.replace("{{ERRO}}", msg))


@app.middleware("http")
async def _cabecalhos_seguranca(request: Request, call_next):
    resp = await call_next(request)
    for k, v in _SEC_HDRS.items():
        resp.headers.setdefault(k, v)
    return resp


@app.post("/login_jfn")
async def login_jfn_post(request: Request, senha: str = Form("")):
    ip = request.client.host if request.client else ""
    agora = time.time()
    falhas = [t for t in _LOGIN_FALHAS.get(ip, []) if agora - t < _LOGIN_JANELA]
    if len(falhas) >= _LOGIN_MAX:
        _LOGIN_FALHAS[ip] = falhas
        return HTMLResponse("Muitas tentativas. Aguarde 15 minutos.", status_code=429)
    if _DASH_SENHA and hmac.compare_digest(senha.encode(), _DASH_SENHA.encode()):
        _LOGIN_FALHAS.pop(ip, None)
        resp = RedirectResponse("/painel", status_code=303)
        resp.set_cookie(_DASH_COOKIE, _dash_token(), max_age=_DASH_TTL,
                        httponly=True, samesite="lax", secure=_DASH_COOKIE_SECURE)
        return resp
    _LOGIN_FALHAS[ip] = falhas + [agora]
    return RedirectResponse("/login_jfn?erro=1", status_code=303)


@app.get("/logout_jfn")
async def logout_jfn():
    resp = RedirectResponse("/login_jfn", status_code=303)
    resp.delete_cookie(_DASH_COOKIE)
    return resp


# O bump de `?v=<hash>` no HTML não chegava a ninguém: o HTML que CARREGA esses links vinha do
# cache do navegador (só etag/last-modified, sem Cache-Control — o Chrome então usa heurística e
# nem revalida). Medido pelo it-campo: painel.js?v=66af4ca4 sobreviveu ao bump até um ?cb=1 na URL.
# `no-cache` NÃO é "não guarde": é "guarde, mas revalide sempre" — o 304 continua barato.
_HTML_REVALIDA = {"Cache-Control": "no-cache"}


@app.get("/", response_class=HTMLResponse)
async def index():
    """Painel JFN unificado (mobile-first, dark): visão geral, alertas, SIAFE, sweeps + atalhos. Antigo hub em static/painel.html (aposentado)."""
    return FileResponse("static/jfn-painel.html", headers=_HTML_REVALIDA)


@app.get("/auditoria", response_class=HTMLResponse)
async def auditoria_ui():
    """Painel de Auditoria Financeira (KPIs, alertas, OBs, favorecidos, /relatorio + Lex)."""
    return FileResponse("static/dashboard.html", headers=_HTML_REVALIDA)


@app.get("/painel", response_class=HTMLResponse)
async def painel_fiscalizacao():
    """Painel de fiscalização unificado (leve, Tailwind): visão geral, auditoria/alertas, SIAFE, sweeps, cartel."""
    return FileResponse("static/jfn-painel.html", headers=_HTML_REVALIDA)


@app.get("/cockpit")
async def cockpit():
    """Unificado no painel v6 (aba Início = command deck); a página separada foi aposentada."""
    return RedirectResponse("/painel", status_code=308)


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
    """Check agent status — SEM acordar o browser. `get_agent()` aqui LANÇAVA o Chromium e marcava
    "uso" a cada poll do painel/Yoda, e o guard de idle de 15 min nunca disparava (medido 10/09:
    Chromium do servidor vivo 2,8 h sem nenhuma leitura). Status é observação, não uso."""
    agent = _agent
    if agent is None:
        return {"logged_in": False, "username": os.environ.get("SIAFE_USER", ""),
                "exercicio": os.environ.get("SIAFE_EXERCICIO") or str(__import__('datetime').date.today().year),
                "extracted_records": 0, "browser": "ocioso (relança na próxima leitura)"}
    return {
        "logged_in": agent._siafe._logged_in,
        "username": agent._siafe_username,
        "exercicio": agent._siafe_exercicio or str(__import__('datetime').date.today().year),
        "extracted_records": len(agent._extracted_data),
        "browser": "ativo",
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
        except Exception as exc:
            logger.debug("falha ao enviar %s no WebSocket /ws: %s", msg_type, exc)


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

    except WebSocketDisconnect as exc:
        logger.debug("cliente desconectou do WebSocket /ws: %s", exc)
    except Exception as e:
        try:
            await ws.send_text(json.dumps({"type": "error", "content": str(e)}))
        except Exception as exc:
            logger.debug("falha ao enviar erro no WebSocket /ws já fechado: %s", exc)


def parse_args():
    parser = argparse.ArgumentParser(description="SIAFE2 Finance Agent — Servidor Web")
    parser.add_argument("--host", default="0.0.0.0", help="Host (padrão: 0.0.0.0 = acessível na rede)")
    parser.add_argument("--port", type=int, default=8000, help="Porta (padrão: 8000)")
    parser.add_argument("--visible", action="store_true", help="Browser visível no PC")
    return parser.parse_args()


# ── Split 2026-07-06: rotas por domínio (ver rotas/*.py; rede de segurança em tests/test_server_snapshot.py) ──
# `vinculos` entrou em módulo próprio (2026-07-29): investigacao.py já tinha 2.291 linhas e 98
# rotas, e o eixo de vínculos é um domínio inteiro — somar ali só pioraria o problema.
from rotas import hermes as _r_hermes, produtos as _r_produtos, sistema as _r_sistema, investigacao as _r_investigacao, vinculos as _r_vinculos, lai as _r_lai, acervo as _r_acervo, comissao as _r_comissao, governo_couto as _r_governo_couto  # noqa: E402

for _r in (_r_hermes, _r_produtos, _r_sistema, _r_investigacao, _r_vinculos, _r_lai, _r_acervo, _r_comissao,
           _r_governo_couto):
    app.include_router(_r.router)

# v61 (2026-11-11): território — o router mora junto do motor (`compliance_agent/territorio/`), só lê
# `data/territorio.db`. Autenticação = a do middleware `_auth_jfn`, como todo `/api/*`.
from compliance_agent.territorio import api as _r_territorio  # noqa: E402

app.include_router(_r_territorio.router)

# v61: AO VIVO — estado dos motores (systemd, travas, logs por lista branca) e o fio SSE. Só leitura.
from compliance_agent.aovivo import api as _r_aovivo  # noqa: E402

app.include_router(_r_aovivo.router)


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

