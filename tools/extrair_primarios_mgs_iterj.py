#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrai FONTE PRIMÁRIA (NF/NL/OB/comprovante) dos documentos SEI dos processos MGS-ITERJ,
com OCR para scans. Reusa o login itkava + _conteudo_doc do sei_reader (browser_lock, sem 2 browsers)."""
import asyncio
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, "/home/ubuntu/JFN")
from tools import sei_reader as SR

CDP = {
    "2024": "data/sei_cache/cdp_SEI_330005_000007_2024.json",
    "2025": "data/sei_cache/cdp_SEI_330005_000018_2025.json",
    "2026": "data/sei_cache/cdp_SEI_330005_000030_2026.json",
}
# documentos-alvo (prováveis fontes primárias): Anexo genérico (NF/comprovante), NL, OB orçamentária
ALVO_RE = re.compile(r"^(anexo$|anexo ob|despacho de formaliza|nota fiscal|anexo nf|comprovante|extrato)", re.I)


def seleciona(docs):
    out = []
    for d in docs:
        tit = (d.get("titulo") or "").strip()
        if d.get("url") and ALVO_RE.search(tit):
            out.append({"titulo": tit, "url": d["url"]})
    return out[:6]   # bounded por processo


async def main():
    from compliance_agent.recursos import browser_lock_async, aguardar_load_async
    from playwright.async_api import async_playwright
    await aguardar_load_async(max_por_core=1.5, espera_max=90)
    resultado = []
    async with browser_lock_async(espera_max=600), async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page()
        try:
            if not await SR.login(pg, tentativas=30):
                print("LOGIN FALHOU"); return
            print("login itkava OK", flush=True)
            for ano, path in CDP.items():
                d = json.loads(Path(path).read_text())
                alvos = seleciona(d.get("documentos") or [])
                print(f"\n=== {ano} ({d.get('numero')}): {len(alvos)} docs-alvo ===", flush=True)
                for doc in alvos:
                    r = await SR._conteudo_doc(pg, doc)
                    cont = (r or {}).get("conteudo", "") or ""
                    via = (r or {}).get("via", "html")
                    # extrai sinais primários
                    nf = sorted(set(re.findall(r"(?:nota fiscal|NFS?-?e|NF)[^\d]{0,12}(\d{3,9})", cont, re.I)))[:8]
                    val = sorted(set(re.findall(r"R\$ ?[\d.]{3,12},\d{2}", cont)))[:12]
                    comp = sorted(set(re.findall(r"(?:compet[êe]ncia|refer[êe]nte a|m[êe]s)[^\n]{0,30}", cont, re.I)))[:8]
                    banco = sorted(set(re.findall(r"(?:banco|ag[êe]ncia|conta|cr[ée]dito em conta|BB|favorecido)[^\n]{0,40}", cont, re.I)))[:6]
                    print(f"  • {doc['titulo'][:42]:<42} via={via} {len(cont)}c | NF={nf} comp={comp[:2]} R$={val[:4]}", flush=True)
                    resultado.append({"ano": ano, "titulo": doc["titulo"], "via": via, "len": len(cont),
                                      "nf": nf, "valores": val, "competencia": comp, "banco": banco,
                                      "texto": cont[:2500]})
        finally:
            await b.close()
    Path("data/sei_cache/primarios_mgs_iterj.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nSALVO data/sei_cache/primarios_mgs_iterj.json")


asyncio.run(main())
