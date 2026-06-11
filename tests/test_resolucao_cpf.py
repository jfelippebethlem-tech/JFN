# -*- coding: utf-8 -*-
"""Testes da resolução de CPF mascarado (nome + 6 díg do meio → CPF completo), técnica br-acc.

Determinísticos: montam um SQLite temporário com `ordens_bancarias` (favorecido_cpf/nome) e exercem
o match 1:1, a guarda de ambiguidade, a normalização de acentos e o reconhecimento da máscara."""
import sqlite3

from compliance_agent.resolucao_cpf import middle6, resolver


def _db(tmp_path, linhas):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ordens_bancarias (favorecido_cpf TEXT, favorecido_nome TEXT)")
    con.executemany("INSERT INTO ordens_bancarias VALUES (?,?)", linhas)
    con.commit()
    con.close()
    return p


def test_middle6_extrai_so_da_mascara():
    assert middle6("***912137**") == "912137"
    assert middle6("***.912.137-**") == "912137"
    assert middle6("12345678901") == ""   # CPF limpo NÃO é máscara
    assert middle6("") == ""


def test_resolve_par_unico(tmp_path):
    # CPF 11122334455 → 6 do meio (pos 4-9) = 223344
    p = _db(tmp_path, [("11122334455", "JOAO DA SILVA"), ("99988877766", "OUTRO NOME")])
    out = resolver("JOAO DA SILVA", "***223344**", db_path=p)
    assert out["resolvido"] and out["cpf"] == "11122334455"
    assert out["confianca"] == 0.85


def test_acento_normalizado(tmp_path):
    p = _db(tmp_path, [("11122334455", "JOÃO DA SILVA")])  # base com acento
    out = resolver("joao da silva", "***223344**", db_path=p)  # consulta sem acento/minúscula
    assert out["resolvido"] and out["cpf"] == "11122334455"


def test_ambiguidade_nao_resolve(tmp_path):
    # mesmo nome + mesmo middle6 em 2 CPFs distintos → não resolve (honesto)
    p = _db(tmp_path, [("11122334455", "JOSE SANTOS"), ("88822334400", "JOSE SANTOS")])
    out = resolver("JOSE SANTOS", "***223344**", db_path=p)
    assert not out["resolvido"] and "ambíguo" in out["motivo"]


def test_sem_correspondencia(tmp_path):
    p = _db(tmp_path, [("11122334455", "JOAO DA SILVA")])
    out = resolver("MARIA SOUZA", "***223344**", db_path=p)
    assert not out["resolvido"] and "sem correspondência" in out["motivo"]


def test_doc_nao_mascarado_nao_resolve(tmp_path):
    p = _db(tmp_path, [("11122334455", "JOAO DA SILVA")])
    out = resolver("JOAO DA SILVA", "11122334455", db_path=p)  # sem '*' → não é máscara
    assert not out["resolvido"]
