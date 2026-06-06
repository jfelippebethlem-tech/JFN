#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SEI-RJ — reader AUTENTICADO da VM (login itkava + Pesquisa interna), na MESMA sessão.

PROVADO ao vivo (2026-06-06): da própria VM, com Chromium real + retry (vence o WAF de fingerprint),
loga como itkava/ITERJ SEM captcha e — clicando os LINKS internos do app (não URL crua) — chega à
Pesquisa autenticada com a sessão intacta (unidade ITERJ/CHEGAB confirmada). Base p/ o Lex ler a íntegra
real do SEI direto da VM, sem proxy/Actions.

Fluxo: login (form txtUsuario/#pwdSenha/#selOrgao→ITERJ + ACESSAR, retry+backoff) → clicar "Pesquisa
Rápida" → buscar o processo. FALTA (próximo passo bounded): trocar p/ o protocolo EXATO
(#txtProtocoloPesquisa na pesquisa avançada), abrir o processo (procedimento_trabalhar) e extrair a árvore
de documentos reaproveitando os extractors de `compliance_agent/collectors/sei_cdp.py`, gravando em
data/sei_cache/cdp_<proc>.json (Lex consome 24h).

Uso: python tools/sei_reader.py "SEI-070002/008633/2022"
"""
from __future__ import annotations
import asyncio, os, re, sys
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
from compliance_agent.envfile import carregar_env
carregar_env()

URL = os.environ.get("SEI_LOGIN_URL")
U, P, ORG = os.environ.get("SEI_USER", "itkava"), os.environ.get("SEI_PASS", ""), os.environ.get("SEI_ORGAO", "iterj")


async def _goto_retry(pg, url, n=8):
    for _ in range(n):
        try:
            r = await pg.goto(url, wait_until="domcontentloaded", timeout=20000); return r.status if r else None
        except Exception:
            await pg.wait_for_timeout(2500)
    return None


async def login(pg, tentativas=40) -> bool:
    """Loga no SEI interno (itkava/ITERJ) vencendo o flap do WAF. Retorna True se autenticou."""
    for _ in range(tentativas):
        if not await _goto_retry(pg, URL, 3):
            continue
        form = await pg.evaluate(r"""()=>{const q=s=>document.querySelector(s);const o=q('#selOrgao')||q('select');
          return {user:!!q('input[name="txtUsuario"]'),pwd:!!q('#pwdSenha'),opts:o?[...o.options].map(x=>({v:x.value,t:(x.text||'').trim()})):[]};}""")
        if not form["user"] or not form["pwd"]:
            await pg.wait_for_timeout(2000); continue
        await pg.fill('input[name="txtUsuario"]', U)
        try: await pg.fill('#pwdSenha', P)
        except Exception: pass
        await pg.evaluate(r"""(p)=>{document.querySelectorAll('#pwdSenha,input[name=\"pwdSenha\"]').forEach(e=>e.value=p);}""", P)
        cand = [o for o in form["opts"] if re.search(r"\biterj\b|terras", o["t"], re.I)]
        if cand:
            await pg.select_option('#selOrgao', value=cand[0]["v"])
        await pg.evaluate(r"""()=>{const b=[...document.querySelectorAll('button,input[type=submit],a')].find(e=>/acessar|entrar|logar/i.test((e.value||e.innerText||'').trim()));if(b)b.click();}""")
        await pg.wait_for_timeout(6000)
        if "login.php" not in pg.url:
            return True
        await pg.wait_for_timeout(1500)
    return False


async def abrir_pesquisa(pg) -> bool:
    """Clica a Pesquisa interna (clique real preserva os tokens de sessão). Retorna True se chegou na busca."""
    await pg.evaluate(r"""()=>{const e=[...document.querySelectorAll('a,area,img')].find(x=>/pesquis/i.test((x.id||'')+' '+(x.title||'')+' '+(x.innerText||'')+' '+(x.getAttribute&&x.getAttribute('onclick')||'')));if(e)e.click();}""")
    await pg.wait_for_timeout(5000)
    return "#pwdSenha" not in ((await pg.content()) or "")


async def main():
    from playwright.async_api import async_playwright
    proc = sys.argv[1] if len(sys.argv) > 1 else "SEI-070002/008633/2022"
    if not P:
        print("SEI_PASS vazio"); return
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page()
        if not await login(pg):
            print("FALHOU login"); await b.close(); return
        print("✅ LOGADO:", pg.url[:80])
        if await abrir_pesquisa(pg):
            print("✅ Pesquisa autenticada acessível (sessão intacta):", pg.url[:90])
            print("→ próximo: protocolo exato + abrir processo + extrair via sei_cdp")
        else:
            print("⚠ Pesquisa voltou ao login (flap) — repetir")
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
