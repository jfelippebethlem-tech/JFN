# -*- coding: utf-8 -*-
"""Relatório classe mundial — JFN 2.0, Onda 7. HTML (Jinja2+CSS) → PDF (Playwright).

Salto estético Kroll/Deloitte: capa com rating card, seções, gráficos SVG vetoriais, proveniência
por número (REAL/CACHE + fonte + data) e hash de integridade no rodapé. HTML→PDF via Playwright
`page.pdf()` (já instalado; substitui WeasyPrint, que exige libs de sistema). Grátis.

Honesto: indícios, nunca acusação; cada número declara a proveniência; o hash torna o relatório
uma peça defensável (não-adulteração). Score decomposto (risco de achado ≠ punição).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

_REPORTS = Path(__file__).resolve().parent.parent.parent / "reports"

_FAIXA_COR = {"BAIXO": "#2e7d32", "MÉDIO": "#f9a825", "ALTO": "#ef6c00", "EXTREMO": "#c62828"}

_TEMPLATE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<style>
  @page { size: A4; margin: 20mm 16mm 18mm 16mm; }
  * { box-sizing: border-box; }
  body { font-family: Georgia, 'Times New Roman', serif; color: #1a1a1a; font-size: 10.5px; line-height: 1.55; }
  /* capa */
  .capa { border-bottom: 3px solid #1f4e79; padding-bottom: 12px; margin-bottom: 16px; }
  .classif { color:#b71c1c; font-weight:700; letter-spacing:.15em; font-size:9.5px; text-transform:uppercase; }
  h1 { font-size: 21px; color:#1f4e79; margin: 6px 0 2px; line-height:1.25; font-weight:700; }
  .meta { color:#555; font-size:9.5px; line-height:1.5; }
  /* rating card */
  .rating { display:flex; align-items:center; gap:16px; border:1px solid #d7dde6; border-radius:10px;
            padding:14px 16px; margin:14px 0 18px; background:linear-gradient(180deg,#fbfcfe,#f4f7fb); }
  .score-badge { width:78px; height:78px; border-radius:50%; color:#fff; display:flex; align-items:center;
                 justify-content:center; flex-direction:column; font-weight:700; flex:0 0 auto;
                 box-shadow:0 1px 4px rgba(0,0,0,.15); }
  .score-badge .n { font-size:24px; line-height:1; } .score-badge .f { font-size:8.5px; letter-spacing:.5px; margin-top:2px; }
  .flag { display:inline-block; padding:2px 8px; border-radius:10px; background:#eef3fa; color:#1f4e79;
          font-size:8.5px; border:1px solid #d7e2f0; margin:2px 3px 0 0; font-family:Arial,sans-serif; }
  /* títulos de seção */
  h2 { font-size:13.5px; color:#1f4e79; border-bottom:1.5px solid #1f4e79; padding-bottom:4px; margin:20px 0 8px;
       font-weight:700; }
  h3 { font-size:12px; color:#12335a; background:#eef3fa; border-left:4px solid #1f4e79; padding:6px 10px;
       margin:12px 0 8px; border-radius:0 4px 4px 0; }
  h4 { font-size:10.5px; color:#1f4e79; margin:12px 0 4px; text-transform:uppercase; letter-spacing:.04em;
       font-family:Arial,sans-serif; font-weight:700; }
  p { margin:5px 0; } .sub { font-weight:700; color:#333; margin-top:10px; }
  /* tabelas */
  table { width:100%; border-collapse:collapse; font-size:9.5px; margin:7px 0; font-family:Arial,sans-serif; }
  th,td { text-align:left; padding:5px 7px; border-bottom:1px solid #e8ebef; vertical-align:top; }
  th { background:#1f4e79; color:#fff; font-weight:600; font-size:9px; letter-spacing:.02em; }
  table tr:nth-child(even) td { background:#f5f8fc; }
  table.ident th.k { background:#eef3fa; color:#12335a; width:26%; font-weight:700; border-bottom:1px solid #dbe4f0; }
  td.mono, .mono { font-family:'Courier New',monospace; font-size:8.5px; color:#444; }
  /* fichas */
  .ficha { margin-bottom:4px; }
  blockquote.clausula { margin:6px 0; padding:10px 14px; background:#fff8e1; border-left:4px solid #f9a825;
       border-radius:0 4px 4px 0; font-style:italic; color:#4a3b00; font-size:10px; }
  .sumula { margin:6px 0; padding:8px 12px; background:#f1f8f4; border-left:4px solid #2e7d32; border-radius:0 4px 4px 0; }
  .acordao { margin:6px 0; padding:8px 12px; background:#f3f6fb; border-left:4px solid #5b7fb0; border-radius:0 4px 4px 0; }
  .teste { background:#eef3fa; padding:6px 10px; border-radius:4px; }
  .aviso { color:#8a6d00; background:#fff8e1; padding:6px 10px; border-radius:4px; font-size:9px; }
  /* colegiado / votos */
  table.colegiado td.lente { font-weight:700; color:#12335a; width:20%; }
  td.vc { text-align:center; white-space:nowrap; width:9%; }
  .voto { display:inline-block; padding:2px 8px; border-radius:10px; color:#fff; font-weight:700; font-size:9px; }
  .voto.alto { background:#c62828; } .voto.medio { background:#f9a825; color:#3a2c00; } .voto.baixo { background:#2e7d32; }
  .cit { font-size:8.5px; color:#555; font-style:italic; margin-top:3px; }
  .gate { color:#b71c1c; font-size:8px; font-weight:700; }
  .ind { color:#8a8a8a; font-style:italic; }
  .conclusao { padding:9px 13px; border-radius:5px; margin-top:8px; }
  .conclusao.extremo { background:#fdecea; border-left:4px solid #c62828; }
  .conclusao.alto { background:#fff3e0; border-left:4px solid #ef6c00; }
  .conclusao.medio { background:#fffde7; border-left:4px solid #f9a825; }
  .chart { margin:8px 0; }
  .nota { font-size:8.5px; color:#777; font-style:italic; }
  footer { margin-top:22px; border-top:1px solid #ddd; padding-top:7px; font-size:8px; color:#888; }
  .prov td { font-size:8.5px; color:#555; }
  .pgbreak { page-break-before: always; }
  h3, h4, blockquote, .sumula, .conclusao { page-break-inside: avoid; }
</style></head><body>
  <div class="capa">
    <div class="classif">{{ classificacao }}</div>
    <h1>{{ titulo }}</h1>
    <div class="meta">{{ subtitulo }}<br>Emitido em {{ data }} · Analista: {{ analista }} · Metodologia: {{ metodologia }}</div>
  </div>

  <div class="rating">
    <div class="score-badge" style="background:{{ cor_faixa }}"><span class="n">{{ score }}</span><span class="f">{{ faixa }}</span></div>
    <div>
      <b>{{ rotulo_score }}:</b> {{ score }}/100 ({{ faixa }}) — risco de ACHADO, não de punição.<br>
      <b>Destaques:</b> {% for c in top_flags %}<span class="flag">{{ c }}</span> {% endfor %}
    </div>
  </div>

  {% for sec in secoes %}
  <h2 {% if sec.page_break %}class="pgbreak"{% endif %}>{{ sec.titulo }}</h2>
  {% if sec.html %}{{ sec.html | safe }}{% endif %}
  {% if sec.chart %}<div class="chart">{{ sec.chart | safe }}</div>{% endif %}
  {% endfor %}

  {% if proveniencia %}
  <h2>Proveniência dos dados</h2>
  <table class="prov"><tr><th>Dado</th><th>Estado</th><th>Fonte</th><th>Data</th></tr>
  {% for p in proveniencia %}<tr><td>{{ p.dado }}</td><td>{{ p.estado }}</td><td>{{ p.fonte }}</td><td>{{ p.data }}</td></tr>{% endfor %}
  </table>{% endif %}

  <p class="nota">{{ ressalva }}</p>
  <footer>Inteligência fiscal RJ — peça de diligência (indícios, nunca acusação; presunção de
  legitimidade). Hash de integridade SHA-256: {{ hash }}</footer>
</body></html>"""


def render_html(ctx: dict) -> str:
    """Renderiza o HTML do relatório a partir do contexto. Calcula o hash de integridade."""
    from jinja2 import Template

    dados_hash = hashlib.sha256(json.dumps(ctx.get("_dados", ctx), sort_keys=True, default=str)
                                .encode()).hexdigest()
    faixa = (ctx.get("faixa") or "BAIXO").upper()
    full = {
        "classificacao": ctx.get("classificacao", "CONFIDENCIAL — USO INTERNO"),
        "titulo": ctx.get("titulo", "Relatório de Inteligência"),
        "subtitulo": ctx.get("subtitulo", ""),
        "data": ctx.get("data") or datetime.now().strftime("%d/%m/%Y"),
        "analista": ctx.get("analista", "Controle Externo (automatizado)"),
        "metodologia": ctx.get("metodologia", "Due diligence Nível II + red flags TCU/TCE-RJ"),
        "score": ctx.get("score", 0), "faixa": faixa,
        "cor_faixa": _FAIXA_COR.get(faixa, "#777"),
        "rotulo_score": ctx.get("rotulo_score", "Índice de risco"),
        "top_flags": ctx.get("top_flags", []),
        "secoes": ctx.get("secoes", []),
        "proveniencia": ctx.get("proveniencia", []),
        "ressalva": ctx.get("ressalva", "Indícios para apuração interna; presunção de legitimidade dos "
                                        "atos administrativos. Nenhum dado indisponível foi fabricado."),
        "hash": dados_hash[:32],
    }
    return Template(_TEMPLATE).render(**full)


async def html_to_pdf(html: str, destino: str) -> str:
    """Converte HTML→PDF com Playwright (page.pdf). Tipografia A4 profissional."""
    from playwright.async_api import async_playwright

    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = await b.new_page()
            await page.set_content(html, wait_until="networkidle")
            await page.pdf(path=destino, format="A4", print_background=True,
                           display_header_footer=True,
                           header_template="<span></span>",
                           footer_template=(
                               "<div style='font-family:Georgia,serif;font-size:7.5px;color:#999;"
                               "width:100%;padding:0 14mm;display:flex;justify-content:space-between;'>"
                               "<span>Controle Externo — RJ · indícios, nunca acusação</span>"
                               "<span>pág. <span class='pageNumber'></span> de <span class='totalPages'></span></span>"
                               "</div>"),
                           margin={"top": "14mm", "bottom": "16mm", "left": "10mm", "right": "10mm"})
        finally:
            await b.close()
    return destino


async def gerar_pdf(ctx: dict, nome_base: str) -> str:
    """Pipeline completo: ctx → HTML → PDF em reports/<nome_base>_<data>.pdf."""
    html = render_html(ctx)
    destino = str(_REPORTS / f"{nome_base}_{datetime.now().date()}.pdf")
    return await html_to_pdf(html, destino)
