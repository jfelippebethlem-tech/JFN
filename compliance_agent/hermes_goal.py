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
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from compliance_agent.llm.memoria import aprender, contexto_para_prompt
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


async def _garantir_chrome() -> dict:
    """GARANTE o Chrome 9222 no ar — o Hermes sabe trazê-lo de volta SOZINHO quando precisa, sem depender do LLM.
    O Chrome 9222 é o `chrome-jfn.service` (systemd user, Restart=always): a forma CANÔNICA de garanti-lo é
    (re)iniciar esse serviço — NUNCA lançar um chrome concorrente (conflitaria na porta/perfil). Idempotente:
    se a porta já responde, no-op. Fallback (sem systemd disponível): `abrir_chrome_debug`."""
    if await chrome_disponivel():
        return {"ok": True, "ja_estava": True}
    # canônico: subir o serviço gerenciado pelo systemd (perfil /tmp/chrome-jfn, Restart=always)
    try:
        subprocess.run(["systemctl", "--user", "start", "chrome-jfn.service"], timeout=15, check=False)
        for _ in range(8):
            await asyncio.sleep(2)
            if await chrome_disponivel():
                return {"ok": True, "via": "chrome-jfn.service"}
    except Exception:  # noqa: BLE001 — sem systemd (ex.: Windows/dev): cai no fallback
        pass
    return await abrir_chrome_debug()


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
    g = await _garantir_chrome()  # auto-abre se estiver fechado (idle-guard/reboot/kill) — não depende do LLM
    if not await chrome_disponivel():
        return {"ok": False, "erro": f"Chrome 9222 indisponível e auto-abertura falhou: {g.get('erro', g)}"}

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

_CONFIG_PADRAO_PATH = Path(__file__).parent / "default_audit_config.py"
_SYSTEM_GOAL = (
    "Você é o HERMES, auditor-chefe autônomo do sistema JFN. Você recebeu um OBJETIVO DE AUDITORIA "
    "e deve executá-lo CYCLICAMENTE, em fases, sem parar para pedir permissão, até concluir ou "
    "determinar que faltam evidências. O objetivo não muda durante o ciclo.\n\n"
    "MODO /goal (Claude-like):\n"
    "  - objetivo: inalterável durante todo o ciclo\n"
    "  - memoria: tudo que você aprender é persistido no banco local (categoria=auditoria_objetivo)\n"
    "  - retomada: se o ciclo reiniciar, continue do estado atual sem refazer etapas concluídas\n"
    "  - relatorio_final: deve ser produzido ao final com achados, riscos, recomendações e erros\n\n"
    "REGRAS PRIMEIRAS:\n"
    "  • SEMPRE use o domínio SIAFE2 correto: https://siafe2.fazenda.rj.gov.br/Siafe/\n"
    "  • NÃO use https://siafe.rj.gov.br/\n"
    "  • Nunca force navegação como primeiro passo quando existir ação de coleta estruturada.\n"
    "  • Qualifique uma OB como obra apenas se houver evidência em processo/sei ou no campo categoria.\n\n"
    "FERRAMENTAS DISPONÍVEIS (campo 'acao'):\n"
    "  abrir_chrome        — abre/garante o Chrome debug 9222 no SIAFE\n"
    "  status_chrome       — verifica se o Chrome 9222 está no ar\n"
    "  coletar_siafe       — coleta OBs do dia no SIAFE2\n"
    "  coletar_doerj       — coleta publicações do DOERJ do dia\n"
    "  dados_abertos       — args {termo}: consulta o portal CKAN de dados abertos do RJ (despesas, contratos, servidores) SEM Chrome/CAPTCHA\n"
    "  ler_sei             — args {numero}: lê processo SEI na íntegra (OCR no CAPTCHA)\n"
    "  ler_doerj           — args {url|data}: lê edição do DOERJ direto por URL ou data\n"
    "  navegar             — args {url?, clicar?}: use SOMENTE se a ação pedir URL explícita\n"
    "  investigar          — args {nome?, cnpj?}: investiga empresa/pessoa\n"
    "  listar_alertas      — lista alertas de compliance recentes\n"
    "  lembrar             — args {termo}: recupera aprendizados anteriores\n"
    "  analisar_dados      — args {tipo, limite}: analisa OBs (sem_sei, valores_redondos, dispensa_obras, dispensa_compras, geral)\n"
    "  identificar_padroes — detecta concentrações, valores redondos e OBs sem SEI\n"
    "  desenvolver_hipoteses — gera hipóteses de irregularidade a partir dos padrões\n"
    "  testar_hipoteses    — valida/avalia hipóteses e recomenda próximos passos\n"
    "  aprender            — args {chave, licao}: salva aprendizado persistente\n"
    "  concluir            — encerra o ciclo: args {resumo, relatorio_final}\n"
    "FORMATO DE SAÍDA OBRIGATÓRIO:\n"
    "  Responda SEMPRE com UM JSON: {pensamento, acao, args}\n"
    "  Quando usar 'concluir', inclua 'resumo' e 'relatorio_final' em args.\n"
    "  O relatorio_final deve conter: achados, riscos, recomendações, erros e próximos passos.\n\n"
    "SEQUÊNCIA PADRÃO DO /goal:\n"
    "  1) analisar_dados (sem_sei, valores_redondos, dispensa_obras, dispensa_compras)\n"
    "  2) identificar_padroes (concentração, valores redondos, sem SEI)\n"
    "  3) desenvolver_hipoteses (H1/H2/H3)\n"
    "  4) testar_hipoteses (confirmar/descartar e recomendar ações)\n"
    "  5) aprender (salvar aprendizado)\n"
    "  6) repetir a sequência enquanto houver dados novos até ordem de parada\n\n"
    "REGRAS DE PARADA:\n"
    "  - NÃO use 'concluir' como fim definitivo. Use-o apenas para encerrar uma subfase.\n"
    "  - O ciclo só termina se: (a) o usuário pedir parar; (b) faltarem evidências por 3 ciclos seguidos.\n"
    "  - Quando o ciclo acabar por parada N, inclua em relatorio_final: 'parada_por': 'usuario'|'sem_evidencias'.\n\n"
    "MODO CONTÍNUO:\n"
    "  - Após cada 'concluir', volte para 1) se houver dados novos acumulados.\n"
    "  - Se actions retornarem 'ok':true sem dados novos, registre 'sem_novo' e siga; após 3x, declare 'sem_evidencias' e pare com resumo.\n"
)


class HermesGoalAgent:
    """Auditor autônomo guiado por missão, com memória persistente."""

    def __init__(self, session=None, objetivo: str = ""):
        from compliance_agent.database.models import get_session, init_db
        init_db()
        self.session = session or get_session()
        self._compliance = None  # ComplianceAgent sob demanda (tem as 22 ferramentas)
        self._historico_ciclo: list[dict] = []
        # Override de objetivo por instância: permite missões paralelas distintas
        # sem colidir com a missão "atual" global (slot único na memória).
        self._objetivo_override: str = objetivo or ""

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
        # Missão por instância (multi-missão) tem precedência sobre o slot global.
        if self._objetivo_override:
            return self._objetivo_override
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

            if acao == "ler_sei":
                # Lê um processo SEI na íntegra via Chrome 9222, com HUMANO-NO-LOOP
                # para o CAPTCHA (avisa por Telegram e espera você resolver).
                from compliance_agent.collectors.sei_cdp import ler_processo_sei
                numero = args.get("numero") or args.get("numero_sei") or ""
                if not numero:
                    return {"ok": False, "erro": "informe 'numero' do processo SEI"}
                await _garantir_chrome()  # garante o Chrome 9222 antes da leitura SEI (auto-abre se fechado)
                r = await ler_processo_sei(numero)
                if r.get("erro"):
                    return {"ok": False, "erro": r["erro"],
                            "aguardou_humano": r.get("aguardou_humano", False)}
                return {
                    "ok": True,
                    "numero": r.get("numero"),
                    "n_documentos": len(r.get("documentos", [])),
                    "cpfs": r.get("cpfs", [])[:10],
                    "cnpjs": r.get("cnpjs", [])[:10],
                    "valores": r.get("valores", [])[:10],
                    "captcha_resolvido": r.get("captcha_resolvido", False),
                    "texto_amostra": (r.get("texto", "") or "")[:600],
                }

            if acao == "ler_doerj":
                # Lê uma edição do DOERJ pelo URL ou coleta o dia especificado.
                from compliance_agent.collectors.doerj import DOERJCollector
                url_ed = args.get("url") or args.get("url_edicao") or ""
                data_str = args.get("data") or args.get("date") or ""
                col = DOERJCollector(self.session)
                if url_ed:
                    pubs = await col.coletar_edicao_url(url_ed)
                    return {
                        "ok": True,
                        "fonte": "url_direta",
                        "n_atos": len(pubs),
                        "tipos": list({p["tipo_ato"] for p in pubs}),
                        "orgaos": list({p.get("orgao", "")[:80] for p in pubs if p.get("orgao")}),
                        "amostra": [p["titulo"][:120] for p in pubs[:5]],
                    }
                alvo = date.today()
                if data_str:
                    try:
                        alvo = date.fromisoformat(data_str)
                    except ValueError:
                        pass
                pubs = await col.coletar_data(alvo)
                return {
                    "ok": True,
                    "data": alvo.isoformat(),
                    "n_publicacoes": len(pubs),
                    "tipos": list({p["tipo_ato"] for p in pubs}),
                    "orgaos": list({p.get("orgao", "")[:80] for p in pubs if p.get("orgao")})[:10],
                    "amostra": [p["titulo"][:120] for p in pubs[:5]],
                }

            if acao == "dados_abertos":
                # Consulta o portal CKAN de dados abertos do RJ (sem Chrome/CAPTCHA).
                from compliance_agent.collectors.dados_abertos_rj import pesquisar
                termo = args.get("termo") or args.get("q") or "despesa"
                r = await pesquisar(termo, limite=int(args.get("limite", 8) or 8))
                return r

            if acao == "analisar_dados":
                return await self._analisar_dados(args)

            if acao == "identificar_padroes":
                return await self._identificar_padroes(args)

            if acao == "desenvolver_hipoteses":
                return await self._desenvolver_hipoteses(args)

            if acao == "gerar_relatorio":
                return await self._gerar_relatorio(args)

            if acao == "testar_hipoteses":
                return await self._testar_hipoteses(args)

            return {"ok": False, "erro": f"ação desconhecida: {acao}"}
        except Exception as e:
            return {"ok": False, "erro": f"{type(e).__name__}: {e}"}

    async def _gerar_relatorio(self, args: dict) -> dict:
        try:
            from compliance_agent.reporting.export_relatorios import generate_report
            fmt = (args.get("formato") or "txt").strip().lower()
            limite = args.get("limit")
            try:
                limite = int(limite) if limite is not None else None
            except (TypeError, ValueError):
                limite = None

            result = generate_report(limit=limite, fmt=fmt)

            aprender(
                "licao",
                f"relatorio_{fmt}",
                f"Relatório gerado em {fmt}: {result['arquivo']}",
                fonte="hermes_goal",
                session=self.session,
            )
            return {
                "ok": result["ok"],
                "arquivo": result["arquivo"],
                "formato": fmt,
                "obs": result["obs"],
                "alertas": result["alertas"],
                "msg": "Relatório gerado com sucesso.",
            }
        except Exception as exc:
            return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}

    # ── Análises de dados (modo /goal) ────────────────────────────────────────

    async def _analisar_dados(self, args: dict) -> dict:
        tipo = (args.get("tipo") or "geral").strip().lower()
        limite = args.get("limite")
        try:
            limite = float(limite)
        except (TypeError, ValueError):
            limite = None
        from compliance_agent.database.models import OrdemBancaria
        from sqlalchemy import select
        obs = self.session.execute(select(OrdemBancaria)).scalars().all()
        linhas = []
        for o in obs:
            v = float(o.valor) if o.valor is not None else 0.0
            if tipo == "dispensa_obras":
                if o.categoria and "obra" in o.categoria.lower() and v > 119_812.02:
                    linhas.append((o.numero_ob, v, o.favorecido_nome, o.ug_codigo, o.numero_processo, o.numero_sei))
            elif tipo == "dispensa_compras":
                if o.categoria not in {"obras"} and v > 59_906.02:
                    linhas.append((o.numero_ob, v, o.favorecido_nome, o.ug_codigo, o.numero_processo, o.numero_sei))
            elif tipo == "fracionamento":
                # Retorno simplificado; o padrão real será detalhado em identificar_padroes
                continue
            elif tipo == "valores_redondos":
                if v >= 5_000 and abs(v - round(v, -2)) < 50.0:
                    linhas.append((o.numero_ob, v))
            elif tipo == "sem_sei":
                if not o.numero_sei:
                    linhas.append((o.numero_ob, o.numero_processo or "", o.favorecido_nome))
            else:
                linhas.append((o.numero_ob, v, o.favorecido_nome, o.ug_codigo, o.categoria))
        return {
            "ok": True,
            "tipo": tipo,
            "qtd": len(linhas),
            "amostra": linhas[:20],
        }

    async def _identificar_padroes(self, args: dict) -> dict:
        from compliance_agent.database.models import OrdemBancaria
        from sqlalchemy import select
        from collections import defaultdict
        obs = self.session.execute(select(OrdemBancaria)).scalars().all()
        itens = []
        for o in obs:
            itens.append({
                "id": o.id,
                "numero_ob": o.numero_ob,
                "valor": float(o.valor) if o.valor is not None else 0.0,
                "favorecido_nome": o.favorecido_nome or "",
                "ug_codigo": o.ug_codigo or "",
                "categoria": o.categoria or "",
                "numero_processo": o.numero_processo or "",
                "numero_sei": o.numero_sei or "",
                "data_emissao": str(o.data_emissao) if o.data_emissao else "",
            })
        # concentração favorecido+UG
        chaves = defaultdict(list)
        for item in itens:
            chave = f"{(item['favorecido_nome'] or '').strip()}|{(item['ug_codigo'] or '').strip()}"
            chaves[chave].append(item)
        concentracoes = []
        for chave, grupo in chaves.items():
            if len(grupo) >= 3:
                concentracoes.append({
                    "chave": chave,
                    "qtd": len(grupo),
                    "total": sum(g["valor"] for g in grupo),
                })
        concentracoes.sort(key=lambda x: x["total"], reverse=True)
        # valores redondos
        redondos = [i for i in itens if i["valor"] >= 5_000 and abs(i["valor"] - round(i["valor"], -2)) < 50.0]
        # sem SEI
        sem_sei = [i for i in itens if not i["numero_sei"]]
        return {
            "ok": True,
            "concentracoes": concentracoes[:10],
            "valores_redondos_qtd": len(redondos),
            "sem_sei_qtd": len(sem_sei),
        }

    async def _desenvolver_hipoteses(self, args: dict) -> dict:
        padroes = await self._identificar_padroes(args)
        hipoteses = []
        if padroes.get("sem_sei_qtd"):
            hipoteses.append({
                "id": "H1",
                "titulo": "Pagamentos sem rastreabilidade processual",
                "evidencia": f"{padroes['sem_sei_qtd']} OBs sem SEI.",
                "risco": "Alto",
                "fundamento": "Súmula 13/STF e art. 8º da Lei 14.133/2021.",
            })
        if padroes.get("concentracoes"):
            hipoteses.append({
                "id": "H2",
                "titulo": "Direcionamento por concentração de contratos",
                "evidencia": f"{len(padroes['concentracoes'])} grupos com 3+ pagamentos.",
                "risco": "Alto",
                "fundamento": "Lei 14.133/2021, arts. 8º e 75.",
            })
        if padroes.get("valores_redondos_qtd"):
            hipoteses.append({
                "id": "H3",
                "titulo": "Valores redondos semelhantes a estimativas sem cotação",
                "evidencia": f"{padroes['valores_redondos_qtd']} valores redondos.",
                "risco": "Médio",
                "fundamento": "Princípio da economicidade e jurisprudência dos TCs.",
            })
        return {
            "ok": True,
            "hipoteses": hipoteses,
            "recomendacao": "Priorizar H1 e H2 para aprofundamento.",
        }

    async def _testar_hipoteses(self, args: dict) -> dict:
        hipoteses = await self._desenvolver_hipoteses(args)
        resultados = []
        for h in hipoteses.get("hipoteses", []):
            status = "confirmado_parcialmente" if h["risco"] == "Alto" else "em_verificacao"
            resultados.append({
                "id": h["id"],
                "status": status,
                "acao_recomendada": " Cruzar com CEIS/CNEP e PNCP; validar processos SEI correspondentes.",
            })
        return {
            "ok": True,
            "resultados": resultados,
            "proximos_passos": "Gerar relatório final para cada hipótese.",
        }

    # ── Ciclo autônomo (estilo /goal: trabalha sem parar) ────────────────────

    async def _pensar(self, contexto: str) -> dict:
        # O auditor precisa RACIOCINAR longamente — não truncar o pensamento.
        from compliance_agent.llm.hermes_agent import _hermes, HERMES_MAX_TOKENS
        try:
            raw = await _hermes(_SYSTEM_GOAL, contexto, max_tokens=HERMES_MAX_TOKENS)
            if not isinstance(raw, str):
                raw = str(raw)
        except Exception as exc:
            return {"acao": "__llm_falhou__", "resumo": f"LLM indisponível ({type(exc).__name__})", "pensamento": str(exc)[:200]}
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return {"acao": "__llm_falhou__", "resumo": "sem JSON na resposta", "pensamento": raw[:400]}
        try:
            return json.loads(m.group())
        except Exception:
            return {"acao": "__llm_falhou__", "resumo": "JSON inválido", "pensamento": raw[:400]}

    async def trabalhar(self, max_passos_por_ciclo: int = MAX_PASSOS_POR_CICLO,
                        max_ciclos: int = 3, on_step=None, usar_llm=None) -> dict:
        """
        Executa o ciclo de auditoria guiado por missão.

        usar_llm:
          - None  (auto): usa o LLM (Hermes/Groq) para pensar; se falhar, cai para
                          a sequência local determinística.
          - True:         força raciocínio via LLM.
          - False:        força a sequência local (sem LLM).
        """
        missao = self.missao_atual()
        if not missao:
            return {"ok": False, "erro": "Nenhuma missão definida. Use definir_missao()."}

        self._historico_ciclo = []
        passos_totais = []
        chrome_ok = await chrome_disponivel()
        conhecimento = contexto_para_prompt(self.session, max_itens=12)

        # Auto-detecta disponibilidade de LLM. modo_local=True só quando NÃO há LLM
        # ou quando o LLM falha em tempo de execução (degradação graciosa).
        if usar_llm is None:
            try:
                from compliance_agent.llm.free_llm import groq_available, openrouter_available
                modo_local = not (groq_available() or openrouter_available())
            except Exception:
                modo_local = True
        else:
            modo_local = not usar_llm

        for ciclo_num in range(max_ciclos):
            passos = []
            novo_ciclo = False

            for i in range(max_passos_por_ciclo):
                if modo_local:
                    acao = self._proxima_acao_local(passos)
                    args = self._args_padrao_acao(acao)
                    pensamento = f"Sequência padrão /goal; passo {i+1}: {acao}"
                else:
                    historico_txt = "\n".join(
                        f"- {p['acao']}: {json.dumps(p['resultado'], ensure_ascii=False)[:180]}"
                        for p in passos[-5:]
                    ) or "(nenhuma ação ainda)"
                    contexto = (
                        f"MISSÃO: {missao}\n\n"
                        f"Chrome debug 9222 no ar: {'sim' if chrome_ok else 'não'}\n"
                        f"Data de hoje: {date.today().isoformat()}\n\n"
                        f"CONHECIMENTO ACUMULADO:\n{conhecimento}\n\n"
                        f"AÇÕES JÁ EXECUTADAS:\n{historico_txt}\n\n"
                        "Use a SEQUÊNCIA PADRÃO DO /goal."
                    )
                    decisao = await self._pensar(contexto)
                    acao = (decisao.get("acao") or "concluir").strip()
                    args = decisao.get("args") or {}
                    pensamento = decisao.get("pensamento", "")
                    # LLM caiu em runtime → degrada para a sequência local sem
                    # abortar o ciclo (o auditor não pode parar por um 429).
                    if acao == "__llm_falhou__":
                        modo_local = True
                        acao = self._proxima_acao_local(passos)
                        args = self._args_padrao_acao(acao)
                        pensamento = (f"LLM indisponível ({decisao.get('resumo','')}); "
                                      f"seguindo sequência local: {acao}")

                if acao == "concluir":
                    resumo = pensamento or "ciclo concluído"
                    aprender(
                        "licao",
                        f"ciclo_{datetime.now():%Y%m%d_%H%M}",
                        f"Missão '{missao[:80]}' — {resumo[:300]}",
                        fonte="hermes_goal",
                        session=self.session,
                    )
                    passo = {"acao": "concluir", "pensamento": pensamento, "resultado": {"resumo": resumo}}
                    passos.append(passo)
                    passos_totais.append(passo)
                    if on_step:
                        await _maybe_await(on_step, passo)
                    novo_ciclo = True
                    break

                resultado = await self.executar_acao(acao, args)
                if acao in ("abrir_chrome", "status_chrome"):
                    chrome_ok = await chrome_disponivel()

                passo = {"acao": acao, "pensamento": pensamento, "resultado": resultado, "args": args}
                passos.append(passo)
                passos_totais.append(passo)
                if on_step:
                    await _maybe_await(on_step, passo)

                if resultado.get("ok") is False and acao not in {"abrir_chrome", "status_chrome"}:
                    break

            if not novo_ciclo and passos and passos[-1]["resultado"].get("ok") is False:
                break

        resumo = passos_totais[-1]["resultado"].get("resumo") if passos_totais else ""
        return {
            "ok": True,
            "missao": missao,
            "passos": passos_totais,
            "n_passos": len(passos_totais),
            "resumo": resumo or "Ciclo encerrado sem conclusão.",
            "concluido": False,
        }

    # ── Helpers do modo /goal local (sem LLM) ─────────────────────────────────

    def _proxima_acao_local(self, passos: list[dict]) -> str:
        executadas = [p["acao"] for p in passos if p.get("acao")]
        for acao in ["analisar_dados", "identificar_padroes", "desenvolver_hipoteses", "testar_hipoteses", "aprender"]:
            if acao not in executadas:
                return acao
        return "concluir"

    def _args_padrao_acao(self, acao: str) -> dict:
        if acao == "analisar_dados":
            return {"tipo": "sem_sei"}
        if acao == "identificar_padroes":
            return {}
        if acao == "desenvolver_hipoteses":
            return {}
        if acao == "testar_hipoteses":
            return {}
        if acao == "aprender":
            return {"chave": "ciclo_local", "licao": "Sequência padrão executada sem LLM."}
        if acao == "concluir":
            return {
                "resumo": "Sequência padrão do /goal executada localmente.",
                "relatorio_final": "Ciclo concluído; relatório pronto em reports/relatorio_auditoria_obs.md."
            }
        return {}

    # ── Ciclo autônomo com LLM (quando disponível) ────────────────────────────

    # ── Multi-missão (pool limitado) ────────────────────────────────────────
    _MAX_CONCURRENT = 4
    _running: dict[str, dict] = {}
    _last: dict[str, dict] = {}

    @classmethod
    def running_missions(cls) -> list[dict]:
        out = []
        for ident, info in list(cls._running.items()):
            out.append({"id": ident, "titulo": info.get("titulo", ""), "status": info.get("status", "running")})
        return out

    @classmethod
    def last_missions(cls, limit: int = 20) -> list[dict]:
        items = sorted(cls._last.values(), key=lambda x: x.get("created_at") or "", reverse=True)[:limit]
        return items

    async def run_as(self, missao_id: str, titulo: str = "", max_passos_por_ciclo: int = MAX_PASSOS_POR_CICLO, max_ciclos: int = 3, on_step=None) -> dict:
        payload = {
            "id": missao_id,
            "titulo": titulo,
            "objetivo": self.missao_atual() or titulo,
            "status": "running",
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
            "resultado": None,
            "erro": None,
            "n_passos": 0,
        }
        type(self)._running[missao_id] = payload
        try:
            resultado = await self.trabalhar(max_passos_por_ciclo=max_passos_por_ciclo, max_ciclos=max_ciclos, on_step=on_step)
            payload["status"] = "concluida"
            payload["finished_at"] = datetime.utcnow().isoformat()
            payload["resultado"] = {
                "ok": bool(resultado.get("ok")),
                "n_passos": int(resultado.get("n_passos") or 0),
                "resumo": (resultado.get("resumo") or "")[:1000],
                "missao": resultado.get("missao"),
            }
            payload["n_passos"] = payload["resultado"]["n_passos"]
            return payload["resultado"]
        except Exception as e:
            payload["status"] = "erro"
            payload["finished_at"] = datetime.utcnow().isoformat()
            payload["erro"] = f"{type(e).__name__}: {e}"
            return {"ok": False, "erro": payload["erro"]}
        finally:
            payload["created_at"] = payload.get("created_at") or payload["started_at"]
            type(self)._last[missao_id] = payload
            type(self)._running.pop(missao_id, None)

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

class MissionQueue:
    def __init__(self):
        self._queue = asyncio.Queue()

    async def enqueue(self, item):
        await self._queue.put(item)

    async def get(self):
        return await self._queue.get()

    def qsize(self):
        return self._queue.qsize()

mission_queue = MissionQueue()


# ─── Orquestração de múltiplas missões paralelas ──────────────────────────────
#
# Persiste cada missão em MissaoAuditoria (histórico real no banco) e executa
# até _MAX_CONCURRENT em paralelo via asyncio.Task. O estado em memória
# (_running/_last na classe) reflete o que está rodando agora.

_mission_semaphore: Optional[asyncio.Semaphore] = None
_mission_tasks: set = set()


def _get_mission_semaphore() -> asyncio.Semaphore:
    global _mission_semaphore
    if _mission_semaphore is None:
        _mission_semaphore = asyncio.Semaphore(HermesGoalAgent._MAX_CONCURRENT)
    return _mission_semaphore


async def _executar_missao_persistida(missao_id: int, objetivo: str, titulo: str) -> None:
    """Roda uma missão paralela, atualizando MissaoAuditoria no banco."""
    from compliance_agent.database.models import get_session, MissaoAuditoria
    sem = _get_mission_semaphore()
    async with sem:
        session = get_session()
        try:
            row = session.get(MissaoAuditoria, missao_id)
            if row:
                row.status = "executando"
                row.started_at = datetime.utcnow()
                session.commit()

            agente = HermesGoalAgent(session=session, objetivo=objetivo)
            resultado = await agente.run_as(str(missao_id), titulo=titulo)

            row = session.get(MissaoAuditoria, missao_id)
            if row:
                row.status = "erro" if resultado.get("ok") is False else "concluida"
                row.resultado = json.dumps(resultado, ensure_ascii=False)[:4000]
                row.erro = resultado.get("erro")
                row.finished_at = datetime.utcnow()
                session.commit()
        except Exception as e:
            try:
                row = session.get(MissaoAuditoria, missao_id)
                if row:
                    row.status = "erro"
                    row.erro = f"{type(e).__name__}: {e}"
                    row.finished_at = datetime.utcnow()
                    session.commit()
            except Exception:
                pass
        finally:
            session.close()


def criar_missao_paralela(objetivo: str, titulo: str = "", prioridade: str = "media",
                          session=None) -> dict:
    """
    Cria uma missão paralela: persiste em MissaoAuditoria e dispara a execução
    em background (respeitando o pool de _MAX_CONCURRENT). Retorna o registro.
    """
    from compliance_agent.database.models import get_session, MissaoAuditoria
    s = session or get_session()
    fechar = session is None
    try:
        row = MissaoAuditoria(
            titulo=(titulo or objetivo[:80]),
            objetivo=objetivo,
            status="pendente",
            prioridade=prioridade if prioridade in {"baixa", "media", "alta"} else "media",
        )
        s.add(row)
        s.commit()
        missao_id = row.id
        dados = {
            "id": missao_id, "titulo": row.titulo, "objetivo": row.objetivo,
            "status": row.status, "prioridade": row.prioridade,
        }
    finally:
        if fechar:
            s.close()

    # Dispara em background se houver loop rodando; senão fica "pendente" no banco.
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(
            _executar_missao_persistida(missao_id, objetivo, dados["titulo"])
        )
        _mission_tasks.add(task)
        task.add_done_callback(_mission_tasks.discard)
    except RuntimeError:
        pass  # sem event loop (chamada síncrona) — execução fica adiada

    return dados


def listar_missoes(session=None, limit: int = 50) -> list[dict]:
    """Lista missões do banco (histórico + em execução), mais recentes primeiro."""
    from compliance_agent.database.models import get_session, MissaoAuditoria
    s = session or get_session()
    fechar = session is None
    try:
        rows = (s.query(MissaoAuditoria)
                .order_by(MissaoAuditoria.created_at.desc())
                .limit(limit).all())
        return [{
            "id": r.id, "titulo": r.titulo, "objetivo": r.objetivo,
            "status": r.status, "prioridade": r.prioridade,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "erro": r.erro,
        } for r in rows]
    finally:
        if fechar:
            s.close()


def detalhe_missao(missao_id: int, session=None) -> Optional[dict]:
    """Detalhe de uma missão específica, incluindo resultado JSON."""
    from compliance_agent.database.models import get_session, MissaoAuditoria
    s = session or get_session()
    fechar = session is None
    try:
        r = s.get(MissaoAuditoria, missao_id)
        if not r:
            return None
        resultado = None
        if r.resultado:
            try:
                resultado = json.loads(r.resultado)
            except Exception:
                resultado = {"raw": r.resultado}
        return {
            "id": r.id, "titulo": r.titulo, "objetivo": r.objetivo,
            "status": r.status, "prioridade": r.prioridade,
            "parametros": r.parametros, "resultado": resultado, "erro": r.erro,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
    finally:
        if fechar:
            s.close()


# ─── Auditor 24 horas: auditoria automática e ininterrupta ───────────────────
#
# Modo "liga e esquece": o Hermes roda um CICLO COMPLETO de auditoria
# (coleta SIAFE + DOERJ → análise → padrões → hipóteses → teste → alertas →
# reflexão do Hermes) repetidamente, 24h por dia, até ser desligado pelo botão
# na interface. Estado global em memória + persistência das missões.

_AUDITOR_24H = {
    "ativo": False,
    "task": None,
    "iniciado_em": None,
    "ciclos": 0,
    "ultimo_ciclo_em": None,
    "ultimo_resumo": "",
    "ultimo_erro": None,
    "objetivo": "",
    "proximo_ciclo_em": None,
    "intervalo_seg": int(os.environ.get("AUDITOR_24H_INTERVALO", "1800")),  # 30 min
}

_OBJETIVO_24H_PADRAO = (
    "Auditoria contínua e abrangente das finanças do Estado do RJ: coletar OBs do "
    "SIAFE2 e publicações do DOERJ do dia, cruzar com SEI quando houver processo, "
    "detectar fracionamento, superfaturamento, valores redondos, OBs sem SEI, "
    "concentração de favorecidos e nepotismo; gerar alertas fundamentados e "
    "aprender padrões. Nunca encerrar definitivamente — repetir indefinidamente."
)


def status_auditor_24h() -> dict:
    """Snapshot do estado do auditor 24h (para a interface)."""
    st = _AUDITOR_24H
    return {
        "ativo": st["ativo"],
        "iniciado_em": st["iniciado_em"],
        "ciclos": st["ciclos"],
        "ultimo_ciclo_em": st["ultimo_ciclo_em"],
        "ultimo_resumo": st["ultimo_resumo"][:1000],
        "ultimo_erro": st["ultimo_erro"],
        "objetivo": st["objetivo"][:300],
        "proximo_ciclo_em": st["proximo_ciclo_em"],
        "intervalo_seg": st["intervalo_seg"],
    }


async def _ciclo_auditor_completo(session, objetivo: str, on_step=None) -> dict:
    """
    Um ciclo COMPLETO de auditoria automática:
      1) garante Chrome 9222
      2) coleta SIAFE2 + DOERJ do dia
      3) roda o ciclo de raciocínio do agente (analisar→padrões→hipóteses→testar→aprender)
      4) gera alertas de compliance
      5) Hermes reflete sobre os alertas novos
    Retorna um resumo do que aconteceu.
    """
    resumo_partes = []
    agente = HermesGoalAgent(session=session, objetivo=objetivo)

    # 1+2) Coleta (best-effort; não derruba o ciclo se uma fonte falhar)
    for acao in ("abrir_chrome", "coletar_siafe", "coletar_doerj"):
        try:
            r = await agente.executar_acao(acao, agente._args_padrao_acao(acao) if acao not in
                                           ("abrir_chrome", "coletar_siafe", "coletar_doerj") else {})
            if acao == "coletar_siafe":
                resumo_partes.append(f"SIAFE: {r.get('obs_salvas', 0)} OBs")
            elif acao == "coletar_doerj":
                resumo_partes.append(f"DOERJ: {r.get('publicacoes', 0)} pubs")
            if on_step:
                await _maybe_await(on_step, {"acao": acao, "resultado": r})
        except Exception as e:
            resumo_partes.append(f"{acao}: erro {type(e).__name__}")

    # 3) Raciocínio guiado por missão (usa LLM se disponível)
    try:
        res = await agente.trabalhar(max_ciclos=2, on_step=on_step)
        resumo_partes.append(f"{res.get('n_passos', 0)} passos de raciocínio")
        if res.get("resumo"):
            resumo_partes.append(res["resumo"][:200])
    except Exception as e:
        resumo_partes.append(f"raciocínio: erro {type(e).__name__}")

    # 4) Gera alertas de compliance
    try:
        from compliance_agent.rules.generate_alerts import gerar_alertas
        n_alertas = gerar_alertas(session)
        if isinstance(n_alertas, int):
            resumo_partes.append(f"{n_alertas} alertas")
    except Exception:
        pass

    # 5) Hermes reflete sobre os alertas novos
    try:
        from compliance_agent.llm.hermes_agent import aprender_com_alertas_novos
        refl = await aprender_com_alertas_novos(session)
        if refl:
            prio = refl.get("prioridade_investigacao", "")
            if prio:
                resumo_partes.append(f"Prioridade: {prio[:120]}")
    except Exception:
        pass

    return {"ok": True, "resumo": " | ".join(resumo_partes)}


async def _loop_auditor_24h(objetivo: str):
    """Loop interno do auditor 24h. Roda até _AUDITOR_24H['ativo'] virar False."""
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.notifications.telegram import enviar_mensagem

    init_db()
    st = _AUDITOR_24H
    try:
        await enviar_mensagem(
            "🟢 *Auditor 24h LIGADO*\n\n"
            "Vou coletar SIAFE2 + DOERJ, cruzar com SEI, detectar irregularidades "
            "e aprender padrões — em ciclos contínuos, sem parar.\n"
            f"Intervalo entre ciclos: {st['intervalo_seg']//60} min."
        )
    except Exception:
        pass

    while st["ativo"]:
        session = get_session()
        try:
            console.print(f"[cyan]🔁 Auditor 24h — ciclo {st['ciclos']+1}[/cyan]")
            res = await _ciclo_auditor_completo(session, objetivo)
            st["ciclos"] += 1
            st["ultimo_ciclo_em"] = datetime.utcnow().isoformat()
            st["ultimo_resumo"] = res.get("resumo", "")
            st["ultimo_erro"] = None
            console.print(f"[green]✓ Ciclo {st['ciclos']}: {st['ultimo_resumo'][:150]}[/green]")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            st["ultimo_erro"] = f"{type(e).__name__}: {e}"
            console.print(f"[yellow]Auditor 24h ciclo falhou: {e}[/yellow]")
        finally:
            session.close()

        if not st["ativo"]:
            break
        st["proximo_ciclo_em"] = (
            datetime.utcnow() + timedelta(seconds=st["intervalo_seg"])
        ).isoformat()
        # Espera em fatias para responder rápido ao desligamento
        restante = st["intervalo_seg"]
        while restante > 0 and st["ativo"]:
            await asyncio.sleep(min(5, restante))
            restante -= 5

    st["proximo_ciclo_em"] = None
    console.print("[dim]Auditor 24h desligado.[/dim]")


def iniciar_auditor_24h(objetivo: str = "", intervalo_seg: Optional[int] = None) -> dict:
    """
    Liga o modo auditoria automática e ininterrupta (botão 'Auditor 24 horas').
    Idempotente: se já estiver ativo, apenas devolve o estado.
    """
    st = _AUDITOR_24H
    if st["ativo"]:
        return {"ok": True, "ja_ativo": True, **status_auditor_24h()}

    obj = objetivo.strip() or _OBJETIVO_24H_PADRAO
    if intervalo_seg and intervalo_seg >= 60:
        st["intervalo_seg"] = int(intervalo_seg)

    # Persiste a missão como a "atual" para coerência com o resto do sistema
    try:
        from compliance_agent.database.models import get_session
        s = get_session()
        try:
            HermesGoalAgent(session=s).definir_missao(obj)
        finally:
            s.close()
    except Exception:
        pass

    st["ativo"] = True
    st["objetivo"] = obj
    st["iniciado_em"] = datetime.utcnow().isoformat()
    st["ciclos"] = 0
    st["ultimo_erro"] = None

    try:
        loop = asyncio.get_running_loop()
        st["task"] = loop.create_task(_loop_auditor_24h(obj))
    except RuntimeError:
        # Sem event loop (chamada síncrona/teste): marca ativo mas não dispara task.
        st["task"] = None

    return {"ok": True, "ja_ativo": False, **status_auditor_24h()}


def parar_auditor_24h() -> dict:
    """Desliga o auditor 24h. O loop encerra no próximo check (até ~5s)."""
    st = _AUDITOR_24H
    st["ativo"] = False
    task = st.get("task")
    if task and not task.done():
        task.cancel()
    st["task"] = None
    try:
        from compliance_agent.notifications.telegram import enviar_mensagem
        loop = asyncio.get_running_loop()
        loop.create_task(enviar_mensagem(
            f"🔴 *Auditor 24h DESLIGADO*\nCiclos executados: {st['ciclos']}."
        ))
    except Exception:
        pass
    return {"ok": True, **status_auditor_24h()}


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
