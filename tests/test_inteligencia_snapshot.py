# -*- coding: utf-8 -*-
"""
Snapshot de REFACTOR do relatório de inteligência — mesma receita do Lex
(tests/test_lex_snapshot.py): subprocess com PYTHONHASHSEED=0 e env SANITIZADO
(sem vazamento de NUCLEO_*/JFN_DB do conftest), golden byte a byte.

Regravar após mudança INTENCIONAL:
    PYTHONHASHSEED=0 python tools/inteligencia_snapshot_check.py --update
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_relatorio_inteligencia_snapshot_identico():
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "TZ")}
    env.update(PYTHONHASHSEED="0")
    proc = subprocess.run(
        [sys.executable, str(REPO / "tools" / "inteligencia_snapshot_check.py")],
        capture_output=True, text=True, env=env, cwd=str(REPO), timeout=300,
    )
    assert proc.returncode == 0, f"snapshot divergiu:\n{proc.stdout}\n{proc.stderr}"
