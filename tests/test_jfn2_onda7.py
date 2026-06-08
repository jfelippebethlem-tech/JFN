# -*- coding: utf-8 -*-
"""Testes da Onda 7 (relatório classe mundial): gráficos SVG + HTML (rating card, proveniência, hash)."""
from __future__ import annotations


def test_charts_svg_validos():
    from compliance_agent.reporting import charts_svg as C

    assert C.sparkline([1, 2, 3, 2, 5]).startswith("<svg")
    assert C.barras(["A", "B"], [0.7, 0.3], "t").startswith("<svg")
    assert C.heatmap_pxi(7, 6).startswith("<svg")


def test_render_html_tem_rating_proveniencia_e_hash():
    from compliance_agent.reporting.render_html import render_html

    ctx = {
        "titulo": "Dossiê — X", "score": 74, "faixa": "EXTREMO",
        "top_flags": ["conflito_doador"],
        "secoes": [{"titulo": "Pagamentos", "html": "<p>R$ 1</p>"}],
        "proveniencia": [{"dado": "OB", "estado": "REAL", "fonte": "SIAFE", "data": "2026-06-08"}],
    }
    html = render_html(ctx)
    assert "score-badge" in html and ">74<" in html and "EXTREMO" in html
    assert "SHA-256" in html and "Proveniência" in html
    assert "indícios" in html.lower() or "indicios" in html.lower()  # ressalva honesta


def test_render_html_cor_por_faixa():
    """A faixa define a cor do badge (EXTREMO=vermelho, BAIXO=verde)."""
    from compliance_agent.reporting.render_html import render_html, _FAIXA_COR

    h_ext = render_html({"faixa": "EXTREMO", "score": 90})
    h_baixo = render_html({"faixa": "BAIXO", "score": 5})
    assert _FAIXA_COR["EXTREMO"] in h_ext
    assert _FAIXA_COR["BAIXO"] in h_baixo


def test_render_html_hash_muda_com_dados():
    """O hash de integridade depende dos dados (não-adulteração)."""
    from compliance_agent.reporting.render_html import render_html
    import re

    def _hash(html):
        m = re.search(r"SHA-256:\s*([0-9a-f]+)", html)
        return m.group(1) if m else None

    h1 = _hash(render_html({"_dados": {"a": 1}, "score": 1}))
    h2 = _hash(render_html({"_dados": {"a": 2}, "score": 1}))
    assert h1 and h2 and h1 != h2
