#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Foto de FACHADA sem Google Maps API — $0, sem chave, sem billing, imagem real.

Como: geocodifica o endereço no OSM/Nominatim (grátis) e tira um SCREENSHOT do
Street View **embed clássico** (`output=svembed`) num navegador headless. Esse
embed NÃO usa API key e NÃO gera cobrança — é a mesma imagem do Google, mas
capturada da tela, não da Static API (paga, que está desligada por billing).
Acurácia = a do próprio Street View; honesto quando não há cobertura.

    .venv/bin/python tools/fachada_capturar.py --cnpj 19088605000104
    .venv/bin/python tools/fachada_capturar.py --endereco "Rua X, 100, Maricá, RJ"
    .venv/bin/python tools/fachada_capturar.py --latlon -22.9068,-43.1729 --nome alvo

Saída: data/fachadas/<slug>.jpg + <slug>.json (fonte, lat/lon, cobertura).
VM-safe: vm_guard preflight + 1 browser + cleanup. Metodologia de fachada
fantasma (quando pedir a foto): compliance_agent/empresa_fantasma.py.
"""
from __future__ import annotations

import logging
import argparse
import asyncio
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RAIZ = Path(__file__).resolve().parents[1]
OUT = RAIZ / "data" / "fachadas"

_SEM_COBERTURA = ("no imagery here", "sem imagens", "nao temos imagens",
                  "no imagery for", "sorry, we have no imagery")


logger = logging.getLogger(__name__)


def _norm(s: str) -> str:
    t = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def _slug(s: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", _norm(s)).strip("_") or "fachada"


def url_streetview_embed(lat: float, lon: float, heading: int = 0) -> str:
    """Street View embed SEM chave (output=svembed). Não gera cobrança."""
    return ("https://www.google.com/maps?layer=c&output=svembed"
            f"&cbll={lat},{lon}&cbp=11,{heading},0,0,0")


def sem_cobertura(texto_pagina: str) -> bool:
    t = _norm(texto_pagina)
    return any(m in t for m in _SEM_COBERTURA)


def _geocodificar(endereco: str) -> tuple[float, float] | None:
    """Nominatim/OSM (grátis, sem chave). Reusa o geocoder do projeto se houver."""
    try:
        import httpx
        r = httpx.get("https://nominatim.openstreetmap.org/search",
                      params={"q": endereco, "format": "json", "limit": 1,
                              "countrycodes": "br"},
                      headers={"User-Agent": "JFN-Compliance/1.0 (fiscalizacao)"},
                      timeout=20)
        d = r.json()
        if d:
            return float(d[0]["lat"]), float(d[0]["lon"])
    except Exception as exc:
        logger.warning("geocoding OSM falhou (sem-coordenada pode ser falso): %s", exc)
    return None


def _endereco_do_cnpj(cnpj: str) -> tuple[str, str]:
    """(endereço, razão social) do CNPJ na base. Vazio se não houver."""
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{RAIZ}/data/compliance.db?mode=ro", uri=True)
        row = con.execute("SELECT endereco, razao FROM endereco_fornecedor "
                          "WHERE cnpj=?", (cnpj,)).fetchone()
        con.close()
        if row:
            return row[0] or "", row[1] or ""
    except Exception as exc:
        logger.warning("endereço do CNPJ %s ilegível no DB: %s", cnpj, exc)
    return "", ""


async def _capturar(lat: float, lon: float, destino: Path) -> dict:
    from playwright.async_api import async_playwright
    from tools import vm_guard as G

    ok, msg = G.preflight()
    if not ok:
        return {"ok": False, "erro": f"preflight: {msg}"}
    resultado = {"ok": False, "lat": lat, "lon": lon, "fonte": "streetview_embed_sem_chave"}
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=G.guarded_launch_args())
        try:
            ctx = await b.new_context(viewport={"width": 1000, "height": 720},
                                      locale="pt-BR")
            pg = await ctx.new_page()
            for heading in (0, 90, 180, 270):  # tenta ângulos até achar cobertura
                # o embed clássico EXIGE iframe (navegação direta é bloqueada) —
                # montamos uma página local com o iframe em tela cheia
                url = url_streetview_embed(lat, lon, heading)
                await pg.set_content(
                    "<html><body style='margin:0'>"
                    f"<iframe src='{url}' style='border:0;width:1000px;"
                    "height:720px' allowfullscreen></iframe></body></html>",
                    wait_until="load")
                await pg.wait_for_timeout(4500)
                fr = pg.frames[-1] if len(pg.frames) > 1 else pg
                try:
                    txt = await fr.evaluate("() => document.body.innerText || ''")
                except Exception:
                    txt = ""
                if sem_cobertura(txt) or "must be used in an iframe" in _norm(txt):
                    resultado["cobertura"] = False
                    continue
                el = await pg.query_selector("iframe")
                await (el.screenshot(path=str(destino), type="jpeg", quality=80)
                       if el else pg.screenshot(path=str(destino), type="jpeg",
                                                quality=80))
                resultado.update(ok=True, cobertura=True, heading=heading,
                                 arquivo=str(destino))
                break
        finally:
            await b.close()
    G.cleanup_orphans()
    return resultado


def capturar(*, cnpj: str = "", endereco: str = "", latlon: str = "",
             nome: str = "") -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    razao = nome
    if cnpj:
        cnpj = re.sub(r"\D", "", cnpj)
        end_db, razao_db = _endereco_do_cnpj(cnpj)
        endereco = endereco or end_db
        razao = razao or razao_db or cnpj
    slug = _slug(cnpj or nome or endereco)
    destino = OUT / f"{slug}.jpg"

    if latlon:
        lat, lon = (float(x) for x in latlon.split(","))
    elif endereco:
        geo = _geocodificar(endereco)
        if not geo:
            return {"ok": False, "erro": "geocodificação falhou", "endereco": endereco}
        lat, lon = geo
    else:
        return {"ok": False, "erro": "informe --cnpj, --endereco ou --latlon"}

    res = asyncio.run(_capturar(lat, lon, destino))
    res.update(cnpj=cnpj, endereco=endereco, razao_social=razao, slug=slug)
    (OUT / f"{slug}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cnpj", default="")
    ap.add_argument("--endereco", default="")
    ap.add_argument("--latlon", default="", help="lat,lon")
    ap.add_argument("--nome", default="")
    args = ap.parse_args()
    res = capturar(cnpj=args.cnpj, endereco=args.endereco,
                   latlon=args.latlon, nome=args.nome)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
