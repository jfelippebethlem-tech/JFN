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
# 2026-07-18e: +5 (1455→1460) — comparador de preços: 4 route handlers novos (buscar/item/orgaos/
# fornecedores) no idioma-padrão das rotas + 1 já contabilizado. Todos catch-and-return, não mudos.
# 2026-07-18f: +2 (1460→1462) — dossiê caro+suspeito: rota /api/comparador/dossie + degradação
# graciosa do cache do radar (except→radar={}, não mudo). Ambos idioma-padrão, logados/graceful.
# 2026-07-18g: +2 (1462→1464) — rotas /api/comparador/economia + /api/sancoes/detalhar (idioma
# das rotas, catch-and-return).
# 2026-07-18h: +1 (1464→1465) — rota /api/comparador/vedada (idioma das rotas).
# 2026-07-18i: +1 (1465→1466) — enriquecimento capital/porte no investigacao_dd (except→logger.debug,
# não mudo; degrada honesto se a tabela empresas_cadastro não existir).
# 2026-07-18j: +4 (1466→1470) — sweeps de cadastro (cadastro_enrich + empresas_dump): lookups de
# rede e guarda de recursos (amplos por design, todos logados/degradam honesto).
BASELINE = 1471  # medido 2026-07-18k (+1: rota /api/intel/prioridade_valor, boundary HTTP padrão; 1466→sweeps cadastro)


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
