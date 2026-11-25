# -*- coding: utf-8 -*-
"""O8.4 — RETOMADA gerada: as seções de estado saem do backlog + quadro + git; o texto escrito à mão fica byte a byte."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import retomada_gerar as R  # noqa: E402

MANUAL = "---\natualizado: x\n---\n\n# RETOMADA\n\n## 2. Decisões do dono\n- só RJ\n\n## 3. Feito\n- O8.1 ✅\n"
BLOCOS = {"backlog": "B1", "quadro": "Q1", "git": "G1"}


def test_sem_marcadores_acrescenta_secao_e_preserva_o_manual():
    novo = R.substituir_blocos(MANUAL, BLOCOS, "24/11/2026 23:00")
    assert novo.startswith(MANUAL.rstrip("\n"))                       # nada do que é escrito à mão muda
    assert "## 7. Estado gerado (24/11/2026 23:00;" in novo
    for nome, corpo in BLOCOS.items():
        assert f"<!-- gerado:{nome} -->\n{corpo}\n<!-- /gerado:{nome} -->" in novo


def test_regenerar_troca_so_o_miolo_e_e_idempotente():
    um = R.substituir_blocos(MANUAL, BLOCOS, "24/11/2026 23:00")
    mao = um.replace("- só RJ", "- só RJ (editado à mão depois)")      # o dono escreve fora dos blocos
    dois = R.substituir_blocos(mao, {"backlog": "B2", "quadro": "Q1", "git": "G1"}, "25/11/2026 08:00")
    assert "- só RJ (editado à mão depois)" in dois and "B2" in dois and "B1" not in dois
    assert dois.count("## 7. Estado gerado") == 1 and "25/11/2026 08:00" in dois
    assert R.substituir_blocos(dois, {"backlog": "B2", "quadro": "Q1", "git": "G1"}, "25/11/2026 08:00") == dois


def test_so_o_carimbo_nao_conta_como_mudanca():
    a = R.substituir_blocos(MANUAL, BLOCOS, "24/11/2026 23:00")
    b = R.substituir_blocos(a, BLOCOS, "24/11/2026 23:05")
    assert a != b and not R.mudou(a, b)
    assert R.mudou(a, R.substituir_blocos(a, {**BLOCOS, "git": "G2"}, "24/11/2026 23:05"))


def test_marcador_quebrado_nao_adivinha():
    with pytest.raises(ValueError):
        R.substituir_blocos(MANUAL + "<!-- gerado:git -->\nx\n", BLOCOS, "c")


def test_backlog_conta_e_lista_prontos_pelas_dependencias():
    itens = [{"id": "A", "estado": "feito", "titulo": "a"},
             {"id": "B", "dep": ["A"], "estado": "pendente", "titulo": "b", "maq": "vm1"},
             {"id": "C", "dep": ["B"], "estado": "pendente", "titulo": "c"},
             {"id": "D", "estado": "bloqueado_dono", "titulo": "d", "nota": "senha"},
             {"id": "E", "estado": "em_curso", "titulo": "e"}]
    t = R.render_backlog(itens)
    assert "pendente 2" in t and "feito 1" in t and "total 5" in t
    prontos = t.split("Prontos")[1]
    assert "`B`" in prontos and "`C`" not in prontos                  # C depende de B, que não terminou
    assert "`D`" in t.split("Bloqueado pelo dono")[1] and "senha" in t


def test_frente_do_quadro_e_git_sem_upstream():
    f = R.ler_frente("projeto: JFN\noque: O8.4\nmaquina: vm1\ndesde: 2026-11-24\n\n> n1\n> n2 última\n", "x-1")
    assert f["projeto"] == "JFN" and f["ultima"] == "n2 última"
    assert "`x-1` JFN — O8.4" in R.render_quadro([f])
    assert "INDISPONÍVEL" in R.render_git("feat/x", None, ["abc 24/11 msg"])  # sem upstream ≠ 0 commits


def test_gravar_atomico_e_so_quando_muda(tmp_path):
    p = tmp_path / "RETOMADA.md"
    p.write_text(MANUAL, encoding="utf-8")
    novo = R.substituir_blocos(MANUAL, BLOCOS, "c1")
    assert R.gravar(p, novo) is True and p.read_text(encoding="utf-8") == novo
    assert R.gravar(p, R.substituir_blocos(novo, BLOCOS, "c2")) is False   # só o carimbo: não regrava
    assert not list(tmp_path.glob(".*gerando"))
