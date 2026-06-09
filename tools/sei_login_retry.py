#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SEI-RJ — login interno (itkava) via Chromium — VENCE o WAF de fingerprint+flap (validado 2026-06-06).

DESCOBERTAS (validadas ao vivo da VM):
  • O WAF do SEI bloqueia por FINGERPRINT, não por IP: `curl`/`httpx` são dropados (ERR_CONNECTION_CLOSED,
    0/10), mas um Chromium REAL passa (HTTP 200) — de forma intermitente (flap). Daí o retry com backoff.
  • Login interno (txtUsuario/pwdSenha/selOrgao + botão ACESSAR) funciona como `itkava` órgão ITERJ e
    **NÃO exige captcha** — cai direto em `controlador.php?acao=procedimento_controlar` (Controle de Processos).
  • Campos: `input[name="txtUsuario"]`, senha visível `#pwdSenha` (+ hidden `name=pwdSenha`), `#selOrgao`
    (107 órgãos; achar "ITERJ"). NÃO há `/sip/` bloqueado; o que dropa é o flap (retry resolve).
  • ⚠️ A sessão NÃO sobrevive entre contextos (storage_state bounce p/ login) NEM a `goto` de URL crua de
    ação interna (ex.: protocolo_pesquisar volta ao login). É preciso LOGAR e LER na MESMA sessão,
    navegando pelos LINKS internos do app (que carregam os tokens de sessão), não por URL crua.

Uso: python tools/sei_login_retry.py [--tentativas 80] [--headful]
Próximo passo (a integrar no sei_cdp): após o login, clicar a Pesquisa do app e extrair a íntegra do
processo → gravar em data/sei_cache/cdp_*.json (Lex consome 24h).
"""
from __future__ import annotations
import argparse
import asyncio
import os
import re
import sys
import time
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
from compliance_agent.envfile import carregar_env
carregar_env()

URL = os.environ.get("SEI_LOGIN_URL", "https://sei.rj.gov.br/sip/login.php?sigla_orgao_sistema=ERJ&sigla_sistema=SEI&infra_url=L3NlaS8=")
U = os.environ.get("SEI_USER", "itkava")
P = os.environ.get("SEI_PASS", "")
ORG = os.environ.get("SEI_ORGAO", "iterj")
STATE = _REPO / "data" / "sei_cache" / "sei_state.json"


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


async def _try_once(ctx) -> dict:
    pg = await ctx.new_page()
    try:
        try:
            r = await pg.goto(URL, wait_until="domcontentloaded", timeout=20000)
            st = r.status if r else None
        except Exception as e:
            return {"fase": "goto", "ok": False, "erro": str(e)[:70]}
        # form presente? (campos reais do SEI: txtUsuario, pwdSenha, selOrgao — sem captcha no login interno)
        form = await pg.evaluate(r"""()=>{
          const q=s=>document.querySelector(s);
          const org=q('#selOrgao')||q('select[name="selOrgao"]')||q('select');
          return {user:!!q('input[name="txtUsuario"]'),
                  pwd:!!(q('#pwdSenha')||q('input[name="pwdSenha"]')),
                  org: org?org.id||org.getAttribute('name'):null,
                  org_opts: org?[...org.options].map(o=>({v:o.value,t:(o.text||'').trim()})):[],
                  captcha:(()=>{const c=q('#txtInfraCaptcha');if(!c)return false;const r=c.getBoundingClientRect();return r.width>0&&r.height>0;})()};
        }""")
        if not form.get("user") or not form.get("pwd"):
            return {"fase": "form", "ok": False, "http": st}
        if form.get("captcha"):
            return {"fase": "captcha", "ok": False, "http": st,
                    "detalhe": "captcha exigido — precisa OCR (sei_cdp._resolver_captcha_ocr)"}
        # preenche usuário + senha (campo visível id=pwdSenha; reforça o name=pwdSenha via JS)
        await pg.fill('input[name="txtUsuario"]', U)
        try:
            await pg.fill('#pwdSenha', P)
        except Exception:
            pass
        await pg.evaluate(r"""(p)=>{document.querySelectorAll('#pwdSenha,input[name=\"pwdSenha\"]').forEach(e=>{e.value=p;});}""", P)
        org_sel = None
        if form.get("org_opts"):
            cand = [o for o in form["org_opts"] if re.search(r"\biterj\b|terras", o["t"], re.I)] or \
                   [o for o in form["org_opts"] if o["t"].lower().startswith(ORG.lower())]
            if cand:
                try:
                    await pg.select_option('#selOrgao', value=cand[0]["v"]); org_sel = cand[0]["t"]
                except Exception:
                    org_sel = "?(" + cand[0]["t"] + ")"
        # submit (botão ACESSAR)
        await pg.evaluate(r"""()=>{const b=[...document.querySelectorAll('button,input[type=submit],input[type=button],a')].find(e=>/acessar|entrar|logar/i.test((e.value||e.innerText||'').trim()));if(b)b.click();}""")
        await pg.wait_for_timeout(6000)
        url2 = pg.url
        body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", (await pg.content()) or "")).lower()
        if "login.php" not in url2 and any(k in body for k in ["controle de processos", "sair", "acompanhamento", "menu", "infrabarra"]):
            await ctx.storage_state(path=str(STATE))
            return {"fase": "logado", "ok": True, "url": url2[:90], "org": org_sel}
        err = [k for k in ["senha", "inválid", "incorret", "captcha", "bloque", "negad"] if k in body]
        return {"fase": "pos_submit", "ok": False, "url": url2[:90], "erros": err, "org": org_sel}
    finally:
        await pg.close()


async def main(tentativas: int, headful: bool):
    from playwright.async_api import async_playwright
    if not P:
        log("SEI_PASS vazio — aborta"); return
    log(f"alvo: {URL[:70]} | user={U} | órgão≈{ORG} | tentativas={tentativas}")
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=not headful, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        back = 3
        for i in range(1, tentativas + 1):
            res = await _try_once(ctx)
            log(f"tentativa {i}/{tentativas}: {res}")
            if res.get("ok"):
                log(f"✅ LOGADO no SEI! sessão salva em {STATE}"); await b.close(); return
            if res.get("fase") == "captcha":
                log("⛔ captcha exigido — parar o retry e tratar via OCR (sei_cdp)"); await b.close(); return
            if res.get("erros"):
                log("⛔ credenciais/erro de login (não é WAF) — parar"); await b.close(); return
            await asyncio.sleep(min(back, 20)); back = int(back * 1.4)
        log("❌ esgotou tentativas sem furar o WAF/flap"); await b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tentativas", type=int, default=60)
    ap.add_argument("--headful", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.tentativas, a.headful))
