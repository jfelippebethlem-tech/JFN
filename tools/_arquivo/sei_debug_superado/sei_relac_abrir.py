#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Abre o processo (cracked), pega os URLs dos RELACIONADOS e abre CADA UM lendo o nº SEI do cabeçalho
(span/título 'Processo SEI-...'). Acha os processos de pagamento 2022/2023. VM-guarded.
Uso: sei_relac_abrir.py 330005/000007/2024"""
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
            dump = await SR._ler_cracked(pg, ALVO)
            rel = dump.get("relacionados") or []
            urls = [r.get("url") for r in rel if r.get("url")]
            achados = []
            for u in urls[:14]:
                try:
                    await pg.goto(u, wait_until="domcontentloaded", timeout=25000)
                    await pg.wait_for_timeout(2500)
                    num = None
                    for fr in pg.frames:
                        try:
                            n = await fr.evaluate(r"""()=>{
                              const t=document.body?document.body.innerText:'';
                              const m=t.match(/\d{6}\/\d{6}\/\d{4}/g);
                              if(m){const c={};m.forEach(x=>c[x]=(c[x]||0)+1);return Object.entries(c).sort((a,b)=>b[1]-a[1])[0][0];}
                              return null;}""")
                            if n:
                                num = n; break
                        except Exception:
                            continue
                    achados.append(num)
                except Exception as e:
                    achados.append(f"erro:{str(e)[:30]}")
            nums = sorted({a for a in achados if a and re.match(r"\d{6}/\d{6}/\d{4}", str(a))})
            out = {"alvo": ALVO, "n_rel": len(rel), "numeros_relacionados": nums,
                   "candidatos_2022_2023": [n for n in nums if re.search(r"/202[23]$", n)]}
            (REPO / "data/sei_cache/relac_abrir.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            print(json.dumps(out, ensure_ascii=False, indent=1))
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
