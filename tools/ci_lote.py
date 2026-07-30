#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fatia determinística da suíte — o lote k de n, sempre igual em qualquer máquina.

POR QUE EXISTE. A suíte monolítica **já derrubou esta VM quatro vezes** (entre 47% e 66%, com sweep e
Chromium disputando 2 vCPU). O protocolo da casa é rodar em 3-4 lotes, e até agora isso era feito à
mão com `ls | sed -n '1,120p'` — o que muda de resultado se um arquivo novo entra no meio, e aí "o
lote 2" de hoje não é o de ontem. Sem fatia determinística não há como comparar rodada com rodada.

Fatiamento por ARQUIVO (nunca por teste), ordenado, round-robin — round-robin em vez de blocos
contíguos porque os arquivos pesados se concentram por diretório (`tests/detectores`, `tests/pcrj`) e
blocos contíguos jogariam todo o peso num lote só.

Uso:
    python -m tools.ci_lote 1 4                 # imprime os arquivos do lote 1 de 4
    pytest -q -rf $(python -m tools.ci_lote 1 4)
"""
from __future__ import annotations

import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent


def arquivos() -> list[str]:
    """Todo `test_*.py` sob `tests/`, ordenado — a ordem é a chave do determinismo."""
    achados = sorted(p.relative_to(_RAIZ).as_posix()
                     for p in (_RAIZ / "tests").rglob("test_*.py"))
    return achados


def lote(k: int, n: int) -> list[str]:
    if not (1 <= k <= n):
        raise SystemExit(f"lote inválido: {k} de {n}")
    return [f for i, f in enumerate(arquivos()) if i % n == (k - 1)]


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    print(" ".join(lote(int(sys.argv[1]), int(sys.argv[2]))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
