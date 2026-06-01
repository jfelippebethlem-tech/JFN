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
import json
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
        log(f"\n  --- Texto visível (primeiros 1500 chars) ---")
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


async def main():
    from playwright.async_api import async_playwright

    log(f"SIAFE2 Diagnóstico — {datetime.now():%d/%m/%Y %H:%M}")
    log(f"Usuário: {USERNAME}")
    log(f"Exercício configurado: {EXERCICIO or '(padrão)'}")

    if not USERNAME or not PASSWORD:
        log("\n❌ SIAFE_USER e SIAFE_PASS não encontrados no .env!")
        log("   Preencha o arquivo .env antes de rodar este script.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # browser VISÍVEL
            slow_mo=300,     # mais devagar para acompanhar
            args=["--no-sandbox", "--disable-setuid-sandbox", "--ignore-certificate-errors"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            ignore_https_errors=True,
        )
        page = await ctx.new_page()

        # ── Etapa 1: Página de Login ───────────────────────────────────────────
        sep("ETAPA 1: Página de Login")
        log(f"  Abrindo: {SIAFE_LOGIN}")
        try:
            await page.goto(SIAFE_LOGIN, wait_until="networkidle", timeout=30000)
        except Exception as e:
            log(f"  Erro ao carregar: {e}")
            log("  Tentando sem wait_until...")
            await page.goto(SIAFE_LOGIN, timeout=30000)

        await asyncio.sleep(2)
        await dump_page(page, "01_login_page")

        # ── Etapa 2: Preencher login ───────────────────────────────────────────
        sep("ETAPA 2: Preenchendo credenciais")

        # Dump todos os inputs primeiro
        all_inputs = await page.query_selector_all("input")
        log(f"  Encontrados {len(all_inputs)} inputs")

        filled_user = False
        filled_pass = False

        for inp in all_inputs:
            try:
                t = await inp.get_attribute("type") or "text"
                n = await inp.get_attribute("name") or ""
                i = await inp.get_attribute("id") or ""
                if t == "password":
                    log(f"  → Preenchendo senha em: id={i!r} name={n!r}")
                    await inp.fill(PASSWORD)
                    filled_pass = True
                elif t in ("text", "number", "") and not filled_user:
                    v = await inp.get_attribute("value") or ""
                    if not v:  # campo vazio
                        log(f"  → Preenchendo usuário em: id={i!r} name={n!r}")
                        await inp.fill(USERNAME)
                        filled_user = True
            except Exception as ex:
                log(f"  [erro: {ex}]")

        # Selects (Cliente, Exercício)
        all_selects = await page.query_selector_all("select")
        log(f"\n  Encontrados {len(all_selects)} selects")
        for sel in all_selects:
            try:
                i = await sel.get_attribute("id") or ""
                n = await sel.get_attribute("name") or ""
                opts = await sel.query_selector_all("option")
                opt_texts = []
                for o in opts[:10]:
                    opt_texts.append(await o.inner_text())
                log(f"  Select id={i!r} name={n!r} opções: {opt_texts}")

                # Se parece exercício, seleciona o ano correto
                if EXERCICIO and any(EXERCICIO in t for t in opt_texts):
                    log(f"    → Selecionando exercício {EXERCICIO}")
                    await sel.select_option(label=EXERCICIO)
            except Exception as ex:
                log(f"  [erro no select: {ex}]")

        await dump_page(page, "02_credentials_filled")

        # ── Etapa 3: Submeter login ────────────────────────────────────────────
        sep("ETAPA 3: Submetendo login")
        buttons = await page.query_selector_all("button, input[type='submit'], input[type='button']")
        log(f"  Encontrados {len(buttons)} botões:")
        for btn in buttons:
            try:
                txt = (await btn.inner_text()).strip() or await btn.get_attribute("value") or ""
                i   = await btn.get_attribute("id") or ""
                cls = await btn.get_attribute("class") or ""
                log(f"  Botão: {txt!r:20} id={i!r:30} class={cls[:40]!r}")
            except Exception:
                pass

        # Clicar no primeiro botão de submit ou "Ok"/"Entrar"
        submitted = False
        for btn in buttons:
            try:
                txt = (await btn.inner_text()).strip().lower()
                val = (await btn.get_attribute("value") or "").lower()
                if any(kw in txt or kw in val for kw in ["ok", "entrar", "acessar", "login", "submit", "confirmar"]):
                    log(f"  → Clicando botão: {txt!r}")
                    await btn.click()
                    submitted = True
                    break
            except Exception:
                pass

        if not submitted:
            log("  → Nenhum botão encontrado, tentando Enter...")
            await page.keyboard.press("Enter")

        log("  Aguardando carregamento pós-login...")
        await asyncio.sleep(3)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await asyncio.sleep(2)

        await dump_page(page, "03_after_login")

        # ── Etapa 4: Menu principal ────────────────────────────────────────────
        sep("ETAPA 4: Mapeando menu principal")
        current_url = page.url
        log(f"  URL após login: {current_url}")

        if "login" in current_url.lower():
            log("  ⚠️  Ainda na página de login — verificar credenciais ou OTP")
            body = await page.inner_text("body")
            log(f"  Texto: {body[:800]}")

            # Verificar OTP
            if any(kw in body.lower() for kw in ["código", "token", "e-mail", "autenticação"]):
                log("\n  🔐 Parece que há pedido de código OTP/2FA!")
                log("  Digite o código e pressione Enter para continuar...")
                otp = input("  Código OTP: ").strip()
                otp_inputs = await page.query_selector_all("input[type='text']:visible, input[type='number']:visible")
                for oi in otp_inputs:
                    await oi.fill(otp)
                await page.keyboard.press("Enter")
                await asyncio.sleep(3)
                await page.wait_for_load_state("networkidle", timeout=15000)
                await dump_page(page, "04_after_otp")
        else:
            log("  ✅ Login realizado!")

        # ── Etapa 5: Localizar FlexVision no menu ──────────────────────────────
        sep("ETAPA 5: Procurando FlexVision no menu")

        # Listar todos os elementos clicáveis do topo
        nav_elements = await page.query_selector_all(
            "a, button, li, td.af_menuBar_item, [role='menuitem'], [role='menubar'] *"
        )
        log(f"  {len(nav_elements)} elementos de navegação encontrados:")
        for el in nav_elements[:100]:
            try:
                txt = (await el.inner_text()).strip()
                cls = await el.get_attribute("class") or ""
                if txt and len(txt) < 80:
                    log(f"  - {txt!r:40} class={cls[:40]!r}")
            except Exception:
                pass

        # Tentar clicar em FlexVision
        fv = None
        for selector in [
            'a:has-text("FlexVision")',
            'span:has-text("FlexVision")',
            'td:has-text("FlexVision")',
            'li:has-text("FlexVision")',
            '*:has-text("FlexVision"):visible',
        ]:
            try:
                fv = await page.wait_for_selector(selector, timeout=3000)
                if fv:
                    log(f"  ✅ FlexVision encontrado com: {selector!r}")
                    break
            except Exception:
                pass

        if fv:
            log("  → Clicando em FlexVision...")
            await fv.click()
            await asyncio.sleep(3)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            await dump_page(page, "05_flexvision")
        else:
            log("  ❌ FlexVision não encontrado no menu. Listando TODOS os links:")
            all_links = await page.query_selector_all("a")
            for lnk in all_links:
                try:
                    txt  = (await lnk.inner_text()).strip()
                    href = await lnk.get_attribute("href") or ""
                    if txt:
                        log(f"    link: {txt!r:50} href={href[:80]!r}")
                except Exception:
                    pass

        # ── Etapa 6: Navegar para Execução por OB ─────────────────────────────
        sep("ETAPA 6: Procurando 'Execução por OB' / 'Consultas'")

        # Verificar frames
        frames = page.frames
        log(f"  {len(frames)} frames na página:")
        for f in frames:
            log(f"  Frame: {f.url}")

        # Buscar em todos os frames
        for frame in frames:
            try:
                frame_text = await frame.inner_text("body")
                if any(kw in frame_text for kw in ["Consultas", "Execução", "FlexVision"]):
                    log(f"\n  🎯 Conteúdo relevante no frame: {frame.url}")
                    log(f"  Texto: {frame_text[:1000]}")

                    # Listar links deste frame
                    frame_links = await frame.query_selector_all("a, button, li, td")
                    log(f"\n  Links no frame ({len(frame_links)} elementos):")
                    for el in frame_links[:60]:
                        try:
                            txt = (await el.inner_text()).strip()
                            if txt and len(txt) < 80:
                                log(f"    - {txt!r}")
                        except Exception:
                            pass
            except Exception:
                pass

        # Dump final
        sep("ETAPA 7: Screenshot final")
        await dump_page(page, "07_final_state")

        log("\n\n" + "="*60)
        log("  DIAGNÓSTICO CONCLUÍDO")
        log(f"  Screenshots em: {SCREENSHOTS}/")
        log(f"  Relatório em:   {REPORT}")
        log("="*60)

        log("\n  Aguardando 15s para você visualizar... (feche o browser para encerrar)")
        await asyncio.sleep(15)

        await browser.close()

    # Salvar relatório
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
                log(f"  ✅ Campos encontrados — preenchendo credenciais")
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
                    log(f"  → Clicando no primeiro botão disponível")
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
            log(f"\n  ✅ Linhas com 'OB'/'Execu':")
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


async def main_siafe2():
    """
    Modo SIAFE2: mapeia o menu Oracle ADF do SIAFE2 via CDP.
    Explora todos os menus principais e submenus procurando OB / Ordens Bancárias.

    Uso: python diagnose_siafe.py --siafe2
    Chrome deve estar aberto com --remote-debugging-port=9222 e logado no SIAFE2.
    """
    log(f"SIAFE2 Diagnóstico (modo SIAFE2) — {datetime.now():%d/%m/%Y %H:%M}")

    p, browser, page = await _cdp_connect()
    if not page:
        REPORT.write_text("\n".join(report_lines), encoding="utf-8")
        return

    # Prefer SIAFE2 tab (not FlexVision)
    siafe2_page = None
    for ctx in browser.contexts:
        for pg in ctx.pages:
            url = pg.url.lower()
            if "siafe2.fazenda" in url and "flexvision" not in url:
                siafe2_page = pg
                break
        if siafe2_page:
            break
    if not siafe2_page:
        siafe2_page = page
        log(f"⚠️  Usando aba disponível: {page.url}")
    else:
        log(f"✅ Aba SIAFE2 encontrada: {siafe2_page.url}")

    # ── 1. Snapshot inicial ───────────────────────────────────────────────────
    sep("1. Página atual do SIAFE2")
    await dump_page(siafe2_page, "s01_siafe2_inicial")
    body_init = await siafe2_page.inner_text("body")
    if "login" in siafe2_page.url.lower():
        log("⚠️  Ainda na página de login. Faça login e execute de novo.")
        REPORT.write_text("\n".join(report_lines), encoding="utf-8")
        await p.stop()
        return

    # ── 2. Mapear menu principal (classe .xyo) ────────────────────────────────
    sep("2. Menu principal (.xyo)")
    main_menu_els = await siafe2_page.query_selector_all(".xyo")
    log(f"  {len(main_menu_els)} itens .xyo:")
    menu_texts: list[str] = []
    for item in main_menu_els:
        try:
            t = (await item.inner_text()).strip()
            cls = await item.get_attribute("class") or ""
            if t:
                menu_texts.append(t)
                log(f"    - {t!r:40} cls={cls!r}")
        except Exception:
            pass

    # Fallback seletores se .xyo vazio
    if not menu_texts:
        sep("2b. Fallback — outros seletores de menu")
        for sel in [
            ".af_menuBar_item", "[role='menuitem']", ".xfl", ".xfk",
            "a[class*='menu']", "td[class*='menu']",
        ]:
            items = await siafe2_page.query_selector_all(sel)
            if items:
                log(f"  {sel!r}: {len(items)} itens")
                for it in items[:20]:
                    try:
                        t = (await it.inner_text()).strip()
                        cls = await it.get_attribute("class") or ""
                        if t and len(t) < 100:
                            log(f"    - {t!r:50} cls={cls!r}")
                    except Exception:
                        pass

    # ── 3. Clicar em cada menu e registrar submenus ───────────────────────────
    sep("3. Mapa completo de menus")
    menu_map: dict[str, list] = {}
    all_top_els = await siafe2_page.query_selector_all(".xyo")
    for menu_el in all_top_els:
        try:
            menu_text = (await menu_el.inner_text()).strip()
            if not menu_text:
                continue
            await menu_el.click()
            await asyncio.sleep(1.2)

            sub_items = await siafe2_page.query_selector_all(".xgh")
            sub_data: list[dict] = []
            for si in sub_items:
                try:
                    t = (await si.inner_text()).strip()
                    cls = await si.get_attribute("class") or ""
                    if not t:
                        continue
                    disabled = "p_AFDisabled" in cls
                    sub_data.append({"text": t, "disabled": disabled, "cls": cls})
                except Exception:
                    pass

            menu_map[menu_text] = sub_data
            log(f"\n  ── {menu_text!r} ({len(sub_data)} submenus) ──")
            for sd in sub_data:
                mark = "[D]" if sd["disabled"] else "   "
                ob_flag = " ⭐OB" if any(
                    kw in sd["text"].upper() for kw in ("OB", "ORDEM BANC", "ORDENS BANC")
                ) else ""
                log(f"    {mark} {sd['text']!r}{ob_flag}")

            # Press Escape to close menu before next iteration
            await siafe2_page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        except Exception as ex:
            log(f"  [erro: {ex}]")

    # ── 4. Explorar submenus de Execução em profundidade ─────────────────────
    sep("4. Submenus de Execução (com sub-submenus)")
    exec_el = None
    for menu_el in await siafe2_page.query_selector_all(".xyo"):
        try:
            if (await menu_el.inner_text()).strip() == "Execução":
                exec_el = menu_el
                break
        except Exception:
            pass

    if exec_el:
        for sd in menu_map.get("Execução", []):
            if sd["disabled"]:
                log(f"  ⏭️  '{sd['text']}' — desativado")
                continue

            # Reopen Execução menu
            try:
                exec_el2 = None
                for el in await siafe2_page.query_selector_all(".xyo"):
                    if (await el.inner_text()).strip() == "Execução":
                        exec_el2 = el
                        break
                if not exec_el2:
                    break
                await exec_el2.click()
                await asyncio.sleep(1)

                # Find and click this submenu item
                sub_items2 = await siafe2_page.query_selector_all(".xgh")
                target = None
                for si in sub_items2:
                    try:
                        t = (await si.inner_text()).strip()
                        cls = await si.get_attribute("class") or ""
                        if t == sd["text"] and "p_AFDisabled" not in cls:
                            target = si
                            break
                    except Exception:
                        pass

                if not target:
                    log(f"  ❌ '{sd['text']}' não clicável")
                    await siafe2_page.keyboard.press("Escape")
                    continue

                await target.click()
                await asyncio.sleep(1)

                sub2 = await siafe2_page.query_selector_all(".xgg")
                if sub2:
                    log(f"\n  ▶ '{sd['text']}' → {len(sub2)} sub-submenus:")
                    for ssi in sub2:
                        try:
                            t = (await ssi.inner_text()).strip()
                            cls2 = await ssi.get_attribute("class") or ""
                            disabled2 = "p_AFDisabled" in cls2
                            ob_flag = " ⭐OB" if any(
                                kw in t.upper() for kw in ("OB", "ORDEM BANC", "ORDENS BANC")
                            ) else ""
                            mark2 = "[D]" if disabled2 else "   "
                            if t:
                                log(f"      {mark2} {t!r}{ob_flag}")
                        except Exception:
                            pass
                else:
                    log(f"  ▶ '{sd['text']}' — sem sub-submenus (abriu página?)")
                    body_after = await siafe2_page.inner_text("body")
                    if len(body_after) != len(body_init):
                        log(f"    Texto página ({len(body_after)} chars): {body_after[:300]}")
                    await dump_page(siafe2_page, f"s04_exec_{sd['text'][:20].replace(' ','_').lower()}")

                await siafe2_page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
            except Exception as ex:
                log(f"  [erro: {ex}]")
    else:
        log("  ❌ Menu 'Execução' não encontrado no DOM")

    # ── 5. Busca por 'OB' em todo o DOM ──────────────────────────────────────
    sep("5. Elementos com 'OB' / 'Ordem Bancária' no DOM")
    ob_elements = await siafe2_page.evaluate("""
        () => {
            const kws = ['OB', 'Ordem Banc', 'Ordens Banc', 'ordem banc'];
            const results = [];
            for (const el of document.querySelectorAll('*')) {
                const direct = [...el.childNodes]
                    .filter(n => n.nodeType === 3)
                    .map(n => n.textContent.trim())
                    .filter(Boolean)
                    .join(' ');
                if (!direct || direct.length > 200) continue;
                if (kws.some(k => direct.includes(k))) {
                    const r = el.getBoundingClientRect();
                    results.push({
                        tag: el.tagName, cls: el.className,
                        text: direct, visible: r.width > 0 && r.height > 0
                    });
                }
            }
            return results;
        }
    """)
    log(f"  {len(ob_elements)} elementos encontrados:")
    for e in ob_elements:
        vis = "✓" if e.get("visible") else "·"
        log(f"  {vis} <{e['tag'].lower():8}> text={e['text']!r:60} cls={e['cls']!r}")

    # ── 6. Dump todos os itens visíveis ──────────────────────────────────────
    sep("6. Todos os elementos visíveis (leaf nodes)")
    leaf_els = await siafe2_page.evaluate(_JS_LEAF_ELEMENTS)
    visible_els = [e for e in leaf_els if e.get("visible")]
    log(f"  {len(visible_els)} visíveis:")
    for e in visible_els:
        log(f"  ✓ <{e['tag'].lower():6}> {e['text']!r:60} cls={e['cls'][:50]!r}")

    # ── 7. HTML completo ──────────────────────────────────────────────────────
    html = await siafe2_page.content()
    html_path = SCREENSHOTS / "siafe2_dom.html"
    html_path.write_text(html, encoding="utf-8")
    log(f"\n  HTML completo: {html_path.name} ({len(html)} chars)")

    sep("DIAGNÓSTICO SIAFE2 CONCLUÍDO")
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
    else:
        asyncio.run(main())
