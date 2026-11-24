"""
Exportador de relatórios do Hermes para .txt, .pdf e .docx.
Usa dados do banco local (OB PAGA do SIAFE, Alerta) para gerar relatórios.
24/11/2026: as OBs vinham do espelho TFE (`OrdemBancaria` = `ordens_bancarias`); regra da casa é OB = SIAFE
(`ob_orcamentaria_siafe`, régua `_ob_paga`). O SIAFE não separa nº SEI de nº de processo: `processo` vai nos dois.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Iterable

from compliance_agent.database.models import Alerta, get_session, init_db
from compliance_agent.reporting.intel_base import reais

REPORT_DIR = Path(__file__).resolve().parent.parent / "reports"
REPORT_DIR.mkdir(exist_ok=True)


FONTE_OB = "OB paga do SIAFE (ob_orcamentaria_siafe, régua _ob_paga); espelho TFE fora"


def _data_rows(limit: int | None = None):
    """OBs PAGAS do SIAFE, mais recentes primeiro, com os atributos que os montadores leem (numero_ob,
    favorecido_nome, valor, numero_sei, numero_processo)."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    from compliance_agent.database.models import _resolver_db
    from compliance_agent.reporting.cobertura_siafe import ISO_EMISSAO_SIAFE
    con = sqlite3.connect(f"file:{_resolver_db()}?mode=ro", uri=True)
    try:
        sql = (f"SELECT numero_ob, nome_credor, valor, processo FROM ob_orcamentaria_siafe WHERE {_ob_paga(con)} "
               f"ORDER BY {ISO_EMISSAO_SIAFE} DESC, numero_ob DESC")
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [SimpleNamespace(numero_ob=n, favorecido_nome=nm, valor=v, numero_sei=p, numero_processo=p)
                for n, nm, v, p in con.execute(sql)]
    finally:
        con.close()


def _alert_rows(limit: int = 50):
    init_db()
    session = get_session()
    try:
        q = session.query(Alerta).order_by(Alerta.created_at.desc()).limit(int(limit))
        return list(q)
    finally:
        session.close()


def _fmt_currency(value) -> str:
    try:
        float(value)
    except (TypeError, ValueError):
        return str(value)
    return reais(value)


def build_txt_report(path: Path, rows: Iterable, alerts: Iterable[Alerta]) -> Path:
    with path.open("w", encoding="utf-8") as f:
        f.write("Relatorio de Auditoria — Controle Externo\n")
        f.write(f"Gerado em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"Total OBs: {sum(1 for _ in rows)} — fonte: {FONTE_OB}\n\n")
        f.write("== Alertas ==\n")
        for a in alerts:
            f.write(f"- [{a.severidade}] {a.titulo}\n")
            if a.descricao:
                f.write(f"  {a.descricao}\n")
        f.write("\n== Ordens Bancarias ==\n")
        for o in rows:
            f.write(
                f"- {o.numero_ob} | {o.favorecido_nome or 'Sem nome'} | "
                f"{_fmt_currency(o.valor)} | {o.numero_sei or 'Sem SEI'} | {o.numero_processo or '-'}\n"
            )
    return path


def build_docx_report(path: Path, rows: Iterable, alerts: Iterable[Alerta]) -> Path:
    try:
        from docx import Document
    except Exception as e:
        raise RuntimeError(
            "python-docx não está instalado. Instale com: pip install python-docx"
        ) from e

    doc = Document()
    doc.add_heading("Relatório de Auditoria — Controle Externo", 0)
    doc.add_paragraph(f"Gerado em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    doc.add_paragraph(f"Total OBs: {sum(1 for _ in rows)} — fonte: {FONTE_OB}")

    doc.add_heading("Alertas", level=1)
    for a in alerts:
        doc.add_paragraph(f"[{a.severidade}] {a.titulo}", style="List Bullet")
        if a.descricao:
            doc.add_paragraph(a.descricao)

    doc.add_heading("Ordens Bancárias", level=1)
    for o in rows:
        doc.add_paragraph(
            f"{o.numero_ob} | {o.favorecido_nome or 'Sem nome'} | "
            f"{_fmt_currency(o.valor)} | {o.numero_sei or 'Sem SEI'} | {o.numero_processo or '-'}",
            style="List Bullet",
        )

    doc.save(str(path))
    return path


def build_pdf_report(path: Path, rows: Iterable, alerts: Iterable[Alerta]) -> Path:
    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    except Exception as e:
        raise RuntimeError("fpdf2 não está instalado. Instale com: pip install fpdf2") from e

    class Pdf(FPDF):
        def header(self):
            self.set_font("Arial", "B", 12)
            self.cell(0, 10, "Relatorio de Auditoria — Controle Externo", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(4)

    pdf = Pdf()
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 8, f"Gerado em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 8, f"Fonte das OBs: {FONTE_OB}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 8, "Alertas", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Arial", "", 10)
    for a in alerts:
        txt = f"[{a.severidade}] {a.titulo} - {a.descricao or ''}"
        pdf.multi_cell(0, 8, txt)

    pdf.ln(4)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 8, "Ordens Bancarias", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Arial", "", 9)
    for o in rows:
        txt = (
            f"{o.numero_ob} | {o.favorecido_nome or 'Sem nome'} | "
            f"{_fmt_currency(o.valor)} | {o.numero_sei or 'Sem SEI'} | {o.numero_processo or '-'}"
        )
        pdf.multi_cell(0, 6, txt)

    pdf.output(str(path))
    return path


def generate_report(limit: int | None = None, fmt: str = "txt") -> dict:
    fmt = (fmt or "txt").lower().strip()
    if fmt not in {"txt", "pdf", "docx"}:
        raise ValueError("Formato inválido. Use txt, pdf ou docx.")
    rows = _data_rows(limit=limit)
    alerts = _alert_rows()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = REPORT_DIR / f"relatorio_auditoria_{stamp}.{fmt}"
    if fmt == "txt":
        build_txt_report(out, rows, alerts)
    elif fmt == "docx":
        build_docx_report(out, rows, alerts)
    elif fmt == "pdf":
        build_pdf_report(out, rows, alerts)
    return {
        "ok": True,
        "arquivo": str(out),
        "formato": fmt,
        "obs": sum(1 for _ in rows),
        "fonte_obs": FONTE_OB,
        "alertas": sum(1 for _ in alerts),
    }
