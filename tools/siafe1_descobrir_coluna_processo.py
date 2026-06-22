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
            lg = await M._login(pg, ex)
            if not lg.get("ok"):
                return {"ok": False, "etapa": "login", **lg}
            nav = await M._navegar(pg)
            if not nav.get("ok"):
                return {"ok": False, "etapa": "nav", **nav}
            await pg.wait_for_timeout(2000)
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
            out = {"ok": True, "colunas_exibidas": heads, "menus": menus}
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
