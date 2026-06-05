"""
Diagnostic script: loads the SIAFE2 login page and prints all form fields found.
Run this locally (from a network that can reach siafe2.fazenda.rj.gov.br) to inspect
the exact field names/IDs before using the main agent.

Usage:
    python inspect_login.py
    python inspect_login.py --visible    # with visible browser window
"""
import asyncio
import argparse
import sys
from pathlib import Path


CHROMIUM_PATH = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"  # adjust if needed


async def inspect(visible: bool = False):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=not visible,
            executable_path=CHROMIUM_PATH if Path(CHROMIUM_PATH).exists() else None,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="pt-BR",
            ignore_https_errors=True,
        )
        page = await ctx.new_page()

        print("Acessando login SIAFE2...")
        await page.goto(
            "https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp",
            wait_until="networkidle",
            timeout=30000,
        )
        await asyncio.sleep(3)

        Path("screenshots").mkdir(exist_ok=True)
        await page.screenshot(path="screenshots/inspect_login.png", full_page=True)
        print("Screenshot salvo: screenshots/inspect_login.png")

        # Print all inputs, selects, buttons
        print("\n=== INPUTS ===")
        inputs = await page.query_selector_all("input")
        for el in inputs:
            attrs = await page.evaluate("""el => ({
                id: el.id, name: el.name, type: el.type,
                placeholder: el.placeholder, value: el.value,
                'aria-label': el.getAttribute('aria-label'),
                class: el.className.substring(0, 60)
            })""", el)
            print(f"  INPUT: {attrs}")

        print("\n=== SELECTS ===")
        selects = await page.query_selector_all("select")
        for el in selects:
            attrs = await page.evaluate("""el => ({
                id: el.id, name: el.name,
                options: Array.from(el.options).map(o => o.text).slice(0, 5)
            })""", el)
            print(f"  SELECT: {attrs}")

        print("\n=== BUTTONS ===")
        buttons = await page.query_selector_all("button, input[type='submit'], input[type='button']")
        for el in buttons:
            attrs = await page.evaluate("""el => ({
                id: el.id, name: el.name, type: el.type,
                text: el.textContent.trim().substring(0, 50),
                value: el.value
            })""", el)
            print(f"  BTN: {attrs}")

        print("\n=== LABELS ===")
        labels = await page.query_selector_all("label")
        for el in labels:
            text = (await el.inner_text()).strip()
            for_attr = await el.get_attribute("for")
            if text:
                print(f"  LABEL: '{text}' for='{for_attr}'")

        print("\n=== PAGE TEXT (first 500 chars) ===")
        body_text = await page.inner_text("body")
        print(body_text[:500])

        print("\n=== FRAMES ===")
        for frame in page.frames:
            print(f"  FRAME: {frame.url}")

        # Save HTML
        html = await page.content()
        Path("screenshots/login_page.html").write_text(html, encoding="utf-8")
        print("\nHTML completo salvo: screenshots/login_page.html")

        await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--visible", action="store_true")
    args = parser.parse_args()
    asyncio.run(inspect(visible=args.visible))
