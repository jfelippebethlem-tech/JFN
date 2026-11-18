"""Verificação humana no circuito: a coleta para no captcha / "não sou robô", o dono clica pelo noVNC e ela segue.

Dono, 18/11/2026: "monta no novnc que eu clico". NÃO resolve captcha por máquina (decisão: burlar a proteção do site
fragiliza a origem do dado e arrisca bloqueio). Usa o navegador já existente da VM-1 ("navegador-claude": Xvfb :88 +
x11vnc + noVNC na Tailnet em http://jfn-core:6080/vnc.html, Chromium com depuração em 127.0.0.1:9333).

Fluxo: abre a URL nesse Chromium → se não há verificação, devolve a sessão na hora; se há, avisa o dono no Telegram
(com o link do noVNC) e espera a verificação sumir → grava os cookies (JSON) para a coleta reaproveitar a sessão →
volta a aba para about:blank (página pesada aberta come a CPU da VM-1).

    python -m tools.verificacao_humana URL --motivo "PNCP: lista de atas" [--cookies saida.json] [--minutos 30]

Na coleta (Playwright): `cookies = carregar_sessao(url) or aguardar_humano(url, motivo)` e
`contexto.add_cookies(cookies)`.
SESSÕES PERMANENTES (dono, 18/11: "crie mecanismos para que as sessões sejam permanentes"): o perfil do Chromium é
persistente; toda sessão resolvida vai para o cofre data/sessoes/<host>.json; `--manter` (cron single-pass) revisita
cada site registrado para renovar antes de expirar e só avisa o dono se o desafio voltar (1 aviso/site/6 h).
Limite: a VM-1 é IP de datacenter — site que bloqueia datacenter continua bloqueando aqui (ver memória
tfe-bloqueia-datacenter-toda-origem-testada).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

CDP = "http://127.0.0.1:9333"
SESSOES = Path(__file__).resolve().parents[1] / "data" / "sessoes"      # cofre: <host>.json + sites.json
AVISO_MIN_H = 6.0                                                        # no máximo 1 aviso por site a cada 6 h
LINK_NOVNC = "http://jfn-core:6080/vnc.html"
# Sinais de desafio anti-robô: iframes dos provedores + textos de página de desafio. Só DETECTA — nunca interage.
_IFRAMES = ("recaptcha", "hcaptcha", "challenges.cloudflare.com", "turnstile", "captcha")
_TEXTOS = ("não sou um robô", "nao sou um robo", "i'm not a robot", "verify you are human", "verifique que você é humano",
           "confirme que você é humano", "checking your browser", "verificando seu navegador", "digite os caracteres",
           "captcha")


def _host(url: str) -> str:
    from urllib.parse import urlparse
    return (urlparse(url).hostname or "sem_host").lower()


def _ler_json(p: Path, padrao):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return padrao


def _gravar_json(p: Path, dado) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(dado, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def registrar_site(url: str, motivo: str) -> None:
    """Site entra na renovação periódica (`--manter`)."""
    reg = _ler_json(SESSOES / "sites.json", {})
    reg[_host(url)] = {"url": url, "motivo": motivo, "desde": reg.get(_host(url), {}).get("desde") or time.strftime("%F %T")}
    _gravar_json(SESSOES / "sites.json", reg)


def guardar_sessao(url: str, cookies: list[dict]) -> None:
    _gravar_json(SESSOES / f"{_host(url)}.json", {"em": time.strftime("%F %T"), "url": url, "cookies": cookies})


def carregar_sessao(url: str, agora: float | None = None) -> list[dict]:
    """Cookies guardados do site, sem os já expirados (expires −1 = de sessão: mantido). Vazio se não houver."""
    agora = time.time() if agora is None else agora
    d = _ler_json(SESSOES / f"{_host(url)}.json", {})
    return [c for c in (d.get("cookies") or []) if (c.get("expires") or -1) < 0 or c["expires"] > agora]


def ha_desafio(iframes_src: list[str], texto_visivel: str) -> bool:
    """Puro (testável): há verificação humana pendente na página?"""
    if any(any(k in (s or "").lower() for k in _IFRAMES) for s in iframes_src):
        return True
    t = (texto_visivel or "").lower()
    return any(k in t for k in _TEXTOS)


async def _estado(pagina) -> bool:
    srcs = [f.url for f in pagina.frames]
    try:
        texto = await pagina.inner_text("body", timeout=5000)
    except Exception:  # noqa: BLE001 — página navegando/sem body: trata como ainda carregando (sem desafio visível)
        texto = ""
    return ha_desafio(srcs, texto[:20000])


async def _avisar(motivo: str, url: str) -> None:
    from compliance_agent.notifications import silencio, telegram
    silencio.PEDIDO.set(True)   # pedido do dono: não cai no silêncio dos avisos automáticos
    await telegram.enviar_mensagem(
        f"🖱️ Verificação humana pedida — {motivo}\n{url}\n\nAbra {LINK_NOVNC} e resolva o desafio na tela; "
        f"a coleta segue sozinha assim que ele sumir.", parse_mode="")


async def aguardar_humano_async(url: str, motivo: str, minutos: float = 30.0) -> list[dict]:
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        navegador = await pw.chromium.connect_over_cdp(CDP)
        contexto = navegador.contexts[0] if navegador.contexts else await navegador.new_context()
        pagina = await contexto.new_page()
        try:
            await pagina.goto(url, wait_until="domcontentloaded", timeout=90000)
            await pagina.wait_for_timeout(3000)
            if await _estado(pagina):
                await _avisar(motivo, url)
                fim = time.monotonic() + minutos * 60
                while await _estado(pagina):
                    if time.monotonic() > fim:
                        raise TimeoutError(f"verificação humana não resolvida em {minutos:.0f} min: {url}")
                    await asyncio.sleep(5)
                await pagina.wait_for_timeout(2000)
            cookies = await contexto.cookies(url)
            registrar_site(url, motivo)
            guardar_sessao(url, cookies)
            return cookies
        finally:
            try:
                await pagina.goto("about:blank")
                await pagina.close()
            except Exception:  # noqa: BLE001 — limpeza de aba não pode mascarar o resultado
                pass


def _pode_avisar(host: str, agora: float) -> bool:
    marcas = _ler_json(SESSOES / "avisos.json", {})
    if agora - float(marcas.get(host, 0)) < AVISO_MIN_H * 3600:
        return False
    marcas[host] = agora
    _gravar_json(SESSOES / "avisos.json", marcas)
    return True


async def manter_async() -> dict:
    """Passada única: visita cada site registrado no Chromium PERSISTENTE (renova a sessão antes de expirar) e regrava o
    cofre. Desafio de volta → avisa o dono (no máximo 1 por site a cada 6 h) e segue; não espera aqui."""
    from playwright.async_api import async_playwright
    reg = _ler_json(SESSOES / "sites.json", {})
    out = {}
    if not reg:
        return out
    async with async_playwright() as pw:
        navegador = await pw.chromium.connect_over_cdp(CDP)
        contexto = navegador.contexts[0] if navegador.contexts else await navegador.new_context()
        for host, info in reg.items():
            pagina = await contexto.new_page()
            try:
                await pagina.goto(info["url"], wait_until="domcontentloaded", timeout=90000)
                await pagina.wait_for_timeout(3000)
                if await _estado(pagina):
                    out[host] = "desafio"
                    if _pode_avisar(host, time.time()):
                        await _avisar(f"sessão expirou — {info.get('motivo', host)}", info["url"])
                else:
                    guardar_sessao(info["url"], await contexto.cookies(info["url"]))
                    out[host] = "renovada"
            except Exception as e:  # noqa: BLE001 — um site fora do ar não para a renovação dos outros
                out[host] = f"erro: {type(e).__name__}"
            finally:
                try:
                    await pagina.goto("about:blank")
                    await pagina.close()
                except Exception:  # noqa: BLE001
                    pass
    return out


def aguardar_humano(url: str, motivo: str, minutos: float = 30.0) -> list[dict]:
    return asyncio.run(aguardar_humano_async(url, motivo, minutos))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Verificação humana pelo noVNC (o dono clica; a coleta segue)")
    ap.add_argument("url", nargs="?")
    ap.add_argument("--manter", action="store_true", help="renova as sessões de todos os sites registrados (cron)")
    ap.add_argument("--motivo", default="coleta")
    ap.add_argument("--minutos", type=float, default=30.0)
    ap.add_argument("--cookies", default="", help="arquivo JSON para gravar os cookies da sessão")
    a = ap.parse_args(argv)
    if a.manter:
        print(json.dumps(asyncio.run(manter_async()), ensure_ascii=False))
        return 0
    if not a.url:
        ap.error("informe a URL ou --manter")
    try:
        cookies = aguardar_humano(a.url, a.motivo, a.minutos)
    except TimeoutError as e:
        print(str(e), file=sys.stderr)
        return 2
    if a.cookies:
        Path(a.cookies).write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"ok": True, "cookies": len(cookies)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
