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


async def _navigate_to_ob(page) -> bool:
    """
    Garante que estamos na tela de OB Orçamentária.

    Navega via execucaoFinanceiraMain.jsp (inicializa o contexto ADF) e
    depois clica no menu 'OB Orçamentária' (a.xgg). NUNCA usa goto direto
    na URL da OB — isso quebra o ADF/JSF (erro BeanELResolver).
    """
    if "ordembancariaorcamentaria" in page.url.lower():
        await _dismiss_dialogs(page)
        return True

    cur = page.url.lower()
    if "execucaofinanceira" not in cur and "siafe2.fazenda" in cur:
        # já está no SIAFE, só não na financeira — tenta o menu direto
        pass

    if "siafe2.fazenda" not in cur or "erro" in cur or "error" in cur or "login" in cur:
        for target in (_SIAFE_FINANCEIRA, _SIAFE_HOME):
            try:
                await page.goto(target, wait_until="networkidle", timeout=20000)
                await asyncio.sleep(3)
                await _dismiss_dialogs(page)
                c = page.url.lower()
                if "erro" not in c and "error" not in c and "login" not in c:
                    break
            except Exception:
                pass
    elif "execucaofinanceira" not in cur and "ordembancaria" not in cur:
        try:
            await page.goto(_SIAFE_FINANCEIRA, wait_until="networkidle", timeout=20000)
            await asyncio.sleep(3)
            await _dismiss_dialogs(page)
        except Exception:
            pass

    if "ordembancariaorcamentaria" in page.url.lower():
        return True

    # Clica no item de menu 'OB Orçamentária' (a.xgg)
    for _ in range(2):
        clicked = await page.evaluate(r"""
            () => {
                for (const el of document.querySelectorAll('a.xgg')) {
                    const t = el.textContent.trim();
                    if ((t === 'OB Orçamentária' || t.startsWith('OB Or'))
                        && !el.className.includes('p_AFDisabled')) {
                        el.click(); return t;
                    }
                }
                return null;
            }
        """)
        if clicked:
            await _adf_wait(page, 15000)
            await _dismiss_dialogs(page)
            if "ordembancariaorcamentaria" in page.url.lower():
                return True
        await asyncio.sleep(2)

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
    try:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
    except Exception as e:
        summary["errors"].append(f"CDP connect falhou: {e}")
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


async def run_daily_collection(target_date: date | None = None) -> dict:
    """Pipeline completo: coleta + persiste + registra SessaoAuditoria."""
    init_db()
    session = get_session()
    target_date = target_date or date.today()

    summary = await collect_ob_day(target_date)

    saved = 0
    if summary["records"] > 0:
        try:
            saved = save_ob_records(session, summary)
        except Exception as e:
            summary["errors"].append(f"Erro ao salvar no banco: {e}")

    sessao = SessaoAuditoria(
        data_sessao=target_date,
        tipo="siafe_ob",
        status="ok" if not summary["errors"] else ("parcial" if saved else "erro"),
        registros=saved,
        resumo=json.dumps({
            "date": summary["date"],
            "records_fetched": summary["records"],
            "records_saved": saved,
            "header": summary["header"],
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
    print(f"SIAFE2 OB: {result}")
