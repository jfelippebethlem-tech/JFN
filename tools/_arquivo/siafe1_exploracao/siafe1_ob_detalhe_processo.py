#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SIAFE-1: abre o DETALHE de uma OB (duplo-clique na linha do grid) e dumpa os campos do form p/ achar o
nº do Processo SEI (que NÃO está no grid de 19 colunas, mas EXISTE no detalhe — dono confirmou).
Robusto: captura traceback + screenshot em CADA passo; grava json mesmo em falha. NUNCA culpar acesso/WAF.
Salva data/sei_cache/siafe1_ob_detalhe.json + screenshots. VM-guarded."""
import asyncio
import json
import os
import sys
import traceback
from pathlib import Path
os.environ["JFN_SIAFE_LOGIN_URL"] = "https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from tools.vm_guard import preflight, cleanup_orphans
import compliance_agent.siafe_ob_orcamentaria as M
from playwright.async_api import async_playwright

SHOT = REPO / "data/sei_cache"
OUT = {"passos": []}


async def shot(pg, nome):
    try:
        await pg.screenshot(path=str(SHOT / f"siafe1_det_{nome}.png"))
        OUT["passos"].append(f"shot:{nome}")
    except Exception as e:
        OUT["passos"].append(f"shot_falhou:{nome}:{str(e)[:40]}")


async def run(ex=2023):
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
                                  viewport={"width": 1700, "height": 1000},
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            for t in range(6):
                lg = await M._login(pg, ex)
                if lg.get("ok"):
                    OUT["passos"].append(f"login_ok_t{t+1}"); break
                OUT["passos"].append(f"login_retry_{t+1}"); await pg.wait_for_timeout(8000)
            else:
                OUT["erro"] = "login não autenticou após 6 tentativas (NÃO é acesso — revisar fluxo)"; return OUT
            await shot(pg, "1_poslogin")
            nav = await M._navegar(pg)
            OUT["nav"] = nav
            await shot(pg, "2_posnav")
            if not nav.get("ok"):
                OUT["erro"] = "grid não apareceu"; return OUT
            await pg.wait_for_timeout(2000)
            # duplo-clique na 1ª linha de dados do grid p/ abrir o detalhe
            abriu = await pg.evaluate(r"""()=>{
              const tb=document.querySelector('[id*="tblOBOrcamentaria"]');
              if(!tb) return 'sem tabela';
              const linha=tb.querySelector('tr[_afrrk], tbody tr, .af_table_data-row, [id*=":0:"]');
              const cell=(linha&&linha.querySelector('td,span'))||linha;
              if(cell){const r=cell.getBoundingClientRect();
                ['mousedown','mouseup','click','dblclick'].forEach(t=>cell.dispatchEvent(new MouseEvent(t,{bubbles:true,clientX:r.x+5,clientY:r.y+5})));
                return 'dblclick enviado';}
              return 'sem linha';}""")
            OUT["abrir_detalhe"] = abriu
            await pg.wait_for_timeout(2500)
            # ESTRATÉGIA A: clicar o disclosure/twisty de expansão da 1ª linha (detailStamp ADF)
            OUT["A_twisty"] = await pg.evaluate(r"""()=>{
              const tw=document.querySelector('[id*="tblOBOrcamentaria"] a[id*=":0:"][id*="dt"], [id*="tblOBOrcamentaria"] td.af_table_column-disclosure a, [id*="tblOBOrcamentaria"] a[title*="xpand"], [id*="tblOBOrcamentaria"] img[src*="expand"]');
              if(tw){tw.click();return 'twisty:'+(tw.id||tw.title||'').slice(0,40);}
              return 'sem twisty';}""")
            await pg.wait_for_timeout(2500)
            await shot(pg, "A_twisty")
            campos_a = await pg.evaluate(r"""()=>{const o=[];document.querySelectorAll('*').forEach(e=>{const s=(e.innerText||'').trim();if(/processo/i.test(s)&&s.length<90)o.push(s)});return [...new Set(o)].slice(0,12);}""")
            OUT["A_processo"] = campos_a
            # ESTRATÉGIA B: botão-direito (context menu) na 1ª célula
            try:
                cell = await pg.query_selector('[id*="tblOBOrcamentaria"] td')
                if cell:
                    await cell.click(button="right")
                    await pg.wait_for_timeout(1500)
                    await shot(pg, "B_ctxmenu")
                    OUT["B_ctx_itens"] = await pg.evaluate(r"""()=>[...document.querySelectorAll('[role=menuitem],.af_menu_item,td')].map(e=>(e.innerText||'').trim()).filter(t=>t&&t.length<30).slice(0,20)""")
            except Exception as e:
                OUT["B_erro"] = str(e)[:60]
            await pg.wait_for_timeout(1500)
            # DUMP da toolbar inteira (todos os botões/links/imgs com id+title+texto) — sem filtro
            OUT["toolbar_botoes"] = await pg.evaluate(r"""()=>{
              const out=[];
              document.querySelectorAll('a,img,button,div[role=button],span[role=button]').forEach(e=>{
                const t=(e.getAttribute&&(e.getAttribute('title')||e.getAttribute('alt'))||'').trim();
                const s=(e.innerText||'').trim();
                const id=(e.id||'');
                if(t||s) out.push({id:id.slice(-45),title:t.slice(0,35),txt:s.slice(0,25)});
              });
              return out.slice(0,70);}""")
            # tenta clicar 'Ver' (menu de colunas do ADF panelCollection) e screenshot do submenu
            verclick = await pg.evaluate(r"""()=>{const m=[...document.querySelectorAll('a,div')].find(e=>{const s=(e.innerText||'').trim().toLowerCase();return s==='ver'||s==='detalhar';});if(m){m.click();return (m.innerText||'').trim();}return null;}""")
            OUT["ver_detalhar_click"] = verclick
            # DUMP de ids completos de TODOS os <a>/<img> da toolbar (ADF: id revela a função)
            OUT["anchor_ids"] = await pg.evaluate(r"""()=>{
              const out=[];
              document.querySelectorAll('a,img,div[role=menuitem]').forEach(e=>{
                const id=e.id||''; const cls=(e.className||'').toString();
                if(/cb\d|cni\d|cl\d|:m\d|detalh|ver|colun|menu|incluir|alterar|consultar|pesquis|exibir|toolbar/i.test(id+' '+cls))
                  out.push({id:id, cls:cls.slice(0,40), title:(e.getAttribute&&e.getAttribute('title')||'').slice(0,30)});
              });
              return out.slice(0,60);}""")
            await pg.wait_for_timeout(1500)
            await shot(pg, "3_detalhe")
            # dumpa TODOS os labels+valores do form do detalhe + procura 'Processo'
            campos = await pg.evaluate(r"""()=>{
              const out=[];
              document.querySelectorAll('label, .af_panelLabelAndMessage_label, [id*=label]').forEach(l=>{
                const t=(l.innerText||'').trim();
                if(t && t.length<40) out.push(t);
              });
              const proc=[];
              document.querySelectorAll('*').forEach(e=>{
                const s=(e.innerText||'').trim();
                if(/processo/i.test(s) && s.length<80) proc.push(s);
              });
              return {labels:[...new Set(out)].slice(0,60), processo_refs:[...new Set(proc)].slice(0,15)};}""")
            OUT["campos_detalhe"] = campos
            return OUT
        except Exception:
            OUT["traceback"] = traceback.format_exc()[-1500:]
            try:
                await shot(pg, "ERRO")
            except Exception:
                pass
            return OUT
        finally:
            (SHOT / "siafe1_ob_detalhe.json").write_text(json.dumps(OUT, ensure_ascii=False, indent=1), encoding="utf-8")
            await b.close()


if __name__ == "__main__":
    ok, motivo = preflight()
    if not ok:
        print(json.dumps({"ok": False, "vm_guard": motivo})); sys.exit(1)
    cleanup_orphans()
    try:
        print(json.dumps(asyncio.run(run()), ensure_ascii=False)[:600])
    finally:
        cleanup_orphans()
