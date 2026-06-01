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
        menu_map[name] = subs

        log(f"\n  ── {name!r} ──")
        for s in subs:
            mark = "[D]" if s["disabled"] else "   "
            ob_flag = " ⭐" if any(k in s["text"].upper()
                                   for k in ("OB", "ORDEM BANC")) else ""
            log(f"    {mark} {s['text']!r}{ob_flag}")

        await pg.keyboard.press("Escape")
        await asyncio.sleep(0.6)

    # ── 3. Click Execução tab + mapear submenus ───────────────────────────────
    sep("3. Entrando em Execução")
    r_exec = await _js_click_adf(pg, "a.xyo", "Execução")
    if not r_exec:
        r_exec = await pg.evaluate("""
            () => {
                for (const el of document.querySelectorAll('a.xyo')) {
                    if (el.textContent.trim().startsWith('Execu')
                        && !el.className.includes('Disabled')) {
                        el.click();
                        return el.textContent.trim();
                    }
                }
                return null;
            }
        """)
    log(f"  Clicou Execução: {r_exec}")
    await _adf_wait(pg, 8000)
    await dump_page(pg, "s02_execucao")

    exec_subs = await _js_read_items(pg, "a.xgh")
    exec_subs = [s for s in exec_subs if s["text"] not in top_names_set and s["text"]]
    log(f"  {len(exec_subs)} submenus de Execução:")
    for s in exec_subs:
        mark = "[D]" if s["disabled"] else "   "
        log(f"    {mark} {s['text']!r}")

    # ── 4. Explorar cada submenu de Execução ──────────────────────────────────
    sep("4. Explorando cada submenu de Execução")

    for sub in exec_subs:
        if sub["disabled"]:
            log(f"\n  ⏭️  '{sub['text']}' — desativado")
            continue

        sub_name = sub["text"]
        safe_name = sub_name[:18].replace(" ", "_").replace("/", "_").lower()
        log(f"\n{'─'*60}")
        log(f"  SUBMENU: {sub_name!r}")

        # Navigate back to Execução, then click this submenu
        r_back = await _js_click_adf(pg, "a.xyo", "Execução")
        if not r_back:
            await pg.evaluate("""
                () => {
                    for (const el of document.querySelectorAll('a.xyo')) {
                        if (el.textContent.trim().startsWith('Execu')
                            && !el.className.includes('Disabled')) { el.click(); return; }
                    }
                }
            """)
        await _adf_wait(pg, 6000)

        r_sub = await _js_click_adf(pg, "a.xgh", sub_name)
        if not r_sub:
            # Partial match fallback
            sub_words = sub_name.split()
            r_sub = await pg.evaluate(f"""
                () => {{
                    for (const el of document.querySelectorAll('a.xgh')) {{
                        const t = el.textContent.trim();
                        if (t.includes('{sub_words[0]}') && !el.className.includes('Disabled')) {{
                            el.click();
                            return t;
                        }}
                    }}
                    return null;
                }}
            """)
        if not r_sub:
            log(f"  ❌ '{sub_name}' não encontrado após reabrir Execução")
            continue

        await _adf_wait(pg, 8000)
        await dump_page(pg, f"s03_{safe_name}")

        body_sub = await pg.inner_text("body")
        log(f"  Texto ({len(body_sub)} chars): {body_sub[:400]}")

        # ── Painel esquerdo ───────────────────────────────────────────────────
        left = await _js_read_items(pg, "a.xg8")
        if not left:
            for sel in ["a[class*='xg']", ".af_navigationPane a"]:
                left = await _js_read_items(pg, sel)
                if left:
                    break

        if left:
            log(f"  Painel esquerdo ({len(left)} itens):")
            for li in left:
                ob = " ⭐OB" if "OB" in li["text"].upper() else ""
                log(f"    {'✓' if li['visible'] else '·'} {li['text']!r:45} cls={li['cls']!r}{ob}")
        else:
            log("  (sem painel esquerdo visível)")

        # ── HTML do submenu ───────────────────────────────────────────────────
        html_sub = await pg.content()
        hp = SCREENSHOTS / f"s03_{safe_name}_dom.html"
        hp.write_text(html_sub, encoding="utf-8")
        log(f"  HTML: {hp.name} ({len(html_sub)} chars)")

        # ── Se é Execução Financeira: explorar cada item do painel ───────────
        if "Financeira" in sub_name and left:
            sep(f"4a. Explorando painel de '{sub_name}'")
            panel_item_names = [li["text"] for li in left
                                if li["visible"] and not li["disabled"]]
            log(f"  {len(panel_item_names)} itens ativos no painel")

            for panel_item in panel_item_names:
                pi_safe = panel_item[:18].replace(" ", "_").lower()
                log(f"\n  ── Painel item: {panel_item!r} ──")

                # Click panel item (pre-escape apostrophes outside the f-string)
                pi_safe_js = panel_item.replace("'", "\\'")
                clicked_pi = await pg.evaluate(f"""
                    () => {{
                        const sels = ['a.xg8', 'a[class*="xg"]', 'a'];
                        for (const sel of sels) {{
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
                await _explore_adf_screen(pg, panel_item,
                                          f"s04_{safe_name}_{pi_safe}")

    # ── 5. Deep-dive especial: OB ─────────────────────────────────────────────
    sep("5. Deep-dive: Execução Financeira → OB")

    # Navigate fresh to Execução Financeira
    r_exec2 = await _js_click_adf(pg, "a.xyo", "Execução")
    if not r_exec2:
        await pg.evaluate("""
            () => { for (const el of document.querySelectorAll('a.xyo'))
                if (el.textContent.trim().startsWith('Execu') && !el.className.includes('Disabled'))
                    { el.click(); return; } }
        """)
    await _adf_wait(pg, 6000)

    r_fin2 = await _js_click_adf(pg, "a.xgh", "Execução Financeira")
    if not r_fin2:
        await pg.evaluate("""
            () => { for (const el of document.querySelectorAll('a.xgh'))
                if (el.textContent.includes('Financeira') && !el.className.includes('Disabled'))
                    { el.click(); return; } }
        """)
    await _adf_wait(pg, 8000)

    # Click OB in left panel
    r_ob = await pg.evaluate("""
        () => {
            for (const sel of ['a.xg8', 'a[class*="xg"]', 'a', 'span', 'td', 'li']) {
                for (const el of document.querySelectorAll(sel)) {
                    const direct = [...el.childNodes]
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim()).filter(Boolean).join('');
                    if (direct.trim() === 'OB' && el.getBoundingClientRect().width > 0) {
                        el.click();
                        return el.tagName + '|' + el.className + '|text=' + direct;
                    }
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
                        except Exception:
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
