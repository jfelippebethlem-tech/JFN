# -*- coding: utf-8 -*-
"""Catraca em base de tolerância é catraca DESLIGADA.

Verificado em 2026-08-06: `tests/BASE-FALHAS-VM2.txt` listava
`test_catraca_excepts::test_except_exception_nao_cresce`, e o workflow passava as DUAS bases ao
`ci_delta`, que as une. Consequência: um commit que subisse `except Exception` de 1626 para 1700
falhava o teste e o CI o classificava como *"falha conhecida, tolerada"*. **A catraca existia e não
impedia nada.** O mesmo valia para `test_lex_snapshot` e `test_inteligencia_snapshot`, que rodam
sobre `tests/golden/snapshot_vazio.db` — versionado — e portanto não dependem do `compliance.db`
que falta no runner.

Este teste impede a recaída, e é `grep` puro: nenhum teste cujo nome anuncia catraca, golden ou
snapshot pode aparecer numa base de falhas conhecidas. Se um deles falhar por ambiente, a saída
certa é `skipif` honesto no próprio teste — não tolerância silenciosa (foi assim que 48 entradas
saíram da base do CI em 2026-08-02).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
BASES = ("tests/BASE-FALHAS-VM2.txt", "tests/BASE-FALHAS-CI.txt")

# o que NUNCA pode ser tolerado: o nome do arquivo denuncia a natureza do teste
_PROTEGIDOS = re.compile(r"test_(?:catraca|divida)_|_snapshot\.py|test_todo_\w+_tem_", re.I)

# EXCEÇÃO NOMINADA, com motivo. `golden_numbers` compara contra o `compliance.db` de 1,2 GB, que
# não é versionado e não existe no runner do GitHub — ali a falha é de AMBIENTE, e a tolerância é
# honesta. Fica só na base do CI; na da VM-2 não entra, porque a VM-2 tem o banco.
_TOLERADO_NO_CI = {"tests/test_golden_numbers.py"}


def _entradas(base: str) -> list[str]:
    p = RAIZ / base
    if not p.exists():
        return []
    fora = []
    for linha in p.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        fora.append(linha.removeprefix("FAILED ").removeprefix("ERROR ").strip())
    return fora


@pytest.mark.parametrize("base", BASES)
def test_nenhuma_catraca_esta_na_base_de_falhas_conhecidas(base):
    infratores = []
    for entrada in _entradas(base):
        arquivo = entrada.split("::")[0]
        if not _PROTEGIDOS.search(arquivo):
            continue
        if base.endswith("CI.txt") and arquivo in _TOLERADO_NO_CI:
            continue
        infratores.append(entrada)
    assert not infratores, (
        f"{base} tolera catraca — ela deixa de bloquear:\n  " + "\n  ".join(infratores)
        + "\n\nSe a falha for de ambiente, use `skipif` no próprio teste; tolerância silenciosa "
          "transforma o gate em decoração.")


def test_o_ci_nao_une_a_base_da_outra_maquina():
    """Cada base serve ao seu ambiente. Unir importa as falhas de ambiente da VM-2 para dentro da
    tolerância do runner — foi o que neutralizou as catracas."""
    wf = (RAIZ / ".github/workflows/testes.yml").read_text(encoding="utf-8")
    # ancorar na INVOCAÇÃO (`-m tools.ci_delta`), não na primeira menção — o cabeçalho do arquivo
    # explica o ci_delta em prosa, e a primeira versão deste teste casou o comentário.
    m = re.search(r"-m tools\.ci_delta(?:.|\n)*?(?=\n\s*-\s+name:|\Z)", wf)
    assert m, "não achei a invocação do ci_delta no workflow"
    trecho = m.group(0)
    assert "BASE-FALHAS-CI.txt" in trecho
    assert "BASE-FALHAS-VM2.txt" not in trecho, \
        "o CI voltou a unir a base da VM-2 — as catracas param de bloquear de novo"
