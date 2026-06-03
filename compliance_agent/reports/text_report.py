"""
Gerador de relatórios .txt para o agente de compliance.

Saída: reports/compliance_YYYY-MM-DD.txt
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Sequence


def _limpar(s: str) -> str:
    return (s or "").replace("\r", " ").strip()


def _severidade_label(sev: str) -> str:
    sev = (sev or "").lower()
    if sev == "alta":
        return "ALTA"
    if sev in ("media", "média"):
        return "MÉDIA"
    return "BAIXA"


def _alerta_linha(a: dict) -> str:
    return (
        f" - [{_severidade_label(a.get('severidade', ''))}] "
        f"{_limpar(a.get('tipo', '') or a.get('titulo', '') or a.get('tipo_alerta', ''))}\n"
        f"    {_limpar(a.get('titulo', '') or a.get('descricao', ''))}\n"
        f"    {_limpar(a.get('descricao', '') or '')}\n"
    )


def gerar_relatorio_txt(
    report: dict,
    alertas: Sequence[dict],
    output_dir: Path,
) -> Path:
    hoje = report.get("data") or datetime.now().strftime("%Y-%m-%d")
    linhas: list[str] = []
    linhas.append("=" * 60)
    linhas.append("JFN COMPLIANCE — RELATÓRIO DO DIA")
    linhas.append("=" * 60)
    linhas.append(f"Data: { hoje }")
    linhas.append(f"Gerado em: { datetime.now().strftime('%d/%m/%Y %H:%M') }")
    linhas.append("Estado do Rio de Janeiro")
    linhas.append("")

    # DOERJ
    doerj = (report.get("doerj") or {})
    linhas.append("-" * 60)
    linhas.append("DOERJ")
    linhas.append("-" * 60)
    linhas.append(f"Publicações: { doerj.get('total_publicacoes', 0) }")
    linhas.append(f"  Nomeações: { doerj.get('nomeacoes', 0) }")
    linhas.append(f"  Contratos: { doerj.get('contratos', 0) }")
    linhas.append(f"  Licitações: { doerj.get('licitacoes', 0) }")
    linhas.append("")

    # SIAFE / OBs
    siafe = (report.get("siafe_ob") or {})
    linhas.append("-" * 60)
    linhas.append("SIAFE2 / ORDENS BANCÁRIAS")
    linhas.append("-" * 60)
    linhas.append(f"Registros coletados: { siafe.get('records_fetched', 0) }")
    linhas.append(f"Registros salvos: { siafe.get('records_saved', 0) }")
    if siafe.get("errors"):
        linhas.append("Erros:")
        for err in siafe.get("errors", [])[:10]:
            linhas.append(f"  - {_limpar(str(err))}")
    linhas.append("")

    # Alertas
    alertas_lista = list(alertas or [])
    linhas.append("-" * 60)
    linhas.append("ALERTAS")
    linhas.append("-" * 60)
    linhas.append(f"Total: { len(alertas_lista) }")
    linhas.append(f"  Alta: { sum(1 for a in alertas_lista if (a.get('severidade') or '').lower() == 'alta') }")
    linhas.append(f"  Média: { sum(1 for a in alertas_lista if (a.get('severidade') or '').lower() in ('media', 'média')) }")
    linhas.append(f"  Baixa: { sum(1 for a in alertas_lista if (a.get('severidade') or '').lower() == 'baixa') }")
    linhas.append("")
    for a in alertas_lista[:200]:
        linhas.append(_alerta_linha(a))
    linhas.append("")
    linhas.append("=" * 60)
    linhas.append("Confidencial — Uso Restrito")
    linhas.append("=" * 60)

    out_path = Path(output_dir) / f"compliance_{hoje}.txt"
    out_path.write_text("\n".join(linhas), encoding="utf-8")
    return out_path
