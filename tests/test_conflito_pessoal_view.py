# -*- coding: utf-8 -*-
"""Teste do cruzamento sócio × folha do Estado (conflito de pessoal) por nome + 5 dígitos (posições 4-8).
QSA mascara posições 4-9 (***.XXX.XXX-**); folha mascara 3-8 (XX######XXX); a sobreposição = posições 4-8."""
import sqlite3

from compliance_agent.reporting import conflito_pessoal_view as cp


def _db(tmp_path, socios, folha):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE socios_fornecedor (cnpj TEXT, razao TEXT, socio_nome TEXT, "
                "socio_nome_norm TEXT, socio_doc TEXT, qualificacao TEXT)")
    con.executemany("INSERT INTO socios_fornecedor VALUES (?,?,?,?,?,?)", socios)
    con.execute("CREATE TABLE registros_folha (cpf TEXT, nome TEXT, orgao_nome TEXT, cargo TEXT, "
                "vinculo TEXT, competencia TEXT)")
    con.executemany("INSERT INTO registros_folha VALUES (?,?,?,?,?,?)", folha)
    con.commit(); con.close()
    return p


def test_match_nome_e_5_digitos(tmp_path):
    # QSA '***223344**' (middle6=223344, pos4-8=22334) casa folha 'XX122334XXX' (digitos 122334, pos4-8=22334)
    socios = [("C1", "ALFA", "JOAO ADM", "JOAO ADM", "***223344**", "Administrador")]
    folha = [("XX122334XXX", "JOAO ADM", "SES-RJ", "Médico", "Estatutário", "2025-06")]
    p = _db(tmp_path, socios, folha)
    agg = cp.por_fornecedor("C1", db_path=p)
    assert agg["n_socios"] == 1 and agg["n_na_folha"] == 1
    assert agg["itens"][0]["orgao"] == "SES-RJ" and agg["itens"][0]["cargo"] == "Médico"
    assert "conflito de pessoal" in cp.leitura(agg).lower() and "8.429" in cp.leitura(agg)


def test_afastado_nome_diferente(tmp_path):
    socios = [("C1", "ALFA", "MARIA SOUZA", "MARIA SOUZA", "***223344**", "Sócio")]
    folha = [("XX122334XXX", "JOAO ADM", "SES", "X", "Y", "2025")]  # mesmos dígitos, nome diferente → não casa
    p = _db(tmp_path, socios, folha)
    agg = cp.por_fornecedor("C1", db_path=p)
    assert agg["n_socios"] == 1 and agg["n_na_folha"] == 0
    assert "AFASTADO" in cp.leitura(agg)


def test_afastado_digitos_diferentes(tmp_path):
    socios = [("C1", "ALFA", "JOAO ADM", "JOAO ADM", "***999999**", "Sócio")]
    folha = [("XX122334XXX", "JOAO ADM", "SES", "X", "Y", "2025")]  # mesmo nome, dígitos diferentes → não casa
    p = _db(tmp_path, socios, folha)
    assert cp.por_fornecedor("C1", db_path=p)["n_na_folha"] == 0


def test_indisponivel_sem_qsa_mascarado(tmp_path):
    socios = [("C1", "ALFA", "", "", "***223344**", "Sócio")]  # sem nome → não entra
    p = _db(tmp_path, socios, [])
    agg = cp.por_fornecedor("C1", db_path=p)
    assert agg["n_socios"] == 0 and "INDISPONÍVEL" in cp.leitura(agg)


def test_vazio_sem_cnpjs():
    assert cp.por_cnpjs([]) == cp._vazio()
