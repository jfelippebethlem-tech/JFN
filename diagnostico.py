"""
diagnostico.py — O BOT APRENDE E TE INFORMA O QUE CORRIGIR.

Usa o Chrome JÁ ABERTO (porta 9222, logado no SIAFE2) para abrir as duas
páginas que precisamos dominar e DESPEJAR a estrutura real delas:

  1. SIAFE2 — tela de OB Orçamentária (Execução Financeira)
  2. IOERJ  — página oficial de busca do Diário Oficial (id=61)

Para cada página, captura e RELATA:
  - URL final, título
  - TODOS os botões/links clicáveis (texto + classe CSS + id)
  - TODOS os campos de formulário (nome, tipo, label)
  - Trecho do texto da página
  - Salva o HTML completo em data/diagnostics/*.html
  - Salva screenshot em data/diagnostics/*.png

O resumo é impresso no console de forma compacta — basta copiar e colar
de volta pro Claude, que aí corrige os seletores com base na REALIDADE,
não em chute.

Uso (Windows):
    iniciar.bat --diag
ou direto:
    python diagnostico.py
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    os.system("")  # habilita ANSI no CMD

CDP_URL = "http://127.0.0.1:9222"
DIAG_DIR = Path(__file__).parent / "data" / "diagnostics"

SIAFE_FINANCEIRA = (
    "https://siafe2.fazenda.rj.gov.br/Siafe/faces/execucao/financeira"
    "/execucaoFinanceiraMain.jsp"
)
IOERJ_BUSCA = "https://www.ioerj.com.br/portal/modules/content/index.php?id=61"

# Cores
G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"; B = "\033[96m"
BOLD = "\033[1m"; DIM = "\033[2m"; RST = "\033[0m"


# JS que extrai a estrutura interativa real da página ─────────────────────────
_JS_DUMP = r"""
() => {
    const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    };
    const labelOf = (el) => {
        if (el.id) {
            const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
            if (l) return l.textContent.trim();
        }
        let p = el.parentElement;
        for (let i = 0; i < 5 && p; i++, p = p.parentElement) {
            const l = p.querySelector('label, span.af_outputLabel, span.x18m, span.xom');
            if (l && l !== el) return l.textContent.trim();
        }
        return '';
    };

    // Clicáveis: a, button, inputs de ação
    const clickables = [];
    for (const el of document.querySelectorAll(
            'a, button, input[type="button"], input[type="submit"], [role="button"]')) {
        if (!visible(el)) continue;
        const txt = (el.textContent || el.value || '').trim().substring(0, 60);
        if (!txt && !el.title) continue;
        clickables.push({
            tag: el.tagName.toLowerCase(),
            text: txt || ('[title=' + el.title + ']'),
            cls: (el.className || '').toString().substring(0, 50),
            id: el.id || '',
            href: (el.tagName === 'A' ? (el.getAttribute('href') || '') : '').substring(0, 120),
        });
    }

    // Campos de entrada
    const inputs = [];
    for (const el of document.querySelectorAll('input, select, textarea')) {
        if (!visible(el)) continue;
        inputs.push({
            tag: el.tagName.toLowerCase(),
            type: el.type || '',
            name: el.name || '',
            id: el.id || '',
            placeholder: el.placeholder || '',
            label: labelOf(el).substring(0, 50),
        });
    }

    // Formulários
    const forms = [];
    for (const f of document.querySelectorAll('form')) {
        forms.push({
            action: f.action || '',
            method: (f.method || 'get').toLowerCase(),
            id: f.id || '',
            n_fields: f.querySelectorAll('input,select,textarea').length,
        });
    }

    return {
        url: location.href,
        title: document.title,
        clickables: clickables.slice(0, 120),
        inputs: inputs.slice(0, 80),
        forms: forms.slice(0, 10),
        bodyText: (document.body ? document.body.innerText : '').substring(0, 1500),
        htmlLen: document.documentElement.outerHTML.length,
    };
}
"""


# JS que lê as linhas de uma tabela ADF pelo fragmento do id ──────────────────
_JS_TABLE = r"""
(frag) => {
    let host = document.querySelector('[id*="' + frag + '"]');
    if (!host) return {found: false};
    // sobe até achar o container da tabela
    let table = host.closest('table') || host;
    const rows = [];
    for (const tr of table.querySelectorAll('tr')) {
        const cells = [...tr.querySelectorAll('td, th')]
            .map(c => c.textContent.trim()).filter(Boolean);
        if (cells.length) rows.push(cells);
    }
    return {found: true, n: rows.length, rows: rows.slice(0, 12)};
}
"""


async def _wait(pg, ms=8000):
    try:
        await pg.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        pass
    await asyncio.sleep(2)


async def _click_id_frag(pg, frag: str):
    """Clica no primeiro elemento cujo id contém `frag`."""
    return await pg.evaluate(
        """(frag) => {
            const el = document.querySelector('[id*="' + frag + '"]');
            if (el) { el.click(); return el.id || true; }
            return null;
        }""",
        frag,
    )


async def _click_text(pg, texto: str):
    """Clica no primeiro link/botão cujo texto bate exatamente. Retorna href/id."""
    return await pg.evaluate(
        """(t) => {
            for (const el of document.querySelectorAll('a, button, input[type=submit], input[type=button]')) {
                const s = (el.textContent || el.value || '').trim();
                if (s.toUpperCase() === t.toUpperCase()) {
                    const ret = el.getAttribute('href') || el.id || s;
                    el.click();
                    return ret;
                }
            }
            return null;
        }""",
        texto,
    )


async def _dump_tabela(pg, frag: str, nome: str):
    try:
        res = await pg.evaluate(_JS_TABLE, frag)
    except Exception as e:
        print(f"  {R}(erro lendo tabela {frag}: {e}){RST}")
        return
    if not res or not res.get("found"):
        print(f"\n  {Y}TABELA '{nome}' ({frag}): não encontrada na página{RST}")
        return
    print(f"\n  {BOLD}{Y}TABELA '{nome}' — {res['n']} linhas (primeiras 12):{RST}")
    for row in res.get("rows", []):
        print(f"    {DIM}| {' | '.join(str(c)[:22] for c in row[:9])}{RST}")


async def _dismiss_dialogs(pg):
    """Fecha pop-ups do SIAFE clicando OK (mensagem do administrador, etc.)."""
    for _ in range(5):
        r = await pg.evaluate(r"""
            () => {
                const ok = document.getElementById('myBtnOk');
                if (ok && ok.getBoundingClientRect().width > 0) { ok.click(); return 'myBtnOk'; }
                for (const el of document.querySelectorAll('a.x7j, a.xg2, button')) {
                    const t = el.textContent.trim().toLowerCase();
                    const r = el.getBoundingClientRect();
                    if ((t === 'ok' || t === 'sim' || t === 'fechar') && r.width > 0
                            && !el.className.includes('p_AFDisabled')) {
                        el.click(); return el.id || t;
                    }
                }
                return null;
            }
        """)
        if r:
            await asyncio.sleep(1.5)
        else:
            break


def _print_dump(nome: str, dump: dict):
    print(f"\n{BOLD}{B}{'═'*72}{RST}")
    print(f"{BOLD}{B}  {nome}{RST}")
    print(f"{BOLD}{B}{'═'*72}{RST}")
    print(f"  {BOLD}URL final:{RST} {dump['url']}")
    print(f"  {BOLD}Título:{RST}    {dump['title']}")
    print(f"  {BOLD}HTML:{RST}      {dump['htmlLen']} bytes")

    forms = dump.get("forms", [])
    if forms:
        print(f"\n  {BOLD}{Y}FORMULÁRIOS ({len(forms)}):{RST}")
        for f in forms:
            print(f"    • action={f['action'][:70]}")
            print(f"      method={f['method']}  id={f['id']}  campos={f['n_fields']}")

    inputs = dump.get("inputs", [])
    if inputs:
        print(f"\n  {BOLD}{Y}CAMPOS DE ENTRADA ({len(inputs)}):{RST}")
        for i in inputs:
            print(f"    • <{i['tag']} type={i['type']}> name='{i['name']}' "
                  f"id='{i['id']}' label='{i['label']}' ph='{i['placeholder']}'")

    clk = dump.get("clickables", [])
    if clk:
        print(f"\n  {BOLD}{Y}CLICÁVEIS ({len(clk)}):{RST}")
        for c in clk:
            href = f"  href='{c['href']}'" if c.get("href") else ""
            print(f"    • [{c['tag']}] \"{c['text']}\"  cls='{c['cls']}'  id='{c['id']}'{href}")

    bt = dump.get("bodyText", "").strip()
    if bt:
        print(f"\n  {BOLD}{Y}TEXTO DA PÁGINA (início):{RST}")
        for line in bt.splitlines()[:25]:
            if line.strip():
                print(f"    {DIM}{line.strip()[:90]}{RST}")


async def _capturar(pg, nome_arquivo: str, dump: dict):
    DIAG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = DIAG_DIR / f"{nome_arquivo}_{ts}"
    try:
        html = await pg.content()
        base.with_suffix(".html").write_text(html, encoding="utf-8")
    except Exception as e:
        print(f"  {R}(não salvou HTML: {e}){RST}")
    try:
        await pg.screenshot(path=str(base.with_suffix(".png")), full_page=True)
    except Exception:
        pass
    try:
        base.with_suffix(".json").write_text(
            json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass
    print(f"  {G}✓ Salvo: {base}.html / .png / .json{RST}")


async def main():
    from playwright.async_api import async_playwright

    print(f"{BOLD}{B}")
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║   DIAGNÓSTICO — o bot lê as páginas e te relata      ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print(RST)

    p = await async_playwright().start()
    try:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
    except Exception as e:
        print(f"{R}  ERRO: não conectou ao Chrome em {CDP_URL}{RST}")
        print(f"  {DIM}{e}{RST}")
        print(f"\n  Abra o Chrome assim e tente de novo:")
        print(f"  {B}chrome.exe --remote-debugging-port=9222{RST}")
        await p.stop()
        return

    if not browser.contexts:
        print(f"{R}  Nenhum contexto no Chrome.{RST}")
        await p.stop()
        return
    ctx = browser.contexts[0]

    # ── 1. SIAFE2 ────────────────────────────────────────────────────────────
    print(f"\n{BOLD}{Y}[1/2] Lendo o SIAFE2 (tela de Execução Financeira / OB)...{RST}")
    siafe_page = None
    for pg in ctx.pages:
        if "siafe2.fazenda" in pg.url.lower() and "flexvision" not in pg.url.lower():
            siafe_page = pg
            break
    if not siafe_page:
        # Usa a primeira aba e tenta navegar
        siafe_page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    try:
        await _dismiss_dialogs(siafe_page)
        cur = siafe_page.url.lower()
        if "execucaofinanceira" not in cur and "ordembancaria" not in cur:
            print(f"  {DIM}Navegando para Execução Financeira...{RST}")
            try:
                await siafe_page.goto(SIAFE_FINANCEIRA, wait_until="networkidle", timeout=25000)
            except Exception as e:
                print(f"  {R}goto falhou: {e}{RST}")
            await _wait(siafe_page)
            await _dismiss_dialogs(siafe_page)

        dump = await siafe_page.evaluate(_JS_DUMP)
        _print_dump("SIAFE2 — Execução Financeira / OB", dump)
        await _capturar(siafe_page, "siafe", dump)

        # Lê a tabela de OBs que já está na tela
        await _dump_tabela(siafe_page, "tblOBOrcamentaria", "OB Orçamentária")

        # Abre o painel de filtro (disclosure "Mostrar este painel") e re-dump
        print(f"\n  {DIM}Abrindo painel de filtro (sdtFilter)...{RST}")
        clicked = await _click_id_frag(siafe_page, "sdtFilter")
        if clicked:
            await _wait(siafe_page, 6000)
            await _dismiss_dialogs(siafe_page)
            dump2 = await siafe_page.evaluate(_JS_DUMP)
            print(f"\n  {BOLD}{B}>>> APÓS ABRIR O PAINEL DE FILTRO:{RST}")
            _print_dump("SIAFE2 — Filtro de OB (painel aberto)", dump2)
            await _capturar(siafe_page, "siafe_filtro", dump2)
        else:
            print(f"  {Y}(não achei o disclosure sdtFilter para abrir){RST}")
    except Exception as e:
        print(f"  {R}Erro ao ler SIAFE2: {type(e).__name__}: {e}{RST}")

    # ── 2. IOERJ (DOERJ) ─────────────────────────────────────────────────────
    print(f"\n{BOLD}{Y}[2/2] Lendo o IOERJ no MESMO Chrome (sem 403)...{RST}")
    ioerj_page = await ctx.new_page()
    try:
        try:
            await ioerj_page.goto(IOERJ_BUSCA, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"  {R}goto IOERJ falhou: {e}{RST}")
        await _wait(ioerj_page, 6000)

        dump = await ioerj_page.evaluate(_JS_DUMP)
        _print_dump("IOERJ — Busca DOERJ (id=61)", dump)
        await _capturar(ioerj_page, "ioerj", dump)

        # Clica "BUSCA POR DATA" para revelar o formulário de busca por data
        print(f"\n  {DIM}Clicando 'BUSCA POR DATA'...{RST}")
        ret = await _click_text(ioerj_page, "BUSCA POR DATA")
        if ret:
            print(f"  {DIM}-> {ret}{RST}")
            await _wait(ioerj_page, 8000)
            dump2 = await ioerj_page.evaluate(_JS_DUMP)
            print(f"\n  {BOLD}{B}>>> PÁGINA DE BUSCA POR DATA:{RST}")
            _print_dump("IOERJ — Busca por Data", dump2)
            await _capturar(ioerj_page, "ioerj_data", dump2)
        else:
            print(f"  {Y}(não achei o botão 'BUSCA POR DATA'){RST}")
    except Exception as e:
        print(f"  {R}Erro ao ler IOERJ: {type(e).__name__}: {e}{RST}")
    finally:
        try:
            await ioerj_page.close()
        except Exception:
            pass

    await p.stop()

    print(f"\n{BOLD}{G}{'═'*72}{RST}")
    print(f"{BOLD}{G}  PRONTO. Copie TODO o texto acima e cole de volta pro Claude.{RST}")
    print(f"{BOLD}{G}  (Os arquivos .html/.png/.json estão em data/diagnostics/){RST}")
    print(f"{BOLD}{G}{'═'*72}{RST}\n")


if __name__ == "__main__":
    asyncio.run(main())
