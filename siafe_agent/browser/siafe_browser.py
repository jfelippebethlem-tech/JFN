"""
Playwright automation for SIAFE2 + FlexVision.

Facts confirmed from live system inspection via CDP (01/06/2026):

SIAFE2 (Oracle ADF):
- Login URL: https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp
- Framework: Oracle ADF with Fusion skin, minified CSS classes
- Menu bar: class="xyo"  Submenu: class="xgh"  Sub-submenu: class="xgg"
- Disabled items: class contains "p_AFDisabled"
- Input IDs follow pattern: pt1:fieldName::content

FlexVision (Vaadin 7/8):
- Base URL: https://siafe2-flexvision.fazenda.rj.gov.br/Flexvision/
- Hash routing: #!paineis, #!gerenciamento, #!consultas, etc.
- Login: input[type=text] (username), input[type=password] (password)
- Sidebar nav items: <span class="valo-menu-item-caption">
  - "Consultas", "Administração", "Segurança" headings are <b> (non-navigable labels)
  - Actual nav items are <span> — click via page.evaluate()
- Form inputs: class="v-textfield v-widget"  (no stable IDs)
- Tables: class="v-grid" or "v-table"  rows: ".v-grid-row"  cells: ".v-grid-cell"
- All interactions must use page.evaluate() JavaScript — no standard <a>/<button>
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from playwright.async_api import async_playwright, Page, Browser, BrowserContext


SIAFE_BASE      = "https://siafe2.fazenda.rj.gov.br/Siafe"
SIAFE_LOGIN_URL = f"{SIAFE_BASE}/faces/login.jsp"
FV_BASE         = "https://siafe2-flexvision.fazenda.rj.gov.br/Flexvision/"

_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
]

# ── JavaScript helpers (Vaadin has no standard <a>/<button>) ──────────────────

def _js_click_exact(text: str) -> str:
    """JS snippet: clicks first element whose direct text equals `text`."""
    safe = text.replace("'", "\\'")
    return f"""
        () => {{
            for (const el of document.querySelectorAll('*')) {{
                const direct = [...el.childNodes]
                    .filter(n => n.nodeType === 3)
                    .map(n => n.textContent.trim())
                    .join('');
                if (direct === '{safe}') {{
                    el.click();
                    return el.tagName + '|' + el.className;
                }}
            }}
            return null;
        }}
    """


def _js_click_contains(text: str) -> str:
    """JS snippet: clicks smallest visible element containing `text`."""
    safe = text.replace("'", "\\'")
    return f"""
        () => {{
            let best = null, bestSize = Infinity;
            for (const el of document.querySelectorAll('*')) {{
                if (!el.textContent.includes('{safe}')) continue;
                const r = el.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) continue;
                const sz = r.width * r.height;
                if (sz < bestSize) {{ best = el; bestSize = sz; }}
            }}
            if (best) {{
                best.click();
                return best.tagName + '|' + best.className + '|' + best.textContent.trim().slice(0, 60);
            }}
            return null;
        }}
    """


def _js_dblclick_contains(text: str) -> str:
    """JS snippet: double-clicks smallest visible element containing `text`."""
    safe = text.replace("'", "\\'")
    return f"""
        () => {{
            let best = null, bestSize = Infinity;
            for (const el of document.querySelectorAll('*')) {{
                if (!el.textContent.includes('{safe}')) continue;
                const r = el.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) continue;
                const sz = r.width * r.height;
                if (sz < bestSize) {{ best = el; bestSize = sz; }}
            }}
            if (best) {{
                best.dispatchEvent(new MouseEvent('dblclick', {{bubbles: true}}));
                return best.tagName + '|' + best.textContent.trim().slice(0, 60);
            }}
            return null;
        }}
    """


def _js_click_valo_span(text: str) -> str:
    """JS snippet: clicks <span class="valo-menu-item-caption"> with exact text.
    Avoids accidentally clicking category headers (<b> elements)."""
    safe = text.replace("'", "\\'")
    return f"""
        () => {{
            for (const el of document.querySelectorAll('span.valo-menu-item-caption')) {{
                if (el.textContent.trim() === '{safe}') {{
                    el.click();
                    return 'clicked';
                }}
            }}
            return null;
        }}
    """


_JS_LEAF_ELEMENTS = """
    () => {
        const results = [];
        for (const el of document.querySelectorAll('*')) {
            const directText = [...el.childNodes]
                .filter(n => n.nodeType === 3)
                .map(n => n.textContent.trim())
                .join('');
            if (!directText || directText.length < 2 || directText.length > 120) continue;
            const r = el.getBoundingClientRect();
            results.push({
                tag: el.tagName,
                cls: el.className,
                id: el.id,
                text: directText,
                visible: r.width > 0 && r.height > 0,
            });
        }
        return results;
    }
"""

_JS_ALL_TEXT = """
    () => {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        const texts = [];
        let node;
        while ((node = walker.nextNode())) {
            const t = node.textContent.trim();
            if (t && t.length > 1) texts.push(t);
        }
        return texts.join('\\n');
    }
"""


# ─────────────────────────────────────────────────────────────────────────────

class SIAFEBrowser:
    """Browser automation for SIAFE2 + FlexVision."""

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
        """Launch a headless (or visible) Chromium instance."""
        self._playwright = await async_playwright().start()
        kwargs = dict(headless=self.headless, args=_CHROMIUM_ARGS)
        if self.chromium_path:
            kwargs["executable_path"] = self.chromium_path
        self._browser = await self._playwright.chromium.launch(**kwargs)
        self._context = await self._browser.new_context(
            viewport={"width": 1366, "height": 900},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()
        await self._page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )

    async def close(self):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def screenshot(self, name: str) -> str:
        ts = datetime.now().strftime("%H%M%S")
        path = self.screenshots_dir / f"{name}_{ts}.png"
        try:
            await self._page.screenshot(path=str(path), full_page=True)
        except Exception:
            pass
        return str(path)

    # ── SIAFE2 Login ─────────────────────────────────────────────────────────

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
        Fields: Usuário (CPF), Senha, Cliente (dropdown), Exercício (dropdown).
        An email OTP step may appear after submit.
        """
        await self._page.goto(SIAFE_LOGIN_URL, wait_until="networkidle", timeout=30000)
        await self._vaadin_settle(3)
        await self.screenshot("01_login_page")

        # ── Usuário ───────────────────────────────────────────────────────────
        user_field = await self._find([
            'input[id*="usuario"]',
            'input[name*="usuario"]',
            'input[type="text"]:first-of-type',
        ])
        if not user_field:
            return {"success": False, "message": "Campo 'Usuário' não encontrado na página de login."}
        await user_field.fill(username)

        # ── Senha ─────────────────────────────────────────────────────────────
        pass_field = await self._find([
            'input[type="password"]',
            'input[id*="senha"]',
            'input[name*="senha"]',
        ])
        if not pass_field:
            return {"success": False, "message": "Campo 'Senha' não encontrado."}
        await pass_field.fill(password)

        # ── Cliente (dropdown) ────────────────────────────────────────────────
        for sel in ['select[id*="cliente"]', 'select[name*="cliente"]']:
            try:
                el = await self._page.query_selector(sel)
                if el and cliente:
                    try:
                        await el.select_option(label=cliente)
                    except Exception:
                        await el.select_option(value=cliente)
                break
            except Exception:
                pass

        # ── Exercício (dropdown) ──────────────────────────────────────────────
        year = exercicio or str(datetime.now().year)
        for sel in ['select[id*="exercicio"]', 'select[name*="exercicio"]']:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    try:
                        await el.select_option(label=year)
                    except Exception:
                        try:
                            await el.select_option(value=year)
                        except Exception:
                            pass
                break
            except Exception:
                pass

        await self.screenshot("02_credentials_filled")

        # ── Submit ────────────────────────────────────────────────────────────
        ok_btn = await self._find([
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

        await self._adf_wait(20000)
        await self.screenshot("03_after_submit")

        # ── OTP step ─────────────────────────────────────────────────────────
        body_text = await self._page.inner_text("body")
        if any(kw in body_text.lower() for kw in ["código", "token", "verificação", "autenticação"]):
            otp_input = await self._find([
                'input[name*="codigo"]',
                'input[name*="token"]',
                'input[type="text"]:visible',
            ])
            if otp_input:
                code = await otp_callback() if otp_callback else input("[SIAFE2] OTP code: ").strip()
                await otp_input.fill(code)
                confirm = await self._find([
                    'button:has-text("Confirmar")',
                    'button:has-text("Ok")',
                    'button[type="submit"]',
                ])
                if confirm:
                    await confirm.click()
                else:
                    await self._page.keyboard.press("Enter")
                await self._adf_wait(15000)
                await self.screenshot("04_after_otp")

        # ── Verify ────────────────────────────────────────────────────────────
        url = self._page.url
        if "login.jsp" in url.lower():
            err = await self._adf_error_text()
            return {"success": False, "message": f"Login falhou. {err}".strip(), "url": url}

        self._logged_in = True
        return {"success": True, "message": "Login realizado com sucesso.", "url": url}

    # ── FlexVision Login ──────────────────────────────────────────────────────

    async def ensure_flexvision(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> dict:
        """
        Ensure the current page is FlexVision (logged in).

        Tries (in order):
          1. Already on FlexVision — nothing to do.
          2. Navigate directly to FV_BASE + "#!paineis" (SSO via SIAFE2 session cookie).
          3. If FlexVision shows a login form, fill username/password.
        """
        if "flexvision" in self._page.url.lower():
            return {"success": True, "message": "Já no FlexVision.", "url": self._page.url}

        await self._page.goto(FV_BASE + "#!paineis", wait_until="networkidle", timeout=25000)
        await self._vaadin_settle(3)
        await self.screenshot("05_fv_initial")

        body = await self._page.inner_text("body")

        # FlexVision login page has input[type=text] + input[type=password]
        user_inp = await self._page.query_selector("input[type='text']")
        pass_inp = await self._page.query_selector("input[type='password']")

        if user_inp and pass_inp:
            if not username or not password:
                return {
                    "success": False,
                    "message": "FlexVision pediu login mas credenciais não fornecidas.",
                }
            await user_inp.fill(username)
            await asyncio.sleep(0.3)
            await pass_inp.fill(password)
            await asyncio.sleep(0.3)

            # Click login button
            btns = await self._page.query_selector_all("button, .gwt-Button")
            for btn in btns:
                txt = (await btn.inner_text()).strip().lower()
                if any(k in txt for k in ["login", "entrar", "ok", "acessar"]):
                    await btn.click()
                    break
            else:
                if btns:
                    await btns[0].click()

            await self._vaadin_settle(4)
            await self.screenshot("06_fv_after_login")

        # Confirm we're logged in (sidebar items should be visible)
        body2 = await self._page.inner_text("body")
        has_menu = any(t in body2 for t in ["Paineis", "Consultas", "Gerenciamento"])
        if not has_menu:
            return {
                "success": False,
                "message": "Não foi possível acessar o FlexVision.",
                "page_text": body2[:400],
            }

        return {"success": True, "message": "FlexVision acessado.", "url": self._page.url}

    # ── FlexVision Navigation ─────────────────────────────────────────────────

    async def navigate_to_consultas(self) -> dict:
        """
        Navigate to the Consultas section in FlexVision.

        Uses direct hash navigation (#!consultas) which is more reliable than
        clicking the sidebar item (the sidebar has a <b> category label and a
        <span> nav item both with text "Consultas"; direct navigation is cleaner).
        """
        await self._page.goto(FV_BASE + "#!consultas", wait_until="networkidle", timeout=20000)
        await self._vaadin_settle(3)
        await self.screenshot("07_fv_consultas")

        url = self._page.url
        if "consultas" not in url.lower():
            # The hash didn't stick — try clicking the <span> sidebar item
            result = await self._page.evaluate(_js_click_valo_span("Consultas"))
            await self._vaadin_settle(2)
            url = self._page.url

        body = await self._page.inner_text("body")
        return {
            "success": True,
            "url": url,
            "page_text_preview": body[:600],
        }

    async def navigate_to_execucao_ob(self) -> dict:
        """
        Navigate to the 'Execução por OB' consultation inside FlexVision Consultas.

        The Consultas section shows a list/table of saved consultation reports.
        'Execução por OB' is one of those items — we find it by text and click it
        (Vaadin requires a double-click to open a row in most grid views).
        """
        nav = await self.navigate_to_consultas()
        if not nav["success"]:
            return nav

        await self.screenshot("08_fv_consultas_list")

        # Look for the row — try several text variants
        variants = [
            "Execução por OB",
            "Execucao por OB",
            "Execução OB",
            "Documento - OB",
            "OB",
        ]

        for variant in variants:
            # Try single-click first
            clicked = await self._page.evaluate(_js_click_contains(variant))
            if clicked:
                await self._vaadin_settle(2)
                # Then double-click to open (Vaadin grid rows require dblclick)
                clicked2 = await self._page.evaluate(_js_dblclick_contains(variant))
                if clicked2:
                    await self._vaadin_settle(3)
                    await self.screenshot("09_fv_ob_opened")
                    return {
                        "success": True,
                        "message": f"Consulta '{variant}' aberta.",
                        "url": self._page.url,
                    }
                # Single click might have been enough
                body = await self._page.inner_text("body")
                return {
                    "success": True,
                    "message": f"Consulta '{variant}' clicada.",
                    "url": self._page.url,
                    "page_text": body[:800],
                }

        # Not found — enumerate visible items to help diagnose
        all_els = await self._page.evaluate(_JS_LEAF_ELEMENTS)
        visible = [e["text"] for e in all_els if e.get("visible")]
        await self.screenshot("ERROR_ob_not_found")
        return {
            "success": False,
            "message": "Consulta 'Execução por OB' não encontrada na lista.",
            "visible_items": visible[:40],
        }

    # ── FlexVision Sidebar Navigation ─────────────────────────────────────────

    async def navigate_sidebar(self, item_name: str) -> dict:
        """
        Click a sidebar item in FlexVision by name.
        Uses hash routing when available, falls back to JS click.

        Known hashes:
          paineis, gerenciamento, dimensoes, cubos, parametros,
          agregacoes, monitoramento, consultas
        """
        hash_map = {
            "Paineis":                "#!paineis",
            "Gerenciamento":          "#!gerenciamento",
            "Dimensões":              "#!dimens%C3%B5es",
            "Cubos":                  "#!cubos",
            "Parâmetros":             "#!par%C3%A2metros",
            "Agregações":             "#!agrega%C3%A7%C3%B5es",
            "Monitoramento":          "#!monitoramento",
            "Consultas":              "#!consultas",
        }
        hash_frag = hash_map.get(item_name)
        if hash_frag:
            await self._page.goto(FV_BASE + hash_frag, wait_until="networkidle", timeout=15000)
            await self._vaadin_settle(2)
        else:
            clicked = await self._page.evaluate(_js_click_valo_span(item_name))
            if not clicked:
                clicked = await self._page.evaluate(_js_click_exact(item_name))
            if not clicked:
                return {"success": False, "message": f"Item '{item_name}' não encontrado na barra lateral."}
            await self._vaadin_settle(2)

        return {"success": True, "url": self._page.url}

    # ── Search & Data Extraction ──────────────────────────────────────────────

    async def search_execucao_ob(
        self,
        orgao: Optional[str] = None,
        data_inicio: Optional[str] = None,
        data_fim: Optional[str] = None,
        numero_ob: Optional[str] = None,
    ) -> dict:
        """
        Fill filter fields and execute the Execução por OB query.

        FlexVision filter forms use Vaadin text fields (class="v-textfield").
        Fields don't have stable IDs — we target them by position or label proximity.

        Args:
            orgao:       Órgão code or name  (e.g. "260")
            data_inicio: Start date  DD/MM/AAAA
            data_fim:    End date    DD/MM/AAAA
            numero_ob:   Specific OB number
        """
        await self.screenshot("10_search_form_before")

        # Collect all visible text inputs
        inputs = await self._page.query_selector_all("input[type='text'], input.v-textfield")
        labels_and_inputs = []

        for inp in inputs:
            try:
                ph = await inp.get_attribute("placeholder") or ""
                cls = await inp.get_attribute("class") or ""
                r = await inp.bounding_box()
                if r and r["width"] > 0:
                    labels_and_inputs.append({"el": inp, "ph": ph.lower(), "cls": cls})
            except Exception:
                pass

        def _fill_by_hint(hints: list[str], value: str) -> bool:
            """Fill first input whose placeholder or nearby label matches a hint."""
            for item in labels_and_inputs:
                ph = item["ph"]
                if any(h.lower() in ph for h in hints):
                    asyncio.get_event_loop().run_until_complete(item["el"].triple_click())
                    asyncio.get_event_loop().run_until_complete(item["el"].fill(value))
                    return True
            return False

        # Async version of fill_by_hint
        async def _afill(hints: list[str], value: str) -> bool:
            for item in labels_and_inputs:
                ph = item["ph"]
                if any(h.lower() in ph for h in hints):
                    await item["el"].triple_click()
                    await item["el"].fill(value)
                    return True
            # Fallback: find by label proximity via JS
            for hint in hints:
                result = await self._page.evaluate(f"""
                    () => {{
                        const labels = document.querySelectorAll('label, span, td, th');
                        for (const lbl of labels) {{
                            if (lbl.textContent.toLowerCase().includes('{hint.lower()}')) {{
                                const parent = lbl.closest('tr') || lbl.parentElement;
                                if (parent) {{
                                    const inp = parent.querySelector('input, select');
                                    if (inp) {{ inp.value = '{value}'; inp.dispatchEvent(new Event('input', {{bubbles:true}})); return true; }}
                                }}
                            }}
                        }}
                        return false;
                    }}
                """)
                if result:
                    return True
            return False

        if orgao:
            await _afill(["órgão", "orgao", "unidade", "ug"], orgao)
        if data_inicio:
            await _afill(["início", "inicio", "de", "start", "from"], data_inicio)
        if data_fim:
            await _afill(["fim", "até", "até", "end", "to"], data_fim)
        if numero_ob:
            await _afill(["ob", "número", "numero", "nº"], numero_ob)

        await self.screenshot("11_filters_filled")

        # Submit — FlexVision typically has a button labeled "Consultar", "Gerar", etc.
        submit_clicked = await self._page.evaluate(_js_click_contains("Consultar"))
        if not submit_clicked:
            submit_clicked = await self._page.evaluate(_js_click_contains("Pesquisar"))
        if not submit_clicked:
            submit_clicked = await self._page.evaluate(_js_click_contains("Gerar"))
        if not submit_clicked:
            submit_clicked = await self._page.evaluate(_js_click_contains("Executar"))
        if not submit_clicked:
            # Try standard button selectors
            btn = await self._find([
                'button:has-text("Consultar")',
                'button:has-text("Gerar")',
                'button:has-text("Pesquisar")',
                'button[type="submit"]',
            ])
            if btn:
                await btn.click()
                submit_clicked = True

        if not submit_clicked:
            await self.screenshot("ERROR_no_submit_button")
            return {"success": False, "message": "Botão de consulta não encontrado."}

        await self._vaadin_settle(10)  # OLAPs podem demorar
        await self.screenshot("12_search_results")

        # Count rows in result grid
        row_count = await self._count_grid_rows()
        return {
            "success": True,
            "message": f"Consulta executada. {row_count} linha(s) encontrada(s).",
            "row_count": row_count,
        }

    async def extract_ob_data(self, max_pages: int = 50) -> list[dict]:
        """
        Extract all OB records from the Vaadin grid, handling pagination.

        Vaadin 7/8 grids: .v-grid-row  cells: .v-grid-cell
        Falls back to .v-table-row / .v-table-cell if v-grid is not present.
        """
        all_records: list[dict] = []
        headers = await self._extract_grid_headers()

        for page_num in range(1, max_pages + 1):
            await self.screenshot(f"13_data_page_{page_num:02d}")
            rows = await self._extract_grid_rows(headers)
            if not rows:
                break
            all_records.extend(rows)

            # Pagination: look for "Próxima", ">" buttons
            next_btn = await self._find([
                'button:has-text("Próxima")',
                'button:has-text("Próximo")',
                '[aria-label="Next page"]',
                '[title*="Próxima"]',
            ], timeout=2000)

            if not next_btn:
                break
            disabled = await next_btn.get_attribute("disabled")
            aria_dis = await next_btn.get_attribute("aria-disabled")
            if disabled is not None or aria_dis == "true":
                break

            await next_btn.click()
            await self._vaadin_settle(4)

        return all_records

    # ── Page inspection ───────────────────────────────────────────────────────

    async def get_page_text(self) -> str:
        """Return visible text of the current page (first 8000 chars)."""
        try:
            return (await self._page.inner_text("body"))[:8000]
        except Exception:
            return ""

    async def get_visible_items(self) -> list[str]:
        """Return all visible leaf text items (useful for diagnostics)."""
        els = await self._page.evaluate(_JS_LEAF_ELEMENTS)
        return [e["text"] for e in els if e.get("visible")]

    async def get_page_html(self) -> str:
        return await self._page.content()

    async def get_current_url(self) -> str:
        return self._page.url

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _vaadin_settle(self, seconds: float = 2):
        """Wait for Vaadin JS rendering to settle."""
        try:
            await self._page.wait_for_load_state("networkidle", timeout=int(seconds * 1000 + 2000))
        except Exception:
            pass
        await asyncio.sleep(max(0.5, seconds * 0.5))

    async def _adf_wait(self, timeout: int = 12000):
        """Wait for Oracle ADF page load."""
        try:
            await self._page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            pass
        await asyncio.sleep(1.5)

    async def _find(self, selectors: list[str], timeout: int = 3000):
        """Try selectors on main page in order, return first match."""
        for sel in selectors:
            try:
                el = await self._page.wait_for_selector(sel, timeout=timeout)
                if el:
                    return el
            except Exception:
                continue
        return None

    async def _adf_error_text(self) -> str:
        for sel in [".af_message", "[class*='error']", "[class*='erro']"]:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    t = await el.inner_text()
                    if t.strip():
                        return t.strip()
            except Exception:
                pass
        return ""

    async def _count_grid_rows(self) -> int:
        """Count rows in the Vaadin grid."""
        return await self._page.evaluate("""
            () => {
                const rows = document.querySelectorAll('.v-grid-row, .v-table-row, tbody tr');
                return rows.length;
            }
        """)

    async def _extract_grid_headers(self) -> list[str]:
        """Extract column headers from the Vaadin grid."""
        headers = await self._page.evaluate("""
            () => {
                const sels = [
                    '.v-grid-column-header-content',
                    '.v-treegrid-column-header-content',
                    '.v-table-header-cell',
                    'th',
                    'thead td',
                ];
                for (const sel of sels) {
                    const els = document.querySelectorAll(sel);
                    if (els.length > 0) {
                        return [...els].map(e => e.textContent.trim()).filter(Boolean);
                    }
                }
                return [];
            }
        """)
        return headers or []

    async def _extract_grid_rows(self, headers: list[str]) -> list[dict]:
        """Extract data rows from the Vaadin grid."""
        rows_data = await self._page.evaluate("""
            () => {
                const rowSels = ['.v-grid-row', '.v-table-row', 'tbody tr'];
                const cellSels = ['.v-grid-cell', '.v-table-cell', 'td'];
                let rows = [];
                for (const rSel of rowSels) {
                    rows = [...document.querySelectorAll(rSel)];
                    if (rows.length > 0) break;
                }
                return rows.map(row => {
                    const cells = [];
                    for (const cSel of cellSels) {
                        const cs = row.querySelectorAll(cSel);
                        if (cs.length > 0) {
                            cs.forEach(c => cells.push(c.textContent.trim()));
                            break;
                        }
                    }
                    return cells;
                }).filter(cells => cells.some(Boolean));
            }
        """)
        if not headers:
            return [{"col_" + str(i + 1): v for i, v in enumerate(row)} for row in rows_data]
        return [
            {headers[i] if i < len(headers) else f"col_{i+1}": v for i, v in enumerate(row)}
            for row in rows_data
        ]
