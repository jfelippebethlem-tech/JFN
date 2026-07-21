#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Abre um processo (cracked) e extrai o NÚMERO SEI de cada processo RELACIONADO do painel
'Processos Relacionados' (não a caixa). Os relacionados 'Financeiro: Pagamento' do pagamento MGS
são os processos de pagamento dos OUTROS anos (2022/2023). VM-guarded.
Uso: sei_relacionados_numeros.py 330005/000007/2024"""
import asyncio
import json
import sys
import re
from pathlib import Path
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from tools.vm_guard import preflight, cleanup_orphans
from tools import sei_reader as SR


async def main():
    ALVO = sys.argv[1] if len(sys.argv) > 1 else "330005/000007/2024"
    from playwright.async_api import async_playwright
    from tools.sei_session import abrir_sessao
    async with async_playwright() as pw:
        b, ctx, pg, ok = await abrir_sessao(pw)
        try:
            if not ok:
                print(json.dumps({"ok": False, "erro": "login"})); return
            # abre o processo pelo método cracked (carrega a árvore + relacionados)
            dump = await SR._ler_cracked(pg, ALVO)
            await pg.wait_for_timeout(2000)
            # varre TODOS os frames por nº SEI em links/linhas (painel de relacionados + árvore)
            achados = {}
            for fr in pg.frames:
                try:
                    itens = await fr.evaluate(r"""()=>{
                      const out=[];
                      document.querySelectorAll('a,tr,td,span,div').forEach(e=>{
                        const s=(e.innerText||'').replace(/\s+/g,' ').trim();
                        const m=s.match(/(\d{6}\/\d{6}\/\d{4})/);
                        if(m && s.length<160){ out.push([m[1], s.slice(0,90)]); }
                        // href/onclick podem ter o protocolo tb
                        const h=(e.getAttribute&&(e.getAttribute('href')||e.getAttribute('onclick'))||'');
                        const m2=h.match(/(\d{6}\/\d{6}\/\d{4})/);
                        if(m2) out.push([m2[1], 'href:'+(s.slice(0,60)||h.slice(0,60))]);
                      });
                      return out;}""")
                    for num, ctx_ in itens:
                        achados.setdefault(num, ctx_)
                except Exception:
                    continue
            relac = dump.get("relacionados") or []
            out = {"alvo": ALVO, "via": dump.get("via"), "n_relacionados_painel": len(relac),
                   "nums_distintos": len(achados),
                   "candidatos_2022_2023": {n: c for n, c in sorted(achados.items()) if re.search(r"/202[23]$", n)},
                   "todos_nums": {n: c for n, c in sorted(achados.items())}}
            (REPO / "data/sei_cache/relac_numeros.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            print(json.dumps({k: out[k] for k in ("alvo", "via", "n_relacionados_painel", "nums_distintos", "candidatos_2022_2023")}, ensure_ascii=False, indent=1))
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
