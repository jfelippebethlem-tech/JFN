#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SONDA (só leitura): como o painel de filtros da OB Orçamentária se apresenta no SIAFE 1.

`coletar_por_ug_grande` assume que a linha 1 do filtro (`table_rtfFilter:1`) já existe — verdade no
SIAFE 2. No SIAFE 1 a chamada estoura em `Locator.click: Timeout` esperando esse campo, e sem a
segunda linha não há subdivisão por prefixo de número, que é justamente o que fura o teto de 1.000.
Esta sonda loga, navega e INVENTARIA o que existe: quantas linhas de filtro, seus ids, e se há
botão de adicionar linha. Não coleta, não ingere, não clica em nada que mude estado.

    JFN_SIAFE_LOGIN_URL=https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp \
      .venv/bin/python -m tools._sonda_siafe1_filtro 2023
"""
from __future__ import annotations

import asyncio
import json
import sys


async def main() -> int:
    exercicio = int(sys.argv[1]) if len(sys.argv) > 1 else 2023
    from playwright.async_api import async_playwright

    import compliance_agent.siafe_ob_orcamentaria as M

    async with async_playwright() as pw:
        b, pg = await M._novo_browser(pw, True)
        try:
            # o login do ADF redireciona no meio do `evaluate` e mata o contexto de execução —
            # transitório conhecido; tenta de novo antes de desistir (o custo é o tempo de login).
            login = {}
            for tentativa in range(3):
                try:
                    login = await M._login(pg, exercicio)
                    if login.get("ok"):
                        break
                except Exception as exc:  # noqa: BLE001 — fronteira de browser
                    login = {"ok": False, "erro": f"{type(exc).__name__}: {str(exc)[:80]}"}
                    await pg.wait_for_timeout(3000)
            if not login.get("ok"):
                print(json.dumps({"etapa": "login", **login}, ensure_ascii=False))
                return 1
            # INVENTÁRIO DO MENU antes de clicar: o `_navegar` é escrito para o acordeão do
            # SIAFE 2 (`a.xyo`); no SIAFE 1 o menu é barra de ABAS no topo, e o clique cego levou
            # a sessão para fora do sistema (página de bloqueio da SEFAZ).
            menu = await pg.evaluate(r"""()=>{
                const vis = e => { const r=e.getBoundingClientRect(); return r.width>0 && r.height>0; };
                const abas = [...document.querySelectorAll('a,div[role="tab"],span')]
                    .filter(e=>vis(e) && /^(planejamento|execu|projetos|apoio|administra|relat)/i
                        .test((e.innerText||'').trim()))
                    .map(e=>({txt:(e.innerText||'').trim().slice(0,28), id:e.id||null,
                              cls:(e.className||'').slice(0,28), tag:e.tagName}));
                return {abas: abas.slice(0,20),
                        tem_xyo: document.querySelectorAll('a.xyo').length};
            }""")
            print(json.dumps({"etapa": "menu", **menu}, ensure_ascii=False, indent=1))
            return 0
            from compliance_agent.siafe_adf import AdfSync
            adf = AdfSync(pg)
            await adf.boot()
            if await pg.locator(f'[id="{M._F_PROP}"]').count() == 0:
                await M._click_real(pg, M._F_DISC)
                await adf.wait()
            achado = await pg.evaluate(r"""()=>{
                const ids = [...document.querySelectorAll('[id*="table_rtfFilter"]')].map(e=>e.id);
                const linhas = new Set(ids.map(i=>(i.match(/table_rtfFilter:(\d+)/)||[])[1]).filter(Boolean));
                const botoes = [...document.querySelectorAll('a,button,img,div[role="button"]')]
                    .filter(e=>/adicion|nova linha|novo filtro|\+/i.test((e.title||'')+(e.alt||'')+(e.innerText||'')))
                    .map(e=>({id:e.id, txt:(e.innerText||e.title||e.alt||'').trim().slice(0,40)}))
                    .filter(e=>e.id).slice(0,12);
                return {linhas:[...linhas].sort(), n_ids:ids.length, amostra_ids: ids.slice(0,14), botoes};
            }""")
            print(json.dumps({"etapa": "ok", "exercicio": exercicio, **achado},
                             ensure_ascii=False, indent=1))
            return 0
        finally:
            await b.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
