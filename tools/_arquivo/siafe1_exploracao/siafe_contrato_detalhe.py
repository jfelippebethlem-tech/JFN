#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SIAFE: navega Execução > Contratos e Convênios, acha o contrato 005/2021 (MGS) e extrai o nº do
processo SEI da contratação + campos (vigência, valor, empenhos, anexos/planilha). Exploratório."""
import asyncio
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, "/home/ubuntu/JFN")
import compliance_agent.siafe_ob_orcamentaria as M
from playwright.async_api import async_playwright

ALVO = "005/2021"; CNPJ = "19088605000104"


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
              viewport={"width": 1600, "height": 1000},
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            lg = await M._login(pg, 2025)
            print("login SIAFE2:", lg.get("ok"), flush=True)
            if not lg.get("ok"):
                print("FALHA:", lg); return
            await pg.wait_for_timeout(2500)
            # Execução
            await pg.evaluate(r"""()=>{const a=[...document.querySelectorAll('a.xyo')].find(e=>(e.innerText||'').trim()==='Execução');if(a)a.click();}""")
            await pg.wait_for_timeout(1800)
            # Contratos e Convênios (disclosure)
            await pg.evaluate(r"""()=>{const a=[...document.querySelectorAll('a')].find(e=>/contratos e conv/i.test((e.innerText||'').trim()));if(a)a.click();}""")
            await pg.wait_for_timeout(2200)
            sub = await pg.evaluate(r"""()=>{const vis=el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height>0;};return [...document.querySelectorAll('a')].filter(a=>vis(a)).map(a=>(a.innerText||'').trim()).filter(t=>t.length>2&&t.length<50);}""")
            print("submenu Contratos e Convênios:", sorted(set(sub))[:30], flush=True)
            # clica em "Contratos" (a função de consulta de contratos)
            clic = await pg.evaluate(r"""()=>{const els=[...document.querySelectorAll('a')];const e=els.find(a=>/^contratos?$/i.test((a.innerText||'').trim()))||els.find(a=>/^contrato/i.test((a.innerText||'').trim()));if(e){e.click();return (e.innerText||'').trim();}return null;}""")
            print("clicou:", clic, flush=True)
            await pg.wait_for_timeout(6000)
            await pg.screenshot(path="data/sei_cache/siafe_contratos.png")
            # tenta filtrar pelo nº do contrato OU favorecido (ADF filtro §8b: typeahead)
            body = await pg.inner_text("body")
            print("tem grade de contrato?", "Contrato" in body or "Favorecido" in body, "| 005/2021 visível?", ALVO in body, flush=True)
            # dump de qualquer linha com 005/2021 ou MGS + campos da tela
            achados = re.findall(r"(005/2021[^\n]{0,80}|MGS[^\n]{0,60}|Processo[^\n]{0,40}|SEI[- ]?\d{6}/\d{6}/\d{4})", body)
            print("trechos relevantes:", [re.sub(r'\s+', ' ', a)[:70] for a in achados[:15]], flush=True)
            Path("data/sei_cache/siafe_contrato_body.txt").write_text(body, encoding="utf-8")
            print("SALVO siafe_contrato_body.txt", flush=True)
            # DUMP dos elementos de FILTRO do grid de Contrato (disclosure/select/input do sdtFilter)
            filt = await pg.evaluate(r"""()=>{
                const out={disc:[],sel:[],inp:[],tbl:[]};
                document.querySelectorAll('[id*="sdtFilter"],[id*="disAcr"],[id*="isclosure"]').forEach(e=>out.disc.push(e.id));
                document.querySelectorAll('select').forEach(e=>{if(e.id)out.sel.push({id:e.id,opts:[...e.options].map(o=>o.value+':'+o.text.slice(0,20)).slice(0,12)})});
                document.querySelectorAll('input[type=text]').forEach(e=>{if(e.id)out.inp.push(e.id)});
                document.querySelectorAll('[id*="tbl"],[id*="Tbl"]').forEach(e=>{if(/tbl/i.test(e.id)&&out.tbl.length<8)out.tbl.push(e.id)});
                return out;}""")
            print("FILTRO disc:", filt["disc"][:8], flush=True)
            print("FILTRO selects:", json.dumps(filt["sel"][:6], ensure_ascii=False)[:500], flush=True)
            print("FILTRO inputs:", filt["inp"][:10], flush=True)
            print("TBL ids:", filt["tbl"][:6], flush=True)
            # tenta abrir o filtro (disclosure) e listar as Propriedades disponíveis
            # FILTRA pela UG do ITERJ no selUg → grid mostra os contratos do ITERJ
            try:
                opt = await pg.evaluate(r"""()=>{const s=document.getElementById('pt1:selUg::content');if(!s)return null;
                    const o=[...s.options].find(x=>/iterj|terras|133100|270042/i.test(x.text));return o?{v:o.value,t:o.text}:null;}""")
                print("opção ITERJ no selUg:", opt, flush=True)
                if opt:
                    await pg.select_option('[id="pt1:selUg::content"]', value=opt["v"])
                    await pg.wait_for_timeout(5000)
                    body2 = await pg.inner_text("body")
                    Path("data/sei_cache/siafe_contrato_iterj.txt").write_text(body2, encoding="utf-8")
                    print("005/2021 agora visível?", "005/2021" in body2, flush=True)
                    procs = sorted(set(re.findall(r"SEI[- ]?\d{6}/\d{6}/\d{4}", body2)))
                    print("processos SEI na tela ITERJ:", procs[:12], flush=True)
                    linhas = re.findall(r"(005/2021[^\n]{0,90}|MGS[^\n]{0,70})", body2)
                    print("linhas 005/2021 / MGS:", [re.sub(r'\s+', ' ', x)[:80] for x in linhas[:8]], flush=True)
                    # clica na linha do 005/2021 p/ abrir o detalhe
                    abriu = await pg.evaluate(r"""()=>{const tds=[...document.querySelectorAll('td,span,a')].filter(e=>/005\/2021/.test(e.innerText||''));if(tds[0]){tds[0].click();return true;}return false;}""")
                    if abriu:
                        await pg.wait_for_timeout(4000)
                        det = await pg.inner_text("body")
                        Path("data/sei_cache/siafe_contrato_detalhe.txt").write_text(det, encoding="utf-8")
                        dp = sorted(set(re.findall(r"SEI[- ]?\d{6}/\d{6}/\d{4}", det)))
                        print("DETALHE 005/2021 — processos SEI:", dp, flush=True)
                        print("DETALHE campos:", [re.sub(r'\s+', ' ', x)[:60] for x in re.findall(r"(Processo[^\n]{0,40}|Vig[êe]ncia[^\n]{0,30}|Valor[^\n]{0,25}|Favorecido[^\n]{0,40}|Empenho[^\n]{0,30})", det)][:12], flush=True)
            except Exception as e:
                print("filtro UG erro:", str(e)[:100], flush=True)
        finally:
            await b.close()


asyncio.run(main())
