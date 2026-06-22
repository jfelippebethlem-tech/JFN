#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DEBUG do search por Interessado: loga, abre Pesquisa, digita o CNPJ no Contato, espera o autocomplete
e DUMPA o estado (dropdown, hidden, botões) — sem submeter. Descobre por que trava. VM-guarded."""
import asyncio, json, sys
from pathlib import Path
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from tools.vm_guard import preflight, cleanup_orphans

TERMO = sys.argv[1] if len(sys.argv) > 1 else "19.088.605/0001-04"


async def main():
    from playwright.async_api import async_playwright
    from tools.sei_session import abrir_sessao
    async with async_playwright() as pw:
        b, ctx, pg, ok = await abrir_sessao(pw)
        try:
            if not ok:
                print(json.dumps({"ok": False, "erro": "login"})); return
            await pg.evaluate(r"""()=>{const e=[...document.querySelectorAll('a')].find(a=>/^pesquisa$/i.test((a.innerText||'').trim())||/protocolo_pesquisar\b/i.test(a.href||a.getAttribute('onclick')||''));if(e)e.click();}""")
            await pg.wait_for_timeout(5000)
            # estado do campo Contato + campos ocultos antes
            est0 = await pg.evaluate(r"""()=>{
              const c=document.getElementById('txtContato');
              const hid=[...document.querySelectorAll('input[type=hidden]')].filter(e=>/contato|interess|protocolo/i.test((e.id||'')+(e.name||''))).map(e=>({id:e.id||e.name,v:e.value}));
              return {tem_txtContato:!!c, hidden:hid};}""")
            # digita devagar (autocomplete reage a keystrokes)
            try:
                await pg.click("#txtContato")
                await pg.fill("#txtContato", "")
                await pg.type("#txtContato", TERMO, delay=120)
            except Exception as e:
                print("erro digitar:", e)
            await pg.wait_for_timeout(5000)  # espera AJAX
            est1 = await pg.evaluate(r"""()=>{
              const drop=[...document.querySelectorAll('ul.ui-autocomplete li, li.ui-menu-item, div.ajax_result, div.autocomplete, .ui-menu-item-wrapper')];
              const vis=drop.filter(e=>e.offsetParent!==null);
              const c=document.getElementById('txtContato');
              const hid=[...document.querySelectorAll('input[type=hidden]')].filter(e=>e.value&&/contato|interess/i.test((e.id||'')+(e.name||''))).map(e=>({id:e.id||e.name,v:e.value}));
              return {valor_campo:c?c.value:null, n_drop:drop.length, n_drop_visivel:vis.length,
                      amostra_drop:drop.slice(0,6).map(e=>(e.innerText||'').trim().slice(0,70)),
                      hidden_setados:hid};}""")
            # tenta selecionar a opção MGS e ver se o hidden seta
            sel = await pg.evaluate(r"""()=>{
              const op=[...document.querySelectorAll('ul.ui-autocomplete li, li.ui-menu-item, .ui-menu-item-wrapper, div.ajax_result a, a, li')]
                .find(e=>{const s=(e.innerText||'').toUpperCase();return s.includes('MGS')||s.includes('19.088')||s.includes('19088605');});
              if(op){op.scrollIntoView&&op.scrollIntoView();op.click();return (op.innerText||'').trim().slice(0,80);}
              return null;}""", )
            await pg.wait_for_timeout(1500)
            est2 = await pg.evaluate(r"""()=>{
              const hid=[...document.querySelectorAll('input[type=hidden]')].filter(e=>e.value&&/contato|interess/i.test((e.id||'')+(e.name||''))).map(e=>({id:e.id||e.name,v:(e.value||'').slice(0,40)}));
              const c=document.getElementById('txtContato');
              return {valor_campo:c?c.value:null, hidden_setados:hid};}""")
            print(json.dumps({"ok": True, "antes": est0, "pos_digitar": est1,
                              "opcao_clicada": sel, "pos_clique": est2}, ensure_ascii=False, indent=1))
        finally:
            await b.close()


if __name__ == "__main__":
    ok, motivo = preflight()
    if not ok:
        print(json.dumps({"ok": False, "vm_guard": motivo})); sys.exit(1)
    cleanup_orphans()
    try:
        asyncio.run(main())
    finally:
        cleanup_orphans()
