"""
Bypass assistido do captcha do SEI-RJ usando Chrome já aberto em modo debug.

Fluxo:
- Conecta no Chrome pela CDP na porta 9222
- Abre a página de pesquisa do SEI
- Submete o número do processo
- Se aparecer captcha:
    1) Localiza a imagem do captcha
    2) Salva em disco
    3) Usa pytesseract para ler o texto
    4) Preenche e envia
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

from compliance_agent.captcha_solver import solve_captcha_url

SEI_PESQUISA   = "https://portalsei.rj.gov.br/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php"
SEI_CONTROLADOR = "https://portalsei.rj.gov.br/sei/controlador.php"


async def _get_sei_page():
    p = await async_playwright().start()
    browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=30000)
    ctx = browser.contexts[0] if browser.contexts else None
    pages = ctx.pages if ctx else []
    # Usa a página já aberta do SEI se existir; senão cria
    page = next((pg for pg in pages if "portalsei.rj.gov.br" in pg.url), None)
    if page is None:
        page = await ctx.new_page()
    return p, browser, page


def _is_captcha_page(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in [
        "captcha",
        "não sou um robô",
        "nao sou um robo",
        "digite os caracteres",
        "código da imagem",
        "codigo da imagem",
    ])


async def _preencher_captcha(page) -> bool:
    captcha_img_src = await page.evaluate("""() => {
      const img = document.querySelector('img[src*="captcha"]');
      return img ? img.src : '';
    }""")

    if not captcha_img_src:
        return False

    texto = solve_captcha_url(captcha_img_src)
    if not texto:
        return False

    campo = await page.query_selector('input[name*="txtCaptcha"], input[id*="txtCaptcha"], input[name*="captcha"]')
    if not campo:
        return False

    await campo.fill(texto)
    await page.keyboard.press("Enter")
    await page.wait_for_load_state("domcontentloaded", timeout=20000)
    await asyncio.sleep(1)
    return True


async def submit_sei_search(numero: str, *, max_attempts: int = 2) -> dict:
    p = browser = page = None
    try:
        p, browser, page = await _get_sei_page()

        await page.goto(SEI_PESQUISA, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)

        campo = await page.query_selector('input[name="txtPesquisaRapida"], input[name="txtNroProcesso"], input[name="txtPesquisa"]')
        if not campo:
            return {"erro": "Campo de busca não encontrado"}

        await campo.fill(numero)
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(1)

        txt = await page.inner_text("body")

        for _ in range(max_attempts):
            if not _is_captcha_page(txt):
                break
            ok = await _preencher_captcha(page)
            if not ok:
                break
            txt = await page.inner_text("body")

        # Salva HTML final para inspeção futura
        Path("data/tmp/sei_last_search.html").write_text(await page.content(), encoding="utf-8")
        Path("data/tmp/sei_last_search.txt").write_text(txt, encoding="utf-8")

        return {
            "ok": True,
            "texto": txt,
            "url": page.url,
            "captcha_resolvido": "captcha" not in txt.lower(),
        }
    except Exception as e:
        return {"erro": str(e)}
    finally:
        try:
            if page:
                await page.dispose()
            if browser:
                await browser.close()
            if p:
                await p.stop()
        except Exception:
            pass
