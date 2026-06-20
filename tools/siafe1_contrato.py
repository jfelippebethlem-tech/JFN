#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SIAFE 1 (www5/SiafeRio): Execução > Contratos e Convênios > Contrato. Filtra por Favorecido~MGS
(grid §8b alcança outras UGs mesmo a conta só expondo ALERJ no dropdown), abre o detalhe do 005/2021
e extrai o campo PROCESSO (nº do processo SEI da contratação) + vigência/valor/aditivos. Exploratório."""
import os, asyncio, json, re, sys
from pathlib import Path
sys.path.insert(0, "/home/ubuntu/JFN")
os.environ["JFN_SIAFE_LOGIN_URL"] = "https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"  # ANTES do import
import compliance_agent.siafe_ob_orcamentaria as M
from compliance_agent.siafe_adf import AdfSync
from playwright.async_api import async_playwright

GRID = "pt1:tblContrato"
F_DISC = f"{GRID}:sdtFilter::disAcr"
F_PROP = f"{GRID}:table_rtfFilter:0:cbx_col_sel_rtfFilter::content"
F_OP = f"{GRID}:table_rtfFilter:0:cbx_op_sel_rtfFilter::content"


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
              viewport={"width": 1600, "height": 1000},
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            lg = await M._login(pg, 2023)   # SIAFE 1 cobre 2016-2023; 005/2021 ativo até 2023
            print("login SIAFE1:", lg.get("ok"), lg.get("erro") or "", flush=True)
            if not lg.get("ok"):
                print("FALHA login:", lg); return
            adf = AdfSync(pg)
            await pg.wait_for_timeout(2500)

            async def dump_menu(tag):
                items = await pg.evaluate(r"""()=>{const vis=el=>{const r=el.getBoundingClientRect();return r.width>1&&r.height>1;};
                    return [...document.querySelectorAll('a,div[role=menuitem],td.xpt')].filter(vis).map(a=>({t:(a.innerText||a.textContent||'').trim().slice(0,40),id:a.id||''})).filter(x=>x.t.length>1&&x.t.length<42);}""")
                uniq=[]; seen=set()
                for it in items:
                    k=it["t"]+"|"+it["id"]
                    if k not in seen and it["t"]: seen.add(k); uniq.append(it)
                print(f"[{tag}] {len(uniq)} itens:", [f"{x['t']}#{x['id'][-22:]}" for x in uniq if re.search(r'contrat|conv|execu|financ|empenho|liquid', x['t'], re.I)][:20], flush=True)
                return uniq

            # 1) Execução (disclosureAnchor por ID — fallback a texto)
            ok = await M._click_real(pg, "pt1:pt_np4:1:pt_cni6::disclosureAnchor")
            if not ok:
                await pg.evaluate(r"""()=>{const a=[...document.querySelectorAll('a')].find(e=>(e.innerText||'').trim()==='Execução');if(a)a.click();}""")
            await pg.wait_for_timeout(2500)
            m1 = await dump_menu("Execução")
            # 2) Contratos e Convênios — clica por id/texto
            cc = next((x for x in m1 if re.search(r"contratos? e conv|contratos e conv", x["t"], re.I)), None) or \
                 next((x for x in m1 if re.search(r"contrat", x["t"], re.I)), None)
            print("→ Contratos e Convênios:", cc, flush=True)
            if cc and cc["id"]:
                await M._click_real(pg, cc["id"])
            elif cc:
                await pg.evaluate(r"""(t)=>{const a=[...document.querySelectorAll('a,div[role=menuitem]')].find(e=>(e.innerText||'').trim()===t);if(a)a.click();}""", cc["t"])
            await pg.wait_for_timeout(2500)
            m2 = await dump_menu("ContratosConv")
            # 3) leaf "Contrato"
            leaf = next((x for x in m2 if re.fullmatch(r"contratos?", x["t"].strip(), re.I)), None) or \
                   next((x for x in m2 if re.search(r"^contrato\b", x["t"], re.I)), None)
            print("→ leaf Contrato:", leaf, flush=True)
            if leaf and leaf["id"]:
                await M._click_real(pg, leaf["id"])
            elif leaf:
                await pg.evaluate(r"""(t)=>{const a=[...document.querySelectorAll('a,div[role=menuitem]')].find(e=>(e.innerText||'').trim()===t);if(a)a.click();}""", leaf["t"])
            await pg.wait_for_timeout(6000)
            await pg.screenshot(path="data/sei_cache/siafe1_contrato_grid.png")
            body = await pg.inner_text("body")
            print("grid carregou? 'Contrato' in body:", "Contrato" in body, "| MGS visível?", "MGS" in body, "| 005/2021?", "005/2021" in body, flush=True)
            # abre o filtro §8b e dumpa as Propriedades
            if await pg.locator(f'[id="{F_PROP}"]').count() == 0:
                await M._click_real(pg, F_DISC); await adf.wait()
            props = await pg.evaluate(r"""(pid)=>{const s=document.getElementById(pid);return s?[...s.options].map(o=>o.text):[];}""", F_PROP)
            print("PROP opts (Contrato):", props[:25], flush=True)
            # escolhe a propriedade que casa com Favorecido/Credor; senão Número
            alvo_prop = next((p for p in props if re.search(r"favorec|credor|contrat[ad]", p, re.I)), None) or \
                        next((p for p in props if re.search(r"n[úu]mero", p, re.I)), None)
            print("prop escolhida:", alvo_prop, flush=True)
            if alvo_prop:
                await M._typeahead(pg, F_PROP, alvo_prop[:8]); await adf.wait()
                # operador "contém" (favorecido) ou "começa com" (número)
                op_opts = await pg.evaluate(r"""(pid)=>{const s=document.getElementById(pid);return s?[...s.options].map(o=>o.text):[];}""", F_OP)
                op_alvo = next((o for o in op_opts if re.search(r"cont[ée]m", o, re.I)), None) or \
                          next((o for o in op_opts if re.search(r"come[çc]a", o, re.I)), None) or (op_opts[0] if op_opts else None)
                print("OP opts:", op_opts[:10], "| op escolhido:", op_alvo, flush=True)
                if op_alvo:
                    await M._typeahead(pg, F_OP, op_alvo[:6]); await adf.wait()
                valor = "MGS" if re.search(r"favorec|credor", alvo_prop or "", re.I) else "005/2021"
                val = pg.locator('[id*="in_value_rtfFilter"]:visible').last
                if await val.count() == 0:
                    val = pg.locator(f'[id*="table_rtfFilter:0"] input[type="text"]:visible').last
                if await val.count():
                    await val.click(); await val.press("Control+a"); await val.press("Delete")
                    await pg.keyboard.type(valor, delay=90); await pg.keyboard.press("Tab")
                    await adf.wait(); await pg.wait_for_timeout(3500)
                    print(f"filtrado {alvo_prop}~{valor}", flush=True)
            body2 = await pg.inner_text("body")
            Path("data/sei_cache/siafe1_contrato_grid.txt").write_text(body2)
            print("pós-filtro MGS?", "MGS" in body2, "| 005/2021?", "005/2021" in body2, flush=True)
            linhas = re.findall(r"(005/2021[^\n]{0,90}|MGS[^\n]{0,70})", body2)
            print("linhas:", [re.sub(r'\s+',' ',x)[:80] for x in linhas[:8]], flush=True)
            # abre o detalhe (duplo-clique na 1ª linha MGS/005/2021)
            abriu = await pg.evaluate(r"""()=>{const els=[...document.querySelectorAll('tr,td,span,a')].filter(e=>/005\/2021|MGS/i.test(e.innerText||''));if(els[0]){const ev=new MouseEvent('dblclick',{bubbles:true});els[0].dispatchEvent(ev);els[0].click();return (els[0].innerText||'').slice(0,50);}return null;}""")
            print("abriu detalhe via:", abriu, flush=True)
            await pg.wait_for_timeout(4500)
            det = await pg.inner_text("body")
            Path("data/sei_cache/siafe1_contrato_detalhe.txt").write_text(det)
            await pg.screenshot(path="data/sei_cache/siafe1_contrato_detalhe.png")
            procs = sorted(set(re.findall(r"(SEI[- ]?\d{6}/\d{6}/\d{4}|E-?\d{2}/\d{3}/\d{3,6}/\d{4}|\d{6}/\d{6}/\d{4})", det)))
            print("PROCESSOS no detalhe:", procs[:15], flush=True)
            campos = re.findall(r"(Processo[^\n]{0,45}|Vig[êe]ncia[^\n]{0,35}|Valor[^\n]{0,30}|Favorecido[^\n]{0,45}|Aditiv[^\n]{0,40}|Apostil[^\n]{0,40}|Objeto[^\n]{0,60})", det)
            print("CAMPOS detalhe:", [re.sub(r'\s+',' ',c)[:60] for c in campos[:18]], flush=True)
        finally:
            await b.close()


asyncio.run(main())
