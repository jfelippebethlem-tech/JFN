# -*- coding: utf-8 -*-
"""O conversor de "falha de ambiente" em SKIP não pode virar tapete para regressão.

Em 2026-08-02 quatro testes reprovaram o CI por rodarem contra uma `compliance.db` VAZIA que o
próprio runner cria — falha de ambiente lida como regressão. O conftest passou a converter isso
em skip, mas **apenas quando a base comprovadamente não serve**. Estes testes travam as duas
metades da regra: reconhecer a base real e recusar a base de fachada.
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

# o conftest.py não é importável pelo nome (não está no sys.path como módulo) — carrega pelo
# caminho, que é o mesmo arquivo que o pytest usa em runtime.
_spec = importlib.util.spec_from_file_location(
    "jfn_conftest_sob_teste", Path(__file__).resolve().parent / "conftest.py")
conftest = importlib.util.module_from_spec(_spec)
sys.modules["jfn_conftest_sob_teste"] = conftest
_spec.loader.exec_module(conftest)


def _fabricar_base(tmp_path, n_tabelas: int, tamanho: int) -> str:
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    for i in range(n_tabelas):
        con.execute(f"create table t{i} (a text)")
    con.commit()
    con.close()
    with open(p, "ab") as f:                      # engorda até o tamanho pedido
        falta = tamanho - p.stat().st_size
        if falta > 0:
            f.write(b"\0" * falta)
    return str(p)


def test_base_criada_por_teste_nao_conta_como_utilizavel(tmp_path, monkeypatch):
    """Poucas tabelas e arquivo pequeno = base de fachada; o teste dependente deve poder pular."""
    alvo = _fabricar_base(tmp_path, n_tabelas=3, tamanho=4096)
    monkeypatch.setattr("compliance_agent.reporting.intel_base._DB", alvo, raising=False)
    assert conftest._base_utilizavel() is False


def test_base_real_e_reconhecida(tmp_path, monkeypatch):
    """Dezenas de tabelas e tamanho de produção = base real; falha aqui É regressão."""
    alvo = _fabricar_base(tmp_path, n_tabelas=30, tamanho=2_000_000)
    monkeypatch.setattr("compliance_agent.reporting.intel_base._DB", alvo, raising=False)
    assert conftest._base_utilizavel() is True


def test_base_ausente_nao_e_utilizavel(tmp_path, monkeypatch):
    monkeypatch.setattr("compliance_agent.reporting.intel_base._DB",
                        str(tmp_path / "nao_existe.db"), raising=False)
    assert conftest._base_utilizavel() is False


def test_sintomas_cobrem_os_erros_reais_de_base_ausente():
    """Os três erros que o SQLite dá quando a base não serve — vistos no runner em 2026-08-02."""
    assert "no such table" in conftest._SINTOMAS_SEM_BASE
    assert "no such column" in conftest._SINTOMAS_SEM_BASE
    assert "unable to open database file" in conftest._SINTOMAS_SEM_BASE


def test_na_vm_com_base_real_nada_e_convertido_em_skip():
    """Guarda contra o pior cenário: mascarar regressão na máquina que TEM os dados."""
    if not conftest._BASE_UTILIZAVEL:
        pytest.skip("esta máquina não tem a base real — nada a garantir aqui")
    assert conftest._BASE_UTILIZAVEL is True
