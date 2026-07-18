# -*- coding: utf-8 -*-
"""
siafe_sweep_ugs — varre as OBs por UG Emitente (fura o teto de 1000) p/ um conjunto de UGs × anos.
Usa a receita §8b validada: coletar_por_ug (typeahead + Tab). Resumível por (ug,ano) via checkpoint.
Detecta CAP (colhidas>=990 → UG grande, precisa sub-filtro por período — sinaliza p/ fase 2).

Resolve "Casa Civil" lendo as opções do selUg ao vivo (1 login). Demais por código fixo do dropdown.
Uso (background): PYTHONPATH=. .venv/bin/python -m tools.siafe_sweep_ugs
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_CKPT = _REPO / "data" / "sei_cache" / "siafe_sweep_ugs_ckpt.json"
_LOG = _REPO / "data" / "siafe_sweep_ugs.log"

# UGs prioritárias (códigos do dropdown selUg do SIAFE-Rio2). Casa Civil resolvida ao vivo.
ALVOS = {"030100": "TJ (TJRJ)", "290100": "SES", "180100": "SEEDUC",
         "226300": "FSERJ — FUNDO SOBERANO do ERJ (sem OB na base; coletar — dono 2026-07-11)",
         "263100": "DETRAN-RJ", "294200": "FUNDAÇÃO SAÚDE", "296100": "FES",
         "243200": "INEA", "200900": "SEFAZ", "570100": "SEGOV", "140100": "Casa Civil"}
ANOS = [2026, 2025, 2024]   # SIAFE 2.0 (2016–2023 = SIAFE 1, fase futura)


def _ck() -> dict:
    try:
        return json.loads(_CKPT.read_text()) if _CKPT.exists() else {}
    except Exception:
        return {}


def _ck_save(d: dict):
    try:
        _CKPT.parent.mkdir(parents=True, exist_ok=True)
        _CKPT.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    except (OSError, TypeError):
        pass


def _log(m: str):
    line = f"[{int(time.time())}] {m}"
    print(line, flush=True)
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


async def _resolver_casa_civil() -> dict:
    """1 login p/ ler o selUg e achar o código da Casa Civil (e validar os demais)."""
    from playwright.async_api import async_playwright
    import compliance_agent.siafe_ob_orcamentaria as M
    out = {}
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
                                  viewport={"width": 1600, "height": 1000})
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            if not (await M._login(pg, 2026)).get("ok"):
                return out
            await pg.wait_for_timeout(1200)
            opts = await pg.evaluate(r"""()=>{const s=document.getElementById('pt1:selUg::content');
                return s?[...s.options].map(o=>o.text):[];}""")
            for t in opts:
                if "casa civil" in t.lower() or ("civil" in t.lower() and "casa" in t.lower()):
                    code = t.split("-")[0].strip()
                    if code.isdigit():
                        out[code] = t.strip()
        finally:
            await b.close()
    return out


async def main():
    import compliance_agent.siafe_ob_orcamentaria as M
    alvos = dict(ALVOS)
    cc = await _resolver_casa_civil()
    if cc:
        alvos.update(cc); _log(f"Casa Civil resolvida: {cc}")
    else:
        _log("Casa Civil NÃO encontrada no selUg (verificar manualmente).")
    ck = _ck()
    for ug, nome in alvos.items():
        for ano in ANOS:
            chave = f"{ug}:{ano}"
            if ck.get(chave, {}).get("ok"):
                _log(f"pulando {nome} {ano} (já feito: {ck[chave]})"); continue
            _log(f"coletando {nome} ({ug}) {ano}…")
            try:
                r = await M.coletar_por_ug(ano, ug)
            except Exception as e:  # noqa: BLE001
                r = {"ok": False, "erro": f"{type(e).__name__}: {str(e)[:80]}"}
            cap = r.get("colhidas", 0) >= 990
            r["cap_atingido"] = cap
            ck[chave] = r; _ck_save(ck)
            flag = " ⚠️CAP(precisa sub-filtro por período)" if cap else ""
            _log(f"  {nome} {ano}: {r}{flag}")
    _log(f"SWEEP CONCLUÍDO. checkpoint: {_CKPT}")
    # resumo
    caps = [k for k, v in ck.items() if v.get("cap_atingido")]
    if caps:
        _log(f"UGs/anos que ATINGIRAM o cap (incompletos, fase 2 por período): {caps}")


if __name__ == "__main__":
    asyncio.run(main())
