"""
PDF report generator for the compliance system.

Uses fpdf2 to generate daily and monthly compliance reports in PDF format.
"""

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CHARTS_DIR = Path("reports/charts")


class RelatorioCompliance:
    """
    FPDF subclass with custom header and footer for compliance reports.
    Import-guarded to avoid errors if fpdf2 is not installed.
    """
    pass


def _make_pdf_class():
    """Lazily create the FPDF subclass to handle import errors gracefully."""
    try:
        from fpdf import FPDF

        class _RelatorioCompliance(FPDF):
            """PDF report with JFN Compliance branding."""

            # Auto-sanitize all text written to PDF — Helvetica is Latin-1 only
            def cell(self, *args, **kwargs):
                if args and isinstance(args[0], (int, float)):
                    # cell(w, h, txt, ...) — txt is 3rd positional arg
                    lst = list(args)
                    if len(lst) > 2:
                        lst[2] = _t(lst[2])
                    args = tuple(lst)
                if "text" in kwargs:
                    kwargs["text"] = _t(kwargs["text"])
                return super().cell(*args, **kwargs)

            def multi_cell(self, *args, **kwargs):
                if args and isinstance(args[0], (int, float)):
                    lst = list(args)
                    if len(lst) > 2:
                        lst[2] = _t(lst[2])
                    args = tuple(lst)
                if "text" in kwargs:
                    kwargs["text"] = _t(kwargs["text"])
                return super().multi_cell(*args, **kwargs)

            def header(self):
                self.set_font("Helvetica", "B", 12)
                self.set_text_color(30, 64, 175)  # blue-700
                self.cell(0, 8, "JFN COMPLIANCE", align="L", new_x="LMARGIN", new_y="NEXT")
                self.set_font("Helvetica", "", 9)
                self.set_text_color(100, 116, 139)  # slate-500
                self.cell(0, 5, f"Sistema de Compliance e Auditoria — Estado do Rio de Janeiro", new_x="LMARGIN", new_y="NEXT")
                self.cell(0, 5, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", new_x="LMARGIN", new_y="NEXT")
                # Horizontal rule
                self.set_draw_color(203, 213, 225)
                self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
                self.ln(4)

            def footer(self):
                self.set_y(-15)
                self.set_font("Helvetica", "I", 8)
                self.set_text_color(148, 163, 184)
                self.cell(0, 10, f"Página {self.page_no()} | Confidencial — Uso Restrito", align="C")

        return _RelatorioCompliance
    except ImportError:
        return None


def _severidade_color(sev: str) -> tuple[int, int, int]:
    """Return (R, G, B) tuple for severity level."""
    if sev == "alta":
        return (239, 68, 68)    # red
    elif sev in ("média", "media"):
        return (245, 158, 11)   # amber
    return (34, 197, 94)        # green


def _t(s: str) -> str:
    """Sanitize text for Helvetica (Latin-1): replace chars outside 0x00-0xFF."""
    return (
        str(s)
        .replace("—", "-")   # em dash
        .replace("–", "-")   # en dash
        .replace("‘", "'")   # left single quote
        .replace("’", "'")   # right single quote
        .replace("“", '"')   # left double quote
        .replace("”", '"')   # right double quote
        .replace("…", "...")  # ellipsis
        .replace("°", "o")   # degree sign (safe in latin-1 but some fonts miss)
        .encode("latin-1", errors="replace")
        .decode("latin-1")
    )


def gerar_relatorio_diario(
    report: dict,
    alertas: list[dict],
    output_dir: Path,
) -> Path:
    """
    Generate a daily compliance PDF report.

    Args:
        report:     Daily report dict (from scheduler) with doerj/alertas stats.
        alertas:    List of alert dicts with tipo/severidade/titulo/descricao.
        output_dir: Directory where the PDF will be saved.

    Returns:
        Path to the generated PDF file.
    """
    PDFClass = _make_pdf_class()
    if PDFClass is None:
        logger.warning("fpdf2 não instalado — relatório PDF não gerado.")
        # Return a placeholder path
        output_dir.mkdir(parents=True, exist_ok=True)
        placeholder = output_dir / f"relatorio_{report.get('data', date.today().isoformat())}.txt"
        placeholder.write_text("fpdf2 não instalado. Instale com: pip install fpdf2", encoding="utf-8")
        return placeholder

    output_dir.mkdir(parents=True, exist_ok=True)
    data_str = report.get("data", date.today().isoformat())
    out_path = output_dir / f"relatorio_{data_str}.pdf"

    pdf = PDFClass()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)

    # ── Capa ─────────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(30, 64, 175)
    pdf.ln(10)
    pdf.cell(0, 12, "RELATÓRIO DIÁRIO DE COMPLIANCE", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 16)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(0, 10, f"Data de referência: {data_str}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 12)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 8, "Sistema de Compliance e Auditoria — Estado do RJ", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)

    # Status badge
    alertas_stats = report.get("alertas", {})
    alta_count = alertas_stats.get("alta", 0)
    media_count = alertas_stats.get("media", 0)

    if alta_count > 0:
        status_text = f"STATUS: ATENÇÃO ALTA ({alta_count} alertas críticos)"
        r, g, b = 239, 68, 68
    elif media_count > 0:
        status_text = f"STATUS: ATENÇÃO MÉDIA ({media_count} alertas)"
        r, g, b = 245, 158, 11
    else:
        status_text = "STATUS: NORMAL"
        r, g, b = 34, 197, 94

    pdf.set_fill_color(r, g, b)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 12, status_text, align="C", fill=True, new_x="LMARGIN", new_y="NEXT")

    # ── Resumo executivo ──────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(30, 64, 175)
    pdf.cell(0, 10, "1. RESUMO EXECUTIVO", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    doerj = report.get("doerj", {})

    # DOERJ stats table
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(241, 245, 249)
    pdf.set_text_color(30, 41, 59)
    pdf.set_draw_color(203, 213, 225)

    col_w = [80, 50]
    pdf.cell(col_w[0], 8, "Métrica", fill=True, border=1)
    pdf.cell(col_w[1], 8, "Valor", fill=True, border=1, new_x="LMARGIN", new_y="NEXT")

    doerj_rows = [
        ("Total publicações DOERJ", str(doerj.get("total_publicacoes", 0))),
        ("Nomeações", str(doerj.get("nomeacoes", 0))),
        ("Contratos publicados", str(doerj.get("contratos", 0))),
        ("Licitações", str(doerj.get("licitacoes", 0))),
        ("Total alertas gerados", str(alertas_stats.get("total", 0))),
        ("Alertas de alta severidade", str(alertas_stats.get("alta", 0))),
        ("Alertas de média severidade", str(alertas_stats.get("media", 0))),
        ("Alertas de baixa severidade", str(alertas_stats.get("baixa", 0))),
    ]

    pdf.set_font("Helvetica", "", 10)
    for i, (label, valor) in enumerate(doerj_rows):
        fill = i % 2 == 0
        pdf.set_fill_color(248, 250, 252 if fill else 241, 245, 249)
        pdf.cell(col_w[0], 7, label, border=1, fill=fill)
        pdf.cell(col_w[1], 7, valor, border=1, fill=fill, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)

    # Alert type breakdown
    por_tipo = alertas_stats.get("por_tipo", {})
    if por_tipo:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(30, 64, 175)
        pdf.cell(0, 8, "Alertas por tipo:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(30, 41, 59)
        for tipo, qtd in sorted(por_tipo.items(), key=lambda x: x[1], reverse=True):
            pdf.cell(0, 6, f"  • {tipo}: {qtd}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    # ── Alertas de alta severidade ────────────────────────────────────────────
    alta_alertas = [a for a in alertas if a.get("severidade") == "alta"]
    if alta_alertas:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(239, 68, 68)
        pdf.cell(0, 10, "2. ALERTAS DE ALTA SEVERIDADE", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        for i, alerta in enumerate(alta_alertas, 1):
            if pdf.get_y() > 240:
                pdf.add_page()

            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(239, 68, 68)
            pdf.cell(0, 7, f"{i}. {alerta.get('titulo', '')[:90]}", new_x="LMARGIN", new_y="NEXT")

            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(71, 85, 105)
            pdf.cell(0, 5, f"Tipo: {alerta.get('tipo', '')} | Severidade: ALTA", new_x="LMARGIN", new_y="NEXT")

            descr = alerta.get("descricao", "")[:150]
            if descr:
                pdf.set_text_color(51, 65, 85)
                pdf.multi_cell(0, 5, descr)
            pdf.ln(3)

    # ── Alertas de média severidade ───────────────────────────────────────────
    media_alertas = [a for a in alertas if a.get("severidade") in ("média", "media")]
    if media_alertas:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(245, 158, 11)
        pdf.cell(0, 10, "3. ALERTAS DE MÉDIA SEVERIDADE", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        for i, alerta in enumerate(media_alertas, 1):
            if pdf.get_y() > 240:
                pdf.add_page()

            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(245, 158, 11)
            pdf.cell(0, 7, f"{i}. {alerta.get('titulo', '')[:90]}", new_x="LMARGIN", new_y="NEXT")

            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(71, 85, 105)
            pdf.cell(0, 5, f"Tipo: {alerta.get('tipo', '')} | Severidade: MÉDIA", new_x="LMARGIN", new_y="NEXT")

            descr = alerta.get("descricao", "")[:150]
            if descr:
                pdf.set_text_color(51, 65, 85)
                pdf.multi_cell(0, 5, descr)
            pdf.ln(3)

    # ── Gráficos ──────────────────────────────────────────────────────────────
    chart_files = sorted(CHARTS_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    if chart_files:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(30, 64, 175)
        pdf.cell(0, 10, "4. GRÁFICOS", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        for chart_path in chart_files[:4]:  # max 4 charts
            try:
                if pdf.get_y() > 180:
                    pdf.add_page()
                pdf.image(str(chart_path), x=15, w=180)
                pdf.ln(4)
            except Exception as exc:
                logger.warning(f"Não foi possível incluir gráfico {chart_path}: {exc}")

    try:
        pdf.output(str(out_path))
        logger.info(f"Relatório PDF gerado: {out_path}")
    except Exception as exc:
        logger.error(f"Erro ao salvar PDF: {exc}")

    return out_path


def gerar_relatorio_mensal(
    mes: str,
    session,
    output_dir: Path,
) -> Path:
    """
    Generate a monthly compliance PDF report.

    Args:
        mes:        Month in "AAAA-MM" format (e.g., "2025-05").
        session:    SQLAlchemy session.
        output_dir: Directory where the PDF will be saved.

    Returns:
        Path to the generated PDF file.
    """
    PDFClass = _make_pdf_class()
    output_dir.mkdir(parents=True, exist_ok=True)

    if PDFClass is None:
        logger.warning("fpdf2 não instalado — relatório PDF mensal não gerado.")
        placeholder = output_dir / f"relatorio_mensal_{mes}.txt"
        placeholder.write_text("fpdf2 não instalado. Instale com: pip install fpdf2", encoding="utf-8")
        return placeholder

    out_path = output_dir / f"relatorio_mensal_{mes}.pdf"

    try:
        from compliance_agent.database.models import Alerta, Contrato, Empresa, Pessoa
        from sqlalchemy import func

        # Query alerts for the month
        alertas = (
            session.query(Alerta)
            .filter(Alerta.created_at.like(f"{mes}%"))
            .all()
        )

        # Group by type and severity
        por_tipo: dict = {}
        por_sev: dict = {"alta": 0, "média": 0, "baixa": 0}
        for a in alertas:
            por_tipo[a.tipo] = por_tipo.get(a.tipo, 0) + 1
            sev = a.severidade or "baixa"
            por_sev[sev] = por_sev.get(sev, 0) + 1

        # Top 10 most suspect contracts by valor
        top_contratos = (
            session.query(Contrato)
            .filter(Contrato.valor_total.isnot(None))
            .order_by(Contrato.valor_total.desc())
            .limit(10)
            .all()
        )

        # Top 10 most connected actors (from alerts)
        top_empresas_alerta = (
            session.query(Empresa, func.count(Alerta.id).label("n_alertas"))
            .join(Alerta, Alerta.empresa_id == Empresa.id)
            .group_by(Empresa.id)
            .order_by(func.count(Alerta.id).desc())
            .limit(10)
            .all()
        )

    except Exception as exc:
        logger.error(f"Erro ao consultar dados para relatório mensal: {exc}")
        alertas = []
        por_tipo = {}
        por_sev = {"alta": 0, "média": 0, "baixa": 0}
        top_contratos = []
        top_empresas_alerta = []

    pdf = PDFClass()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)

    # ── Capa ─────────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(30, 64, 175)
    pdf.ln(10)
    pdf.cell(0, 12, "RELATÓRIO MENSAL DE COMPLIANCE", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 14)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(0, 8, f"Referência: {mes}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 11)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 6, "Sistema de Compliance e Auditoria — Estado do RJ", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)

    # ── Resumo ────────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(30, 64, 175)
    pdf.cell(0, 10, "1. RESUMO DO MÊS", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(30, 41, 59)

    summary_rows = [
        ("Total de alertas no mês", str(len(alertas))),
        ("Alta severidade", str(por_sev.get("alta", 0))),
        ("Média severidade", str(por_sev.get("média", 0))),
        ("Baixa severidade", str(por_sev.get("baixa", 0))),
    ]

    col_w = [100, 60]
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(241, 245, 249)
    pdf.set_draw_color(203, 213, 225)
    pdf.cell(col_w[0], 8, "Métrica", fill=True, border=1)
    pdf.cell(col_w[1], 8, "Valor", fill=True, border=1, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    for i, (label, valor) in enumerate(summary_rows):
        fill = i % 2 == 0
        pdf.set_fill_color(248, 250, 252)
        pdf.cell(col_w[0], 7, label, border=1, fill=fill)
        pdf.cell(col_w[1], 7, valor, border=1, fill=fill, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)

    # Alert type breakdown
    if por_tipo:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(30, 64, 175)
        pdf.cell(0, 8, "Alertas por tipo:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(30, 41, 59)
        for tipo, qtd in sorted(por_tipo.items(), key=lambda x: x[1], reverse=True):
            pdf.cell(0, 6, f"  • {tipo}: {qtd} alertas", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    # ── Top 10 contratos ─────────────────────────────────────────────────────
    if top_contratos:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(30, 64, 175)
        pdf.cell(0, 10, "2. TOP 10 CONTRATOS (MAIOR VALOR)", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        # Table header
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(241, 245, 249)
        pdf.set_draw_color(203, 213, 225)
        pdf.set_text_color(30, 41, 59)
        w = [15, 35, 60, 40, 30]
        headers_row = ["#", "Número", "Objeto", "Órgão", "Valor (R$)"]
        for col, h in zip(headers_row, w):
            pdf.cell(h, 8, col, fill=True, border=1)
        pdf.ln()

        pdf.set_font("Helvetica", "", 8)
        for i, c in enumerate(top_contratos, 1):
            if pdf.get_y() > 250:
                pdf.add_page()
            row_data = [
                str(i),
                (c.numero or "")[:20],
                (c.objeto or "")[:50],
                (c.orgao_contrat or "")[:35],
                f"{c.valor_total:,.0f}" if c.valor_total else "0",
            ]
            fill = i % 2 == 0
            pdf.set_fill_color(248, 250, 252)
            for val, col_width in zip(row_data, w):
                pdf.cell(col_width, 6, str(val), border=1, fill=fill)
            pdf.ln()

        pdf.ln(4)

    # ── Top 10 empresas com alertas ───────────────────────────────────────────
    if top_empresas_alerta:
        if pdf.get_y() > 180:
            pdf.add_page()
        else:
            pdf.ln(4)

        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(30, 64, 175)
        pdf.cell(0, 10, "3. TOP 10 EMPRESAS COM MAIS ALERTAS", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(241, 245, 249)
        pdf.set_draw_color(203, 213, 225)
        pdf.set_text_color(30, 41, 59)
        w2 = [15, 60, 40, 25, 40]
        for col, h in zip(["#", "Razão Social", "CNPJ", "Alertas", "Situação"], w2):
            pdf.cell(h, 8, col, fill=True, border=1)
        pdf.ln()

        pdf.set_font("Helvetica", "", 8)
        for i, (emp, n_alertas) in enumerate(top_empresas_alerta, 1):
            if pdf.get_y() > 250:
                pdf.add_page()
            row_data = [
                str(i),
                (emp.razao_social or "")[:55],
                (emp.cnpj or "")[:18],
                str(n_alertas),
                (emp.situacao or "")[:35],
            ]
            fill = i % 2 == 0
            pdf.set_fill_color(248, 250, 252)
            for val, col_width in zip(row_data, w2):
                pdf.cell(col_width, 6, str(val), border=1, fill=fill)
            pdf.ln()

    try:
        pdf.output(str(out_path))
        logger.info(f"Relatório mensal PDF gerado: {out_path}")
    except Exception as exc:
        logger.error(f"Erro ao salvar PDF mensal: {exc}")

    return out_path
