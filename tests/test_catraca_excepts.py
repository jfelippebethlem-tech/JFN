# -*- coding: utf-8 -*-
"""Catraca de `except Exception` — trava o CRESCIMENTO da dívida de erro engolido.

Não exige corrigir o legado: falha só se o total SUBIR além da baseline. Quando a
contagem cair (curadoria tipo dae25fe no Massare), abaixe a BASELINE p/ o novo valor —
a catraca só anda numa direção. Novo código: capturar exceção ESPECÍFICA, ou ao menos
logar (`logger.debug/warning`) — nunca `except Exception: pass` mudo (perda silenciosa,
lição da dívida de 1.404 ocorrências mapeada no MOC-Ecossistema 2026-06-24/07-07).
"""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE = 1392  # medido 2026-07-11 (curadoria: httpx/sqlite/PWError específicos; antes 1404)


def _contar() -> int:
    arquivos = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    total = 0
    for rel in arquivos:
        if rel.startswith("massare") or rel == "tests/test_catraca_excepts.py":
            continue  # massare tem catraca própria; este arquivo cita a string 4× (auto-referência)
        try:
            total += (REPO / rel).read_text(encoding="utf-8", errors="ignore").count("except Exception")
        except OSError:
            continue
    return total


def test_except_exception_nao_cresce():
    atual = _contar()
    assert atual <= BASELINE, (
        f"{atual} `except Exception` (baseline {BASELINE}): o novo código introduziu "
        f"{atual - BASELINE} captura(s) genérica(s). Capture a exceção específica ou logue o erro."
    )


def test_baseline_atualizada_quando_melhora():
    atual = _contar()
    folga = BASELINE - atual
    assert folga <= 25, (
        f"A contagem caiu para {atual} — abaixe BASELINE em tests/test_catraca_excepts.py "
        f"para {atual} e trave o ganho (catraca só anda numa direção)."
    )
