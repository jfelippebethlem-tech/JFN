"""
Matplotlib chart generation for compliance reports.

All charts use dark background, save PNG files to reports/charts/,
and return the file Path. No interactive display.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CHARTS_DIR = Path("reports/charts")


def _ensure_dir() -> Path:
    """Create charts directory if it doesn't exist."""
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    return CHARTS_DIR


def grafico_alertas_por_tipo(alertas_dict: dict) -> Path:
    """
    Generate a horizontal bar chart of alerts grouped by type.

    Args:
        alertas_dict: Dict mapping alert type (str) → count (int).

    Returns:
        Path to the saved PNG file.
    """
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    plt.style.use("dark_background")
    _ensure_dir()

    tipos = list(alertas_dict.keys())
    contagens = [alertas_dict[t] for t in tipos]

    # Sort by count descending
    paired = sorted(zip(contagens, tipos), reverse=True)
    contagens = [p[0] for p in paired]
    tipos = [p[1] for p in paired]

    fig, ax = plt.subplots(figsize=(10, max(4, len(tipos) * 0.6)))

    colors = [
        "#ef4444" if c >= max(contagens, default=1) * 0.7
        else "#f59e0b" if c >= max(contagens, default=1) * 0.3
        else "#22c55e"
        for c in contagens
    ]

    bars = ax.barh(tipos, contagens, color=colors, edgecolor="#334155", height=0.6)

    # Add value labels
    for bar, val in zip(bars, contagens):
        ax.text(
            bar.get_width() + 0.1,
            bar.get_y() + bar.get_height() / 2,
            str(val),
            va="center",
            ha="left",
            color="#e2e8f0",
            fontsize=10,
        )

    ax.set_xlabel("Quantidade de Alertas", color="#94a3b8")
    ax.set_title("Alertas por Tipo", color="#f1f5f9", fontsize=14, pad=15)
    ax.tick_params(colors="#94a3b8")
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax.set_facecolor("#0f172a")
    fig.patch.set_facecolor("#0f172a")

    plt.tight_layout()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = CHARTS_DIR / f"alertas_por_tipo_{ts}.png"
    plt.savefig(str(out_path), dpi=120, bbox_inches="tight", facecolor="#0f172a")
    plt.close()

    logger.info(f"Gráfico salvo: {out_path}")
    return out_path


def grafico_alertas_por_dia(dados: list[dict]) -> Path:
    """
    Generate a line chart showing alerts over time.

    Args:
        dados: List of dicts with keys: data (str YYYY-MM-DD), total (int),
               alta (int), media (int).

    Returns:
        Path to the saved PNG file.
    """
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    from matplotlib.dates import DateFormatter, AutoDateLocator
    import matplotlib.dates as mdates
    from datetime import datetime as dt

    plt.style.use("dark_background")
    _ensure_dir()

    if not dados:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(0.5, 0.5, "Sem dados disponíveis", transform=ax.transAxes,
                ha="center", va="center", color="#94a3b8", fontsize=12)
        ax.set_facecolor("#0f172a")
        fig.patch.set_facecolor("#0f172a")
        plt.tight_layout()
        out_path = CHARTS_DIR / "alertas_por_dia_empty.png"
        plt.savefig(str(out_path), dpi=120, bbox_inches="tight", facecolor="#0f172a")
        plt.close()
        return out_path

    # Parse dates
    dates = []
    totals = []
    altas = []
    medias = []

    for d in dados:
        try:
            dates.append(dt.strptime(d["data"], "%Y-%m-%d"))
            totals.append(d.get("total", 0))
            altas.append(d.get("alta", 0))
            medias.append(d.get("media", 0))
        except (KeyError, ValueError):
            continue

    if not dates:
        return grafico_alertas_por_dia([])

    fig, ax = plt.subplots(figsize=(12, 5))

    ax.plot(dates, totals, color="#60a5fa", linewidth=2, label="Total", marker="o", markersize=4)
    ax.plot(dates, altas, color="#ef4444", linewidth=1.5, label="Alta", marker="^", markersize=4, linestyle="--")
    ax.plot(dates, medias, color="#f59e0b", linewidth=1.5, label="Média", marker="s", markersize=4, linestyle="--")

    ax.fill_between(dates, totals, alpha=0.15, color="#60a5fa")

    ax.xaxis.set_major_locator(AutoDateLocator())
    ax.xaxis.set_major_formatter(DateFormatter("%d/%m"))
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))

    ax.set_xlabel("Data", color="#94a3b8")
    ax.set_ylabel("Alertas", color="#94a3b8")
    ax.set_title("Alertas ao Longo do Tempo", color="#f1f5f9", fontsize=14, pad=15)
    ax.tick_params(colors="#94a3b8")
    ax.legend(facecolor="#1e293b", edgecolor="#334155", labelcolor="#e2e8f0")
    ax.set_facecolor("#0f172a")
    fig.patch.set_facecolor("#0f172a")
    fig.autofmt_xdate()

    plt.tight_layout()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = CHARTS_DIR / f"alertas_por_dia_{ts}.png"
    plt.savefig(str(out_path), dpi=120, bbox_inches="tight", facecolor="#0f172a")
    plt.close()

    logger.info(f"Gráfico salvo: {out_path}")
    return out_path


def grafico_top_orgaos_contratos(ranking: list[dict]) -> Path:
    """
    Generate a horizontal bar chart showing average contract value per organ.

    Args:
        ranking: List of dicts with keys: orgao (str), media_contrato (float).

    Returns:
        Path to the saved PNG file.
    """
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    plt.style.use("dark_background")
    _ensure_dir()

    if not ranking:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(0.5, 0.5, "Sem dados disponíveis", transform=ax.transAxes,
                ha="center", va="center", color="#94a3b8", fontsize=12)
        ax.set_facecolor("#0f172a")
        fig.patch.set_facecolor("#0f172a")
        plt.tight_layout()
        out_path = CHARTS_DIR / "top_orgaos_empty.png"
        plt.savefig(str(out_path), dpi=120, bbox_inches="tight", facecolor="#0f172a")
        plt.close()
        return out_path

    # Limit to top 15
    ranking = sorted(ranking, key=lambda x: x.get("media_contrato", 0), reverse=True)[:15]
    orgaos = [r.get("orgao", "")[:40] for r in ranking]
    medias = [r.get("media_contrato", 0) for r in ranking]

    fig, ax = plt.subplots(figsize=(12, max(5, len(orgaos) * 0.55)))

    colors = ["#ef4444" if i < 3 else "#f59e0b" if i < 7 else "#22c55e"
              for i in range(len(orgaos))]

    bars = ax.barh(orgaos, medias, color=colors, edgecolor="#334155", height=0.65)

    # Format values as R$ K
    for bar, val in zip(bars, medias):
        label = f"R$ {val:,.0f}" if val < 1_000_000 else f"R$ {val/1_000_000:.1f}M"
        ax.text(
            bar.get_width() * 1.01,
            bar.get_y() + bar.get_height() / 2,
            label,
            va="center", ha="left", color="#e2e8f0", fontsize=9,
        )

    ax.set_xlabel("Média por Contrato (R$)", color="#94a3b8")
    ax.set_title("Top Órgãos por Valor Médio de Contrato", color="#f1f5f9", fontsize=14, pad=15)
    ax.tick_params(colors="#94a3b8")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"R$ {x:,.0f}"))
    ax.set_facecolor("#0f172a")
    fig.patch.set_facecolor("#0f172a")

    plt.tight_layout()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = CHARTS_DIR / f"top_orgaos_{ts}.png"
    plt.savefig(str(out_path), dpi=120, bbox_inches="tight", facecolor="#0f172a")
    plt.close()

    logger.info(f"Gráfico salvo: {out_path}")
    return out_path


def grafico_superfaturamentos(dados: list[dict]) -> Path:
    """
    Generate a scatter plot comparing contract values vs category median.

    Args:
        dados: List of dicts with keys: valor (float), mediana (float),
               objeto (str, label), categoria (str).

    Returns:
        Path to the saved PNG file.
    """
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    import numpy as np

    plt.style.use("dark_background")
    _ensure_dir()

    if not dados:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, "Sem dados disponíveis", transform=ax.transAxes,
                ha="center", va="center", color="#94a3b8", fontsize=12)
        ax.set_facecolor("#0f172a")
        fig.patch.set_facecolor("#0f172a")
        plt.tight_layout()
        out_path = CHARTS_DIR / "superfaturamentos_empty.png"
        plt.savefig(str(out_path), dpi=120, bbox_inches="tight", facecolor="#0f172a")
        plt.close()
        return out_path

    valores = [d.get("valor", 0) for d in dados]
    medianas = [d.get("mediana", 0) for d in dados]
    labels = [str(d.get("objeto", ""))[:30] for d in dados]

    # Color by how far above median
    ratios = [v / m if m > 0 else 1.0 for v, m in zip(valores, medianas)]
    colors = [
        "#ef4444" if r > 2.0
        else "#f59e0b" if r > 1.3
        else "#22c55e"
        for r in ratios
    ]

    fig, ax = plt.subplots(figsize=(12, 7))

    scatter = ax.scatter(
        medianas, valores,
        c=colors,
        s=[min(200, r * 60) for r in ratios],
        alpha=0.8,
        edgecolors="#334155",
        linewidth=0.5,
    )

    # Draw diagonal (valor == mediana)
    max_val = max(max(valores, default=1), max(medianas, default=1))
    ax.plot([0, max_val], [0, max_val], color="#475569", linestyle="--", linewidth=1, label="Valor = Mediana")
    ax.plot([0, max_val], [0, max_val * 2], color="#f59e0b", linestyle=":", linewidth=1, label="2× Mediana")
    ax.plot([0, max_val], [0, max_val * 3], color="#ef4444", linestyle=":", linewidth=1, label="3× Mediana")

    # Annotate top outliers
    indexed = sorted(enumerate(ratios), key=lambda x: x[1], reverse=True)
    for idx, _ in indexed[:5]:
        ax.annotate(
            labels[idx],
            (medianas[idx], valores[idx]),
            textcoords="offset points", xytext=(5, 5),
            fontsize=7, color="#cbd5e1",
        )

    ax.set_xlabel("Mediana da Categoria (R$)", color="#94a3b8")
    ax.set_ylabel("Valor do Contrato (R$)", color="#94a3b8")
    ax.set_title("Superfaturamento: Valor × Mediana por Categoria", color="#f1f5f9", fontsize=14, pad=15)
    ax.tick_params(colors="#94a3b8")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"R$ {x:,.0f}"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"R$ {x:,.0f}"))
    ax.legend(facecolor="#1e293b", edgecolor="#334155", labelcolor="#e2e8f0", fontsize=8)
    ax.set_facecolor("#0f172a")
    fig.patch.set_facecolor("#0f172a")

    plt.tight_layout()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = CHARTS_DIR / f"superfaturamentos_{ts}.png"
    plt.savefig(str(out_path), dpi=120, bbox_inches="tight", facecolor="#0f172a")
    plt.close()

    logger.info(f"Gráfico salvo: {out_path}")
    return out_path
