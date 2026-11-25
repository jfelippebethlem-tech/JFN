# -*- coding: utf-8 -*-
"""Catraca do gene `vm-nao-crashar` (O8.4 — genes com validação executável): nenhum script versionado roda a suíte
INTEIRA de uma vez (`pytest tests`, `pytest tests/`).

A suíte monolítica já derrubou a VM-1 4× (CLAUDE.md regra 8; memória vm-nao-crashar): a suíte roda em lotes
(`tools/ci_lote.py`) e na VM-2/it-campo (`tools/testar_na_vm2.sh`, `tools/portao.py`). Um cron, hook ou script novo
que chame `pytest tests` volta a pôr a máquina inteira no chão — este teste pega na hora. Medido em 24/11/2026: 0.
A PROVA (regra COR-15): o padrão acusa o defeito injetado e deixa passar o alvo explícito.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
# `pytest` (ou `-m pytest`) seguido só de opções e do diretório `tests` inteiro
MONOLITICA = re.compile(r"pytest(?:\s+-{1,2}[\w=:.-]+(?:\s+(?!tests\b)[\w=:.-]+)?)*\s+[\"']?tests/?[\"']?(?=\s|$|[\"';)|&])")
ONDE = ("tools/", "deploy/", ".githooks/", "config/", "scripts/")
EXT = (".sh", ".py", ".service", ".timer", ".yaml", ".yml", ".cron", ".xml", ".ps1")


def _versionados() -> list[Path]:
    saida = subprocess.run(["git", "ls-files", *ONDE], cwd=RAIZ, capture_output=True, text=True, check=True).stdout
    return [RAIZ / p for p in saida.splitlines() if p.endswith(EXT) and not p.startswith("tools/_arquivo/")]


def achar(texto: str) -> list[str]:
    return [ln.strip()[:160] for ln in texto.splitlines() if MONOLITICA.search(ln)]


def test_nenhum_script_roda_a_suite_monolitica():
    achados = {str(p.relative_to(RAIZ)): a for p in _versionados() if p.exists()
               and (a := achar(p.read_text(encoding="utf-8", errors="replace")))}
    assert not achados, ("suíte inteira de uma vez derruba a VM (memória vm-nao-crashar) — use tools/ci_lote.py "
                         f"em lotes, na VM-2 (tools/testar_na_vm2.sh): {achados}")


def test_prova_o_padrao_acusa_o_defeito_e_poupa_o_alvo():
    for ruim in ("python -m pytest tests -q", "pytest tests/", ".venv/bin/python -m pytest -q -x tests",
                 "timeout 900 pytest -p no:cacheprovider tests/ >> log", "pytest 'tests'"):
        assert achar(ruim), ruim
    for bom in ("pytest tests/test_x.py -q", "python -m pytest $(python -m tools.ci_lote 1 4)",
                "pytest -q tests/test_a.py tests/test_b.py", "# a suíte em tests/ roda em lotes"):
        assert not achar(bom), bom
