#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DESCOBERTA: o SIAFE-1 TEM o nº do Processo SEI (dono confirmou), mas o grid OB Orçamentária mostra 19
colunas por padrão (sem Processo). Este script loga, abre o grid e dumpa o SELETOR DE COLUNAS (menu ADF
Ver/Colunas) + qualquer referência a 'Processo' — p/ habilitar a coluna e recuperar o nº SEI de 2021-2023.
VM-guarded. Salva data/sei_cache/siafe1_colunas.json."""
import asyncio, json, os, sys
from pathlib import Path
os.environ["JFN_SIAFE_LOGIN_URL"] = "https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from tools.vm_guard import preflight, cleanup_orphans
import compliance_agent.siafe_ob_orcamentaria as M
from playwright.async_api import async_playwright


async def run(ex=2023):
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
                                  viewport={"width": 1600, "height": 1000},
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            # RETRY EXTERNO do login: o WAF da SEFAZ (interstício IP) é intermitente — re-tenta até passar.
            lg = {}
            for tent in range(6):
                lg = await M._login(pg, ex)
                if lg.get("ok"):
                    print(f"   login OK na tentativa {tent+1}", flush=True); break
                print(f"   login flap WAF (tentativa {tent+1}/6) — re-tentando…", flush=True)
                await pg.wait_for_timeout(8000)
            if not lg.get("ok"):
                return {"ok": False, "etapa": "login", **lg}
            nav = {}
            for tent in range(3):
                nav = await M._navegar(pg)
                if nav.get("ok"):
                    break
                await pg.wait_for_timeout(4000)
            if not nav.get("ok"):
                return {"ok": False, "etapa": "nav", **nav}
            await pg.wait_for_timeout(2500)
            # SCREENSHOT JÁ (antes de qualquer eval frágil) — pra eu VER o grid e achar o seletor de colunas
            try:
                await pg.screenshot(path=str(REPO / "data/sei_cache/siafe1_grid.png"))
                print("   screenshot salvo", flush=True)
            except Exception as e:
                print(f"   screenshot falhou: {e}", flush=True)
            # tenta abrir o menu 'Ver/Ações' do painel da tabela (ADF) p/ revelar 'Colunas'
            try:
                await pg.evaluate(r"""()=>{const m=[...document.querySelectorAll('a,div,span')].find(e=>/^(ver|a[çc][õo]es|exibir)$/i.test((e.innerText||'').trim()));if(m)m.click();}""")
                await pg.wait_for_timeout(1500)
                await pg.screenshot(path=str(REPO / "data/sei_cache/siafe1_grid_menu.png"))
            except Exception:
                pass
            # 1) colunas atualmente exibidas
            heads = await pg.evaluate(r"""()=>[...document.querySelectorAll('th, .af_column_columnHeader, [id*=column]')].map(e=>(e.innerText||'').trim()).filter(Boolean).slice(0,40)""")
            # 2) toolbar/menus do panelCollection (Ver, Colunas, Exibir...) + qualquer item 'Processo'/'Coluna'
            menus = await pg.evaluate(r"""()=>{
              const out={toolbar:[],itens_menu:[],processo_refs:[]};
              document.querySelectorAll('a,div[role=menuitem],span,button,td').forEach(e=>{
                const s=(e.innerText||'').trim();
                if(!s||s.length>40) return;
                if(/^(ver|colunas?|exibir|gerenciar|painel|view|columns?|mostrar|ocultar)$/i.test(s)) out.toolbar.push({t:s,id:e.id||''});
                if(/coluna|column|processo|exibir/i.test(s)) out.itens_menu.push(s);
                if(/processo/i.test(s)) out.processo_refs.push({t:s,id:e.id||''});
              });
              out.toolbar=[...new Set(out.toolbar.map(JSON.stringify))].map(JSON.parse).slice(0,15);
              out.itens_menu=[...new Set(out.itens_menu)].slice(0,30);
              return out;}""")
            # 3) DUMP da toolbar/ícones ADF (a, img, botões com id/title) p/ achar 'Ver>Colunas' ou 'Detalhar'
            toolbar_full = await pg.evaluate(r"""()=>{
              const out=[];
              document.querySelectorAll('a,img,button,div[role=button],[onclick]').forEach(e=>{
                const t=(e.getAttribute&&(e.getAttribute('title')||e.getAttribute('alt'))||'').trim();
                const s=(e.innerText||'').trim();
                const id=e.id||'';
                if((t||s) && (t.length<40||s.length<40) && /coluna|column|ver|detalh|exibir|painel|gerenc|config|menu|consul|abrir|selec/i.test(t+' '+s+' '+id))
                  out.push({id:id.slice(-40), title:t.slice(0,40), txt:s.slice(0,30)});
              });
              return out.slice(0,40);}""")
            # 4) SCREENSHOT + HTML da toolbar do panelCollection (ver a estrutura real, sem adivinhar)
            try:
                await pg.screenshot(path=str(REPO / "data/sei_cache/siafe1_grid.png"), full_page=False)
            except Exception:
                pass
            toolbar_html = await pg.evaluate(r"""()=>{
              // acha o panelCollection/toolbar que envolve a tabela tblOBOrcamentaria
              let el=document.querySelector('[id*=tblOBOrcamentaria]');
              let pc=el; for(let i=0;i<8 && pc;i++){ if((pc.className||'').match(/panelCollection|PanelCollection/)) break; pc=pc.parentElement; }
              const tb=(pc||document).querySelector('[class*=toolbar],[class*=Toolbar]');
              return {pc_class:(pc&&pc.className||'').slice(0,60), toolbar_html:(tb&&tb.outerHTML||'').slice(0,2500)};}""")
            out = {"ok": True, "colunas_exibidas": heads, "menus": menus, "toolbar_full": toolbar_full,
                   "toolbar_html": toolbar_html}
            (REPO / "data/sei_cache/siafe1_colunas.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return out
        finally:
            await b.close()


if __name__ == "__main__":
    ok, motivo = preflight()
    if not ok:
        print(json.dumps({"ok": False, "vm_guard": motivo})); sys.exit(1)
    cleanup_orphans()
    try:
        asyncio.run(run())
    finally:
        cleanup_orphans()
