#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SESSÃO SEI PERSISTENTE (anti-flap do WAF).

Problema histórico: cada leitura/busca subia um browser novo e RE-LOGAVA do zero; logins repetidos
em sequência fazem o WAF do SEI estrangular → falha intermitente ("toda hora dificuldade").

Solução: logar UMA vez, salvar os cookies (storage_state) em disco e REUSAR em todas as operações.
Re-loga só quando a sessão morreu (ou --force). É a base canônica p/ sei_reader/sei_busca_mgs.

Uso:
  python tools/sei_session.py aquecer     # loga (se preciso) e salva a sessão
  python tools/sei_session.py checar       # diz se a sessão salva ainda está viva (sem logar)
  python tools/sei_session.py aquecer --force   # força novo login
"""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

_REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(_REPO))
from tools import sei_reader as SR

STATE = _REPO / "data" / "sei_cache" / "sei_storage_state.json"
# fingerprint que vence o WAF do SEI (idêntico ao context de sei_reader.ler)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _proxy():
    """Proxy opcional p/ furar o WAF (SEI_PROXY_URL/PROXY_URL no .env), igual ao reader."""
    try:
        from compliance_agent.collectors.sei_cdp import _proxy_do_env
        return _proxy_do_env()
    except Exception:
        return None


async def _novo_browser(pw):
    px = _proxy()
    return await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"],
                                    **({"proxy": px} if px else {}))


async def _novo_ctx(b, *, com_state: bool):
    return await b.new_context(ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
                               user_agent=UA, storage_state=str(STATE) if com_state else None)


SEI_APP = "https://sei.rj.gov.br/sei/"


async def _sessao_viva(pg) -> bool:
    """Navega no APP autenticado /sei/ (NÃO no SSO /sip/login.php, que sempre mostra o form).
    Sessão viva = a UI logada aparece (#txtPesquisaRapida) e não caiu no login."""
    await SR._goto_retry(pg, SEI_APP, 3)
    url = (pg.url or "")
    if "login.php" in url:
        return False
    if await pg.evaluate("()=>!!document.querySelector('#pwdSenha,input[name=\"pwdSenha\"]')"):
        return False
    return await pg.evaluate("()=>!!document.querySelector('#txtPesquisaRapida')")


async def abrir_sessao(pw, *, force: bool = False, tentativas_login: int = 30):
    """Retorna (browser, ctx, pg, ok). pg já está AUTENTICADO e na sessão SEI.
    Reusa o storage_state salvo (sem re-logar) sempre que possível; só loga se a sessão morreu."""
    b = await _novo_browser(pw)
    usar_state = STATE.exists() and not force
    ctx = await _novo_ctx(b, com_state=usar_state)
    pg = await ctx.new_page()
    await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    if usar_state and await _sessao_viva(pg):
        return b, ctx, pg, True  # reusou a sessão — SEM login (sem flap do WAF)
    # sessão morta/ausente → loga uma vez e PERSISTE
    if not await SR.login(pg, tentativas=tentativas_login):
        return b, ctx, pg, False
    STATE.parent.mkdir(parents=True, exist_ok=True)
    await ctx.storage_state(path=str(STATE))
    return b, ctx, pg, True


async def _cli(cmd: str, force: bool):
    from playwright.async_api import async_playwright
    from tools.vm_guard import preflight, cleanup_orphans
    ok, motivo = preflight()
    if not ok:
        print(json.dumps({"ok": False, "vm_guard": motivo})); return
    cleanup_orphans()
    try:
        async with async_playwright() as pw:
            if cmd == "checar":
                if not STATE.exists():
                    print(json.dumps({"ok": True, "sessao_salva": False, "viva": False})); return
                b = await _novo_browser(pw)
                ctx = await _novo_ctx(b, com_state=True)
                pg = await ctx.new_page()
                viva = await _sessao_viva(pg)
                await b.close()
                print(json.dumps({"ok": True, "sessao_salva": True, "viva": viva}))
                return
            # aquecer
            b, ctx, pg, ok = await abrir_sessao(pw, force=force)
            print(json.dumps({"ok": ok, "autenticado": ok, "state": str(STATE),
                              "reusou": (STATE.exists() and not force), "url": (pg.url or "")[-60:]}))
            await b.close()
    finally:
        cleanup_orphans()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "aquecer"
    asyncio.run(_cli(cmd, "--force" in sys.argv))
