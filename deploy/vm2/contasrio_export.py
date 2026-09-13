# -*- coding: utf-8 -*-
"""Exporta a 'Relação de Contratos' do ContasRio (Vaadin) por ano em CSV — VM-2 (browser livre).
    .venv/bin/python contasrio_export.py --anos 2026 2025 --dest data/contasrio
Cada ano vira data/contasrio/contratos_<ano>.csv (latin-1, ';'), copiado p/ ~/shared-brain/contasrio/."""
import argparse
import shutil
from pathlib import Path
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
VISTAS = {  # nome → (fragmento da URL, prefixo do CSV)
    "contratos": ("Rela%C3%A7%C3%A3o%20de%20Contratos", "contratos"),
    "fiscais": ("Fiscais%20de%20Contratos", "fiscais"),   # + Nome do Fiscal e CPF/matrícula (mascarado)
}
URL = "https://contasrio.rio.rj.gov.br/ContasRio/#!Contratos/{frag}"

def exportar(anos, dest: Path, vista: str = "contratos"):
    frag, prefixo = VISTAS[vista]
    dest.mkdir(parents=True, exist_ok=True)
    feitos = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        pg = b.new_context(accept_downloads=True, viewport={"width": 1400, "height": 900}).new_page()
        pg.goto(URL.format(frag=frag), wait_until="domcontentloaded", timeout=60000); pg.wait_for_timeout(15000)
        for ano in anos:
            try:
                combo = pg.locator(".v-filterselect").nth(2)
                # o filtro de ano é uma lista de CHECKBOXES (multi): Limpar → marca o ano → fecha (Escape)
                combo.locator(".v-filterselect-button").click(); pg.wait_for_timeout(2000)
                pg.locator(".v-filterselect-suggestpopup .gwt-MenuItem").filter(has_text="Limpar").first.click(timeout=10000); pg.wait_for_timeout(1500)
                if not pg.locator(".v-filterselect-suggestpopup").count():
                    combo.locator(".v-filterselect-button").click(); pg.wait_for_timeout(2000)
                pg.locator(".v-filterselect-suggestpopup .gwt-MenuItem").filter(has_text=str(ano)).first.click(timeout=10000); pg.wait_for_timeout(1000)
                pg.keyboard.press("Escape"); pg.wait_for_timeout(1000)
                # espera o grid trocar: a coluna 'Ano de Celebração' (índice 4) da 1ª linha de dados
                ano_grid = None
                for _ in range(150):   # a vista de fiscais de 2024 levou > 90 s para renderizar
                    pg.wait_for_timeout(2000)
                    ano_grid = pg.evaluate("()=>{const r=document.querySelectorAll('.v-grid-body tr')[1]; return r? (r.querySelectorAll('td')[4]||{}).innerText : null}")
                    if ano_grid and str(ano) in ano_grid: break
                if not ano_grid or str(ano) not in ano_grid:
                    print(f"{ano}: grid ficou em '{ano_grid}'; combo='{combo.locator('input').input_value()}' — pulo", flush=True)
                    pg.screenshot(path=f"/tmp/contasrio_ano_{ano}.png"); continue
                pg.click(".v-button:has(.v-icon-download)", timeout=10000); pg.wait_for_timeout(1500)
                with pg.expect_download(timeout=300000) as dl:
                    pg.click("text=/^Csv$/", timeout=10000)
                alvo = dest / f"{prefixo}_{ano}.csv"; dl.value.save_as(str(alvo))
                n = sum(1 for _ in open(alvo, encoding="latin-1")) - 2
                feitos[ano] = n; print(f"{ano}: {n} contratos → {alvo}", flush=True)
                pg.keyboard.press("Escape"); pg.wait_for_timeout(1000)
            except (PlaywrightError, OSError) as e:
                print(f"{ano}: erro {type(e).__name__}: {str(e)[:140]}", flush=True)
        b.close()
    sb = Path.home() / "shared-brain" / "contasrio"; sb.mkdir(exist_ok=True)
    for ano in feitos: shutil.copy2(dest / f"{prefixo}_{ano}.csv", sb / f"{prefixo}_{ano}.csv")
    return feitos

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--anos", nargs="+", type=int, default=[2026]); ap.add_argument("--dest", default="data/contasrio")
    ap.add_argument("--vista", choices=sorted(VISTAS), default="contratos")
    a = ap.parse_args(); print(exportar(a.anos, Path(a.dest), a.vista))
