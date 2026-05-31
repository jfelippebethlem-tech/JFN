"""
Playwright automation for SIAFE2 - Sistema Integrado de Administração Financeira do Estado do RJ.

Key facts discovered from live inspection:
- Framework: Oracle ADF (Application Development Framework) with Fusion skin
- Login URL: https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp
- Login fields: Usuário, Senha, Cliente, Exercício  (4 required fields)
- FlexVision runs on a separate subdomain: siafe2-flexvision.fazenda.rj.gov.br
- FlexVision path within SIAFE: Flexvision > Consultas > (reports like Execução por OB)
- Version: 4.167.12 (build 202605281616)
- Email OTP may appear after login (2FA or new-IP detection)
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Frame


SIAFE_BASE_URL = "https://siafe2.fazenda.rj.gov.br/Siafe"
SIAFE_LOGIN_URL = f"{SIAFE_BASE_URL}/faces/login.jsp"
FLEXVISION_URL = "https://siafe2-flexvision.fazenda.rj.gov.br/Flexvision/"

# Oracle ADF renders input fields inside component wrappers.
# The actual <input> elements are found by their surrounding label text.
# We use Playwright's :has-text and adjacent sibling strategies.

_ADF_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
]


class SIAFEBrowser:
    """Handles all browser interactions with the SIAFE2 / FlexVision systems."""

    def __init__(
        self,
        headless: bool = True,
        screenshots_dir: str = "screenshots",
        chromium_path: Optional[str] = None,
    ):
        self.headless = headless
        self.screenshots_dir = Path(screenshots_dir)
        self.screenshots_dir.mkdir(exist_ok=True)
        self.chromium_path = chromium_path
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._logged_in = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self):
        """Launch browser."""
        self._playwright = await async_playwright().start()
        launch_kwargs = dict(
            headless=self.headless,
            args=_ADF_CHROMIUM_ARGS,
        )
        if self.chromium_path:
            launch_kwargs["executable_path"] = self.chromium_path

        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            ignore_https_errors=True,
            # Spoof automation detection
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()
        # Hide navigator.webdriver
        await self._page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

    async def close(self):
        """Close browser and clean up."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def screenshot(self, name: str) -> str:
        """Take a debug screenshot. Returns file path."""
        ts = datetime.now().strftime("%H%M%S")
        path = self.screenshots_dir / f"{name}_{ts}.png"
        await self._page.screenshot(path=str(path), full_page=True)
        return str(path)

    # ── Login ─────────────────────────────────────────────────────────────────

    async def login(
        self,
        username: str,
        password: str,
        cliente: Optional[str] = None,
        exercicio: Optional[str] = None,
        otp_callback=None,
    ) -> dict:
        """
        Log into SIAFE2.

        The login page has 4 required fields:
          - Usuário   → username (CPF)
          - Senha     → password
          - Cliente   → organization selector (dropdown) — uses default if not provided
          - Exercício → fiscal year selector (dropdown) — uses current year if not provided

        An email OTP step may appear after submitting (new IP / 2FA).
        If otp_callback is None, prompts via input().
        """
        await self._page.goto(SIAFE_LOGIN_URL, wait_until="networkidle", timeout=30000)
        # ADF loads slowly — wait for the spinner to disappear
        await self._wait_for_adf_load()
        await self.screenshot("01_login_page")

        # ── Fill Usuário ──────────────────────────────────────────────────────
        user_input = await self._adf_find_input_by_label("Usuário")
        if not user_input:
            user_input = await self._find([
                'input[name*="usuario"]',
                'input[name*="user"]',
                'input[type="text"]:first-of-type',
            ])
        if not user_input:
            await self.screenshot("ERROR_no_user_field")
            return {"success": False, "message": "Campo 'Usuário' não encontrado."}
        await user_input.fill(username)

        # ── Fill Senha ────────────────────────────────────────────────────────
        pass_input = await self._find([
            'input[type="password"]',
            'input[name*="senha"]',
            'input[name*="password"]',
        ])
        if not pass_input:
            await self.screenshot("ERROR_no_pass_field")
            return {"success": False, "message": "Campo 'Senha' não encontrado."}
        await pass_input.fill(password)

        # ── Select Cliente (if dropdown present) ─────────────────────────────
        cliente_sel = await self._find([
            'select[name*="cliente"]',
            'select[id*="cliente"]',
        ], timeout=2000)
        if cliente_sel:
            if cliente:
                try:
                    await cliente_sel.select_option(label=cliente)
                except Exception:
                    await cliente_sel.select_option(value=cliente)
            # else leave default

        # ── Select Exercício ─────────────────────────────────────────────────
        exercicio_sel = await self._find([
            'select[name*="exercicio"]',
            'select[name*="exercício"]',
            'select[id*="exercicio"]',
        ], timeout=2000)
        if exercicio_sel:
            year = exercicio or str(datetime.now().year)
            try:
                await exercicio_sel.select_option(label=year)
            except Exception:
                try:
                    await exercicio_sel.select_option(value=year)
                except Exception:
                    pass  # leave default

        await self.screenshot("02_credentials_filled")

        # ── Submit ────────────────────────────────────────────────────────────
        ok_btn = await self._find([
            # ADF renders buttons with specific skin classes
            'button:has-text("Ok")',
            'button:has-text("OK")',
            'button:has-text("Entrar")',
            'button:has-text("Acessar")',
            'input[value="Ok"]',
            'input[type="submit"]',
            'button[type="submit"]',
        ])
        if ok_btn:
            await ok_btn.click()
        else:
            await self._page.keyboard.press("Enter")

        await self._wait_for_adf_load(timeout=20000)
        await self.screenshot("03_after_login_submit")

        # ── OTP / Email code step ─────────────────────────────────────────────
        page_text = await self._page.inner_text("body")
        otp_indicators = [
            "código",
            "token",
            "verificação",
            "e-mail",
            "autenticação",
        ]
        if any(kw in page_text.lower() for kw in otp_indicators):
            otp_input = await self._find([
                'input[name*="codigo"]',
                'input[name*="token"]',
                'input[name*="code"]',
                'input[type="text"]:visible',
            ])
            if otp_input:
                if otp_callback:
                    code = await otp_callback()
                else:
                    code = input("\n[SIAFE2] Digite o código recebido por e-mail: ").strip()

                await otp_input.fill(code)

                confirm_btn = await self._find([
                    'button:has-text("Confirmar")',
                    'button:has-text("Ok")',
                    'button:has-text("Verificar")',
                    'button[type="submit"]',
                ])
                if confirm_btn:
                    await confirm_btn.click()
                else:
                    await self._page.keyboard.press("Enter")

                await self._wait_for_adf_load(timeout=15000)
                await self.screenshot("04_after_otp")

        # ── Verify success ────────────────────────────────────────────────────
        current_url = self._page.url
        if "login" in current_url.lower() and "login.jsp" in current_url.lower():
            # Still on login page — check for error message
            error_text = await self._extract_error_message()
            return {
                "success": False,
                "message": f"Login falhou. {error_text}".strip(),
                "url": current_url,
            }

        self._logged_in = True
        return {
            "success": True,
            "message": "Login realizado com sucesso.",
            "url": current_url,
        }

    # ── Navigation ────────────────────────────────────────────────────────────

    async def navigate_to_flexvision(self) -> dict:
        """
        Navigate to FlexVision.

        FlexVision lives at siafe2-flexvision.fazenda.rj.gov.br — it is accessed
        from within SIAFE2 via a top-menu link that opens the module (may be
        in an iframe or a redirect to the FlexVision subdomain).
        """
        if not self._logged_in:
            return {"success": False, "message": "Não logado no SIAFE2."}

        await self.screenshot("05_main_menu_before_flexvision")

        # Try clicking the FlexVision link in the top navigation bar
        fv_selectors = [
            'a:has-text("FlexVision")',
            'span:has-text("FlexVision")',
            'td:has-text("FlexVision")',
            'div:has-text("FlexVision")',
            '[title*="FlexVision"]',
            '[title*="Flexvision"]',
        ]
        fv_link = await self._find(fv_selectors, timeout=5000)
        if fv_link:
            await fv_link.click()
            await self._wait_for_adf_load(timeout=15000)
            await self.screenshot("06_flexvision_opened")
            return {
                "success": True,
                "message": "FlexVision acessado.",
                "url": self._page.url,
                "frames": [f.url for f in self._page.frames],
            }

        # Fallback: navigate directly to FlexVision subdomain
        # (the session cookie from SIAFE2 should carry over)
        await self._page.goto(FLEXVISION_URL, wait_until="networkidle", timeout=20000)
        await self._wait_for_adf_load()
        await self.screenshot("06_flexvision_direct")

        if "bloqueado" in (await self._page.inner_text("body")).lower():
            return {
                "success": False,
                "message": "Acesso bloqueado ao FlexVision. Tente pela interface principal do SIAFE2.",
            }

        return {
            "success": True,
            "message": "FlexVision acessado (domínio direto).",
            "url": self._page.url,
        }

    async def navigate_to_execucao_ob(self) -> dict:
        """
        Navigate to 'Execução por OB' inside FlexVision.

        FlexVision > Consultas > Execução por OB
        """
        await self.screenshot("07_flexvision_before_execucao_ob")

        # FlexVision may render in an iframe
        target = await self._get_flexvision_frame()

        # Step 1: Find and click "Consultas"
        consultas = await self._find_in([target], [
            'a:has-text("Consultas")',
            'span:has-text("Consultas")',
            'li:has-text("Consultas")',
            'td:has-text("Consultas")',
        ], timeout=5000)

        if consultas:
            await consultas.click()
            await asyncio.sleep(1)
            await self._wait_for_adf_load(timeout=8000)

        # Step 2: Find Execução por OB
        execucao_selectors = [
            'a:has-text("Execução por OB")',
            'a:has-text("Execucao por OB")',
            'span:has-text("Execução por OB")',
            'td:has-text("Execução por OB")',
            'li:has-text("Execução por OB")',
            'a:has-text("OB")',
        ]
        execucao = await self._find_in([target], execucao_selectors, timeout=5000)

        if execucao:
            await execucao.click()
            await self._wait_for_adf_load(timeout=12000)
            await self.screenshot("08_execucao_ob_loaded")
            return {
                "success": True,
                "message": "Tela 'Execução por OB' aberta.",
                "url": self._page.url,
            }

        # Try expanding tree/accordion nodes
        await self._expand_all_menu_items(target)
        await asyncio.sleep(0.5)

        execucao = await self._find_in([target], execucao_selectors, timeout=3000)
        if execucao:
            await execucao.click()
            await self._wait_for_adf_load(timeout=12000)
            await self.screenshot("08_execucao_ob_loaded")
            return {"success": True, "message": "Execução por OB aberta (via menu expandido)."}

        await self.screenshot("ERROR_execucao_ob_not_found")
        # Return available items to help diagnose
        items = await self._list_visible_links(target)
        return {
            "success": False,
            "message": "Seção 'Execução por OB' não encontrada.",
            "available_items": items[:30],
        }

    async def search_execucao_ob(
        self,
        orgao: Optional[str] = None,
        data_inicio: Optional[str] = None,
        data_fim: Optional[str] = None,
        numero_ob: Optional[str] = None,
    ) -> dict:
        """
        Fill filter fields and run the Execução por OB query.

        Args:
            orgao: Órgão code or name (e.g. "260" or "SEEDUC")
            data_inicio: Start date DD/MM/AAAA
            data_fim: End date DD/MM/AAAA
            numero_ob: Specific OB number

        Returns:
            Success status + row count found.
        """
        await self.screenshot("09_search_form_before")
        target = await self._get_flexvision_frame()

        async def _fill(labels: list[str], value: str):
            """Find input by label text and fill it."""
            for label in labels:
                inp = await self._adf_find_input_by_label_in_frame(target, label)
                if not inp:
                    inp = await self._find_in([target], [
                        f'input[name*="{label.lower()}"]',
                        f'input[id*="{label.lower()}"]',
                    ], timeout=1500)
                if inp:
                    tag = await inp.evaluate("el => el.tagName.toLowerCase()")
                    if tag == "select":
                        try:
                            await inp.select_option(label=value)
                        except Exception:
                            await inp.select_option(value=value)
                    else:
                        await inp.triple_click()
                        await inp.fill(value)
                    return True
            return False

        if orgao:
            await _fill(["Órgão", "Orgao", "orgão", "orgao"], orgao)

        if data_inicio:
            await _fill(["Data Início", "Data De", "De", "Início", "dataInicio"], data_inicio)

        if data_fim:
            await _fill(["Data Fim", "Data Até", "Até", "Fim", "dataFim"], data_fim)

        if numero_ob:
            await _fill(["Número OB", "Nº OB", "OB", "numeroOB", "numero_ob"], numero_ob)

        await self.screenshot("10_filters_filled")

        # Submit search
        search_btn = await self._find_in([target], [
            'button:has-text("Pesquisar")',
            'button:has-text("Consultar")',
            'button:has-text("Buscar")',
            'button:has-text("Executar")',
            'button:has-text("Gerar")',
            'input[value*="Pesquisar"]',
            'button[type="submit"]',
        ], timeout=5000)

        if search_btn:
            await search_btn.click()
        else:
            # FlexVision sometimes uses Enter on the last field
            await self._page.keyboard.press("Enter")

        await self._wait_for_adf_load(timeout=25000)
        await self.screenshot("11_search_results")

        # Count result rows
        rows = await target.query_selector_all("table tbody tr, tr.af_table_data-row")
        return {
            "success": True,
            "message": f"Pesquisa executada. {len(rows)} linhas encontradas.",
            "row_count": len(rows),
        }

    async def extract_ob_data(self, max_pages: int = 50) -> list[dict]:
        """
        Extract all OB records from the results table, handling pagination.

        Returns a list of dicts (one per row), keys = column headers.
        """
        all_records = []
        page_num = 1
        target = await self._get_flexvision_frame()

        while page_num <= max_pages:
            await self.screenshot(f"12_data_page_{page_num:02d}")

            # Extract headers
            headers = await self._extract_table_headers(target)
            # Extract rows
            rows_data = await self._extract_table_rows(target, headers)
            all_records.extend(rows_data)

            # Pagination
            next_btn = await self._find_in([target], [
                'button:has-text("Próxima")',
                'button:has-text("Próximo")',
                'a:has-text("Próxima")',
                '[aria-label="Next"]',
                '.af_table_scroll-next',
                'button[title*="próxima"]',
            ], timeout=3000)

            if not next_btn:
                break
            disabled = await next_btn.get_attribute("disabled")
            aria_disabled = await next_btn.get_attribute("aria-disabled")
            if disabled or aria_disabled == "true":
                break

            await next_btn.click()
            await self._wait_for_adf_load(timeout=10000)
            page_num += 1

        return all_records

    # ── Page inspection helpers ───────────────────────────────────────────────

    async def get_page_text(self) -> str:
        """Return visible text of the current page (first 8000 chars)."""
        text = await self._page.inner_text("body")
        return text[:8000]

    async def list_menu_items(self) -> list[str]:
        """Return all distinct clickable text items visible on the page."""
        els = await self._page.query_selector_all("a, button, li, td.af_menuBar_item")
        texts = []
        for el in els:
            try:
                t = (await el.inner_text()).strip()
                if t and len(t) < 120:
                    texts.append(t)
            except Exception:
                pass
        return list(dict.fromkeys(texts))

    async def get_page_html(self) -> str:
        return await self._page.content()

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _wait_for_adf_load(self, timeout: int = 12000):
        """
        Wait for Oracle ADF to finish loading.
        ADF shows a spinning overlay (ss.gif) while loading.
        We wait for it to disappear, then add a short settled delay.
        """
        try:
            await self._page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            pass
        # Extra wait for ADF JS rendering
        await asyncio.sleep(1.5)

    async def _get_flexvision_frame(self) -> Page | Frame:
        """
        Return the frame containing FlexVision content.
        Falls back to the main page if no FlexVision frame is found.
        """
        for frame in self._page.frames:
            url = frame.url.lower()
            if "flexvision" in url or "flex" in url:
                return frame
        return self._page

    async def _find(self, selectors: list[str], timeout: int = 3000):
        """Try selectors on the main page in order."""
        return await self._find_in([self._page], selectors, timeout)

    async def _find_in(self, targets: list, selectors: list[str], timeout: int = 3000):
        """Try selectors on each target (page or frame) in order."""
        for target in targets:
            for selector in selectors:
                try:
                    el = await target.wait_for_selector(selector, timeout=timeout)
                    if el:
                        return el
                except Exception:
                    continue
        return None

    async def _adf_find_input_by_label(self, label_text: str, timeout: int = 3000):
        """
        In Oracle ADF, inputs are wrapped in a <td> with a preceding <td> containing the label.
        Strategy: find a cell whose text matches the label, then get the next sibling <td>'s input.
        """
        return await self._adf_find_input_by_label_in_frame(self._page, label_text, timeout)

    async def _adf_find_input_by_label_in_frame(self, frame, label_text: str, timeout: int = 3000):
        """Find ADF input adjacent to a label cell."""
        try:
            # Try label element first
            label_el = await frame.wait_for_selector(
                f'label:has-text("{label_text}")', timeout=timeout
            )
            if label_el:
                for_attr = await label_el.get_attribute("for")
                if for_attr:
                    input_el = await frame.query_selector(f'#{for_attr}')
                    if input_el:
                        return input_el
        except Exception:
            pass

        # ADF pattern: input is sibling of label inside same <tr>
        try:
            script = f"""() => {{
                const labels = document.querySelectorAll('label, td, th, span');
                for (const el of labels) {{
                    if (el.textContent.trim() === '{label_text}') {{
                        const parent = el.closest('tr') || el.parentElement;
                        if (parent) {{
                            const input = parent.querySelector('input, select, textarea');
                            if (input) return input;
                        }}
                    }}
                }}
                return null;
            }}"""
            result = await frame.evaluate_handle(script)
            if result:
                el = result.as_element()
                if el:
                    return el
        except Exception:
            pass
        return None

    async def _extract_table_headers(self, target) -> list[str]:
        """Extract column headers from ADF table."""
        headers = []
        # ADF tables use <th> elements with class af_column_header
        header_els = await target.query_selector_all(
            "th, th.af_column_header, thead th, tr:first-child th"
        )
        for th in header_els:
            try:
                text = (await th.inner_text()).strip()
                if text:
                    headers.append(text)
            except Exception:
                pass
        return headers

    async def _extract_table_rows(self, target, headers: list[str]) -> list[dict]:
        """Extract data rows from ADF table."""
        records = []
        rows = await target.query_selector_all("tbody tr, tr.af_table_data-row")
        for row in rows:
            cells = await row.query_selector_all("td")
            if not cells:
                continue
            values = []
            for cell in cells:
                try:
                    text = (await cell.inner_text()).strip()
                    values.append(text)
                except Exception:
                    values.append("")
            if not any(values):
                continue
            record = {}
            for i, val in enumerate(values):
                key = headers[i] if i < len(headers) else f"col_{i + 1}"
                record[key] = val
            records.append(record)
        return records

    async def _expand_all_menu_items(self, target):
        """Click all collapsed/expandable tree nodes."""
        expandable = await target.query_selector_all(
            "[class*='collapsed'], [class*='expand'], "
            "[class*='tree-node'], [class*='treeNode'], "
            "li > a, .af_treeTable_expand-icon"
        )
        for el in expandable:
            try:
                await el.click()
                await asyncio.sleep(0.2)
            except Exception:
                pass

    async def _list_visible_links(self, target) -> list[str]:
        """Return visible link/button texts (for diagnostics)."""
        els = await target.query_selector_all("a, button, span[onclick], td[onclick]")
        texts = []
        for el in els:
            try:
                t = (await el.inner_text()).strip()
                if t and len(t) < 100:
                    texts.append(t)
            except Exception:
                pass
        return list(dict.fromkeys(texts))

    async def _extract_error_message(self) -> str:
        """Try to get an error message from the current page."""
        error_selectors = [
            ".af_message, .af_panelBox_body, [class*='error'], [class*='erro']",
            ".ui-message-error-detail",
        ]
        for sel in error_selectors:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    text = await el.inner_text()
                    if text.strip():
                        return text.strip()
            except Exception:
                pass
        return ""
