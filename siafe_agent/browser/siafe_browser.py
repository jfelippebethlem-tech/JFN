"""
Playwright automation for SIAFE2 + FlexVision.

Selectors confirmed from live CDP inspection of production system (01/06/2026):

══════════════════════════════════════════════════════════════════════════════
SIAFE2  (Oracle ADF — https://siafe2.fazenda.rj.gov.br/Siafe)
══════════════════════════════════════════════════════════════════════════════

Menu hierarchy (all <a> tags, ALL interactions via page.evaluate — ADF PPR
invalidates ElementHandle objects):

  a.xyo   — top bar tabs:  Planejamento | Execução | Projetos | Apoio | …
  a.xgh   — 2nd-level bar: Execução Orçamentária | Execução Financeira | …
  a.xgg   — 3rd-level menu (left-panel dropdown):
              Ordens Bancárias | OB Orçamentária | OB de Dedução |
              OB de Retenção | OB de Transferência | OB Extra-orçamentária |
              Programações de Desembolso | PD Orçamentária | … |
              Lista de Favorecido para OB | Bloqueio Judicial | …
  a.xg8   — left panel nav item (e.g. "Visualizar OB Orçamentária")
  a.xyp   — detail tabs inside a record:
              Detalhamento | Itens | Pagamentos | OB Complementares [D] |
              ⭐ Processo  ← tab that shows the SEI process number |
              Observação | Espelho Contábil | Registro de Envio | Histórico

Disabled items have class "p_AFDisabled".

Input IDs follow pattern:  tplSip:fieldName::content   (tplSip prefix for
Execução Financeira screens; pt1 prefix on some others).

Key form inputs on OB Orçamentária screen:
  id="tplSip:iTxtCad::content"       — text filter (caderno/nº)
  id="tplSip:selUg::content"         — UG (órgão) select
  id="tplSip:slcTipoAnulacao::content" — tipo de anulação select

OB detail URL:
  /Siafe/faces/execucao/financeira/ordemBancariaOrcamentariaEdit.jsp

Navigation to OB Orçamentária:
  ⚠️  DO NOT click a.xyo "Execução" — it navigates to FlexVision, not SIAFE2.
  1. JS click a.xgg "OB Orçamentária"  (ALWAYS in DOM — direct, no menu traversal)
  2. Fallback: JS click a.xgh "Execução Financeira" → a.xgg "OB Orçamentária"
  3. Left panel: a.xg8 "Visualizar OB Orçamentária"
  4. Select a row → Enter / a.xg8 Visualizar / dblclick → detail screen
  5. Click a.xyp "Processo" tab → SEI process number

══════════════════════════════════════════════════════════════════════════════
FlexVision  (Vaadin 7/8 — https://siafe2-flexvision.fazenda.rj.gov.br/Flexvision/)
══════════════════════════════════════════════════════════════════════════════

Hash routing: #!paineis, #!gerenciamento, #!consultas, #!cubos, etc.
⚠️  page.goto(hash) breaks Vaadin SPA router — always use JS sidebar clicks.

Login:  input[type=text] (username)  +  input[type=password] (password)
Sidebar nav items: <span class="valo-menu-item-caption">
  - "Consultas", "Administração", "Segurança" as <b> = category labels (non-nav)
  - Actual nav items are <span> — click via _js_click_valo_span()

Form inputs:   class="v-textfield v-widget"   (no stable IDs)
Grid headers:  class="v-grid-column-header-content"
Grid rows:     class="v-grid-row"  cells: "v-grid-cell"  (virtual scroll)
All interactions must use page.evaluate() — no standard <a>/<button>

Cube "Documento - OB" (code 000079): OB cadastro data available in FlexVision
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

logger = logging.getLogger(__name__)


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
        except Exception as exc:
            logger.debug("screenshot '%s' falhou: %s", name, exc)
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
            except Exception as exc:
                logger.warning("login: falha ao selecionar cliente '%s' via %s: %s", cliente, sel, exc)

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
                        except Exception as exc:
                            logger.warning("login: exercício '%s' não selecionado (label e value falharam): %s", year, exc)
                break
            except Exception as exc:
                logger.debug("login: sondagem do seletor de exercício %s falhou: %s", sel, exc)

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

    # ── SIAFE2 Execução Navigation ────────────────────────────────────────────

    async def navigate_to_ob_orcamentaria(self) -> dict:
        """
        Navigate to OB Orçamentária.

        IMPORTANT: clicking a.xyo "Execução" navigates to FlexVision, not SIAFE2.
        The a.xgg items are ALWAYS present in the SIAFE2 DOM regardless of which
        top-level menu is active — click directly without going through the menu bar.

        Confirmed selectors (01/06/2026):
          a.xgg  "OB Orçamentária"  (always in DOM, href='#')
          Fallback: a.xgh "Execução Financeira" → a.xgg "OB Orçamentária"
        """
        # Direct path: a.xgg "OB Orçamentária" is always rendered in DOM
        r1 = await self._page.evaluate("""
            () => {
                for (const el of document.querySelectorAll('a.xgg')) {
                    const t = el.textContent.trim();
                    if ((t === 'OB Orçamentária' || t.includes('OB Or'))
                        && !el.className.includes('p_AFDisabled')) {
                        el.click();
                        return 'a.xgg: ' + t;
                    }
                }
                return null;
            }
        """)
        if not r1:
            # Fallback: navigate via Execução Financeira submenu (a.xgh)
            r_fin = await self._adf_js_click("a.xgh", "Execução Financeira")
            if not r_fin:
                r_fin = await self._page.evaluate("""
                    () => {
                        for (const el of document.querySelectorAll('a.xgh')) {
                            if (el.textContent.trim().includes('Financeira')
                                && !el.className.includes('Disabled')) {
                                el.click(); return el.textContent.trim();
                            }
                        }
                        return null;
                    }
                """)
            if not r_fin:
                available = await self._page.evaluate(
                    "() => [...document.querySelectorAll('a.xgh, a.xgg')].map(e => e.textContent.trim()).filter(Boolean)"
                )
                return {"success": False, "step": "xgh Execução Financeira",
                        "message": "Submenu não encontrado.", "available": available}
            await self._adf_wait(8000)

            r1 = await self._adf_js_click("a.xgg", "OB Orçamentária")
            if not r1:
                subs = await self._page.evaluate(
                    "() => [...document.querySelectorAll('a.xgg')].map(e => e.textContent.trim()).filter(Boolean)"
                )
                return {"success": False, "step": "xgg OB Orçamentária",
                        "message": "Item não encontrado.", "available_xgg": subs}

        await self._adf_wait(8000)
        await self.screenshot("ob_orcamentaria")

        return {"success": True, "url": self._page.url,
                "message": "Navegou para OB Orçamentária.", "clicked": r1}

    async def search_ob(
        self,
        ug: Optional[str] = None,
        data_ini: Optional[str] = None,
        data_fim: Optional[str] = None,
        numero: Optional[str] = None,
    ) -> dict:
        """
        Fill OB Orçamentária search filters and click Consultar.

        Known input IDs (tplSip prefix, confirmed 01/06/2026):
          tplSip:selUg::content          — UG (select by option text or value)
          tplSip:iTxtCad::content        — número/caderno (text)

        Date fields don't have stable IDs yet — filled by label proximity.

        Args:
            ug:        UG code (e.g. "010100") or partial name ("ALERJ")
            data_ini:  DD/MM/AAAA
            data_fim:  DD/MM/AAAA
            numero:    OB number
        """
        if ug:
            try:
                sel = await self._page.query_selector("#tplSip\\:selUg\\:\\:content")
                if sel:
                    try:
                        await sel.select_option(label=ug)
                    except Exception:
                        await sel.select_option(value=ug)
            except Exception as exc:
                logger.warning("search_ob: falha ao selecionar UG '%s' em tplSip:selUg — busca seguirá sem filtro de UG: %s", ug, exc)

        if numero:
            try:
                inp = await self._page.query_selector("#tplSip\\:iTxtCad\\:\\:content")
                if inp:
                    await inp.fill(numero)
            except Exception as exc:
                logger.warning("search_ob: falha ao preencher número da OB '%s' em tplSip:iTxtCad: %s", numero, exc)

        # Fill date fields by label proximity (IDs not yet confirmed)
        if data_ini or data_fim:
            await self._page.evaluate(f"""
                () => {{
                    const inputs = [...document.querySelectorAll('input[type="text"], input:not([type])')];
                    for (const inp of inputs) {{
                        if (inp.getBoundingClientRect().width <= 0) continue;
                        let lbl = '';
                        let p = inp.parentElement;
                        for (let i = 0; i < 6 && p; i++, p = p.parentElement) {{
                            const l = p.querySelector('label, span.x18m, span.af_outputLabel');
                            if (l && l !== inp) {{ lbl = l.textContent.trim().toLowerCase(); break; }}
                        }}
                        if ('{data_ini or ""}' && (lbl.includes('in') || lbl.includes('de') || lbl.includes('início')))
                            {{ inp.value = '{data_ini or ""}'; inp.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                        if ('{data_fim or ""}' && (lbl.includes('fim') || lbl.includes('até') || lbl.includes('final')))
                            {{ inp.value = '{data_fim or ""}'; inp.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                    }}
                }}
            """)
            await asyncio.sleep(0.5)

        # Click Consultar
        clicked = await self._page.evaluate("""
            () => {
                const kws = ['consultar', 'pesquisar', 'buscar', 'filtrar', 'listar'];
                for (const btn of document.querySelectorAll('button, a.x7j, a.xg2, input[type="button"], input[type="submit"]')) {
                    const t = (btn.textContent || btn.value || '').trim().toLowerCase();
                    if (kws.some(k => t.includes(k)) && btn.getBoundingClientRect().width > 0) {
                        btn.click(); return t;
                    }
                }
                return null;
            }
        """)
        if not clicked:
            return {"success": False, "message": "Botão Consultar não encontrado."}

        await self._adf_wait(15000)
        await self.screenshot("ob_resultados")

        rows = await self._count_grid_rows()
        return {"success": True, "rows_visible": rows,
                "message": f"Busca executada. {rows} linha(s) visíveis."}

    async def open_ob_detail(self, row_index: int = 0) -> dict:
        """
        Select a row in the OB grid and open its detail screen.

        Tries: click row → Enter → dblclick.
        Returns success + page URL if navigated.
        """
        # Click row by index
        clicked = await self._page.evaluate(f"""
            () => {{
                const sels = ['tr.af_table_row', 'tr[class*="Row"]:not([class*="Header"])', 'tbody tr'];
                for (const sel of sels) {{
                    const rows = [...document.querySelectorAll(sel)];
                    const row = rows[{row_index}];
                    if (row && row.getBoundingClientRect().height > 0) {{
                        row.click();
                        return row.textContent.trim().substring(0, 100);
                    }}
                }}
                return null;
            }}
        """)
        if not clicked:
            return {"success": False, "message": "Nenhuma linha encontrada na grid."}

        body_before = len(await self._page.inner_text("body"))
        await asyncio.sleep(1)
        await self._page.keyboard.press("Enter")
        await self._adf_wait(8000)

        body_after = len(await self._page.inner_text("body"))
        if body_after == body_before:
            # Try double-click
            await self._page.evaluate(f"""
                () => {{
                    const sels = ['tr.af_table_row', 'tr[class*="Row"]:not([class*="Header"])', 'tbody tr'];
                    for (const sel of sels) {{
                        const row = document.querySelectorAll(sel)[{row_index}];
                        if (row) {{ row.dispatchEvent(new MouseEvent('dblclick', {{bubbles:true}})); return; }}
                    }}
                }}
            """)
            await self._adf_wait(8000)

        await self.screenshot("ob_detalhe")
        return {"success": True, "url": self._page.url,
                "row_text": clicked, "message": "Detalhe aberto."}

    async def get_ob_processo_sei(self) -> dict:
        """
        Click the 'Processo' tab in the OB detail screen and extract the SEI
        process number.

        Tab selector: a.xyp  text="Processo"
        Returns the SEI process number (string) and any SEI links found.
        """
        r = await self._adf_js_click("a.xyp", "Processo")
        if not r:
            tabs = await self._page.evaluate(
                "() => [...document.querySelectorAll('a.xyp')].map(e => e.textContent.trim())"
            )
            return {"success": False, "message": "Aba 'Processo' não encontrada.",
                    "available_tabs": tabs}
        await self._adf_wait(6000)
        await self.screenshot("ob_processo_sei")

        # Extract process number and SEI links
        sei_data = await self._page.evaluate("""
            () => {
                const result = {numero: null, links: [], raw_text: ''};

                // Scan all visible text for SEI-like process numbers
                const body = document.body.innerText;
                result.raw_text = body.substring(0, 3000);

                // Regex patterns for SEI-RJ process numbers
                const patterns = [
                    /\\d{7,}-\\d\\.\\d{4}\\.\\d{7}\\/\\d{4}-\\d{2}/g,  // standard SEI
                    /E-\\d{2}\\/\\d+\\/\\d{4}/g,                          // E-xx/NNNNN/AAAA
                    /\\d{4,}\\/\\d{4,}-\\d{2,}/g,                         // generic numeric
                ];
                for (const re of patterns) {
                    const m = body.match(re);
                    if (m && m.length > 0) { result.numero = m[0]; break; }
                }

                // Collect SEI hyperlinks
                for (const a of document.querySelectorAll('a[href]')) {
                    if (/sei/i.test(a.href) || a.textContent.includes('SEI')) {
                        result.links.push({text: a.textContent.trim().substring(0,80), href: a.href});
                    }
                }

                // Look for input/span values near "Processo" label
                for (const el of document.querySelectorAll('*')) {
                    const direct = [...el.childNodes]
                        .filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('');
                    if (/[Pp]rocesso/.test(direct) && direct.length < 50) {
                        const sibling = el.nextElementSibling || el.parentElement?.querySelector('input, span.af_outputText');
                        if (sibling) {
                            const val = sibling.value || sibling.textContent.trim();
                            if (val && !result.numero) result.numero = val;
                        }
                    }
                }

                return result;
            }
        """)

        return {
            "success": True,
            "processo_sei": sei_data.get("numero"),
            "sei_links": sei_data.get("links", []),
            "page_text_preview": sei_data.get("raw_text", "")[:800],
        }

    async def _adf_js_click(self, css: str, text: str) -> Optional[str]:
        """Click ADF element by CSS selector + exact text via JS (no ElementHandle)."""
        safe = text.replace("'", "\\'")
        return await self._page.evaluate(f"""
            () => {{
                for (const el of document.querySelectorAll('{css}')) {{
                    if (el.textContent.trim() === '{safe}' && !el.className.includes('p_AFDisabled')) {{
                        el.dispatchEvent(new MouseEvent('mouseover', {{bubbles: true}}));
                        el.click();
                        return el.tagName + '|' + el.className.trim().substring(0, 60);
                    }}
                }}
                return null;
            }}
        """)

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

        Uses JS sidebar click (valo-menu-item-caption span) rather than page.goto()
        because page.goto() triggers a full reload that breaks Vaadin's SPA router.
        """
        clicked = await self._page.evaluate(_js_click_valo_span("Consultas"))
        if not clicked:
            clicked = await self._page.evaluate(_js_click_exact("Consultas"))
        await self._vaadin_settle(3)
        await self.screenshot("07_fv_consultas")

        body = await self._page.inner_text("body")
        return {
            "success": bool(clicked),
            "url": self._page.url,
            "page_text_preview": body[:600],
        }

    async def navigate_to_execucao_ob(self) -> dict:
        """
        Navigate to the 'Execução por OB' consultation inside FlexVision.

        Strategy (in order):
          1. #!consultas → own queries list → look for 'Execução por OB'
          2. #!consultas → click 'Consultas de outros usuários' → expanded list
          3. #!cubos → double-click 'Documento - OB' cube directly

        Vaadin grid rows need a double-click to open.
        """
        nav = await self.navigate_to_consultas()
        if not nav["success"]:
            return nav

        await self.screenshot("08_fv_consultas_list")

        ob_variants = [
            "Execução por OB",
            "Execucao por OB",
            "Execução OB",
            "Documento - OB",
        ]

        # ── Pass 1: user's own query list ─────────────────────────────────────
        result = await self._try_open_ob_row(ob_variants, "09_fv_ob_pass1")
        if result:
            return result

        # ── Pass 2: click "Consultas de outros usuários" then retry ───────────
        clicked_outros = await self._page.evaluate(
            _js_click_contains("Consultas de outros usuários")
        )
        if clicked_outros:
            await self._vaadin_settle(4)
            await self.screenshot("08b_fv_outros_usuarios")
            result = await self._try_open_ob_row(ob_variants, "09_fv_ob_pass2")
            if result:
                return result

        # ── Pass 3: fallback via Cubos → Documento - OB ───────────────────────
        clicked_cubos = await self._page.evaluate(_js_click_valo_span("Cubos"))
        if not clicked_cubos:
            clicked_cubos = await self._page.evaluate(_js_click_exact("Cubos"))
        await self._vaadin_settle(4)
        await self.screenshot("08c_fv_cubos")

        result = await self._try_open_ob_row(
            ["Documento - OB", "Execução de PD", "OB"], "09_fv_ob_cubo"
        )
        if result:
            return result

        # Nothing worked — return diagnostics
        all_els = await self._page.evaluate(_JS_LEAF_ELEMENTS)
        visible = [e["text"] for e in all_els if e.get("visible")]
        await self.screenshot("ERROR_ob_not_found")
        return {
            "success": False,
            "message": "Consulta 'Execução por OB' não encontrada (tentou lista própria, outros usuários, e cubos).",
            "visible_items": visible[:40],
        }

    async def _try_open_ob_row(self, variants: list[str], screenshot_name: str) -> Optional[dict]:
        """
        Try to single-click then double-click each text variant in the current grid.
        Returns a success dict if opened, or None if not found.
        """
        for variant in variants:
            clicked = await self._page.evaluate(_js_click_contains(variant))
            if clicked:
                await self._vaadin_settle(2)
                clicked2 = await self._page.evaluate(_js_dblclick_contains(variant))
                if clicked2:
                    await self._vaadin_settle(4)
                    await self.screenshot(screenshot_name)
                    return {
                        "success": True,
                        "message": f"Aberto: '{variant}'",
                        "url": self._page.url,
                    }
                # Single click might have navigated
                body = await self._page.inner_text("body")
                await self.screenshot(screenshot_name)
                return {
                    "success": True,
                    "message": f"Clicado: '{variant}'",
                    "url": self._page.url,
                    "page_text": body[:600],
                }
        return None

    # ── FlexVision Sidebar Navigation ─────────────────────────────────────────

    async def navigate_sidebar(self, item_name: str) -> dict:
        """
        Click a sidebar item in FlexVision by name.

        Always uses JS sidebar click (valo-menu-item-caption span) — page.goto()
        triggers a full reload that breaks Vaadin's SPA router.
        """
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
            except Exception as exc:
                logger.debug("search_execucao_ob: input ignorado ao coletar filtros FlexVision: %s", exc)

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
        except Exception as exc:
            logger.debug("_vaadin_settle: networkidle não atingido no FlexVision: %s", exc)
        await asyncio.sleep(max(0.5, seconds * 0.5))

    async def _adf_wait(self, timeout: int = 12000):
        """Wait for Oracle ADF page load."""
        try:
            await self._page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception as exc:
            logger.debug("_adf_wait: networkidle não atingido na tela ADF/SIAFE2: %s", exc)
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
            except Exception as exc:
                logger.debug("_adf_error_text: sondagem do seletor de erro %s falhou: %s", sel, exc)
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
