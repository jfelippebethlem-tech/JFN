from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import os, time, re, base64
from datetime import datetime
from pathlib import Path

SEARCH_URL = "https://sei.rj.gov.br/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php?acao_externa=protocolo_pesquisar&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=6"
SAVE_DIR = Path("data/tmp/sei_captchas")
SAVE_DIR.mkdir(parents=True, exist_ok=True)

def screencap(page):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    shot = page.screenshot(full_page=False, path=str(SAVE_DIR / f"captcha_{ts}.png"))

    # heuristic: save alleged "box" crop at right-bottom
    vp = page.viewport_size or {}
    w, h = vp.get("width") or 1280, vp.get("height") or 720
    left = int(w * 0.55)
    top = int(h * 0.78)
    right = min(w, int(left + 260))
    bottom = min(h, int(top + 110))
    if right > left and bottom > top:
        clip = {"x": left, "y": top, "width": right - left, "height": bottom - top}
        try:
            page.screenshot(path=str(SAVE_DIR / f"captcha_{ts}_box.png"), clip=clip)
        except Exception:
            pass
    return shot

def run(n=1, headless=True):
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        default_context = browser.contexts[0] if browser.contexts else browser.new_context(viewport={"width":1280,"height":800})
        page = default_context.pages[0] if default_context.pages else default_context.new_page()
        page.set_default_timeout(45000)
        page.set_default_navigation_timeout(45000)
        for i in range(n):
            try:
                page.goto(SEARCH_URL, wait_until="domcontentloaded")
                time.sleep(2.5)
                # pega o campo de texto do captcha logo acima do input
                label = page.locator("label:has-text('Texto da imagem')")
                if label.count():
                    label.click()
                    time.sleep(0.3)
                screencap(page)
                print(f"[{i+1}/{n}] captcha salvo")
                time.sleep(1.2)
            except Exception as e:
                print(f"[{i+1}/{n}] erro: {e}")
        browser.close()

if __name__ == "__main__":
    run(n=2)
