#!/usr/bin/env python3
"""Índice AUTORITATIVO de UGs do SIAFE-Rio (dropdown selUg) — código + nome.

POR QUE existe: `compliance_agent/ugs.py` deriva o mapa das UGs JÁ COLETADAS
(despesa_execucao) + curadoria — logo é INCOMPLETO e defasa quando o estado cria/
renomeia UGs (ex.: Fundo Soberano não aparece porque nunca foi coletado). A fonte
da verdade é o selUg do SIAFE-Rio2, que muda com o tempo. Este dumper lê o selUg
ao vivo (1 login) e grava data/ug_index_siafe.json {codigo: nome} + carimbo de data.

Uso: PYTHONPATH=. .venv/bin/python tools/siafe_ug_index.py [--ano 2026]
Depois: buscar por nome (ex.: 'soberano') no JSON gerado.
"""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SAIDA = Path(__file__).resolve().parent.parent / "data" / "ug_index_siafe.json"


async def baixar_index(ano: int) -> dict:
    from playwright.async_api import async_playwright

    import compliance_agent.siafe_ob_orcamentaria as M

    ugs: dict[str, str] = {}
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
                                  timezone_id="America/Sao_Paulo",
                                  viewport={"width": 1600, "height": 1000})
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            if not (await M._login(pg, ano)).get("ok"):
                return {"_erro": "login SIAFE falhou"}
            await pg.wait_for_timeout(1500)
            opts = await pg.evaluate(
                r"""()=>{const s=document.getElementById('pt1:selUg::content');
                    return s?[...s.options].map(o=>o.text):[];}""")
            for t in opts:
                t = (t or "").strip()
                m = re.match(r"^(\d{4,6})\s*[-–]\s*(.+)$", t)
                if m:
                    ugs[m.group(1)] = m.group(2).strip()
        finally:
            await b.close()
    return ugs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", type=int, default=2026)
    args = ap.parse_args()

    from tools.vm_guard import cleanup_orphans, wait_until_safe
    cleanup_orphans()
    ok, msg = wait_until_safe()
    if not ok:
        print(f"vm_guard: {msg} — abortando p/ não crashar a VM")
        sys.exit(2)

    ugs = asyncio.run(baixar_index(args.ano))
    if "_erro" in ugs or not ugs:
        print(f"INDISPONÍVEL: {ugs.get('_erro', 'selUg vazio')}")
        sys.exit(2)
    payload = {"atualizado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "ano": args.ano, "n": len(ugs), "ugs": ugs}
    tmp = SAIDA.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(SAIDA)
    print(f"índice SIAFE gravado: {len(ugs)} UGs em {SAIDA}")
    # destaque dos fundos/órgãos-alvo
    for cod, nome in sorted(ugs.items()):
        N = nome.upper()
        if any(t in N for t in ("SOBERANO", "PREVID", "DETRAN", "TRANSITO", "TRÂNSITO",
                                "FSERJ", "FUNSERJ", "ROYALT", "PETROL")):
            print(f"  {cod}  {nome}")


if __name__ == "__main__":
    main()
