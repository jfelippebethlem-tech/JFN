# -*- coding: utf-8 -*-
"""
siafe_sweep_full — varredura COMPLETA das OBs por UG × ano (fura o teto de 1000).
Por UG/ano: tenta coletar_por_ug (1 filtro); se bater o cap (>=990), refaz com coletar_por_ug_grande
(UG + Número prefixo + subdivisão automática). Resumível (checkpoint por sistema:ug:ano). Começa por TJRJ.

SIAFE 2 (siafe2, anos 2024-2026) e SIAFE 1 (www5/SiafeRio, 2016-2023) — sessões independentes (paralelizáveis).
Escolha o sistema pelo argumento. UG list lida do selUg (1x) e cacheada.

Uso:
  PYTHONPATH=. .venv/bin/python -m tools.siafe_sweep_full 2     # SIAFE 2 (2024-26)
  PYTHONPATH=. .venv/bin/python -m tools.siafe_sweep_full 1     # SIAFE 1 (2016-23)
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
# Cache de UGs POR SISTEMA: o SIAFE 1 (conta ALERJ-only) e o SIAFE 2 têm listas de selUg DIFERENTES.
# Um cache compartilhado fazia o S1 reusar as ~205 UGs do S2 → 205×8 anos varrendo uma conta que só
# enxerga a ALERJ (010100) → milhares de falsos-0 (era o "bug §41"). (achado 2026-06-07)
def _cache_ug(sistema: str) -> Path:
    return _REPO / "data" / "sei_cache" / f"ugs_siafe_{sistema}.json"
TJRJ = "030100"
LOGIN_1 = "https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"
ANOS = {"2": [2026, 2025, 2024], "1": [2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016]}


def _ckpt_path(sistema: str) -> Path:
    return _REPO / "data" / "sei_cache" / f"siafe_sweep_full_{sistema}.json"


def _ck(sistema):
    p = _ckpt_path(sistema)
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}


def _ck_save(sistema, d):
    try:
        _ckpt_path(sistema).write_text(json.dumps(d, ensure_ascii=False))
    except Exception:
        pass


def _log(sistema, m):
    line = f"[{int(time.time())}][S{sistema}] {m}"
    print(line, flush=True)
    try:
        with open(_REPO / "data" / f"siafe_sweep_full_{sistema}.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


async def _ler_ugs(login_url, sistema) -> list[str]:
    """Lê os códigos de UG do selUg da PRÓPRIA conta (1 login). Cacheia POR SISTEMA.
    No SIAFE 1 a conta só expõe TODAS + 010100 (ALERJ) → retorna ['010100']."""
    cache = _cache_ug(sistema)
    if cache.exists():
        try:
            return json.loads(cache.read_text())
        except Exception:
            pass
    from playwright.async_api import async_playwright
    import compliance_agent.siafe_ob_orcamentaria as M
    import os as _os
    _os.environ["JFN_SIAFE_LOGIN_URL"] = login_url
    import importlib
    importlib.reload(M)
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
                                  viewport={"width": 1600, "height": 1000})
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            ano0 = ANOS["2"][0] if "siafe2" in login_url else ANOS["1"][0]
            if not (await M._login(pg, ano0)).get("ok"):
                return []
            await pg.wait_for_timeout(1500)
            opts = await pg.evaluate(r"""()=>{const s=document.getElementById('pt1:selUg::content');
                return s?[...s.options].map(o=>o.text):[];}""")
            ugs = []
            for t in opts:
                code = t.split("-")[0].strip()
                if code.isdigit() and len(code) >= 6:
                    ugs.append(code)
            if ugs:
                cache.write_text(json.dumps(ugs, ensure_ascii=False))
            return ugs
        finally:
            await b.close()


async def main():
    import os as _os
    sistema = sys.argv[1] if len(sys.argv) > 1 else "2"
    login_url = LOGIN_1 if sistema == "1" else "https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp"
    _os.environ["JFN_SIAFE_LOGIN_URL"] = login_url
    import importlib
    import compliance_agent.siafe_ob_orcamentaria as M
    importlib.reload(M)

    ugs = await _ler_ugs(login_url, sistema)
    if not ugs:
        _log(sistema, "FALHA ao ler lista de UGs — abortando."); return
    # começar por TJRJ (se a conta tiver acesso), depois o resto (ordem estável). No SIAFE 1 a conta só
    # expõe a ALERJ → NÃO prepender TJRJ (senão varre uma UG inacessível gerando falso-0).
    ugs = ([TJRJ] if TJRJ in ugs else []) + [u for u in ugs if u != TJRJ]
    anos = ANOS[sistema]
    _log(sistema, f"UGs={len(ugs)} × anos={anos} — começando por {ugs[0]}")
    ck = _ck(sistema)
    try:
        from compliance_agent import siafe_runner as _sr
    except Exception:
        _sr = None
    for ug in ugs:
        for ano in anos:
            chave = f"{ug}:{ano}"
            if ck.get(chave, {}).get("ok"):
                continue
            if _sr:
                _sr.refresh_lock(f"sweep:{sistema}")   # heartbeat: mantém o lock vivo no sweep longo
            try:
                r = await M.coletar_por_ug(ano, ug)
                colh = r.get("colhidas", 0)
                if r.get("ok") and colh >= 990:           # capou → refaz com subdivisão
                    _log(sistema, f"{ug} {ano}: {colh} (CAP) → ug-grande")
                    r = await M.coletar_por_ug_grande(ano, ug)
            except Exception as e:  # noqa: BLE001
                r = {"ok": False, "erro": f"{type(e).__name__}: {str(e)[:90]}"}
            ck[chave] = r
            _ck_save(sistema, ck)
            _log(sistema, f"{ug} {ano}: {r.get('ingeridas', r.get('colhidas','?'))} ing | ok={r.get('ok')}")
    _log(sistema, "SWEEP COMPLETO.")


if __name__ == "__main__":
    asyncio.run(main())
