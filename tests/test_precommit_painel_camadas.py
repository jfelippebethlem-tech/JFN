# -*- coding: utf-8 -*-
"""O gate que pula por CARGA não pode levar junto o gate seguinte.

`tools/precommit_painel.sh` tem duas camadas vivas: o `painel_boot_check` (percorre abas, falha em
`pageerror`) e o `painel_fila_check` (os dez painéis que só nascem de um CLIQUE — card que não
renderiza NÃO produz erro, some em silêncio). A segunda existe precisamente porque a primeira não
a alcança.

O DEFEITO (medido em 2026-08-11): as duas saídas de escape da camada viva — servidor fora e
`load > 3.0` — eram `exit 0`, e `exit 0` num script encerra o ARQUIVO, não o bloco. Numa VM de
2 vCPU a carga passa de 3 quase sempre (nesta sessão o próprio commit imprimiu `load 4.32 em
2 vCPU — pulei o boot_check`), então o gate do card-por-clique estava, na prática, DESLIGADO — e
o aviso impresso falava só do boot_check, de modo que o log dizia menos do que o script fazia.

Este teste lê o script como TEXTO de propósito: o que se quer garantir é estrutural — nenhum
`exit 0` entre o início da camada viva e o bloco da fila. Rodar o hook de verdade exigiria
servidor, Chrome e minutos; a regressão que interessa é a de uma linha.
"""
from __future__ import annotations

import re
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "precommit_painel.sh"


def _texto() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


def test_o_script_existe_e_e_o_gate_do_painel():
    t = _texto()
    assert "painel_boot_check" in t and "painel_fila_check" in t


def test_nenhum_exit_0_entre_a_camada_viva_e_o_gate_da_fila():
    """Se aparecer um `exit 0` no meio, o gate do clique morre calado — foi o bug de 2026-08-11."""
    t = _texto()
    i_viva = t.index("# ── 2.")
    i_fila = t.index("painel_fila_check")
    trecho = t[i_viva:i_fila]
    ofensores = [ln.strip() for ln in trecho.splitlines()
                 if re.match(r"^\s*exit\s+0\s*$", ln)]
    assert not ofensores, (
        "`exit 0` entre a camada viva e o gate da fila encerra o script inteiro: o "
        f"`painel_fila_check` nunca roda. Ofensores: {ofensores}")


def test_o_aviso_de_pulo_declara_as_duas_camadas():
    """Aviso que fala só do boot_check enquanto pula as duas é log que mente por omissão."""
    t = _texto()
    i_viva = t.index("# ── 2.")
    i_fila = t.index("painel_fila_check")
    avisos = [ln for ln in t[i_viva:i_fila].splitlines() if "⚠️" in ln]
    assert avisos, "a camada viva tem de AVISAR quando não mede"
    assert any("fila" in a.lower() or "clique" in a.lower() or "vivas" in a.lower()
               for a in avisos), (
        "o aviso precisa dizer que o gate do card-por-clique também ficou de fora; "
        f"hoje diz apenas: {avisos}")
