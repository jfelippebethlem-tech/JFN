#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Busca SEI por TEXTO LIVRE (campo 'q' do form avançado) com a mecânica PROVADA do _ler_cracked
(#sbmPesquisar UMA vez + expect_navigation). Lista os processos onde o termo aparece — usado p/
enumerar os processos de pagamento/execução da MGS no ITERJ (ciclos 2022-2023, unidade 330020/330005).
VM-guarded. Uso: sei_busca_mgs.py "MGS CLEAN" [--docs]   (--docs = Considerar Documentos)."""
import asyncio, json, sys
sys.path.insert(0, "/home/ubuntu/JFN")
from tools import sei_reader as SR
from tools.vm_guard import preflight, cleanup_orphans

import re
TERMO = next((a for a in sys.argv[1:] if not a.startswith("--")), "MGS CLEAN")
DOCS = "--docs" in sys.argv
ORGAO = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--orgao=")), "")  # regex p/ texto da opção
DE = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--de=")), "")       # dd/mm/aaaa
ATE = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--ate=")), "")
LISTAORGAOS = "--listorgaos" in sys.argv
INTERESSADO = "--interessado" in sys.argv  # busca ESTRUTURADA por Contato/Interessado (não full-text)


async def main():
    from playwright.async_api import async_playwright
    from tools.sei_session import abrir_sessao
    async with async_playwright() as pw:
        b, ctx, pg, ok = await abrir_sessao(pw)  # reusa a sessão salva (sem flap do WAF)
        try:
            if not ok:
                print(json.dumps({"ok": False, "erro": "login"})); return
            # abrir Pesquisa (clique REAL preserva sessão)
            await pg.evaluate(r"""()=>{const e=[...document.querySelectorAll('a')].find(a=>/^pesquisa$/i.test((a.innerText||'').trim())||/protocolo_pesquisar\b/i.test(a.href||a.getAttribute('onclick')||''));if(e)e.click();}""")
            await pg.wait_for_timeout(5000)
            if LISTAORGAOS:
                ops = await pg.evaluate(r"""()=>{const s=document.getElementById('selOrgaoPesquisa');return s?[...s.options].map(o=>o.text.trim()).filter(Boolean):[];}""")
                print(json.dumps({"ok": True, "orgaos": ops}, ensure_ascii=False, indent=1)); return
            # MODO INTERESSADO: campo Contato + autocomplete + checkbox Interessado (lista só processos onde MGS é parte)
            inter_dbg = None
            if INTERESSADO:
                await pg.evaluate(r"""(t)=>{const c=document.getElementById('txtContato');
                  if(c){c.value=t;c.focus();c.dispatchEvent(new Event('input',{bubbles:true}));c.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true,key:'a'}));}}""", TERMO)
                await pg.wait_for_timeout(4000)  # espera o AJAX do autocomplete
                inter_dbg = await pg.evaluate(r"""(t)=>{
                  const T=t.toUpperCase().replace(/[^0-9A-Z]/g,'').slice(0,8);
                  const cand=[...document.querySelectorAll('ul.ui-autocomplete li, li.ui-menu-item, div.ajax_result a, a, li, div')]
                    .filter(e=>{const s=(e.innerText||'').toUpperCase().replace(/[^0-9A-Z ]/g,'');return s&&(s.includes('MGS')||s.includes('19088605'))&&s.length<140;});
                  if(cand.length){cand[0].click();return {sel:(cand[0].innerText||'').trim().slice(0,90)};}
                  return {sel:null, amostra:[...document.querySelectorAll('li,div.ajax_result a')].map(e=>(e.innerText||'').trim()).filter(Boolean).slice(0,8)};}""", TERMO)
                await pg.wait_for_timeout(500)
                await pg.evaluate(r"""()=>{const c=document.getElementById('chkSinInteressado'); if(c&&!c.checked)c.click();}""")
            # setup: radio Processos + texto q + Órgão (filtra/limpa) + Restringir DESMARCADO + Docs + datas
            setup = await pg.evaluate(r"""(o)=>{
              const hit=[];
              const rp=document.getElementById('optProcessos'); if(rp&&!rp.checked){rp.click();hit.push('optProcessos');}
              const q=document.getElementById('q'); if(q&&!o.inter){q.value=o.termo;q.dispatchEvent(new Event('input',{bubbles:true}));hit.push('q');}
              const so=document.getElementById('selOrgaoPesquisa');
              if(so){[...so.options].forEach(x=>x.selected=false);
                if(o.orgao){const re=new RegExp(o.orgao,'i');let n=0;[...so.options].forEach(x=>{if(re.test(x.text)){x.selected=true;n++;}});hit.push('orgao:sel='+n);}
                else hit.push('orgao:limpo');
                so.dispatchEvent(new Event('change',{bubbles:true}));}
              const ro=document.getElementById('chkSinRestringirOrgao'); if(ro&&ro.checked){ro.click();hit.push('restringir:off');}
              const cd=document.getElementById('chkSinConsiderarDocumentos');
              if(cd){ if(o.docs&&!cd.checked){cd.click();hit.push('docs:on');} if(!o.docs&&cd.checked){cd.click();hit.push('docs:off');} }
              if(o.de){const e=document.getElementById('txtDataInicio'); if(e){e.value=o.de;e.dispatchEvent(new Event('input',{bubbles:true}));hit.push('de');}}
              if(o.ate){const e=document.getElementById('txtDataFim'); if(e){e.value=o.ate;e.dispatchEvent(new Event('input',{bubbles:true}));hit.push('ate');}}
              return hit;
            }""", {"termo": TERMO, "docs": DOCS, "orgao": ORGAO, "de": DE, "ate": ATE, "inter": INTERESSADO})
            await pg.wait_for_timeout(800)
            # diagnóstico do submit: o botão #sbmPesquisar existe mesmo?
            diag = await pg.evaluate(r"""()=>{
              const b=document.querySelector('#sbmPesquisar');
              const todos=[...document.querySelectorAll('button,input[type=submit],input[type=button]')]
                .filter(e=>/pesquisar/i.test(e.value||e.innerText||'')).map(e=>(e.id||e.value||e.innerText||'').trim().slice(0,30));
              return {tem_sbmPesquisar:!!b, botoes_pesquisar:todos};
            }""")
            # submit PROVADO: #sbmPesquisar uma vez + expect_navigation
            try:
                async with pg.expect_navigation(wait_until="domcontentloaded", timeout=35000):
                    await pg.evaluate(r"""()=>{const b=document.querySelector('#sbmPesquisar');if(b){b.click();return;}const f=document.querySelector('#frmProtocoloPesquisa,form[action*=protocolo_pesquisar],form[action*=pesquisa]');if(f)f.submit();}""")
            except Exception:
                pass
            try:
                await pg.wait_for_load_state("networkidle", timeout=25000)
            except Exception:
                pass
            await pg.wait_for_timeout(3000)
            txt0 = await pg.inner_text("body")
            reg = (re.search(r"Lista de Processos[^\d]*\((\d+)\s+registro", txt0, re.I)
                   or re.search(r"\((\d+)\s+registro", txt0, re.I) or [None, None])[1]
            # pares tipo↔número, percorrendo TODAS as páginas
            achados: dict[str, str] = {}

            async def colher():
                for _ in range(3):
                    try:
                        await pg.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                    try:
                        return await _colher_eval()
                    except Exception:
                        await pg.wait_for_timeout(2000)
                return None

            async def _colher_eval():
                pares = await pg.evaluate(r"""()=>{
                  const out=[]; let tipo='';
                  document.querySelectorAll('a,span,td,div').forEach(e=>{
                    const s=(e.innerText||'').replace(/\s+/g,' ').trim();
                    const m=s.match(/(?:(.+?)\s+N[ºo°]\s*)?SEI[- ]?(\d{6}\/\d{6}\/\d{4})/);
                    if(m){ if(m[1])tipo=m[1].trim().slice(0,70); out.push([m[2], (m[1]||tipo||'').trim().slice(0,70)]); }
                  });
                  return out;}""")
                for num, tipo in pares:
                    achados.setdefault(num, tipo or achados.get(num, ""))

            await colher()
            for _ in range(5):  # paginação (capada — antes travava em 20×networkidle)
                antes = len(achados)
                try:
                    prox = await pg.evaluate(r"""()=>{const a=[...document.querySelectorAll('a')].find(e=>/pr[oó]xim|seguinte|^›$|^»$/i.test(((e.innerText||'')+' '+(e.title||'')).trim())&&!/desabilit|disabled/i.test(e.className||''));if(a){a.click();return true;}return false;}""")
                except Exception:
                    break
                if not prox:
                    break
                await pg.wait_for_timeout(2500)
                await colher()
                if len(achados) == antes:  # não cresceu → fim
                    break
            pagamentos = {n: t for n, t in achados.items() if re.search(r"pagament", t, re.I)}
            print(json.dumps({"ok": True, "termo": TERMO, "modo": ("interessado" if INTERESSADO else "fulltext"),
                              "considerar_docs": DOCS, "setup": setup, "interessado_dbg": inter_dbg,
                              "diag_submit": diag, "n_registros": reg, "n_total": len(achados),
                              "n_pagamentos": len(pagamentos),
                              "pagamentos": dict(sorted(pagamentos.items())),
                              "todos": dict(sorted(achados.items()))},
                             ensure_ascii=False, indent=1))
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
