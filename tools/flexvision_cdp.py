# -*- coding: utf-8 -*-
"""
flexvision_cdp — login interativo no FlexVision (Vaadin) usando o Chrome PERSISTENTE
da porta 9222 (CDP), pra atravessar a Autenticação Multifator (MFA por e-mail) ENTRE turnos.

O Chrome fica vivo segurando o diálogo de MFA enquanto eu desconecto; no turno seguinte
reconecto e digito o código. Marca "Dispensar código neste dispositivo por 30 dias" e
salva a sessão → sem MFA por 30 dias.

Subcomandos:
  login            -> abre nova aba, FV, preenche user/senha, dispara MFA. Deixa a aba viva.
  code <CODIGO>    -> acha a aba do FV, digita o código, marca 30 dias, Ok, salva sessão.
  status           -> diz em que estado a aba do FV está (login / mfa / dentro).

Uso: PYTHONPATH=. .venv/bin/python -m tools.flexvision_cdp <subcomando> [codigo]
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent
_STATE = _REPO / "data" / "sei_cache" / "flexvision_state.json"
_SINAL = _REPO / "data" / "sei_cache" / "flexvision_sinal.json"
_GWLOG = Path.home() / ".hermes" / "logs" / "gateway.log"
CDP = "http://127.0.0.1:9222"
FV = "https://siafe2-flexvision.fazenda.rj.gov.br/Flexvision/"
CHAT = "45338178"  # chat do Jorge no Telegram (de onde vem o código)

# regex do código MFA no log do Hermes: ...chat=45338178 msg='<CODIGO>'
import re as _re
_RX_MSG = _re.compile(r"inbound message:.*chat=" + CHAT + r"\s+msg='([^']*)'")


def _emit_sinal(sinal: str, detalhe: str = "") -> None:
    """Grava um SINAL inequívoco que uma IA fraca/cron lê pra saber o que fazer.
    Sinais: LOGADO | MFA_PENDENTE | PRECISA_LOGIN | MFA_FALHOU | ERRO."""
    import json
    try:
        _SINAL.parent.mkdir(parents=True, exist_ok=True)
        _SINAL.write_text(json.dumps({"sinal": sinal, "detalhe": detalhe}, ensure_ascii=False),
                          encoding="utf-8")
    except Exception as exc:
        logger.warning("falha ao gravar sinal %s em %s: %s", sinal, _SINAL, exc)
    print(f"SINAL={sinal}" + (f" | {detalhe}" if detalhe else ""), flush=True)


def _parece_codigo(s: str) -> bool:
    """Heurística do código MFA: 6–12 alfanum, sem espaço, com dígito OU caixa mista; não-comando."""
    s = (s or "").strip()
    if not (6 <= len(s) <= 12) or " " in s or s.startswith("/"):
        return False
    if not s.isalnum():
        return False
    tem_dig = any(c.isdigit() for c in s)
    tem_mix = any(c.islower() for c in s) and any(c.isupper() for c in s)
    return tem_dig or tem_mix


def _codigos_no_log(ultimas_linhas: int = 400) -> list[str]:
    """Lê as mensagens recentes do Jorge no log do Hermes (ordem cronológica)."""
    try:
        linhas = _GWLOG.read_text(encoding="utf-8", errors="replace").splitlines()[-ultimas_linhas:]
    except Exception:
        return []
    out = []
    for ln in linhas:
        m = _RX_MSG.search(ln)
        if m:
            out.append(m.group(1))
    return out


async def _fv_page(browser):
    """Acha (ou abre) a aba do FlexVision dentro do Chrome persistente."""
    for ctx in browser.contexts:
        for pg in ctx.pages:
            if "flexvision" in (pg.url or "").lower():
                return pg, ctx
    ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
    pg = await ctx.new_page()
    return pg, ctx


async def _estado(pg) -> str:
    body = ((await pg.inner_text("body")) or "").lower()
    # sessão ÚNICA: derrubada porque o usuário logou em outro IP (ou expirou)
    if "sessão expirou" in body or "sessao expirou" in body or "já está logado" in body or "ja esta logado" in body:
        return "ocupada"
    if "multifator" in body or "código de autenticação foi enviado" in body:
        return "mfa"
    if await pg.query_selector("input[type=password]"):
        return "login"
    return "dentro"


async def _pos_login_dialogos(pg, timeout_s: int = 16):
    """Trata diálogos pós-Login: take-over de sessão única ('Sim') + avisos ('Ok'/'Ciente').
    A sessão é ÚNICA: se o Jorge estiver logado, aparece 'O usuário já está logado... Deseja
    continuar? Sim/Não' — clicar Sim ASSUME a sessão (derruba a dele)."""
    sim = pg.locator("xpath=//*[contains(@class,'v-window')]//*[contains(@class,'v-button')][normalize-space()='Sim' or .//span[normalize-space()='Sim']]")
    try:
        await sim.first.wait_for(state="visible", timeout=timeout_s * 1000)
        await sim.first.click()
        print("  take-over: 'Sim' clicado (assumiu a sessão única)", flush=True)
    except Exception as exc:
        logger.debug("diálogo 'Sim' de take-over não apareceu: %s", exc)
    await pg.wait_for_timeout(3500)
    for _ in range(5):
        agiu = await pg.evaluate(r"""()=>{const vis=el=>{const r=el.getBoundingClientRect();const s=getComputedStyle(el);return r.width>0&&r.height>0&&s.visibility!=='hidden';};
            for(const t of ['Ok','OK','Ciente','Estou ciente','Continuar','Fechar']){const e=[...document.querySelectorAll('.v-button,button,[role=button]')].filter(vis).find(x=>(x.innerText||'').trim()===t);if(e){e.click();return t;}}return null;}""")
        if not agiu:
            break
        await pg.wait_for_timeout(1800)


async def cmd_login():
    from playwright.async_api import async_playwright
    from compliance_agent.envfile import carregar_env
    carregar_env()
    try:
        from compliance_agent import siafe_coord
    except Exception:
        siafe_coord = None
    u = (os.environ.get("SIAFE_USER") or "").strip()
    p = (os.environ.get("SIAFE_PASS") or "").strip()
    async with async_playwright() as pw:
        br = await pw.chromium.connect_over_cdp(CDP)
        # ABA LIMPA: fechar quaisquer abas FV antigas (acumulam janelas de erro Vaadin cujo
        # overlay aria-live intercepta cliques) e abrir uma nova.
        ctx = br.contexts[0] if br.contexts else await br.new_context()
        for c in br.contexts:
            for old in list(c.pages):
                if "flexvision" in (old.url or "").lower():
                    try:
                        await old.close()
                    except Exception as exc:
                        logger.debug("falha ao fechar aba FV antiga %s: %s", old.url, exc)
        pg = await ctx.new_page()
        await pg.goto(FV, wait_until="domcontentloaded", timeout=45000)
        await pg.wait_for_timeout(3500)
        ut = await pg.query_selector("input[type=text]")
        pt = await pg.query_selector("input[type=password]")
        if not (ut and pt):
            print("STATE:", await _estado(pg), "| url:", pg.url)
            print("já logado ou sem form — nada a fazer no login.")
            await br.close(); return
        await ut.click(); await ut.fill(""); await ut.type(u, delay=25); await pg.wait_for_timeout(150)
        await pt.click(); await pt.fill(""); await pt.type(p, delay=25); await pg.wait_for_timeout(150)
        await pg.click("xpath=//*[contains(@class,'v-button')][normalize-space()='Login' or .//span[normalize-space()='Login']]")
        await pg.wait_for_timeout(2500)
        await _pos_login_dialogos(pg)
        est = await _estado(pg)
        print("STATE:", est, "| url:", pg.url)
        if est == "mfa":
            # marcar JÁ o checkbox "Dispensar por 30 dias" (deixa a janela pronta p/ o Jorge)
            marcou = await pg.evaluate(r"""()=>{const W=[...document.querySelectorAll('.v-window')].find(w=>/multifator|código|dispensar/i.test(w.innerText||''));
                if(!W)return false; const c=W.querySelector('input[type=checkbox]'); if(c&&!c.checked)c.click(); return c?c.checked:false;}""")
            print(f"OK -> MFA disparado; checkbox 30 dias = {marcou}. Código novo enviado ao e-mail.")
            if siafe_coord:
                siafe_coord.notificar("🔐 FlexVision: abri o login e disparei o MFA (caixa '30 dias' já marcada). "
                                      "Me mande o CÓDIGO que chegou no seu e-mail que eu clico Ok. (expira em minutos)")
        elif est == "dentro":
            print("OK -> entrou direto (sessão confiável). Salvando estado.")
            await ctx.storage_state(path=str(_STATE))
        else:
            body = (await pg.inner_text("body")) or ""
            print("login não avançou. body[:300]:", repr(body[:300]))
        await br.close()  # fecha só a CONEXÃO CDP; o Chrome (e a aba) seguem vivos


async def cmd_code(codigo: str):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        br = await pw.chromium.connect_over_cdp(CDP)
        pg, ctx = await _fv_page(br)
        est = await _estado(pg)
        if est != "mfa":
            print("STATE:", est, "— não está no MFA. (se 'login', rode 'login' antes; se 'dentro', já está logado)")
            if est == "dentro":
                await ctx.storage_state(path=str(_STATE)); print("estado salvo.")
            await br.close(); return
        # 0) fechar janelas de ERRO empilhadas (ex.: "Usuário e/ou senha incorretos")
        await pg.evaluate(r"""()=>{[...document.querySelectorAll('.v-window')].forEach(w=>{
            const t=(w.innerText||'').toLowerCase();
            if(t.includes('incorret')||t.includes('erro')){
                const x=w.querySelector('.v-window-closebox'); if(x)x.click();
            }});}""")
        await pg.wait_for_timeout(500)
        # localizar a JANELA do MFA (texto Multifator/Código/Dispensar) e digitar no SEU password
        info = await pg.evaluate(r"""(cod)=>{
          const W=[...document.querySelectorAll('.v-window')].find(w=>/multifator|código|dispensar/i.test(w.innerText||''));
          if(!W) return {ok:false, motivo:'sem janela MFA'};
          const inp=W.querySelector('input[type=password]');
          if(!inp) return {ok:false, motivo:'sem campo password na janela MFA'};
          inp.focus(); inp.value=''; inp.value=cod;
          inp.dispatchEvent(new Event('input',{bubbles:true}));
          inp.dispatchEvent(new Event('change',{bubbles:true}));
          const chk=W.querySelector('input[type=checkbox]'); if(chk&&!chk.checked) chk.click();
          return {ok:true, len:inp.value.length, chk: chk?chk.checked:null};
        }""", codigo.strip())
        print("preencheu:", info)
        if not info.get("ok"):
            print("não consegui preencher o código:", info.get("motivo")); await br.close(); return
        # reforçar digitação real no campo (Vaadin às vezes ignora set programático)
        try:
            ci = await pg.query_selector("xpath=//*[contains(@class,'v-window')][contains(.,'Multifator') or contains(.,'Código') or contains(.,'Dispensar')]//input[@type='password']")
            if ci:
                await ci.click(); await ci.fill(""); await ci.type(codigo.strip(), delay=40)
        except Exception as exc:
            logger.debug("reforço de digitação do código MFA falhou: %s", exc)
        await pg.wait_for_timeout(300)
        # clicar Ok via JS DENTRO da janela do MFA (overlay aria-live intercepta clique normal)
        await pg.evaluate(r"""()=>{const W=[...document.querySelectorAll('.v-window')].find(w=>/multifator|código|dispensar/i.test(w.innerText||''));
            if(!W)return; const b=[...W.querySelectorAll('.v-button,[role=button]')].find(x=>/(^|\b)ok\b/i.test((x.innerText||'').trim()));
            if(b)b.click();}""")
        await pg.wait_for_timeout(6000)
        try:
            await pg.wait_for_load_state("networkidle", timeout=12000)
        except Exception as exc:
            logger.debug("espera por networkidle pós-código expirou: %s", exc)
        est2 = await _estado(pg)
        print("STATE pós-código:", est2, "| url:", pg.url)
        if est2 == "dentro":
            await ctx.storage_state(path=str(_STATE))
            print("✅ LOGADO. Sessão salva em", _STATE)
            try:
                await pg.screenshot(path="/tmp/flexvision_dentro.png", full_page=True)
            except Exception as exc:
                logger.debug("screenshot de confirmação falhou: %s", exc)
        else:
            body = (await pg.inner_text("body")) or ""
            print("código não passou (talvez expirado/errado). body[:300]:", repr(body[:300]))
        await br.close()


async def cmd_status():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        br = await pw.chromium.connect_over_cdp(CDP)
        pg, _ = await _fv_page(br)
        est = await _estado(pg)
        sinal = {"dentro": "LOGADO", "mfa": "MFA_PENDENTE", "login": "PRECISA_LOGIN",
                 "ocupada": "SESSAO_OCUPADA"}.get(est, "ERRO")
        print("STATE:", est, "| url:", pg.url, "| title:", await pg.title())
        _emit_sinal(sinal, pg.url)
        await br.close()


async def _digitar_codigo_e_ok(pg, codigo: str) -> None:
    """Fecha janelas de erro, acha a janela MFA pelo texto, digita o código, marca 30 dias e Ok (JS)."""
    await pg.evaluate(r"""()=>{[...document.querySelectorAll('.v-window')].forEach(w=>{
        const t=(w.innerText||'').toLowerCase();
        if(t.includes('incorret')||t.includes('erro')){const x=w.querySelector('.v-window-closebox'); if(x)x.click();}});}""")
    await pg.wait_for_timeout(400)
    try:
        ci = await pg.query_selector("xpath=//*[contains(@class,'v-window')][contains(.,'Multifator') or contains(.,'Código') or contains(.,'Dispensar')]//input[@type='password']")
        if ci:
            await ci.click(); await ci.fill(""); await ci.type(codigo.strip(), delay=40)
    except Exception as exc:
        logger.warning("falha ao digitar código MFA na janela: %s", exc)
    await pg.evaluate(r"""()=>{const W=[...document.querySelectorAll('.v-window')].find(w=>/multifator|código|dispensar/i.test(w.innerText||''));
        if(!W)return; const c=W.querySelector('input[type=checkbox]'); if(c&&!c.checked)c.click();}""")
    await pg.wait_for_timeout(250)
    await pg.evaluate(r"""()=>{const W=[...document.querySelectorAll('.v-window')].find(w=>/multifator|código|dispensar/i.test(w.innerText||''));
        if(!W)return; const b=[...W.querySelectorAll('.v-button,[role=button]')].find(x=>/(^|\b)ok\b/i.test((x.innerText||'').trim())); if(b)b.click();}""")
    await pg.wait_for_timeout(5000)


async def cmd_auto(timeout_s: int = 240):
    """Ciclo COMPLETO e auto-sinalizante (operável por IA fraca / cron):
    login -> marca 30 dias -> avisa Jorge no Telegram -> LÊ o código no log do Hermes -> Ok -> salva.
    Idempotente: se já está logado, só confirma. Sinais em data/sei_cache/flexvision_sinal.json."""
    import time
    from playwright.async_api import async_playwright
    from compliance_agent.envfile import carregar_env
    carregar_env()
    try:
        from compliance_agent import siafe_coord
    except Exception:
        siafe_coord = None
    u = (os.environ.get("SIAFE_USER") or "").strip()
    p = (os.environ.get("SIAFE_PASS") or "").strip()
    async with async_playwright() as pw:
        br = await pw.chromium.connect_over_cdp(CDP)
        ctx = br.contexts[0] if br.contexts else await br.new_context()
        pg, _ = await _fv_page(br)
        # 1) já logado?
        if await _estado(pg) == "dentro":
            await ctx.storage_state(path=str(_STATE))
            _emit_sinal("LOGADO", "já estava logado"); await br.close(); return
        # 2) login em aba limpa
        for c in br.contexts:
            for old in list(c.pages):
                if "flexvision" in (old.url or "").lower():
                    try: await old.close()
                    except Exception as exc: logger.debug("auto: falha ao fechar aba FV antiga: %s", exc)
        pg = await ctx.new_page()
        await pg.goto(FV, wait_until="domcontentloaded", timeout=45000)
        await pg.wait_for_timeout(3500)
        ut = await pg.query_selector("input[type=text]"); pt = await pg.query_selector("input[type=password]")
        if ut and pt:
            await ut.click(); await ut.fill(""); await ut.type(u, delay=25)
            await pt.click(); await pt.fill(""); await pt.type(p, delay=25); await pg.wait_for_timeout(150)
            await pg.click("xpath=//*[contains(@class,'v-button')][normalize-space()='Login' or .//span[normalize-space()='Login']]")
            await pg.wait_for_timeout(2500)
            await _pos_login_dialogos(pg)
        if await _estado(pg) == "dentro":
            await ctx.storage_state(path=str(_STATE)); _emit_sinal("LOGADO", "entrou sem MFA"); await br.close(); return
        if await _estado(pg) != "mfa":
            _emit_sinal("PRECISA_LOGIN", "login não chegou ao MFA"); await br.close(); return
        # 3) marca 30 dias + avisa Jorge; registra baseline do log
        await pg.evaluate(r"""()=>{const W=[...document.querySelectorAll('.v-window')].find(w=>/multifator|código|dispensar/i.test(w.innerText||''));
            if(!W)return; const c=W.querySelector('input[type=checkbox]'); if(c&&!c.checked)c.click();}""")
        base = len(_codigos_no_log())
        if siafe_coord:
            siafe_coord.notificar("🔐 FlexVision: MFA disparado (caixa '30 dias' marcada). "
                                  "Me manda AQUI o CÓDIGO do e-mail que eu entro sozinho. (expira em minutos)")
        _emit_sinal("MFA_PENDENTE", "aguardando código no log do Hermes")
        # 4) poll do log do Hermes por um código NOVO; tenta cada novo até logar
        t0 = time.time(); tentados = set()
        while time.time() - t0 < timeout_s:
            cods = _codigos_no_log()
            novos = [c for c in cods[base:] if _parece_codigo(c) and c not in tentados]
            for cod in novos:
                tentados.add(cod)
                await _digitar_codigo_e_ok(pg, cod)
                if await _estado(pg) == "dentro":
                    await ctx.storage_state(path=str(_STATE))
                    _emit_sinal("LOGADO", f"código {cod} aceito"); await br.close(); return
                print(f"código {cod} não passou; aguardando próximo…", flush=True)
            await asyncio.sleep(4)
        _emit_sinal("MFA_FALHOU", f"sem código válido em {timeout_s}s"); await br.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "login":
        asyncio.run(cmd_login())
    elif cmd == "code":
        asyncio.run(cmd_code(sys.argv[2] if len(sys.argv) > 2 else ""))
    elif cmd == "auto":
        asyncio.run(cmd_auto(int(sys.argv[2]) if len(sys.argv) > 2 else 240))
    else:
        asyncio.run(cmd_status())
