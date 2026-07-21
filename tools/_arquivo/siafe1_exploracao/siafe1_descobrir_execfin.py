#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Descobre as funções de SIAFE 1 (www5) > Execução > Execução Financeira p/ localizar
'Nota de Liquidação' / 'Documento Hábil' / NF (o NL não está no grid de OB do SIAFE 1).
Salva data/sei_cache/siafe1_execfin_funcoes.json. VM-guarded (preflight + cleanup)."""
import asyncio
import json
import os
import sys
from pathlib import Path

os.environ["JFN_SIAFE_LOGIN_URL"] = "https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from tools.vm_guard import preflight, cleanup_orphans
import compliance_agent.siafe_ob_orcamentaria as M
from playwright.async_api import async_playwright

DUMP_ANCHORS = r"""()=>[...document.querySelectorAll('a,span.xta,div.xta')]
  .map(e=>({t:(e.innerText||'').trim(), id:e.id||''}))
  .filter(x=>x.t && x.t.length<60)"""

LIQ_WORDS = ['liquid', 'nota', 'document', 'fiscal', 'hábil', 'habil', 'despesa', 'empenh', 'ordem banc', 'pagamento']


async def run(ex=2023):
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
                                  timezone_id="America/Sao_Paulo", viewport={"width": 1600, "height": 1000})
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            lg = await M._login(pg, ex)
            if not lg.get("ok"):
                return {"ok": False, "etapa": "login", **lg}
            # Execução
            await pg.evaluate(r"""()=>{const a=[...document.querySelectorAll('a.xyo,a')].find(e=>(e.innerText||'').trim()==='Execução');if(a)a.click();}""")
            await pg.wait_for_timeout(1800)
            stage_exec = await pg.evaluate(DUMP_ANCHORS)
            # Execução Financeira
            await pg.evaluate(r"""()=>{const a=[...document.querySelectorAll('a.xyo,a')].find(e=>(e.innerText||'').trim()==='Execução Financeira');if(a)a.click();}""")
            await pg.wait_for_timeout(1800)
            stage_execfin = await pg.evaluate(DUMP_ANCHORS)
            # dedup + filtro de liquidação/NF
            todos = {(x['t'], x['id']) for x in (stage_exec + stage_execfin)}
            todos = [{"t": t, "id": i} for (t, i) in sorted(todos)]
            liq = [x for x in todos if any(w in x['t'].lower() for w in LIQ_WORDS)]
            out = REPO / "data/sei_cache/siafe1_execfin_funcoes.json"
            out.write_text(json.dumps({"ok": True, "n": len(todos), "todos": todos, "liquidacao": liq},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
            return {"ok": True, "n_itens": len(todos), "candidatos_NL_NF": liq, "arquivo": str(out)}
        finally:
            await b.close()


if __name__ == "__main__":
    ok, motivo = preflight()
    if not ok:
        print(json.dumps({"ok": False, "vm_guard": motivo}, ensure_ascii=False)); sys.exit(1)
    cleanup_orphans()
    try:
        r = asyncio.run(run())
        print(json.dumps(r, ensure_ascii=False, indent=1))
    finally:
        cleanup_orphans()
