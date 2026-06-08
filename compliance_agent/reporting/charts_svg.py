# -*- coding: utf-8 -*-
"""Gráficos SVG para o relatório classe mundial — JFN 2.0, Onda 7.

matplotlib → SVG (vetorial, embutível inline no HTML; sem dependência de browser para gerar).
Estética sóbria (due diligence). Cada função retorna uma STRING SVG. Grátis (matplotlib).
"""
from __future__ import annotations

import io


def _fig_to_svg(fig) -> str:
    """Serializa uma figura matplotlib em string SVG (sem XML decl, p/ embutir inline)."""
    import matplotlib.pyplot as plt

    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)
    svg = buf.getvalue()
    i = svg.find("<svg")
    return svg[i:] if i >= 0 else svg


def sparkline(valores: list[float], titulo: str = "") -> str:
    """Mini-linha de tendência (ex.: pagamentos por ano)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(4, 1.1))
    ax.plot(range(len(valores)), valores, color="#1f4e79", linewidth=2)
    ax.fill_between(range(len(valores)), valores, color="#1f4e79", alpha=0.12)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    if titulo:
        ax.set_title(titulo, fontsize=8, color="#444")
    return _fig_to_svg(fig)


def barras(labels: list[str], valores: list[float], titulo: str = "") -> str:
    """Barras horizontais (ex.: concentração por órgão)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5, max(1.2, 0.4 * len(labels) + 0.4)))
    cores = ["#c0392b" if i == 0 else "#1f4e79" for i in range(len(labels))]
    ax.barh(range(len(labels)), valores, color=cores)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels([str(x)[:28] for x in labels], fontsize=8)
    ax.invert_yaxis()
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    if titulo:
        ax.set_title(titulo, fontsize=9, color="#222")
    return _fig_to_svg(fig)


def heatmap_pxi(prob: int, impacto: int, titulo: str = "Matriz de Risco P×I (TCU)") -> str:
    """Mapa de calor 9×9 P×I (metodologia TCU) com o ponto do achado destacado."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    grid = np.outer(np.arange(1, 10), np.arange(1, 10))  # P×I
    fig, ax = plt.subplots(figsize=(3.2, 3.0))
    ax.imshow(grid, cmap="RdYlGn_r", origin="lower", extent=[0.5, 9.5, 0.5, 9.5], aspect="auto")
    p = max(1, min(int(prob), 9)); i = max(1, min(int(impacto), 9))
    ax.scatter([i], [p], s=160, edgecolor="black", facecolor="white", zorder=5)
    ax.text(i, p, "✕", ha="center", va="center", fontsize=10, zorder=6)
    ax.set_xlabel("Impacto", fontsize=8); ax.set_ylabel("Probabilidade", fontsize=8)
    ax.set_title(titulo, fontsize=8, color="#222")
    ax.set_xticks(range(1, 10)); ax.set_yticks(range(1, 10))
    ax.tick_params(labelsize=6)
    return _fig_to_svg(fig)
