# -*- coding: utf-8 -*-
"""
SIAFE - lista TODOS os contratos de um fornecedor (por CNPJ) via Playwright.
✅ MÉTODO QUE FUNCIONA (validado 2026-06-04 com MGS CLEAN: 41 contratos, R$146,7mi).

Pré-requisito: estar LOGADO no SIAFE num Chrome com --remote-debugging-port=9222,
e na tela Execução > Contratos e Convênios > Contrato (a grade de contratos aberta).
(O login + navegação por menu ADF ainda é instável de automatizar em sessão nova;
 por ora faça login/navegação manual OU via o fluxo do siafe_browser.py, e rode isto.)

Uso: python siafe_contratos.py 19088605000104

SEGREDOS DESCOBERTOS (o que faz funcionar):
1) O painel de filtro abre pelo disclosure 'pt1:tblContrato:sdtFilter::disAcr'
   (NÃO pelo texto "Filtro", que tem onclick=return false).
2) Propriedade '7' = Cod. Contratado; Operador '0' = igual.
3) ⚠️ O valor PRECISA ser DIGITADO (keyboard.type) — o ADF só dispara a query com
   keystrokes reais. fill() NÃO aplica o filtro. Depois Enter.
"""
import os
import sys
import re
import json
import time
from playwright.sync_api import sync_playwright

def filtrar(cnpj_digits):
    with sync_playwright() as pw:
        b = pw.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=40000)
        pg = None
        for ctx in b.contexts:
            for p in ctx.pages:
                if "siafe2.fazenda" in (p.url or "") and "contrato" in (p.url or "").lower():
                    pg = p
        if not pg:
            for ctx in b.contexts:
                for p in ctx.pages:
                    if "siafe2.fazenda" in (p.url or ""): pg = p
        if not pg:
            print("ERRO: abra o SIAFE logado na tela Contrato (porta 9222)."); return
        def has_filter(): return pg.evaluate("()=>!!document.querySelector('[id*=table_rtfFilter]')")
        def click_vis(i):
            c = pg.evaluate("""(id)=>{for(let e of document.querySelectorAll('[id=\"'+id+'\"]')){let r=e.getBoundingClientRect();if(r.width>0&&r.height>0)return{x:r.left+r.width/2,y:r.top+r.height/2}}return null}""", i)
            if c: pg.mouse.click(c["x"], c["y"]); return True
            return False
        for t in ("OK", "Sim"):
            try:
                e = pg.get_by_text(t, exact=True).first
                if e.is_visible(timeout=1000): e.click(); time.sleep(1)
            except Exception: pass
        if not has_filter():
            click_vis("pt1:tblContrato:sdtFilter::disAcr"); time.sleep(2.5)
        P = '[id="pt1:tblContrato:table_rtfFilter:0:cbx_col_sel_rtfFilter::content"]:visible'
        O = '[id="pt1:tblContrato:table_rtfFilter:0:cbx_op_sel_rtfFilter::content"]:visible'
        pg.locator(P).first.select_option("7"); time.sleep(2.5)       # Cod. Contratado
        pg.locator(O).first.select_option("0"); time.sleep(2.5)       # igual
        v = pg.locator('[id*="table_rtfFilter:0"] input[type="text"]:visible').last
        v.click(); v.press("Control+a"); v.press("Delete")
        pg.keyboard.type(cnpj_digits, delay=80)                       # DIGITAR (essencial!)
        pg.keyboard.press("Enter"); time.sleep(6)
        rows = pg.evaluate("""()=>{let tb=[...document.querySelectorAll('table')].sort((a,b)=>b.querySelectorAll('tr').length-a.querySelectorAll('tr').length)[0];if(!tb)return[];let o=[];for(let tr of tb.querySelectorAll('tr')){let c=[...tr.querySelectorAll('td')].map(td=>(td.textContent||'').replace(/\\s+/g,' ').trim());if(c.length>=5)o.push(c);}return o;}""")
        rows = [r for r in rows if cnpj_digits in " ".join(r)]
        def val(s):
            m = re.search(r'([\d\.]+,\d{2})', s or ''); return float(m.group(1).replace('.','').replace(',','.')) if m else 0.0
        tot = sum(val(r[11]) for r in rows if len(r) > 11)
        print("CONTRATOS:", len(rows), "| VALOR TOTAL: R$ %s" % "{:,.2f}".format(tot))
        for r in rows:
            if len(r) > 11:
                print("  R$ %15s | %-18s | %s" % ("{:,.2f}".format(val(r[11])), (r[2] or r[1] or r[0])[:18], r[6][:32]))
        _cache = os.environ.get("JFN_DATA_DIR") and os.path.join(os.environ["JFN_DATA_DIR"], "sei_cache") \
            or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "sei_cache")
        os.makedirs(_cache, exist_ok=True)
        json.dump(rows, open(os.path.join(_cache, "siafe_contratos_%s.json" % cnpj_digits), "w", encoding="utf-8"), ensure_ascii=False)

if __name__ == "__main__":
    cnpj = re.sub(r"\D", "", sys.argv[1] if len(sys.argv) > 1 else "19088605000104")
    filtrar(cnpj)
