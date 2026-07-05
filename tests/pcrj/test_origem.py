# -*- coding: utf-8 -*-
"""Testes do decodificador de origem (título de eleitor → UF; CPF → região fiscal)."""
from compliance_agent.pcrj.origem import (
    origem_fora_do_rj,
    regiao_do_cpf,
    uf_do_titulo,
)


def test_uf_do_titulo_rj():
    # dígitos 9-10 = '03' → RJ (exemplos reais do consulta_cand 2016)
    assert uf_do_titulo("045964990388") == "RJ"
    assert uf_do_titulo("065856750396") == "RJ"


def test_uf_do_titulo_fora():
    # '039514781015' → dígitos 9-10 = '10' → GO
    assert uf_do_titulo("039514781015") == "GO"


def test_uf_do_titulo_invalido():
    assert uf_do_titulo("") == ""
    assert uf_do_titulo("123") == ""
    assert uf_do_titulo("-4") == ""


def test_regiao_do_cpf():
    # 9º dígito 7 = região fiscal RJ/ES
    assert "RJ" in regiao_do_cpf("11111111711")
    assert regiao_do_cpf("11111111811") == ["SP"]
    assert regiao_do_cpf("") == []
    assert regiao_do_cpf("123") == []


def test_origem_fora_do_rj():
    assert origem_fora_do_rj(titulo="039514781015")[0] is True     # GO
    assert origem_fora_do_rj(titulo="045964990388")[0] is False    # RJ
    assert origem_fora_do_rj(uf_nascimento="SP")[0] is True
    assert origem_fora_do_rj(uf_nascimento="RJ")[0] is False
    assert origem_fora_do_rj()[0] is False                          # sem dado ≠ fora
