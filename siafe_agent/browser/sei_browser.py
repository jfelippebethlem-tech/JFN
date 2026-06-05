"""Playwright automation for SEI Rio - Sistema Eletrônico de Informações do Estado do RJ."""

import asyncio
from typing import Optional

from playwright.async_api import Page


SEI_BASE_URL = "https://sei.fazenda.rj.gov.br/sei"
SEI_LOGIN_URL = f"{SEI_BASE_URL}/controlador.php?acao=usuario_login"


class SEIBrowser:
    """
    SEI Rio scraper. Reuses an already-open Playwright page/context
    from SIAFEBrowser or operates standalone.
    """

    def __init__(self, page: Page, screenshots_dir: str = "screenshots"):
        self._page = page
        from pathlib import Path
        self.screenshots_dir = Path(screenshots_dir)
        self.screenshots_dir.mkdir(exist_ok=True)
        from datetime import datetime
        self._dt = datetime

    async def screenshot(self, name: str) -> str:
        from datetime import datetime
        path = self.screenshots_dir / f"sei_{name}_{datetime.now().strftime('%H%M%S')}.png"
        await self._page.screenshot(path=str(path), full_page=True)
        return str(path)

    async def login(self, username: str, password: str) -> dict:
        """Log into SEI Rio (separate credentials may be required)."""
        await self._page.goto(SEI_LOGIN_URL, wait_until="networkidle")
        await self.screenshot("01_login")

        user_field = await self._find(
            ['input[id="txtUsuario"]', 'input[name="txtUsuario"]', 'input[name*="user"]']
        )
        pass_field = await self._find(
            ['input[id="pwdSenha"]', 'input[name="pwdSenha"]', 'input[type="password"]']
        )
        if not user_field or not pass_field:
            return {"success": False, "message": "Campos de login SEI não encontrados."}

        # SEI uses org selection too — try SEFAZ-RJ
        orgao_selectors = ['select[id="selOrgao"]', 'select[name="selOrgao"]']
        orgao_sel = await self._find(orgao_selectors)
        if orgao_sel:
            # Select first option or SEFAZ
            options = await orgao_sel.evaluate("el => Array.from(el.options).map(o => o.text)")
            sefaz_opt = next((o for o in options if "FAZENDA" in o.upper() or "SEFAZ" in o.upper()), None)
            if sefaz_opt:
                await orgao_sel.select_option(label=sefaz_opt)

        await user_field.fill(username)
        await pass_field.fill(password)

        submit = await self._find(['button[type="submit"]', 'input[value="Acessar"]', 'button:has-text("Acessar")'])
        if submit:
            await submit.click()
        else:
            await self._page.keyboard.press("Enter")

        await self._page.wait_for_load_state("networkidle", timeout=10000)
        await self.screenshot("02_after_login")

        if "login" in self._page.url.lower() or "Usuário inválido" in await self._page.inner_text("body"):
            return {"success": False, "message": "Login SEI falhou."}

        return {"success": True, "message": "Login SEI realizado."}

    async def search_process_by_ob(self, ob_number: str) -> Optional[dict]:
        """
        Search SEI for processes linked to an OB (Ordem Bancária).

        Tries to search by the OB number in SEI's document search.
        Returns process info dict or None.
        """
        # Navigate to SEI search
        search_url = f"{SEI_BASE_URL}/controlador.php?acao=pesquisa_rapida"
        await self._page.goto(search_url, wait_until="networkidle")

        search_field = await self._find([
            'input[id="txtPesquisaRapida"]',
            'input[name*="pesquisa"]',
            'input[placeholder*="pesquisa"]',
            'input[type="search"]',
        ])
        if not search_field:
            return None

        await search_field.fill(ob_number)
        await self._page.keyboard.press("Enter")
        await self._page.wait_for_load_state("networkidle", timeout=10000)

        return await self._extract_first_process_result()

    async def get_process_details(self, numero_sei: str) -> dict:
        """
        Retrieve details for a specific SEI process number.

        Args:
            numero_sei: Process number like "SEI-030004/002345/2024" or "030004/002345/2024"

        Returns:
            dict with process metadata
        """
        # Normalize format
        numero_clean = numero_sei.replace("SEI-", "").strip()

        search_url = f"{SEI_BASE_URL}/controlador.php?acao=pesquisa_rapida"
        await self._page.goto(search_url, wait_until="networkidle")

        search_field = await self._find([
            'input[id="txtPesquisaRapida"]',
            'input[name*="pesquisa"]',
        ])
        if not search_field:
            return {"error": "Campo de pesquisa não encontrado no SEI."}

        await search_field.fill(numero_clean)
        await self._page.keyboard.press("Enter")
        await self._page.wait_for_load_state("networkidle", timeout=10000)
        await self.screenshot(f"process_{numero_clean.replace('/', '_')}")

        result = await self._extract_first_process_result()
        if result:
            return result
        return {"numero_sei": numero_sei, "error": "Processo não encontrado no SEI."}

    async def extract_ob_sei_numbers_from_siafe_row(self, row_data: dict) -> dict:
        """
        Given a row from SIAFE2 Execução por OB, attempt to find the SEI number.
        Searches using OB number, beneficiary name, or value.
        """
        # Common field names in SIAFE for OB number
        ob_number = (
            row_data.get("Número OB")
            or row_data.get("N° OB")
            or row_data.get("OB")
            or row_data.get("Número")
            or ""
        )

        if ob_number:
            result = await self.search_process_by_ob(ob_number)
            if result:
                return {**row_data, "numero_sei": result.get("numero_processo", ""), "sei_info": result}

        return {**row_data, "numero_sei": "", "sei_info": None}

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _find(self, selectors: list[str], timeout: int = 3000):
        for selector in selectors:
            try:
                el = await self._page.wait_for_selector(selector, timeout=timeout)
                if el:
                    return el
            except Exception:
                continue
        return None

    async def _extract_first_process_result(self) -> Optional[dict]:
        """Extract first result row from SEI search results table."""
        # SEI results are typically in a table
        rows = await self._page.query_selector_all("table.resultado tr, table tbody tr")
        if not rows:
            return None

        # Skip header row
        data_rows = rows[1:] if len(rows) > 1 else rows

        if not data_rows:
            return None

        first_row = data_rows[0]
        cells = await first_row.query_selector_all("td")
        if not cells:
            return None

        # SEI typically shows: Número do Processo | Tipo | Interessado | Unidade | Data
        texts = []
        for cell in cells:
            text = await cell.inner_text()
            texts.append(text.strip())

        # Try to get the link (SEI process number is usually a link)
        link = await first_row.query_selector("a")
        href = ""
        if link:
            href = await link.get_attribute("href") or ""

        result = {
            "numero_processo": texts[0] if texts else "",
            "tipo": texts[1] if len(texts) > 1 else "",
            "interessado": texts[2] if len(texts) > 2 else "",
            "unidade": texts[3] if len(texts) > 3 else "",
            "data": texts[4] if len(texts) > 4 else "",
            "url": href,
        }
        return result
