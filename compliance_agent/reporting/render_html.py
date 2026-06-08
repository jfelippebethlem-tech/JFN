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
  @page { size: A4; margin: 18mm 15mm; }
  body { font-family: 'Helvetica Neue', Arial, sans-serif; color: #1a1a1a; font-size: 11px; line-height: 1.5; }
  .capa { border-bottom: 3px solid #1f4e79; padding-bottom: 10px; margin-bottom: 14px; }
  .classif { color:#c62828; font-weight:700; letter-spacing:1px; font-size:10px; }
  h1 { font-size: 20px; color:#1f4e79; margin: 4px 0; }
  .meta { color:#555; font-size:10px; }
  .rating { display:flex; align-items:center; gap:14px; border:1px solid #ddd; border-radius:8px;
            padding:12px 14px; margin:12px 0; background:#fafafa; }
  .score-badge { width:74px; height:74px; border-radius:50%; color:#fff; display:flex; align-items:center;
                 justify-content:center; flex-direction:column; font-weight:700; }
  .score-badge .n { font-size:22px; line-height:1; }
  .score-badge .f { font-size:9px; letter-spacing:.5px; }
  h2 { font-size:13px; color:#1f4e79; border-bottom:1px solid #e0e0e0; padding-bottom:3px; margin-top:16px; }
  table { width:100%; border-collapse:collapse; font-size:10px; margin:6px 0; }
  th,td { text-align:left; padding:4px 6px; border-bottom:1px solid #eee; }
  th { background:#f3f6fa; color:#1f4e79; }
  .flag { padding:2px 6px; border-radius:3px; background:#fdecea; color:#c62828; font-size:9px; }
  .chart { margin:8px 0; }
  .nota { font-size:9px; color:#666; font-style:italic; }
  footer { margin-top:20px; border-top:1px solid #ddd; padding-top:6px; font-size:8px; color:#888; }
  .prov td { font-size:9px; color:#555; }
</style></head><body>
  <div class="capa">
    <div class="classif">{{ classificacao }}</div>
    <h1>{{ titulo }}</h1>
    <div class="meta">{{ subtitulo }}<br>Emitido em {{ data }} · Analista: {{ analista }} · Metodologia: {{ metodologia }}</div>
  </div>

  <div class="rating">
    <div class="score-badge" style="background:{{ cor_faixa }}"><span class="n">{{ score }}</span><span class="f">{{ faixa }}</span></div>
    <div>
      <b>Score de convergência:</b> {{ score }}/100 ({{ faixa }}) — risco de ACHADO, não de punição.<br>
      <b>Top indícios:</b> {% for c in top_flags %}<span class="flag">{{ c }}</span> {% endfor %}
    </div>
  </div>

  {% for sec in secoes %}
  <h2>{{ sec.titulo }}</h2>
  {% if sec.html %}{{ sec.html | safe }}{% endif %}
  {% if sec.chart %}<div class="chart">{{ sec.chart | safe }}</div>{% endif %}
  {% endfor %}

  {% if proveniencia %}
  <h2>Proveniência dos dados</h2>
  <table class="prov"><tr><th>Dado</th><th>Estado</th><th>Fonte</th><th>Data</th></tr>
  {% for p in proveniencia %}<tr><td>{{ p.dado }}</td><td>{{ p.estado }}</td><td>{{ p.fonte }}</td><td>{{ p.data }}</td></tr>{% endfor %}
  </table>{% endif %}

  <p class="nota">{{ ressalva }}</p>
  <footer>JFN · Inteligência fiscal RJ — peça de diligência (indícios, nunca acusação; presunção de
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
        "analista": ctx.get("analista", "JFN (automatizado)"),
        "metodologia": ctx.get("metodologia", "Due diligence Nível II + red flags TCU/TCE-RJ"),
        "score": ctx.get("score", 0), "faixa": faixa,
        "cor_faixa": _FAIXA_COR.get(faixa, "#777"),
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
                           margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
        finally:
            await b.close()
    return destino


async def gerar_pdf(ctx: dict, nome_base: str) -> str:
    """Pipeline completo: ctx → HTML → PDF em reports/<nome_base>_<data>.pdf."""
    html = render_html(ctx)
    destino = str(_REPORTS / f"{nome_base}_{datetime.now().date()}.pdf")
    return await html_to_pdf(html, destino)
