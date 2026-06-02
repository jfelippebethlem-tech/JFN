"""
SIAFE2 OB Orçamentária — coletor diário.

Conecta no Chrome já aberto (CDP porta 9222), navega até a tela de
OB Orçamentária (Execução > Execução Financeira > OB Orçamentária) e lê
DIRETO a tabela de OBs que já vem carregada na tela.

Estrutura real da tabela (confirmada por diagnóstico em 01/06/2026):
    Número | UG Emitente | UG Pagadora | Data Emissão | Status |
    Tipo | Finalidade | Tipo de OB | NL
Ex.: 2026OB00571 | 300100 | 300100 | 01/06/2026 | Contabilizado |
     12 | 6 | Orçamentária | 2026NL00338

A tela é uma LISTA (não há botão "Consultar"); os registros do dia já
aparecem. Lemos a grade `pt1:tblOBOrcamentaria` diretamente.

Uso (standalone):
    python -m compliance_agent.collectors.siafe_ob
"""

import asyncio
import json
import re
from datetime import date, datetime
from pathlib import Path

from compliance_agent.database.models import (
    OrdemBancaria, SessaoAuditoria, get_session, init_db
)

CDP_URL = "http://127.0.0.1:9222"

# Navegar para a página-mãe inicializa o contexto ADF corretamente.
# NUNCA fazer goto direto na URL da OB (causa BeanELResolver crash).
_SIAFE_FINANCEIRA = (
    "https://siafe2.fazenda.rj.gov.br/Siafe/faces/execucao/financeira"
    "/execucaoFinanceiraMain.jsp"
)
_SIAFE_HOME = "https://siafe2.fazenda.rj.gov.br/Siafe/"

_RE_OB = re.compile(r"^\d{4}OB\d+")

# JS que lê a grade de OBs já carregada na tela ───────────────────────────────
_JS_READ_OB_TABLE = r"""
() => {
    const host = document.querySelector('[id*="tblOBOrcamentaria"]');
    if (!host) return {found: false, header: [], rows: []};
    const table = host.closest('table') || host;

    let header = [];
    const rows = [];
    for (const tr of table.querySelectorAll('tr')) {
        const cells = [...tr.querySelectorAll('td, th')]
            .map(c => c.textContent.trim())
            .filter(t => t.length > 0);
        if (!cells.length) continue;
        // linha de cabeçalho
        if (cells.includes('Número') && cells.some(c => c.indexOf('Data') >= 0)) {
            header = cells;
            continue;
        }
        // linha de dados: começa com número de OB (ex.: 2026OB00571)
        if (/^\d{4}OB\d+/.test(cells[0])) {
            rows.push(cells);
        }
    }
    return {found: true, header: header, rows: rows};
}
"""


async def _adf_wait(pg, timeout: int = 12000):
    try:
        await pg.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    await asyncio.sleep(1.5)


async def _dismiss_dialogs(page, max_iter: int = 6) -> list[str]:
    """Fecha pop-ups (mensagem do administrador, etc.) clicando OK."""
    dismissed = []
    for _ in range(max_iter):
        result = await page.evaluate(r"""
            () => {
                const ok = document.getElementById('myBtnOk');
                if (ok && ok.getBoundingClientRect().width > 0) {
                    ok.click(); return 'myBtnOk';
                }
                for (const el of document.querySelectorAll('a.x7j, a.xg2, button')) {
                    const t = el.textContent.trim().toLowerCase();
                    const r = el.getBoundingClientRect();
                    if ((t === 'ok' || t === 'sim' || t === 'fechar') && r.width > 0
                            && r.height > 0 && !el.className.includes('p_AFDisabled')) {
                        el.click(); return el.id || t;
                    }
                }
                return null;
            }
        """)
        if result:
            dismissed.append(result)
            await asyncio.sleep(1.5)
        else:
            break
    return dismissed


_SIAFE_LOGIN = "https://siafe2.fazenda.rj.gov.br/Siafe/faces/autenticacao/autenticacao.xhtml"

# JS que lê campos de login presentes na página
_JS_CHECK_LOGIN = r"""
() => {
    const u = document.querySelector('input[id*="usuario"], input[id*="user"], input[name*="user"], input[type="text"]');
    const p = document.querySelector('input[type="password"]');
    return !!(u && p && u.getBoundingClientRect().width > 0);
}
"""

_JS_DO_LOGIN = r"""
(usuario, senha) => {
    const u = document.querySelector('input[id*="usuario"], input[id*="user"], input[name*="user"], input[type="text"]');
    const p = document.querySelector('input[type="password"]');
    const btn = document.querySelector('button[id*="login"], input[type="submit"], button[type="submit"], a.x7j, a.xg2');
    if (!u || !p) return 'inputs não encontrados';
    u.value = usuario;
    p.value = senha;
    u.dispatchEvent(new Event('change', {bubbles: true}));
    p.dispatchEvent(new Event('change', {bubbles: true}));
    if (btn) { btn.click(); return 'login clicado'; }
    return 'botão não encontrado';
}
"""


async def _esta_na_tela_login(page) -> bool:
    try:
        return bool(await page.evaluate(_JS_CHECK_LOGIN))
    except Exception:
        return False


async def _fazer_login(page) -> bool:
    """Tenta fazer login com as credenciais do .env / variáveis de ambiente."""
    import os
    usuario = os.environ.get("SIAFE_USER", "")
    senha = os.environ.get("SIAFE_PASS", "")
    if not usuario or not senha:
        return False

    try:
        await page.goto(_SIAFE_LOGIN, wait_until="networkidle", timeout=20000)
        await asyncio.sleep(2)
        await _dismiss_dialogs(page)

        if not await _esta_na_tela_login(page):
            return False

        result = await page.evaluate(_JS_DO_LOGIN, usuario, senha)
        await _adf_wait(page, 20000)
        await _dismiss_dialogs(page)

        cur = page.url.lower()
        logged_in = "login" not in cur and "autenticacao" not in cur and "siafe2.fazenda" in cur
        print(f"[SIAFE2] Login {'OK' if logged_in else 'FALHOU'}: {result} → {page.url[:80]}")
        return logged_in
    except Exception as exc:
        print(f"[SIAFE2] Erro no login: {exc}")
        return False


async def _navigate_to_ob(page) -> bool:
    """
    Garante que estamos na tela de OB Orçamentária.

    Navega via execucaoFinanceiraMain.jsp (inicializa o contexto ADF) e
    depois clica no menu 'OB Orçamentária'. Detecta sessão expirada e
    re-loga automaticamente. NUNCA usa goto direto na URL da OB (BeanELResolver crash).
    """
    if "ordembancariaorcamentaria" in page.url.lower():
        await _dismiss_dialogs(page)
        return True

    cur = page.url.lower()

    # Detecta sessão expirada (tela de login ou página de erro/redirecionamento)
    sessao_expirada = (
        "login" in cur
        or "autenticacao" in cur
        or "erro" in cur
        or "error" in cur
        or await _esta_na_tela_login(page)
    )

    if sessao_expirada:
        print("[SIAFE2] Sessão expirada — tentando re-login automático...")
        if not await _fazer_login(page):
            return False
        cur = page.url.lower()

    # Se não está no SIAFE2 ainda, navega para lá
    if "siafe2.fazenda" not in cur:
        try:
            await page.goto(_SIAFE_HOME, wait_until="networkidle", timeout=20000)
            await asyncio.sleep(3)
            await _dismiss_dialogs(page)
            cur = page.url.lower()
            if "login" in cur or "autenticacao" in cur or await _esta_na_tela_login(page):
                if not await _fazer_login(page):
                    return False
        except Exception:
            pass

    # Navega para a seção de Execução Financeira se ainda não está lá
    if "execucaofinanceira" not in page.url.lower() and "ordembancaria" not in page.url.lower():
        try:
            await page.goto(_SIAFE_FINANCEIRA, wait_until="networkidle", timeout=20000)
            await asyncio.sleep(3)
            await _dismiss_dialogs(page)
            # Re-check login after navigation
            if "login" in page.url.lower() or "autenticacao" in page.url.lower():
                if not await _fazer_login(page):
                    return False
                await page.goto(_SIAFE_FINANCEIRA, wait_until="networkidle", timeout=20000)
                await asyncio.sleep(3)
                await _dismiss_dialogs(page)
        except Exception:
            pass

    if "ordembancariaorcamentaria" in page.url.lower():
        return True

    # Aguarda o menu ADF carregar (a.xgg pode demorar)
    try:
        await page.wait_for_selector("a.xgg", timeout=10000)
    except Exception:
        pass
    await asyncio.sleep(2)

    # Tenta clicar em 'OB Orçamentária' — busca progressivamente mais ampla
    for attempt in range(3):
        clicked = await page.evaluate(r"""
            () => {
                // Busca em seletores do mais específico ao mais amplo
                const selectorGroups = [
                    'a.xgg',
                    'a.xg2',
                    'a[class*="xg"]',
                    'a, span, li a, td a',
                ];
                for (const sel of selectorGroups) {
                    for (const el of document.querySelectorAll(sel)) {
                        const t = el.textContent.trim();
                        const r = el.getBoundingClientRect();
                        if (r.width <= 0) continue;
                        if (el.className && el.className.includes('p_AFDisabled')) continue;
                        if (t === 'OB Orçamentária'
                            || t.startsWith('OB Or')
                            || (t.includes('Orçament') && t.includes('OB'))
                            || t === 'OB Orcamentaria') {
                            el.click();
                            return 'clicked:' + t;
                        }
                    }
                }
                // Não encontrou — devolve lista dos a.xgg visíveis para debug
                const found = [];
                for (const el of document.querySelectorAll('a.xgg, a.xg2, a[class*="xg"]')) {
                    const t = el.textContent.trim();
                    const r = el.getBoundingClientRect();
                    if (t && r.width > 0) found.push(t.slice(0, 50));
                }
                return 'NOT_FOUND|' + found.slice(0, 25).join('||');
            }
        """)

        if clicked and not clicked.startswith("NOT_FOUND"):
            await _adf_wait(page, 15000)
            await _dismiss_dialogs(page)
            if "ordembancariaorcamentaria" in page.url.lower():
                return True
        else:
            if attempt == 0 and clicked:
                # Log visible menu items on first failure for diagnostics
                print(f"[SIAFE2] Menu items visíveis: {clicked}")
            await asyncio.sleep(3)

    return "ordembancariaorcamentaria" in page.url.lower()


def _parse_money(s: str):
    """Converte '1.234,56' -> 1234.56. Retorna None se não numérico."""
    try:
        clean = re.sub(r"[^\d,.-]", "", str(s)).replace(".", "").replace(",", ".")
        return float(clean) if clean else None
    except (ValueError, TypeError):
        return None


def _parse_date_br(s: str):
    """Converte 'dd/mm/yyyy' -> date. Retorna None se inválido."""
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y").date()
    except (ValueError, TypeError, AttributeError):
        return None


async def collect_ob_day(target_date: date | None = None, max_rows: int = 1000) -> dict:
    """
    Conecta no Chrome via CDP e lê a tabela de OBs já carregada na tela.
    Retorna dict com: date, records, rows, header, errors.
    """
    from playwright.async_api import async_playwright

    target_date = target_date or date.today()
    summary = {
        "date": target_date.isoformat(),
        "records": 0,
        "rows": [],
        "header": [],
        "errors": [],
    }

    p = await async_playwright().start()
    browser = None
    last_err = None
    for attempt in range(3):
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL, timeout=60000)
            break
        except Exception as e:
            last_err = e
            if attempt < 2:
                await asyncio.sleep(5)
    if browser is None:
        summary["errors"].append(f"CDP connect falhou: {last_err}")
        await p.stop()
        return summary

    try:
        # Localiza a aba do SIAFE2
        page = None
        for ctx in browser.contexts:
            for pg in ctx.pages:
                u = pg.url.lower()
                if "siafe2.fazenda" in u and "flexvision" not in u:
                    page = pg
                    break
            if page:
                break
        if not page and browser.contexts and browser.contexts[0].pages:
            page = browser.contexts[0].pages[0]
        if not page:
            summary["errors"].append("Nenhuma aba encontrada no Chrome")
            return summary

        await _dismiss_dialogs(page)

        if not await _navigate_to_ob(page):
            summary["errors"].append(f"Não chegou na tela de OB — URL: {page.url}")
            return summary

        # Lê a grade direto
        result = await page.evaluate(_JS_READ_OB_TABLE)
        if not result.get("found"):
            summary["errors"].append("Tabela tblOBOrcamentaria não encontrada na tela")
            return summary

        summary["header"] = result.get("header", [])
        summary["rows"] = result.get("rows", [])[:max_rows]
        summary["records"] = len(summary["rows"])

        if summary["records"] == 0:
            body = await page.inner_text("body")
            if "limite de 1000" in body.lower() or "nenhum registro" in body.lower():
                pass  # tabela vazia é resultado válido

    except Exception as e:
        summary["errors"].append(f"Erro de coleta: {type(e).__name__}: {e}")
    finally:
        try:
            await p.stop()
        except Exception:
            pass

    return summary


# Mapa de nomes de coluna -> índice, a partir do header lido
def _col_index(header: list[str]) -> dict:
    idx = {}
    for i, h in enumerate(header):
        idx[h.strip().lower()] = i
    return idx


def save_ob_records(session, summary: dict) -> int:
    """Insere/atualiza OBs do summary no banco. Retorna quantas salvou."""
    header = summary.get("header", [])
    idx = _col_index(header)
    saved = 0

    def cell(row, *names):
        for n in names:
            j = idx.get(n)
            if j is not None and j < len(row):
                return row[j]
        return None

    for row in summary.get("rows", []):
        numero = cell(row, "número", "numero") or (row[0] if row else "")
        if not numero:
            continue

        data_str = cell(row, "data emissão", "data emissao", "data")
        data_emissao = _parse_date_br(data_str) or date.fromisoformat(summary["date"])
        ug_emit = cell(row, "ug emitente", "ug")
        status = cell(row, "status")
        tipo_ob = cell(row, "tipo de ob")
        nl = cell(row, "nl")

        raw = {header[i] if i < len(header) else f"col{i}": v
               for i, v in enumerate(row)}

        existing = session.query(OrdemBancaria).filter_by(
            numero_ob=str(numero), data_emissao=data_emissao
        ).first()

        if existing:
            existing.status = status or existing.status
            existing.raw_json = json.dumps(raw, ensure_ascii=False)
            existing.updated_at = datetime.utcnow()
        else:
            ob = OrdemBancaria(
                numero_ob=str(numero),
                data_emissao=data_emissao,
                exercicio=data_emissao.year,
                ug_codigo=str(ug_emit) if ug_emit else None,
                status=str(status) if status else None,
                tipo_ob=str(tipo_ob) if tipo_ob else None,
                observacao=f"NL={nl}" if nl else None,
                raw_json=json.dumps(raw, ensure_ascii=False),
            )
            session.add(ob)
        saved += 1

    session.commit()
    return saved


_JS_OPEN_FIRST_OB = r"""
(numero) => {
    // Find the row by OB number and click Visualizar on it
    for (const el of document.querySelectorAll('a.x12k, a.xg2, a.x7j, td')) {
        const t = el.textContent.trim();
        if (t === numero) {
            // select the row first
            el.click();
            return 'selected row: ' + numero;
        }
    }
    return null;
}
"""

_JS_CLICK_VISUALIZAR = r"""
() => {
    for (const el of document.querySelectorAll('a, button, input[type="button"]')) {
        const t = el.textContent.trim().toLowerCase();
        if ((t === 'visualizar' || t === 'detalhar' || t === 'ver' || t === 'editar')
                && el.getBoundingClientRect().width > 0
                && !el.className.includes('p_AFDisabled')) {
            el.click();
            return 'clicked: ' + el.textContent.trim();
        }
    }
    return null;
}
"""

_JS_CLICK_RETORNAR = r"""
() => {
    for (const el of document.querySelectorAll('a.x12k, a.xg2, a, button')) {
        const t = el.textContent.trim().toLowerCase();
        if ((t === 'retornar' || t === 'voltar' || t === 'cancelar')
                && el.getBoundingClientRect().width > 0) {
            el.click();
            return 'clicked: ' + el.textContent.trim();
        }
    }
    return null;
}
"""

_JS_READ_DETAIL_FIELDS = r"""
() => {
    const clone = document.body.cloneNode(true);
    // Remove noisy dropdowns and menus
    for (const sel of ['select', 'script', 'style', '[id*="selUg"]', '[id*="iTxtCad"]',
                        '[id*="pt_np"]', '[id*="pt_rhcl"]', '[id*="pt_bc"]']) {
        clone.querySelectorAll(sel).forEach(n => n.remove());
    }
    // Collect label->value pairs from visible inputs
    function labelOf(el) {
        if (el.labels && el.labels.length > 0) return el.labels[0].textContent.trim();
        const lbl = document.querySelector('label[for="' + el.id + '"]');
        if (lbl) return lbl.textContent.trim();
        const prev = el.previousElementSibling;
        if (prev && prev.tagName === 'LABEL') return prev.textContent.trim();
        return '';
    }
    const fields = {};
    for (const el of document.querySelectorAll('input, textarea')) {
        const val = (el.value || '').trim();
        if (!val) continue;
        const lbl = labelOf(el).replace(/:$/, '').trim();
        if (lbl) fields[lbl] = val;
        else if (el.id) fields[el.id] = val;
    }
    // Also read visible spans/labels that look like values
    const bodyText = clone.body ? clone.body.innerText : '';
    return {fields, bodyText: bodyText.substring(0, 4000)};
}
"""

_JS_CLICK_TAB = r"""
(tabText) => {
    for (const el of document.querySelectorAll('a.xyp, a[role="tab"], li[role="tab"], .x1b4')) {
        const t = el.textContent.trim();
        if (t === tabText || t.startsWith(tabText)) {
            el.click();
            return 'clicked tab: ' + t;
        }
    }
    return null;
}
"""


def _extract_ob_fields(detail: dict) -> dict:
    """Extract favorecido, valor, processo from raw detail fields."""
    fields = detail.get("fields", {})
    body = detail.get("bodyText", "")

    favorecido_nome = None
    favorecido_cpf = None
    valor = None
    numero_processo = None

    for k, v in fields.items():
        kl = k.lower()
        if "favorecido" in kl or "beneficiário" in kl or "credor" in kl:
            if not favorecido_nome:
                favorecido_nome = v
        elif "cpf" in kl or "cnpj" in kl:
            if not favorecido_cpf:
                favorecido_cpf = re.sub(r"\D", "", v)[:14]
        elif "valor" in kl and ("total" in kl or "pag" in kl or "ob" in kl or favorecido_nome):
            if not valor:
                valor = _parse_money(v)
        elif "processo" in kl or "sei" in kl:
            if not numero_processo:
                numero_processo = v.strip()

    # Fallback: regex on bodyText
    if not favorecido_nome:
        m = re.search(r"Favorecido[:\s]+([A-ZÁÀÉÍÓÚÃÕÂÊÎÔÛÇ][^\n]{4,80})", body)
        if m:
            favorecido_nome = m.group(1).strip()
    if not numero_processo:
        m = re.search(r"SEI[:\s\-]+(\d[\d.\-/]+\d)", body)
        if not m:
            m = re.search(r"Processo[:\s]+([A-Z\d][\d.\-/]+\d)", body)
        if m:
            numero_processo = m.group(1).strip()
    if not valor:
        for match in re.finditer(r"R\$\s*([\d.]+,\d{2})", body):
            v = _parse_money(match.group(1))
            if v and v > 0:
                valor = v
                break

    return {
        "favorecido_nome": favorecido_nome,
        "favorecido_cpf": favorecido_cpf,
        "valor": valor,
        "numero_processo": numero_processo,
    }


async def _check_session_and_recover(page) -> bool:
    """
    Verifica se a sessão SIAFE2 ainda está ativa.
    Se não, faz re-login e volta para a tela de OBs.
    Retorna True se estamos na tela de OBs, False se falhou.
    """
    cur = page.url.lower()
    session_ok = (
        "siafe2.fazenda" in cur
        and "login" not in cur
        and "autenticacao" not in cur
        and not await _esta_na_tela_login(page)
    )
    if session_ok:
        return True

    print("[SIAFE2] Sessão expirou durante coleta de detalhes — re-logando...")
    if not await _fazer_login(page):
        print("[SIAFE2] Re-login falhou.")
        return False

    # Volta para a tela de OBs
    return await _navigate_to_ob(page)


async def collect_ob_details(page, ob_numbers: list[str]) -> dict[str, dict]:
    """
    For each OB number in the list, click it, read detail tabs,
    extract favorecido/valor/processo, click Retornar.
    Detecta sessão expirada a cada 10 OBs e re-loga automaticamente.
    Returns dict {numero_ob: {favorecido_nome, favorecido_cpf, valor, numero_processo}}.
    """
    results = {}
    consecutive_failures = 0

    for i, numero in enumerate(ob_numbers):
        # Verifica sessão a cada 10 OBs ou após 3 falhas consecutivas
        if i % 10 == 0 or consecutive_failures >= 3:
            if not await _check_session_and_recover(page):
                # Marca o restante como erro e sai
                for n in ob_numbers[i:]:
                    results[n] = {"error": "sessão expirada, re-login falhou"}
                break
            consecutive_failures = 0

        try:
            # Click on the OB row to select it
            sel_result = await page.evaluate(f"""
                () => {{
                    for (const el of document.querySelectorAll('td, span')) {{
                        const t = el.textContent.trim();
                        if (t === '{numero}') {{
                            const row = el.closest('tr');
                            if (row) row.click();
                            el.click();
                            return 'selected: ' + t;
                        }}
                    }}
                    return null;
                }}
            """)
            if sel_result:
                await asyncio.sleep(0.5)

            # Click Visualizar button
            viz = await page.evaluate(_JS_CLICK_VISUALIZAR)
            if not viz:
                results[numero] = {"error": "Visualizar not found"}
                consecutive_failures += 1
                continue

            consecutive_failures = 0
            await _adf_wait(page, 12000)
            await _dismiss_dialogs(page)

            # Read Detalhamento tab (default)
            detail = await page.evaluate(_JS_READ_DETAIL_FIELDS)
            extracted = _extract_ob_fields(detail)

            # Click Processo tab for SEI number
            if not extracted.get("numero_processo"):
                tab_clicked = await page.evaluate(_JS_CLICK_TAB, "Processo")
                if tab_clicked:
                    await asyncio.sleep(1.5)
                    proc_detail = await page.evaluate(_JS_READ_DETAIL_FIELDS)
                    proc_extra = _extract_ob_fields(proc_detail)
                    if proc_extra.get("numero_processo"):
                        extracted["numero_processo"] = proc_extra["numero_processo"]

            results[numero] = extracted

            # Return to list
            ret = await page.evaluate(_JS_CLICK_RETORNAR)
            await _adf_wait(page, 10000)
            await _dismiss_dialogs(page)
            if not ret:
                await page.go_back()
                await _adf_wait(page, 10000)
                await _dismiss_dialogs(page)

        except Exception as exc:
            results[numero] = {"error": str(exc)}
            consecutive_failures += 1
            try:
                await page.evaluate(_JS_CLICK_RETORNAR)
                await _adf_wait(page, 8000)
            except Exception:
                pass

    return results


async def run_daily_collection(
    target_date: date | None = None,
    collect_details: bool = True,
    max_details: int = 200,
) -> dict:
    """
    Pipeline completo: coleta lista de OBs + detalhes + persiste no banco.

    collect_details=True abre cada OB para extrair favorecido/valor/processo.
    max_details limita quantas OBs terão detalhes coletados (segurança de tempo).
    """
    from playwright.async_api import async_playwright

    init_db()
    session = get_session()
    target_date = target_date or date.today()

    result = {
        "date": target_date.isoformat(),
        "records_fetched": 0,
        "records_saved": 0,
        "details_collected": 0,
        "errors": [],
    }

    p = await async_playwright().start()
    browser = None
    try:
        # Tenta conectar ao Chrome com retry (3×, timeout 60s cada)
        last_err = None
        for attempt in range(3):
            try:
                browser = await p.chromium.connect_over_cdp(CDP_URL, timeout=60000)
                break
            except Exception as e:
                last_err = e
                if attempt < 2:
                    await asyncio.sleep(5)
        if browser is None:
            result["errors"].append(f"CDP connect falhou após 3 tentativas: {last_err}")
        else:
            # Localiza aba do SIAFE2
            page = None
            for ctx in browser.contexts:
                for pg in ctx.pages:
                    u = pg.url.lower()
                    if "siafe2.fazenda" in u and "flexvision" not in u:
                        page = pg
                        break
                if page:
                    break
            if not page and browser.contexts and browser.contexts[0].pages:
                page = browser.contexts[0].pages[0]

            if not page:
                result["errors"].append("Nenhuma aba encontrada no Chrome")
            else:
                await _dismiss_dialogs(page)

                if not await _navigate_to_ob(page):
                    result["errors"].append(f"Não chegou na tela de OB — URL: {page.url}")
                else:
                    # 1. Lê a tabela de OBs
                    raw = await page.evaluate(_JS_READ_OB_TABLE)
                    if not raw.get("found"):
                        result["errors"].append(
                            "Tabela tblOBOrcamentaria não encontrada (não chegou na grade de OB)"
                        )
                    else:
                        header = raw.get("header", [])
                        rows = raw.get("rows", [])[:1000]
                        result["records_fetched"] = len(rows)
                        # Observabilidade: grade encontrada porém vazia é diferente de
                        # tabela ausente. Quase sempre significa que o filtro de data/UG
                        # não foi aplicado, ou que não há OB para a data (fim de semana).
                        if len(rows) == 0:
                            result["errors"].append(
                                "Grade de OB encontrada porém VAZIA — aplique filtro de "
                                "data/UG na tela do SIAFE ou verifique se há OB nesta data "
                                "(fim de semana/feriado costuma ter zero)."
                            )

                        # 2. Salva lista no banco
                        summary = {
                            "date": target_date.isoformat(),
                            "records": len(rows),
                            "rows": rows,
                            "header": header,
                            "errors": [],
                        }
                        try:
                            result["records_saved"] = save_ob_records(session, summary)
                        except Exception as e:
                            result["errors"].append(f"Erro ao salvar lista: {e}")

                        # 3. Coleta detalhes de cada OB
                        if collect_details and rows:
                            idx = _col_index(header)
                            num_col = idx.get("número", idx.get("numero", 0))
                            ob_numbers = [
                                row[num_col] for row in rows
                                if row and len(row) > num_col and row[num_col]
                            ][:max_details]

                            try:
                                details = await collect_ob_details(page, ob_numbers)
                                n_det = 0
                                for numero, det in details.items():
                                    if "error" in det:
                                        continue
                                    ob = session.query(OrdemBancaria).filter_by(
                                        numero_ob=numero, data_emissao=target_date
                                    ).first()
                                    if ob:
                                        if det.get("favorecido_nome"):
                                            ob.favorecido_nome = det["favorecido_nome"]
                                        if det.get("favorecido_cpf"):
                                            ob.favorecido_cpf = det["favorecido_cpf"]
                                        if det.get("valor"):
                                            ob.valor = det["valor"]
                                        if det.get("numero_processo"):
                                            ob.numero_processo = det["numero_processo"]
                                            ob.numero_sei = det["numero_processo"]
                                        ob.updated_at = datetime.utcnow()
                                        n_det += 1
                                session.commit()
                                result["details_collected"] = n_det
                            except Exception as e:
                                result["errors"].append(f"Erro ao coletar detalhes: {e}")

    except Exception as e:
        result["errors"].append(f"Erro inesperado: {e}")
    finally:
        try:
            await p.stop()
        except Exception:
            pass
        try:
            session.close()
        except Exception:
            pass

    sessao = SessaoAuditoria(
        data_sessao=target_date,
        tipo="siafe_ob",
        status="ok" if not result["errors"] else ("parcial" if result["records_saved"] else "erro"),
        registros=result["records_saved"],
        resumo=json.dumps({
            "date": result["date"],
            "records_fetched": result["records_fetched"],
            "records_saved": result["records_saved"],
            "details_collected": result["details_collected"],
        }, ensure_ascii=False),
        detalhes=json.dumps(result.get("errors", []), ensure_ascii=False)
        if result["errors"] else None,
    )
    db_sess = get_session()
    db_sess.add(sessao)
    db_sess.commit()
    db_sess.close()

    return result


if __name__ == "__main__":
    result = asyncio.run(run_daily_collection())
    print(f"SIAFE2 OB: {result}")
