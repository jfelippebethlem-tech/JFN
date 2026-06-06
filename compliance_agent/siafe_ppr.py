# -*- coding: utf-8 -*-
"""
SIAFE-Rio 2 — coleta COMPLETA de OBs via replay do PPR do ADF (bypass do limite de 50 da UI).

Como funciona (protocolo Oracle ADF Rich Client):
  - A grade `pt1:tblOrdemBancaria:tabViewerDec` entrega 50 linhas e busca o resto por PPR.
  - Disparamos o evento de SCROLL da tabela via POST, controlando a posição por
    `oracle.adf.view.rich.DELTAS = {<tableId>={viewportSize=N}}`, incrementando N de 50 em 50.
  - Cada resposta é o envelope ADF com as linhas em `<fragment><![CDATA[ ...HTML... ]]></fragment>`.
  - O `javax.faces.ViewState` ROTACIONA: extrair o novo a cada resposta para a próxima.

Usa Playwright só para LOGAR (sessão de 30d) e abrir a tela de OB (ViewState válido); a partir daí,
pagina via `context.request` (mesmos cookies). Sem depender da UI travada.

Uso: python -m compliance_agent.siafe_ppr --ano 2025 --max 100000
"""
import argparse
import asyncio
import importlib.util
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

TABLE = "pt1:tblOrdemBancaria:tabViewerDec"
EV = ('<m xmlns="http://oracle.com/richClient/comm">'
      '<k v="type"><s>scroll</s></k><k v="first"><n>{first}</n></k><k v="rows"><n>50</n></k></m>')


def _viewstate(text):
    m = (re.search(r'javax\.faces\.ViewState[^>]*?>\s*<!\[CDATA\[(.*?)\]\]>', text, re.S)
         or re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', text)
         or re.search(r'<value>([^<]+)</value>', text))
    return m.group(1) if m else None


def _parse_rows(text):
    """Extrai linhas de OB do envelope PPR. Retorna lista de listas (células) + set de números."""
    rows, nums = [], set()
    # cada <tr ...>...</tr> com tds
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', text, re.S):
        cells = [re.sub(r'<[^>]+>', '', c).replace('&nbsp;', ' ').strip()
                 for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        cells = [re.sub(r'\s+', ' ', x) for x in cells if x is not None]
        m = re.search(r'20\d\dOB\d{5}', tr)
        if m and len([c for c in cells if c]) >= 6:
            num = m.group(0)
            if num not in nums:
                nums.add(num)
                rows.append(cells)
    return rows, nums


async def coletar(ano=2025, maxn=100000, page=50):
    spec = importlib.util.spec_from_file_location("c", str(_REPO / "_SANDBOX" / "coletar_obs_agora.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    sm = __import__("compliance_agent.coletar_obs_sessao", fromlist=["_navegar_ob"])
    from playwright.async_api import async_playwright
    todos, vistos = [], set()
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, storage_state=str(_REPO / "data/sei_cache/siafe_state.json"),
                                  viewport={"width": 1600, "height": 1000}, locale="pt-BR")
        pg = await ctx.new_page()
        await mod._login(pg, ano); await mod._settle(pg, 2500)
        await sm._navegar_ob(pg); await pg.wait_for_timeout(3500)
        url = pg.url
        vs = await pg.evaluate(r"""()=>{const e=document.querySelector('[name="javax.faces.ViewState"]');return e?e.value:null;}""")
        wid = await pg.evaluate(r"""()=>{const e=document.querySelector('[name="Adf-Window-Id"]');return e?e.value:'';}""")
        form = await pg.evaluate(r"""()=>{const e=document.querySelector('[name="org.apache.myfaces.trinidad.faces.FORM"]');return e?e.value:'frmPrincipal';}""")
        # 1ª página (já no DOM)
        first_rows = await pg.evaluate(r"""()=>{const db=document.getElementById('pt1:tblOrdemBancaria:tabViewerDec::db');const o=[];if(db)db.querySelectorAll('tr').forEach(tr=>{const tds=[...tr.querySelectorAll('td')].map(td=>(td.innerText||'').replace(/\s+/g,' ').trim());if(tds.some(x=>x))o.push(tds);});return o;}""")
        for r in first_rows:
            m = re.search(r'20\d\dOB\d{5}', " ".join(r))
            if m and m.group(0) not in vistos:
                vistos.add(m.group(0)); todos.append(r)
        print(f"  página inicial: {len(vistos)} OBs", flush=True)
        seco = 0
        viewport = page
        while len(todos) < maxn and seco < 4:
            data = {
                "org.apache.myfaces.trinidad.faces.FORM": form,
                "Adf-Window-Id": wid,
                "javax.faces.ViewState": vs,
                "event": TABLE,
                "event.%s" % TABLE: EV.format(first=viewport),
            }
            try:
                resp = await ctx.request.post(url, form=data, headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Adf-Rich-Message": "true", "Adf-Ads-Page-Id": "1",
                    "X-Requested-With": "XMLHttpRequest"})
                txt = await resp.text()
            except Exception as e:
                print(f"  erro viewport {viewport}: {str(e)[:50]}", flush=True); break
            nvs = _viewstate(txt)
            if nvs:
                vs = nvs
            _, nums = _parse_rows(txt)
            novos = nums - vistos
            rows, _ = _parse_rows(txt)
            for r in rows:
                m = re.search(r'20\d\dOB\d{5}', " ".join(r))
                if m and m.group(0) in novos:
                    vistos.add(m.group(0)); todos.append(r)
            if novos:
                seco = 0
                if len(todos) % 500 < 50:
                    print(f"  viewport={viewport}: total={len(todos)}", flush=True)
            else:
                seco += 1
            viewport += page
        await b.close()
    return todos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", type=int, default=2025)
    ap.add_argument("--max", type=int, default=100000)
    a = ap.parse_args()
    rows = asyncio.run(coletar(a.ano, a.max))
    print(f"TOTAL OBs coletadas via PPR: {len(rows)}")
    for r in rows[:3]:
        print("  ", r[:8])


if __name__ == "__main__":
    main()
