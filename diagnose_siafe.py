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


async def main_cdp():
    """Conecta ao Chrome já aberto com --remote-debugging-port=9222."""
    from playwright.async_api import async_playwright

    log(f"SIAFE2 Diagnóstico (modo CDP) — {datetime.now():%d/%m/%Y %H:%M}")
    log("Conectando ao Chrome local na porta 9222...")
    log("(Certifique-se que o Chrome foi aberto com --remote-debugging-port=9222)")

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
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

        # Mapear todo o menu e estrutura
        sep("Mapeamento completo do DOM")
        try:
            # Todos os inputs
            inputs = await target_page.query_selector_all("input, select, textarea")
            log(f"\n  {len(inputs)} inputs na página:")
            for inp in inputs:
                try:
                    id_ = await inp.get_attribute("id") or ""
                    nm  = await inp.get_attribute("name") or ""
                    tp  = await inp.get_attribute("type") or ""
                    ph  = await inp.get_attribute("placeholder") or ""
                    tag = await inp.evaluate("el => el.tagName.toLowerCase()")
                    log(f"    <{tag}> id={id_!r:35} name={nm!r:30} type={tp!r:10} placeholder={ph!r}")
                except Exception:
                    pass

            # Frames
            frames = target_page.frames
            log(f"\n  {len(frames)} frame(s):")
            for f in frames:
                log(f"    {f.url}")
                if "siafe" in f.url.lower() or "flexvision" in f.url.lower() or f.url != "about:blank":
                    try:
                        ftxt = await f.inner_text("body")
                        log(f"    → Texto ({len(ftxt)} chars): {ftxt[:500]}")
                        finputs = await f.query_selector_all("input, select, button")
                        log(f"    → {len(finputs)} elementos interativos")
                        for fi in finputs[:30]:
                            try:
                                fid = await fi.get_attribute("id") or ""
                                fnm = await fi.get_attribute("name") or ""
                                ftg = await fi.evaluate("el => el.tagName.toLowerCase()")
                                ftxt2 = (await fi.inner_text()).strip()[:40]
                                log(f"      <{ftg}> id={fid!r:35} name={fnm!r:30} text={ftxt2!r}")
                            except Exception:
                                pass
                    except Exception as e:
                        log(f"    [erro: {e}]")
        except Exception as e:
            log(f"  Erro no mapeamento: {e}")

        # Screenshot final
        sep("Screenshot final")
        await dump_page(target_page, "cdp_02_full_map")

        log("\n" + "="*60)
        log("  DIAGNÓSTICO CDP CONCLUÍDO")
        log(f"  Screenshots em: {SCREENSHOTS}/")
        log(f"  Relatório em:   {REPORT}")
        log("="*60)

    REPORT.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n✅ Relatório salvo em: {REPORT}")


if __name__ == "__main__":
    import sys
    if "--cdp" in sys.argv:
        asyncio.run(main_cdp())
    else:
        asyncio.run(main())
