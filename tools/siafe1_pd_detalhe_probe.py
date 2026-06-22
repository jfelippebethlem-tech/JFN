#!/usr/bin/env python3
"""PROBE ÚNICO (não-loop, 1 login): abre o DETALHE do PD 2022PD00914 no SIAFE-1 legado
(www5/SiafeRio) e dumpa o DOM para localizar o Processo SEI. O drill anterior só fazia
quick-search+scrape (voltou vazio); aqui seleciono a linha + btnView com CLIQUE REAL (§6)
e leio o painel de detalhe. Reusa M._login + M._click_real (validados). VM-guarded, foreground.
Saída: data/sei_cache/siafe1_pd_detalhe_probe.json — Processo se achar, OU mapa do DOM p/ fechar."""
import asyncio, json, os, sys, traceback
from pathlib import Path

os.environ["JFN_SIAFE_LOGIN_URL"] = "https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from tools.vm_guard import preflight, cleanup_orphans
import compliance_agent.siafe_ob_orcamentaria as M
from playwright.async_api import async_playwright

PD = "2022PD00914"
MENU = "Acompanhamento de Execução de PD"
O = {"pd": PD}


async def run(ex=2022):
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
                                  timezone_id="America/Sao_Paulo", viewport={"width": 1600, "height": 1000})
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            lg = await M._login(pg, ex)
            O["login"] = lg.get("ok")
            if not lg.get("ok"):
                O["etapa"] = "login"; return O
            # menu: Execução > Execução Financeira > Acompanhamento de PD (JS click — nav validado no drill)
            for label in ("Execução", "Execução Financeira", MENU):
                await pg.evaluate("""(t)=>{const a=[...document.querySelectorAll('a')].find(e=>(e.innerText||'').trim()===t);if(a)a.click();}""", label)
                await pg.wait_for_timeout(1800)
            # busca o PD na caixa de consulta rápida + Enter
            try:
                await pg.fill('[id="pt1:iTxtCad::content"]', PD, timeout=6000)
            except Exception:
                await pg.evaluate("""(v)=>{const e=document.getElementById('pt1:iTxtCad::content');if(e){e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}));}}""", PD)
            await pg.keyboard.press("Enter"); await pg.wait_for_timeout(3500)
            # MAPA do DOM: tabelas, linhas (com a que casa o PD), botões view/visualizar
            O["dom"] = await pg.evaluate(r"""(pd)=>{
                const tables=[...document.querySelectorAll('table')].map(t=>t.id).filter(Boolean).slice(0,20);
                const rows=[...document.querySelectorAll('tr')].map((r,i)=>({i,id:r.id||'',txt:(r.innerText||'').replace(/\s+/g,' ').trim().slice(0,120)})).filter(r=>r.txt).slice(0,40);
                const hit=rows.find(r=>r.txt.includes(pd));
                const btns=[...document.querySelectorAll('a,button,div,img')].filter(e=>/view|visualiz|detalh/i.test((e.id||'')+' '+(e.title||''))).map(e=>({id:e.id||'',title:e.title||''})).filter(x=>x.id).slice(0,20);
                return {tables,rows,hit:hit||null,btns};
            }""", PD)
            hit = O["dom"].get("hit")
            if hit and hit.get("id"):
                await M._click_real(pg, hit["id"]); await pg.wait_for_timeout(1200)
                for bt in O["dom"].get("btns", []):
                    if bt.get("id"):
                        await M._click_real(pg, bt["id"]); await pg.wait_for_timeout(2500); O["btn_view"] = bt["id"]; break
                await pg.screenshot(path=str(REPO / "data/sei_cache/siafe1_pd_detalhe_probe.png"))
                O["detalhe"] = await pg.evaluate(r"""()=>{
                    const t=document.body.innerText||'';
                    const grab=(re)=>[...new Set((t.match(re)||[]))].slice(0,15);
                    const lbl=[...document.querySelectorAll('label,span,td,div,input')].map(e=>((e.innerText||'')+' '+(e.value||'')).trim()).filter(s=>/processo|documento h|nota de liquid|\d{4}NL\d+|empenh/i.test(s)&&s.length<160);
                    return {processo_sei: grab(/\d{5,}[\/.\-]\d{4,6}[\/.\-]?\d*/g), NL: grab(/\d{4}NL\d+/g), NE: grab(/\d{4}NE\d+/g), labels:[...new Set(lbl)].slice(0,30)};
                }""")
            return O
        except Exception:
            O["tb"] = traceback.format_exc()[-700:]; return O
        finally:
            (REPO / "data/sei_cache/siafe1_pd_detalhe_probe.json").write_text(
                json.dumps(O, ensure_ascii=False, indent=1), encoding="utf-8")
            await b.close()


if __name__ == "__main__":
    ok, motivo = preflight()
    if not ok:
        print(json.dumps({"ok": False, "vm_guard": motivo}, ensure_ascii=False)); sys.exit(1)
    cleanup_orphans()
    try:
        print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=1)[:2500])
    finally:
        cleanup_orphans()
