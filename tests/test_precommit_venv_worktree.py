# -*- coding: utf-8 -*-
"""Gate do pre-commit não pode se desligar calado num worktree de agente.

O DEFEITO (medido em 23/11/2026, commit bfcb5731 de 22/11): o agente commitou de
`.claude/worktrees/agent-…`, que não tem `.venv` — o venv mora só na árvore principal. O hook imprimiu
`validate/gen capabilities falhou` (o `.venv/bin/python` relativo não existia; o hook local já foi corrigido às
12:58 de 22/11 para achar o venv pelo `git rev-parse --git-common-dir`) e, na linha seguinte,
`ruff ausente — gate de lint NÃO rodou`: o gate que BLOQUEIA (tools/precommit_ruff.sh) e o do painel
(tools/precommit_painel.sh) procuravam o venv só em `$root/.venv` e, no worktree, saíam com `exit 0`.

Controle positivo: um ruff de mentira no `.venv` da árvore principal que REPROVA tudo; commitado do worktree, o
gate tem de bloquear (rc 1). Controle negativo: o mesmo ruff aprovando → rc 0.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_RUFF_SH = _REPO / "tools" / "precommit_ruff.sh"
_PAINEL_SH = _REPO / "tools" / "precommit_painel.sh"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture()
def worktree(tmp_path):
    """Repo com `.venv/bin/ruff` de mentira na árvore principal e um worktree sem `.venv` com um .py staged."""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q")
    _git(main, "config", "user.email", "t@t")
    _git(main, "config", "user.name", "t")
    (main / "a.py").write_text("x = 1\n")
    _git(main, "add", "a.py")
    _git(main, "commit", "-qm", "init")
    venv = main / ".venv" / "bin"
    venv.mkdir(parents=True)
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", str(wt))
    (wt / "b.py").write_text("y = 2\n")
    _git(wt, "add", "b.py")
    return main, wt, venv


def _ruff_falso(venv: Path, rc: int) -> None:
    f = venv / "ruff"
    f.write_text(f"#!/bin/sh\necho 'RUFF-FALSO $*'\nexit {rc}\n")
    f.chmod(0o755)


def _rodar(script: Path, cwd: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PATH"] = "/usr/bin:/bin"            # sem ruff de sistema: só o do venv conta
    return subprocess.run(["bash", str(script)], cwd=cwd, env=env, capture_output=True, text=True, timeout=60)


def test_ruff_do_venv_principal_bloqueia_commit_do_worktree(worktree):
    _, wt, venv = worktree
    _ruff_falso(venv, 1)
    r = _rodar(_RUFF_SH, wt)
    assert "ruff ausente" not in r.stderr, r.stderr
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)


def test_controle_negativo_ruff_aprova_e_o_commit_passa(worktree):
    _, wt, venv = worktree
    _ruff_falso(venv, 0)
    r = _rodar(_RUFF_SH, wt)
    assert r.returncode == 0 and "ruff ausente" not in r.stderr, (r.returncode, r.stderr)


def test_sem_venv_em_lugar_nenhum_o_aviso_continua_visivel(worktree):
    """INDISPONÍVEL ≠ limpo: sem ruff nenhum o gate não bloqueia, mas AVISA."""
    _, wt, _ = worktree
    r = _rodar(_RUFF_SH, wt)
    assert r.returncode == 0 and "ruff ausente" in r.stderr


def test_gate_do_painel_acha_o_venv_pelo_common_dir():
    """O painel precisa de servidor e Chrome para rodar de verdade; aqui a regressão é estrutural: o python vem
    do `.venv` da árvore principal (git-common-dir) quando o worktree não tem o seu."""
    t = _PAINEL_SH.read_text(encoding="utf-8")
    i = t.index('py="$root/.venv/bin/python"')
    trecho = t[i:t.index("venv ausente", i)]
    assert "git-common-dir" in trecho, trecho
