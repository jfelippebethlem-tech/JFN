# -*- coding: utf-8 -*-
"""Teste do cruzamento sócio resolvido × folha do Estado (conflito de pessoal). DB temp, sem rede."""
import sqlite3

from compliance_agent.reporting import conflito_pessoal_view as cp


def _db(tmp_path, socios, beneficios, folha):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE socios_fornecedor (cnpj TEXT, razao TEXT, socio_nome TEXT, "
                "socio_nome_norm TEXT, socio_doc TEXT, qualificacao TEXT)")
    con.executemany("INSERT INTO socios_fornecedor VALUES (?,?,?,?,?,?)", socios)
    con.execute("CREATE TABLE socio_beneficio (socio_nome_norm TEXT, socio_doc TEXT, resolvido INT, cpf_resolvido TEXT)")
    con.executemany("INSERT INTO socio_beneficio VALUES (?,?,?,?)", beneficios)
    con.execute("CREATE TABLE registros_folha (cpf TEXT, nome TEXT, orgao_nome TEXT, cargo TEXT, "
                "vinculo TEXT, competencia TEXT)")
    con.executemany("INSERT INTO registros_folha VALUES (?,?,?,?,?,?)", folha)
    con.commit(); con.close()
    return p


def test_indicio_socio_na_folha(tmp_path):
    socios = [("C1", "ALFA", "JOAO ADM", "JOAO ADM", "***111111**", "Administrador")]
    beneficios = [("JOAO ADM", "***111111**", 1, "11122334455")]
    folha = [("11122334455", "JOAO ADM", "SES-RJ", "Médico", "Estatutário", "2025-06")]
    p = _db(tmp_path, socios, beneficios, folha)
    agg = cp.por_fornecedor("C1", db_path=p)
    assert agg["n_resolvidos"] == 1 and agg["n_na_folha"] == 1
    assert agg["itens"][0]["orgao"] == "SES-RJ" and agg["itens"][0]["cargo"] == "Médico"
    txt = cp.leitura(agg)
    assert "conflito de pessoal" in txt.lower() and "8.429" in txt


def test_afastado_quando_resolvido_mas_fora_da_folha(tmp_path):
    socios = [("C1", "ALFA", "MARIA", "MARIA", "***222222**", "Sócio")]
    beneficios = [("MARIA", "***222222**", 1, "99988877766")]
    p = _db(tmp_path, socios, beneficios, [])
    agg = cp.por_fornecedor("C1", db_path=p)
    assert agg["n_resolvidos"] == 1 and agg["n_na_folha"] == 0
    assert "AFASTADO" in cp.leitura(agg)


def test_indisponivel_sem_resolvidos(tmp_path):
    socios = [("C1", "ALFA", "PEDRO", "PEDRO", "***333333**", "Sócio")]
    beneficios = [("PEDRO", "***333333**", 0, "")]  # não resolvido
    p = _db(tmp_path, socios, beneficios, [])
    agg = cp.por_fornecedor("C1", db_path=p)
    assert agg["n_resolvidos"] == 0 and "INDISPONÍVEL" in cp.leitura(agg)


def test_vazio_sem_cnpjs():
    assert cp.por_cnpjs([]) == cp._vazio()
