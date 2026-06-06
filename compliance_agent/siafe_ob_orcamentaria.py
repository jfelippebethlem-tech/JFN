# -*- coding: utf-8 -*-
"""
SIAFE-Rio 2 — varredura da tela "Execução > Execução Financeira > OB Orçamentária"
(tela `ordemBancariaOrcamentariaCad.jsp`, tabela ADF `pt1:tblOBOrcamentaria:tabViewerDec`).

ABORDAGEM (a mais robusta): o Playwright LOGA (tratando o diálogo de sessão única do SIAFE) e abre a tela;
depois **rola a tabela virtualizada de verdade** e colhe as linhas do DOM à medida que o Oracle ADF as
carrega por PPR. Assim o navegador cuida de ViewState/clientTokens/fetch sozinho — sem replay frágil.

Login: SIAFE_USER (CPF) e SIAFE_PASS vêm SÓ do .env (nunca hardcoded). Sessão é única por usuário: ao logar,
o SIAFE pergunta "usuário já logado... Deseja continuar? [Sim]" e FECHA a outra sessão (ex.: seu navegador).

USO:
    cd ~/JFN
    .venv/bin/python -m compliance_agent.siafe_ob_orcamentaria --exercicio 2025 --max 300
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

LOGIN_URL = "https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp"
TABLE_DB = "pt1:tblOBOrcamentaria:tabViewerDec::db"   # container rolável do corpo da tabela
OB_RE = re.compile(r"20\d\dOB\d{5,6}")
_STATE = _REPO / "data" / "sei_cache" / "siafe_state.json"
_CKPT = _REPO / "data" / "sei_cache" / "ob_orcamentaria_checkpoint.json"


class SessaoPerdida(Exception):
    """Disparada quando o SIAFE nos desconecta no meio (ex.: o Mestre Jorge logou e tomou a sessão única)."""


async def _sessao_perdida(pg) -> bool:
    """Detecta se fomos deslogados: voltou pra tela de login ou mensagem de sessão encerrada."""
    try:
        if "login.jsp" in (pg.url or "").lower():
            return True
        txt = ((await pg.inner_text("body")) or "").lower()
    except Exception:
        return True  # página morreu = trate como perda
    return any(k in txt for k in ("sessão encerrada", "sessao encerrada", "sessão expirou",
                                  "sessão expirada", "sua sessão", "faça login novamente",
                                  "esqueceu sua senha"))


async def _login(pg, exercicio: int):
    from compliance_agent.envfile import carregar_env
    try:
        carregar_env()
    except Exception:
        pass
    u = (os.environ.get("SIAFE_USER") or "").strip()
    p = (os.environ.get("SIAFE_PASS") or "").strip()
    if not u or not p:
        return {"ok": False, "erro": "sem SIAFE_USER/SIAFE_PASS no .env"}
    await pg.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
    await pg.wait_for_timeout(2500)
    await pg.locator("input[type=text]").first.fill(u)
    await pg.locator("input[type=password]").first.fill(p)
    # exercício no dropdown correto (cbxExercicio); o 1º <select> é o cliente "Rio de Janeiro"
    try:
        sel = pg.locator("select[id*='cbxExercicio']")
        if not await sel.count():
            sels = pg.locator("select"); sel = sels.nth(await sels.count() - 1)
        if await sel.count():
            await sel.first.select_option(label=str(exercicio))
    except Exception:
        pass
    await pg.keyboard.press("Enter")
    await pg.wait_for_timeout(6000)
    # diálogo de sessão única: "já está logado ... Deseja continuar? [Sim]"
    for _ in range(4):
        txt = ((await pg.inner_text("body")) or "").lower()
        if any(k in txt for k in ("já está logado", "ja esta logado", "deseja continuar",
                                  "outra janela", "deseja acess", "conexão feita a partir")):
            for lbl in ("Sim", "Continuar", "OK", "Ok"):
                try:
                    btn = pg.get_by_text(lbl, exact=True)
                    if await btn.count():
                        await btn.first.click(); await pg.wait_for_timeout(3500); break
                except Exception:
                    pass
        else:
            break
    await pg.wait_for_timeout(3000)
    body = ((await pg.inner_text("body")) or "").lower()
    if any(k in body for k in ("token", "código de verificação", "autenticação de dois")):
        return {"ok": False, "erro": "mfa", "detail": "SIAFE pediu MFA — fornecer o código."}
    if "esqueceu sua senha" in body and "login" in pg.url.lower():
        return {"ok": False, "erro": "login_falhou", "url": pg.url}
    return {"ok": True, "url": pg.url}


async def _navegar(pg) -> dict:
    """Execução → Execução Financeira → OB Orçamentária. Retorna {ok, itens_submenu}."""
    await pg.evaluate(r"""()=>{const a=[...document.querySelectorAll('a.xyo')].find(e=>(e.innerText||'').trim()==='Execução');if(a)a.click();}""")
    await pg.wait_for_timeout(1800)
    await pg.evaluate(r"""()=>{const a=document.getElementById('pt1:pt_np3:1:pt_cni4::disclosureAnchor')||[...document.querySelectorAll('a.xyo')].find(e=>(e.innerText||'').trim()==='Execução Financeira');if(a)a.click();}""")
    await pg.wait_for_timeout(2200)
    itens = await pg.evaluate(r"""()=>[...document.querySelectorAll('a')].map(e=>(e.innerText||'').trim()).filter(t=>t.length>2&&t.length<60)""")
    # clica o item da OB Orçamentária (varia o rótulo)
    await pg.evaluate(r"""()=>{const cand=[...document.querySelectorAll('a')].find(e=>{const t=(e.innerText||'').trim().toLowerCase();return /ob.*or[çc]ament|ordem banc.*or[çc]ament|or[çc]ament[áa]ria/.test(t);});if(cand)cand.click();}""")
    await pg.wait_for_timeout(12000)
    achou = await pg.evaluate(r"""()=>!!document.querySelector('[id*="tblOBOrcamentaria"]')""")
    return {"ok": bool(achou), "itens_submenu": [t for t in itens if "ob" in t.lower() or "orçament" in t.lower() or "orcament" in t.lower()][:10]}


async def _colher(pg, maxn: int, vistos: set, linhas: list, save_cb=None) -> list:
    """Rola a tabela virtualizada e colhe as linhas do DOM (acumula em `linhas`/`vistos`).
    Levanta SessaoPerdida se o SIAFE nos deslogar no meio. `save_cb()` persiste o progresso."""
    header = await pg.evaluate(r"""()=>{
        const h=document.querySelector('[id="pt1:tblOBOrcamentaria:tabViewerDec::ch"]')||document.querySelector('[id*="tblOBOrcamentaria"][id*="::ch"]');
        if(!h)return[];return [...h.querySelectorAll('th,td')].map(c=>(c.innerText||'').replace(/\s+/g,' ').trim()).filter(x=>x);
    }""")
    seco = 0
    js_rows = r"""()=>{const db=document.getElementById('""" + TABLE_DB + r"""');const o=[];if(db)db.querySelectorAll('tr').forEach(tr=>{const tds=[...tr.querySelectorAll('td')].map(td=>(td.innerText||'').replace(/\s+/g,' ').trim());if(tds.some(x=>x))o.push(tds);});return o;}"""
    js_scroll = r"""()=>{const db=document.getElementById('""" + TABLE_DB + r"""');if(db){db.scrollTop=db.scrollHeight;return db.scrollTop;}return -1;}"""
    ciclo = 0
    while len(linhas) < maxn and seco < 6:
        rows = await pg.evaluate(js_rows)
        novos = 0
        for r in rows:
            m = OB_RE.search(" ".join(r))
            if m and m.group(0) not in vistos and len([c for c in r if c]) >= 4:
                vistos.add(m.group(0)); linhas.append(r); novos += 1
        seco = 0 if novos else seco + 1
        if novos and save_cb and len(linhas) % 200 < novos:
            save_cb(header, linhas)
        if len(linhas) >= maxn:
            break
        await pg.evaluate(js_scroll)
        await pg.wait_for_timeout(1400)  # espera o PPR carregar o próximo bloco
        ciclo += 1
        if ciclo % 5 == 0 and await _sessao_perdida(pg):
            if save_cb:
                save_cb(header, linhas)
            raise SessaoPerdida(f"deslogado após colher {len(linhas)} OBs")
    if save_cb:
        save_cb(header, linhas)
    return header


def _ckpt_load(exercicio: int) -> tuple[set, list, list]:
    try:
        d = json.loads(_CKPT.read_text(encoding="utf-8"))
        if d.get("exercicio") == exercicio:
            linhas = d.get("linhas", [])
            vistos = set()
            for r in linhas:
                m = OB_RE.search(" ".join(r))
                if m:
                    vistos.add(m.group(0))
            return vistos, linhas, d.get("header", [])
    except Exception:
        pass
    return set(), [], []


def _ckpt_save(exercicio: int, header: list, linhas: list):
    try:
        _CKPT.parent.mkdir(parents=True, exist_ok=True)
        _CKPT.write_text(json.dumps({"exercicio": exercicio, "header": header, "linhas": linhas},
                                    ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


async def coletar(exercicio=2025, maxn=300, headless=True, vistos=None, linhas=None) -> dict:
    """Uma passada: login → navega → colhe. Acumula em `vistos`/`linhas` (para retomar entre tentativas)."""
    from playwright.async_api import async_playwright
    vistos = vistos if vistos is not None else set()
    linhas = linhas if linhas is not None else []
    save_cb = lambda h, ls: _ckpt_save(exercicio, h, ls)
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=headless, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
                                  viewport={"width": 1600, "height": 1000},
                                  user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"))
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        _t0 = time.time()
        _log = lambda m: print(f"[{time.time()-_t0:5.1f}s] {m}", flush=True)
        try:
            _log("login: iniciando...")
            log = await _login(pg, exercicio)
            _log(f"login: {log}")
            if not log.get("ok"):
                return {"ok": False, "etapa": "login", **log}
            _log("navegação: Execução > Execução Financeira > OB Orçamentária...")
            nav = await _navegar(pg)
            _log(f"navegação: {nav}")
            if not nav.get("ok"):
                try:
                    await pg.screenshot(path=str(_REPO / "data/sei_cache/ERRO_nav_ob_orc.png"))
                except Exception:
                    pass
                return {"ok": False, "etapa": "navegacao", "detail": "tabela tblOBOrcamentaria não apareceu",
                        "itens_submenu": nav.get("itens_submenu")}
            try:
                await ctx.storage_state(path=str(_STATE))
            except Exception:
                pass
            _log(f"colhendo (rolando a tabela, alvo {maxn})...")
            header = await _colher(pg, maxn, vistos, linhas, save_cb)
            _log(f"colheu {len(linhas)} OBs | header={header}")
            return {"ok": True, "exercicio": exercicio, "header": header, "n": len(linhas), "linhas": linhas}
        finally:
            await b.close()


async def coletar_resiliente(exercicio=2025, maxn=100000, max_tentativas=24,
                             headless=True, coordenar=True, espera_fallback_s=3600,
                             _sleep=None, _aguardar=None) -> dict:
    """
    Varredura RESILIENTE à sessão única do SIAFE. Se o Mestre Jorge logar e nos derrubar (ou vice-versa),
    a sessão cai: salvamos o progresso (checkpoint) e, em vez de esperar um tempo fixo, **perguntamos no
    Telegram** e aguardamos o Jorge liberar (ele responde 'siafe livre' → o Yoda seta o flag). Aí RETOMAMOS
    de onde paramos. Se `coordenar=False`, cai no modo de espera fixa (`espera_fallback_s`).
    """
    _sleep = _sleep or asyncio.sleep
    try:
        from compliance_agent import siafe_coord
    except Exception:
        siafe_coord = None
    _aguardar = _aguardar or (siafe_coord.aguardar_liberacao if (siafe_coord and coordenar) else None)

    async def _esperar(motivo):
        if _aguardar:
            # roda o aguardar (bloqueante) numa thread para não travar o loop async
            await asyncio.to_thread(_aguardar, motivo)
            if siafe_coord:
                siafe_coord.set_status("coletor_rodando", "varredura em curso")
        else:
            await _sleep(espera_fallback_s)

    vistos, linhas, _ = _ckpt_load(exercicio)
    # antes de logar (e derrubar o Jorge), se ele marcou 'ocupado', pergunta e aguarda liberar
    if siafe_coord and coordenar and siafe_coord.get_status() == "ocupado":
        await _esperar("preciso iniciar a varredura, mas o flag está 'ocupado'")
    ultimo = len(linhas)
    for tentativa in range(1, max_tentativas + 1):
        try:
            res = await coletar(exercicio, maxn, headless=headless, vistos=vistos, linhas=linhas)
        except SessaoPerdida as e:
            print(f"[resiliente] sessão perdida ({e}). {len(linhas)} OBs salvas. Coordenando via Telegram...", flush=True)
            await _esperar(f"fui desconectado no meio da varredura (já tenho {len(linhas)} OBs)")
            continue
        if not res.get("ok"):
            if res.get("erro") == "mfa":
                if siafe_coord:
                    siafe_coord.notificar("🔐 SIAFE pediu MFA na varredura — me mande o código, Mestre Jorge.")
                return {"ok": False, "erro": "mfa", "n": len(linhas),
                        "detail": "SIAFE pediu MFA — preciso do código do Mestre Jorge."}
            print(f"[resiliente] falha '{res.get('etapa')}' ({res.get('erro') or res.get('detail')}). Coordenando...", flush=True)
            await _esperar(f"falhei na etapa '{res.get('etapa')}' do SIAFE")
            continue
        if len(linhas) >= maxn:
            return {"ok": True, "completo": False, "exercicio": exercicio,
                    "header": res.get("header", []), "n": len(linhas), "linhas": linhas}
        # passada concluiu sem perder sessão → varredura completa
        return {"ok": True, "completo": True, "exercicio": exercicio,
                "header": res.get("header", []), "n": len(linhas), "linhas": linhas}
    return {"ok": False, "erro": "max_tentativas", "n": len(linhas), "linhas": linhas}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exercicio", type=int, default=2025)
    ap.add_argument("--max", type=int, default=300)
    a = ap.parse_args()
    res = asyncio.run(coletar(a.exercicio, a.max))
    if not res.get("ok"):
        print(json.dumps(res, ensure_ascii=False, indent=1)); return
    print(f"OK — {res['n']} OBs colhidas (exercício {res['exercicio']})")
    print("HEADER:", res["header"])
    for r in res["linhas"][:5]:
        print("  ", r[:10])


if __name__ == "__main__":
    main()
