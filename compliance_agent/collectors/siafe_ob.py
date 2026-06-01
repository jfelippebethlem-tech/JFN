"""
SIAFE2 OB Orçamentária — daily data collector.

Connects to the user's running Chrome (CDP on port 9222), navigates to the
OB Orçamentária screen, searches the current day's records, and saves them
to the compliance database.

Usage (standalone):
    python -m compliance_agent.collectors.siafe_ob

Called automatically by the daily scheduler at 08:00.
"""

import asyncio
import json
import os
from datetime import date, datetime
from pathlib import Path

from compliance_agent.database.models import (
    OrdemBancaria, SessaoAuditoria, get_session, init_db
)

_SIAFE_OB_URL = (
    "https://siafe2.fazenda.rj.gov.br/Siafe/faces/execucao/financeira"
    "/ordemBancariaOrcamentariaEdit.jsp"
)

_JS_ADF_INPUTS = """
    () => {
        const results = [];
        for (const el of document.querySelectorAll('input, select, textarea')) {
            const r = el.getBoundingClientRect();
            if (r.width <= 0) continue;
            let label = '';
            const id = el.id || '';
            if (id) {
                const lbl = document.querySelector(`label[for="${id}"]`);
                if (lbl) label = lbl.textContent.trim();
            }
            if (!label) {
                let p = el.parentElement;
                for (let i = 0; i < 5 && p; i++, p = p.parentElement) {
                    const lbl = p.querySelector('label, span.af_outputLabel, span.x18m');
                    if (lbl && lbl !== el) { label = lbl.textContent.trim(); break; }
                }
            }
            results.push({
                tag: el.tagName, id: el.id || '', name: el.name || '',
                type: el.type || '', label: label.substring(0, 60),
            });
        }
        return results;
    }
"""

_JS_ADF_GRID_ROWS = """
    (maxRows) => {
        const rowSels = ['tr.af_table_row', 'tr[class*="Row"]:not([class*="Header"])', 'tbody tr'];
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


async def _adf_wait(pg, timeout: int = 10000):
    try:
        await pg.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    await asyncio.sleep(1.5)


async def _dismiss_dialogs(page, max_iter: int = 5) -> list[str]:
    dismissed = []
    for _ in range(max_iter):
        result = await page.evaluate("""
            () => {
                const sim = document.getElementById('myBtnOk');
                if (sim && sim.getBoundingClientRect().width > 0) {
                    sim.click(); return 'sim_dialog';
                }
                const skip = new Set(['myBtnCancel']);
                for (const sel of ['a.x7j', 'a.xg2']) {
                    for (const el of document.querySelectorAll(sel)) {
                        if (skip.has(el.id)) continue;
                        const t = el.textContent.trim().toLowerCase();
                        const r = el.getBoundingClientRect();
                        if ((t === 'ok' || t === 'sim') && r.width > 0 && r.height > 0
                                && !el.className.includes('p_AFDisabled')) {
                            el.click();
                            return 'ok_btn:' + el.id;
                        }
                    }
                }
                return null;
            }
        """)
        if result:
            dismissed.append(result)
            await asyncio.sleep(2)
        else:
            break
    return dismissed


async def _navigate_to_ob(page) -> bool:
    """Navigate to OB Orçamentária. Returns True if screen reached."""
    try:
        await page.goto(_SIAFE_OB_URL, wait_until="networkidle", timeout=20000)
    except Exception:
        pass
    await asyncio.sleep(2)
    await _dismiss_dialogs(page)

    if "ordemBancariaOrcamentaria" in page.url.lower():
        return True

    # Fallback: via a.xgg menu item
    clicked = await page.evaluate("""
        () => {
            for (const el of document.querySelectorAll('a.xgg')) {
                const t = el.textContent.trim();
                if ((t === 'OB Orçamentária' || t.includes('OB Or'))
                    && !el.className.includes('p_AFDisabled')) {
                    el.click(); return t;
                }
            }
            return null;
        }
    """)
    if clicked:
        await _adf_wait(page, 12000)
        return "ordemBancariaOrcamentaria" in page.url.lower()

    return False


def _parse_ob_rows(raw_rows: list[list[str]], colnames: list[str]) -> list[dict]:
    """Map grid row arrays to dict using detected column names."""
    result = []
    for row in raw_rows:
        d = {}
        for i, val in enumerate(row):
            key = colnames[i].lower().replace(" ", "_") if i < len(colnames) else f"col{i}"
            d[key] = val
        result.append(d)
    return result


async def collect_ob_day(target_date: date | None = None, max_rows: int = 200) -> dict:
    """
    Connect to Chrome via CDP, collect OB records for target_date (default: today).
    Returns summary dict with keys: date, records, errors, session_id.
    """
    from playwright.async_api import async_playwright

    target_date = target_date or date.today()
    mes_ini = f"01/{target_date.month:02d}/{target_date.year}"
    mes_fim = f"{target_date.day:02d}/{target_date.month:02d}/{target_date.year}"

    summary = {
        "date": target_date.isoformat(),
        "records": 0,
        "rows": [],
        "errors": [],
        "col_headers": [],
    }

    p = await async_playwright().start()
    browser = None
    try:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    except Exception as e:
        summary["errors"].append(f"CDP connect failed: {e}")
        await p.stop()
        return summary

    try:
        page = None
        for ctx in browser.contexts:
            for pg in ctx.pages:
                url = pg.url.lower()
                if "siafe2.fazenda" in url and "flexvision" not in url:
                    page = pg
                    break
            if page:
                break
        if not page and browser.contexts and browser.contexts[0].pages:
            page = browser.contexts[0].pages[0]

        if not page:
            summary["errors"].append("No page found in CDP browser")
            return summary

        await _dismiss_dialogs(page)

        on_ob = await _navigate_to_ob(page)
        if not on_ob:
            summary["errors"].append(f"Could not navigate to OB screen — URL: {page.url}")
            return summary

        # Fill date range
        await page.evaluate(f"""
            () => {{
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
                    }} else if (fim) {{
                        inp.value = '{mes_fim}';
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('blur', {{bubbles: true}}));
                    }}
                }}
            }}
        """)
        await asyncio.sleep(0.5)

        # Click Consultar
        consultar = await page.evaluate("""
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
        if not consultar:
            summary["errors"].append("Consultar button not found")
            return summary

        await _adf_wait(page, 20000)

        # Read column headers
        headers_data = await page.evaluate("""
            () => {
                const sels = ['th', 'thead td', '.af_column_cell-text', '.af_column_sortable-text',
                              '[class*="columnHeader"]'];
                for (const sel of sels) {
                    const els = [...document.querySelectorAll(sel)];
                    const texts = els.map(e => e.textContent.trim()).filter(t => t && t.length < 80);
                    if (texts.length > 0) return texts;
                }
                return [];
            }
        """)
        summary["col_headers"] = headers_data

        # Read up to max_rows
        rows_data = await page.evaluate(_JS_ADF_GRID_ROWS, max_rows)
        if rows_data:
            summary["rows"] = rows_data["rows"]
            summary["records"] = len(rows_data["rows"])
        else:
            body_text = await page.inner_text("body")
            if "sem resultado" in body_text.lower() or "não encontrad" in body_text.lower():
                summary["records"] = 0
            else:
                summary["errors"].append(f"No grid rows detected. Page text: {body_text[:300]}")

    except Exception as e:
        summary["errors"].append(f"Collection error: {e}")
    finally:
        try:
            await p.stop()
        except Exception:
            pass

    return summary


def save_ob_records(session, summary: dict) -> int:
    """Upsert OB records from summary into the database. Returns count saved."""
    col_headers = summary.get("col_headers", [])
    saved = 0
    target_date = date.fromisoformat(summary["date"])

    for row in summary.get("rows", []):
        d = {}
        for i, val in enumerate(row):
            key = col_headers[i].lower().replace(" ", "_") if i < len(col_headers) else f"col{i}"
            d[key] = val

        # Try to extract number from first column
        numero = (
            d.get("número", "") or d.get("numero", "") or
            d.get("n°", "") or d.get("ob", "") or
            (row[0] if row else "")
        )

        # Check for existing
        existing = session.query(OrdemBancaria).filter_by(
            numero_ob=str(numero),
            data_emissao=target_date,
        ).first()

        if existing:
            existing.raw_json = json.dumps(d, ensure_ascii=False)
            existing.updated_at = datetime.utcnow()
        else:
            ob = OrdemBancaria(
                numero_ob=str(numero),
                data_emissao=target_date,
                exercicio=target_date.year,
                raw_json=json.dumps(d, ensure_ascii=False),
            )
            # Map common column names
            for key, val in d.items():
                if "favorecido" in key or "beneficiário" in key:
                    if not ob.favorecido_nome:
                        ob.favorecido_nome = str(val)
                elif "valor" in key:
                    try:
                        ob.valor = float(str(val).replace(".", "").replace(",", "."))
                    except (ValueError, TypeError):
                        pass
                elif "situação" in key or "status" in key:
                    ob.status = str(val)
                elif "ug" in key or "unidade" in key:
                    if not ob.ug_nome:
                        ob.ug_nome = str(val)
            session.add(ob)
        saved += 1

    session.commit()
    return saved


async def run_daily_collection(target_date: date | None = None) -> dict:
    """
    Full collection pipeline: collect from SIAFE2 and persist to DB.
    Also logs a SessaoAuditoria record.
    """
    init_db()
    session = get_session()
    target_date = target_date or date.today()

    summary = await collect_ob_day(target_date)

    saved = 0
    if not summary["errors"] or summary["records"] > 0:
        try:
            saved = save_ob_records(session, summary)
        except Exception as e:
            summary["errors"].append(f"DB save error: {e}")

    sessao = SessaoAuditoria(
        data_sessao=target_date,
        tipo="siafe_ob",
        status="ok" if not summary["errors"] else "erro",
        registros=saved,
        resumo=json.dumps({
            "date": summary["date"],
            "records_fetched": summary["records"],
            "records_saved": saved,
            "col_headers": summary["col_headers"],
        }, ensure_ascii=False),
        detalhes=json.dumps(summary.get("errors", []), ensure_ascii=False)
        if summary["errors"] else None,
    )
    session.add(sessao)
    session.commit()
    session.close()

    return {
        "date": target_date.isoformat(),
        "records_fetched": summary["records"],
        "records_saved": saved,
        "errors": summary["errors"],
    }


if __name__ == "__main__":
    result = asyncio.run(run_daily_collection())
    print(f"SIAFE2 OB collection: {result}")
