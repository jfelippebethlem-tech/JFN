# -*- coding: utf-8 -*-
"""Contrato acima do teto do porte (espelho de contratos do TCE-RJ).

O que estes testes protegem: o teto é POR PORTE (ME R$ 360 mil, EPP R$ 4,8 mi) e a lente mede
CONTRATO CELEBRADO, não pagamento. Trocar o teto ou passar a medir o pago transforma esta lente
na irmã `porte_incompativel` — e a casa perderia justamente o critério que a lei usa.
"""
import sqlite3

from tools.contrato_acima_do_porte import TETO_ANUAL, acima_do_porte


def _banco():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE empresas_cadastro (cnpj_basico TEXT, porte_txt TEXT, capital_social REAL)")
    con.execute("CREATE TABLE contratos_tcerj (processo TEXT, data_contratacao TEXT, unidade TEXT,"
                " valor_contrato REAL, cnpj TEXT, fornecedor TEXT, status TEXT)")
    return con


def test_tetos_sao_os_da_LC123():
    assert TETO_ANUAL == {"Microempresa": 360_000.0, "Empresa de Pequeno Porte": 4_800_000.0}


def test_microempresa_acima_do_teto_entra():
    con = _banco()
    con.execute("INSERT INTO empresas_cadastro VALUES ('11111111','Microempresa',100000)")
    con.execute("INSERT INTO contratos_tcerj VALUES ('P1','2023-03-20','SES',87e6,"
                "'11111111000155','MAJU','Ativo')")
    r = acima_do_porte(con)
    assert len(r) == 1
    assert round(r[0]["razao_teto"]) == 242, "a razão contra o teto de ME mudou"


def test_abaixo_do_teto_do_proprio_porte_nao_entra():
    """EPP com R$ 4 mi está DENTRO do seu teto — marcar seria falso positivo."""
    con = _banco()
    con.execute("INSERT INTO empresas_cadastro VALUES ('11111111','Empresa de Pequeno Porte',1e6)")
    con.execute("INSERT INTO contratos_tcerj VALUES ('P1','2023-01-01','X',4e6,"
                "'11111111000155','EPP OK','Ativo')")
    assert acima_do_porte(con) == []


def test_porte_grande_fica_de_fora():
    """Quem não é ME/EPP não tem teto de porte — a lente não se aplica."""
    con = _banco()
    con.execute("INSERT INTO empresas_cadastro VALUES ('11111111','Demais',1e6)")
    con.execute("INSERT INTO contratos_tcerj VALUES ('P1','2023-01-01','X',87e6,"
                "'11111111000155','GRANDE','Ativo')")
    assert acima_do_porte(con) == []


def test_soma_por_empresa_e_maior_contrato():
    con = _banco()
    con.execute("INSERT INTO empresas_cadastro VALUES ('11111111','Microempresa',100000)")
    for v in (1e6, 5e6):
        con.execute("INSERT INTO contratos_tcerj VALUES ('P','2023-01-01','X',?,"
                    "'11111111000155','X','Ativo')", (v,))
    r = acima_do_porte(con)[0]
    assert r["n_contratos"] == 2 and r["soma_contratada"] == 6e6 and r["maior"] == 5e6


def test_min_razao_filtra():
    con = _banco()
    con.execute("INSERT INTO empresas_cadastro VALUES ('11111111','Microempresa',100000)")
    con.execute("INSERT INTO contratos_tcerj VALUES ('P','2023-01-01','X',1e6,"
                "'11111111000155','X','Ativo')")
    assert len(acima_do_porte(con, min_razao=1)) == 1      # 2,8x o teto
    assert acima_do_porte(con, min_razao=10) == []


def test_contrato_sem_valor_nao_entra():
    """Valor nulo é ausência de dado — não vira zero nem presunção."""
    con = _banco()
    con.execute("INSERT INTO empresas_cadastro VALUES ('11111111','Microempresa',100000)")
    con.execute("INSERT INTO contratos_tcerj VALUES ('P','2023-01-01','X',NULL,"
                "'11111111000155','X','Ativo')")
    assert acima_do_porte(con) == []
