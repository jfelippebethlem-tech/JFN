"""
Hermes Goal Agent — o auditor autônomo guiado por MISSÃO.

Funciona como o `/goal` do Claude: você dá uma missão e ele trabalha sozinho,
em ciclos, sem parar a cada passo para perguntar. A cada ciclo ele:

  1. PENSA (Hermes-3 / melhor LLM grátis) qual é a melhor próxima ação
  2. AGE usando uma ferramenta (abrir/dirigir Chrome 9222, coletar SIAFE/DOERJ,
     investigar empresa, listar alertas, aprender algo…)
  3. OBSERVA o resultado
  4. APRENDE (memória persistente sobre os casos)
  5. Repete até concluir a missão ou atingir o limite de passos do ciclo

Protocolo de ação em JSON (model-agnostic — não depende de tool-calling nativo):
    {"pensamento": "...", "acao": "<nome>", "args": {...}}
    {"pensamento": "...", "acao": "concluir", "resumo": "..."}

A missão fica salva na memória (categoria "missao"), então sobrevive a
reinícios — o agente retoma de onde parou.
"""

import asyncio
import json
import os
import platform
import re
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()

CDP_URL = "http://127.0.0.1:9222"
SIAFE_HOME = "https://siafe2.fazenda.rj.gov.br/Siafe/"

# Limites de segurança do ciclo autônomo
MAX_PASSOS_POR_CICLO = int(os.environ.get("HERMES_MAX_PASSOS", "8"))


# ─── Ferramentas de sistema: abrir e checar o Chrome debug 9222 ───────────────

async def chrome_disponivel() -> bool:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{CDP_URL}/json/version")
            return r.status_code == 200
    except Exception:
        return False


def _achar_chrome() -> Optional[str]:
    """Localiza o executável do Chrome no Windows/Linux/Mac."""
    candidatos = []
    if platform.system() == "Windows":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env, "")
            if base:
                candidatos.append(Path(base) / "Google/Chrome/Application/chrome.exe")
    else:
        candidatos += [Path(p) for p in (
            "/usr/bin/google-chrome", "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )]
    for c in candidatos:
        if c and Path(c).exists():
            return str(c)
    for nome in ("google-chrome", "chrome", "chromium", "chromium-browser"):
        achado = shutil.which(nome)
        if achado:
            return achado
    return None


async def abrir_chrome_debug(url: str = SIAFE_HOME) -> dict:
    """
    Abre o Chrome no modo debug (porta 9222) apontando para o SIAFE.
    Se já estiver no ar, não reabre. É a forma do Hermes 'aprender a clicar'
    no Chrome: a partir daqui ele dirige a aba via CDP.
    """
    if await chrome_disponivel():
        return {"ok": True, "ja_estava": True, "msg": "Chrome debug já estava no ar (9222)."}

    exe = _achar_chrome()
    if not exe:
        return {"ok": False, "erro": "Chrome não encontrado no sistema."}

    # Perfil exclusivo do JFN — força nova instância independente do Chrome normal.
    # Usar o perfil padrão faz Chrome reutilizar processo existente e ignorar --remote-debugging-port.
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", str(Path.home()))
        perfil = str(Path(base) / "JFN" / "ChromeDebug")
    else:
        perfil = str(Path.home() / ".config" / "jfn-chrome-debug")

    args = [
        exe,
        "--remote-debugging-port=9222",
        f"--user-data-dir={perfil}",
        "--no-first-run",
        "--no-default-browser-check",
        url,
    ]
    try:
        kwargs = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    except Exception as e:
        return {"ok": False, "erro": f"falha ao abrir Chrome: {e}"}

    # Espera subir a porta (até ~30s)
    for _ in range(15):
        await asyncio.sleep(2)
        if await chrome_disponivel():
            return {"ok": True, "ja_estava": False, "msg": f"Chrome debug aberto (perfil: {perfil})."}
    return {"ok": False, "erro": "Chrome aberto mas a porta 9222 não respondeu a tempo."}


async def _aba_siafe(browser):
    """Acha a aba do SIAFE no Chrome conectado, ou usa a primeira disponível."""
    for ctx in browser.contexts:
        for pg in ctx.pages:
            if "siafe2.fazenda" in pg.url.lower():
                return pg
    if browser.contexts and browser.contexts[0].pages:
        return browser.contexts[0].pages[0]
    return None


async def navegar_e_ler(url: str = "", clicar_texto: str = "") -> dict:
    """
    Conecta no Chrome 9222 e: navega para `url` (se dado), clica no link/botão
    cujo texto casa com `clicar_texto` (se dado), e devolve título + amostra do
    texto + links visíveis. É como o Hermes 'enxerga e clica' no navegador.
    """
    if not await chrome_disponivel():
        return {"ok": False, "erro": "Chrome 9222 indisponível. Use a ação abrir_chrome antes."}

    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    try:
        browser = await p.chromium.connect_over_cdp(CDP_URL, timeout=30000)
        page = await _aba_siafe(browser)
        if not page:
            return {"ok": False, "erro": "Nenhuma aba encontrada no Chrome."}

        if url:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

        clicou = ""
        if clicar_texto:
            clicou = await page.evaluate(
                """(alvo) => {
                    const norm = s => (s||'').trim().toLowerCase();
                    for (const el of document.querySelectorAll('a, button, span, td, li')) {
                        const r = el.getBoundingClientRect();
                        if (r.width<=0 || r.height<=0) continue;
                        if (norm(el.textContent).includes(norm(alvo))) { el.click(); return el.textContent.trim().slice(0,60); }
                    }
                    return '';
                }""",
                clicar_texto,
            )
            await asyncio.sleep(2.5)

        dump = await page.evaluate(
            """() => {
                const links = [];
                for (const a of document.querySelectorAll('a[href]')) {
                    const t=(a.textContent||'').trim();
                    if (t) links.push(t.slice(0,60));
                }
                return {
                    url: location.href,
                    title: document.title,
                    texto: (document.body?document.body.innerText:'').slice(0,2500),
                    links: links.slice(0,40),
                };
            }"""
        )
        dump["ok"] = True
        dump["clicou"] = clicou
        return dump
    except Exception as e:
        return {"ok": False, "erro": f"{type(e).__name__}: {e}"}
    finally:
        try:
            await p.stop()
        except Exception:
            pass


# ─── O agente guiado por missão ───────────────────────────────────────────────

_SYSTEM_GOAL = (
    "Você é o HERMES, auditor-chefe autônomo do sistema JFN, que fiscaliza as "
    "finanças do Estado do Rio de Janeiro (SIAFE2 + Diário Oficial). Você recebeu "
    "uma MISSÃO e trabalha sozinho até cumpri-la, escolhendo a melhor próxima ação "
    "a cada passo. Você NÃO pede permissão — você age, observa e aprende.\n\n"
    "FERRAMENTAS DISPONÍVEIS (campo 'acao'):\n"
    "  abrir_chrome        — abre/garante o Chrome debug 9222 no SIAFE\n"
    "  status_chrome       — verifica se o Chrome 9222 está no ar\n"
    "  coletar_siafe       — coleta as Ordens Bancárias do dia no SIAFE2\n"
    "  coletar_doerj       — coleta as publicações do Diário Oficial do dia\n"
    "  navegar             — args {url?, clicar?}: navega/clica e lê a página no Chrome\n"
    "  investigar          — args {nome?, cnpj?}: investiga uma empresa/pessoa a fundo\n"
    "  listar_alertas      — lista os alertas de compliance recentes\n"
    "  aprender            — args {chave, licao}: salva um aprendizado na memória\n"
    "  lembrar             — args {termo}: recupera o que já se sabe sobre um tema\n"
    "  concluir            — encerra o ciclo: args {resumo}\n\n"
    "REGRAS:\n"
    "  • Responda SEMPRE com UM objeto JSON, nada mais.\n"
    "  • Formato: {\"pensamento\": \"raciocínio curto\", \"acao\": \"<nome>\", \"args\": {…}}\n"
    "  • Se a missão exige dados do SIAFE/DOERJ e o Chrome não está no ar, comece por abrir_chrome.\n"
    "  • Quando não houver mais ação útil agora, use 'concluir' com um resumo do que fez e aprendeu.\n"
    "  • Seja objetivo e priorize ações que produzam resultado concreto (dados, alertas, aprendizados)."
)


class HermesGoalAgent:
    """Auditor autônomo guiado por missão, com memória persistente."""

    def __init__(self, session=None):
        from compliance_agent.database.models import get_session, init_db
        init_db()
        self.session = session or get_session()
        self._compliance = None  # ComplianceAgent sob demanda (tem as 22 ferramentas)
        self._historico_ciclo: list[dict] = []

    # ── Missão persistente (estilo /goal) ───────────────────────────────────

    def definir_missao(self, texto: str) -> None:
        # Sobrescreve SEMPRE (trocar por missão mais curta também deve valer).
        from compliance_agent.database.models import MemoriaAprendizado
        from datetime import datetime as _dt
        item = (self.session.query(MemoriaAprendizado)
                .filter_by(categoria="missao", chave="atual").first())
        if item:
            item.valor = texto
            item.fonte = "usuario"
            item.ultima_vez = _dt.utcnow()
            item.n_observacoes = (item.n_observacoes or 0) + 1
        else:
            self.session.add(MemoriaAprendizado(
                categoria="missao", chave="atual", valor=texto,
                confianca=1.0, n_observacoes=1, fonte="usuario"))
        self.session.commit()
        console.print(f"[green]🎯 Missão definida:[/green] {texto[:120]}")

    def missao_atual(self) -> str:
        from compliance_agent.llm.memoria import lembrar
        m = lembrar("missao", chave="atual", session=self.session)
        return m[0]["valor"] if m else ""

    def limpar_missao(self) -> None:
        from compliance_agent.database.models import MemoriaAprendizado
        self.session.query(MemoriaAprendizado).filter_by(
            categoria="missao", chave="atual").delete()
        self.session.commit()

    # ── Execução de uma ação ─────────────────────────────────────────────────

    async def _compliance_agent(self):
        if self._compliance is None:
            from compliance_agent.agent import ComplianceAgent
            self._compliance = ComplianceAgent()
        return self._compliance

    async def executar_acao(self, acao: str, args: dict) -> dict:
        try:
            if acao == "abrir_chrome":
                return await abrir_chrome_debug()

            if acao == "status_chrome":
                return {"ok": True, "chrome_9222": await chrome_disponivel()}

            if acao == "coletar_siafe":
                from compliance_agent.collectors.siafe_ob import run_daily_collection
                r = await run_daily_collection(date.today(), collect_details=True)
                return {"ok": True, "obs_salvas": r.get("records_saved", 0),
                        "erros": r.get("errors", [])[:3]}

            if acao == "coletar_doerj":
                from compliance_agent.collectors.doerj import DOERJCollector
                pubs = await DOERJCollector(self.session).coletar_hoje()
                return {"ok": True, "publicacoes": len(pubs)}

            if acao == "navegar":
                return await navegar_e_ler(args.get("url", ""), args.get("clicar", ""))

            if acao == "investigar":
                from compliance_agent.collectors.web_research import investigar
                dossie = await investigar(args.get("nome", ""), args.get("cnpj", ""))
                return {"ok": True, "resumo": dossie.get("resumo", "")[:600],
                        "riscos": dossie.get("riscos_detectados", [])}

            if acao == "listar_alertas":
                from compliance_agent.database.models import Alerta
                q = (self.session.query(Alerta)
                     .order_by(Alerta.created_at.desc()).limit(15).all())
                return {"ok": True, "alertas": [
                    {"tipo": a.tipo, "sev": a.severidade, "titulo": a.titulo[:120]} for a in q
                ]}

            if acao == "aprender":
                from compliance_agent.llm.memoria import aprender
                aprender("licao", (args.get("chave") or "licao")[:200],
                         args.get("licao", ""), fonte="hermes_goal",
                         delta_confianca=0.15, session=self.session)
                return {"ok": True, "msg": "aprendizado salvo na memória"}

            if acao == "lembrar":
                from compliance_agent.llm.memoria import lembrar
                mems = lembrar("licao", chave=args.get("termo", ""), session=self.session)
                mems += lembrar("padrao_fraude", chave=args.get("termo", ""), session=self.session)
                return {"ok": True, "memorias": [m["valor"][:200] for m in mems[:6]]}

            return {"ok": False, "erro": f"ação desconhecida: {acao}"}
        except Exception as e:
            return {"ok": False, "erro": f"{type(e).__name__}: {e}"}

    # ── Ciclo autônomo (estilo /goal: trabalha sem parar) ────────────────────

    async def _pensar(self, contexto: str) -> dict:
        """Pede ao Hermes a próxima ação em JSON."""
        from compliance_agent.llm.hermes_agent import _hermes
        raw = await _hermes(_SYSTEM_GOAL, contexto, max_tokens=600)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return {"acao": "concluir", "resumo": "sem ação clara", "pensamento": raw[:200]}
        try:
            return json.loads(m.group())
        except Exception:
            return {"acao": "concluir", "resumo": "JSON inválido", "pensamento": raw[:200]}

    async def trabalhar(self, max_passos: int = MAX_PASSOS_POR_CICLO,
                        on_step=None) -> dict:
        """
        Executa um ciclo autônomo rumo à missão. Não bloqueia pedindo permissão.
        `on_step(passo_dict)` é chamado a cada passo (para UI ao vivo).
        Retorna {missao, passos, resumo}.
        """
        from compliance_agent.llm.memoria import contexto_para_prompt, aprender

        missao = self.missao_atual()
        if not missao:
            return {"ok": False, "erro": "Nenhuma missão definida. Use definir_missao()."}

        self._historico_ciclo = []
        passos = []
        chrome_ok = await chrome_disponivel()
        conhecimento = contexto_para_prompt(self.session, max_itens=12)

        for i in range(max_passos):
            historico_txt = "\n".join(
                f"- {p['acao']}: {json.dumps(p['resultado'], ensure_ascii=False)[:180]}"
                for p in passos[-5:]
            ) or "(nenhuma ação ainda)"

            contexto = (
                f"MISSÃO: {missao}\n\n"
                f"Chrome debug 9222 no ar: {'sim' if chrome_ok else 'não'}\n"
                f"Data de hoje: {date.today().isoformat()}\n\n"
                f"CONHECIMENTO ACUMULADO:\n{conhecimento}\n\n"
                f"AÇÕES JÁ EXECUTADAS NESTE CICLO:\n{historico_txt}\n\n"
                f"Qual a próxima ação? Responda só com JSON."
            )

            decisao = await self._pensar(contexto)
            acao = (decisao.get("acao") or "concluir").strip()
            args = decisao.get("args") or {}
            pensamento = decisao.get("pensamento", "")

            if acao == "concluir":
                resumo = decisao.get("resumo", pensamento or "ciclo concluído")
                aprender("licao", f"ciclo_{datetime.now():%Y%m%d_%H%M}",
                         f"Missão '{missao[:80]}' — {resumo[:300]}",
                         fonte="hermes_goal", session=self.session)
                passo = {"acao": "concluir", "pensamento": pensamento,
                         "resultado": {"resumo": resumo}}
                passos.append(passo)
                if on_step:
                    await _maybe_await(on_step, passo)
                break

            resultado = await self.executar_acao(acao, args)
            if acao == "abrir_chrome" or acao == "status_chrome":
                chrome_ok = await chrome_disponivel()

            passo = {"acao": acao, "args": args, "pensamento": pensamento,
                     "resultado": resultado}
            passos.append(passo)
            self._historico_ciclo.append(passo)
            if on_step:
                await _maybe_await(on_step, passo)

        return {
            "ok": True,
            "missao": missao,
            "passos": passos,
            "n_passos": len(passos),
            "resumo": passos[-1]["resultado"].get("resumo", "") if passos else "",
        }

    # ── Conversa (chat livre com o Hermes, com todo o contexto) ──────────────

    async def conversar(self, pergunta: str) -> str:
        from compliance_agent.llm.hermes_agent import responder_hermes
        contexto_db = self._snapshot_db()
        return await responder_hermes(pergunta, contexto_db, self.session)

    def _snapshot_db(self) -> str:
        from compliance_agent.database.models import OrdemBancaria, Alerta
        try:
            n_obs = self.session.query(OrdemBancaria).count()
            n_alt = self.session.query(Alerta).count()
            ult = (self.session.query(Alerta)
                   .order_by(Alerta.created_at.desc()).limit(5).all())
            linhas = [f"Banco: {n_obs} OBs, {n_alt} alertas.",
                      "Últimos alertas:"]
            for a in ult:
                linhas.append(f"- [{a.severidade}] {a.titulo[:100]}")
            return "\n".join(linhas)
        except Exception:
            return "Banco indisponível."


async def _maybe_await(fn, arg):
    r = fn(arg)
    if asyncio.iscoroutine(r):
        await r


# ─── Loop contínuo: persegue a missão permanente em background ────────────────

async def loop_hermes_goal():
    """
    7º loop do scheduler. Se houver uma missão definida, o Hermes trabalha nela
    em ciclos espaçados (respeitando o rate-limit do LLM grátis). Sem missão,
    apenas aguarda. É isto que faz o /goal 'não parar toda hora'.
    """
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.llm.free_llm import openrouter_available, groq_available
    from compliance_agent.notifications.telegram import enviar_mensagem

    if not (openrouter_available() or groq_available()):
        console.print("[yellow]Hermes Goal: sem LLM grátis configurado — desligado.[/yellow]")
        return

    console.print("[green]🎯 Hermes Goal Agent ativo — perseguindo a missão em background.[/green]")
    init_db()
    INTERVALO = int(os.environ.get("HERMES_GOAL_INTERVALO", "900"))  # 15 min entre ciclos

    while True:
        session = get_session()
        try:
            agente = HermesGoalAgent(session=session)
            missao = agente.missao_atual()
            if missao:
                console.print(f"[cyan]🎯 Trabalhando na missão: {missao[:80]}[/cyan]")
                resultado = await agente.trabalhar()
                resumo = resultado.get("resumo", "")
                if resumo:
                    try:
                        await enviar_mensagem(
                            f"🎯 *Hermes avançou na missão*\n"
                            f"_{missao[:100]}_\n\n"
                            f"Passos: {resultado.get('n_passos',0)}\n"
                            f"{resumo[:400]}"
                        )
                    except Exception:
                        pass
            else:
                console.print("[dim]Hermes Goal: nenhuma missão definida. Use /missao no Telegram ou o painel.[/dim]")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            console.print(f"[yellow]Hermes Goal loop: {e}[/yellow]")
        finally:
            session.close()
        await asyncio.sleep(INTERVALO)
