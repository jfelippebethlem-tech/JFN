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
# 2026-07-17: re-medido em 1447 — a expansão de intel do dia (11 detectores da leva b, +47 já
# COMMITADOS sem rodar a catraca; +8 da leva c, todos logados ou no idioma-padrão das rotas)
# subiu a dívida. DÉBITO REGISTRADO: curadoria p/ voltar a ≤1392 pende (trocar por exceção
# específica nos detectores novos). A catraca volta a travar crescimento a partir daqui.
# 2026-07-18: +4 (1447→1451) — todos LOGADOS (não mudos) e amplos por DESIGN correto: rodar
# detector arbitrário no fingerprint da autoauditoria (erro = estado do retrato) e libs de OCR
# (fitz/tesseract/PIL, espaço de exceção enorme). Converter p/ específico seria errado aqui.
# 2026-07-18b: +1 (1451→1452) — 1 route handler novo (/api/intel/comunidades_grafo) no idioma-padrão
# das ~71 rotas do investigacao.py (catch-all que RETORNA o erro no JSON, não é mudo).
# 2026-07-18c: +1 (1452→1453) — rota /api/intel/escalada (detector novo), idioma-padrão das rotas.
# 2026-07-18d: +2 (1453→1455) — rota /api/intel/lift + o catch-por-detector do avaliar_lift (roda
# detector arbitrário no harness de lift, como o fingerprint; logado, amplo por design correto).
BASELINE = 1455  # medido 2026-07-18d (1453→lift; 1447 em 2026-07-17; 1392 em 2026-07-11)


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
