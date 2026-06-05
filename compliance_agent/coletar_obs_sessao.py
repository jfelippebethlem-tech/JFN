# -*- coding: utf-8 -*-
"""
Coleta de OBs no SIAFE reutilizando a SESSÃO autenticada (sem novo login/MFA).

Aproveita a navegação já pronta de `_SANDBOX/coletar_obs_agora.py` (_ir_obs, _ir_lista_favorecido,
_filtrar_por_cnpj, _ler_tabela), mas injeta o storage_state salvo por siafe_session.py — então NÃO
faz login (válido por ~30 dias com o device-trust). Resultado: OBs por empresa/exercício.

Uso: python -m compliance_agent.coletar_obs_sessao --cnpj 19088605000104 --ano 2025
"""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("JFN_DATA_DIR", _REPO / "data")) / "sei_cache"
STATE = DATA / "siafe_state.json"
APP_URL = "https://siafe2.fazenda.rj.gov.br/Siafe/faces/"


def _load_collector():
    """Carrega o módulo _SANDBOX/coletar_obs_agora.py por caminho."""
    p = _REPO / "_SANDBOX" / "coletar_obs_agora.py"
    spec = importlib.util.spec_from_file_location("coletar_obs_agora", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def coletar(cnpj, cnpj_fmt, ano):
    if not STATE.exists():
        return {"erro": "sem sessão — rode siafe_session --login primeiro"}
    mod = _load_collector()
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(
            viewport={"width": 1366, "height": 900}, locale="pt-BR",
            timezone_id="America/Sao_Paulo", ignore_https_errors=True,
            storage_state=str(STATE),
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"))
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            # Login NORMAL, mas com o cookie de device-trust carregado -> SIAFE NÃO pede MFA,
            # e o workspace ADF renderiza corretamente (carregar /faces/ direto vinha em branco).
            ok = await mod._login(pg, ano)
            if not ok:
                await mod._screenshot(pg, "ERRO_login_sessao")
                return {"erro": "login (com trust) falhou", "url": pg.url}

            # navega até as OBs (tenta o caminho direto, depois 'Lista de Favorecido')
            nav = await mod._ir_obs(pg)
            if not nav:
                nav = await mod._ir_lista_favorecido(pg)
            if not nav:
                await mod._screenshot(pg, "ERRO_nav_obs_sessao")
                return {"erro": "não chegou na tela de OBs", "url": pg.url}

            # filtra por CNPJ
            await mod._filtrar_por_cnpj(pg, cnpj=cnpj, cnpj_fmt=cnpj_fmt)
            await mod._settle(pg, 4000)

            # lê a tabela
            rows, headers = await mod._ler_tabela(pg)
            return {"cnpj": cnpj, "ano": ano, "headers": headers, "n": len(rows), "rows": rows}
        except Exception as e:
            try:
                await mod._screenshot(pg, "ERRO_coleta_sessao")
            except Exception:
                pass
            return {"erro": f"{type(e).__name__}: {str(e)[:160]}", "url": pg.url}
        finally:
            await b.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cnpj", default="19088605000104")
    ap.add_argument("--cnpj-fmt", default="19.088.605/0001-04")
    ap.add_argument("--ano", type=int, default=2025)
    a = ap.parse_args()
    res = asyncio.run(coletar(a.cnpj, a.cnpj_fmt, a.ano))
    if "erro" in res:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(f"OBs coletadas: {res['n']} | headers: {res['headers']}")
        out = DATA / f"obs_sessao_{a.cnpj}_{a.ano}.json"
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"salvo em {out}")
        for r in res["rows"][:5]:
            print("  ", r)


if __name__ == "__main__":
    main()
