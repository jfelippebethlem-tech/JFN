"""
Diagnóstico do SIAFE2 — Coleta seletores reais do sistema.

Modos de uso:

  1. Browser novo (padrão):
        python diagnose_siafe.py
     Abre um Chrome novo, faz login com as credenciais do .env.

  2. Conectar ao SEU Chrome já aberto (recomendado!):
        python diagnose_siafe.py --cdp

     Passos para o modo --cdp:
       a) Feche TODOS os Chrome abertos
       b) Abra o Chrome com debug ativado (execute no CMD):
              "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222
       c) No Chrome que abriu, acesse o SIAFE2 e faça login normalmente
       d) Execute este script: python diagnose_siafe.py --cdp

     Assim o script enxerga exatamente o que você vê no seu Chrome.

Ao final gera: diagnostic_report.txt + screenshots em diagnostic_screenshots/
"""

import asyncio
from playwright.async_api import Error as PWError
import os
import sys
from datetime import datetime
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────

def _load_env():
    env = Path(__file__).parent / ".env"
    if not env.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env, override=False)
    except ImportError:
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()


_load_env()

SCREENSHOTS = Path("diagnostic_screenshots")
SCREENSHOTS.mkdir(exist_ok=True)
REPORT = Path("diagnostic_report.txt")

USERNAME  = os.environ.get("SIAFE_USER", "")
PASSWORD  = os.environ.get("SIAFE_PASS", "")
EXERCICIO = os.environ.get("SIAFE_EXERCICIO", "")

SIAFE_LOGIN = "https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp"

report_lines = []


def log(msg: str):
    print(msg)
    report_lines.append(msg)


def sep(title=""):
    line = f"\n{'='*60}"
    if title:
        line += f"\n  {title}\n{'='*60}"
    log(line)


async def dump_page(page, name: str):
    """Screenshot + HTML + visible text + input fields."""
    ts = datetime.now().strftime("%H%M%S")
    shot_path = SCREENSHOTS / f"{name}_{ts}.png"
    await page.screenshot(path=str(shot_path), full_page=True)
    log(f"  📸 Screenshot: {shot_path.name}")

    url = page.url
    log(f"  🌐 URL: {url}")
    log(f"  📄 Título: {await page.title()}")

    # Visible text (truncated)
    try:
        body_text = await page.inner_text("body")
        log("\n  --- Texto visível (primeiros 1500 chars) ---")
        log(body_text[:1500])
    except Exception as e:
        log(f"  [erro ao ler texto: {e}]")

    # All input fields
    sep(f"Inputs em '{name}'")
    inputs = await page.query_selector_all("input, select, textarea, button[type='submit']")
    for inp in inputs:
        try:
            tag    = await inp.evaluate("el => el.tagName.toLowerCase()")
            id_    = await inp.get_attribute("id") or ""
            name_  = await inp.get_attribute("name") or ""
            type_  = await inp.get_attribute("type") or ""
            value_ = await inp.get_attribute("value") or ""
            ph_    = await inp.get_attribute("placeholder") or ""
            cls_   = await inp.get_attribute("class") or ""
            txt_   = ""
            if tag in ("button", "select"):
                txt_ = (await inp.inner_text()).strip()[:60]
            log(f"  <{tag}> id={id_!r:30} name={name_!r:30} type={type_!r:10} value={value_!r:20} placeholder={ph_!r:20} text={txt_!r}")
        except Exception:
            pass

    # Links and clickable elements
    sep(f"Links/clicáveis em '{name}'")
    links = await page.query_selector_all("a, button, [onclick]")
    seen = set()
    for el in links[:80]:
        try:
            txt = (await el.inner_text()).strip()
            href = await el.get_attribute("href") or ""
            cls  = await el.get_attribute("class") or ""
            if txt and txt not in seen and len(txt) < 100:
                log(f"  {txt!r:40} href={href[:60]!r:30} class={cls[:40]!r}")
                seen.add(txt)
        except Exception:
            pass

    # iFrames
    frames = page.frames
    if len(frames) > 1:
        sep(f"iFrames em '{name}'")
        for f in frames:
            log(f"  Frame URL: {f.url}")

    # Save full HTML
    html_path = SCREENSHOTS / f"{name}_{ts}.html"
    try:
        html = await page.content()
        html_path.write_text(html, encoding="utf-8")
        log(f"\n  💾 HTML completo salvo: {html_path.name} ({len(html)} chars)")
    except Exception as e:
        log(f"  [erro ao salvar HTML: {e}]")

    return shot_path


_SIAFE_OB_URL = (
    "https://siafe2.fazenda.rj.gov.br/Siafe/faces/execucao/financeira"
    "/ordemBancariaOrcamentariaEdit.jsp"
)


async def _dismiss_all_dialogs(page, max_iter: int = 6) -> list[str]:
    """
    Dismiss all visible SIAFE2 modal dialogs: admin messages, session conflicts,
    and generic OK/Cancelar modals.  Returns list of what was dismissed.

    Called immediately after login submit and after any navigation that might
    trigger a popup.
    """
    dismissed = []
    for _ in range(max_iter):
        result = await page.evaluate("""
            () => {
                // 1. Admin message or session-conflict dialog with Sim/Não
                const sim = document.getElementById('myBtnOk');
                if (sim && sim.getBoundingClientRect().width > 0) {
                    sim.click(); return 'sim_nao_dialog';
                }
                // 2. Generic visible OK button (class x7j or xg2), NOT the Não/Cancelar
                const skip = new Set(['myBtnCancel']);
                for (const sel of ['a.x7j', 'a.xg2']) {
                    for (const el of document.querySelectorAll(sel)) {
                        if (skip.has(el.id)) continue;
                        const t = el.textContent.trim().toLowerCase();
                        const r = el.getBoundingClientRect();
                        if ((t === 'ok' || t === 'sim') && r.width > 0 && r.height > 0
                                && !el.className.includes('p_AFDisabled')) {
                            el.click();
                            return 'ok_btn: ' + el.id + '/' + t;
                        }
                    }
                }
                return null;
            }
        """)
        if result:
            dismissed.append(result)
            await asyncio.sleep(2)
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
        else:
            break
    return dismissed


async def _navigate_to_ob_url(page, log_prefix: str = "") -> bool:
    """
    Navigate directly to the OB Orçamentária URL (ADF direct URL approach).
    Works from any section as long as the user session is valid.
    Returns True if landed on OB screen.
    """
    pfx = f"  {log_prefix}" if log_prefix else "  "
    log(f"{pfx}Navegando direto para URL OB: {_SIAFE_OB_URL}")
    try:
        await page.goto(_SIAFE_OB_URL, wait_until="networkidle", timeout=20000)
    except Exception as e:
        log(f"{pfx}[timeout/error ao navegar: {e} — continuando]")
    await asyncio.sleep(2)
    url = page.url
    log(f"{pfx}URL resultante: {url}")
    return "ordemBancariaOrcamentaria" in url.lower()


async def _navigate_ob_via_menu(page) -> bool:
    """
    Navigate to OB Orçamentária via the menu hierarchy.
    Handles both contexts:
      - Administração page: click a.xgh "Execução" → a.xgg "OB Orçamentária"
      - Any other page:     click a.xgg "OB Orçamentária" directly (always in DOM)
    Returns True if OB screen reached.
    """
    # From Administração or unknown context: click "Execução" at whichever level it is
    r_exec = await page.evaluate("""
        () => {
            // Try every navigation class — the CSS class changes by section
            for (const sel of ['a.xgh', 'a.xyo', 'a.xg8']) {
                for (const el of document.querySelectorAll(sel)) {
                    const t = el.textContent.trim();
                    if (t === 'Execução' && !el.className.includes('Disabled')
                            && el.getBoundingClientRect().width > 0) {
                        el.click();
                        return sel + ': ' + t;
                    }
                }
            }
            return null;
        }
    """)
    if r_exec:
        log(f"  Clicou Execução: {r_exec}")
        await asyncio.sleep(3)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

    # Now click a.xgg "OB Orçamentária" (should be in DOM if we're in Execução)
    r_ob = await page.evaluate("""
        () => {
            for (const el of document.querySelectorAll('a.xgg')) {
                const t = el.textContent.trim();
                if ((t === 'OB Orçamentária' || t.includes('OB Or'))
                        && !el.className.includes('p_AFDisabled')) {
                    el.click();
                    return t;
                }
            }
            return null;
        }
    """)
    log(f"  Clicou OB Orçamentária: {r_ob}")
    if r_ob:
        await asyncio.sleep(3)
        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        return "ordemBancariaOrcamentaria" in page.url.lower() or r_ob is not None

    return False


async def main():
    """
    Modo padrão (sem flags): abre browser novo, faz login, navega para
    OB Orçamentária e executa o deep-dive completo.

    Trata automaticamente:
      - Diálogos de mensagem do administrador (OK para fechar)
      - Conflito de sessão (Sim para continuar)
      - Seleção automática do exercício correto
    """
    from playwright.async_api import async_playwright

    log(f"SIAFE2 Diagnóstico — {datetime.now():%d/%m/%Y %H:%M}")
    log(f"Usuário: {USERNAME}")
    log(f"Exercício configurado: {EXERCICIO or str(datetime.now().year)}")

    if not USERNAME or not PASSWORD:
        log("\n❌ SIAFE_USER e SIAFE_PASS não encontrados no .env!")
        log("   Preencha o arquivo .env antes de rodar este script.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=200,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--ignore-certificate-errors"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            ignore_https_errors=True,
        )
        page = await ctx.new_page()

        # ── Etapa 1: Login page ────────────────────────────────────────────────
        sep("ETAPA 1: Página de Login")
        log(f"  Abrindo: {SIAFE_LOGIN}")
        try:
            await page.goto(SIAFE_LOGIN, wait_until="networkidle", timeout=30000)
        except Exception as e:
            log(f"  Erro: {e}")
            await page.goto(SIAFE_LOGIN, timeout=30000)
        await asyncio.sleep(2)
        await dump_page(page, "01_login_page")

        # ── Etapa 2: Fill credentials ──────────────────────────────────────────
        sep("ETAPA 2: Preenchendo credenciais")
        # Username
        try:
            u = await page.query_selector("#loginBox\\:itxUsuario\\:\\:content, input[type='text']:not([readonly])")
            if u:
                log(f"  → Usuário: {await u.get_attribute('id')!r}")
                await u.click()
                await u.fill(USERNAME)
        except Exception as e:
            log(f"  [erro usuário: {e}]")

        # Password
        try:
            pw = await page.query_selector("input[type='password']")
            if pw:
                log(f"  → Senha: {await pw.get_attribute('id')!r}")
                await pw.fill(PASSWORD)
        except Exception as e:
            log(f"  [erro senha: {e}]")

        # Exercício select — always pick current year (or configured)
        ano_alvo = EXERCICIO or str(datetime.now().year)
        try:
            sel_exercicio = await page.query_selector(
                "#loginBox\\:cbxExercicio\\:\\:content, select[id*='Exercicio'], select[id*='exercicio']"
            )
            if sel_exercicio:
                try:
                    await sel_exercicio.select_option(label=ano_alvo)
                    log(f"  → Exercício selecionado: {ano_alvo}")
                except Exception:
                    # Try value
                    opts = await sel_exercicio.query_selector_all("option")
                    for o in opts:
                        v = await o.get_attribute("value") or ""
                        t = await o.inner_text()
                        if ano_alvo in (v, t.strip()):
                            await sel_exercicio.select_option(value=v)
                            log(f"  → Exercício (value): {v}")
                            break
        except Exception as e:
            log(f"  [erro exercício: {e}]")

        await dump_page(page, "02_credentials_filled")

        # ── Etapa 3: Submit ────────────────────────────────────────────────────
        sep("ETAPA 3: Submetendo login")
        # Target the specific login confirm button (not the Sim/Não popup buttons)
        login_btn = await page.query_selector(
            "#loginBox\\:btnConfirmar, "
            "a.x7j[id*='Confirmar'], a.x7j[id*='btnOk'], "
            "input[value='Ok'], button[type='submit']"
        )
        if login_btn:
            log(f"  → Clicando botão login: {await login_btn.get_attribute('id')!r}")
            await login_btn.click()
        else:
            # Fallback: click first visible 'Ok' link that's NOT the Sim/Não popup
            clicked = await page.evaluate("""
                () => {
                    for (const el of document.querySelectorAll('a.x7j')) {
                        const t = el.textContent.trim().toLowerCase();
                        const r = el.getBoundingClientRect();
                        if (t === 'ok' && r.width > 0 && el.id !== 'myBtnOk') {
                            el.click(); return el.id;
                        }
                    }
                    return null;
                }
            """)
            log(f"  → Fallback: {clicked!r}")

        log("  Aguardando carregamento pós-login...")
        await asyncio.sleep(4)
        try:
            await page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        await asyncio.sleep(2)
        await dump_page(page, "03_after_login")

        # ── Etapa 4: Fechar diálogos pós-login ────────────────────────────────
        sep("ETAPA 4: Fechando diálogos pós-login (admin messages, sessão, etc.)")
        dismissed = await _dismiss_all_dialogs(page)
        if dismissed:
            log(f"  Diálogos fechados: {dismissed}")
            await dump_page(page, "04_after_dialogs")
        else:
            log("  Nenhum diálogo ativo detectado")

        current_url = page.url
        log(f"  URL pós-login: {current_url}")
        if "login" in current_url.lower():
            log("  ⚠️  Ainda na página de login — credenciais incorretas ou OTP necessário")
            body_txt = await page.inner_text("body")
            log(body_txt[:600])
            # OTP check
            if any(kw in body_txt.lower() for kw in ["código", "token", "e-mail", "autenticação", "verificação"]):
                log("  🔐 OTP solicitado!")
                otp = input("  Digite o código OTP: ").strip()
                otp_inp = await page.query_selector("input[type='text']:visible")
                if otp_inp:
                    await otp_inp.fill(otp)
                await page.keyboard.press("Enter")
                await asyncio.sleep(4)
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                dismissed2 = await _dismiss_all_dialogs(page)
                log(f"  Diálogos pós-OTP: {dismissed2}")
                await dump_page(page, "04b_after_otp")
        else:
            log("  ✅ Login realizado com sucesso!")

        # ── Etapa 5: Navegar para OB Orçamentária ────────────────────────────
        sep("ETAPA 5: Navegando para OB Orçamentária")
        # Strategy 1: direct URL (fastest, works from any section)
        on_ob = await _navigate_to_ob_url(page)
        if not on_ob:
            # Strategy 2: via menu hierarchy
            log("  Fallback: via menu")
            on_ob = await _navigate_ob_via_menu(page)
        # Dismiss any dialog that appeared after navigation
        await _dismiss_all_dialogs(page)
        await dump_page(page, "05_ob_screen")
        log(f"  Na tela OB: {on_ob}")

        # ── Etapa 6: OB deep-dive (reutiliza main_ob logic) ───────────────────
        sep("ETAPA 6: Deep-dive OB (delegando para lógica main_ob)")
        log("  Continuando diagnóstico OB com browser aberto...")
        # Run the same exploration loop used in --ob mode
        await _ob_deep_dive(page)

        log("\n  Aguardando 15s para você visualizar...")
        await asyncio.sleep(15)
        await browser.close()

    REPORT.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n✅ Relatório salvo em: {REPORT}")


_JS_LEAF_ELEMENTS = """
    () => {
        const results = [];
        document.querySelectorAll('*').forEach(el => {
            const directText = [...el.childNodes]
                .filter(n => n.nodeType === 3)
                .map(n => n.textContent.trim())
                .join('');
            if (directText && directText.length < 120 && directText.length > 1) {
                const r = el.getBoundingClientRect();
                results.push({
                    tag: el.tagName,
                    cls: el.className,
                    id: el.id,
                    text: directText,
                    onclick: el.onclick ? 'yes' : 'no',
                    visible: r.width > 0 && r.height > 0
                });
            }
        });
        return results;
    }
"""

def _js_click_exact(text: str) -> str:
    """Returns JS that clicks element whose direct text equals `text`."""
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
                    return el.tagName + ' | cls=' + el.className + ' | id=' + el.id;
                }}
            }}
            return null;
        }}
    """

def _js_click_contains(text: str) -> str:
    """Returns JS that clicks smallest visible element containing `text`."""
    safe = text.replace("'", "\\'")
    return f"""
        () => {{
            let best = null, bestSize = Infinity;
            for (const el of document.querySelectorAll('*')) {{
                if (!el.textContent.includes('{safe}')) continue;
                const r = el.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) continue;
                const size = r.width * r.height;
                if (size < bestSize) {{ best = el; bestSize = size; }}
            }}
            if (best) {{
                best.click();
                return best.tagName + ' | cls=' + best.className + ' | text=' + best.textContent.trim().substring(0,80);
            }}
            return null;
        }}
    """


def _js_click_valo_span(text: str) -> str:
    """Returns JS that clicks <span class='valo-menu-item-caption'> with exact text."""
    safe = text.replace("'", "\\'")
    return f"""
        () => {{
            for (const el of document.querySelectorAll('span.valo-menu-item-caption')) {{
                if (el.textContent.trim() === '{safe}') {{
                    el.click();
                    return 'SPAN|' + el.className + '|' + el.textContent.trim();
                }}
            }}
            return null;
        }}
    """


def _js_dblclick_contains(text: str) -> str:
    """Returns JS that double-clicks smallest visible element containing `text`."""
    safe = text.replace("'", "\\'")
    return f"""
        () => {{
            let best = null, bestSize = Infinity;
            for (const el of document.querySelectorAll('*')) {{
                if (!el.textContent.includes('{safe}')) continue;
                const r = el.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) continue;
                const size = r.width * r.height;
                if (size < bestSize) {{ best = el; bestSize = size; }}
            }}
            if (best) {{
                best.dispatchEvent(new MouseEvent('dblclick', {{bubbles: true}}));
                return best.tagName + ' | cls=' + best.className + ' | text=' + best.textContent.trim().substring(0,80);
            }}
            return null;
        }}
    """


async def _dump_inputs(page, label: str):
    """Log all input/select/button elements on the page."""
    sep(f"Formulário: {label}")
    form_inputs = await page.query_selector_all("input, select, textarea, button")
    log(f"  {len(form_inputs)} inputs/botões:")
    for inp in form_inputs:
        try:
            tag = await inp.evaluate("el => el.tagName.toLowerCase()")
            id_ = await inp.get_attribute("id") or ""
            nm  = await inp.get_attribute("name") or ""
            tp  = await inp.get_attribute("type") or ""
            cls = await inp.get_attribute("class") or ""
            ph  = await inp.get_attribute("placeholder") or ""
            txt = (await inp.inner_text()).strip()[:50]
            log(f"    <{tag}> id={id_!r:35} name={nm!r:25} type={tp!r:12} "
                f"class={cls[:35]!r} ph={ph!r} txt={txt!r}")
        except Exception:
            pass


async def _explore_flexvision(page):
    """Explora o FlexVision via JavaScript (Vaadin/GWT não usa <a>/<button> padrão)."""
    FV_BASE = "https://siafe2-flexvision.fazenda.rj.gov.br/Flexvision/"

    sep("EXPLORANDO FLEXVISION — snapshot inicial")
    await dump_page(page, "fv_00_initial")

    # ── 1. Classes CSS ──────────────────────────────────────────────────────────
    sep("Classes CSS usadas no FlexVision")
    all_classes = await page.evaluate("""
        () => {
            const classes = new Set();
            document.querySelectorAll('*').forEach(el => {
                el.classList.forEach(c => classes.add(c));
            });
            return [...classes].sort().filter(c => c.length > 2);
        }
    """)
    log(f"  Total: {len(all_classes)} classes")
    log(f"  {', '.join(all_classes)}")

    # ── 2. Todos os elementos com texto direto ──────────────────────────────────
    sep("Elementos com texto direto (folhas da árvore DOM)")
    elements = await page.evaluate(_JS_LEAF_ELEMENTS)
    log(f"  Total: {len(elements)} elementos")
    for e in elements:
        vis = "✓" if e.get("visible") else "·"
        log(f"  {vis} <{e['tag'].lower():6}> text={e['text']!r:45} cls={e['cls']!r:45} id={e['id']!r}")

    # ── 3. Clicar em cada item do menu lateral ──────────────────────────────────
    # Menus visíveis na barra lateral conforme diagnóstico anterior
    sidebar_menus = [
        "Paineis", "Gerenciamento", "Administração", "Dimensões", "Cubos",
        "Parâmetros", "Agregações", "Exportação/Importação", "Monitoramento",
        "Consultas", "Segurança", "Visibilidades", "Alteração de Senha", "Sobre",
    ]

    sep("Navegando por cada item do menu lateral")
    for menu_name in sidebar_menus:
        url_before = page.url
        clicked = await page.evaluate(_js_click_exact(menu_name))
        if not clicked:
            # Fallback: try contains
            clicked = await page.evaluate(_js_click_contains(menu_name))

        if clicked:
            await asyncio.sleep(2)
            url_after = page.url
            hash_part = ("#" + url_after.split("#", 1)[1]) if "#" in url_after else "(sem hash)"
            log(f"\n  ── {menu_name} ──")
            log(f"     Elemento: {clicked}")
            log(f"     Hash URL: {hash_part}")

            body = await page.inner_text("body")
            log(f"     Texto ({len(body)} chars): {body[:600]}")

            # Salvar screenshot + HTML deste menu
            safe_name = menu_name[:15].replace("/", "_").replace(" ", "_").lower()
            await dump_page(page, f"fv_menu_{safe_name}")

            # Capturar sub-itens que apareceram
            sub_els = await page.evaluate(_JS_LEAF_ELEMENTS)
            new_texts = {e["text"] for e in sub_els} - {e["text"] for e in elements}
            if new_texts:
                log(f"     Novos itens após clicar: {sorted(new_texts)}")

            # Formulário de inputs nesta view
            await _dump_inputs(page, menu_name)

            # ── Caso especial: Consultas — explorar sub-itens ───────────────
            if menu_name == "Consultas":
                sep("  Sub-itens de Consultas")
                all_sub = await page.evaluate(_JS_LEAF_ELEMENTS)
                log(f"  {len(all_sub)} elementos após abrir Consultas:")
                for e in all_sub:
                    vis = "✓" if e.get("visible") else "·"
                    log(f"    {vis} {e['text']!r:50} cls={e['cls']!r:40} id={e['id']!r}")

                # Tentar clicar em "Execução por OB" ou variações
                sep("  Clicando em 'Execução por OB'")
                ob_variants = [
                    "Execução por OB", "Execucao por OB", "Execução por Ob",
                    "ExecuçãoOB", "OB", "Ordens Bancárias", "Exec. por OB",
                ]
                ob_found = False
                for variant in ob_variants:
                    clicked2 = await page.evaluate(_js_click_exact(variant))
                    if not clicked2:
                        clicked2 = await page.evaluate(_js_click_contains(variant))
                    if clicked2:
                        log(f"  ✅ Clicado '{variant}': {clicked2}")
                        await asyncio.sleep(2)
                        hash_ob = ("#" + page.url.split("#", 1)[1]) if "#" in page.url else ""
                        log(f"  URL hash: {hash_ob}")
                        await dump_page(page, "fv_execucao_ob")
                        await _dump_inputs(page, "Execução por OB")

                        # Capturar texto completo da tela de OB
                        ob_body = await page.inner_text("body")
                        log(f"  Texto da tela OB:\n{ob_body[:2000]}")

                        # Enumerar todos elementos para mapear form fields
                        ob_els = await page.evaluate(_JS_LEAF_ELEMENTS)
                        log(f"\n  Elementos na tela OB ({len(ob_els)}):")
                        for e in ob_els:
                            log(f"    {e['text']!r:55} cls={e['cls']!r:40}")
                        ob_found = True
                        break
                    else:
                        log(f"  ❌ Não encontrou '{variant}'")

                if not ob_found:
                    log("  ⚠️  'Execução por OB' não encontrado. "
                        "Listando todos os itens visíveis após clicar Consultas:")
                    consult_els = await page.evaluate(_JS_LEAF_ELEMENTS)
                    for e in consult_els:
                        if e.get("visible"):
                            log(f"    ✓ {e['text']!r:55} cls={e['cls']!r}")
        else:
            log(f"\n  ── {menu_name}: ❌ não encontrado no DOM")

    # ── 4. Tentar hashes conhecidos diretamente ─────────────────────────────────
    sep("Testando hashes de URL diretamente")
    hash_candidates = [
        "#!consultas", "#!execucao-ob", "#!execucaoob", "#!execucao_ob",
        "#!relatorios", "#!exec-ob", "#!execob", "#!paineis",
    ]
    for h in hash_candidates:
        try:
            await page.goto(FV_BASE + h, timeout=10000)
            await asyncio.sleep(2)
            body = await page.inner_text("body")
            has_error = "could not be found" in body.lower() or "não encontrad" in body.lower()
            status = "❌ erro" if has_error else "✅ ok"
            log(f"  {status}  {FV_BASE + h}  →  {body[:120]!r}")
        except Exception as ex:
            log(f"  💥  {h}: {ex}")

    # ── 5. HTML completo ────────────────────────────────────────────────────────
    html = await page.content()
    html_path = SCREENSHOTS / "fv_full_dom.html"
    html_path.write_text(html, encoding="utf-8")
    log(f"\n  HTML completo salvo: {html_path.name} ({len(html)} chars)")


async def main_cdp():
    """Conecta ao Chrome já aberto com --remote-debugging-port=9222."""
    from playwright.async_api import async_playwright

    log(f"SIAFE2 Diagnóstico (modo CDP) — {datetime.now():%d/%m/%Y %H:%M}")
    log("Conectando ao Chrome local na porta 9222...")
    log("(Certifique-se que o Chrome foi aberto com --remote-debugging-port=9222)")

    async with async_playwright() as p:
        try:
            # Usa 127.0.0.1 — no Windows, "localhost" resolve como ::1 (IPv6) e falha
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        except Exception as e:
            log(f"\n❌ Não conseguiu conectar: {e}")
            log("\nVerifique:")
            log("  1. Chrome está aberto com --remote-debugging-port=9222 ?")
            log("  2. Nenhum outro Chrome estava aberto antes?")
            log('  3. Tente: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222')
            return

        log("✅ Conectado ao Chrome!")
        contexts = browser.contexts
        log(f"  {len(contexts)} contexto(s) aberto(s)")

        for ctx_i, ctx in enumerate(contexts):
            pages = ctx.pages
            log(f"\n  Contexto {ctx_i}: {len(pages)} aba(s)")
            for pg_i, pg in enumerate(pages):
                log(f"    Aba {pg_i}: {pg.url} — {await pg.title()}")

        # Usar a aba com SIAFE2 aberto, ou a primeira aba
        target_page = None
        for ctx in contexts:
            for pg in ctx.pages:
                if "siafe" in pg.url.lower() or "fazenda.rj" in pg.url.lower():
                    target_page = pg
                    log(f"\n✅ Aba SIAFE2 encontrada: {pg.url}")
                    break
            if target_page:
                break

        if not target_page and contexts and contexts[0].pages:
            target_page = contexts[0].pages[0]
            log(f"\n  (Usando primeira aba disponível: {target_page.url})")

        if not target_page:
            log("\n❌ Nenhuma aba encontrada. Abra o SIAFE2 no Chrome e tente de novo.")
            return

        sep("Página atual do SIAFE2")
        await dump_page(target_page, "cdp_01_current_page")

        # ── Explorar menus principais ──────────────────────────────────────────
        sep("Explorando menus principais (Execução, Relatórios, etc.)")

        # Menus principais conhecidos (classe ADF xyo)
        main_menus = ["Execução", "Relatórios", "Apoio", "Projetos", "Planejamento"]
        for menu_name in main_menus:
            sep(f"Menu: {menu_name}")
            try:
                # Clicar no menu
                menu_el = await target_page.query_selector(f"a.xyo:has-text('{menu_name}'), span.xyo:has-text('{menu_name}')")
                if not menu_el:
                    # Tentar seletores mais amplos
                    all_els = await target_page.query_selector_all(".xyo")
                    for el in all_els:
                        t = (await el.inner_text()).strip()
                        if t == menu_name:
                            menu_el = el
                            break
                if not menu_el:
                    log(f"  ❌ Menu '{menu_name}' não encontrado na página")
                    continue

                log(f"  → Clicando em '{menu_name}'...")
                await menu_el.click()
                await asyncio.sleep(1.5)

                # Capturar submenus que apareceram
                submenu_items = await target_page.query_selector_all(".xgh")
                log(f"  Submenus (.xgh) encontrados: {len(submenu_items)}")
                for item in submenu_items:
                    try:
                        t = (await item.inner_text()).strip()
                        cls = await item.get_attribute("class") or ""
                        if t:
                            log(f"    - {t!r:40} class={cls!r}")
                    except Exception:
                        pass

                await dump_page(target_page, f"cdp_menu_{menu_name.lower()}")

                # Se é Execução, explorar submenus
                if menu_name == "Execução":
                    sep("  Submenus de Execução (clicando em cada um)")
                    for item in submenu_items[:10]:
                        try:
                            t = (await item.inner_text()).strip()
                            if not t or "Disabled" in (await item.get_attribute("class") or ""):
                                continue
                            log(f"    → Clicando em '{t}'...")
                            await item.click()
                            await asyncio.sleep(1.5)
                            # Capturar sub-submenus
                            subsubitems = await target_page.query_selector_all(".xgg")
                            if subsubitems:
                                log(f"      Sub-submenus (.xgg): {len(subsubitems)}")
                                for ssi in subsubitems:
                                    sst = (await ssi.inner_text()).strip()
                                    if sst:
                                        log(f"        - {sst!r}")
                            await dump_page(target_page, f"cdp_execucao_sub_{t[:20].replace(' ', '_').lower()}")
                            # Voltar para Execução
                            menu_el2 = None
                            all_els2 = await target_page.query_selector_all(".xyo")
                            for e2 in all_els2:
                                if (await e2.inner_text()).strip() == "Execução":
                                    menu_el2 = e2
                                    break
                            if menu_el2:
                                await menu_el2.click()
                                await asyncio.sleep(1)
                        except Exception as ex:
                            log(f"      [erro: {ex}]")

            except Exception as ex:
                log(f"  Erro ao explorar '{menu_name}': {ex}")

        # ── Se já estamos no FlexVision, explorar diretamente e encerrar ───────
        if "flexvision" in target_page.url.lower():
            await _explore_flexvision(target_page)
            sep("DIAGNÓSTICO CDP CONCLUÍDO (FlexVision já estava aberto)")
            log(f"  Screenshots em: {SCREENSHOTS}/")
            log(f"  Relatório em:   {REPORT}")
            REPORT.write_text("\n".join(report_lines), encoding="utf-8")
            print(f"\n✅ Relatório salvo em: {REPORT}")
            return

        # ── Login no FlexVision (sistema separado) ────────────────────────────
        sep("LOGIN NO FLEXVISION")
        FV_URL = "https://siafe2-flexvision.fazenda.rj.gov.br/Flexvision/"
        log(f"  Navegando para: {FV_URL}")
        try:
            await target_page.goto(FV_URL, timeout=25000, wait_until="networkidle")
            await asyncio.sleep(2)
            log(f"  URL: {target_page.url}")
            log(f"  Título: {await target_page.title()}")
            await dump_page(target_page, "fv_01_login_page")

            # Preencher credenciais (IDs GWT são dinâmicos, usar type)
            user_input = await target_page.query_selector("input[type='text']")
            pass_input = await target_page.query_selector("input[type='password']")

            if user_input and pass_input:
                log("  ✅ Campos encontrados — preenchendo credenciais")
                await user_input.fill(USERNAME)
                await asyncio.sleep(0.5)
                await pass_input.fill(PASSWORD)
                await asyncio.sleep(0.5)

                # Botão Login
                login_btn = await target_page.query_selector("button, .gwt-Button")
                buttons = await target_page.query_selector_all("button, .gwt-Button, .gwt-SubmitButton")
                log(f"  Botões encontrados: {len(buttons)}")
                for btn in buttons:
                    txt = (await btn.inner_text()).strip()
                    cls = await btn.get_attribute("class") or ""
                    log(f"    - {txt!r:30} class={cls!r}")

                # Clicar no botão de login
                clicked = False
                for btn in buttons:
                    txt = (await btn.inner_text()).strip().lower()
                    if "login" in txt or "entrar" in txt or "ok" in txt:
                        log(f"  → Clicando: {txt!r}")
                        await btn.click()
                        clicked = True
                        break
                if not clicked and buttons:
                    log("  → Clicando no primeiro botão disponível")
                    await buttons[0].click()

                await asyncio.sleep(3)
                try:
                    await target_page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                await asyncio.sleep(2)

                log(f"  URL pós-login: {target_page.url}")
                log(f"  Título pós-login: {await target_page.title()}")
                await dump_page(target_page, "fv_02_after_login")

                # ── Explorar menus do FlexVision ──────────────────────────────
                sep("MENUS DO FLEXVISION (pós-login)")
                body_text = await target_page.inner_text("body")
                log(f"  Texto da página ({len(body_text)} chars):\n{body_text[:3000]}")

                # Listar todos os elementos clicáveis
                sep("Todos os links/botões do FlexVision")
                all_els = await target_page.query_selector_all("a, button, li, [role='menuitem'], .gwt-TreeItem, .menuItem, td[onclick], span[onclick]")
                log(f"  {len(all_els)} elementos clicáveis:")
                seen = set()
                for el in all_els[:150]:
                    try:
                        t = (await el.inner_text()).strip()
                        cls = await el.get_attribute("class") or ""
                        href = await el.get_attribute("href") or ""
                        if t and t not in seen and len(t) < 100:
                            log(f"    {t!r:50} class={cls[:40]!r} href={href[:40]!r}")
                            seen.add(t)
                    except Exception:
                        pass

                # Frames dentro do FlexVision
                sep("Frames do FlexVision")
                for f in target_page.frames:
                    log(f"  Frame: {f.url}")
                    if f.url and f.url != "about:blank":
                        try:
                            ftxt = await f.inner_text("body")
                            log(f"  → Texto: {ftxt[:500]}")
                        except Exception:
                            pass

                # Navegar para #!paineis e depois explorar completamente
                sep("Navegando para #!paineis")
                await target_page.goto(f"{FV_URL}#!paineis", timeout=15000)
                await asyncio.sleep(3)
                await _explore_flexvision(target_page)

            else:
                log("  ❌ Campos de login não encontrados no FlexVision")
                body = await target_page.inner_text("body")
                log(f"  Texto: {body[:500]}")

        except Exception as ex:
            log(f"  Erro ao navegar FlexVision: {ex}")

        # Screenshot final
        sep("Screenshot final")
        await dump_page(target_page, "cdp_03_final")

        log("\n" + "="*60)
        log("  DIAGNÓSTICO CDP CONCLUÍDO")
        log(f"  Screenshots em: {SCREENSHOTS}/")
        log(f"  Relatório em:   {REPORT}")
        log("="*60)

    REPORT.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n✅ Relatório salvo em: {REPORT}")


async def _cdp_connect():
    """Connect to Chrome via CDP and return (browser, target_page)."""
    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    try:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    except Exception as e:
        log(f"❌ Não conectou: {e}")
        return p, None, None
    target_page = None
    for ctx in browser.contexts:
        for pg in ctx.pages:
            if "flexvision" in pg.url.lower() or "fazenda.rj" in pg.url.lower():
                target_page = pg
                break
        if target_page:
            break
    if not target_page and browser.contexts and browser.contexts[0].pages:
        target_page = browser.contexts[0].pages[0]
    return p, browser, target_page


async def _dump_grid_rows(page, label: str):
    """Dump all rows visible in a Vaadin v-grid."""
    sep(f"Linhas da grid: {label}")
    rows = await page.evaluate("""
        () => {
            const rowSels = ['.v-grid-row', '.v-table-row', 'tbody tr'];
            const cellSels = ['.v-grid-cell', '.v-table-cell', 'td'];
            for (const rSel of rowSels) {
                const rows = [...document.querySelectorAll(rSel)];
                if (!rows.length) continue;
                return rows.map(row => {
                    for (const cSel of cellSels) {
                        const cells = [...row.querySelectorAll(cSel)];
                        if (cells.length) return cells.map(c => c.textContent.trim());
                    }
                    return [row.textContent.trim()];
                }).filter(r => r.some(Boolean));
            }
            return [];
        }
    """)
    log(f"  {len(rows)} linhas na grid:")
    for r in rows:
        log(f"  {r}")
    return rows


async def main_consultas():
    """
    Modo focado: explora #!consultas a fundo.
    Inclui: Consultas de outros usuários, Categorias, e fallback via #!cubos.

    Uso: python diagnose_siafe.py --consultas
    Chrome deve estar aberto com --remote-debugging-port=9222 e logado no FlexVision.
    """
    FV_BASE = "https://siafe2-flexvision.fazenda.rj.gov.br/Flexvision/"
    log(f"SIAFE2 Diagnóstico (modo CONSULTAS v2) — {datetime.now():%d/%m/%Y %H:%M}")

    p, browser, page = await _cdp_connect()
    if not page:
        REPORT.write_text("\n".join(report_lines), encoding="utf-8")
        return

    log(f"✅ Aba: {page.url}")

    # ── 1. Navegar para #!consultas ───────────────────────────────────────────
    sep("1. Navegando para #!consultas")
    await page.goto(FV_BASE + "#!consultas", wait_until="networkidle", timeout=20000)
    await asyncio.sleep(4)
    await dump_page(page, "c01_consultas_inicial")
    full_text = await page.inner_text("body")
    log(f"  Texto completo ({len(full_text)} chars):\n{full_text[:3000]}")

    # ── 2. Listar todos os elementos visíveis ────────────────────────────────
    sep("2. Elementos visíveis iniciais")
    elements = await page.evaluate(_JS_LEAF_ELEMENTS)
    visible = [e for e in elements if e.get("visible")]
    for e in visible:
        log(f"  ✓ <{e['tag'].lower():6}> text={e['text']!r:60} cls={e['cls']!r}")

    await _dump_grid_rows(page, "grid inicial (provavelmente vazia)")

    # ── 3. Clicar em "Consultas de outros usuários" ───────────────────────────
    sep("3. Clicando em 'Consultas de outros usuários'")
    clicked_outros = await page.evaluate(_js_click_contains("Consultas de outros usuários"))
    if clicked_outros:
        log(f"  ✅ Clicado: {clicked_outros}")
        await asyncio.sleep(4)
        await dump_page(page, "c02_outros_usuarios")
        text_outros = await page.inner_text("body")
        log(f"  Texto ({len(text_outros)} chars):\n{text_outros[:4000]}")
        rows = await _dump_grid_rows(page, "Consultas de outros usuários")
        # Buscar OB nas linhas
        ob_rows = [r for r in rows if any("OB" in str(c) or "Execu" in str(c) for c in r)]
        if ob_rows:
            log("\n  ✅ Linhas com 'OB'/'Execu':")
            for r in ob_rows:
                log(f"    {r}")
        else:
            log("  (nenhuma linha com 'OB'/'Execu' encontrada)")
    else:
        log("  ❌ 'Consultas de outros usuários' não encontrado")

    # ── 4. Explorar categorias no painel esquerdo ────────────────────────────
    sep("4. Explorando painel 'Categorias'")
    cat_elements = await page.evaluate(_JS_LEAF_ELEMENTS)
    # Após clicar 'outros usuários', verificar novos itens visíveis
    for e in cat_elements:
        if e.get("visible") and "Categor" not in e["text"] and "Consultas" not in e["text"]:
            log(f"  ✓ {e['text']!r:60} cls={e['cls']!r}")

    # Tentar clicar em categoria "Execução" ou similares
    cat_keywords = ["Execução", "Financeiro", "Orçamentário", "Contábil", "OB", "Bancária"]
    for kw in cat_keywords:
        clicked_cat = await page.evaluate(_js_click_contains(kw))
        if clicked_cat:
            log(f"  ✅ Clicou categoria '{kw}': {clicked_cat}")
            await asyncio.sleep(3)
            await dump_page(page, f"c03_cat_{kw[:10].replace(' ','_')}")
            text_cat = await page.inner_text("body")
            log(f"  Texto:\n{text_cat[:3000]}")
            await _dump_grid_rows(page, f"Após clicar '{kw}'")
            break

    # ── 5. Tentar abrir "Execução por OB" na grid ────────────────────────────
    sep("5. Tentando abrir 'Execução por OB'")
    ob_variants = ["Execução por OB", "Execucao por OB", "Execução OB", "Documento - OB"]
    opened_ob = False
    for variant in ob_variants:
        # Single-click (seleção de linha)
        c1 = await page.evaluate(_js_click_contains(variant))
        if c1:
            log(f"  ✅ Single-click '{variant}': {c1}")
            await asyncio.sleep(2)
            # Double-click (abrir)
            c2 = await page.evaluate(_js_dblclick_contains(variant))
            if c2:
                log(f"  ✅ Double-click '{variant}': {c2}")
                await asyncio.sleep(3)
                await dump_page(page, "c04_ob_aberto")
                text_ob = await page.inner_text("body")
                log(f"  Texto após abrir OB:\n{text_ob[:4000]}")
                await _dump_inputs_consultas(page, "Formulário OB")
                # Capturar elementos visíveis
                els_ob = await page.evaluate(_JS_LEAF_ELEMENTS)
                log(f"\n  Elementos visíveis após abrir OB ({len(els_ob)}):")
                for e in els_ob:
                    if e.get("visible"):
                        log(f"    ✓ {e['text']!r:60} cls={e['cls']!r}")
                opened_ob = True
                break

    # ── 6. Fallback: navegar via #!cubos → Documento - OB ────────────────────
    sep("6. Fallback — Cubos → Documento - OB")
    await page.goto(FV_BASE + "#!cubos", wait_until="networkidle", timeout=20000)
    await asyncio.sleep(4)
    await dump_page(page, "c05_cubos")

    # Listar primeiros cubos visíveis
    cubos_text = await page.inner_text("body")
    log(f"  Texto Cubos ({len(cubos_text)} chars):\n{cubos_text[:3000]}")
    await _dump_grid_rows(page, "Lista de Cubos")

    # Buscar Documento OB
    ob_cubo_found = False
    for cubo_name in ["Documento - OB", "Execução de PD", "OB"]:
        c_click = await page.evaluate(_js_click_contains(cubo_name))
        if c_click:
            log(f"  ✅ Single-click '{cubo_name}': {c_click}")
            await asyncio.sleep(2)
            c_dbl = await page.evaluate(_js_dblclick_contains(cubo_name))
            if c_dbl:
                log(f"  ✅ Double-click '{cubo_name}': {c_dbl}")
                await asyncio.sleep(4)
                await dump_page(page, "c06_cubo_ob_aberto")
                text_cubo = await page.inner_text("body")
                log(f"  Texto após abrir cubo:\n{text_cubo[:4000]}")
                await _dump_inputs_consultas(page, "Formulário Cubo OB")
                els_cubo = await page.evaluate(_JS_LEAF_ELEMENTS)
                log(f"\n  Elementos visíveis ({len(els_cubo)}):")
                for e in els_cubo:
                    if e.get("visible"):
                        log(f"    ✓ {e['text']!r:60} cls={e['cls']!r}")
                ob_cubo_found = True
                break

    # ── 7. HTML completo ──────────────────────────────────────────────────────
    html = await page.content()
    html_path = SCREENSHOTS / "consultas_v2_dom.html"
    html_path.write_text(html, encoding="utf-8")
    log(f"\n  HTML completo: {html_path.name} ({len(html)} chars)")

    sep("DIAGNÓSTICO CONSULTAS v2 CONCLUÍDO")
    log(f"  Screenshots em: {SCREENSHOTS}/")
    log(f"  Relatório em:   {REPORT}")

    await p.stop()
    REPORT.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n✅ Relatório salvo em: {REPORT}")


async def _adf_wait(pg, timeout: int = 8000):
    """Wait for Oracle ADF partial-page refresh to settle."""
    try:
        await pg.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    await asyncio.sleep(1.5)


async def _js_click_adf(pg, css: str, text: str) -> str | None:
    """Click an ADF element by CSS selector + exact text via JS evaluate.

    Uses page.evaluate() so no ElementHandle is stored — avoids stale-handle
    errors that occur when ADF's PPR (Partial Page Refresh) replaces the DOM.
    Returns the element description if found, None otherwise.
    """
    safe = text.replace("'", "\\'")
    return await pg.evaluate(f"""
        () => {{
            for (const el of document.querySelectorAll('{css}')) {{
                if (el.textContent.trim() === '{safe}' && !el.className.includes('p_AFDisabled')) {{
                    el.dispatchEvent(new MouseEvent('mouseover', {{bubbles: true}}));
                    el.click();
                    return el.tagName + '|' + el.className.trim();
                }}
            }}
            return null;
        }}
    """)


# ── ADF grid / detail helpers ──────────────────────────────────────────────────

_JS_ADF_GRID_HEADERS = """
    () => {
        // ADF renders column headers in <th> or cells with header-like classes
        const sels = [
            'th', 'thead td',
            '.af_column_cell-text', '.af_column_sortable-text',
            '[class*="columnHeader"]', '[class*="Header"][class*="cell"]'
        ];
        for (const sel of sels) {
            const els = [...document.querySelectorAll(sel)];
            const texts = els.map(e => e.textContent.trim()).filter(t => t && t.length < 80);
            if (texts.length > 0) return {sel, texts};
        }
        return null;
    }
"""

_JS_ADF_GRID_ROWS = """
    (maxRows) => {
        // ADF table body rows — exclude header rows
        const rowSels = [
            'tr.af_table_row',
            'tr[class*="Row"]:not([class*="Header"])',
            'tbody tr',
        ];
        for (const sel of rowSels) {
            const rows = [...document.querySelectorAll(sel)].slice(0, maxRows);
            if (!rows.length) continue;
            const data = rows.map(row =>
                [...row.querySelectorAll('td')].map(td => td.textContent.trim()).filter(Boolean)
            ).filter(r => r.length > 0);
            if (data.length > 0) return {sel, rows: data};
        }
        return null;
    }
"""

_JS_ADF_INPUTS = """
    () => {
        const results = [];
        for (const el of document.querySelectorAll('input, select, textarea')) {
            const r = el.getBoundingClientRect();
            if (r.width <= 0) continue;
            // Find nearest label text
            let label = '';
            const id = el.id || '';
            if (id) {
                const lbl = document.querySelector(`label[for="${id}"]`);
                if (lbl) label = lbl.textContent.trim();
            }
            if (!label) {
                // Walk up DOM to find nearby label/span
                let p = el.parentElement;
                for (let i = 0; i < 5 && p; i++, p = p.parentElement) {
                    const lblEl = p.querySelector('label, span.af_outputLabel, span.x18m');
                    if (lblEl && lblEl !== el) { label = lblEl.textContent.trim(); break; }
                }
            }
            results.push({
                tag:   el.tagName,
                id:    el.id || '',
                name:  el.name || '',
                type:  el.type || '',
                cls:   el.className || '',
                ph:    el.placeholder || '',
                label: label.substring(0, 60),
            });
        }
        return results;
    }
"""

_JS_FIND_SEI = """
    () => {
        const result = {processo: null, links: []};

        // Strategy 1: look for input/span containing "Processo" label
        for (const el of document.querySelectorAll('*')) {
            const direct = [...el.childNodes]
                .filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('');
            if (!direct || direct.length > 60) continue;
            if (/[Pp]rocesso/.test(direct) || /SEI/i.test(direct)) {
                // Get sibling input or next value element
                const parent = el.parentElement;
                const val = parent
                    ? (parent.querySelector('input')?.value ||
                       parent.querySelector('span:not(:has(*))')?.textContent?.trim() || '')
                    : '';
                result.processo = {label: direct, value: val, cls: el.className};
            }
        }

        // Strategy 2: find SEI hyperlinks
        for (const a of document.querySelectorAll('a[href]')) {
            const href = a.href;
            if (/sei/i.test(href) || a.textContent.includes('Processo')) {
                result.links.push({text: a.textContent.trim().substring(0,80), href});
            }
        }

        return result;
    }
"""


async def _adf_try_open_detail(pg) -> dict:
    """
    Select first visible grid row and try to open its detail screen.
    Handles both same-page navigation and popup windows.
    Returns {opened, method, popup_page}.
    """
    # Click first body row
    clicked_row = await pg.evaluate("""
        () => {
            const sels = [
                'tr.af_table_row', 'tr[class*="Row"]:not([class*="Header"])', 'tbody tr'
            ];
            for (const sel of sels) {
                const row = document.querySelector(sel);
                if (row && row.getBoundingClientRect().height > 0) {
                    row.click();
                    return row.textContent.trim().substring(0, 100);
                }
            }
            return null;
        }
    """)
    if not clicked_row:
        return {"opened": False, "reason": "no rows found"}

    await asyncio.sleep(1)

    # Try pressing Enter
    url_before = pg.url
    body_before_len = len(await pg.inner_text("body"))
    await pg.keyboard.press("Enter")
    await asyncio.sleep(3)
    try:
        await pg.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass

    body_after = await pg.inner_text("body")
    if len(body_after) != body_before_len or pg.url != url_before:
        return {"opened": True, "method": "Enter", "popup_page": None,
                "row_info": clicked_row}

    # Try double-click on first row
    double_clicked = await pg.evaluate("""
        () => {
            const sels = ['tr.af_table_row', 'tr[class*="Row"]:not([class*="Header"])', 'tbody tr'];
            for (const sel of sels) {
                const row = document.querySelector(sel);
                if (row && row.getBoundingClientRect().height > 0) {
                    row.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
                    return sel;
                }
            }
            return null;
        }
    """)
    await asyncio.sleep(3)
    try:
        await pg.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass

    body_after2 = await pg.inner_text("body")
    if len(body_after2) != body_before_len:
        return {"opened": True, "method": "dblclick", "popup_page": None,
                "row_info": clicked_row}

    return {"opened": False, "reason": "neither Enter nor dblclick changed page",
            "row_info": clicked_row}


async def _explore_adf_screen(pg, label: str, screenshot_prefix: str):
    """
    Full exploration of an ADF screen: inputs, grid headers, sample rows,
    detail window, and SEI process capture.
    """
    safe_prefix = screenshot_prefix.replace(" ", "_")[:30]

    sep(f"  Tela: {label}")
    await dump_page(pg, safe_prefix)

    body_txt = await pg.inner_text("body")
    log(f"  Texto ({len(body_txt)} chars): {body_txt[:600]}")

    # ── Inputs / filtros ──────────────────────────────────────────────────────
    sep(f"  Inputs: {label}")
    inputs = await pg.evaluate(_JS_ADF_INPUTS)
    log(f"  {len(inputs)} inputs:")
    for inp in inputs:
        log(f"    [{inp['tag']}] id={inp['id']!r:35} name={inp['name']!r:25} "
            f"type={inp['type']!r:10} label={inp['label']!r:40} ph={inp['ph']!r}")

    # ── Grid column headers ───────────────────────────────────────────────────
    headers = await pg.evaluate(_JS_ADF_GRID_HEADERS)
    if headers:
        log(f"  Colunas (via {headers['sel']}): {headers['texts']}")
    else:
        log("  Colunas: (nenhuma grid encontrada)")

    # ── Tentar executar busca para obter linhas ───────────────────────────────
    sep(f"  Executando busca padrão: {label}")
    search_clicked = await pg.evaluate("""
        () => {
            const kws = ['consultar', 'pesquisar', 'buscar', 'executar', 'filtrar', 'listar'];
            const btns = [...document.querySelectorAll('button, a.x7j, a.xg2, input[type="button"], input[type="submit"]')];
            for (const btn of btns) {
                const t = (btn.textContent || btn.value || '').trim().toLowerCase();
                if (kws.some(k => t.includes(k)) && btn.getBoundingClientRect().width > 0) {
                    btn.click();
                    return t;
                }
            }
            return null;
        }
    """)
    if search_clicked:
        log(f"  ✅ Busca executada: {search_clicked!r}")
        await _adf_wait(pg, 12000)
        await dump_page(pg, f"{safe_prefix}_resultados")
    else:
        log("  (nenhum botão de busca encontrado — tela pode não ter filtros)")

    # ── Sample rows ───────────────────────────────────────────────────────────
    rows_data = await pg.evaluate(_JS_ADF_GRID_ROWS, 3)
    if rows_data:
        log(f"  Primeiras linhas ({rows_data['sel']}):")
        for r in rows_data["rows"]:
            log(f"    {r}")

        # ── Tentar abrir detalhe da primeira linha ────────────────────────────
        sep(f"  Detalhe linha 1: {label}")
        detail = await _adf_try_open_detail(pg)
        log(f"  Resultado: {detail}")

        if detail.get("opened"):
            await _adf_wait(pg, 10000)
            await dump_page(pg, f"{safe_prefix}_detalhe")

            # Procurar Processo/SEI
            sei = await pg.evaluate(_JS_FIND_SEI)
            log(f"  SEI/Processo: {sei}")
            if sei.get("processo"):
                log(f"  ⭐ PROCESSO SEI: {sei['processo']}")
            if sei.get("links"):
                log(f"  ⭐ LINKS SEI: {sei['links']}")

            # Todos os elementos visíveis no detalhe
            sep(f"  Elementos do detalhe: {label}")
            det_els = await pg.evaluate(_JS_LEAF_ELEMENTS)
            for e in det_els:
                if e.get("visible"):
                    log(f"    ✓ <{e['tag'].lower():6}> {e['text']!r:60} cls={e['cls'][:50]!r}")

            # HTML do detalhe
            det_html = await pg.content()
            p = SCREENSHOTS / f"{safe_prefix}_detalhe_dom.html"
            p.write_text(det_html, encoding="utf-8")
            log(f"  HTML detalhe: {p.name} ({len(det_html)} chars)")

            # Tentar voltar (botão Cancelar, Fechar, ou browser back)
            closed = await pg.evaluate("""
                () => {
                    const kws = ['cancelar', 'fechar', 'voltar', 'close', 'back'];
                    for (const btn of document.querySelectorAll('button, a.x7j, a.xg2')) {
                        const t = (btn.textContent || '').trim().toLowerCase();
                        if (kws.some(k => t.includes(k))) { btn.click(); return t; }
                    }
                    return null;
                }
            """)
            if not closed:
                await pg.go_back()
            await _adf_wait(pg, 6000)
    else:
        log("  (nenhuma linha de dados encontrada após busca)")

    # HTML completo da tela
    html = await pg.content()
    hp = SCREENSHOTS / f"{safe_prefix}_dom.html"
    hp.write_text(html, encoding="utf-8")
    log(f"  HTML tela: {hp.name} ({len(html)} chars)")


async def _js_read_items(pg, css: str) -> list[dict]:
    """Read all items matching a CSS selector via JS evaluate (fresh DOM context)."""
    return await pg.evaluate(f"""
        () => [...document.querySelectorAll('{css}')].map(e => ({{
            tag:      e.tagName,
            text:     e.textContent.trim(),
            cls:      e.className.trim(),
            disabled: e.className.includes('p_AFDisabled'),
            visible:  e.getBoundingClientRect().width > 0
        }})).filter(e => e.text && e.text.length < 120)
    """)


async def _get_siafe2_page(browser, fallback_page):
    """Return the SIAFE2 (non-FlexVision) page from an open browser."""
    for ctx in browser.contexts:
        for pg in ctx.pages:
            url = pg.url.lower()
            if "siafe2.fazenda" in url and "flexvision" not in url:
                return pg
    return fallback_page


async def main_siafe2():
    """
    Diagnóstico completo da seção Execução do SIAFE2.

    Uso: python diagnose_siafe.py --siafe2
    Chrome deve estar aberto com --remote-debugging-port=9222 e logado no SIAFE2.

    O que faz:
      1. Mapeia todos os menus principais via JS (sem ElementHandle stale)
      2. Para cada submenu de Execução:
         - Clica, mapeia painel esquerdo, screenshot, HTML
      3. Para cada item do painel esquerdo de Execução Financeira:
         - Mapeia inputs/filtros com IDs/nomes
         - Executa busca padrão
         - Captura colunas da grid
         - Abre detalhe da primeira linha (Enter + dblclick)
         - Procura campo Processo/SEI e links SEI
      4. Deep-dive especial na tela OB:
         - Busca com filtro de data (mês corrente) para obter resultados reais
         - Abre detalhe da primeira OB
         - Captura número do Processo SEI e URL do sistema SEI
         - Mapeia todos os campos do formulário de detalhe
    """
    log(f"SIAFE2 Diagnóstico completo — {datetime.now():%d/%m/%Y %H:%M}")
    log("(isso pode levar vários minutos — explorando toda a seção Execução)")

    p, browser, page = await _cdp_connect()
    if not page:
        REPORT.write_text("\n".join(report_lines), encoding="utf-8")
        return

    pg = await _get_siafe2_page(browser, page)
    log(f"✅ Aba: {pg.url}")

    # ── 1. Snapshot + verificação de login ───────────────────────────────────
    sep("1. Snapshot inicial")
    await dump_page(pg, "s01_inicial")
    if "login" in pg.url.lower():
        log("⚠️  Ainda na página de login. Faça login e execute de novo.")
        await p.stop()
        REPORT.write_text("\n".join(report_lines), encoding="utf-8")
        return

    # ── 2. Mapa completo dos menus via JS ─────────────────────────────────────
    sep("2. Mapa completo: todos os menus e submenus")
    top_items = await _js_read_items(pg, "a.xyo")
    top_names_set = {it["text"] for it in top_items}
    log(f"  {len(top_items)} menus principais:")
    for it in top_items:
        mark = "[D]" if it["disabled"] else "   "
        log(f"  {mark} {it['text']!r}")

    menu_map: dict[str, list[dict]] = {}
    for it in top_items:
        if it["disabled"]:
            continue
        name = it["text"]
        clicked = await _js_click_adf(pg, "a.xyo", name)
        if not clicked:
            log(f"  ⚠️  '{name}' não clicável")
            continue
        await _adf_wait(pg, 6000)

        subs = await _js_read_items(pg, "a.xgh")
        subs = [s for s in subs if s["text"] not in top_names_set and s["text"]]

        # Also capture 3rd-level .xgg items (may already be rendered in DOM)
        sub3 = await _js_read_items(pg, "a.xgg")
        sub3 = [s for s in sub3 if s["text"] and s["text"] not in top_names_set]

        menu_map[name] = subs

        log(f"\n  ── {name!r} ──")
        for s in subs:
            mark = "[D]" if s["disabled"] else "   "
            ob_flag = " ⭐" if any(k in s["text"].upper()
                                   for k in ("OB", "ORDEM BANC")) else ""
            log(f"    {mark} {s['text']!r:40} (xgh){ob_flag}")
        if sub3:
            log(f"    3rd level (.xgg): {len(sub3)} itens")
            for s in sub3:
                mark = "[D]" if s["disabled"] else "   "
                ob_flag = " ⭐" if any(k in s["text"].upper()
                                       for k in ("OB", "ORDEM BANC", "PROG", "PD")) else ""
                log(f"      {mark} {s['text']!r}{ob_flag}")

        await pg.keyboard.press("Escape")
        await asyncio.sleep(0.6)

    # ── 3. Mapear submenus de Execução via a.xgh (sem navegar para FlexVision) ─
    sep("3. Submenus de Execução (leitura via JS — sem navegar)")
    # NOTE: a.xyo "Execução" opens FlexVision instead of staying in SIAFE2.
    # We read the already-rendered a.xgh items directly from the DOM without
    # clicking the top bar again.
    exec_subs = await _js_read_items(pg, "a.xgh")
    exec_subs = [s for s in exec_subs if s["text"] not in top_names_set and s["text"]]
    log(f"  {len(exec_subs)} submenus de Execução (a.xgh):")
    for s in exec_subs:
        mark = "[D]" if s["disabled"] else "   "
        log(f"    {mark} {s['text']!r}")

    # Also dump all a.xgg items (always in DOM)
    sep("3b. Todos os itens a.xgg (3rd level — sempre no DOM)")
    xgg_items = await _js_read_items(pg, "a.xgg")
    log(f"  {len(xgg_items)} itens a.xgg:")
    for it in xgg_items:
        mark = "[D]" if it["disabled"] else "   "
        ob_flag = " ⭐" if any(k in it["text"].upper()
                               for k in ("OB", "ORDEM BANC", "PD", "PROG")) else ""
        log(f"    {mark} {it['text']!r:50}{ob_flag}")

    await dump_page(pg, "s02_execucao_state")

    # ── 4. Explorar Execução Financeira via a.xgh ─────────────────────────────
    sep("4. Navegando para Execução Financeira via a.xgh")
    r_fin = await _js_click_adf(pg, "a.xgh", "Execução Financeira")
    if not r_fin:
        r_fin = await pg.evaluate("""
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
    log(f"  Clicou Execução Financeira: {r_fin}")
    await _adf_wait(pg, 8000)
    await dump_page(pg, "s03_exec_financeira")

    left_fin = await _js_read_items(pg, "a.xg8")
    log(f"  Painel esquerdo Exec Financeira ({len(left_fin)} itens):")
    for li in left_fin:
        ob = " ⭐OB" if "OB" in li["text"].upper() else ""
        log(f"    {'✓' if li['visible'] else '·'} {li['text']!r:45} cls={li['cls']!r}{ob}")

    html_fin = await pg.content()
    hp_fin = SCREENSHOTS / "s03_exec_financeira_dom.html"
    hp_fin.write_text(html_fin, encoding="utf-8")
    log(f"  HTML: {hp_fin.name} ({len(html_fin)} chars)")

    # Explore left panel items of Execução Financeira
    panel_item_names = [li["text"] for li in left_fin
                        if li.get("visible") and not li.get("disabled")]
    log(f"\n  Explorando {len(panel_item_names)} itens do painel:")
    for panel_item in panel_item_names:
        pi_safe = panel_item[:18].replace(" ", "_").lower()
        log(f"\n  ── Painel item: {panel_item!r} ──")
        pi_safe_js = panel_item.replace("'", "\\'")
        clicked_pi = await pg.evaluate(f"""
            () => {{
                for (const sel of ['a.xg8', 'a[class*="xg"]', 'a']) {{
                    for (const el of document.querySelectorAll(sel)) {{
                        const direct = [...el.childNodes]
                            .filter(n => n.nodeType === 3)
                            .map(n => n.textContent.trim()).filter(Boolean).join('');
                        if (direct === '{pi_safe_js}' && el.getBoundingClientRect().width > 0) {{
                            el.click();
                            return el.tagName + '|' + el.className;
                        }}
                    }}
                }}
                return null;
            }}
        """)
        if not clicked_pi:
            log(f"  ❌ '{panel_item}' não clicável")
            continue
        await _adf_wait(pg, 10000)
        await _explore_adf_screen(pg, panel_item, f"s04_fin_{pi_safe}")

    # ── 5. Deep-dive especial: OB Orçamentária via a.xgg ─────────────────────
    sep("5. Deep-dive: OB Orçamentária (navegando direto via a.xgg)")

    # Navigate directly via a.xgg — ALWAYS in DOM, no need for menu hierarchy
    r_ob = await pg.evaluate("""
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
    log(f"  Clicou OB: {r_ob}")
    if not r_ob:
        log("  ❌ 'OB' não encontrado — dump diagnóstico:")
        vis = await pg.evaluate(_JS_LEAF_ELEMENTS)
        for e in vis:
            if e.get("visible"):
                log(f"    ✓ <{e['tag'].lower():6}> {e['text']!r:60} cls={e['cls']!r}")
    else:
        await _adf_wait(pg, 10000)
        await dump_page(pg, "s05_ob_tela")

        # ── 5a. Mapear todos os inputs da tela OB ────────────────────────────
        sep("5a. OB — inputs/filtros (IDs e nomes para automação)")
        ob_inputs = await pg.evaluate(_JS_ADF_INPUTS)
        log(f"  {len(ob_inputs)} inputs:")
        for inp in ob_inputs:
            log(f"    [{inp['tag']}] id={inp['id']!r:40} name={inp['name']!r:30} "
                f"type={inp['type']!r:10} label={inp['label']!r:40} ph={inp['ph']!r}")

        # ── 5b. Colunas da grid ───────────────────────────────────────────────
        sep("5b. OB — colunas da grid")
        ob_headers = await pg.evaluate(_JS_ADF_GRID_HEADERS)
        if ob_headers:
            log(f"  Colunas ({ob_headers['sel']}): {ob_headers['texts']}")
        else:
            log("  (colunas não encontradas — grid pode estar vazia)")

        # ── 5c. Executar busca com data do mês corrente ───────────────────────
        sep("5c. OB — executando busca (data atual como filtro mínimo)")
        hoje = datetime.now()
        mes_ini = f"01/{hoje.month:02d}/{hoje.year}"
        mes_fim = f"{hoje.day:02d}/{hoje.month:02d}/{hoje.year}"
        log(f"  Tentando preencher período: {mes_ini} a {mes_fim}")

        # Try to fill date fields by label proximity
        date_filled = await pg.evaluate(f"""
            () => {{
                const filled = [];
                const inputs = [...document.querySelectorAll('input[type="text"], input:not([type])')];
                for (const inp of inputs) {{
                    if (inp.getBoundingClientRect().width <= 0) continue;
                    // Look for date-like context
                    let parent = inp.parentElement;
                    let label = '';
                    for (let i = 0; i < 6 && parent; i++, parent = parent.parentElement) {{
                        const lbl = parent.querySelector('label, span.af_outputLabel, span.x18m');
                        if (lbl && lbl !== inp) {{ label = lbl.textContent.trim().toLowerCase(); break; }}
                    }}
                    if (label.includes('in') || label.includes('de') || label.includes('início')) {{
                        inp.value = '{mes_ini}';
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        filled.push('inicio:' + label);
                    }} else if (label.includes('fim') || label.includes('até') || label.includes('final')) {{
                        inp.value = '{mes_fim}';
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        filled.push('fim:' + label);
                    }}
                }}
                return filled;
            }}
        """)
        log(f"  Campos preenchidos: {date_filled}")
        await asyncio.sleep(1)

        # Click Consultar
        search_btn = await pg.evaluate("""
            () => {
                const kws = ['consultar', 'pesquisar', 'buscar', 'filtrar', 'executar', 'listar'];
                for (const btn of document.querySelectorAll('button, a.x7j, a.xg2, input[type="button"], input[type="submit"]')) {
                    const t = (btn.textContent || btn.value || '').trim().toLowerCase();
                    if (kws.some(k => t.includes(k)) && btn.getBoundingClientRect().width > 0) {
                        btn.click();
                        return t;
                    }
                }
                return null;
            }
        """)
        log(f"  Botão busca: {search_btn!r}")
        if search_btn:
            await _adf_wait(pg, 15000)
            await dump_page(pg, "s05_ob_resultados")

            # Re-read headers after results load
            ob_headers2 = await pg.evaluate(_JS_ADF_GRID_HEADERS)
            if ob_headers2:
                log(f"  Colunas após busca: {ob_headers2['texts']}")

            rows_data = await pg.evaluate(_JS_ADF_GRID_ROWS, 5)
            if rows_data:
                log(f"  Primeiras {len(rows_data['rows'])} linhas ({rows_data['sel']}):")
                for r in rows_data["rows"]:
                    log(f"    {r}")

                # ── 5d. Abrir detalhe da primeira OB ─────────────────────────
                sep("5d. OB — abrindo detalhe (Enter / dblclick)")

                # Watch for popup window
                async def _try_open_with_popup():
                    try:
                        popup_task = asyncio.ensure_future(
                            pg.context.wait_for_event("page", timeout=8000)
                        )
                        detail_result = await _adf_try_open_detail(pg)
                        try:
                            popup_pg = await asyncio.wait_for(popup_task, timeout=8000)
                            await _adf_wait(popup_pg, 10000)
                            return detail_result, popup_pg
                        except asyncio.TimeoutError:
                            popup_task.cancel()
                            return detail_result, None
                    except Exception as ex:
                        log(f"  [popup watch error: {ex}]")
                        return {"opened": False}, None

                detail, popup_pg = await _try_open_with_popup()
                log(f"  Detalhe: {detail}")

                target_pg = popup_pg if popup_pg else pg

                if detail.get("opened") or popup_pg:
                    if popup_pg:
                        log(f"  ✅ Popup aberto: {popup_pg.url}")
                    await dump_page(target_pg, "s05_ob_detalhe")

                    # ── 5e. Campos do detalhe ─────────────────────────────────
                    sep("5e. OB detalhe — todos os campos/inputs")
                    det_inputs = await target_pg.evaluate(_JS_ADF_INPUTS)
                    log(f"  {len(det_inputs)} inputs:")
                    for inp in det_inputs:
                        log(f"    [{inp['tag']}] id={inp['id']!r:40} name={inp['name']!r:30} "
                            f"label={inp['label']!r:45} ph={inp['ph']!r}")

                    sep("5f. OB detalhe — elementos visíveis")
                    det_vis = await target_pg.evaluate(_JS_LEAF_ELEMENTS)
                    for e in det_vis:
                        if e.get("visible"):
                            log(f"    ✓ <{e['tag'].lower():6}> {e['text']!r:60} cls={e['cls'][:50]!r}")

                    sep("5g. OB detalhe — texto completo")
                    det_body = await target_pg.inner_text("body")
                    log(f"  Texto ({len(det_body)} chars):\n{det_body[:6000]}")

                    # ── 5h. Procurar Processo / SEI ───────────────────────────
                    sep("5h. OB detalhe — campo Processo (SEI)")
                    sei_info = await target_pg.evaluate(_JS_FIND_SEI)
                    if sei_info.get("processo"):
                        log(f"  ⭐ PROCESSO SEI: {sei_info['processo']}")
                    else:
                        log("  (campo Processo não encontrado por label)")
                    if sei_info.get("links"):
                        log(f"  ⭐ LINKS SEI: {sei_info['links']}")
                    else:
                        # Search body text for SEI-like patterns
                        patterns = await target_pg.evaluate("""
                            () => {
                                const text = document.body.innerText;
                                const matches = [];
                                // SEI process numbers: NNNNNNNN-N.NNNN.NNNNNNN/NNNN-NN or similar
                                const re1 = /\\d{7,}-\\d\\.\\d{4}\\.\\d{7}\\/\\d{4}-\\d{2}/g;
                                const re2 = /E-\\d{2}\\/\\d+\\/\\d{4}/g;      // E-xx/NNNNN/AAAA style
                                const re3 = /SEI[\\s-]*\\d[\\d./\\-]+/gi;
                                for (const re of [re1, re2, re3]) {
                                    const m = text.match(re);
                                    if (m) matches.push(...m.slice(0,5));
                                }
                                return [...new Set(matches)];
                            }
                        """)
                        if patterns:
                            log(f"  ⭐ Padrões SEI no texto: {patterns}")
                        else:
                            log("  (nenhum padrão SEI encontrado no corpo da página)")

                    # HTML do detalhe
                    det_html = await target_pg.content()
                    dhp = SCREENSHOTS / "s05_ob_detalhe_dom.html"
                    dhp.write_text(det_html, encoding="utf-8")
                    log(f"  HTML: {dhp.name} ({len(det_html)} chars)")

                    # Close popup if opened
                    if popup_pg:
                        try:
                            await popup_pg.close()
                        except PWError:
                            pass
                else:
                    log("  ❌ Detalhe não abriu — listando visíveis:")
                    vis3 = await pg.evaluate(_JS_LEAF_ELEMENTS)
                    for e in vis3:
                        if e.get("visible"):
                            log(f"    ✓ {e['text']!r:60} cls={e['cls']!r}")
            else:
                log("  (sem linhas de resultado após busca)")
                vis4 = await pg.evaluate(_JS_LEAF_ELEMENTS)
                for e in vis4:
                    if e.get("visible"):
                        log(f"    ✓ {e['text']!r:60} cls={e['cls']!r}")

    # ── 6. HTML + relatório final ─────────────────────────────────────────────
    try:
        html_final = await pg.content()
        fp = SCREENSHOTS / "siafe2_final_dom.html"
        fp.write_text(html_final, encoding="utf-8")
        log(f"\n  HTML estado final: {fp.name} ({len(html_final)} chars)")
    except Exception:
        pass

    sep("DIAGNÓSTICO SIAFE2 CONCLUÍDO")
    log(f"  Screenshots em: {SCREENSHOTS}/")
    log(f"  Relatório em:   {REPORT}")

    await p.stop()
    REPORT.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n✅ Relatório salvo em: {REPORT}")


async def _ob_deep_dive(page) -> None:
    """
    Core OB Orçamentária exploration: snapshot → filters → search → results →
    detail → all tabs.  Page must already be on the OB screen.
    Called from both main() (fresh browser) and main_ob() (CDP).
    """
    pg = page

    sep("OB: Estado inicial da tela")
    await dump_page(pg, "ob_01_inicial")
    body_ini = await pg.inner_text("body")
    log(f"  Texto ({len(body_ini)} chars):\n{body_ini[:3000]}")

    tabs_check = await pg.evaluate("""
        () => {
            const all = [...document.querySelectorAll('a.xyp')];
            const vis = all.filter(el => el.getBoundingClientRect().width > 0);
            return {
                total: all.length,
                visible: vis.length,
                names: vis.map(el => el.textContent.trim()).filter(Boolean),
            };
        }
    """)
    log(f"  Abas a.xyp: {tabs_check}")
    on_detail = tabs_check.get("visible", 0) > 0

    sep("OB: Inputs/filtros (IDs para automação)")
    ob_inputs = await pg.evaluate(_JS_ADF_INPUTS)
    log(f"  {len(ob_inputs)} inputs/selects:")
    for inp in ob_inputs:
        log(f"    [{inp['tag']}] id={inp['id']!r:50} name={inp['name']!r:35} "
            f"type={inp['type']!r:10} label={inp['label']!r:50}")

    sep("OB: Links e botões visíveis")
    lnk_btns = await pg.evaluate("""
        () => [...document.querySelectorAll('a, button, input[type="button"], input[type="submit"]')]
            .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
            .map(el => ({tag: el.tagName, text: (el.textContent || el.value || '').trim().substring(0,70), cls: el.className || ''}))
            .filter(el => el.text)
    """)
    for lb in lnk_btns:
        log(f"  [{lb['tag']:6}] {lb['text']!r:50} cls={lb['cls'][:45]!r}")

    sep("OB: Elementos visíveis (leaf nodes)")
    vis_ini = await pg.evaluate(_JS_LEAF_ELEMENTS)
    for e in vis_ini:
        if e.get("visible"):
            log(f"  ✓ <{e['tag'].lower():6}> {e['text']!r:65} cls={e['cls'][:45]!r}")

    html_ini = await pg.content()
    hip = SCREENSHOTS / "ob_01_ini_dom.html"
    hip.write_text(html_ini, encoding="utf-8")
    log(f"  HTML inicial: {hip.name} ({len(html_ini)} chars)")

    if not on_detail:
        sep("OB: Executando busca para obter registros")
        hoje = datetime.now()
        mes_ini = f"01/{hoje.month:02d}/{hoje.year}"
        mes_fim = f"{hoje.day:02d}/{hoje.month:02d}/{hoje.year}"
        log(f"  Período: {mes_ini} → {mes_fim}")

        date_filled = await pg.evaluate(f"""
            () => {{
                const filled = [];
                for (const inp of document.querySelectorAll('input[type="text"], input:not([type])')) {{
                    if (inp.getBoundingClientRect().width <= 0) continue;
                    let lbl = ''; let par = inp.parentElement;
                    for (let i = 0; i < 6 && par; i++, par = par.parentElement) {{
                        const l = par.querySelector('label, span.x18m, span.af_outputLabel');
                        if (l && l !== inp) {{ lbl = l.textContent.trim().toLowerCase(); break; }}
                    }}
                    const ini = lbl.includes('iní') || lbl.includes(' de') || lbl.match(/^de$/);
                    const fim = lbl.includes('fim') || lbl.includes('até') || lbl.includes('final');
                    if (ini) {{
                        inp.value = '{mes_ini}';
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('blur', {{bubbles: true}}));
                        filled.push('ini:' + lbl);
                    }} else if (fim) {{
                        inp.value = '{mes_fim}';
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('blur', {{bubbles: true}}));
                        filled.push('fim:' + lbl);
                    }}
                }}
                return filled;
            }}
        """)
        log(f"  Campos de data: {date_filled}")
        await asyncio.sleep(0.8)

        consultar = await pg.evaluate("""
            () => {
                const kws = ['consultar', 'pesquisar', 'buscar', 'filtrar', 'listar', 'executar'];
                for (const el of document.querySelectorAll(
                        'a, button, input[type="button"], input[type="submit"]')) {
                    const t = (el.textContent || el.value || '').trim().toLowerCase();
                    if (kws.some(k => t === k || t.startsWith(k))
                        && el.getBoundingClientRect().width > 0
                        && !el.className.includes('p_AFDisabled')) {
                        el.click(); return t;
                    }
                }
                return null;
            }
        """)
        log(f"  Botão Consultar: {consultar!r}")
        if consultar:
            await _adf_wait(pg, 18000)
            await dump_page(pg, "ob_02_resultados")

        sep("OB: Grid de resultados — colunas e primeiras linhas")
        ob_headers = await pg.evaluate(_JS_ADF_GRID_HEADERS)
        if ob_headers:
            log(f"  Colunas ({ob_headers['sel']}): {ob_headers['texts']}")
        else:
            log("  (colunas não detectadas — grid pode estar vazia)")

        rows_data = await pg.evaluate(_JS_ADF_GRID_ROWS, 5)
        if rows_data:
            log(f"  Primeiras {len(rows_data['rows'])} linhas ({rows_data['sel']}):")
            for r in rows_data["rows"]:
                log(f"    {r}")
        else:
            log("  Sem linhas — verificando texto da página:")
            page_text = await pg.inner_text("body")
            log(f"  Texto ({len(page_text)} chars): {page_text[:1500]}")

        sep("OB: Abrindo detalhe da primeira OB")
        row_info = await pg.evaluate("""
            () => {
                const sels = [
                    'tr.af_table_row',
                    'tr[class*="Row"]:not([class*="Header"]):not([class*="header"])',
                    'tbody tr'
                ];
                for (const sel of sels) {
                    for (const row of document.querySelectorAll(sel)) {
                        const r = row.getBoundingClientRect();
                        if (r.height > 5 && row.textContent.trim().length > 2) {
                            row.click();
                            return {text: row.textContent.trim().substring(0, 150), sel};
                        }
                    }
                }
                return null;
            }
        """)
        log(f"  Linha clicada: {row_info}")

        if row_info:
            await asyncio.sleep(1.5)
            await pg.keyboard.press("Enter")
            await _adf_wait(pg, 10000)
            tabs_after = await pg.evaluate("""
                () => [...document.querySelectorAll('a.xyp')]
                    .filter(el => el.getBoundingClientRect().width > 0)
                    .map(el => el.textContent.trim()).filter(Boolean)
            """)
            if tabs_after:
                log(f"  ✅ Detalhe via Enter — abas: {tabs_after}")
                on_detail = True

            if not on_detail:
                viz = await pg.evaluate("""
                    () => {
                        for (const el of document.querySelectorAll('a.xg8, a[class*="xg"]')) {
                            if (el.textContent.trim().includes('Visualizar')
                                && !el.className.includes('p_AFDisabled')) {
                                el.click(); return el.textContent.trim();
                            }
                        }
                        return null;
                    }
                """)
                log(f"  Visualizar: {viz!r}")
                if viz:
                    await _adf_wait(pg, 10000)
                    tabs2 = await pg.evaluate("""
                        () => [...document.querySelectorAll('a.xyp')]
                            .filter(el => el.getBoundingClientRect().width > 0)
                            .map(el => el.textContent.trim()).filter(Boolean)
                    """)
                    if tabs2:
                        log(f"  ✅ Detalhe via Visualizar — abas: {tabs2}")
                        on_detail = True

            if not on_detail:
                dbl = await pg.evaluate("""
                    () => {
                        const sels = ['tr.af_table_row',
                                      'tr[class*="Row"]:not([class*="Header"])', 'tbody tr'];
                        for (const sel of sels) {
                            const row = document.querySelector(sel);
                            if (row && row.getBoundingClientRect().height > 0) {
                                row.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
                                return sel;
                            }
                        }
                        return null;
                    }
                """)
                log(f"  Dblclick: {dbl!r}")
                await _adf_wait(pg, 10000)
                tabs3 = await pg.evaluate("""
                    () => [...document.querySelectorAll('a.xyp')]
                        .filter(el => el.getBoundingClientRect().width > 0)
                        .map(el => el.textContent.trim()).filter(Boolean)
                """)
                if tabs3:
                    log(f"  ✅ Detalhe via dblclick — abas: {tabs3}")
                    on_detail = True

        if not on_detail:
            log("  ⚠️  Não conseguiu abrir detalhe — dump do estado atual:")
            vis_fail = await pg.evaluate(_JS_LEAF_ELEMENTS)
            for e in vis_fail:
                if e.get("visible"):
                    log(f"    ✓ <{e['tag'].lower():6}> {e['text']!r:65} cls={e['cls']!r}")

    if on_detail:
        sep("OB: Tela de detalhe — aba Detalhamento")
        await dump_page(pg, "ob_03_detalhe")
        body_det = await pg.inner_text("body")
        log(f"  Texto ({len(body_det)} chars):\n{body_det[:4000]}")

        sep("OB: Inputs do detalhe")
        det_inputs = await pg.evaluate(_JS_ADF_INPUTS)
        log(f"  {len(det_inputs)} inputs/selects:")
        for inp in det_inputs:
            log(f"    [{inp['tag']}] id={inp['id']!r:50} name={inp['name']!r:35} "
                f"label={inp['label']!r:50}")

        sep("OB: Elementos visíveis no detalhe")
        det_vis = await pg.evaluate(_JS_LEAF_ELEMENTS)
        for e in det_vis:
            if e.get("visible"):
                log(f"  ✓ <{e['tag'].lower():6}> {e['text']!r:65} cls={e['cls'][:45]!r}")

        det_html = await pg.content()
        dhp = SCREENSHOTS / "ob_03_detalhe_dom.html"
        dhp.write_text(det_html, encoding="utf-8")
        log(f"  HTML detalhe: {dhp.name} ({len(det_html)} chars)")

        sep("OB: Abas disponíveis (a.xyp)")
        all_tabs = await pg.evaluate("""
            () => [...document.querySelectorAll('a.xyp')].map(el => ({
                text:     el.textContent.trim(),
                cls:      el.className,
                disabled: el.className.includes('p_AFDisabled'),
                selected: el.className.includes('p_AFSelected'),
                visible:  el.getBoundingClientRect().width > 0
            })).filter(t => t.text)
        """)
        log(f"  {len(all_tabs)} abas:")
        for t in all_tabs:
            marks = []
            if t["disabled"]: marks.append("DESABILITADA")
            if t["selected"]: marks.append("SELECIONADA")
            if not t["visible"]: marks.append("oculta")
            log(f"    {'[D]' if t['disabled'] else '   '} {t['text']!r:35} {marks}")

        sep("OB: Explorando cada aba")
        for tab_info in all_tabs:
            tab_name = tab_info["text"]
            tab_safe = tab_name[:20].replace(" ", "_").replace("/", "_").lower()
            is_dis   = tab_info["disabled"]
            is_sel   = tab_info["selected"]

            sep(f"  ABA: {tab_name!r}{'  [DESABILITADA]' if is_dis else ''}")
            if is_dis:
                log("  ⏭️  Aba desabilitada — pulando")
                continue

            if not is_sel:
                tab_js = tab_name.replace("'", "\\'")
                r_tab = await pg.evaluate(f"""
                    () => {{
                        for (const el of document.querySelectorAll('a.xyp')) {{
                            const t = el.textContent.trim();
                            if ((t === '{tab_js}' || t.includes('{tab_js[:10]}'))
                                && !el.className.includes('p_AFDisabled')) {{
                                el.click(); return t;
                            }}
                        }}
                        return null;
                    }}
                """)
                log(f"  Clicou aba: {r_tab!r}")
                await _adf_wait(pg, 10000)
            else:
                log("  (aba já selecionada — capturando)")

            await pg.screenshot(path=str(SCREENSHOTS / f"ob_aba_{tab_safe}.png"), full_page=True)
            log(f"  📸 ob_aba_{tab_safe}.png")

            tab_body = await pg.inner_text("body")
            log(f"\n  Texto completo da aba ({len(tab_body)} chars):")
            log(tab_body[:5000])

            sep(f"  Elementos visíveis — {tab_name}")
            tab_vis = await pg.evaluate(_JS_LEAF_ELEMENTS)
            cnt_vis = 0
            for e in tab_vis:
                if e.get("visible"):
                    log(f"    ✓ <{e['tag'].lower():6}> {e['text']!r:65} cls={e['cls'][:45]!r}")
                    cnt_vis += 1
            log(f"  Total visíveis: {cnt_vis}")

            sep(f"  Inputs — {tab_name}")
            tab_inp = await pg.evaluate(_JS_ADF_INPUTS)
            log(f"  {len(tab_inp)} inputs:")
            for inp in tab_inp:
                log(f"    [{inp['tag']}] id={inp['id']!r:50} name={inp['name']!r:35} "
                    f"label={inp['label']!r:50}")

            tab_headers = await pg.evaluate(_JS_ADF_GRID_HEADERS)
            if tab_headers:
                log(f"  Colunas ({tab_headers['sel']}): {tab_headers['texts']}")
                tab_rows = await pg.evaluate(_JS_ADF_GRID_ROWS, 10)
                if tab_rows:
                    log(f"  Primeiras {len(tab_rows['rows'])} linhas ({tab_rows['sel']}):")
                    for r in tab_rows["rows"]:
                        log(f"    {r}")
            else:
                log("  (sem grid nesta aba)")

            tab_links = await pg.evaluate("""
                () => [...document.querySelectorAll('a[href], a[onclick], button')]
                    .filter(el => el.getBoundingClientRect().width > 0)
                    .map(el => ({
                        text: (el.textContent || '').trim().substring(0, 80),
                        cls: el.className || '',
                        href: el.href || el.getAttribute('onclick') || '',
                    }))
                    .filter(el => el.text)
            """)
            if tab_links:
                log("  Links/botões na aba:")
                for lnk in tab_links:
                    log(f"    {lnk['text']!r:60} cls={lnk['cls'][:40]!r}")

            if "processo" in tab_name.lower():
                sep("  ⭐ SEI/Processo — extração especial")
                sei_label = await pg.evaluate(_JS_FIND_SEI)
                if sei_label.get("processo"):
                    log(f"  ⭐ Processo por label: {sei_label['processo']}")
                if sei_label.get("links"):
                    log(f"  ⭐ Links SEI: {sei_label['links']}")

                sei_patterns = await pg.evaluate("""
                    () => {
                        const text = document.body.innerText;
                        const found = new Set();
                        const regexes = [
                            /\\d{7,}-\\d\\.\\d{4}\\.\\d{7}\\/\\d{4}-\\d{2}/g,
                            /E-\\d{2}\\/\\d+\\/\\d{4}/g,
                            /SEI[\\s#:\\-]*[\\d.\\-\\/]{6,}/gi,
                            /\\d{5,}\\.\\d{6,}\\/\\d{4}-\\d{2}/g,
                            /\\b[Pp]rocesso[:\\s]+([\\d.\\-\\/]{8,})/g,
                            /\\b\\d{4,}\\.\\d{4,}\\.\\d{4,}/g,
                        ];
                        for (const re of regexes) {
                            let m;
                            while ((m = re.exec(text)) !== null) {
                                found.add(m[0].trim());
                                if (found.size > 10) break;
                            }
                        }
                        return [...found];
                    }
                """)
                if sei_patterns:
                    log(f"  ⭐ Padrões SEI no texto: {sei_patterns}")

                all_href = await pg.evaluate("""
                    () => [...document.querySelectorAll('a[href]')]
                        .map(a => ({
                            text: a.textContent.trim().substring(0, 80),
                            href: a.href,
                            vis:  a.getBoundingClientRect().width > 0,
                        }))
                        .filter(a => a.text || a.href.length > 5)
                """)
                log("  Todos os links (incluindo ocultos):")
                for lnk in all_href:
                    vis_m = "✓" if lnk["vis"] else "·"
                    log(f"    {vis_m} {lnk['text']!r:65} href={lnk['href']!r}")

                proc_body = await pg.inner_text("body")
                log(f"\n  Texto completo da aba Processo ({len(proc_body)} chars):")
                log(proc_body[:8000])

            tab_html = await pg.content()
            thp = SCREENSHOTS / f"ob_aba_{tab_safe}_dom.html"
            thp.write_text(tab_html, encoding="utf-8")
            log(f"  HTML aba: {thp.name} ({len(tab_html)} chars)")

    else:
        sep("⚠️  Detalhe de OB não foi aberto")
        log("  Possíveis razões:")
        log("  1. Nenhum resultado retornou da busca (filtros muito restritivos)")
        log("  2. Os métodos Enter/Visualizar/dblclick não abriram o detalhe")
        log("  3. A tela de OB ainda não foi alcançada")
        log("\n  Estado atual do DOM:")
        vis_err = await pg.evaluate(_JS_LEAF_ELEMENTS)
        for e in vis_err:
            if e.get("visible"):
                log(f"    ✓ <{e['tag'].lower():6}> {e['text']!r:65} cls={e['cls']!r}")

    try:
        html_fin = await pg.content()
        fp = SCREENSHOTS / "ob_final_dom.html"
        fp.write_text(html_fin, encoding="utf-8")
        log(f"\n  HTML estado final: {fp.name} ({len(html_fin)} chars)")
    except Exception:
        pass

    sep("OB: DEEP-DIVE CONCLUÍDO")


async def main_ob():
    """
    Deep-dive completo: OB Orçamentária — tela de pesquisa → resultados →
    detalhe → todas as abas (Detalhamento, Itens, Pagamentos, Processo/SEI,
    Observação, Espelho Contábil, Registro de Envio, Histórico).

    Uso: python diagnose_siafe.py --ob
    Chrome deve estar aberto com --remote-debugging-port=9222 e logado no SIAFE2.
    """
    log(f"OB Orçamentária — Deep-dive completo — {datetime.now():%d/%m/%Y %H:%M}")
    log("Cobrindo: pesquisa → resultados → detalhe → TODAS as abas")

    p, browser, page = await _cdp_connect()
    if not page:
        REPORT.write_text("\n".join(report_lines), encoding="utf-8")
        return

    pg = await _get_siafe2_page(browser, page)
    if not pg:
        pg = page
    log(f"✅ Aba SIAFE2: {pg.url}")

    # ── Fechar qualquer diálogo aberto (Escape) ───────────────────────────────
    await pg.keyboard.press("Escape")
    await asyncio.sleep(1)

    # ── 1. Navegar para OB Orçamentária via a.xgg (sempre no DOM) ────────────
    sep("1. Navegando para OB Orçamentária")
    on_ob = "ordemBancariaOrcamentaria" in pg.url.lower()
    log(f"  URL atual: {pg.url}")
    log(f"  Já na tela OB: {on_ob}")

    if not on_ob:
        nav_r = await pg.evaluate("""
            () => {
                // Prefer exact match on a.xgg
                for (const el of document.querySelectorAll('a.xgg')) {
                    const t = el.textContent.trim();
                    if ((t === 'OB Orçamentária' || t.includes('OB Or'))
                        && !el.className.includes('p_AFDisabled')) {
                        el.click();
                        return 'a.xgg: ' + t;
                    }
                }
                // Fallback: search all visible elements
                for (const el of document.querySelectorAll('a, li, td, span')) {
                    const t = el.textContent.trim();
                    if (t === 'OB Orçamentária' && el.getBoundingClientRect().width > 0
                        && !el.className.includes('Disabled')) {
                        el.click();
                        return 'fallback: ' + el.tagName + '|' + t;
                    }
                }
                return null;
            }
        """)
        log(f"  Resultado navegação: {nav_r}")
        await _adf_wait(pg, 12000)
        log(f"  URL após navegação: {pg.url}")
    else:
        log("  ✅ Já na tela OB Orçamentária — prosseguindo")

    # ── 2. Snapshot + estado inicial ─────────────────────────────────────────
    sep("2. Estado inicial da tela OB")
    await dump_page(pg, "ob_01_inicial")

    body_ini = await pg.inner_text("body")
    log(f"  Texto completo ({len(body_ini)} chars):\n{body_ini[:3000]}")

    # Detect view: detail (tabs visible) or search/list
    tabs_check = await pg.evaluate("""
        () => {
            const all = [...document.querySelectorAll('a.xyp')];
            const vis = all.filter(el => el.getBoundingClientRect().width > 0);
            return {
                total: all.length,
                visible: vis.length,
                names: vis.map(el => el.textContent.trim()).filter(Boolean),
                disabled: all.map(el => ({
                    text: el.textContent.trim(),
                    dis: el.className.includes('p_AFDisabled'),
                    sel: el.className.includes('p_AFSelected'),
                })).filter(el => el.text)
            };
        }
    """)
    log(f"  Abas a.xyp encontradas: {tabs_check}")
    on_detail = tabs_check.get("visible", 0) > 0

    # ── 3. Mapa completo da tela de pesquisa OB ───────────────────────────────
    sep("3. Todos os inputs/filtros da tela OB (IDs completos para automação)")
    ob_inputs = await pg.evaluate(_JS_ADF_INPUTS)
    log(f"  {len(ob_inputs)} inputs/selects:")
    for inp in ob_inputs:
        log(f"    [{inp['tag']}] id={inp['id']!r:50} name={inp['name']!r:35} "
            f"type={inp['type']!r:10} label={inp['label']!r:50}")

    sep("3b. Todos os links e botões visíveis")
    lnk_btns = await pg.evaluate("""
        () => [...document.querySelectorAll('a, button, input[type="button"], input[type="submit"]')]
            .filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            })
            .map(el => ({
                tag: el.tagName,
                text: (el.textContent || el.value || '').trim().substring(0, 70),
                cls: el.className || '',
                href: el.getAttribute('href') || '',
            }))
            .filter(el => el.text)
    """)
    for lb in lnk_btns:
        log(f"  [{lb['tag']:6}] {lb['text']!r:50} cls={lb['cls'][:45]!r}")

    sep("3c. Todos os elementos visíveis (leaf nodes)")
    vis_ini = await pg.evaluate(_JS_LEAF_ELEMENTS)
    for e in vis_ini:
        if e.get("visible"):
            log(f"  ✓ <{e['tag'].lower():6}> {e['text']!r:65} cls={e['cls'][:45]!r}")

    # HTML do estado inicial
    html_ini = await pg.content()
    hip = SCREENSHOTS / "ob_01_ini_dom.html"
    hip.write_text(html_ini, encoding="utf-8")
    log(f"  HTML inicial: {hip.name} ({len(html_ini)} chars)")

    # ── 4. Verificar se precisamos pesquisar ─────────────────────────────────
    if not on_detail:
        sep("4. Executando busca para obter registros")
        hoje = datetime.now()
        mes_ini = f"01/{hoje.month:02d}/{hoje.year}"
        mes_fim = f"{hoje.day:02d}/{hoje.month:02d}/{hoje.year}"
        log(f"  Período padrão: {mes_ini} a {mes_fim}")

        # Fill date range by label proximity
        date_filled = await pg.evaluate(f"""
            () => {{
                const filled = [];
                for (const inp of document.querySelectorAll('input[type="text"], input:not([type])')) {{
                    if (inp.getBoundingClientRect().width <= 0) continue;
                    let lbl = ''; let par = inp.parentElement;
                    for (let i = 0; i < 6 && par; i++, par = par.parentElement) {{
                        const l = par.querySelector('label, span.x18m, span.af_outputLabel');
                        if (l && l !== inp) {{ lbl = l.textContent.trim().toLowerCase(); break; }}
                    }}
                    const ini = lbl.includes('iní') || lbl.includes(' de') || lbl.match(/^de$/);
                    const fim = lbl.includes('fim') || lbl.includes('até') || lbl.includes('final');
                    if (ini) {{
                        inp.value = '{mes_ini}';
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('blur', {{bubbles: true}}));
                        filled.push('ini:' + lbl + '=' + '{mes_ini}');
                    }} else if (fim) {{
                        inp.value = '{mes_fim}';
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('blur', {{bubbles: true}}));
                        filled.push('fim:' + lbl + '=' + '{mes_fim}');
                    }}
                }}
                return filled;
            }}
        """)
        log(f"  Campos de data preenchidos: {date_filled}")
        await asyncio.sleep(0.8)

        # Click Consultar
        consultar = await pg.evaluate("""
            () => {
                const kws = ['consultar', 'pesquisar', 'buscar', 'filtrar', 'listar', 'executar'];
                for (const el of document.querySelectorAll(
                        'a, button, input[type="button"], input[type="submit"]')) {
                    const t = (el.textContent || el.value || '').trim().toLowerCase();
                    if (kws.some(k => t === k || t.startsWith(k))
                        && el.getBoundingClientRect().width > 0
                        && !el.className.includes('p_AFDisabled')) {
                        el.click();
                        return t;
                    }
                }
                return null;
            }
        """)
        log(f"  Botão Consultar: {consultar!r}")
        if consultar:
            await _adf_wait(pg, 18000)
            await dump_page(pg, "ob_02_resultados")

        # ── 5. Grid de resultados ─────────────────────────────────────────────
        sep("5. Grid de resultados OB — colunas e primeiras linhas")
        ob_headers = await pg.evaluate(_JS_ADF_GRID_HEADERS)
        if ob_headers:
            log(f"  Colunas ({ob_headers['sel']}): {ob_headers['texts']}")
        else:
            log("  (colunas não detectadas — grid pode estar vazia)")

        rows_data = await pg.evaluate(_JS_ADF_GRID_ROWS, 5)
        if rows_data:
            log(f"  Primeiras {len(rows_data['rows'])} linhas ({rows_data['sel']}):")
            for r in rows_data["rows"]:
                log(f"    {r}")
        else:
            log("  Sem linhas na grid — verificando texto da página:")
            page_text = await pg.inner_text("body")
            log(f"  Texto ({len(page_text)} chars): {page_text[:1500]}")

        # ── 6. Abrir detalhe da primeira OB ─────────────────────────────────
        sep("6. Abrindo detalhe da primeira OB")

        row_info = await pg.evaluate("""
            () => {
                const sels = [
                    'tr.af_table_row',
                    'tr[class*="Row"]:not([class*="Header"]):not([class*="header"])',
                    'tbody tr'
                ];
                for (const sel of sels) {
                    for (const row of document.querySelectorAll(sel)) {
                        const r = row.getBoundingClientRect();
                        if (r.height > 5 && row.textContent.trim().length > 2) {
                            row.click();
                            return {text: row.textContent.trim().substring(0, 150), sel};
                        }
                    }
                }
                return null;
            }
        """)
        log(f"  Linha clicada: {row_info}")

        if row_info:
            await asyncio.sleep(1.5)

            # Method 1: Enter key
            body_bef = len(await pg.inner_text("body"))
            await pg.keyboard.press("Enter")
            await _adf_wait(pg, 10000)

            tabs_after = await pg.evaluate("""
                () => [...document.querySelectorAll('a.xyp')]
                    .filter(el => el.getBoundingClientRect().width > 0)
                    .map(el => el.textContent.trim()).filter(Boolean)
            """)
            if tabs_after:
                log(f"  ✅ Detalhe via Enter — abas: {tabs_after}")
                on_detail = True

            # Method 2: "Visualizar OB" no painel esquerdo
            if not on_detail:
                viz = await pg.evaluate("""
                    () => {
                        for (const el of document.querySelectorAll('a.xg8, a[class*="xg"]')) {
                            if (el.textContent.trim().includes('Visualizar')
                                && !el.className.includes('p_AFDisabled')) {
                                el.click();
                                return el.textContent.trim();
                            }
                        }
                        return null;
                    }
                """)
                log(f"  Visualizar: {viz!r}")
                if viz:
                    await _adf_wait(pg, 10000)
                    tabs_after2 = await pg.evaluate("""
                        () => [...document.querySelectorAll('a.xyp')]
                            .filter(el => el.getBoundingClientRect().width > 0)
                            .map(el => el.textContent.trim()).filter(Boolean)
                    """)
                    if tabs_after2:
                        log(f"  ✅ Detalhe via Visualizar — abas: {tabs_after2}")
                        on_detail = True

            # Method 3: double-click
            if not on_detail:
                dbl = await pg.evaluate("""
                    () => {
                        const sels = ['tr.af_table_row',
                                      'tr[class*="Row"]:not([class*="Header"])', 'tbody tr'];
                        for (const sel of sels) {
                            const row = document.querySelector(sel);
                            if (row && row.getBoundingClientRect().height > 0) {
                                row.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
                                return sel;
                            }
                        }
                        return null;
                    }
                """)
                log(f"  Dblclick: {dbl!r}")
                await _adf_wait(pg, 10000)
                tabs_after3 = await pg.evaluate("""
                    () => [...document.querySelectorAll('a.xyp')]
                        .filter(el => el.getBoundingClientRect().width > 0)
                        .map(el => el.textContent.trim()).filter(Boolean)
                """)
                if tabs_after3:
                    log(f"  ✅ Detalhe via dblclick — abas: {tabs_after3}")
                    on_detail = True

        if not on_detail:
            log("  ⚠️  Não conseguiu abrir detalhe — dump do estado atual:")
            vis_fail = await pg.evaluate(_JS_LEAF_ELEMENTS)
            for e in vis_fail:
                if e.get("visible"):
                    log(f"    ✓ <{e['tag'].lower():6}> {e['text']!r:65} cls={e['cls']!r}")

    # ── 7. Tela de detalhe + TODAS as abas ───────────────────────────────────
    if on_detail:
        sep("7. Mapeando tela de detalhe OB — estado inicial (aba Detalhamento)")
        await dump_page(pg, "ob_03_detalhe")

        body_det = await pg.inner_text("body")
        log(f"  Texto completo do detalhe ({len(body_det)} chars):\n{body_det[:4000]}")

        # Full inputs of detail screen
        sep("7b. Todos os inputs do detalhe OB")
        det_inputs = await pg.evaluate(_JS_ADF_INPUTS)
        log(f"  {len(det_inputs)} inputs/selects:")
        for inp in det_inputs:
            log(f"    [{inp['tag']}] id={inp['id']!r:50} name={inp['name']!r:35} "
                f"label={inp['label']!r:50}")

        # All visible elements in detail
        sep("7c. Elementos visíveis no detalhe")
        det_vis = await pg.evaluate(_JS_LEAF_ELEMENTS)
        for e in det_vis:
            if e.get("visible"):
                log(f"  ✓ <{e['tag'].lower():6}> {e['text']!r:65} cls={e['cls'][:45]!r}")

        # HTML of detail state
        det_html = await pg.content()
        dhp = SCREENSHOTS / "ob_03_detalhe_dom.html"
        dhp.write_text(det_html, encoding="utf-8")
        log(f"  HTML detalhe: {dhp.name} ({len(det_html)} chars)")

        # ── 7d. Ler todas as abas disponíveis ────────────────────────────────
        sep("7d. Abas disponíveis (a.xyp)")
        all_tabs = await pg.evaluate("""
            () => [...document.querySelectorAll('a.xyp')].map(el => ({
                text:     el.textContent.trim(),
                cls:      el.className,
                disabled: el.className.includes('p_AFDisabled'),
                selected: el.className.includes('p_AFSelected'),
                visible:  el.getBoundingClientRect().width > 0
            })).filter(t => t.text)
        """)
        log(f"  {len(all_tabs)} abas:")
        for t in all_tabs:
            marks = []
            if t["disabled"]:  marks.append("DESABILITADA")
            if t["selected"]:  marks.append("SELECIONADA")
            if not t["visible"]: marks.append("oculta")
            log(f"    {'[D]' if t['disabled'] else '   '} {t['text']!r:35} {marks}")

        # ── 8. Explorar cada aba ─────────────────────────────────────────────
        sep("8. Explorando cada aba do detalhe OB")

        for tab_info in all_tabs:
            tab_name = tab_info["text"]
            tab_safe = tab_name[:20].replace(" ", "_").replace("/", "_").lower()
            is_dis   = tab_info["disabled"]
            is_sel   = tab_info["selected"]

            sep(f"  ABA: {tab_name!r}{'  [DESABILITADA]' if is_dis else ''}")

            if is_dis:
                log("  ⏭️  Aba desabilitada — pulando")
                continue

            # Click tab (skip if already selected — stay and capture)
            if not is_sel:
                tab_name_js = tab_name.replace("'", "\\'")
                r_tab = await pg.evaluate(f"""
                    () => {{
                        for (const el of document.querySelectorAll('a.xyp')) {{
                            const t = el.textContent.trim();
                            if ((t === '{tab_name_js}' || t.includes('{tab_name_js[:10]}'))
                                && !el.className.includes('p_AFDisabled')) {{
                                el.click();
                                return el.textContent.trim();
                            }}
                        }}
                        return null;
                    }}
                """)
                log(f"  Clicou aba: {r_tab!r}")
                await _adf_wait(pg, 10000)
            else:
                log("  (aba já selecionada — capturando conteúdo atual)")

            # Screenshot
            await pg.screenshot(path=str(SCREENSHOTS / f"ob_aba_{tab_safe}.png"),
                                 full_page=True)
            log(f"  📸 ob_aba_{tab_safe}.png")

            # ── Texto completo da aba ────────────────────────────────────────
            tab_body = await pg.inner_text("body")
            log(f"\n  Texto completo da aba ({len(tab_body)} chars):")
            log(tab_body[:5000])

            # ── Elementos visíveis ───────────────────────────────────────────
            sep(f"  Elementos visíveis — {tab_name}")
            tab_vis = await pg.evaluate(_JS_LEAF_ELEMENTS)
            cnt_vis = 0
            for e in tab_vis:
                if e.get("visible"):
                    log(f"    ✓ <{e['tag'].lower():6}> {e['text']!r:65} cls={e['cls'][:45]!r}")
                    cnt_vis += 1
            log(f"  Total visíveis: {cnt_vis}")

            # ── Inputs desta aba ─────────────────────────────────────────────
            sep(f"  Inputs — {tab_name}")
            tab_inp = await pg.evaluate(_JS_ADF_INPUTS)
            log(f"  {len(tab_inp)} inputs:")
            for inp in tab_inp:
                log(f"    [{inp['tag']}] id={inp['id']!r:50} name={inp['name']!r:35} "
                    f"label={inp['label']!r:50}")

            # ── Grid nesta aba (se houver) ───────────────────────────────────
            tab_headers = await pg.evaluate(_JS_ADF_GRID_HEADERS)
            if tab_headers:
                log(f"  Colunas ({tab_headers['sel']}): {tab_headers['texts']}")
                tab_rows = await pg.evaluate(_JS_ADF_GRID_ROWS, 10)
                if tab_rows:
                    log(f"  Primeiras {len(tab_rows['rows'])} linhas ({tab_rows['sel']}):")
                    for r in tab_rows["rows"]:
                        log(f"    {r}")
            else:
                log("  (sem grid nesta aba)")

            # ── Links e botões desta aba ─────────────────────────────────────
            tab_links = await pg.evaluate("""
                () => [...document.querySelectorAll('a[href], a[onclick], button')]
                    .filter(el => el.getBoundingClientRect().width > 0)
                    .map(el => ({
                        text: (el.textContent || '').trim().substring(0, 80),
                        cls: el.className || '',
                        href: el.href || el.getAttribute('onclick') || '',
                    }))
                    .filter(el => el.text)
            """)
            if tab_links:
                log("  Links/botões na aba:")
                for lnk in tab_links:
                    log(f"    {lnk['text']!r:60} cls={lnk['cls'][:40]!r}")
                    if lnk["href"]:
                        log(f"      href={lnk['href']!r}")

            # ──────────────────────────────────────────────────────────────────
            # TRATAMENTO ESPECIAL: aba Processo (SEI)
            # ──────────────────────────────────────────────────────────────────
            if "processo" in tab_name.lower():
                sep("  ⭐ SEI/Processo — extração especial")

                # Strategy 1: label-based search
                sei_label = await pg.evaluate(_JS_FIND_SEI)
                if sei_label.get("processo"):
                    log(f"  ⭐ Processo por label: {sei_label['processo']}")
                if sei_label.get("links"):
                    log(f"  ⭐ Links SEI: {sei_label['links']}")

                # Strategy 2: regex over full body text
                sei_patterns = await pg.evaluate("""
                    () => {
                        const text = document.body.innerText;
                        const found = new Set();
                        const regexes = [
                            /\\d{7,}-\\d\\.\\d{4}\\.\\d{7}\\/\\d{4}-\\d{2}/g,
                            /E-\\d{2}\\/\\d+\\/\\d{4}/g,
                            /SEI[\\s#:\\-]*[\\d.\\-\\/]{6,}/gi,
                            /\\d{5,}\\.\\d{6,}\\/\\d{4}-\\d{2}/g,
                            /\\b[Pp]rocesso[:\\s]+([\\d.\\-\\/]{8,})/g,
                            /\\b\\d{4,}\\.\\d{4,}\\.\\d{4,}/g,
                        ];
                        for (const re of regexes) {
                            let m;
                            while ((m = re.exec(text)) !== null) {
                                found.add(m[0].trim());
                                if (found.size > 10) break;
                            }
                        }
                        return [...found];
                    }
                """)
                if sei_patterns:
                    log(f"  ⭐ Padrões SEI no texto: {sei_patterns}")

                # Strategy 3: all hyperlinks (SEI links often have specific domains)
                all_href = await pg.evaluate("""
                    () => [...document.querySelectorAll('a[href]')]
                        .map(a => ({
                            text: a.textContent.trim().substring(0, 80),
                            href: a.href,
                            vis:  a.getBoundingClientRect().width > 0,
                        }))
                        .filter(a => a.text || a.href.length > 5)
                """)
                log("  Todos os links (incluindo ocultos):")
                for lnk in all_href:
                    vis_m = "✓" if lnk["vis"] else "·"
                    log(f"    {vis_m} {lnk['text']!r:65} href={lnk['href']!r}")

                # Full body text of Processo tab (para análise posterior)
                proc_body = await pg.inner_text("body")
                log(f"\n  Texto completo da aba Processo ({len(proc_body)} chars):")
                log(proc_body[:8000])

            # ── HTML completo desta aba ──────────────────────────────────────
            tab_html = await pg.content()
            thp = SCREENSHOTS / f"ob_aba_{tab_safe}_dom.html"
            thp.write_text(tab_html, encoding="utf-8")
            log(f"  HTML aba: {thp.name} ({len(tab_html)} chars)")

    else:
        sep("⚠️  Detalhe de OB não foi aberto")
        log("  Possíveis razões:")
        log("  1. Nenhum resultado retornou da busca (filtros muito restritivos)")
        log("  2. Os métodos Enter/Visualizar/dblclick não abriram o detalhe")
        log("  3. A tela de OB ainda não foi alcançada")
        log("\n  Estado atual do DOM:")
        vis_err = await pg.evaluate(_JS_LEAF_ELEMENTS)
        for e in vis_err:
            if e.get("visible"):
                log(f"    ✓ <{e['tag'].lower():6}> {e['text']!r:65} cls={e['cls']!r}")

    # ── HTML final + relatório ────────────────────────────────────────────────
    try:
        html_fin = await pg.content()
        fp = SCREENSHOTS / "ob_final_dom.html"
        fp.write_text(html_fin, encoding="utf-8")
        log(f"\n  HTML estado final: {fp.name} ({len(html_fin)} chars)")
    except Exception:
        pass

    sep("OB ORÇAMENTÁRIA — DIAGNÓSTICO CONCLUÍDO")
    log(f"  Screenshots em: {SCREENSHOTS}/")
    log(f"  Relatório em:   {REPORT}")

    await p.stop()
    REPORT.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n✅ Relatório salvo em: {REPORT}")


async def _dump_inputs_consultas(page, label: str):
    """Dump all inputs visible after navigating to a consultation."""
    sep(f"Inputs: {label}")
    form_inputs = await page.query_selector_all("input, select, textarea, button")
    log(f"  {len(form_inputs)} elementos:")
    for inp in form_inputs:
        try:
            tag = await inp.evaluate("el => el.tagName.toLowerCase()")
            id_ = await inp.get_attribute("id") or ""
            nm  = await inp.get_attribute("name") or ""
            tp  = await inp.get_attribute("type") or ""
            cls = await inp.get_attribute("class") or ""
            ph  = await inp.get_attribute("placeholder") or ""
            txt = (await inp.inner_text()).strip()[:40]
            r = await inp.bounding_box()
            vis = "✓" if (r and r["width"] > 0) else "·"
            log(f"  {vis} <{tag}> id={id_!r:30} name={nm!r:20} type={tp!r:12} "
                f"class={cls[:35]!r} ph={ph!r} txt={txt!r}")
        except Exception:
            pass


if __name__ == "__main__":
    import sys
    if "--cdp" in sys.argv:
        asyncio.run(main_cdp())
    elif "--consultas" in sys.argv:
        asyncio.run(main_consultas())
    elif "--siafe2" in sys.argv:
        asyncio.run(main_siafe2())
    elif "--ob" in sys.argv:
        asyncio.run(main_ob())
    else:
        asyncio.run(main())
