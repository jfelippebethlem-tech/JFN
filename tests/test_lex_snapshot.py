# -*- coding: utf-8 -*-
"""
Snapshot de REFACTOR do parecer Lex — garante que o texto do parecer (fornecedor e
órgão) não muda byte a byte com contexto sintético fixo e ambiente offline.

Roda tools/lex_snapshot_check.py em subprocess com PYTHONHASHSEED=0 (a ordem de
iteração de sets no parecer depende do hash de str — sem seed fixo o snapshot flakearia).
Para regravar os goldens após mudança INTENCIONAL de texto:
    PYTHONHASHSEED=0 python tools/lex_snapshot_check.py --update
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_parecer_lex_snapshot_identico(tmp_path):
    # Ambiente SANITIZADO: testes de outros módulos exportam env no import (NUCLEO_*, JFN_DB do
    # conftest, chaves de API) e vazariam pro subprocess, mudando seções do parecer vs golden.
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "TZ")}
    env.update(PYTHONHASHSEED="0", JFN_LEX_LER_SEI="0", JFN_LEX_DISCURSIVO="0")
    # 20/11/2026: o parecer lê caches de data/ (foto da sede, site próprio da fachada) e o snapshot
    # divergia SÓ na VM-1, que tem esses caches (a VM-2 não). Golden é teste: dados isolados.
    env["JFN_DATA_DIR"] = str(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(REPO / "tools" / "lex_snapshot_check.py")],
        capture_output=True, text=True, env=env, cwd=str(REPO), timeout=300,
    )
    assert proc.returncode == 0, f"snapshot divergiu:\n{proc.stdout}\n{proc.stderr}"
